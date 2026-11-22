"""Receipt storage: what merchants' emails say and the transactions they are linked to
(schema 24, `migrations_v24`).

- `record` reads a merchant email in memory and stores only its fields (or, if it cannot be
  read, the data-free failure fingerprint, as for alerts). Idempotent by message id. A failed
  one is asked for again (`known_message_ids`) only if it can succeed later: never an
  unauthenticated, unknown or oversized email (`PERMANENT`), and any other only once the readers
  changed (`READER_VERSION`).
- `load` gives every receipt with its order numbers and links; `by_fingerprint`, the receipts
  of each linked transaction.
- `link`, `unlink` and `dismiss` change the links; `taken` and `dismissed` are what
  `receipt_match.match` needs to know about them.

Nothing here commits: the caller wraps it in `with conn:`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from michelito import receipts
from michelito.alerts.common import AlertEmail, AlertParseError, failure_fingerprint, failure_json
from michelito.receipts import Receipt

Outcome = Literal["known", "stored", "failed"]
Origin = Literal["automatic", "confirmed"]

UNKNOWN_TYPE = "unknown"
# Bump when a reader changes: the emails that failed with the previous one are read again.
READER_VERSION = "1"
# Failures that no reader change can fix: they are never asked for again.
PERMANENT = frozenset({"authentication", "type", "size"})
_CENTS = 100


@dataclass(frozen=True)
class Stored:
    """A receipt as stored, with its order numbers and the transactions it is linked to."""

    id: int
    message_id: str
    source: str
    parser: str
    received_at: datetime
    merchant: str
    kind: str
    orders: tuple[str, ...]
    amount_cents: int
    currency: str
    reference: str
    link: str
    summary: str
    item_count: int | None
    links: tuple[str, ...] = ()  # fingerprints

    @property
    def day(self) -> date:
        return self.received_at.date()


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'receipt_links'"
    ).fetchone()
    return row is not None


def _retryable(failure: str | None) -> bool:
    try:
        found = json.loads(failure or "{}")
    except ValueError:
        return False
    if found.get("failed_field") in PERMANENT:
        return False
    return found.get("reader_version") != READER_VERSION


def known_message_ids(conn: sqlite3.Connection) -> set[str]:
    """Message ids that need no further work: every stored email except the failed ones that
    may succeed now (see the module)."""
    rows = conn.execute("SELECT message_id, status, failure FROM receipt_emails")
    return {str(r[0]) for r in rows if r[1] != "failed" or not _retryable(r[2])}


def record(conn: sqlite3.Connection, email: AlertEmail, source: str, now: str) -> Outcome:
    """Read the email and store its receipts (in the caller's transaction)."""
    existing = conn.execute(
        "SELECT status FROM receipt_emails WHERE message_id = ?", (email.message_id,)
    ).fetchone()
    if existing is not None and existing[0] != "failed":
        return "known"
    reader = receipts.detect(email)
    name = UNKNOWN_TYPE if reader is None else reader.NAME
    try:
        if reader is None:
            raise AlertParseError("type")
        found = reader.parse(email)
    except AlertParseError as error:
        described = failure_fingerprint(email, name, error)
        failure = failure_json({**described, "reader_version": READER_VERSION})
        _upsert_failed(conn, email, source, name, failure, now)
        return "failed"
    if existing is not None:
        conn.execute("DELETE FROM receipt_emails WHERE message_id = ?", (email.message_id,))
    _insert(conn, email, source, name, found, now)
    return "stored"


def record_error(
    conn: sqlite3.Connection, message_id: str, source: str, error: str, now: str
) -> None:
    """A message that could not even be read (an unexpected error): stored as failed, with the
    error's class name only, so the sync goes on and asks for it again next time."""
    failure = failure_json({"alert_type": UNKNOWN_TYPE, "failed_field": "error", "error": error})
    conn.execute(
        "INSERT INTO receipt_emails (message_id, source, received_at, status, failure, "
        "created_at, updated_at) VALUES (?, ?, ?, 'failed', ?, ?, ?) "
        "ON CONFLICT(message_id) DO UPDATE SET failure = excluded.failure, "
        "updated_at = excluded.updated_at",
        (message_id[:200], source, now, failure, now, now),
    )


def _upsert_failed(
    conn: sqlite3.Connection, email: AlertEmail, source: str, reader: str, failure: str, now: str
) -> None:
    conn.execute(
        "INSERT INTO receipt_emails (message_id, source, parser, received_at, status, failure, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, 'failed', ?, ?, ?) "
        "ON CONFLICT(message_id) DO UPDATE SET failure = excluded.failure, "
        "parser = excluded.parser, updated_at = excluded.updated_at",
        (email.message_id, source, reader, email.received_at.isoformat(), failure, now, now),
    )


def _insert(
    conn: sqlite3.Connection,
    email: AlertEmail,
    source: str,
    reader: str,
    found: tuple[Receipt, ...],
    now: str,
) -> None:
    # The subject's summary and count are the whole email's: with several receipts they say
    # nothing about each one.
    first = found[0] if len(found) == 1 else None
    cursor = conn.execute(
        "INSERT INTO receipt_emails (message_id, source, parser, received_at, status, summary, "
        "item_count, created_at, updated_at) VALUES (?, ?, ?, ?, 'read', ?, ?, ?, ?)",
        (
            email.message_id,
            source,
            reader,
            email.received_at.isoformat(),
            "" if first is None else first.summary[: receipts.SUMMARY_MAX],
            None if first is None else first.item_count,
            now,
            now,
        ),
    )
    email_id = cursor.lastrowid
    for position, receipt in enumerate(found):
        inserted = conn.execute(
            "INSERT INTO receipts (email_id, position, merchant, kind, amount_cents, currency, "
            "reference, link) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email_id,
                position,
                receipt.merchant,
                receipt.kind,
                int(receipt.amount * _CENTS),
                receipt.currency,
                receipt.reference,
                receipt.link,
            ),
        )
        conn.executemany(
            "INSERT INTO receipt_orders (receipt_id, order_number, position) VALUES (?, ?, ?)",
            [(inserted.lastrowid, order, index) for index, order in enumerate(receipt.orders)],
        )


