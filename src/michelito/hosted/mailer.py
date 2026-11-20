"""Sending the sign-in emails: the `Mailer` interface, its local adapters and the `Dispatcher`.

- `MemoryMailer` keeps the emails in a list (unit tests).
- `OutboxMailer` writes each email as a JSON file in a folder (local development and e2e:
  nothing leaves the machine). Refused when the server listens beyond loopback (`cli_hosted`).
- `michelito.hosted.resend.ResendMailer` sends through Resend's HTTP API (production).

The `Dispatcher` sends in a background thread, so a request for a code answers in the same time
whether or not an email goes out (no account enumeration by timing). It also keeps the daily
cap (`daily_limit`, Resend's free plan allows 100 a day) in a `Ledger` (`store.Store` in
production, shared by the server and `michelito invite`): when the cap is reached, or the
provider says it was, `available()` is False until the next UTC day and every request for a code
is told, honestly and alike, to try later. There is no fallback sender. Emails still queued when
the process exits are dropped.

No adapter logs the body, the address or the API key.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str


class MailError(Exception):
    """The email could not be sent (the reason is safe to log: no address, code or key)."""


class MailCapReached(MailError):
    """The provider's daily quota is used up."""


class Mailer(Protocol):
    def send(self, email: Email) -> None:
        """Send it, or raise `MailError` / `MailCapReached`."""
        ...


@dataclass
class MemoryMailer:
    sent: list[Email] = field(default_factory=list)

    def send(self, email: Email) -> None:
        self.sent.append(email)


class OutboxMailer:
    """Each email as `<folder>/<n>.json` (only for the user: 0600)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._lock = threading.Lock()
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)

    def send(self, email: Email) -> None:
        # Sortable by time and unique across processes (the server and `michelito invite`).
        path = self.folder / f"{time.time_ns():020d}-{secrets.token_hex(4)}.json"
        with self._lock:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({**asdict(email), "sent_at": time.time()}, handle)


def _utc_day(clock: Callable[[], float]) -> str:
    return datetime.fromtimestamp(clock(), UTC).date().isoformat()


class Ledger(Protocol):
    """Where the day's count of sent emails lives (`store.Store` keeps it in accounts.db, so
    the server and `michelito invite` share it)."""

    def take_mail(self, day: str, limit: int) -> bool: ...

    def mail_available(self, day: str, limit: int) -> bool: ...

    def cap_mail(self, day: str) -> None: ...


class MemoryLedger:
    """A ledger in memory (tests)."""

    def __init__(self) -> None:
        self._sent: dict[str, int] = {}
        self._capped: set[str] = set()
        self._lock = threading.Lock()

    def take_mail(self, day: str, limit: int) -> bool:
        with self._lock:
            if day in self._capped or self._sent.get(day, 0) >= limit:
                return False
            self._sent[day] = self._sent.get(day, 0) + 1
            return True

    def mail_available(self, day: str, limit: int) -> bool:
        with self._lock:
            return day not in self._capped and self._sent.get(day, 0) < limit

    def cap_mail(self, day: str) -> None:
        with self._lock:
            self._capped.add(day)


class Dispatcher:
    """Sends through `mailer`, in a background thread unless `background` is False (then inline,
    for tests and the `invite` command). The day's count lives in `ledger`. Emails still queued
    when the process exits are dropped (the person asks for a new code)."""

    def __init__(
        self,
        mailer: Mailer,
        daily_limit: int = 100,
        background: bool = True,
        clock: Callable[[], float] = time.time,
        ledger: Ledger | None = None,
    ) -> None:
        self.mailer = mailer
        self.daily_limit = daily_limit
        self.background = background
        self.clock = clock
        self.ledger: Ledger = ledger or MemoryLedger()
        self._lock = threading.Lock()
        self._queue: queue.Queue[Email | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def available(self) -> bool:
        """Whether another email can be sent today."""
        return self.ledger.mail_available(_utc_day(self.clock), self.daily_limit)

    def submit(self, email: Email) -> bool:
        """Queue it (counting it against today's cap); False when the cap is reached or, when
        sending inline, when it could not be sent."""
        if not self.ledger.take_mail(_utc_day(self.clock), self.daily_limit):
            return False
        if not self.background:
            return self._deliver(email)
        self._ensure_thread()
        self._queue.put(email)
        return True

    def join(self) -> None:
        """Wait until everything queued was handled (tests)."""
        self._queue.join()

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=10)
            self._thread = None

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="mailer", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            email = self._queue.get()
            try:
                if email is None:
                    return
                self._deliver(email)
            finally:
                self._queue.task_done()

    def _deliver(self, email: Email) -> bool:
        try:
            self.mailer.send(email)
            return True
        except MailCapReached:
            self.ledger.cap_mail(_utc_day(self.clock))
            # For the owner: sign-in codes cannot go out until tomorrow (UTC).
            log.error("the email provider's daily cap was reached; sign-in codes are paused")
        except MailError as exc:
            log.error("a sign-in email could not be sent: %s", exc)
        except Exception:  # the thread must survive anything
            log.exception("a sign-in email could not be sent")
        return False
