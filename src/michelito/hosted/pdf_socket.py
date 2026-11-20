"""The PDF worker in its own container: a Unix socket between the hosted app and `pdfworker`.

In production (`deploy/docker-compose.yml`) uploaded PDFs are not opened in the hosted app's
container at all. A separate `pdfworker` container (same image, `michelito pdf-worker`) runs with
**no secrets, no data volume, no network**, a read-only file system and no capabilities; its only
shared mount is the folder holding this socket. For each request it runs the usual limited
worker process (`pdf_worker._run`: memory, CPU, wall-clock, page and word caps) and returns only
its answer (the positioned words, or why it could not read them). A pdfminer exploit that escaped
those limits would land in a container that holds nothing: no master key, no accounts database,
no other account's data, and no way out.

The hosted app uses it when `MICHELITO_PDF_WORKER_SOCKET` names the socket; without it (local
development, tests) the worker process is started next to the app, as before.

Inside the container, three identities (`drop_privileges`, run once at start as root):

- the **server** (`--server-uid`, 10002) binds the socket in a folder it owns, mode 0750, whose
  group is the hosted app's (`--client-gid`, 10001); the socket is 0660. Only the server can
  remove or replace it; the hosted app can only connect.
- every **worker process** (one per file, fresh each time) runs as one uid of a pool starting
  at `--child-uid` (10003, as many as `--slots`; two workers running at once never share one, a
  uid is reused only after its worker was reaped), with no supplementary groups, and makes itself
  non-dumpable before reading anything (`pdf_worker._not_dumpable`): it cannot even enter the
  socket's folder, cannot signal or trace the
  server, and can write nowhere (it starts in a fresh, empty folder of the server's, mode 0711,
  removed after the file; the container's file system is read-only and /tmp is root's 0711).
- root is only kept as the server's *saved* user id, so it can start, stop and clean those
  workers (the SETUID, SETGID and KILL capabilities; CHOWN only serves the set-up).

The hosted app checks who holds the socket (`SO_PEERCRED`): its user id must be
`MICHELITO_PDF_WORKER_UID`, else nothing is sent and a data-free error is logged. One request per
connection; each one is served by a forked process that exits after its reply, so no PDF or
password outlives it.

    request:  one JSON line {"password": n, "size": m, "limits": {...}}, then n bytes of
              password (UTF-8) and m bytes of PDF
    response: one JSON line {"status": "ok" | "time" | "memory" | "output" | "unreadable" |
              "bad"}, then (for "ok") the worker's answer

The password and the PDF only travel over the socket (never on a command line, in the
environment or on disk); nothing here logs them.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import socketserver
import struct
import threading
from dataclasses import dataclass, fields
from pathlib import Path

from michelito.hosted import pdf_worker
from michelito.hosted.pdf_worker import Limits, TooComplex, Unreadable

SOCKET_ENV = "MICHELITO_PDF_WORKER_SOCKET"
UID_ENV = "MICHELITO_PDF_WORKER_UID"
LOG = logging.getLogger(__name__)
MAX_HEADER = 1024
MAX_PASSWORD = 1024
MAX_PDF = 64 * 1024 * 1024
_MAXIMA = Limits()  # a request may ask for tighter limits, never looser ones


class WorkerUnavailable(Exception):
    """The worker container could not be reached (the upload fails; nothing is opened here)."""


def socket_path() -> Path | None:
    text = os.environ.get(SOCKET_ENV, "").strip()
    return Path(text) if text else None


def expected_uid() -> int | None:
    text = os.environ.get(UID_ENV, "").strip()
    return int(text) if text.isdigit() else None


def peer_uid(conn: socket.socket) -> int:
    """The user id of the process that listens on the other end (`SO_PEERCRED`)."""
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _, uid, _ = struct.unpack("3i", raw)
    return int(uid)


def _check_peer(conn: socket.socket) -> None:
    expected = expected_uid()
    found = peer_uid(conn)
    if expected is None or found != expected:
        # For the owner: someone else holds the socket (a compromised worker?). No data.
        LOG.error(
            "the PDF worker socket is held by uid %d, not the expected %s: nothing was sent",
            found,
            expected,
        )
        raise WorkerUnavailable("unexpected peer")


# The hosted app's side.


def _read_line(conn: socket.socket, limit: int) -> bytes:
    line = bytearray()
    while not line.endswith(b"\n"):
        chunk = conn.recv(1)
        if not chunk:
            break
        line += chunk
        if len(line) > limit:
            raise ValueError("header too long")
    return bytes(line)


def remote_run(path: Path, data: bytes, password: str, limits: Limits) -> bytes:
    """What `pdf_worker._run` returns, computed by the worker container behind `path`."""
    secret = password.encode("utf-8")
    header = {
        "password": len(secret),
        "size": len(data),
        "limits": {f.name: getattr(limits, f.name) for f in fields(Limits)},
    }
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(limits.wall_seconds + 10)
            conn.connect(str(path))
            _check_peer(conn)  # before the password or the PDF leave this process
            conn.sendall(json.dumps(header).encode() + b"\n" + secret + data)
            conn.shutdown(socket.SHUT_WR)
            status = json.loads(_read_line(conn, MAX_HEADER) or b"{}").get("status")
            if status != "ok":
                _raise(status)
            chunks, size = [], 0
            while chunk := conn.recv(65536):
                size += len(chunk)
                if size > limits.max_output:
                    raise TooComplex("output")
                chunks.append(chunk)
    except TimeoutError:
        raise TooComplex("time") from None
    except (OSError, ValueError) as error:
        raise WorkerUnavailable(type(error).__name__) from None
    return b"".join(chunks)


def _raise(status: object) -> None:
    if status in ("time", "memory", "output"):
        raise TooComplex(str(status))
    if status == "unreadable":
        raise Unreadable()
    raise WorkerUnavailable(f"the worker answered {status!r}")


# The worker container's side.


def _limits(raw: object) -> Limits:
    if not isinstance(raw, dict):
        raise ValueError("limits")
    chosen = {}
    for field in fields(Limits):
        value = raw.get(field.name, getattr(_MAXIMA, field.name))
        if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
            raise ValueError(field.name)
        chosen[field.name] = type(getattr(_MAXIMA, field.name))(
            min(value, getattr(_MAXIMA, field.name))
        )
    return Limits(**chosen)


def _read_exactly(conn: socket.socket, size: int) -> bytes:
    chunks, left = [], size
    while left > 0:
        chunk = conn.recv(min(left, 1 << 20))
        if not chunk:
            raise ValueError("short request")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def handle(conn: socket.socket) -> None:
    """Answer one request (see the module)."""
    try:
        header = json.loads(_read_line(conn, MAX_HEADER))
        size, secret_size = int(header["size"]), int(header["password"])
        if not (0 < size <= MAX_PDF and 0 <= secret_size <= MAX_PASSWORD):
            raise ValueError("size")
        limits = _limits(header.get("limits"))
        password = _read_exactly(conn, secret_size).decode("utf-8")
        data = _read_exactly(conn, size)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, OSError):
        _answer(conn, "bad")
        return
    try:
        with pdf_worker._slots:
            output = pdf_worker._run(data, password, limits)
    except TooComplex as error:
        _answer(conn, error.reason)
        return
    except Unreadable:
        _answer(conn, "unreadable")
        return
    except Exception:  # noqa: BLE001 (never the message: it could carry the file's text)
        _answer(conn, "bad")
        return
    _answer(conn, "ok", output)


def _answer(conn: socket.socket, status: str, body: bytes = b"") -> None:
    with contextlib.suppress(OSError):
        conn.sendall(json.dumps({"status": status}).encode() + b"\n" + body)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(_MAXIMA.wall_seconds + 30)
        handle(self.request)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Development and tests: one process, a thread per request."""

    daemon_threads = True


