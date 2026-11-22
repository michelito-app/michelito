"""Reading an uploaded PDF in a separate, limited process (hosted mode).

A PDF's size says nothing about what parsing it costs: a few hundred kilobytes of compressed
stream can expand to gigabytes (a decompression bomb), and a page tree can hold thousands of
pages. So each upload is opened by a short-lived worker (`python -I -m
michelito.hosted.pdf_worker`) and a breach only fails that file (`TooComplex`):

- limits on the worker: address space (`RLIMIT_AS`), CPU (`RLIMIT_CPU`), no files written
  (`RLIMIT_FSIZE` 0), no core dumps, no new processes (`RLIMIT_NPROC` 0, against a fork bomb),
  a handful of file descriptors (`RLIMIT_NOFILE`), every inherited descriptor above 2 closed, an
  empty private working folder, and a wall-clock timeout;
- the page count is checked **before** any words are extracted, and the words are capped per
  page and in total (`Limits`);
- the parent reads at most `Limits.max_output` bytes of the worker's answer.

At most `slots` workers run at once in the whole process (`configure`), whichever route started
them (an upload, a password retry, a shared file): a caller waits for a free slot.

The PDF and its password go to the worker through its standard input (a pipe), never through
the command line or the environment, so neither shows up in the process list; the worker writes
nothing to disk and answers on standard output with the pages (positioned words) as JSON, or with
the reason it could not read them. No error message carries the password or the file's text.

Where the worker runs: with `MICHELITO_PDF_WORKER_SOCKET` set (the deployment), the same
limited process is started in a separate `pdfworker` container with no secrets, no data volume
and no network, reached over a Unix socket (`hosted.pdf_socket`). Without it (local development
and tests) it is started next to the app; then a vulnerability in pdfminer that escapes the
limits above would run as the app's user.

    stdin:  4-byte big-endian password length, the password (UTF-8), the PDF bytes
    stdout: {"pages": [[[text, x0, x1, top], ...], ...]}
            or {"error": "password" | "pages" | "words" | "open"}
"""

from __future__ import annotations

import contextlib
import json
import os
import resource
import selectors
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from michelito.parsers.common import Page, Word, group_lines

MB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    max_pages: int = 50
    memory_bytes: int = 512 * MB
    cpu_seconds: int = 20
    wall_seconds: float = 30.0
    words_per_page: int = 5_000
    total_words: int = 60_000
    max_output: int = 16 * MB


class WrongPassword(Exception):
    """The PDF needs a password, or the one given does not open it."""


class TooComplex(Exception):
    """Too many pages or words, or opening it went over the memory, time or output limit."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # pages, words, memory, time or output: no data from the file


class Unreadable(Exception):
    """Not a PDF that can be opened."""


_slots = threading.BoundedSemaphore(2)
_folder: Path | None = None
_folder_lock = threading.Lock()
# In the pdfworker container (`hosted.pdf_socket.drop_privileges`): the (uid, gid) every worker
# process runs as, and the folder their private working folders go in. None: as this process.
_child: tuple[int, int] | None = None
_child_base: Path | None = None


def run_children_as(uid: int, gid: int, base: Path) -> None:
    """Start every worker as `uid`/`gid` (no supplementary groups), each in a fresh private
    folder under `base`. Needs a saved user id of 0 (the pdfworker server's set-up) and the
    SETUID, SETGID, CHOWN and KILL capabilities."""
    global _child, _child_base
    _child, _child_base = (uid, gid), base


@contextlib.contextmanager
def _privileged() -> Iterator[None]:
    """Effective root for one step (starting, stopping or cleaning a worker of another uid),
    when this process keeps a saved user id of 0; nothing otherwise."""
    if _child is None:
        yield
        return
    previous = os.geteuid()
    os.seteuid(0)
    try:
        yield
    finally:
        os.seteuid(previous)


def _child_folder() -> Path:
    """A new, empty working folder for one worker: the server's, mode 0711, so the worker (another
    uid) can be started in it but can write nothing there, nor anywhere else."""
    assert _child is not None and _child_base is not None
    folder = Path(tempfile.mkdtemp(prefix="w-", dir=_child_base))
    folder.chmod(0o711)
    return folder


def _remove_child_folder(folder: Path) -> None:
    """Remove a worker's folder after its file (it cannot have put anything in it)."""
    with contextlib.suppress(OSError):
        folder.rmdir()


def configure(slots: int) -> None:
    """How many workers may run at once in this process."""
    global _slots
    _slots = threading.BoundedSemaphore(max(1, slots))


def _empty_folder() -> Path:
    """A private, empty working folder for the workers (they never write to it)."""
    global _folder
    with _folder_lock:
        if _folder is None or not _folder.is_dir():
            _folder = Path(tempfile.mkdtemp(prefix="michelito-pdf-worker-"))
        return _folder


def read(data: bytes, password: str, limits: Limits = Limits()) -> tuple[Page, ...]:
    """The PDF's pages, read by a limited worker process (waiting for a free slot)."""
    with _slots:
        output = _dispatch(data, password, limits)
    try:
        answer = json.loads(output)
    except ValueError:
        raise Unreadable() from None
    error = answer.get("error") if isinstance(answer, dict) else "open"
    if error == "password":
        raise WrongPassword()
    if error in ("pages", "words"):
        raise TooComplex(error)
    if error is not None:
        raise Unreadable()
    return tuple(
        group_lines(Word(str(w[0]), float(w[1]), float(w[2]), float(w[3])) for w in page)
        for page in answer["pages"]
    )


def _dispatch(data: bytes, password: str, limits: Limits) -> bytes:
    """The worker's answer: from the worker container when a socket is configured, else from a
    process started here."""
    from michelito.hosted import pdf_socket  # noqa: PLC0415 (it imports this module)

    path = pdf_socket.socket_path()
    if path is None:
        return _run(data, password, limits)
    return pdf_socket.remote_run(path, data, password, limits)


