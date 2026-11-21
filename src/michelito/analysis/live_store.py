"""Live sync storage: the alerts table and the user's decisions on provisionals (schema 20).

- `record` parses an alert email in memory and stores only its fields (or, if it cannot be
  read, the data-free failure fingerprint). Idempotent by message id. A failed one is downloaded
  again (`known_message_ids`) only if it can succeed later: never an unauthenticated, unknown or
  oversized email (`PERMANENT`), and any other only once the parser changed (`PARSER_VERSION`)
  or if it failed with an unexpected error. A resent alert (same card, currency, amount,
  merchant and status within `RESEND_MINUTES`) is stored as `'duplicate'`, not as a second
  provisional.
- `load` gives what `spending.load_all` needs: the provisional transactions (not discarded) and
  the aliases (the content fingerprint of a statement row that confirmed a provisional -> the
  provisional's fingerprint, `alert-<id>`), so the confirmed row keeps the provisional's
  identity and everything linked to it.
- `unmatched`: provisionals that should already be in a statement and are not; `reversals`:
  the ones a reversal alert could not void (they are linked) or that the statement charged
  anyway.

Nothing here commits: the caller wraps it in `with conn:`. `reconcile` (`live_match`) resolves
cards and confirms provisionals.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from michelito import alerts
from michelito.alerts.common import (
    Alert,
    AlertEmail,
    AlertParseError,
    failure_fingerprint,
    failure_json,
)

FINGERPRINT_PREFIX = "alert-"
# A provisional is expected in the statement dated up to this many days after its alert (and
# from one day before it); see `live_match`.
DAYS_BEFORE = 1
DAYS_AFTER = 5
UNKNOWN_TYPE = "unknown"

# "void": a reversal or decline alert cancelled it (`live_match`), as a logged decision.
Decision = Literal["discard", "keep", "void"]
Outcome = Literal["known", "stored", "failed"]

_KIND_STATUS = {
    "approved": "unknown_card",  # `live_match.reconcile` resolves the card
    "declined": "declined",
    "reversed": "reversed",
    "unknown": "unknown_status",
}


def fingerprint(alert_id: int) -> str:
    return f"{FINGERPRINT_PREFIX}{alert_id}"


def is_provisional(mark: str) -> bool:
    return mark.startswith(FINGERPRINT_PREFIX)


def alert_id(mark: str) -> int | None:
    if not is_provisional(mark):
        return None
    rest = mark[len(FINGERPRINT_PREFIX) :]
    return int(rest) if rest.isdigit() else None


@dataclass(frozen=True)
class Provisional:
    id: int
    account: str  # accounts.key
    institution: str
    kind: str  # the account's kind (always a card for now)
    day: date
    amount_cents: int
    currency: str
    merchant: str

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.id)


@dataclass(frozen=True)
class Live:
    provisionals: tuple[Provisional, ...] = ()
    aliases: Mapping[str, str] = field(default_factory=dict)


NONE = Live()


# Bump when an alert parser changes: the alerts that failed with the previous one are retried.
PARSER_VERSION = "2"
# Failures that no parser change can fix: they are never downloaded again.
PERMANENT = frozenset({"authentication", "type", "size"})
RESEND_MINUTES = 10


def _retryable(failure: str | None) -> bool:
    try:
        found = json.loads(failure or "{}")
    except ValueError:
        return False
    if found.get("failed_field") in PERMANENT:
        return False
    # An unexpected error (`record_error`) has no version: it is retried.
    return found.get("parser_version") != PARSER_VERSION


def known_message_ids(conn: sqlite3.Connection) -> set[str]:
    """Message ids that need no further work: every stored alert except the failed ones that
    may succeed now (see the module)."""
    rows = conn.execute("SELECT message_id, status, failure FROM alerts")
    return {str(r[0]) for r in rows if r[1] != "failed" or not _retryable(r[2])}


def record(conn: sqlite3.Connection, email: AlertEmail, source: str, now: str) -> Outcome:
    """Parse the alert and store its fields (in the caller's transaction)."""
    existing = conn.execute(
        "SELECT status FROM alerts WHERE message_id = ?", (email.message_id,)
    ).fetchone()
    if existing is not None and existing[0] != "failed":
        return "known"
    parser = alerts.detect(email)
    name = UNKNOWN_TYPE if parser is None else parser.NAME
    try:
        if parser is None:
            raise AlertParseError("type")
        found = parser.parse(email)
    except AlertParseError as error:
        found_failure = failure_fingerprint(email, name, error)
        failure = failure_json({**found_failure, "parser_version": PARSER_VERSION})
        _upsert_failed(conn, email, source, name, failure, now)
        return "failed"
    if existing is not None:
        conn.execute("DELETE FROM alerts WHERE message_id = ?", (email.message_id,))
    _insert(conn, email, source, found, now, _is_resent(conn, email, found))
    return "stored"


def _is_resent(conn: sqlite3.Connection, email: AlertEmail, alert: Alert) -> bool:
    """The bank sent the same alert again: same card, currency, cents, merchant and status,
    received within RESEND_MINUTES of one already stored."""
    rows = conn.execute(
        "SELECT received_at FROM alerts WHERE status NOT IN ('failed', 'duplicate') "
        "AND last4 = ? AND currency = ? AND amount_cents = ? AND merchant = ? AND bank_status = ?",
        (alert.last4, alert.currency, int(alert.amount * 100), alert.merchant[:200], alert.status),
    ).fetchall()
    window = timedelta(minutes=RESEND_MINUTES)
    for (received,) in rows:
        other = datetime.fromisoformat(received)
        if abs(other - email.received_at) <= window:
            return True
    return False


@dataclass(frozen=True)
class Made:
    """A made-up provisional (demo and test servers): what an alert would have said."""

    message_id: str
    account: str  # accounts.key, already known
    last4: str
    day: date
    amount_cents: int
    currency: str
    merchant: str


def add_made_up(conn: sqlite3.Connection, made: Made, now: str) -> str:
    """Store a made-up provisional without an email (the demo and the e2e server have no
    alerts); returns its fingerprint. Real alerts go through `record`."""
    cursor = conn.execute(
        "INSERT INTO alerts (message_id, source, parser, received_at, status, bank_status, "
        "last4, account_key, day, amount_cents, currency, merchant, created_at, updated_at) "
        "VALUES (?, 'demo', 'demo', ?, 'provisional', 'approved', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            made.message_id,
            now,
            made.last4,
            made.account,
            made.day.isoformat(),
            made.amount_cents,
            made.currency,
            made.merchant,
            now,
            now,
        ),
    )
    return fingerprint(int(cursor.lastrowid or 0))


