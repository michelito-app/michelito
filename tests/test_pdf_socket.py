"""The PDF worker behind a Unix socket (`hosted.pdf_socket`, the `pdfworker` container): the
hosted app gets the same pages, errors and caps as with a local worker process, the socket is
private, a malformed request or looser limits are refused, and without the container nothing is
opened in the app. Synthetic PDFs only."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from michelito.hosted import pdf_socket, pdf_worker
from tests.test_hosted_uploads import BHD_LOCKED, PASSWORD, POPULAR


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, list[int]]]:
    """A worker server on a short socket path, with a count of the requests it handled."""
    folder = Path(tempfile.mkdtemp(prefix="mpw-"))
    path = folder / "w.sock"
    handled: list[int] = []
    real = pdf_socket.handle

    def counting(conn: socket.socket) -> None:
        handled.append(1)
        real(conn)

    monkeypatch.setattr(pdf_socket, "handle", counting)
    ready = threading.Event()
    server = pdf_socket.serve(path, 2, ready)
    assert ready.wait(5)
    monkeypatch.setenv(pdf_socket.SOCKET_ENV, str(path))
    monkeypatch.setenv(pdf_socket.UID_ENV, str(os.getuid()))
    try:
        yield path, handled
    finally:
        server.shutdown()
        server.server_close()
        path.unlink(missing_ok=True)
        folder.rmdir()


def test_the_socket_gives_the_same_pages_as_a_local_worker(
    worker: tuple[Path, list[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, handled = worker
    remote = pdf_worker.read(POPULAR, "")
    assert handled == [1]
    monkeypatch.delenv(pdf_socket.SOCKET_ENV)
    assert pdf_worker.read(POPULAR, "") == remote
    assert path.stat().st_mode & 0o777 == 0o600


def test_errors_and_caps_cross_the_socket(worker: tuple[Path, list[int]]) -> None:
    with pytest.raises(pdf_worker.WrongPassword):
        pdf_worker.read(BHD_LOCKED, "wrong")
    assert pdf_worker.read(BHD_LOCKED, PASSWORD)
    with pytest.raises(pdf_worker.TooComplex) as words:
        pdf_worker.read(POPULAR, "", pdf_worker.Limits(words_per_page=5))
    assert words.value.reason == "words"
    with pytest.raises(pdf_worker.TooComplex) as output:
        pdf_worker.read(POPULAR, "", pdf_worker.Limits(max_output=100))
    assert output.value.reason == "output"
    with pytest.raises(pdf_worker.Unreadable):
        pdf_worker.read(b"%PDF-1.4 not really", "")


def _raw(path: Path, payload: bytes) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(str(path))
        conn.sendall(payload)
        conn.shutdown(socket.SHUT_WR)
        line = b""
        while not line.endswith(b"\n"):
            line += conn.recv(1)
    return json.loads(line)


def test_a_malformed_request_is_refused(worker: tuple[Path, list[int]]) -> None:
    path, _ = worker
    assert _raw(path, b"not json\n")["status"] == "bad"
    too_big = {"password": 0, "size": pdf_socket.MAX_PDF + 1, "limits": {}}
    assert _raw(path, json.dumps(too_big).encode() + b"\n")["status"] == "bad"
    short = {"password": 0, "size": 100, "limits": {}}
    assert _raw(path, json.dumps(short).encode() + b"\nshort")["status"] == "bad"


def test_a_request_cannot_loosen_the_limits() -> None:
    asked = pdf_socket._limits({"max_pages": 10**6, "memory_bytes": 10**12, "words_per_page": 3})
    assert asked.max_pages == pdf_worker.Limits().max_pages
    assert asked.memory_bytes == pdf_worker.Limits().memory_bytes
    assert asked.words_per_page == 3
    for bad in ({"max_pages": -1}, {"cpu_seconds": "20"}, {"max_pages": True}, []):
        with pytest.raises(ValueError):
            pdf_socket._limits(bad)


def test_without_the_worker_container_nothing_is_opened_here(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[int] = []
    monkeypatch.setattr(pdf_worker, "_run", lambda *args: started.append(1) or b"")
    monkeypatch.setenv(pdf_socket.SOCKET_ENV, str(tmp_path / "missing.sock"))
    with pytest.raises(pdf_socket.WorkerUnavailable):
        pdf_worker.read(POPULAR, "")
    assert started == []  # no local worker as a fallback


def test_a_socket_held_by_another_uid_gets_nothing(
    worker: tuple[Path, list[int]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A worker that replaced the socket (another uid than the server's) never receives the
    password or the PDF: the peer is checked before anything is sent."""
    _, handled = worker
    received: list[bytes] = []
    real = pdf_socket._read_line

    def spy(conn: socket.socket, limit: int) -> bytes:
        line = real(conn, limit)
        received.append(line)
        return line

    monkeypatch.setattr(pdf_socket, "_read_line", spy)
    for expected in (str(os.getuid() + 1), ""):
        monkeypatch.setenv(pdf_socket.UID_ENV, expected)
        with caplog.at_level(logging.ERROR), pytest.raises(pdf_socket.WorkerUnavailable):
            pdf_worker.read(BHD_LOCKED, PASSWORD)
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "held by uid" in messages and PASSWORD not in messages
    # The server only ever saw empty requests (the client hung up before sending).
    assert all(PASSWORD.encode() not in line and b"size" not in line for line in received)


