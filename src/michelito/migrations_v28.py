"""Schema 28 (AI proposals): changes an AI connector proposes, waiting for the person's answer.

Self-contained like `migrations_v27`: `db` calls `apply` as one more step of its migration
transaction and takes `VERSION` as the schema version. Every statement is idempotent.

- `ai_proposals`: one batch per request the person made to their AI ("recategorize the
  supermarket"): its title and explanation (plain text, written by the AI: data, never
  instructions), who sent it (the connection's client name) and whether it is still open,
  being applied (claimed, so two clicks cannot apply it twice), applied or dismissed.
- `ai_proposal_items`: each change of a batch. Only `category` in this version: a transaction's
  category, for that transaction or as the merchant's rule. The transaction as it was when the
  change was proposed is kept next to it (day, merchant, amount, category), so the batch reads
  the same even if the transaction changes later; applying always checks it again.
"""

from __future__ import annotations

import sqlite3

VERSION = 28

TITLE_MAX = 120
EXPLANATION_MAX = 2000
REASON_MAX = 300

SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS ai_proposals (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND {TITLE_MAX}),
    explanation TEXT NOT NULL CHECK (length(explanation) <= {EXPLANATION_MAX}),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'applying', 'applied', 'dismissed')),
    decided_at TEXT
)""",
    f"""CREATE TABLE IF NOT EXISTS ai_proposal_items (
    id INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES ai_proposals(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('category')),
    fingerprint TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('transaction', 'merchant')),
    reason TEXT NOT NULL CHECK (length(reason) <= {REASON_MAX}),
    day TEXT NOT NULL,
    merchant TEXT NOT NULL,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    from_category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'applied', 'skipped', 'failed')),
    message TEXT NOT NULL DEFAULT ''
)""",
    "CREATE INDEX IF NOT EXISTS ai_proposal_items_proposal ON ai_proposal_items(proposal_id)",
)


def apply(conn: sqlite3.Connection) -> None:
    """Create the proposal tables (idempotent; inside the caller's transaction)."""
    for statement in SCHEMA:
        conn.execute(statement)
