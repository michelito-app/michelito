"""Schema 25 (installment plans): purchases paid in monthly installments, and their charges.

Self-contained like `migrations_v24`: `db` calls `apply` as one more step of its migration
transaction and takes `VERSION` as the schema version. Every statement is idempotent.

- `installment_plans`: one purchase paid in `count` monthly installments of `amount_cents` on
  one card (`account_key`), from `first_month`. `matcher` is the folded start of the charges'
  description (`installment_match.matcher_of`). `group_id` and `contact_id` (both or neither):
  the installments are that member's, recorded as their expense in that shared group; neither:
  they are the user's own; deleting that group or person deletes the plan.
  `receipt_id`: the merchant receipt of the purchase, if known.
- `installment_links`: the charge (by fingerprint) of each installment. `origin` as in
  `receipt_links`; `entry_id`: the shared group expense the link recorded (a member's plan).
- `installment_dismissals`: charges the person said are not part of the plan.

A plan moves no money and does not change how spending is counted: the charges stay what they
are (each one that month's expense, or the member's shared expense).
"""

from __future__ import annotations

import sqlite3

VERSION = 25

ORIGINS = ("automatic", "confirmed")
_ORIGIN_LIST = ", ".join(f"'{origin}'" for origin in ORIGINS)
NAME_MAX = 80
COUNT_MAX = 120

SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS installment_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND {NAME_MAX}),
    account_key TEXT NOT NULL CHECK (length(account_key) BETWEEN 1 AND 80),
    matcher TEXT NOT NULL CHECK (length(matcher) BETWEEN 1 AND 80),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    count INTEGER NOT NULL CHECK (count BETWEEN 2 AND {COUNT_MAX}),
    first_month TEXT NOT NULL CHECK (first_month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
    group_id INTEGER REFERENCES ledger_groups(id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
    receipt_id INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((group_id IS NULL) = (contact_id IS NULL))
)""",
    f"""CREATE TABLE IF NOT EXISTS installment_links (
    plan_id INTEGER NOT NULL REFERENCES installment_plans(id) ON DELETE CASCADE,
    number INTEGER NOT NULL CHECK (number >= 1),
    fingerprint TEXT NOT NULL UNIQUE CHECK (length(fingerprint) BETWEEN 1 AND 80),
    origin TEXT NOT NULL CHECK (origin IN ({_ORIGIN_LIST})),
    entry_id INTEGER REFERENCES ledger_entries(id) ON DELETE SET NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY (plan_id, number)
)""",
    """CREATE TABLE IF NOT EXISTS installment_dismissals (
    plan_id INTEGER NOT NULL REFERENCES installment_plans(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) BETWEEN 1 AND 80),
    dismissed_at TEXT NOT NULL,
    PRIMARY KEY (plan_id, fingerprint)
)""",
)


def apply(conn: sqlite3.Connection) -> None:
    """Create the installment tables (idempotent; inside the caller's transaction)."""
    for statement in SCHEMA:
        conn.execute(statement)
