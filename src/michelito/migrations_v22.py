"""Schema 22 (Shared): exchange leftovers per person and dismissed "paid for others" suggestions.

Self-contained like `migrations_v21`: `db` calls `apply` as one more step of its migration
transaction, after schema 21's, and takes `VERSION` as the schema version.

- `ledger_members.leftover_settled`: whether what is left with that person after a converted
  payment, below `ledger.LEFTOVER`, counts as settled ("exchange difference"). 1 by default:
  existing members get it on, which is what `ledger` does when the column is missing, so every
  balance computed before and after the migration is the same (`tests/test_schema_v22.py`).
  Compared with the release before schema 22 this is a visible change on purpose: a small
  converted leftover already in a group now shows as settled; the toggle off brings back the
  old balance (`test_small_converted_leftovers_now_show_as_settled`).
- `ledger_dismissals`: the payments whose "Was that payment for someone else too?" was answered
  "No" (`ledger_cover.cover_suggestion` does not propose them again). Deleting the payment takes it
  away (and an undo brings both back: the change log records cascades).

Nothing is backfilled: no stored row changes.
"""

from __future__ import annotations

import sqlite3

VERSION = 22

LEFTOVER_COLUMN = (
    "leftover_settled",
    "INTEGER NOT NULL DEFAULT 1 CHECK (leftover_settled IN (0, 1))",
)
DISMISSALS = """CREATE TABLE IF NOT EXISTS ledger_dismissals (
    payment_id INTEGER PRIMARY KEY REFERENCES ledger_payments(id) ON DELETE CASCADE,
    dismissed_at TEXT NOT NULL
)"""


def apply(conn: sqlite3.Connection) -> None:
    """Bring the ledger's tables to schema 22 (idempotent; inside the caller's transaction)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ledger_members)")}
    if LEFTOVER_COLUMN[0] not in columns:
        conn.execute(
            f"ALTER TABLE ledger_members ADD COLUMN {LEFTOVER_COLUMN[0]} {LEFTOVER_COLUMN[1]}"
        )
    conn.execute(DISMISSALS)