def _run(data: bytes, password: str, limits: Limits) -> bytes:
    secret = password.encode("utf-8")
    message = struct.pack(">I", len(secret)) + secret + data
    del secret
    command = [sys.executable, "-I", "-m", "michelito.hosted.pdf_worker", *_limit_args(limits)]
    folder = _child_folder() if _child else _empty_folder()
    child = _child
    try:
        with _privileged():
            process = subprocess.Popen(  # noqa: S603 - fixed command, the input goes by the pipe
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={"PATH": os.environ.get("PATH", "")},
                cwd=folder,
                close_fds=True,
                user=child[0] if child else None,
                group=child[1] if child else None,
                extra_groups=[] if child else None,
            )
    except BaseException:
        if _child is not None:
            _remove_child_folder(folder)
        raise
    try:
        return _talk(process, message, limits)
    finally:
        if _child is not None:
            _remove_child_folder(folder)


def _talk(process: subprocess.Popen[bytes], message: bytes, limits: Limits) -> bytes:
    writer = threading.Thread(target=_feed, args=(process, message), daemon=True)
    writer.start()
    del message
    try:
        output = _collect(process, limits)
        code = process.wait(timeout=max(0.1, limits.wall_seconds))
    except subprocess.TimeoutExpired:
        raise TooComplex("time") from None
    finally:
        if process.poll() is None:
            with _privileged():  # it may run as another uid
                process.kill()
            process.wait()
        writer.join(timeout=1)
    if code in (-9, -24):  # killed: SIGKILL or SIGXCPU
        raise TooComplex("time")
    if code in (4, 5):  # 5: it could not make itself non-dumpable (never read the PDF)
        raise Unreadable()
    if code != 0:  # it died: out of memory (an allocation it could not report) or a crash
        raise TooComplex("memory")
    return output


def _feed(process: subprocess.Popen[bytes], message: bytes) -> None:
    assert process.stdin is not None
    try:
        process.stdin.write(message)
    except (BrokenPipeError, OSError):
        pass
    finally:
        with contextlib.suppress(OSError):
            process.stdin.close()


def _collect(process: subprocess.Popen[bytes], limits: Limits) -> bytes:
    """The worker's standard output, at most `max_output` bytes, before the wall clock."""
    assert process.stdout is not None
    deadline = time.monotonic() + limits.wall_seconds
    chunks: list[bytes] = []
    size = 0
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TooComplex("time")
            if not selector.select(timeout=left):
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > limits.max_output:
                raise TooComplex("output")
            chunks.append(chunk)


def _limit_args(limits: Limits) -> list[str]:
    return [
        str(limits.max_pages),
        str(limits.memory_bytes),
        str(limits.cpu_seconds),
        str(limits.words_per_page),
        str(limits.total_words),
    ]


def _harden(memory: int, cpu: int) -> None:
    """Called in the worker after its imports: nothing inherited, nothing new."""
    os.closerange(3, 1024)
    # macOS refuses to lower RLIMIT_AS (and would not enforce it); the deployment is Linux, so
    # development there runs without the memory cap, like `_not_dumpable`.
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (8, 8))


def _work(max_pages: int, words_per_page: int, total_words: int, memory: int, cpu: int) -> dict:
    raw = sys.stdin.buffer.read()
    (size,) = struct.unpack(">I", raw[:4])
    password = raw[4 : 4 + size].decode("utf-8")
    data = raw[4 + size :]
    del raw
    import io

    import pdfplumber

    from michelito import pdf

    _harden(memory, cpu)
    try:
        with pdfplumber.open(io.BytesIO(data), password=password) as document:
            if len(document.pages) > max_pages:
                return {"error": "pages"}
            pages = []
            total = 0
            for page in document.pages:
                words = page.extract_words()
                total += len(words)
                if len(words) > words_per_page or total > total_words:
                    return {"error": "words"}
                pages.append([[w["text"], w["x0"], w["x1"], w["top"]] for w in words])
    except MemoryError:
        raise
    except Exception as exc:  # pdfminer raises assorted classes (and wraps a MemoryError)
        if _caused_by_memory(exc):
            raise MemoryError from None
        return {"error": "password" if pdf.wrong_password(exc) else "open"}
    return {"pages": pages}


def _caused_by_memory(error: BaseException) -> bool:
    seen: BaseException | None = error
    while seen is not None:
        if isinstance(seen, MemoryError) or any(isinstance(a, MemoryError) for a in seen.args):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


PR_SET_DUMPABLE = 4
PR_GET_DUMPABLE = 3


def _not_dumpable() -> None:
    """Linux: mark this process non-dumpable, so no other process of the same uid (another
    worker, if one were compromised) can ptrace it or read its memory (`process_vm_readv`,
    /proc/<pid>/mem), whatever `kernel.yama.ptrace_scope` says. Elsewhere: nothing (the
    deployment is Linux; development on another system has no such neighbours to fear)."""
    if not sys.platform.startswith("linux"):
        return
    import ctypes  # noqa: PLC0415

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        os._exit(5)  # refuse to read a PDF without it


def main() -> None:
    _not_dumpable()  # first, before the password and the PDF are read from stdin
    max_pages, memory, cpu, per_page, total = (int(arg) for arg in sys.argv[1:6])
    try:
        answer = _work(max_pages, per_page, total, memory, cpu)
    except MemoryError:
        os._exit(3)
    except Exception:  # a malformed request: nothing to say, nothing printed
        os._exit(4)
    sys.stdout.write(json.dumps(answer))


if __name__ == "__main__":
    main()
