"""Schema 27 (the bank's installment of a loan): what the bank charges each month, from a day on.

Self-contained like `migrations_v26`: `db` calls `apply` as one more step of its migration
transaction and takes `VERSION` as the schema version. Every statement is idempotent.

- `loan_installments`: the monthly installment the bank charges (`installment_cents`) from
  `effective` on. When there is one, the schedule uses it instead of the one computed from the
  contract (`loan_schedule.Installment`), so the end follows from what is really charged.
"""

from __future__ import annotations

import sqlite3

VERSION = 27

INSTALLMENT_MAX_CENTS = 10**13
_DAY = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"

SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS loan_installments (
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    effective TEXT NOT NULL CHECK (effective {_DAY}),
    installment_cents INTEGER NOT NULL
        CHECK (installment_cents BETWEEN 1 AND {INSTALLMENT_MAX_CENTS}),
    PRIMARY KEY (loan_id, effective)
)""",
)


def apply(conn: sqlite3.Connection) -> None:
    """Create the bank's installment table (idempotent; inside the caller's transaction)."""
    for statement in SCHEMA:
        conn.execute(statement)