class UidPool:
    """One worker uid per request being served, so two workers running at once never share a
    uid (none can trace or signal the other). A uid is reused only after its request's process
    was reaped. `slots` uids from `first`."""

    def __init__(self, first: int, slots: int) -> None:
        self.free = list(range(first, first + slots))
        self.busy: dict[int, int] = {}  # pid -> uid

    def take(self) -> int | None:
        return self.free.pop(0) if self.free else None

    def bind(self, pid: int, uid: int) -> None:
        self.busy[pid] = uid

    def give_back(self, uid: int) -> None:
        if uid not in self.free:
            self.free.append(uid)

    def reaped(self, alive: set[int]) -> None:
        """Free the uids of the processes no longer alive."""
        for pid in [p for p in self.busy if p not in alive]:
            self.give_back(self.busy.pop(pid))


class ForkingServer(socketserver.ForkingMixIn, socketserver.UnixStreamServer):
    """The container: a fresh process per request, gone after its reply (nothing kept), each
    with its own worker uid from `pool`."""

    pool: UidPool | None = None
    children: Path | None = None

    def collect_children(self, *, blocking: bool = False) -> None:
        super().collect_children(blocking=blocking)
        if self.pool is not None:
            self.pool.reaped(set(self.active_children or ()))

    def _uid(self) -> int:
        assert self.pool is not None
        uid = self.pool.take()
        while uid is None:  # every uid is in use: wait for a request to finish
            pid, _ = os.waitpid(-1, 0)
            if self.active_children is not None:
                self.active_children.discard(pid)
            self.pool.reaped(set(self.active_children or ()))
            uid = self.pool.take()
        return uid

    def process_request(self, request, client_address):  # noqa: ANN001, ANN201
        if self.pool is None or self.children is None:
            return super().process_request(request, client_address)
        uid = self._uid()
        pid = os.fork()
        if pid:
            self.pool.bind(pid, uid)
            if self.active_children is None:
                self.active_children = set()
            self.active_children.add(pid)
            self.close_request(request)
            return None
        # The request's own process: its worker runs as this uid only.
        pdf_worker.run_children_as(uid, uid, self.children)
        status = 1
        try:
            self.finish_request(request, client_address)
            status = 0
        except Exception:  # noqa: BLE001
            self.handle_error(request, client_address)
        finally:
            try:
                self.shutdown_request(request)
            finally:
                os._exit(status)


