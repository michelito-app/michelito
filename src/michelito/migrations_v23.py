"""Schema 23 (the cash account): concepts, scheduled payments and income, activation, reconcile.

Self-contained like `migrations_live` and `migrations_v21`: `db` calls `apply` as one more step of
its migration transaction (after `cash_entries` exists) and takes `VERSION` as the schema
version. Renumbering it (another branch claiming 22 first) means changing `VERSION` only: every
statement is idempotent and none depends on the number it runs at.

- `cash_entries` gains `concept` (what the movement was: it is its merchant and description),
  `schedule_id` and `occurrence_day` (the schedule and due date that materialized it; one entry
  per schedule and date, `cash_entries_occurrence`) and `status` (`'pending'`: a materialized
  occurrence nobody answered yet; `'confirmed'`: answered; NULL: an ordinary entry). Existing
  rows keep NULL in all four, so they read exactly as before.
- `cash_schedules`: a recurring cash payment or collection (`analysis.cash_schedule`).
  `category_id` has no foreign key on purpose: deleting a category must not be blocked by a
  schedule (a missing category falls back to the default one when it materializes).
- `cash_skips`: occurrences answered "Not paid" / "It did not come" (or deleted), so they are not
  created again.
- `cash_spent_direct`: withdrawals after the activation the user said were "I spent it directly"
  (the automatic "moved into cash" mark is not put back on them).
- `cash_reconciliations`: each "Reconcile cash" (its month), so the monthly prompt stops.
- `cash_auto_marks`: which `stored` marks the system put (discarding or voiding that
  provisional drops them).
- `cash_renames`: which stored names this step renamed (an insight saved before still hashes the
  old ones, `dossier`).
- `cash_settings`: when "Efectivo" (cash) was activated (`activated_on`) and the input marker of the
  last automatic pass (`analysis.cash_activation`). Not in the change log: it is a fact about
  the account, written by the system, never undone.

The step changes no movement: a box that existed before (entries or marked withdrawals) is
activated from the day after the upgrade, so no withdrawal already in the data changes
(`tests/test_schema_v23.py` checks spending, income and balances before and after). It also
renames the two stored names that said "cash box" (the account and the system category) when
the user had not renamed them.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from michelito import config

VERSION = 23

CASH_ACCOUNT_KEY = "manual:cash-box"
CONCEPT_MAX = 60
SCHEDULE_KINDS = ("payment", "collection")
FREQUENCIES = ("weekly", "biweekly", "semimonthly", "monthly")
ENTRY_STATUSES = ("pending", "confirmed")

# spanish-data: begin
OLD_ACCOUNT_NAME = "Caja fuerte"
NEW_ACCOUNT_NAME = "Efectivo"
OLD_CATEGORY_NAME = "Caja fuerte"
NEW_CATEGORY_NAME = "Pasado a efectivo"
# spanish-data: end
_CASH_BOX_KEY = "CASH_BOX"  # `categories.BUILTIN_KEYS`: never changes


def _list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


ENTRY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("concept", f"TEXT CHECK (concept IS NULL OR length(concept) BETWEEN 1 AND {CONCEPT_MAX})"),
    ("schedule_id", "INTEGER"),
    ("occurrence_day", "TEXT CHECK (occurrence_day IS NULL OR length(occurrence_day) = 10)"),
    ("status", f"TEXT CHECK (status IS NULL OR status IN ({_list(ENTRY_STATUSES)}))"),
)

SCHEMA = (
    "CREATE UNIQUE INDEX IF NOT EXISTS cash_entries_occurrence "
    "ON cash_entries(schedule_id, occurrence_day) WHERE schedule_id IS NOT NULL",
    f"""CREATE TABLE IF NOT EXISTS cash_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_key TEXT NOT NULL CHECK (length(account_key) <= 80),
    kind TEXT NOT NULL CHECK (kind IN ({_list(SCHEDULE_KINDS)})),
    concept TEXT NOT NULL CHECK (length(concept) BETWEEN 1 AND {CONCEPT_MAX}),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    category_id INTEGER,
    frequency TEXT NOT NULL CHECK (frequency IN ({_list(FREQUENCIES)})),
    start_day TEXT NOT NULL CHECK (length(start_day) = 10),
    end_day TEXT CHECK (end_day IS NULL OR length(end_day) = 10),
    max_count INTEGER CHECK (max_count IS NULL OR max_count BETWEEN 1 AND 1000),
    paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
    resume_day TEXT CHECK (resume_day IS NULL OR length(resume_day) = 10),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (end_day IS NULL OR max_count IS NULL)
)""",
    """CREATE TABLE IF NOT EXISTS cash_skips (
    schedule_id INTEGER NOT NULL,
    day TEXT NOT NULL CHECK (length(day) = 10),
    created_at TEXT NOT NULL,
    PRIMARY KEY (schedule_id, day)
)""",
    """CREATE TABLE IF NOT EXISTS cash_spent_direct (
    fingerprint TEXT PRIMARY KEY CHECK (length(fingerprint) BETWEEN 1 AND 80),
    created_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS cash_reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_key TEXT NOT NULL CHECK (length(account_key) <= 80),
    month TEXT NOT NULL CHECK (length(month) = 7),
    day TEXT NOT NULL CHECK (length(day) = 10),
    created_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS cash_auto_marks (
    fingerprint TEXT PRIMARY KEY CHECK (length(fingerprint) BETWEEN 1 AND 80),
    created_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS cash_renames (
    what TEXT PRIMARY KEY CHECK (what IN ('account', 'category', 'descriptions'))
)""",
    """CREATE TABLE IF NOT EXISTS cash_settings (
    account_key TEXT PRIMARY KEY CHECK (length(account_key) <= 80),
    activated_on TEXT NOT NULL CHECK (length(activated_on) = 10),
    scan_marker TEXT
)""",
)


def add_columns(conn: sqlite3.Connection) -> None:
    """The new `cash_entries` columns (idempotent): `db` adds them as soon as the table exists,
    because earlier steps already read the flow, which reads them."""
    present = {row[1] for row in conn.execute("PRAGMA table_info(cash_entries)")}
    for name, definition in ENTRY_COLUMNS:
        if name not in present:
            conn.execute(f"ALTER TABLE cash_entries ADD COLUMN {name} {definition}")


def apply(conn: sqlite3.Connection, today: date | None = None) -> None:
    """Bring the cash tables to schema 23 (idempotent; inside the caller's transaction).
    `today`: the upgrade day (by default, the system's), for the activation of an existing box."""
    add_columns(conn)
    for statement in SCHEMA:
        conn.execute(statement)
    if int(conn.execute("PRAGMA user_version").fetchone()[0]) < VERSION:
        _activate_existing(conn, today or config.local_today())
        _rename(conn)


def _activate_existing(conn: sqlite3.Connection, today: date) -> None:
    """A box already in use is activated from tomorrow: nothing already recorded changes."""
    used = conn.execute(
        "SELECT 1 FROM cash_entries WHERE account_key = :key UNION ALL "
        "SELECT 1 FROM link_members m JOIN links l ON l.id = m.link_id "
        "WHERE l.kind = 'cash_box' AND l.account_key = :key LIMIT 1",
        {"key": CASH_ACCOUNT_KEY},
    ).fetchone()
    if used is None:
        return
    conn.execute(
        "INSERT INTO cash_settings (account_key, activated_on) VALUES (?, ?) "
        "ON CONFLICT(account_key) DO NOTHING",
        (CASH_ACCOUNT_KEY, (today + timedelta(days=1)).isoformat()),
    )


def _rename(conn: sqlite3.Connection) -> None:
    """the old cash box names -> the new ones (account and category), only where the
    stored name is still the original one and the new name is free."""
    renamed = []
    account = conn.execute(
        "UPDATE accounts SET name = ? WHERE key = ? AND name = ?",
        (NEW_ACCOUNT_NAME, CASH_ACCOUNT_KEY, OLD_ACCOUNT_NAME),
    )
    if account.rowcount:
        renamed.append("account")
    taken = conn.execute(
        "SELECT 1 FROM categories WHERE lower(name) = lower(?)", (NEW_CATEGORY_NAME,)
    ).fetchone()
    if taken is None:
        category = conn.execute(
            "UPDATE categories SET name = ? WHERE builtin_key = ? AND name = ?",
            (NEW_CATEGORY_NAME, _CASH_BOX_KEY, OLD_CATEGORY_NAME),
        )
        if category.rowcount:
            renamed.append("category")
    # Entries written before: their generic descriptions changed with the catalog.
    if conn.execute("SELECT 1 FROM cash_entries LIMIT 1").fetchone() is not None:
        renamed.append("descriptions")
    conn.executemany(
        "INSERT INTO cash_renames (what) VALUES (?) ON CONFLICT(what) DO NOTHING",
        [(what,) for what in renamed],
    )