_RECEIPTS = """
SELECT r.id, e.message_id, e.source, e.parser, e.received_at, r.merchant, r.kind,
       r.amount_cents, r.currency, r.reference, r.link, e.summary, e.item_count
FROM receipts r
JOIN receipt_emails e ON e.id = r.email_id
WHERE e.status = 'read' {only}
ORDER BY e.received_at, e.id, r.position
"""
_LINKED = "AND EXISTS (SELECT 1 FROM receipt_links l WHERE l.receipt_id = r.id)"


def load(conn: sqlite3.Connection, linked_only: bool = False) -> tuple[Stored, ...]:
    """Every receipt, oldest email first, with its order numbers and links. `linked_only`: only
    the ones linked to a transaction (what the transactions list needs: nothing is read when
    there are no links)."""
    if not _has_tables(conn):
        return ()
    if linked_only and conn.execute("SELECT 1 FROM receipt_links LIMIT 1").fetchone() is None:
        return ()
    orders: dict[int, list[str]] = {}
    for receipt_id, order in conn.execute(
        "SELECT receipt_id, order_number FROM receipt_orders ORDER BY receipt_id, position"
    ):
        orders.setdefault(int(receipt_id), []).append(str(order))
    links: dict[int, list[str]] = {}
    for receipt_id, fingerprint in conn.execute(
        "SELECT receipt_id, fingerprint FROM receipt_links ORDER BY receipt_id, fingerprint"
    ):
        links.setdefault(int(receipt_id), []).append(str(fingerprint))
    return tuple(
        Stored(
            id=int(row[0]),
            message_id=str(row[1]),
            source=str(row[2]),
            parser=str(row[3] or ""),
            received_at=datetime.fromisoformat(row[4]),
            merchant=str(row[5]),
            kind=str(row[6]),
            orders=tuple(orders.get(int(row[0]), ())),
            amount_cents=int(row[7]),
            currency=str(row[8]),
            reference=str(row[9]),
            link=str(row[10]),
            summary=str(row[11]),
            item_count=None if row[12] is None else int(row[12]),
            links=tuple(links.get(int(row[0]), ())),
        )
        for row in conn.execute(_RECEIPTS.format(only=_LINKED if linked_only else "")).fetchall()
    )


