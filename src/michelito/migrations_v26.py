"""Schema 26 (loans): bank loans tracked like an account, and the payments linked to them.

Self-contained like `migrations_v25`: `db` calls `apply` as one more step of its migration
transaction and takes `VERSION` as the schema version. Every statement is idempotent.

- `loans`: the contract (amount, term in months, start date) and the loan `number`, kept clean
  (`loan_match.clean_number`) and unique: every charge whose description has it is a payment.
- `loan_rates`: the annual rate in hundredths of a percent (`rate_bp`, 1250 = 12.50 %) from
  `effective` on; the contract's rate is the one at the start.
- `loan_balances`: real balances the user entered (from the bank), each from its day on.
- `loan_links`: the payments linked (by fingerprint; one loan per charge). `origin` as in
  `receipt_links`. `loan_dismissals`: charges the person said are not the loan's.
- `loan_statement_lines`: each payment as a loan statement prints it (principal, interest, other
  charges, balance after it). They win over the contract for their month. `document`: where
  they came from (a parser's reference), free text.

A loan moves no money and does not change how spending is counted: each payment stays that
month's expense.
"""

from __future__ import annotations

import sqlite3

VERSION = 26

ORIGINS = ("automatic", "confirmed")
_ORIGIN_LIST = ", ".join(f"'{origin}'" for origin in ORIGINS)
NAME_MAX = 80
NUMBER_MAX = 40
TERM_MAX = 600
RATE_MAX_BP = 10_000  # 100 % a year
_DAY = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"

SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND {NAME_MAX}),
    number TEXT NOT NULL UNIQUE CHECK (length(number) BETWEEN 1 AND {NUMBER_MAX}),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    principal_cents INTEGER NOT NULL CHECK (principal_cents > 0),
    term INTEGER NOT NULL CHECK (term BETWEEN 1 AND {TERM_MAX}),
    start_date TEXT NOT NULL CHECK (start_date {_DAY}),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    f"""CREATE TABLE IF NOT EXISTS loan_rates (
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    effective TEXT NOT NULL CHECK (effective {_DAY}),
    rate_bp INTEGER NOT NULL CHECK (rate_bp BETWEEN 0 AND {RATE_MAX_BP}),
    PRIMARY KEY (loan_id, effective)
)""",
    f"""CREATE TABLE IF NOT EXISTS loan_balances (
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    day TEXT NOT NULL CHECK (day {_DAY}),
    balance_cents INTEGER NOT NULL CHECK (balance_cents >= 0),
    PRIMARY KEY (loan_id, day)
)""",
    f"""CREATE TABLE IF NOT EXISTS loan_links (
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE CHECK (length(fingerprint) BETWEEN 1 AND 80),
    origin TEXT NOT NULL CHECK (origin IN ({_ORIGIN_LIST})),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (loan_id, fingerprint)
)""",
    """CREATE TABLE IF NOT EXISTS loan_dismissals (
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) BETWEEN 1 AND 80),
    dismissed_at TEXT NOT NULL,
    PRIMARY KEY (loan_id, fingerprint)
)""",
    f"""CREATE TABLE IF NOT EXISTS loan_statement_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    day TEXT NOT NULL CHECK (day {_DAY}),
    principal_cents INTEGER NOT NULL,
    interest_cents INTEGER NOT NULL CHECK (interest_cents >= 0),
    other_cents INTEGER NOT NULL DEFAULT 0 CHECK (other_cents >= 0),
    balance_cents INTEGER NOT NULL CHECK (balance_cents >= 0),
    document TEXT CHECK (document IS NULL OR length(document) <= 200),
    imported_at TEXT NOT NULL,
    UNIQUE (loan_id, day, principal_cents, interest_cents, balance_cents)
)""",
)


def apply(conn: sqlite3.Connection) -> None:
    """Create the loan tables (idempotent; inside the caller's transaction)."""
    for statement in SCHEMA:
        conn.execute(statement)