@dataclass(frozen=True)
class Identities:
    server_uid: int
    client_gid: int
    child_uid: int
    children: Path  # where each worker's private folder is made


def _own(path: Path, mode: int, uid: int, gid: int) -> None:
    """Root without FOWNER may only chmod its own files: take it, set the mode, hand it over."""
    os.chown(path, 0, 0)
    path.chmod(mode)
    os.chown(path, uid, gid)


def drop_privileges(path: Path, ids: Identities) -> None:
    """As root, once: the socket's folder for the server (0750, the client's group), the
    workers' base folder, then become the server with root only as the saved user id."""
    folder = path.parent
    folder.mkdir(parents=True, exist_ok=True)
    _own(folder, 0o750, ids.server_uid, ids.client_gid)
    ids.children.mkdir(parents=True, exist_ok=True)
    # Workers reach their own folder in it; they can neither list nor write here.
    _own(ids.children, 0o711, ids.server_uid, ids.server_uid)
    # The client's group as the only supplementary one: the server can give its socket that
    # group itself (and gains nothing else by it: no other file here has that group).
    os.setgroups([ids.client_gid])
    os.setresgid(ids.server_uid, ids.server_uid, ids.server_uid)
    os.setresuid(ids.server_uid, ids.server_uid, 0)


def _bind(path: Path, server_class: type[socketserver.UnixStreamServer], client_gid: int | None):
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    old = os.umask(0o177)
    try:
        server = server_class(str(path), _Handler)  # listens as this process's uid (SO_PEERCRED)
    finally:
        os.umask(old)
    if client_gid is None:
        path.chmod(0o600)
    else:
        os.chown(path, os.getuid(), client_gid)  # the server's own file, a group it is in
        path.chmod(0o660)
    return server


def serve(
    path: Path,
    slots: int = 2,
    ready: threading.Event | None = None,
    ids: Identities | None = None,
) -> socketserver.UnixStreamServer:
    """Listen on the Unix socket `path`. With `ids` (the container, started as root) drop to
    the server's uid first and fork a process per request; without them (development, tests)
    only this user may connect (0600). Returns the server, already serving in a thread when
    `ready` is given (tests); else serves forever."""
    pdf_worker.configure(slots)
    if ids is not None:
        drop_privileges(path, ids)
        server = _bind(path, ForkingServer, ids.client_gid)
        server.max_children = max(1, slots)  # type: ignore[attr-defined]
        server.pool = UidPool(ids.child_uid, max(1, slots))  # type: ignore[attr-defined]
        server.children = ids.children  # type: ignore[attr-defined]
    else:
        server = _bind(path, Server, None)
    if ready is None:
        server.serve_forever()
        return server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ready.set()
    return server
