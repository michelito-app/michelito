"""SQLite schema and writing of already validated statements.

Amounts are stored in cents (integers) so that sums are exact.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path

from michelito import (
    encrypted,
    migrations_live,
    migrations_v18,
    migrations_v19,
    migrations_v21,
    migrations_v22,
    migrations_v23,
    migrations_v24,
    migrations_v25,
    migrations_v26,
    migrations_v27,
    migrations_v28,
    migrations_v29,
    migrations_v30,
    migrations_v31,
)
from michelito.analysis import catalog
from michelito.i18n import t
from michelito.parsers import banreservas_account, bhd_savings, popular_web
from michelito.parsers.common import Section, Statement, Transaction

# 31: crypto <-> fiat becomes neutral, like a currency exchange (`migrations_v31`);
# 30: tags, the transactions and loans they hold, and a loan's payout flag (`migrations_v30`);
# 29: AI imports (statements, provisional charges, cash; `migrations_v29`);
# 28: proposals from an AI connector, waiting for an answer (`migrations_v28`);
# 27: the bank's installment of a loan, from a day on (`migrations_v27`);
# 26: loans, their rates, real balances, statement lines and payments (`migrations_v26`);
# 25: installment plans and their charges (`migrations_v25`);
# 24: merchant receipts and their links to transactions (`migrations_v24`);
# 23: the cash account (concepts, schedules, activation, reconcile; `migrations_v23`); 22: exchange
# leftovers and dismissed "paid for others" suggestions (`migrations_v22`); 21: splits by
# parts and payments on behalf of others (`migrations_v21`); 20: live sync
# (`migrations_live`); 19: the shared ledger (`migrations_v19`); 18: stored values in English
# (`migrations_v18`).
SCHEMA_VERSION = migrations_v31.VERSION
DUPLICATE_PERIOD_INDEX = "statements_unique_period"
DUPLICATE_PRINTOUT_INDEX = "statements_unique_printout"
# Parser of Popular's printouts: the account's currency is given by hand (ingest).
PRINTOUT_PARSER = popular_web.NAME
# What is not an official statement but a printout: it covers its range and gives way to the
# statements (see analysis.coverage). Banreservas' current month and BHD's savings one (website)
# are printouts too.
PRINTOUT_PARSERS: tuple[str, ...] = (
    PRINTOUT_PARSER,
    banreservas_account.PARTIAL_NAME,
    bhd_savings.PARTIAL_NAME,
)
_PRINTOUT_LIST = ", ".join(f"'{name}'" for name in PRINTOUT_PARSERS)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    institution TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    last4 TEXT NOT NULL,
    product TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE (account_id, last4)
);
CREATE TABLE IF NOT EXISTS gmail_messages (
    message_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT NOT NULL,
    attachments_saved INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES gmail_messages(message_id),
    source TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'parsed', 'invalid', 'error', 'unsupported', 'archived', 'duplicate'
    )),
    parser TEXT,
    detail TEXT,
    processed_at TEXT,
    UNIQUE (message_id, filename)
);
CREATE INDEX IF NOT EXISTS documents_sha256 ON documents(sha256);
-- A PDF with several statements in a row (parsers with `split`, see ingest): the result of each
-- part, in the PDF's order. `label` is the part's closing date (YYYY-MM-DD) or, if it could not
-- be parsed, `core.ingest.part_label` ("statement N"). `note` is a difference that does not
-- invalidate the part (the summary's row count does not match). It is rewritten every time the
-- document is parsed.
CREATE TABLE IF NOT EXISTS document_parts (
    document_id INTEGER NOT NULL REFERENCES documents(id),
    part INTEGER NOT NULL CHECK (part >= 1),
    label TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('parsed', 'invalid', 'error', 'duplicate')),
    detail TEXT,
    note TEXT,
    PRIMARY KEY (document_id, part)
);
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    card_id INTEGER REFERENCES cards(id),
    parser TEXT NOT NULL,
    product TEXT NOT NULL,
    currency TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT NOT NULL,
    due_date TEXT,
    previous_balance_cents INTEGER,
    closing_balance_cents INTEGER,
    minimum_payment_cents INTEGER,
    credit_limit_cents INTEGER,
    printed_debits_cents INTEGER,
    printed_credits_cents INTEGER,
    transaction_count INTEGER
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statements(id),
    sequence INTEGER NOT NULL,
    transacted_on TEXT NOT NULL,
    posted_on TEXT,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    currency TEXT NOT NULL,
    reference TEXT,
    mcc TEXT,
    raw_line TEXT NOT NULL,
    UNIQUE (statement_id, sequence)
);
-- Categories: the system ones (`builtin_key`, seeded from analysis/categories.py) and the
-- user's. Corrections and keywords store the id: renaming does not touch them.
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense', 'transfer')),
    color TEXT CHECK (color IS NULL OR (length(color) = 7 AND color GLOB '#*'
        AND NOT substr(color, 2) GLOB '*[^0-9A-Fa-f]*')),
    hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    builtin INTEGER NOT NULL DEFAULT 0 CHECK (builtin IN (0, 1)),
    builtin_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    CHECK ((builtin = 1) = (builtin_key IS NOT NULL))
);
-- The user's keywords, normalized like the descriptions (`categories.clean`).
CREATE TABLE IF NOT EXISTS category_keywords (
    category_id INTEGER NOT NULL REFERENCES categories(id),
    keyword TEXT NOT NULL,
    PRIMARY KEY (category_id, keyword)
);
-- Corrections made by hand. They live apart from `transactions` because those rows are
-- recreated when a statement is reprocessed; here they are identified by merchant or fingerprint.
CREATE TABLE IF NOT EXISTS merchant_categories (
    merchant TEXT PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transaction_notes (
    fingerprint TEXT PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id),
    one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)),
    updated_at TEXT NOT NULL,
    note TEXT CHECK (note IS NULL OR length(note) <= 500)
);
-- DOP per USD, one value per month (YYYY-MM). The BCRD table does not overwrite manual ones.
CREATE TABLE IF NOT EXISTS exchange_rates (
    month TEXT PRIMARY KEY,
    dop_per_usd TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('bcrd', 'manual')),
    updated_at TEXT NOT NULL
);
-- The user's marks on recurring charges (by merchant and currency). `status_on` is the date from
-- which charges after cancelling are counted; `installments_on`, the one for installments.
CREATE TABLE IF NOT EXISTS recurring_marks (
    merchant TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT CHECK (status IN ('confirmed', 'dismissed', 'cancelled')),
    installments_left INTEGER CHECK (installments_left IS NULL OR installments_left >= 0),
    status_on TEXT,
    installments_on TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (merchant, currency)
);
-- An account's currency according to whoever imports its website printouts (`import
-- --currency`), which print a bare "$" for dollars too. It goes by the account key
-- (`accounts.key`, the same as the official statement's) and apart from `accounts`: it is a hint
-- for parsing printouts, not account data, and it is looked up before storing.
CREATE TABLE IF NOT EXISTS account_currency (
    account_key TEXT PRIMARY KEY,
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    updated_at TEXT NOT NULL
);
-- One-off suggestions dismissed by hand (the "not a one-off" button), by fingerprint.
CREATE TABLE IF NOT EXISTS one_off_dismissals (
    fingerprint TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL
);
"""

