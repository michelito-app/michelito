""" "Efectivo" (cash) activation and the automatic pass (schema 23).

The cash account is *activated* the first time the user writes something in it after schema 23
(an entry, a schedule or a reconcile; `activate`), on that day (the local date of the action,
not the date of what was written). A box already in use before schema 23 was activated by the
migration from the day after the upgrade (`migrations_v23`). The date lives in `cash_settings`,
outside the change log: undoing the first entry does not deactivate it.

From the activation date on, every ATM withdrawal (`cash_box.can_store`: a cash-category debit
from a bank or a card with no other link) is moved into cash automatically: the pass stores the
usual `'stored'` mark (`cash_box_store.store`), so everything downstream (the flow, the balance,
the transaction detail) treats it like one the user marked by hand. A withdrawal the user said
was "I spent it directly" (`cash_spent_direct`) is left as spending and never marked again.
Withdrawals dated before the activation are never touched.

`refresh` runs on every load (the board opens a connection per request) and on `sync`, outside
the change log: it materializes the scheduled occurrences due (`cash_schedule_store`) and, only
when its inputs changed since the last pass (`_marker`: the statements, the alerts and the change
log), the automatic marks. Both are idempotent.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime

from michelito.analysis import cash_box, cash_box_store, cash_schedule_store, links
from michelito.analysis.accounts import CASH_BOX_KEY
from michelito.analysis.spending import Movement

LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
LOG = logging.getLogger(__name__)

# What the automatic marks depend on: the statement rows (count, ids and content, so a
# `parse --retry` that rebuilds them counts), the alerts and the change log (every user change).
_MARKER = """
SELECT (SELECT COUNT(*) || ':' || COALESCE(MAX(id), 0) || ':' || COALESCE(SUM(amount_cents), 0)
        || ':' || COALESCE(SUM(length(description)), 0) FROM transactions)
    || '/' || (SELECT COUNT(*) || ':' || COALESCE(MAX(id), 0) FROM statements)
    || '/' || (SELECT COUNT(*) || ':' || COALESCE(MAX(updated_at), '') FROM alerts)
    || '/' || (SELECT COALESCE(MAX(id), 0) FROM change_log)
"""


def activated_on(conn: sqlite3.Connection, account_key: str = CASH_BOX_KEY) -> date | None:
    row = conn.execute(
        "SELECT activated_on FROM cash_settings WHERE account_key = ?", (account_key,)
    ).fetchone()
    return None if row is None else date.fromisoformat(row[0])


def activate(conn: sqlite3.Connection, today: date, account_key: str = CASH_BOX_KEY) -> date:
    """Activates the account on `today` unless it already is; returns the activation date."""
    conn.execute(
        "INSERT INTO cash_settings (account_key, activated_on) VALUES (?, ?) "
        "ON CONFLICT(account_key) DO NOTHING",
        (account_key, today.isoformat()),
    )
    found = activated_on(conn, account_key)
    return today if found is None else found


def spent_direct(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(row[0] for row in conn.execute("SELECT fingerprint FROM cash_spent_direct"))


def set_spent_direct(conn: sqlite3.Connection, fingerprint: str, spent: bool) -> None:
    """Records (or forgets) "I spent it directly" for a withdrawal."""
    if spent:
        conn.execute(
            "INSERT INTO cash_spent_direct (fingerprint, created_at) VALUES (?, ?) "
            "ON CONFLICT(fingerprint) DO NOTHING",
            (fingerprint, _now()),
        )
    else:
        conn.execute("DELETE FROM cash_spent_direct WHERE fingerprint = ?", (fingerprint,))


def auto_candidates(
    flow: Sequence[Movement],
    found: links.Links,
    since: date,
    spent: frozenset[str],
) -> list[str]:
    """The withdrawals to move into cash: those `can_store` accepts, dated on or after `since`,
    that the user did not keep as spending. A provisional one (a bank alert) waits for its
    statement row: the alert may still be discarded or reversed, and the row that confirms it
    keeps its fingerprint, so it is marked then."""
    return [
        move.fingerprint
        for move in flow
        if move.day >= since
        and not move.provisional
        and move.fingerprint not in spent
        and cash_box.can_store(move, found)
    ]


def record_auto(conn: sqlite3.Connection, fingerprints: Sequence[str]) -> None:
    """Remembers which `stored` marks the system put (`cash_auto_marks`): discarding or voiding
    that movement may drop them (`live_store.decide`)."""
    conn.executemany(
        "INSERT INTO cash_auto_marks (fingerprint, created_at) VALUES (?, ?) "
        "ON CONFLICT(fingerprint) DO NOTHING",
        [(fingerprint, _now()) for fingerprint in fingerprints],
    )


def auto_store(
    conn: sqlite3.Connection, flow: Sequence[Movement], account_key: str = CASH_BOX_KEY
) -> list[str]:
    """Marks every candidate as stored (nothing before the activation; nothing if the account was
    never activated). Returns the fingerprints marked."""
    since = activated_on(conn, account_key)
    if since is None:
        return []
    marked = auto_candidates(flow, links.load(conn), since, spent_direct(conn))
    for fingerprint in marked:
        cash_box_store.store(conn, fingerprint, account_key)
    record_auto(conn, marked)
    return marked


def forget_auto(conn: sqlite3.Connection, fingerprint: str) -> None:
    """The mark is gone ("I spent it directly"): so is the note that the system put it."""
    conn.execute("DELETE FROM cash_auto_marks WHERE fingerprint = ?", (fingerprint,))


def marker(conn: sqlite3.Connection, extra: str = "") -> str:
    """The inputs of the automatic marks; `extra`: what the caller adds (the holders)."""
    return f"{conn.execute(_MARKER).fetchone()[0]}/{extra}"


def refresh(conn: sqlite3.Connection, today: date, load_flow: LoadFlow, extra: str = "") -> None:
    """The system pass (see the module docstring), in its own transaction. When nothing is due
    and the marker did not change, it only reads (no write lock is taken). `extra`: more inputs
    of the marker (the holders, which decide what is a transfer)."""
    with conn:
        cash_schedule_store.materialize(conn, today)
        row = conn.execute(
            "SELECT activated_on, scan_marker FROM cash_settings WHERE account_key = ?",
            (CASH_BOX_KEY,),
        ).fetchone()
        if row is None:
            return
        current = f"{marker(conn, extra)}/{row['activated_on']}"
        if row["scan_marker"] == current:
            return
        auto_store(conn, load_flow(conn))
        conn.execute(
            "UPDATE cash_settings SET scan_marker = ? WHERE account_key = ?",
            (current, CASH_BOX_KEY),
        )


def refresh_safely(
    conn: sqlite3.Connection, today: date, load_flow: LoadFlow, extra: str = ""
) -> None:
    """`refresh` that never breaks its caller (a board request, a CLI command): a failure is
    logged and the stored data is used as it is (the pass runs in its own transaction, so
    nothing is left half written)."""
    try:
        refresh(conn, today, load_flow, extra)
    except Exception:  # noqa: BLE001 - the pass is an extra; the request must go on
        if conn.in_transaction:
            conn.rollback()
        LOG.warning("the cash pass failed; the stored data is used as it is", exc_info=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
