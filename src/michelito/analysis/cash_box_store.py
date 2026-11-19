"""Reading and writing the cash box (schema 14; the accounting is in `cash_box`).

- The box is a manual account in `accounts` (`accounts.CASH_BOX_KEY`, kind `cash`) and a
  `'cash_box'` link in `links` with that key: both are created the first time the box is used
  (`ensure_box`), so someone who never uses it does not see it in the account filter. Several
  boxes would only need another account and another link with its key: everything here takes
  `account_key`.
- Stored withdrawals and deposits are members of the link (`link_members`), by fingerprint: they
  survive `parse --retry` and a fingerprint is in at most one link.
- Hand-made entries go in `cash_entries`; their category, note and "one-off" flag in
  `transaction_notes` by their fingerprint (`cash-<id>`), like the corrections of any other.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal

from michelito.analysis import catalog, corrections, links
from michelito.analysis.accounts import CASH_BOX_KEY, CASH_BOX_NAME, CASH_KIND
from michelito.analysis.cash_box import (
    CURRENCIES,
    ENTRY_CATEGORY_KIND,
    CashBoxError,
    EntryKind,
    ManualEntry,
    check_day,
    check_entry,
    entry_fingerprint,
)
from michelito.i18n import t


def load_entries(conn: sqlite3.Connection) -> tuple[ManualEntry, ...]:
    rows = conn.execute("SELECT * FROM cash_entries ORDER BY day, id")
    return tuple(
        ManualEntry(
            id=row["id"],
            kind=row["kind"],
            day=date.fromisoformat(row["day"]),
            amount=Decimal(row["amount_cents"]) / 100,
            currency=row["currency"],
            account_key=row["account_key"],
        )
        for row in rows
    )


def entry(conn: sqlite3.Connection, entry_id: int) -> ManualEntry:
    found = next((e for e in load_entries(conn) if e.id == entry_id), None)
    if found is None:
        raise LookupError(t("analysis.cash_box_store.unknown_entry", id=entry_id))
    return found


def box_id(conn: sqlite3.Connection, account_key: str = CASH_BOX_KEY) -> int | None:
    row = conn.execute(
        "SELECT id FROM links WHERE kind = 'cash_box' AND account_key = ? ORDER BY id LIMIT 1",
        (account_key,),
    ).fetchone()
    return None if row is None else int(row[0])


def ensure_box(conn: sqlite3.Connection, account_key: str = CASH_BOX_KEY) -> int:
    """The box account and link (created if missing); returns the link id."""
    conn.execute(
        "INSERT INTO accounts (key, institution, kind, name) VALUES (?, 'manual', ?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        (account_key, CASH_KIND, CASH_BOX_NAME),
    )
    found = box_id(conn, account_key)
    if found is not None:
        return found
    now = _now()
    cursor = conn.execute(
        "INSERT INTO links (kind, account_key, created_at, updated_at) "
        "VALUES ('cash_box', ?, ?, ?)",
        (account_key, now, now),
    )
    return int(cursor.lastrowid or 0)


# --- Hand-made entries ----------------------------------------------------------------------


def add_entry(
    conn: sqlite3.Connection,
    kind: EntryKind,
    day: date,
    amount: Decimal,
    currency: str,
    *,
    category: str | int | None = None,
    note: str | None = None,
    account_key: str = CASH_BOX_KEY,
    today: date | None = None,
) -> int:
    """Records a hand-made entry (the caller opens the transaction). `category`: id or reference,
    only on an inflow (income) or an outflow (expense); without it, the default one. `today`: to
    validate the date (`cash_box.check_day`; by default, the system's). Returns the id."""
    check_entry(kind, amount, currency)
    check_day(day, today or date.today())
    category_id = _category(conn, kind, category)
    ensure_box(conn, account_key)
    now = _now()
    cursor = conn.execute(
        "INSERT INTO cash_entries (account_key, kind, day, amount_cents, currency, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (account_key, kind, day.isoformat(), _cents(amount), currency, now, now),
    )
    found = int(cursor.lastrowid or 0)
    fingerprint = entry_fingerprint(found)
    if category_id is not None:
        corrections.set_transaction_category(conn, fingerprint, category_id)
    if note is not None and kind != "initial":
        corrections.set_note(conn, fingerprint, note)
    return found


def update_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    day: date,
    amount: Decimal,
    currency: str,
    *,
    category: str | int | None = None,
    note: str | None = None,
    today: date | None = None,
) -> None:
    """Changes day, amount and currency (the kind does not change); `category` and `note` when
    given (an empty note deletes it)."""
    current = entry(conn, entry_id)
    check_entry(current.kind, amount, currency)
    check_day(day, today or date.today())
    category_id = _category(conn, current.kind, category)
    conn.execute(
        "UPDATE cash_entries SET day = ?, amount_cents = ?, currency = ?, updated_at = ? "
        "WHERE id = ?",
        (day.isoformat(), _cents(amount), currency, _now(), entry_id),
    )
    fingerprint = entry_fingerprint(entry_id)
    if category_id is not None:
        corrections.set_transaction_category(conn, fingerprint, category_id)
    if note is not None and current.kind != "initial":
        corrections.set_note(conn, fingerprint, note)


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    """Deletes the entry and everything stored by its fingerprint: its note and category, its
    review marks and its place in a shared group (if it was the group's last expense, the group
    is deleted)."""
    entry(conn, entry_id)
    fingerprint = entry_fingerprint(entry_id)
    links.unshare(conn, fingerprint)
    for table in ("link_members", "transaction_notes", "one_off_dismissals", "review_marks"):
        conn.execute(f"DELETE FROM {table} WHERE fingerprint = ?", (fingerprint,))
    conn.execute("DELETE FROM cash_entries WHERE id = ?", (entry_id,))