def record_error(
    conn: sqlite3.Connection, message_id: str, source: str, error: str, now: str
) -> None:
    """A message that could not even be read (an unexpected error): stored as failed, with the
    error's class name only, so the sync goes on and retries it next time."""
    failure = failure_json({"alert_type": UNKNOWN_TYPE, "failed_field": "error", "error": error})
    conn.execute(
        "INSERT INTO alerts (message_id, source, received_at, status, failure, created_at, "
        "updated_at) VALUES (?, ?, ?, 'failed', ?, ?, ?) ON CONFLICT(message_id) DO UPDATE SET "
        "failure = excluded.failure, updated_at = excluded.updated_at",
        (message_id[:200], source, now, failure, now, now),
    )


def _insert(
    conn: sqlite3.Connection,
    email: AlertEmail,
    source: str,
    alert: Alert,
    now: str,
    resent: bool = False,
) -> None:
    conn.execute(
        "INSERT INTO alerts (message_id, source, parser, received_at, status, bank_status, "
        "last4, day, amount_cents, currency, merchant, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            email.message_id,
            source,
            alert.parser,
            email.received_at.isoformat(),
            "duplicate" if resent else _KIND_STATUS[alert.kind],
            alert.status,
            alert.last4,
            alert.day.isoformat(),
            int(alert.amount * 100),
            alert.currency,
            alert.merchant[:200],
            now,
            now,
        ),
    )


