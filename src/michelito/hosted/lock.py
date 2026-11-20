"""One process at a time on a hosted folder: the server, or a master key rotation.

`server_lock(data)` holds an exclusive `flock` on `<data>/server.lock` while the server (or a
rotation) runs. The kernel releases it when the process ends, even after a crash, so a stale
file never blocks anything. The file holds the pid, for people; the lock is what counts.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK = "server.lock"


class FolderBusyError(Exception):
    """Another process (the server or a rotation) is using the hosted folder."""


@contextmanager
def server_lock(data: Path) -> Iterator[None]:
    path = data / LOCK
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FolderBusyError(
                f"{data} is in use by another process (pid in {path}): stop the server first"
            ) from None
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