def by_fingerprint(conn: sqlite3.Connection) -> dict[str, tuple[Stored, ...]]:
    """The receipts of each linked transaction, oldest email first."""
    found: dict[str, tuple[Stored, ...]] = {}
    for receipt in load(conn, linked_only=True):
        for fingerprint in receipt.links:
            found[fingerprint] = (*found.get(fingerprint, ()), receipt)
    return found


def taken(conn: sqlite3.Connection) -> dict[str, frozenset[str]]:
    """For each linked transaction, the order numbers of its receipts."""
    return {
        fingerprint: frozenset(order for receipt in linked for order in receipt.orders)
        for fingerprint, linked in by_fingerprint(conn).items()
    }


def origins(conn: sqlite3.Connection) -> dict[tuple[int, str], str]:
    """Who made each link: (receipt id, fingerprint) -> "automatic" or "confirmed"."""
    if not _has_tables(conn):
        return {}
    rows = conn.execute("SELECT receipt_id, fingerprint, origin FROM receipt_links")
    return {(int(receipt_id), str(mark)): str(origin) for receipt_id, mark, origin in rows}


def dismissed(conn: sqlite3.Connection) -> set[tuple[int, str]]:
    if not _has_tables(conn):
        return set()
    rows = conn.execute("SELECT receipt_id, fingerprint FROM receipt_dismissals")
    return {(int(receipt_id), str(fingerprint)) for receipt_id, fingerprint in rows}


def link(
    conn: sqlite3.Connection, receipt_id: int, fingerprint: str, origin: Origin, now: str
) -> None:
    """Link a receipt to a transaction (an existing link keeps its origin and date). Linking a
    pair that had been dismissed forgets the dismissal."""
    conn.execute(
        "INSERT INTO receipt_links (receipt_id, fingerprint, origin, linked_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT (receipt_id, fingerprint) DO NOTHING",
        (receipt_id, fingerprint, origin, now),
    )
    conn.execute(
        "DELETE FROM receipt_dismissals WHERE receipt_id = ? AND fingerprint = ?",
        (receipt_id, fingerprint),
    )


def move_link(conn: sqlite3.Connection, receipt_id: int, old: str, new: str) -> None:
    """The transaction changed fingerprint (a provisional became its statement row): the link
    follows it, keeping who made it and when."""
    conn.execute(
        "UPDATE OR IGNORE receipt_links SET fingerprint = ? "
        "WHERE receipt_id = ? AND fingerprint = ?",
        (new, receipt_id, old),
    )
    drop_link(conn, receipt_id, old)  # if the new pair already existed, the old row is left over


def drop_link(conn: sqlite3.Connection, receipt_id: int, fingerprint: str) -> None:
    """Remove a link without remembering it (its transaction is gone: nobody refused it)."""
    conn.execute(
        "DELETE FROM receipt_links WHERE receipt_id = ? AND fingerprint = ?",
        (receipt_id, fingerprint),
    )


def dismiss(conn: sqlite3.Connection, receipt_id: int, fingerprint: str, now: str) -> None:
    """The person said this receipt is not about this transaction: never offered again."""
    conn.execute(
        "INSERT INTO receipt_dismissals (receipt_id, fingerprint, dismissed_at) "
        "VALUES (?, ?, ?) ON CONFLICT (receipt_id, fingerprint) DO NOTHING",
        (receipt_id, fingerprint, now),
    )


def unlink(conn: sqlite3.Connection, receipt_id: int, fingerprint: str, now: str) -> None:
    """Remove a link and remember it, so the same pair is not linked or offered again."""
    conn.execute(
        "DELETE FROM receipt_links WHERE receipt_id = ? AND fingerprint = ?",
        (receipt_id, fingerprint),
    )
    dismiss(conn, receipt_id, fingerprint, now)


def failures(conn: sqlite3.Connection) -> list[dict[str, str]]:
    """The data-free description of each email that could not be read."""
    if not _has_tables(conn):
        return []
    rows = conn.execute(
        "SELECT failure FROM receipt_emails WHERE status = 'failed' ORDER BY received_at, id"
    )
    return [json.loads(row[0]) for row in rows]