def _upsert_failed(
    conn: sqlite3.Connection, email: AlertEmail, source: str, parser: str, failure: str, now: str
) -> None:
    conn.execute(
        "INSERT INTO alerts (message_id, source, parser, received_at, status, failure, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, 'failed', ?, ?, ?) "
        "ON CONFLICT(message_id) DO UPDATE SET failure = excluded.failure, "
        "parser = excluded.parser, updated_at = excluded.updated_at",
        (email.message_id, source, parser, email.received_at.isoformat(), failure, now, now),
    )


_PROVISIONALS = """
SELECT al.id, al.account_key, a.institution, a.kind, al.day, al.amount_cents, al.currency,
       al.merchant
FROM alerts al
JOIN accounts a ON a.key = al.account_key
LEFT JOIN provisional_decisions d
    ON d.fingerprint = 'alert-' || al.id AND d.decision IN ('discard', 'void')
WHERE al.status = 'provisional' AND d.fingerprint IS NULL
ORDER BY al.day, al.id
"""


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'provisional_decisions'"
    ).fetchone()
    return row is not None


def load(conn: sqlite3.Connection) -> Live:
    """Nothing on a database that does not have the live-sync tables yet (an earlier schema read
    mid-migration, as schema 19's step and its check script do)."""
    if not _has_tables(conn):
        return NONE
    provisionals = tuple(
        Provisional(
            id=row[0],
            account=row[1],
            institution=row[2],
            kind=row[3],
            day=date.fromisoformat(row[4]),
            amount_cents=row[5],
            currency=row[6],
            merchant=row[7],
        )
        for row in conn.execute(_PROVISIONALS)
    )
    aliases = {
        str(row[0]): fingerprint(int(row[1]))
        for row in conn.execute(
            "SELECT statement_fingerprint, id FROM alerts "
            "WHERE status = 'confirmed' AND keeps_identity = 1"
        )
    }
    if not provisionals and not aliases:
        return NONE
    return Live(provisionals, aliases)


def decisions(conn: sqlite3.Connection) -> dict[str, Decision]:
    rows = conn.execute("SELECT fingerprint, decision FROM provisional_decisions")
    return {str(row[0]): row[1] for row in rows}


def decide(conn: sqlite3.Connection, mark: str, decision: Decision | None, now: str) -> None:
    """Record "Discard" or "Keep" for a provisional (None: forget the decision). Discarding or
    voiding it also drops the automatic "moved into cash" mark, if the system put one."""
    if decision is None:
        conn.execute("DELETE FROM provisional_decisions WHERE fingerprint = ?", (mark,))
        return
    if decision in ("discard", "void"):
        _drop_auto_mark(conn, mark)
    conn.execute(
        "INSERT INTO provisional_decisions (fingerprint, decision, decided_at) VALUES (?, ?, ?) "
        "ON CONFLICT(fingerprint) DO UPDATE SET decision = excluded.decision, "
        "decided_at = excluded.decided_at",
        (mark, decision, now),
    )


def unmatched(conn: sqlite3.Connection) -> dict[str, date]:
    """Provisionals (not discarded) whose matching window is already covered by a statement of
    their account and that no statement row confirmed: fingerprint -> the closing date of the
    statement that covers the alert's date (the one it should have been in)."""
    found: dict[str, date] = {}
    rows = conn.execute(
        "SELECT al.id, al.day, "
        "(SELECT MAX(s.period_end) FROM statements s JOIN accounts a ON a.id = s.account_id "
        " WHERE a.key = al.account_key) AS newest "
        "FROM alerts al WHERE al.status = 'provisional'"
    ).fetchall()
    discarded = {fp for fp, d in decisions(conn).items() if d in ("discard", "void")}
    for row in rows:
        mark = fingerprint(int(row[0]))
        if row[2] is None or mark in discarded:
            continue
        day = date.fromisoformat(row[1])
        if date.fromisoformat(row[2]) < day + timedelta(days=DAYS_AFTER):
            continue
        covering = conn.execute(
            "SELECT MIN(s.period_end) FROM statements s JOIN accounts a ON a.id = s.account_id "
            "JOIN alerts al ON al.account_key = a.key WHERE al.id = ? AND s.period_end >= ?",
            (row[0], day.isoformat()),
        ).fetchone()[0]
        found[mark] = date.fromisoformat(covering)
    return found


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    """How many alerts there are in each status (for the report)."""
    rows = conn.execute("SELECT status, COUNT(*) FROM alerts GROUP BY status")
    return {str(row[0]): int(row[1]) for row in rows}


