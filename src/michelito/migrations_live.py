"""Schema 20 (live sync): bank alerts and the provisional transactions they create.

Self-contained on purpose: `db` calls `apply` as one more step of its migration transaction and
takes `VERSION` as the schema version. Renumbering it (another branch adding its own step first)
means changing `VERSION` only: the step itself is idempotent (`CREATE TABLE IF NOT EXISTS`) and
does not depend on the version it runs at.

- `alerts`: one row per alert email processed (by message id, so a second sync does nothing).
  Only the extracted fields are kept (card digits, amount, currency, date, merchant and the
  bank's status word), never the email. `status` (`STATUSES`) is where the alert stands: a
  `'provisional'` one is a transaction ("pending statement", fingerprint `alert-<id>`); a
  `'confirmed'` one was found in a statement row (`statement_fingerprint`: that row's content
  fingerprint) and, with `keeps_identity`, that row takes the alert's fingerprint, so everything
  linked to the provisional stays linked. `failure` is the data-free structural fingerprint of an
  alert that could not be read (JSON).
- `provisional_decisions`: what the user said about a provisional that did not show up in its
  statement ("Discard" or "Keep"), by fingerprint; recorded in the change log.
"""

from __future__ import annotations

import sqlite3

VERSION = 20

STATUSES = (
    "provisional",  # an approved purchase on a known card: counts as a transaction
    "confirmed",  # found in a statement
    # A held one (unknown card or status) that a reversal alert cancelled. A
    # provisional one that gets cancelled keeps its status: the cancellation is a logged `'void'`
    # decision (undoable), and `voided_by` marks the cancelling alert as used either way.
    "voided",
    "unknown_card",  # approved, but its card is not known yet: held, not guessed
    "unknown_status",  # a status word not in the parser's table: held, never approved
    "declined",  # a decline alert: a failed attempt, never a transaction and it voids nothing
    "reversed",  # a reversal alert: never a transaction
    "failed",  # could not be read (`failure` says which field)
    "stale",  # dated before the account's first statement: history, not a transaction
    "duplicate",  # the same alert sent again (`live_store.RESEND_MINUTES`): recorded, not counted
)
DECISIONS = ("discard", "keep", "void")

_STATUS_LIST = ", ".join(f"'{status}'" for status in STATUSES)
_DECISION_LIST = ", ".join(f"'{decision}'" for decision in DECISIONS)

SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE CHECK (length(message_id) BETWEEN 1 AND 200),
    source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 40),
    parser TEXT CHECK (parser IS NULL OR length(parser) <= 40),
    received_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({_STATUS_LIST})),
    bank_status TEXT CHECK (bank_status IS NULL OR length(bank_status) <= 40),
    last4 TEXT CHECK (last4 IS NULL OR (length(last4) = 4 AND last4 NOT GLOB '*[^0-9]*')),
    account_key TEXT CHECK (account_key IS NULL OR length(account_key) <= 80),
    day TEXT CHECK (day IS NULL OR length(day) = 10),
    amount_cents INTEGER CHECK (amount_cents IS NULL OR amount_cents > 0),
    currency TEXT CHECK (currency IS NULL OR currency IN ('DOP', 'USD')),
    merchant TEXT CHECK (merchant IS NULL OR length(merchant) <= 200),
    statement_fingerprint TEXT UNIQUE,
    keeps_identity INTEGER NOT NULL DEFAULT 0 CHECK (keeps_identity IN (0, 1)),
    voided_by INTEGER REFERENCES alerts(id),
    failure TEXT CHECK (failure IS NULL OR length(failure) <= 400),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((status = 'confirmed') = (statement_fingerprint IS NOT NULL))
)""",
    "CREATE INDEX IF NOT EXISTS alerts_status ON alerts(status)",
    f"""CREATE TABLE IF NOT EXISTS provisional_decisions (
    fingerprint TEXT PRIMARY KEY CHECK (length(fingerprint) BETWEEN 1 AND 80),
    decision TEXT NOT NULL CHECK (decision IN ({_DECISION_LIST})),
    decided_at TEXT NOT NULL
)""",
)


def apply(conn: sqlite3.Connection) -> None:
    """Create the live-sync tables (idempotent; inside the caller's transaction)."""
    for statement in SCHEMA:
        conn.execute(statement)
