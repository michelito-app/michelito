"""Schema 21 (Shared): splits by parts and payments on behalf of others.

Self-contained like `migrations_live`: `db` calls `apply` as one more step of its migration
transaction, after the ledger's tables exist (schema 19), and takes `VERSION` as the schema
version.

- `ledger_entries.split` also allows `'parts'` (SQLite cannot widen a CHECK: the table is
  rebuilt with the same rows, ids, indexes and sequence, with foreign keys off, which `db` turns
  off when `needs_rebuild` says so).
- `ledger_splits.parts`: each person's number of parts in a split by parts (NULL otherwise).
- `ledger_allocations`: who an attributed payment is for (the person whose balance with the user
  it settles) and how much, in cents. Existing attributed payments get one allocation each: the
  person at the other end (who paid the user, or who the user paid) for the whole amount, which
  is what the ledger already did with them, so every balance stays the same (`tests`
  `test_schema_v21` checks it). `check_allocations` verifies it before the transaction commits.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable

VERSION = 21

ALLOCATIONS = """CREATE TABLE IF NOT EXISTS ledger_allocations (
    payment_id INTEGER NOT NULL REFERENCES ledger_payments(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    PRIMARY KEY (payment_id, contact_id)
)"""
# An unattributed payment is nobody's: its allocations go when `from_contact` becomes NULL (an
# undo of an assignment from before schema 21 restores only the payment row).
UNASSIGN_TRIGGER = """CREATE TRIGGER IF NOT EXISTS ledger_allocations_unassigned
AFTER UPDATE OF from_contact ON ledger_payments WHEN NEW.from_contact IS NULL
BEGIN DELETE FROM ledger_allocations WHERE payment_id = NEW.id; END"""
PARTS_COLUMN = ("parts", "INTEGER CHECK (parts IS NULL OR parts >= 1)")
SPLIT_CHECK = "CHECK (split IN ('equal', 'exact', 'parts'))"
_SPLIT_PATTERN = r"CHECK\s*\(\s*split\s+IN\s*\([^)]*\)\s*\)"
_MARKER = "'parts'"
# The tables whose rows `apply` may rebuild or point to the rebuilt one (for `foreign_key_check`).
TOUCHED = ("ledger_entries", "ledger_splits", "ledger_links", "ledger_allocations")

RebuildCheck = Callable[[sqlite3.Connection, str, str, str, str], None]


class AllocationMismatch(sqlite3.IntegrityError):
    """An attributed payment would not settle the same with its allocations."""


def _table_sql(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return None if row is None else str(row[0])


def needs_rebuild(conn: sqlite3.Connection) -> bool:
    """`ledger_entries` exists with the old CHECK (no `'parts'`)."""
    sql = _table_sql(conn, "ledger_entries")
    return sql is not None and _MARKER not in sql


def apply(conn: sqlite3.Connection, rebuild_check: RebuildCheck) -> list[str]:
    """Bring the ledger's tables to schema 21 (idempotent; inside the caller's transaction).
    Returns the tables it rebuilt."""
    rebuilt = []
    sql = _table_sql(conn, "ledger_entries")
    if sql is not None and _MARKER not in sql:
        if re.search(_SPLIT_PATTERN, sql, flags=re.IGNORECASE) is None:
            raise sqlite3.OperationalError("the split CHECK was not found in ledger_entries")
        rebuild_check(conn, "ledger_entries", sql, _SPLIT_PATTERN, SPLIT_CHECK)
        rebuilt.append("ledger_entries")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ledger_splits)")}
    if PARTS_COLUMN[0] not in columns:
        conn.execute(f"ALTER TABLE ledger_splits ADD COLUMN {PARTS_COLUMN[0]} {PARTS_COLUMN[1]}")
    conn.execute(ALLOCATIONS)
    conn.execute(UNASSIGN_TRIGGER)
    if int(conn.execute("PRAGMA user_version").fetchone()[0]) < VERSION:
        backfill(conn)
        check_allocations(conn)
    return rebuilt


def backfill(conn: sqlite3.Connection) -> None:
    """One allocation per attributed payment without any: the other end, the whole amount."""
    me = conn.execute("SELECT id FROM contacts WHERE is_me = 1").fetchone()
    if me is None:
        return
    conn.execute(
        "INSERT INTO ledger_allocations (payment_id, contact_id, amount_cents) "
        "SELECT p.id, CASE WHEN p.to_contact = :me THEN p.from_contact ELSE p.to_contact END, "
        "p.amount_cents FROM ledger_payments p "
        "WHERE p.from_contact IS NOT NULL AND (p.to_contact = :me OR p.from_contact = :me) "
        "AND NOT EXISTS (SELECT 1 FROM ledger_allocations a WHERE a.payment_id = p.id)",
        {"me": int(me[0])},
    )


def check_allocations(conn: sqlite3.Connection) -> None:
    """Every attributed payment of the user has allocations adding up to its amount, one of them
    for the other end; an unattributed one has none."""
    row = conn.execute(
        "SELECT p.id FROM ledger_payments p "
        "LEFT JOIN (SELECT payment_id, SUM(amount_cents) AS total FROM ledger_allocations "
        "GROUP BY payment_id) a ON a.payment_id = p.id "
        "WHERE (p.from_contact IS NULL AND a.total IS NOT NULL) "
        "OR (p.from_contact IS NOT NULL AND a.total IS NOT NULL AND a.total != p.amount_cents) "
        "LIMIT 1"
    ).fetchone()
    if row is not None:
        raise AllocationMismatch(f"payment {row[0]}: its allocations do not add up")
