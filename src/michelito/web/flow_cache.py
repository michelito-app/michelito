"""The loaded flow, kept between requests while the database file is provably unchanged.

Loading every movement (`spending.load_all`) reads and classifies the whole history, and nearly
every route of the board needs it. This keeps the last result per database, in memory only, and
gives it back only when all of these hold:

- the database file (and its write-ahead log, if any) has the same inode, size and modification
  time as when the value was loaded;
- that modification time is at least `RACY_SECONDS` old: a later write then has a later time
  whatever the file system's clock granularity, so an equal signature means an equal file (the
  same idea as git's index); a file written just now, or dated in the future, is never kept;
- no rollback journal sits next to it (a write in progress);
- the other inputs of the load (the holders, the day) are the same.

Anything else loads again. Only the `MAX_ENTRIES` most recently used databases are kept, and a
value not used for `IDLE_SECONDS` is dropped by `prune` (every `get` calls it; a server with
idle periods calls it on a timer), so a person's data does not stay in the server's memory long
after their last request.

The caller must not use it inside a transaction: a load would see rows that may be rolled back.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

RACY_SECONDS = 2.0
IDLE_SECONDS = 300.0
MAX_ENTRIES = 8
_NANOSECONDS = 1_000_000_000
_LOG_SUFFIX = "-wal"
_JOURNAL_SUFFIX = "-journal"

Value = TypeVar("Value")
FileState = tuple[int, int, int]  # inode, size, modification time (ns)
Signature = tuple[FileState, FileState | None]  # the database and its write-ahead log


@dataclass(frozen=True)
class _Entry:
    signature: Signature
    inputs: Hashable
    value: object
    used: float


def _state(path: Path) -> FileState | None:
    try:
        found = os.stat(path)
    except OSError:  # missing, or not something that can be inspected: nothing to go by
        return None
    return (found.st_ino, found.st_size, found.st_mtime_ns)


def _settled(state: FileState, now: float) -> bool:
    """Written long enough ago for a later write to show in its modification time."""
    return now - state[2] / _NANOSECONDS >= RACY_SECONDS


def signature(database: Path, now: float) -> Signature | None:
    """What identifies the database's content on disk; None when it cannot be told apart from a
    later write (missing, written just now, or with a write in progress)."""
    main = _state(database)
    if main is None or not _settled(main, now):
        return None
    if _state(database.with_name(database.name + _JOURNAL_SUFFIX)) is not None:
        return None
    log = _state(database.with_name(database.name + _LOG_SUFFIX))
    if log is not None and not _settled(log, now):
        return None
    return (main, log)


class FlowCache:
    """One value per database (see the module docstring). Safe to call from several threads:
    requests for the same database wait for one load instead of each doing its own."""

    def __init__(
        self,
        *,
        max_entries: int = MAX_ENTRIES,
        idle_seconds: float = IDLE_SECONDS,
        wall: Callable[[], float] = time.time,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_entries = max_entries
        self._idle_seconds = idle_seconds
        self._wall = wall
        self._clock = clock
        self._guard = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._loading: dict[str, threading.Lock] = {}
        self._cleared = 0  # how many times `clear` ran: a load that straddles one is not kept

    def __len__(self) -> int:
        with self._guard:
            return len(self._entries)

    def clear(self) -> None:
        """Drop every value (someone's sessions ended: nothing of theirs stays in memory)."""
        with self._guard:
            for key in list(self._entries):
                self._drop(key)
            self._cleared += 1

    def prune(self) -> None:
        """Drop every value not used for `idle_seconds`."""
        now = self._clock()
        with self._guard:
            idle = [
                key for key, entry in self._entries.items() if now - entry.used > self._idle_seconds
            ]
            unused = [key for key in self._loading if key not in self._entries]
            for key in (*idle, *unused):
                self._drop(key)

    def _drop(self, key: str) -> None:
        """Forget a database (the caller holds the guard). Its lock stays while a load holds it,
        so the requests waiting for that load still share it."""
        self._entries.pop(key, None)
        lock = self._loading.get(key)
        if lock is not None and not lock.locked():
            del self._loading[key]

    def get(self, database: Path, inputs: Hashable, load: Callable[[], Value]) -> Value:
        """The value `load` gives for this database and these inputs: a kept one when the file
        is provably the same, else a new one (kept only if the file can be told apart later)."""
        self.prune()
        found = signature(database, self._wall())
        if found is None:
            return load()
        key = str(database)
        with self._lock_of(key):
            kept = self._fresh(key, found, inputs)
            if kept is not None:
                return kept.value  # type: ignore[return-value]
            # `found` was read before loading: a write in between leaves a newer file under an
            # older signature, which the next request sees as changed.
            cleared = self._cleared
            value = load()
            self._keep(key, _Entry(found, inputs, value, self._clock()), cleared)
            return value

    def _lock_of(self, key: str) -> threading.Lock:
        with self._guard:
            return self._loading.setdefault(key, threading.Lock())

    def _fresh(self, key: str, found: Signature, inputs: Hashable) -> _Entry | None:
        """The kept entry if it is still valid (marked as used now); a stale one is dropped."""
        now = self._clock()
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.signature != found or entry.inputs != inputs:
                del self._entries[key]
                return None
            used = _Entry(entry.signature, entry.inputs, entry.value, now)
            self._entries[key] = used
            return used

    def _keep(self, key: str, entry: _Entry, cleared: int) -> None:
        with self._guard:
            if cleared != self._cleared:
                return
            self._entries[key] = entry
            by_age = sorted(self._entries, key=lambda other: self._entries[other].used)
            for other in by_age[: max(0, len(by_age) - self._max_entries)]:
                self._drop(other)
