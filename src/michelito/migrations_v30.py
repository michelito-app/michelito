"""Schema 30 (tags): purposes that group transactions across months and categories.

Self-contained like `migrations_v27`: `db` calls `apply` as one more step of its migration
transaction and takes `VERSION` as the schema version. Every statement is idempotent.

- `tags`: a named purpose. `folded` is the name folded like category names; it is unique among
  manual tags only (`group_id IS NULL`), since shared groups may share a name. A tag with
  `group_id` belongs to that shared group (one each), follows its name and goes with it.
- `transaction_tags`: transactions tagged by hand (a group tag also holds, at read time, every
  transaction linked to its group: those are never copied here).
- `tag_targets`: a whole loan or installment plan tagged (its payments come along).
- `loans.has_payout`: the loan's money reached the user's account (then it is debt, not
  spending: see `analysis.tags`).
- The backfill gives every existing shared group its tag, with the group's name unchanged.
"""

from __future__ import annotations

import sqlite3

from michelito.analysis.catalog import fold

VERSION = 30

NAME_MAX = 80
FINGERPRINT_MAX = 80

SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND {NAME_MAX}),
    folded TEXT NOT NULL,
    group_id INTEGER UNIQUE REFERENCES ledger_groups(id) ON DELETE CASCADE,
    color TEXT,
    created_at TEXT NOT NULL
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS tags_manual_name ON tags(folded) WHERE group_id IS NULL",
    f"""CREATE TABLE IF NOT EXISTS transaction_tags (
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) BETWEEN 1 AND {FINGERPRINT_MAX}),
    added_at TEXT NOT NULL,
    PRIMARY KEY (tag_id, fingerprint)
)""",
    """CREATE TABLE IF NOT EXISTS tag_targets (
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('loan', 'installment')),
    target_id INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (tag_id, kind, target_id)
)""",
)


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def apply(conn: sqlite3.Connection) -> None:
    """Create the tag tables, the payout flag and the group tags (idempotent; inside the
    caller's transaction)."""
    for statement in SCHEMA:
        conn.execute(statement)
    if not _has_column(conn, "loans", "has_payout"):
        conn.execute(
            "ALTER TABLE loans ADD COLUMN has_payout INTEGER NOT NULL DEFAULT 0 "
            "CHECK (has_payout IN (0, 1))"
        )
    missing = conn.execute(
        "SELECT g.id, g.name, g.created_at FROM ledger_groups g "
        "WHERE NOT EXISTS (SELECT 1 FROM tags t WHERE t.group_id = g.id) ORDER BY g.id"
    ).fetchall()
    for group_id, name, created_at in missing:
        conn.execute(
            "INSERT INTO tags (name, folded, group_id, created_at) VALUES (?, ?, ?, ?)",
            (name, fold(name), group_id, created_at),
        )