def failures(conn: sqlite3.Connection) -> list[dict[str, str]]:
    """The data-free fingerprints of the alerts that could not be read."""
    rows = conn.execute("SELECT failure FROM alerts WHERE status = 'failed' ORDER BY id")
    return [json.loads(row[0]) for row in rows if row[0]]


def _table(conn: sqlite3.Connection, name: str) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return found is not None


def is_linked(conn: sqlite3.Connection, mark: str) -> bool:
    """The fingerprint is in a link (`link_members`) or in the shared ledger (`ledger_links`):
    discarding or voiding it would leave that link pointing at nothing. A mark the system put
    (`cash_auto_marks`, a withdrawal moved into cash automatically) does not count: `decide`
    drops it."""
    for table in ("link_members", "ledger_links"):
        if _table(conn, table):
            found = conn.execute(
                f"SELECT 1 FROM {table} WHERE fingerprint = ? LIMIT 1", (mark,)
            ).fetchone()
            if found is not None and not (table == "link_members" and _auto_marked(conn, mark)):
                return True
    return False


def in_cash(conn: sqlite3.Connection, mark: str) -> bool:
    """Its link is the cash account (moved into cash or deposited from it), by hand."""
    found = conn.execute(
        "SELECT 1 FROM link_members m JOIN links l ON l.id = m.link_id "
        "WHERE m.fingerprint = ? AND l.kind = 'cash_box'",
        (mark,),
    ).fetchone()
    return found is not None


def _auto_marked(conn: sqlite3.Connection, mark: str) -> bool:
    if not _table(conn, "cash_auto_marks"):
        return False
    return (
        conn.execute("SELECT 1 FROM cash_auto_marks WHERE fingerprint = ?", (mark,)).fetchone()
        is not None
    )


def _drop_auto_mark(conn: sqlite3.Connection, mark: str) -> None:
    """A discarded or voided movement never was cash: the system's mark goes with it."""
    if not _auto_marked(conn, mark):
        return
    conn.execute(
        "DELETE FROM link_members WHERE fingerprint = ? AND role = 'stored' "
        "AND link_id IN (SELECT id FROM links WHERE kind = 'cash_box')",
        (mark,),
    )
    conn.execute("DELETE FROM cash_auto_marks WHERE fingerprint = ?", (mark,))


Reversal = Literal["pending", "charged"]


def reversals(conn: sqlite3.Connection) -> dict[str, Reversal]:
    """Purchases a reversal alert named but that still count, by the fingerprint they have now:
    "pending", a provisional the reversal could not void (it is linked, or the void was undone);
    "charged", one the statement had anyway (confirmed after the reversal)."""
    found: dict[str, Reversal] = {}
    cancelled = {fp for fp, d in decisions(conn).items() if d in ("discard", "void")}
    rows = conn.execute(
        "SELECT id, status, statement_fingerprint, keeps_identity FROM alerts "
        "WHERE voided_by IS NOT NULL AND status IN ('provisional', 'confirmed')"
    )
    for alert_id, status, statement, keeps in rows:
        mark = fingerprint(int(alert_id))
        if status == "provisional" and mark not in cancelled:
            found[mark] = "pending"
        elif status == "confirmed":
            found[mark if keeps else str(statement)] = "charged"
    return found
