"""Upload jobs: what the processing screen polls, kept **in memory only** (single process).

A job is one upload of several PDFs by one account. Each file goes from `queued` to `reading`
to a final state (`hosted.uploads`); the bytes of a file are dropped as soon as it reaches a
final state, except while it is `locked` (it waits for its bank's password, which is tried on
every locked file of the job). Jobs expire after `ttl` seconds and each account keeps at most
`keep` of them, so nothing piles up. Nothing here is written to disk: not the PDFs, not their
names, not the password (which never even reaches this module).

`Jobs.run(job, process)` processes the job's queued files in a background thread; the caller's
context (the request's workspace) is copied into it, so the thread opens the same account's
database through the same seam as the request. In hosted mode that workspace carries the
account's unwrapped data key (`Workspace.key`): the thread holds it only in memory, only while it
processes the job, and it is never written anywhere; it goes when the thread ends, and a job
dropped by sign-out or account deletion stops before its next file. How many PDFs are read at
once is bounded by the worker slots (`pdf_worker.configure`), whatever started them.

Retention: `prune()` (called on every use and by the app's sweeper every minute) drops expired
jobs; `forget(account)` drops an account's jobs (sign-out, sign-out everywhere, deleting the
account). A dropped job loses its files' bytes at once (`Job.evict`), and its processing stops
before the next file (`Jobs.alive`).
"""

from __future__ import annotations

import contextvars
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from michelito.hosted.uploads import DUPLICATE, LOCKED, SQUARED, Read

QUEUED = "queued"
READING = "reading"
OPEN_STATES = frozenset({QUEUED, READING})


@dataclass(frozen=True)
class FileState:
    id: int
    name: str
    state: str = QUEUED
    bank: str | None = None
    reads: tuple[Read, ...] = ()
    data: bytes | None = field(default=None, repr=False)

    @property
    def opened(self) -> bool:
        return self.state in (SQUARED, DUPLICATE)


@dataclass
class Job:
    """One account's upload; every change goes through its lock (states are replaced, never
    edited in place)."""

    id: str
    account_id: int
    created: float
    files: list[FileState]
    misses: tuple[str, ...] = ()  # banks whose last password opened none of the locked files
    # The last password try: (bank, files it opened, files still locked).
    last_try: tuple[str, int, int] | None = None
    evicted: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> tuple[tuple[FileState, ...], tuple[str, ...]]:
        with self.lock:
            return tuple(self.files), self.misses

    def set(self, file_id: int, **changes: object) -> None:
        with self.lock:
            self.files = [replace(f, **changes) if f.id == file_id else f for f in self.files]  # type: ignore[arg-type]

    def take(self, states: frozenset[str]) -> list[FileState]:
        """The files in `states`, marked `reading` (so no one else takes them)."""
        with self.lock:
            chosen = [f for f in self.files if f.state in states]
            ids = {f.id for f in chosen}
            self.files = [replace(f, state=READING) if f.id in ids else f for f in self.files]
        return chosen

    def set_misses(self, misses: tuple[str, ...]) -> None:
        with self.lock:
            self.misses = misses

    def set_last_try(self, bank: str, opened: int, left: int) -> None:
        with self.lock:
            self.last_try = (bank, opened, left)

    def evict(self) -> None:
        """Gone from the store: its bytes are dropped at once."""
        with self.lock:
            self.evicted = True
            self.files = [replace(f, data=None) for f in self.files]

    @property
    def done(self) -> bool:
        files, _ = self.snapshot()
        return all(f.state not in OPEN_STATES for f in files)


class Jobs:
    def __init__(
        self,
        ttl: float = 30 * 60,
        keep: int = 3,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ttl = ttl
        self.keep = keep
        self.clock = clock
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, account_id: int, files: Sequence[tuple[str, bytes]]) -> Job:
        job = Job(
            id=secrets.token_urlsafe(12),
            account_id=account_id,
            created=self.clock(),
            files=[FileState(i, name, data=data) for i, (name, data) in enumerate(files, 1)],
        )
        with self._lock:
            self._prune()
            mine = sorted(
                (j for j in self._jobs.values() if j.account_id == account_id),
                key=lambda j: j.created,
            )
            for old in mine[: max(0, len(mine) - self.keep + 1)]:
                del self._jobs[old.id]
                old.evict()
            self._jobs[job.id] = job
        return job

    def get(self, account_id: int, job_id: str) -> Job | None:
        """The job, only if it belongs to that account (another account's is "not found")."""
        with self._lock:
            self._prune()
            job = self._jobs.get(job_id)
        return job if job is not None and job.account_id == account_id else None

    def latest(self, account_id: int) -> Job | None:
        with self._lock:
            self._prune()
            mine = [j for j in self._jobs.values() if j.account_id == account_id]
        return max(mine, key=lambda j: j.created) if mine else None

    def forget(self, account_id: int) -> None:
        with self._lock:
            gone = [j for j in self._jobs.values() if j.account_id == account_id]
            self._jobs = {k: j for k, j in self._jobs.items() if j.account_id != account_id}
        for job in gone:
            job.evict()

    def alive(self, job: Job) -> bool:
        """Whether the job is still kept (processing stops for a dropped one)."""
        with self._lock:
            return self._jobs.get(job.id) is job and not job.evicted

    def prune(self) -> None:
        with self._lock:
            self._prune()

    def run(self, job: Job, process: Callable[[Job], None]) -> threading.Thread:
        """Process the job in a background thread, with the caller's context."""
        context = contextvars.copy_context()

        def work() -> None:
            context.run(process, job)

        thread = threading.Thread(target=work, name="michelito-upload", daemon=True)
        thread.start()
        return thread

    def _prune(self) -> None:
        cutoff = self.clock() - self.ttl
        expired = [j for j in self._jobs.values() if j.created <= cutoff]
        self._jobs = {k: j for k, j in self._jobs.items() if j.created > cutoff}
        for job in expired:
            job.evict()


def locked(files: Sequence[FileState]) -> list[FileState]:
    return [f for f in files if f.state == LOCKED]
