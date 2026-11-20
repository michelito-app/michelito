"""Operations state and the daily "something failed" email to the owner.

`<data>/ops/status.json` records, without any personal or financial data, what the daily check
needs: the last backup that worked and the last that failed (with a short reason), and how many
sign-in emails could not be sent each UTC day. The server, `michelito backup` and
`michelito ops-check` are separate processes: every update takes a file lock and replaces the
file atomically.

`check` looks at that state and at the documents that failed to parse in the last day in every
account's database (a count and a short fingerprint per kind of failure: never a file name, an
amount or an address) and returns the problems; `michelito ops-check` emails them to the owner
**only when there is one**.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import logging
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from michelito import encrypted
from michelito.hosted import auth, keys
from michelito.hosted.backup import derived
from michelito.hosted.keys import MasterKey
from michelito.hosted.mailer import Email, Mailer
from michelito.hosted.store import Store
from michelito.i18n import t

FOLDER = "ops"
STATUS = "status.json"
BACKUP_MAX_AGE = 26 * 3600  # a nightly backup older than this is a failure
WINDOW = 24 * 3600
KEEP_DAYS = 14  # days of mail failure counts kept
FAILED = ("invalid", "error")
MAIL_LOGGER = "michelito.hosted.mailer"
_DIGITS = re.compile(r"\d+")
_LETTERS = re.compile(r"[^\W\d_]+")


def _day(moment: float) -> str:
    return datetime.fromtimestamp(moment, UTC).strftime("%Y-%m-%d")


class Status:
    """The operations state file of the hosted folder `data`."""

    def __init__(self, data: Path, clock: Callable[[], float] = time.time) -> None:
        self.folder = data / FOLDER
        self.path = self.folder / STATUS
        self.clock = clock

    def read(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @contextmanager
    def _update(self) -> Iterator[dict[str, Any]]:
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.folder / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self.read()
            yield state
            partial = self.folder / f".{STATUS}.partial"
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, sort_keys=True)
            os.replace(partial, self.path)

    def backup_succeeded(self, label: str) -> None:
        with self._update() as state:
            state["backup_success"] = {"at": int(self.clock()), "label": label}
            state.pop("backup_failure", None)  # a later success clears it

    def backup_failed(self, reason: str) -> None:
        with self._update() as state:
            state["backup_failure"] = {"at": int(self.clock()), "reason": reason[:200]}

    def mail_failed(self) -> None:
        now = self.clock()
        with self._update() as state:
            days: dict[str, int] = state.get("mail_failures", {})
            today = _day(now)
            days[today] = int(days.get(today, 0)) + 1
            oldest = _day(now - KEEP_DAYS * 86400)
            state["mail_failures"] = {d: n for d, n in days.items() if d >= oldest}


class MailFailureCounter(logging.Handler):
    """Counts the sign-in emails that could not be sent (the mailer logs each one as an error)
    in the status file. It reads nothing from the record but its level."""

    def __init__(self, status: Status) -> None:
        super().__init__(level=logging.ERROR)
        self.status = status

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.status.mail_failed()
        except Exception:  # noqa: BLE001 (counting must never break sending)
            self.handleError(record)


def count_mail_failures(data: Path) -> MailFailureCounter:
    """Install the counter on the mailer's logger (the hosted server calls it once)."""
    handler = MailFailureCounter(Status(data))
    logging.getLogger(MAIL_LOGGER).addHandler(handler)
    return handler


# The daily check.


@dataclass(frozen=True)
class Problem:
    kind: str  # "backup", "parser", "mail"
    text: str  # data-free, for the owner


def _backup_problems(state: dict[str, Any], now: float) -> list[Problem]:
    success = state.get("backup_success", {}).get("at")
    failure = state.get("backup_failure", {})
    found = []
    if failure.get("at") and (success is None or failure["at"] >= success):
        found.append(Problem("backup", t("hosted.ops.backup_failed", reason=failure["reason"])))
    if success is None:
        found.append(Problem("backup", t("hosted.ops.backup_never")))
    elif now - success > BACKUP_MAX_AGE:
        hours = int((now - success) // 3600)
        found.append(Problem("backup", t("hosted.ops.backup_old", hours=hours)))
    return found


def _mail_problems(state: dict[str, Any], now: float) -> list[Problem]:
    days = state.get("mail_failures", {})
    total = sum(int(days.get(_day(now - offset), 0)) for offset in (0, WINDOW))
    return [Problem("mail", t("hosted.ops.mail_failed", count=total))] if total else []


_FINGERPRINT_INFO = b"michelito ops fingerprint v1"


def template(detail: str | None) -> str:
    """A failure's detail with its digit runs and letter runs replaced (amounts, names, account
    numbers go; the shape of the message stays), so equal kinds of failure group together."""
    return _LETTERS.sub("a", _DIGITS.sub("0", detail or ""))


def fingerprint(master: MasterKey, parser: str | None, status: str, detail: str | None) -> str:
    """A short keyed fingerprint of a kind of failure: without the master key it cannot be
    matched against guessed details."""
    key = derived(master, _FINGERPRINT_INFO)
    message = f"{parser}\0{status}\0{template(detail)}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:8]


def parser_failures(
    store: Store, master: MasterKey, root: Path, since: datetime
) -> tuple[Counter[str], int]:
    """Failed documents processed since `since`, across every account: a count per failure
    fingerprint (a keyed hash of parser, status and the detail's template, plus the parser's
    name) and how many
    accounts could not be opened."""
    found: Counter[str] = Counter()
    unreadable = 0
    moment = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    marks = ", ".join("?" for _ in FAILED)
    for stored in store.data_keys():
        path = root / auth.USERS / stored.folder / auth.DATABASE
        if not path.is_file():
            continue
        try:
            key = keys.unwrap(master, stored.wrapped, stored.account_id, stored.folder)
            with closing(encrypted.connect(path, key)) as conn:
                rows = conn.execute(
                    "SELECT parser, status, detail FROM documents "
                    f"WHERE status IN ({marks}) AND processed_at >= ?",
                    (*FAILED, moment),
                ).fetchall()
        except (keys.UnwrapError, Exception):  # noqa: BLE001 (one account must not stop the check)
            unreadable += 1
            continue
        for parser, status, detail in rows:
            found[f"{parser or '-'}:{fingerprint(master, parser, status, detail)}"] += 1
    return found, unreadable


def check(
    data: Path,
    store: Store | None,
    master: MasterKey | None,
    clock: Callable[[], float] = time.time,
) -> list[Problem]:
    now = clock()
    state = Status(data, clock).read()
    found = _backup_problems(state, now) + _mail_problems(state, now)
    if store is not None and master is not None:
        since = datetime.fromtimestamp(now, UTC) - timedelta(seconds=WINDOW)
        failures, unreadable = parser_failures(store, master, data, since)
        if failures:
            kinds = ", ".join(f"{k} ×{n}" for k, n in sorted(failures.items()))
            total = sum(failures.values())
            found.append(Problem("parser", t("hosted.ops.parser_failed", count=total, kinds=kinds)))
        if unreadable:
            found.append(Problem("parser", t("hosted.ops.unreadable", count=unreadable)))
    return found


def alert_email(to: str, problems: list[Problem]) -> Email:
    lines = "\n".join(f"- {p.text}" for p in problems)
    return Email(to, t("hosted.ops.subject"), t("hosted.ops.body", problems=lines))


def notify(mailer: Mailer, to: str, problems: list[Problem]) -> bool:
    """Email the owner when there is a problem; nothing otherwise. Returns whether it sent."""
    if not problems:
        return False
    mailer.send(alert_email(to, problems))
    return True
