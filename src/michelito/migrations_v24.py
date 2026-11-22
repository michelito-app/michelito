"""Schema 24 (merchant receipts): what merchants' emails say about purchases, and their links.

Self-contained like `migrations_live` and `migrations_v23`: `db` calls `apply` as one more step
of its migration transaction and takes `VERSION` as the schema version. Renumbering it means
changing `VERSION` only: every statement is idempotent.

- `receipt_emails`: one row per merchant email processed (by message id, so reading it again
  does nothing). Only extracted fields are kept, never the email: the reader that took it, the
  merchant's own summary of the items and their count. `failure` is the data-free structural
  fingerprint of an email that could not be read (JSON), as for alerts.
- `receipts`: what the email says about each purchase (an order confirmation may hold several
  orders; a shipment is one): the merchant, an amount, the merchant's shipment identifier and
  the order's page at the merchant.
- `receipt_orders`: the merchant's order numbers on a receipt (a shipment may carry several).
- `receipt_links`: the transactions a receipt is about, by fingerprint. `origin` says who made
  the link: `'automatic'` (a single exact candidate, `analysis.receipt_match`) or `'confirmed'`
  (the person chose it). Many to many: an order paid in parts, or an order confirmation and its
  shipment on one charge.
- `receipt_dismissals`: pairs the person removed or refused, so they are not offered again.

A receipt never creates a transaction and takes no part in a statement's validation.
"""

from __future__ import annotations

import sqlite3

VERSION = 24

STATUSES = ("read", "failed")
KINDS = ("order", "shipment")
ORIGINS = ("automatic", "confirmed")

_STATUS_LIST = ", ".join(f"'{status}'" for status in STATUSES)
_KIND_LIST = ", ".join(f"'{kind}'" for kind in KINDS)
_ORIGIN_LIST = ", ".join(f"'{origin}'" for origin in ORIGINS)

SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS receipt_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 200),
    source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 40),
    parser TEXT CHECK (parser IS NULL OR length(parser) <= 40),
    received_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({_STATUS_LIST})),
    summary TEXT NOT NULL DEFAULT '' CHECK (length(summary) <= 120),
    item_count INTEGER CHECK (item_count IS NULL OR item_count BETWEEN 0 AND 9999),
    failure TEXT CHECK (failure IS NULL OR length(failure) <= 400),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((status = 'failed') = (failure IS NOT NULL))
)""",
    f"""CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id INTEGER NOT NULL REFERENCES receipt_emails(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position BETWEEN 0 AND 99),
    merchant TEXT NOT NULL CHECK (length(merchant) BETWEEN 1 AND 80),
    kind TEXT NOT NULL CHECK (kind IN ({_KIND_LIST})),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    reference TEXT NOT NULL DEFAULT '' CHECK (length(reference) <= 40),
    link TEXT NOT NULL DEFAULT '' CHECK (length(link) <= 200),
    UNIQUE (email_id, position)
)""",
    """CREATE TABLE IF NOT EXISTS receipt_orders (
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    order_number TEXT NOT NULL CHECK (length(order_number) BETWEEN 1 AND 40),
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (receipt_id, order_number)
)""",
    "CREATE INDEX IF NOT EXISTS receipt_orders_number ON receipt_orders(order_number)",
    f"""CREATE TABLE IF NOT EXISTS receipt_links (
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) BETWEEN 1 AND 80),
    origin TEXT NOT NULL CHECK (origin IN ({_ORIGIN_LIST})),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (receipt_id, fingerprint)
)""",
    "CREATE INDEX IF NOT EXISTS receipt_links_fingerprint ON receipt_links(fingerprint)",
    """CREATE TABLE IF NOT EXISTS receipt_dismissals (
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) BETWEEN 1 AND 80),
    dismissed_at TEXT NOT NULL,
    PRIMARY KEY (receipt_id, fingerprint)
)""",
)


def apply(conn: sqlite3.Connection) -> None:
    """Create the receipt tables (idempotent; inside the caller's transaction)."""
    for statement in SCHEMA:
        conn.execute(statement)