# Links between movements (schema 9; see `analysis.links`): a shared expense with its
# reimbursements or a currency exchange with its legs. They go by fingerprint, like the
# corrections, so they survive `parse --retry`. Each fingerprint is in at most one link
# (`fingerprint UNIQUE`). They are created in the migration, in one transaction. Since schema 12
# (`GROUP_COLUMNS`) a shared group has several expenses and the split goes on each one: `people`,
# `my_share_cents`, `for_other` and `for_whom` in `links` are legacy (not read). Schema 13 adds
# investments (`LINK_KINDS`, `LINK_ROLES` and `INVESTMENT_COLUMNS`) and 14 the cash box
# (`'cash_box'`, its roles `'stored'` and `'deposit'`, `CASH_BOX_COLUMNS` and `CASH_SCHEMA`).
# Schema 17 adds reserves (`'reserve'`, its role `'reserved'` and `RESERVE_COLUMNS`).
# Hosted mode: the account holders, in the same format as holders.txt, inside the encrypted
# database (see `michelito.holders`). The local board keeps reading holders.txt; it stays empty.
# Created in the migration transaction, after every numbered schema step.
HOLDERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS holders (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    content TEXT NOT NULL
)"""

LINK_KINDS = ("shared", "exchange", "investment", "cash_box", "reserve")
LINK_ROLES = (
    "expense",
    "reimbursement",
    "leg",
    "contribution",
    "return",
    "capital",
    "mixed",
    "stored",
    "deposit",
    "reserved",
)
_LINK_KIND_CHECK = "CHECK (kind IN ({}))".format(", ".join(f"'{k}'" for k in LINK_KINDS))
_LINK_ROLE_CHECK = "CHECK (role IN ({}))".format(", ".join(f"'{r}'" for r in LINK_ROLES))
LINK_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL {_LINK_KIND_CHECK},
    people INTEGER CHECK (people IS NULL OR people >= 2),
    my_share_cents INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0),
    for_other INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1)),
    for_whom TEXT CHECK (for_whom IS NULL OR length(for_whom) <= 80),
    written_off INTEGER NOT NULL DEFAULT 0 CHECK (written_off IN (0, 1)),
    agreed_rate TEXT,
    closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    f"""CREATE TABLE IF NOT EXISTS link_members (
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL {_LINK_ROLE_CHECK},
    added_at TEXT NOT NULL,
    PRIMARY KEY (link_id, fingerprint)
)""",
    """CREATE TABLE IF NOT EXISTS link_manual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    day TEXT NOT NULL,
    person TEXT CHECK (person IS NULL OR length(person) <= 80),
    place TEXT CHECK (place IS NULL OR length(place) <= 80),
    created_at TEXT NOT NULL
)""",
)

# Shared groups (schema 12): new columns per table. The split moves from `links` to each expense
# (`link_members` with `role = 'expense'`); the group has a name and a "with whom"; a manual
# reimbursement states its currency (NULL: that of the group's oldest expense, as before).
GROUP_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "links": (
        ("name", "TEXT CHECK (name IS NULL OR length(name) <= 80)"),
        ("with_whom", "TEXT CHECK (with_whom IS NULL OR length(with_whom) <= 80)"),
    ),
    "link_members": (
        ("people", "INTEGER CHECK (people IS NULL OR people >= 2)"),
        ("my_share_cents", "INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0)"),
        ("for_other", "INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1))"),
    ),
    "link_manual": (("currency", "TEXT CHECK (currency IS NULL OR currency IN ('DOP', 'USD'))"),),
}

# Investments (schema 13; see `analysis.investments`): the capital part of a mixed credit, in
# cents of the credit's currency.
INVESTMENT_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "link_members": (
        ("capital_cents", "INTEGER CHECK (capital_cents IS NULL OR capital_cents > 0)"),
    ),
}

# Cash box (schema 14; see `analysis.cash_box`). One `'cash_box'` link per box, with its account
# key (`accounts.key`, like `account_currency`): its members are the withdrawals put away
# (`'stored'`) and the deposits that came out of it (`'deposit'`). A deposit in a currency other
# than the one leaving the box stores that currency and, if given, how much left in it.
CASH_BOX_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "links": (("account_key", "TEXT CHECK (account_key IS NULL OR length(account_key) <= 80)"),),
    "link_members": (
        ("box_currency", "TEXT CHECK (box_currency IS NULL OR box_currency IN ('DOP', 'USD'))"),
        ("box_amount_cents", "INTEGER CHECK (box_amount_cents IS NULL OR box_amount_cents > 0)"),
    ),
}
# The movements written down by hand in the box: opening balance (`initial`, not income), money
# in (`income`) and money out (`expense`). Their fingerprint is `cash-<id>` (`AUTOINCREMENT`: a
# deleted id is not reused, so its note or link never moves to another one); their category,
# note and one-off flag go in `transaction_notes` by that fingerprint, like a statement's.
CASH_ENTRY_KINDS = ("initial", "income", "expense")
_CASH_KIND_LIST = ", ".join(f"'{kind}'" for kind in CASH_ENTRY_KINDS)
CASH_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS cash_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_key TEXT NOT NULL CHECK (length(account_key) <= 80),
    kind TEXT NOT NULL CHECK (kind IN ({_CASH_KIND_LIST})),
    day TEXT NOT NULL CHECK (length(day) = 10),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
)

# "To review" (schema 10; see `analysis.review`): what was marked "already reviewed", by
# fingerprint and kind, so it survives `parse --retry`. One-offs use `one_off_dismissals`.
REVIEW_MARK_KINDS = (
    "unusual_income",
    "large_third_party",
    "duplicate",
    "price_up",
    "possible_contribution",
    "possible_return",
    "possible_reserve",
    "possible_payment",
)
_REVIEW_KIND_LIST = ", ".join(f"'{kind}'" for kind in REVIEW_MARK_KINDS)
REVIEW_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS review_marks (
    fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ({_REVIEW_KIND_LIST})),
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY (fingerprint, kind)
)""",
)

