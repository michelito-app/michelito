"""The demo's feedback and usage counters, in `feedback.db` (apart from the copies).

Copies are deleted after 24 h; this is not. So **nothing** that identifies a visitor goes in here:
no IP, no `demo_id`, no exact time of a visit. A feedback entry stores what the visitor wrote (and
their email, only if they gave it) plus the context the interface sends (page, screen width,
version, `ref`). Usage is only counts per day: visits per screen, copies created and key events
(`EVENTS`).

Earlier releases kept this in another file (`legacy.FEEDBACK_FILE`) with Spanish table, column
and value names: the first time `feedback.db` is opened in a folder that only has the old file,
every row is copied over (`_migrate_legacy`; the old names live in `michelito.legacy`). The old
file is left as it was.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import unicodedata
from collections import Counter, deque
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from michelito import legacy
from michelito.i18n import t

FILENAME = "feedback.db"
TEXT_MAX = 2000
EMAIL_MAX = 254
PAGE_MAX = 200
VERSION_MAX = 40
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_REF = re.compile(r"[A-Za-z0-9_.-]{1,64}")
# Screens that are counted (the interface sends the key of the screen); anything else counts as
# `OTHER_SCREEN`. `HOME_SCREEN` is the start page ("/").
HOME_SCREEN = "summary"
OTHER_SCREEN = "other"
SCREENS = frozenset(
    {
        HOME_SCREEN,
        "budget",
        "transactions",
        "pending",
        "shared",
        "investments",
        "recurring",
        "reports",
        "accounts",
        "categories",
        "log",
        "import",
    }
)
EVENTS = frozenset(
    {
        "budget_activated",
        "reserve_created",
        "sample_statement",
        "multi_select",
        "undo",
        "copy_for_claude",
    }
)
KINDS = ("visit", "copy", "event")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    email TEXT,
    page TEXT,
    width INTEGER,
    version TEXT,
    ref TEXT
);
CREATE TABLE IF NOT EXISTS usage (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (day, kind, key)
);
"""


class InvalidOpinion(ValueError):
    """The feedback breaks a limit (empty or long text, malformed email or `ref`). The message
    is shown to the visitor."""


@dataclass(frozen=True)
class Opinion:
    """One feedback entry, as the visitor sent it."""

    text: str
    email: str | None = None
    page: str | None = None
    width: int | None = None
    version: str | None = None
    ref: str | None = None


@dataclass(frozen=True)
class Stored(Opinion):
    id: int = 0
    created_at: str = ""


def strip_controls(text: str, keep_newlines: bool = False) -> str:
    """Without control or format characters (Unicode Cc and Cf: ANSI sequences, bidi marks such
    as U+202E…), which in the operator's terminal could clear the screen or disguise the text.
    `keep_newlines`: the newline is kept (in the feedback text)."""
    return "".join(
        char
        for char in text
        if (keep_newlines and char == "\n") or unicodedata.category(char) not in ("Cc", "Cf")
    )


def printable(text: str) -> str:
    """To print what a visitor wrote: control characters show as `\\u202e` and do not act (the
    newline stays)."""
    return "".join(
        char
        if char == "\n" or unicodedata.category(char) not in ("Cc", "Cf")
        else f"\\u{ord(char):04x}"
        for char in text
    )


def clean(opinion: Opinion) -> Opinion:
    """The feedback ready to store (without control characters); `InvalidOpinion` if something
    breaks a limit."""
    text = strip_controls(opinion.text.replace("\r\n", "\n"), keep_newlines=True).strip()
    if not text or len(text) > TEXT_MAX:
        raise InvalidOpinion(t("demo.feedback.text_length", max=f"{TEXT_MAX:,}"))
    email = strip_controls(opinion.email or "").strip() or None
    if email is not None and (len(email) > EMAIL_MAX or not _EMAIL.fullmatch(email)):
        raise InvalidOpinion(t("demo.feedback.bad_email"))
    ref = strip_controls(opinion.ref or "").strip() or None
    if ref is not None and not _REF.fullmatch(ref):
        raise InvalidOpinion(t("demo.feedback.bad_ref"))
    page = strip_controls(opinion.page or "").split("?")[0][:PAGE_MAX] or None
    width = opinion.width if opinion.width is not None and 0 < opinion.width < 20000 else None
    version = strip_controls(opinion.version or "")[:VERSION_MAX] or None
    return Opinion(text, email, page, width, version, ref)


def screen(key: str) -> str:
    """The screen counted for a key the interface sent (empty: the start page)."""
    first = key.strip("/").split("/")[0].split("?")[0]
    if not first:
        return HOME_SCREEN
    return first if first in SCREENS else OTHER_SCREEN


class FeedbackFull(Exception):
    """A global feedback cap was reached (per minute, per day or of the file). The message is
    shown to the visitor."""


@dataclass(frozen=True)
class Caps:
    """Global feedback caps (besides the per-copy cap, in `demo.app`)."""

    per_minute: int = 10
    per_day: int = 300
    rows: int = 10_000
    bytes: int = 20 * 1024 * 1024


def exists(directory: Path) -> bool:
    """Whether `directory` has a feedback store (this release's or the one before the rename)."""
    return (directory / FILENAME).is_file() or (directory / legacy.FEEDBACK_FILE).is_file()


