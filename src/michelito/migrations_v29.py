"""Schema 29 (AI imports): proposals that bring transactions in, besides category changes.

Self-contained like `migrations_v28`: `db` calls `apply` as one more step of its migration
transaction and takes `VERSION` as the schema version. Every statement is idempotent.

- `ai_proposals.kind`: `category` (schema 28's), `statement` (a whole statement the AI read,
  already checked against its printed totals), `provisional` (loose charges of one account,
  pending their statement like a bank alert) or `cash` (cash entries). `account_key`: the
  account a statement or provisional charges belong to (empty for the others).
- `ai_import_rows`: the loose rows of a `provisional` or `cash` proposal, each with the stored
  transaction it seems to repeat (`duplicate_of`, a fingerprint; empty if none), its outcome
  and the fingerprint it got once applied.
- `ai_import_statements`: the statement of a `statement` proposal, as JSON (already
  validated), with its period and size to show it without reading the JSON.
"""

from __future__ import annotations

import sqlite3

VERSION = 29

KINDS = ("category", "statement", "provisional", "cash")
DESCRIPTION_MAX = 200
AMOUNT_MAX_CENTS = 10**11
PAYLOAD_MAX = 512 * 1024
_KIND_LIST = ", ".join(f"'{k}'" for k in KINDS)
_DAY = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"

TABLES = (
    f"""CREATE TABLE IF NOT EXISTS ai_import_rows (
    id INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES ai_proposals(id) ON DELETE CASCADE,
    day TEXT NOT NULL CHECK (day {_DAY}),
    description TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND {DESCRIPTION_MAX}),
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND {AMOUNT_MAX_CENTS}),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    direction TEXT NOT NULL CHECK (direction IN ('out', 'in')),
    category_id INTEGER,
    duplicate_of TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'applied', 'skipped', 'failed')),
    message TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT ''
)""",
    "CREATE INDEX IF NOT EXISTS ai_import_rows_proposal ON ai_import_rows(proposal_id)",
    f"""CREATE TABLE IF NOT EXISTS ai_import_statements (
    proposal_id INTEGER PRIMARY KEY REFERENCES ai_proposals(id) ON DELETE CASCADE,
    period_start TEXT CHECK (period_start IS NULL OR period_start {_DAY}),
    period_end TEXT NOT NULL CHECK (period_end {_DAY}),
    currencies TEXT NOT NULL,
    transactions INTEGER NOT NULL CHECK (transactions >= 0),
    payload TEXT NOT NULL CHECK (length(payload) <= {PAYLOAD_MAX}),
    document_status TEXT NOT NULL DEFAULT ''
)""",
)

COLUMNS = (
    ("kind", f"TEXT NOT NULL DEFAULT 'category' CHECK (kind IN ({_KIND_LIST}))"),
    ("account_key", "TEXT NOT NULL DEFAULT '' CHECK (length(account_key) <= 200)"),
)


def apply(conn: sqlite3.Connection) -> None:
    """Add the import columns and tables (idempotent; inside the caller's transaction)."""
    present = {row[1] for row in conn.execute("PRAGMA table_info(ai_proposals)")}
    for name, definition in COLUMNS:
        if name not in present:
            conn.execute(f"ALTER TABLE ai_proposals ADD COLUMN {name} {definition}")
    for statement in TABLES:
        conn.execute(statement)