# Month analyses (schema 11; see `analysis.insights`): one text per month, with the fingerprint
# of the analyzed data and the accounts (NULL: all).
INSIGHT_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS insights (
    month TEXT PRIMARY KEY
        CHECK (length(month) = 7 AND month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'),
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 4000),
    data_hash TEXT NOT NULL,
    accounts TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
)

# Change log (schema 15; see `analysis.changelog`): every change made from the board, with its
# author, what was there before and what was left after (`changes`: the rows touched, as JSON),
# the fingerprints it affected at that moment and an optional reason. `undoes`: the entry it
# undoes. `change_log_rows` indexes the rows touched (to know which later entry blocks an
# "undo") and `change_log_fingerprints` the fingerprints (a transaction's history). Merchant
# rules proposed and dismissed ("to review") go in `rule_dismissals`; what was seen with
# `michelito new --mark-reviewed`, in `reviewed_fingerprints`. Also, `categories`, `links` and
# `link_manual` move to `AUTOINCREMENT` (`AUTOINCREMENT_TABLES`): a deleted id is not reused, so
# an undo never gives a row back to a foreign parent that inherited its id.
LOG_AUTHORS = ("user", "claude")
LOG_TARGETS = ("transaction", "merchant", "category", "link", "cash_box", "recurring")
LOG_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    author TEXT NOT NULL CHECK (author IN ({authors})),
    kind TEXT NOT NULL CHECK (length(kind) BETWEEN 1 AND 40),
    target_type TEXT NOT NULL CHECK (target_type IN ({targets})),
    target TEXT NOT NULL,
    subject TEXT NOT NULL,
    merchant TEXT,
    before_text TEXT NOT NULL,
    after_text TEXT NOT NULL,
    changes TEXT NOT NULL,
    affected INTEGER NOT NULL CHECK (affected >= 0),
    reason TEXT CHECK (reason IS NULL OR length(reason) <= 500),
    undoes INTEGER REFERENCES change_log(id)
)""".format(
        authors=", ".join(f"'{a}'" for a in LOG_AUTHORS),
        targets=", ".join(f"'{target}'" for target in LOG_TARGETS),
    ),
    "CREATE INDEX IF NOT EXISTS change_log_at ON change_log(at)",
    "CREATE INDEX IF NOT EXISTS change_log_undoes ON change_log(undoes)",
    """CREATE TABLE IF NOT EXISTS change_log_rows (
    entry_id INTEGER NOT NULL REFERENCES change_log(id) ON DELETE CASCADE,
    row_key TEXT NOT NULL,
    PRIMARY KEY (entry_id, row_key)
)""",
    "CREATE INDEX IF NOT EXISTS change_log_rows_key ON change_log_rows(row_key)",
    """CREATE TABLE IF NOT EXISTS change_log_fingerprints (
    entry_id INTEGER NOT NULL REFERENCES change_log(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    PRIMARY KEY (entry_id, fingerprint)
)""",
    "CREATE INDEX IF NOT EXISTS change_log_fingerprints_fp ON change_log_fingerprints(fingerprint)",
    """CREATE TABLE IF NOT EXISTS rule_dismissals (
    merchant TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    dismissed_at TEXT NOT NULL,
    PRIMARY KEY (merchant, category_id)
)""",
    """CREATE TABLE IF NOT EXISTS reviewed_fingerprints (
    fingerprint TEXT PRIMARY KEY,
    reviewed_at TEXT NOT NULL
)""",
    # Hosted onboarding (`hosted.onboarding`): the first review put off, the checklist hidden.
    """CREATE TABLE IF NOT EXISTS onboarding_flags (
    key TEXT PRIMARY KEY CHECK (key IN ('first_review_closed', 'checklist_dismissed')),
    set_at TEXT NOT NULL
)""",
)
# Schema 16 (household recurring charges): the cadence and group chosen by hand on a mark
# (`recurring.GROUPS`; the group is validated in `recurring_marks`) and the merchant unions
# (merchant -> key of its series: another merchant or `provider:<id>`). Marks do not move: those
# of a merchant that now belongs to a provider are read as the provider's
# (`recurring_marks.for_series`).
RECURRING_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "recurring_marks": (
        ("cadence", "TEXT CHECK (cadence IS NULL OR cadence IN ('monthly', 'yearly'))"),
        ("group_key", "TEXT CHECK (group_key IS NULL OR length(group_key) <= 40)"),
    ),
}
RECURRING_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS recurring_unions (
    merchant TEXT PRIMARY KEY CHECK (length(merchant) BETWEEN 1 AND 200),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 200),
    updated_at TEXT NOT NULL
)""",
)
# Schema 17 (budget and reserves; see `analysis.budget` and `analysis.reserves`). A reserve is a
# `'reserve'` link (its expenses, `'reserved'`, by fingerprint like the others: a fingerprint is
# in a single link) with its plan in `links`: estimated amount in RD$ (`reserve_cents`),
# category, first due month (`due_month`, YYYY-MM), how many months until it repeats
# (`every_months`; NULL: only once), whether it gathers several expenses (`multiple`), the
# suggestion it came from (`source`) and the month from which money is set aside
# (`start_month`, the month it was created).
# Each category's cap goes in `budget_caps` (no rows: budget not activated; `cap_cents` NULL:
# "no budget"; `manual`: edited by hand, it stays fixed; `basis_cents`: the rounded usual amount
# already seen, against which a change is warned). Dismissed reserve suggestions go by their key
# in `reserve_dismissals`.
RESERVE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "links": (
        ("reserve_cents", "INTEGER CHECK (reserve_cents IS NULL OR reserve_cents > 0)"),
        ("category_id", "INTEGER"),
        (
            "due_month",
            "TEXT CHECK (due_month IS NULL OR (length(due_month) = 7 "
            "AND due_month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'))",
        ),
        ("every_months", "INTEGER CHECK (every_months IS NULL OR every_months BETWEEN 1 AND 12)"),
        ("multiple", "INTEGER NOT NULL DEFAULT 0 CHECK (multiple IN (0, 1))"),
        ("source", "TEXT CHECK (source IS NULL OR length(source) <= 200)"),
        (
            "start_month",
            "TEXT CHECK (start_month IS NULL OR (length(start_month) = 7 "
            "AND start_month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'))",
        ),
    ),
}
BUDGET_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS budget_caps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL UNIQUE REFERENCES categories(id) ON DELETE CASCADE,
    cap_cents INTEGER CHECK (cap_cents IS NULL OR cap_cents >= 0),
    manual INTEGER NOT NULL DEFAULT 0 CHECK (manual IN (0, 1)),
    basis_cents INTEGER CHECK (basis_cents IS NULL OR basis_cents >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS reserve_dismissals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE CHECK (length(key) BETWEEN 1 AND 200),
    dismissed_at TEXT NOT NULL
)""",
)

# Schema 19 (the shared ledger; see `analysis.ledger` and `migrations_v19`): global contacts (the
# user is the one with `is_me`) with the names seen in transfers (`contact_aliases`), groups with
# members ("They won't pay me" per member), entries with each person's share in cents and
# payments between members (`from_contact` NULL: unattributed). The personal part is
# `ledger_links` (a transaction's fingerprint -> an entry or a payment; a fingerprint is in at most
# one link, here or in `link_members`) and `ledger_settings`; what the migration kept from the
# old groups: `ledger_dormant` (links that counted nothing) and `ledger_migration` (old link id
# -> new group id). Ids are `AUTOINCREMENT` (an undo
# never gives a row back to a parent that inherited its id).
LEDGER_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    is_me INTEGER NOT NULL DEFAULT 0 CHECK (is_me IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS contacts_one_me ON contacts(is_me) WHERE is_me = 1",
    """CREATE TABLE IF NOT EXISTS contact_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    alias TEXT NOT NULL CHECK (length(alias) BETWEEN 1 AND 80),
    folded TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS ledger_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    category_id INTEGER,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS ledger_members (
    group_id INTEGER NOT NULL REFERENCES ledger_groups(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    written_off INTEGER NOT NULL DEFAULT 0 CHECK (written_off IN (0, 1)),
    added_at TEXT NOT NULL,
    PRIMARY KEY (group_id, contact_id)
)""",
    """CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES ledger_groups(id) ON DELETE CASCADE,
    paid_by INTEGER NOT NULL REFERENCES contacts(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    day TEXT NOT NULL CHECK (length(day) = 10),
    description TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND 120),
    category_id INTEGER,
    split TEXT NOT NULL CHECK (split IN ('equal', 'exact', 'parts')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS ledger_splits (
    entry_id INTEGER NOT NULL REFERENCES ledger_entries(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    share_cents INTEGER NOT NULL CHECK (share_cents >= 0),
    parts INTEGER CHECK (parts IS NULL OR parts >= 1),
    PRIMARY KEY (entry_id, contact_id)
)""",
    """CREATE TABLE IF NOT EXISTS ledger_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES ledger_groups(id) ON DELETE CASCADE,
    from_contact INTEGER REFERENCES contacts(id),
    to_contact INTEGER NOT NULL REFERENCES contacts(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    sent_cents INTEGER CHECK (sent_cents IS NULL OR sent_cents > 0),
    accepted INTEGER NOT NULL DEFAULT 0 CHECK (accepted IN (0, 1)),
    day TEXT NOT NULL CHECK (length(day) = 10),
    note TEXT CHECK (note IS NULL OR length(note) <= 120),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS ledger_links (
    fingerprint TEXT PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES ledger_groups(id) ON DELETE CASCADE,
    entry_id INTEGER REFERENCES ledger_entries(id) ON DELETE CASCADE,
    payment_id INTEGER REFERENCES ledger_payments(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    CHECK ((entry_id IS NULL) != (payment_id IS NULL))
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ledger_links_entry ON ledger_links(entry_id) "
    "WHERE entry_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ledger_links_payment ON ledger_links(payment_id) "
    "WHERE payment_id IS NOT NULL",
    """CREATE TABLE IF NOT EXISTS ledger_dormant (
    fingerprint TEXT PRIMARY KEY,
    link_id INTEGER NOT NULL,
    group_id INTEGER REFERENCES ledger_groups(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK (role IN ('expense', 'payment'))
)""",
    """CREATE TABLE IF NOT EXISTS ledger_migration (
    link_id INTEGER PRIMARY KEY,
    group_id INTEGER REFERENCES ledger_groups(id) ON DELETE SET NULL
)""",
    """CREATE TABLE IF NOT EXISTS ledger_settings (
    key TEXT PRIMARY KEY CHECK (length(key) BETWEEN 1 AND 40),
    value TEXT NOT NULL CHECK (length(value) <= 200)
)""",
)

# They go after `SCHEMA` because an old database needs the new columns first.
# One statement per account, card, currency and closing date. Two cards of the same bank with
# the same closing date are different statements; the savings account has no card. A printout
# is not a statement: it may end on a closing day. Two printouts are the same only if their
# content matches too (closing balance, totals and rows): reprinting the same range later may
# bring new postings for the last day.
_STATEMENT_INDEXES = f"""
CREATE UNIQUE INDEX IF NOT EXISTS {DUPLICATE_PERIOD_INDEX}
    ON statements (account_id, COALESCE(card_id, 0), currency, period_end)
    WHERE parser NOT IN ({_PRINTOUT_LIST});
CREATE UNIQUE INDEX IF NOT EXISTS {DUPLICATE_PRINTOUT_INDEX}
    ON statements (
        account_id, currency, COALESCE(period_start, ''), period_end,
        COALESCE(closing_balance_cents, 0), COALESCE(printed_debits_cents, 0),
        COALESCE(printed_credits_cents, 0), COALESCE(transaction_count, 0)
    )
    WHERE parser IN ({_PRINTOUT_LIST});
"""

_INSERT_STATEMENT = """
INSERT INTO statements (
    document_id, account_id, card_id, parser, product, currency, period_start, period_end,
    due_date, previous_balance_cents, closing_balance_cents, minimum_payment_cents,
    credit_limit_cents, printed_debits_cents, printed_credits_cents, transaction_count
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_TRANSACTION = """
INSERT INTO transactions (
    statement_id, sequence, transacted_on, posted_on, description, amount_cents,
    direction, currency, reference, mcc, raw_line
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def connect(path: Path | str, key: bytes | None = None) -> sqlite3.Connection:
    """The database at `path`, created or migrated to the current schema. With `key` (hosted
    mode) it is an encrypted file (`michelito.encrypted`); the rest is the same either way."""
    conn = encrypted.connect(path, key) if key is not None else sqlite3.connect(path)
    upgrade(conn)
    if str(path) != ":memory:":
        Path(path).chmod(0o600)
    return conn


class NewerSchemaError(RuntimeError):
    """The database was written by a newer Michelito than this one (after going back to an
    earlier version, say). It is left untouched: this code does not know its schema."""

    def __init__(self, stored: int, known: int) -> None:
        super().__init__(
            f"the database has schema {stored} and this version knows up to {known}: "
            "run the newer version"
        )
        self.stored = stored
        self.known = known


def upgrade(conn: sqlite3.Connection) -> None:
    """Bring an open connection to the current schema (what `connect` does on every open).

    It goes by the stored version: a database that is up to date is not touched (no schema
    script, no write lock: reads do not wait for a writer), and one from a newer version is
    refused with `NewerSchemaError`. So every schema change needs a new `SCHEMA_VERSION`
    (`tests/test_schema_guard.py` holds that)."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    stored = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if stored > SCHEMA_VERSION:
        raise NewerSchemaError(stored, SCHEMA_VERSION)
    if stored == SCHEMA_VERSION:
        return
    conn.executescript(SCHEMA)
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a database created with an earlier schema up to date (idempotent). It only runs on
    a database below `SCHEMA_VERSION` (`upgrade`): a new step, even one that only changes rows,
    reaches the existing databases only with a new version number."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(statements)")}
    with conn:
        if "period_start" not in columns:
            conn.execute("ALTER TABLE statements ADD COLUMN period_start TEXT")
        if "transaction_count" not in columns:
            conn.execute("ALTER TABLE statements ADD COLUMN transaction_count INTEGER")
        if "note" not in _table_columns(conn, "document_parts"):  # an earlier test database
            conn.execute("ALTER TABLE document_parts ADD COLUMN note TEXT")
    _migrate_categories(conn)


def _migrate_statement_indexes(conn: sqlite3.Connection) -> None:
    """Indexes from earlier versions: without excluding printouts, without their content or
    without all the printout parsers (or with their pre-schema-18 names)."""
    printouts = tuple(f"'{name}'".upper() for name in PRINTOUT_PARSERS)
    _drop_unless(conn, DUPLICATE_PERIOD_INDEX, ("WHERE", *printouts))
    _drop_unless(conn, DUPLICATE_PRINTOUT_INDEX, ("TRANSACTION_COUNT", *printouts))
    # Schema 18: with the old indexes gone, rename the parsers before the new ones are created.
    migrations_v18.translate_parsers(conn)
    for statement in _STATEMENT_INDEXES.split(";"):
        if statement.strip():
            conn.execute(statement)


# Correction tables keyed by category name (schema 7 and before) -> keyed by its id.
_ID_TABLES = {
    "merchant_categories": """
        CREATE TABLE merchant_categories_v8 (
            merchant TEXT PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES categories(id),
            updated_at TEXT NOT NULL
        )""",
    "transaction_notes": """
        CREATE TABLE transaction_notes_v8 (
            fingerprint TEXT PRIMARY KEY,
            category_id INTEGER REFERENCES categories(id),
            one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)),
            updated_at TEXT NOT NULL
        )""",
}


def _migrate_categories(conn: sqlite3.Connection) -> None:
    """Seed the system categories, move name-based corrections to ids and add what schemas 9
    (notes and links), 10 (what was reviewed), 11 (analyses), 12 (shared groups), 13
    (investments), 14 (cash box), 15 (change log), 16 (household recurring charges) and 17
    (budget and reserves) brought; leave the version up to date (idempotent).

    All in one transaction (`user_version` too): it is either fully migrated or left as it was.
    A stored name is read as today (`catalog.Catalog.by_name`: the current name, an old one such
    as "Efectivo y transferencias" or the original one); one that no longer exists is kept as a
    user expense category with that name, so the correction is not lost.
    """
    # Rebuilding a table with children (`links`) would cascade-delete its members: foreign keys
    # are turned off before the transaction (it cannot be done inside) and checked before COMMIT.
    rebuild = _needs_rebuild(conn)
    if rebuild:
        conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_in_transaction(conn, rebuild)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        if rebuild:
            conn.execute("PRAGMA foreign_keys = ON")


# The child tables of `links`, which may be left orphaned if a rebuild goes wrong.
_LINK_CHILDREN = ("link_members", "link_manual", "ledger_links")


def _migrate_in_transaction(conn: sqlite3.Connection, rebuild: bool) -> None:
    # Schema 18 first: every later step reads and writes the English values.
    _migrate_statement_indexes(conn)
    translated = migrations_v18.rebuild(conn, _rebuild_table) if rebuild else []
    migrations_v18.translate(conn)
    catalog.seed_builtins(conn)
    # Before everything that reads movements (`_fill_manual_currency` loads the flow, which
    # includes the cash box ones).
    for statement in CASH_SCHEMA:
        conn.execute(statement)
    migrations_v23.add_columns(conn)  # the flow reads them from here on
    made: dict[str, int] = {}
    for table, create in _ID_TABLES.items():
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "category" in columns:
            _rebuild_with_ids(conn, table, create, made)
    _migrate_links(conn)
    _migrate_groups(conn)
    for statement in (*REVIEW_SCHEMA, *INSIGHT_SCHEMA):
        conn.execute(statement)
    _migrate_investments(conn)
    _add_columns(conn, CASH_BOX_COLUMNS)
    for statement in LOG_SCHEMA:
        conn.execute(statement)
    _add_columns(conn, RECURRING_COLUMNS)
    for statement in RECURRING_SCHEMA:
        conn.execute(statement)
    _add_columns(conn, RESERVE_COLUMNS)
    for statement in BUDGET_SCHEMA:
        conn.execute(statement)
    # Schema 20 (live sync) creates its tables before schema 19's step: that one reads the
    # movements, and `spending.load_all` reads the provisionals.
    migrations_live.apply(conn)
    rebuilt = _migrate_autoincrement(conn)
    for statement in LEDGER_SCHEMA:
        conn.execute(statement)
    conn.execute(migrations_v21.ALLOCATIONS)  # schema 19's step already writes allocations
    # Schema 19 last: it reads the movements with everything above in place.
    if conn.execute("PRAGMA user_version").fetchone()[0] < migrations_v19.VERSION:
        migrations_v19.migrate(conn)
    # Schema 21 after 19: it widens the entries' CHECK and gives each migrated payment its
    # allocation.
    rebuilt.extend(migrations_v21.apply(conn, _rebuild_check))
    migrations_v22.apply(conn)
    # Schema 23 («Efectivo») after every table it reads (links, categories, accounts).
    migrations_v23.apply(conn)
    migrations_v24.apply(conn)
    migrations_v25.apply(conn)  # after the ledger and receipts it refers to
    migrations_v26.apply(conn)
    migrations_v27.apply(conn)  # after the loans it refers to
    migrations_v28.apply(conn)
    migrations_v29.apply(conn)  # after the proposals it extends
    migrations_v30.apply(conn)  # after the groups and loans it refers to
    migrations_v31.apply(conn)
    conn.execute(HOLDERS_SCHEMA)
    # Only after rebuilding tables, and only the rebuilt ones (and the children of `links`): an
    # unrelated orphan (from another table, from before) must not prevent opening the database.
    if rebuild:
        touched = migrations_v21.TOUCHED if "ledger_entries" in rebuilt else ()
        for child in dict.fromkeys((*_LINK_CHILDREN, *rebuilt, *translated, *touched)):
            if conn.execute(f"PRAGMA foreign_key_check({child})").fetchone() is not None:
                raise sqlite3.IntegrityError("the migration left rows without their parent row")
    # Only when it changes: setting it rewrites the file's header, and this runs on every open
    # (an up-to-date database must be left untouched: `web.flow_cache` goes by its file).
    if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


# Schemas 13, 14 and 17: the CHECKs that are widened (SQLite does not change them with ALTER: the
# table is rebuilt with the same columns and rows). Table -> (pattern of the old CHECK, new CHECK,
# marker that it is already up to date: the last value added).
_WIDENED_CHECKS: dict[str, tuple[str, str, str]] = {
    "links": (r"CHECK\s*\(\s*kind\s+IN\s*\([^)]*\)\s*\)", _LINK_KIND_CHECK, "'reserve'"),
    "link_members": (r"CHECK\s*\(\s*role\s+IN\s*\([^)]*\)\s*\)", _LINK_ROLE_CHECK, "'reserved'"),
    "review_marks": (
        r"CHECK\s*\(\s*kind\s+IN\s*\([^)]*\)\s*\)",
        f"CHECK (kind IN ({_REVIEW_KIND_LIST}))",
        "'possible_payment'",
    ),
}


def _table_sql(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return None if row is None else str(row[0])


def _needs_rebuild(conn: sqlite3.Connection) -> bool:
    """Some table has an old CHECK (schema 13 or earlier) that does not allow investments or
    the cash box, or reuses deleted ids (schema 14 or earlier)."""
    for table, (_, _, marker) in _WIDENED_CHECKS.items():
        sql = _table_sql(conn, table)
        if sql is not None and marker not in sql:
            return True
    if migrations_v18.needs_rebuild(conn) or migrations_v21.needs_rebuild(conn):
        return True
    return any(_needs_autoincrement(conn, table) for table in AUTOINCREMENT_TABLES)


# Schema 15: the parent tables an undo goes back to, in the order they are rebuilt.
AUTOINCREMENT_TABLES = ("categories", "links", "link_manual")
_ID_PATTERN = r"\bid\s+INTEGER\s+PRIMARY\s+KEY\b(?!\s+AUTOINCREMENT)"


def _needs_autoincrement(conn: sqlite3.Connection, table: str) -> bool:
    sql = _table_sql(conn, table)
    return sql is not None and "AUTOINCREMENT" not in sql.upper()


def _migrate_autoincrement(conn: sqlite3.Connection) -> list[str]:
    """Schema 15: rebuild the `AUTOINCREMENT_TABLES` with `AUTOINCREMENT` (same columns, rows,
    ids and indexes; `sqlite_sequence` starts at the highest id). Returns the rebuilt ones."""
    rebuilt = []
    for table in AUTOINCREMENT_TABLES:
        if _needs_autoincrement(conn, table):
            sql = str(_table_sql(conn, table))
            _rebuild_check(conn, table, sql, _ID_PATTERN, "id INTEGER PRIMARY KEY AUTOINCREMENT")
            rebuilt.append(table)
    return rebuilt


def _migrate_investments(conn: sqlite3.Connection) -> None:
    """Schemas 13 and 14: widen the CHECKs of `links`, `link_members` and `review_marks`
    (rebuilding each table with its rows and indexes, the parent before the child) and add
    `capital_cents`."""
    for table, (pattern, check, marker) in _WIDENED_CHECKS.items():
        sql = _table_sql(conn, table)
        if sql is not None and marker not in sql:
            _rebuild_check(conn, table, sql, pattern, check)
    _add_columns(conn, INVESTMENT_COLUMNS)


def _add_columns(conn: sqlite3.Connection, tables: dict[str, tuple[tuple[str, str], ...]]) -> None:
    for table, columns in tables.items():
        present = _table_columns(conn, table)
        for name, definition in columns:
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _rebuild_check(
    conn: sqlite3.Connection, table: str, sql: str, pattern: str, check: str
) -> None:
    widened, count = re.subn(pattern, check, sql, count=1, flags=re.IGNORECASE)
    if count != 1:
        raise sqlite3.OperationalError(f"the CHECK to widen was not found in {table}")
    _rebuild_table(conn, table, widened, {})


def _rebuild_table(
    conn: sqlite3.Connection, table: str, sql: str, select: Mapping[str, str]
) -> None:
    """Recreates `table` from `sql` (its new CREATE statement) with the same rows, indexes and
    sequence. `select`: the SQL expression that copies a column (column -> expression; the
    others are copied as they are)."""
    indexes = [
        row[0]
        for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
            "AND sql IS NOT NULL",
            (table,),
        )
    ]
    staging = f"{table}_rebuild"
    created = re.sub(
        rf"^CREATE TABLE (IF NOT EXISTS )?\"?{table}\"?",
        f"CREATE TABLE {staging}",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )
    names = sorted(_table_columns(conn, table))
    columns = ", ".join(names)
    values = ", ".join(select.get(name, name) for name in names)
    # With AUTOINCREMENT, the old table's sequence (which may be past the highest id if rows were
    # deleted) is lost with the DROP: it is saved and restored, so a deleted id is not reused.
    saved = _sequence(conn, table)
    conn.execute(created)
    conn.execute(f"INSERT INTO {staging} ({columns}) SELECT {values} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {staging} RENAME TO {table}")
    if saved is not None:
        _restore_sequence(conn, table, saved)
    for index in indexes:
        conn.execute(index)


def _sequence(conn: sqlite3.Connection, table: str) -> int | None:
    if _table_sql(conn, "sqlite_sequence") is None:
        return None
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
    return None if row is None else int(row[0])


def _restore_sequence(conn: sqlite3.Connection, table: str, saved: int) -> None:
    """Leave `table`'s sequence at max(the current one, `saved`)."""
    current = _sequence(conn, table)
    if current is None:
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, saved))
    elif current < saved:
        conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (saved, table))


def _migrate_links(conn: sqlite3.Connection) -> None:
    """Schema 9: each transaction's free note and the link tables."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(transaction_notes)")}
    if "note" not in columns:
        conn.execute(
            "ALTER TABLE transaction_notes ADD COLUMN note TEXT "
            "CHECK (note IS NULL OR length(note) <= 500)"
        )
    for statement in LINK_SCHEMA:
        conn.execute(statement)


def _migrate_groups(conn: sqlite3.Connection) -> None:
    """Schema 12: a shared link becomes a group of expenses. Add the columns and, the first
    time, copy each link's split to its only expense and "for whom" to "with whom": no figure
    changes. Drop the index of a single expense per link."""
    first_time = "people" not in _table_columns(conn, "link_members")
    for table, columns in GROUP_COLUMNS.items():
        present = _table_columns(conn, table)
        for name, definition in columns:
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    if first_time:
        conn.execute(
            "UPDATE link_members SET "
            "people = (SELECT l.people FROM links l WHERE l.id = link_members.link_id), "
            "my_share_cents = (SELECT l.my_share_cents FROM links l "
            "WHERE l.id = link_members.link_id), "
            "for_other = (SELECT l.for_other FROM links l WHERE l.id = link_members.link_id) "
            "WHERE role = 'expense'"
        )
        conn.execute("UPDATE links SET with_whom = for_whom WHERE kind = 'shared'")
    conn.execute("DROP INDEX IF EXISTS link_one_expense")
    _fill_manual_currency(conn)


def _fill_manual_currency(conn: sqlite3.Connection) -> None:
    """Schema 11's manual reimbursements do not state their currency: it was that of the link's
    only expense. That one is stored (the first expense added), so it does not change if an
    expense in another currency is added later; if the expense no longer shows up, RD$."""
    groups = [
        row[0]
        for row in conn.execute("SELECT DISTINCT link_id FROM link_manual WHERE currency IS NULL")
    ]
    if not groups:
        return
    from michelito.analysis import spending  # noqa: PLC0415 (reads the db with the columns added)

    currency_of = {m.fingerprint: m.currency for m in spending.load_all(conn)}
    for link_id in groups:
        first = conn.execute(
            "SELECT fingerprint FROM link_members WHERE link_id = ? AND role = 'expense' "
            "ORDER BY added_at, rowid LIMIT 1",
            (link_id,),
        ).fetchone()
        currency = None if first is None else currency_of.get(first[0])
        conn.execute(
            "UPDATE link_manual SET currency = ? WHERE link_id = ? AND currency IS NULL",
            (currency or "DOP", link_id),
        )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _rebuild_with_ids(
    conn: sqlite3.Connection, table: str, create: str, made: dict[str, int]
) -> None:
    conn.execute(create)
    key = "merchant" if table == "merchant_categories" else "fingerprint"
    extra = "" if table == "merchant_categories" else ", one_off"
    rows = conn.execute(f"SELECT {key}, category{extra}, updated_at FROM {table}").fetchall()
    for row in rows:
        category = row["category"]
        category_id = None if category is None else _category_id(conn, category, made)
        values = (row[key], category_id, *([row["one_off"]] if extra else []), row["updated_at"])
        marks = ", ".join("?" * len(values))
        conn.execute(f"INSERT INTO {table}_v8 VALUES ({marks})", values)
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}_v8 RENAME TO {table}")


_NO_NAME = t("core.db.no_name")


def _category_id(conn: sqlite3.Connection, name: str, made: dict[str, int]) -> int:
    """The id of the stored name; it never fails (the migration cannot be left half done).

    An unknown one is stored with a valid, unique name: empty -> `_NO_NAME`, cut to
    `catalog.NAME_MAX` and with " (2)", " (3)"… if it already exists. `made` remembers the ones
    created, so the same old name always gives the same category.
    """
    if name in made:
        return made[name]
    found = catalog.load(conn).by_name(name) if name.strip() else None
    if found is not None:
        return found.id
    base = " ".join(name.split()) or _NO_NAME
    taken = {catalog.fold(row[0]) for row in conn.execute("SELECT name FROM categories")}
    candidate, number = base[: catalog.NAME_MAX], 2
    while catalog.fold(candidate) in taken:
        suffix = f" ({number})"
        candidate = base[: catalog.NAME_MAX - len(suffix)].rstrip() + suffix
        number += 1
    cursor = conn.execute(
        "INSERT INTO categories (name, kind, color, hidden, builtin, builtin_key, created_at) "
        "VALUES (?, 'expense', NULL, 0, 0, NULL, datetime('now'))",
        (candidate,),
    )
    made[name] = int(cursor.lastrowid or 0)
    return made[name]


def _drop_unless(conn: sqlite3.Connection, name: str, markers: tuple[str, ...]) -> None:
    found = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
    ).fetchone()
    if found is not None and not all(m in found["sql"].upper() for m in markers):
        conn.execute(f"DROP INDEX {name}")


def cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(f"amount with more than two decimals: {value}")
    return int(scaled)


def account_key(statement: Statement) -> str:
    """A card changes its plastic but stays the same account; a savings account does not."""
    if statement.kind == "credit_card":
        return f"{statement.institution}:credit_card"
    return f"{statement.institution}:{statement.kind}:{statement.identifier}"


def account_currency(conn: sqlite3.Connection, key: str) -> str | None:
    """The currency given for the account's printouts, if someone gave it."""
    row = conn.execute(
        "SELECT currency FROM account_currency WHERE account_key = ?", (key,)
    ).fetchone()
    return None if row is None else str(row[0])


def account_currencies(conn: sqlite3.Connection) -> dict[str, str]:
    """Every currency given, by account key."""
    rows = conn.execute("SELECT account_key, currency FROM account_currency")
    return {str(row[0]): str(row[1]) for row in rows}


def set_account_currency(conn: sqlite3.Connection, key: str, currency: str, now: str) -> None:
    conn.execute(
        "INSERT INTO account_currency (account_key, currency, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(account_key) DO UPDATE SET "
        "currency = excluded.currency, updated_at = excluded.updated_at",
        (key, currency, now),
    )


def store_statement(conn: sqlite3.Connection, document_id: int, statement: Statement) -> int:
    """Store the statement (one row per currency) and its transactions; returns how many."""
    account_id = _account_id(conn, statement)
    card_id = _card_id(conn, account_id, statement)
    stored = 0
    for section in statement.sections:
        statement_id = _insert_section(conn, document_id, account_id, card_id, statement, section)
        conn.executemany(
            _INSERT_TRANSACTION,
            [
                _transaction_row(statement_id, i, item)
                for i, item in enumerate(section.transactions)
            ],
        )
        stored += len(section.transactions)
    return stored


def _account_id(conn: sqlite3.Connection, statement: Statement) -> int:
    key = account_key(statement)
    name = f"{statement.institution.upper()} {statement.product}"
    if statement.kind != "credit_card":
        name = f"{name} {statement.identifier}"
    conn.execute(
        "INSERT INTO accounts (key, institution, kind, name) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        (key, statement.institution, statement.kind, name),
    )
    return conn.execute("SELECT id FROM accounts WHERE key = ?", (key,)).fetchone()[0]


def _card_id(conn: sqlite3.Connection, account_id: int, statement: Statement) -> int | None:
    if statement.kind != "credit_card":
        return None
    seen = statement.period_end.isoformat()
    conn.execute(
        "INSERT INTO cards (account_id, last4, product, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(account_id, last4) DO UPDATE SET "
        "first_seen = min(first_seen, excluded.first_seen), "
        "last_seen = max(last_seen, excluded.last_seen)",
        (account_id, statement.identifier, statement.product, seen, seen),
    )
    row = conn.execute(
        "SELECT id FROM cards WHERE account_id = ? AND last4 = ?",
        (account_id, statement.identifier),
    ).fetchone()
    return row[0]


def _insert_section(
    conn: sqlite3.Connection,
    document_id: int,
    account_id: int,
    card_id: int | None,
    statement: Statement,
    section: Section,
) -> int:
    cursor = conn.execute(
        _INSERT_STATEMENT,
        (
            document_id,
            account_id,
            card_id,
            statement.parser,
            statement.product,
            section.currency,
            statement.period_start.isoformat() if statement.period_start else None,
            statement.period_end.isoformat(),
            statement.due_date.isoformat() if statement.due_date else None,
            cents(section.previous_balance),
            cents(section.closing_balance),
            cents(section.minimum_payment),
            cents(section.credit_limit),
            cents(section.printed_debits),
            cents(section.printed_credits),
            len(section.transactions),
        ),
    )
    return int(cursor.lastrowid or 0)


def _transaction_row(statement_id: int, sequence: int, transaction: Transaction) -> tuple:
    return (
        statement_id,
        sequence,
        transaction.transacted_on.isoformat(),
        transaction.posted_on.isoformat() if transaction.posted_on else None,
        transaction.description,
        cents(transaction.amount),
        transaction.direction,
        transaction.currency,
        transaction.reference,
        transaction.mcc,
        transaction.raw_line,
    )


FAILED_PART_STATUSES = ("invalid", "error")


def replace_document_parts(
    conn: sqlite3.Connection,
    document_id: int,
    parts: Iterable[tuple[int, str, str, str | None, str | None]],
) -> None:
    """Rewrite the document's parts: (number, label, status, detail, note)."""
    conn.execute("DELETE FROM document_parts WHERE document_id = ?", (document_id,))
    conn.executemany(
        "INSERT INTO document_parts (document_id, part, label, status, detail, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(document_id, *part) for part in parts],
    )


def failed_parts(conn: sqlite3.Connection, document_id: int) -> int:
    """How many of the document's parts were not stored because they did not balance or read."""
    marks = ", ".join("?" for _ in FAILED_PART_STATUSES)
    row = conn.execute(
        f"SELECT COUNT(*) FROM document_parts WHERE document_id = ? AND status IN ({marks})",
        (document_id, *FAILED_PART_STATUSES),
    ).fetchone()
    return int(row[0])


def stored_for_document(conn: sqlite3.Connection, document_id: int, statement: Statement) -> bool:
    """Was this statement (account, currency and closing date) already stored from this document?"""
    marks = ", ".join("?" for _ in statement.sections)
    row = conn.execute(
        "SELECT COUNT(*) FROM statements s JOIN accounts a ON a.id = s.account_id "
        f"WHERE s.document_id = ? AND a.key = ? AND s.period_end = ? AND s.currency IN ({marks})",
        (
            document_id,
            account_key(statement),
            statement.period_end.isoformat(),
            *(section.currency for section in statement.sections),
        ),
    ).fetchone()
    return int(row[0]) > 0


def has_statements(conn: sqlite3.Connection, document_id: int) -> bool:
    """Does the document already have a stored statement?"""
    row = conn.execute(
        "SELECT 1 FROM statements WHERE document_id = ? LIMIT 1", (document_id,)
    ).fetchone()
    return row is not None