def test_the_socket_is_for_the_client_group_only(tmp_path: Path) -> None:
    folder = Path(tempfile.mkdtemp(prefix="mpw-"))
    path = folder / "g.sock"
    server = pdf_socket._bind(path, pdf_socket.Server, os.getgid())
    try:
        mode = path.stat()
        assert mode.st_mode & 0o777 == 0o660 and mode.st_gid == os.getgid()
    finally:
        server.server_close()
        path.unlink()
        folder.rmdir()


def test_workers_start_as_the_child_uid_in_a_private_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the container does as root, checked without root: the identity handed to each
    worker, its fresh folder it cannot write to, and that the folder is gone afterwards."""
    seen: dict[str, object] = {}
    raised: list[int] = []

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            seen.update(kwargs)
            folder = Path(str(kwargs["cwd"]))
            seen["mode"] = folder.stat().st_mode & 0o777
            seen["owner"] = folder.stat().st_uid

    monkeypatch.setattr(pdf_worker.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(pdf_worker, "_talk", lambda process, message, limits: b"answer")
    monkeypatch.setattr(pdf_worker.os, "seteuid", lambda uid: raised.append(uid))
    pdf_worker.run_children_as(10003, 10003, tmp_path)
    try:
        assert pdf_worker._run(b"%PDF", "pw", pdf_worker.Limits()) == b"answer"
    finally:
        pdf_worker._child = None
        pdf_worker._child_base = None
    assert (seen["user"], seen["group"], seen["extra_groups"]) == (10003, 10003, [])
    folder = Path(str(seen["cwd"]))
    assert folder.parent == tmp_path
    # The server's folder, entered but not writable by anyone else (the worker's uid).
    assert seen["owner"] == os.getuid() and seen["mode"] == 0o711
    assert not folder.exists()  # removed: nothing of one file stays for the next
    assert 0 in raised  # root (the saved uid) only to start it


def test_without_root_the_container_identities_are_refused(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    from michelito import cli

    if os.geteuid() == 0:
        pytest.skip("run as root")
    argv = ["pdf-worker", "--socket", str(tmp_path / "s.sock"), "--server-uid", "10002"]
    assert cli.main(argv) == 2
    assert "start as root" in capsys.readouterr().err


DUMPABLE = (
    "import ctypes, sys; from michelito.hosted import pdf_worker; pdf_worker._not_dumpable(); "
    "print(ctypes.CDLL(None).prctl(pdf_worker.PR_GET_DUMPABLE, 0, 0, 0, 0))"
)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="prctl is Linux")
def test_a_worker_makes_itself_non_dumpable() -> None:
    done = subprocess.run(
        [sys.executable, "-I", "-c", DUMPABLE], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "0"


def test_the_worker_is_non_dumpable_before_it_reads_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    monkeypatch.setattr(pdf_worker, "_not_dumpable", lambda: order.append("not dumpable"))
    monkeypatch.setattr(
        pdf_worker, "_work", lambda *args: order.append("read stdin") or {"pages": []}
    )
    monkeypatch.setattr(sys, "argv", ["pdf_worker", "50", "1", "1", "1", "1"])
    pdf_worker.main()
    assert order == ["not dumpable", "read stdin"]


def test_concurrent_requests_get_different_worker_uids() -> None:
    """The allocator the container's server uses (setting the uids needs root: checked in a
    container, see the report)."""
    pool = pdf_socket.UidPool(10003, 2)
    first, second = pool.take(), pool.take()
    assert first is not None and second is not None
    assert {first, second} == {10003, 10004}
    pool.bind(101, first)
    pool.bind(102, second)
    assert pool.take() is None  # a third request waits: no uid is shared
    pool.reaped({102})  # 101 was reaped: only its uid comes back
    assert pool.take() == first and pool.take() is None
    pool.reaped(set())
    assert pool.take() == second