def _category(conn: sqlite3.Connection, kind: str, category: str | int | None) -> int | None:
    if category is None:
        return None
    wanted = ENTRY_CATEGORY_KIND.get(kind)
    if wanted is None:
        raise CashBoxError(t("analysis.cash_box_store.initial_no_category"))
    try:
        found_id = catalog.resolve_ref(conn, category)
    except ValueError as exc:
        raise CashBoxError(str(exc)) from None
    found = catalog.load(conn).by_id(found_id)
    if found is None or found.kind != wanted:
        key = "income" if wanted == "income" else "expense"
        raise CashBoxError(t(f"analysis.cash_box_store.category_must_be_{key}"))
    return found_id


# --- Stored withdrawals and deposits ---------------------------------------------------------


def store(conn: sqlite3.Connection, fingerprint: str, account_key: str = CASH_BOX_KEY) -> None:
    """Marks the withdrawal as stored in the box (the caller checks that it can be)."""
    _add_member(conn, fingerprint, "stored", None, None, account_key)


def deposit(
    conn: sqlite3.Connection,
    fingerprint: str,
    box_currency: str | None = None,
    box_amount: Decimal | None = None,
    account_key: str = CASH_BOX_KEY,
) -> None:
    """Marks the credit as a deposit that left the box. `box_currency`: the currency in which it
    left the box when it is not the credit's; `box_amount`, how much left in it (without it, at
    the month's rate). The caller checks that the credit can be marked and passes None for the
    same currency."""
    if box_currency is not None and box_currency not in CURRENCIES:
        raise CashBoxError(t("analysis.cash_box.currency"))
    if box_amount is not None:
        if box_currency is None:
            raise CashBoxError(t("analysis.cash_box_store.amount_needs_currency"))
        check_entry("expense", box_amount, box_currency)
    _add_member(conn, fingerprint, "deposit", box_currency, box_amount, account_key)


def _add_member(
    conn: sqlite3.Connection,
    fingerprint: str,
    role: str,
    box_currency: str | None,
    box_amount: Decimal | None,
    account_key: str,
) -> None:
    found = conn.execute(
        "SELECT 1 FROM link_members WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    if found is not None:
        raise links.AlreadyLinked(t("analysis.links.already_linked"))
    box = ensure_box(conn, account_key)
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at, box_currency, "
        "box_amount_cents) VALUES (?, ?, ?, ?, ?, ?)",
        (
            box,
            fingerprint,
            role,
            _now(),
            box_currency,
            None if box_amount is None else _cents(box_amount),
        ),
    )
    conn.execute("UPDATE links SET updated_at = ? WHERE id = ?", (_now(), box))


def remove(conn: sqlite3.Connection, fingerprint: str, role: str) -> None:
    """Removes the stored-withdrawal (`stored`) or deposit (`deposit`) mark: the movement goes
    back to its category. LookupError if it did not have it."""
    cursor = conn.execute(
        "DELETE FROM link_members WHERE fingerprint = ? AND role = ? "
        "AND link_id IN (SELECT id FROM links WHERE kind = 'cash_box')",
        (fingerprint, role),
    )
    if cursor.rowcount == 0:
        key = "not_stored" if role == "stored" else "not_deposit"
        raise LookupError(t(f"analysis.cash_box_store.{key}"))


def _cents(amount: Decimal) -> int:
    return int(amount * 100)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