class Feedback:
    """`feedback.db` at `path`; every operation opens and closes its connection.

    Usage counts are gathered in memory and written in batches (`flush`, which the background
    maintenance runs every minute, and before reading them): a visit does not write to disk."""

    def __init__(self, path: Path, caps: Caps = Caps()) -> None:
        self.path = path
        self.caps = caps
        self._pending: Counter[tuple[str, str, str]] = Counter()
        self._recent: deque[float] = deque()
        self._lock = threading.Lock()
        old = path.with_name(legacy.FEEDBACK_FILE)
        if not path.exists() and old.is_file():
            _build_from_legacy(path, old)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        path.chmod(0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    def save(self, opinion: Opinion, now: datetime | None = None) -> int:
        """Stores the feedback, cleaned; `FeedbackFull` if a global cap was reached."""
        ok = clean(opinion)
        moment = now or datetime.now(UTC)
        with self._lock:
            self._check_minute(moment.timestamp())
            with self._connect() as conn:
                self._check_totals(conn, moment.date())
                cursor = conn.execute(
                    "INSERT INTO feedback (created_at, text, email, page, width, version, ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        moment.isoformat(timespec="seconds"),
                        ok.text,
                        ok.email,
                        ok.page,
                        ok.width,
                        ok.version,
                        ok.ref,
                    ),
                )
            self._recent.append(moment.timestamp())
            return int(cursor.lastrowid or 0)

    def _check_minute(self, now: float) -> None:
        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        if len(self._recent) >= self.caps.per_minute:
            raise FeedbackFull(t("demo.feedback.per_minute"))

    def _check_totals(self, conn: sqlite3.Connection, day: date) -> None:
        today = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE created_at LIKE ?", (f"{day.isoformat()}%",)
        ).fetchone()[0]
        if today >= self.caps.per_day:
            raise FeedbackFull(t("demo.feedback.per_day"))
        total = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        if total >= self.caps.rows or self.path.stat().st_size >= self.caps.bytes:
            raise FeedbackFull(t("demo.feedback.store_full"))

    def count(self, kind: str, key: str, day: date | None = None) -> None:
        """Adds one to the day's count (`kind` from `KINDS`; the key, already normalized). It
        stays in memory until the next `flush`."""
        if kind not in KINDS:
            raise ValueError(f"unknown usage kind: {kind}")
        when = (day or datetime.now(UTC).date()).isoformat()
        with self._lock:
            self._pending[(when, kind, key)] += 1

    def flush(self) -> None:
        """Writes the gathered counts; if it fails, they go back to the queue."""
        with self._lock:
            pending, self._pending = self._pending, Counter()
        if not pending:
            return
        try:
            with self._connect() as conn:
                conn.executemany(
                    "INSERT INTO usage (day, kind, key, count) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(day, kind, key) DO UPDATE SET count = count + excluded.count",
                    [(*key, amount) for key, amount in pending.items()],
                )
        except sqlite3.Error:
            with self._lock:
                self._pending.update(pending)
            raise

    def opinions(self) -> list[Stored]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM feedback ORDER BY id DESC").fetchall()
        return [Stored(**dict(row)) for row in rows]

    def usage(self) -> list[dict[str, str | int]]:
        self.flush()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT day, kind, key, count FROM usage ORDER BY day DESC, kind, key"
            ).fetchall()
        return [dict(row) for row in rows]


def _build_from_legacy(path: Path, old: Path) -> None:
    """Writes the migrated store to a temporary file next to `path` and renames it into place,
    so a failure leaves no `feedback.db` behind and the migration is retried on the next start."""
    staging = path.with_name(f".{path.name}.migrating-{os.getpid()}")
    staging.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(staging)) as conn:
            conn.executescript(_SCHEMA)
            with conn:
                _migrate_legacy(conn, old)
        staging.chmod(0o600)
        os.replace(staging, path)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


def _migrate_legacy(conn: sqlite3.Connection, old: Path) -> None:
    """Copies every row of the pre-rename store (`legacy.FEEDBACK_FILE`) into the new tables,
    with its usage kinds, keys and screens in English (a value with no translation is kept as
    it was). Runs on the staging copy built by `_build_from_legacy`."""
    with closing(sqlite3.connect(f"{old.resolve().as_uri()}?mode=ro", uri=True)) as source:
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master")}
        if legacy.FEEDBACK_TABLE in tables:
            columns = ", ".join(legacy.FEEDBACK_COLUMNS)
            rows = source.execute(f"SELECT {columns} FROM {legacy.FEEDBACK_TABLE}").fetchall()
            conn.executemany(
                f"INSERT INTO feedback ({', '.join(legacy.FEEDBACK_COLUMNS.values())}) "
                f"VALUES ({', '.join('?' for _ in legacy.FEEDBACK_COLUMNS)})",
                rows,
            )
        if legacy.USAGE_TABLE in tables:
            columns = ", ".join(legacy.USAGE_COLUMNS)
            rows = source.execute(f"SELECT {columns} FROM {legacy.USAGE_TABLE}").fetchall()
            conn.executemany(
                "INSERT INTO usage (day, kind, key, count) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day, kind, key) DO UPDATE SET count = count + excluded.count",
                [(day, *legacy.usage_row(kind, key), count) for day, kind, key, count in rows],
            )


def as_dict(opinion: Stored) -> dict[str, object]:
    return asdict(opinion)
