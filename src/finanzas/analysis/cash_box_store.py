"""Lectura y escritura de la caja fuerte (esquema 14; las cuentas están en `cash_box`).

- La caja es una cuenta manual en `accounts` (`accounts.CASH_BOX_KEY`, tipo `cash`) y un vínculo
  `'cash_box'` en `links` con esa clave: los dos se crean la primera vez que se usa la caja
  (`ensure_box`), así quien nunca la usa no la ve en el filtro de cuentas. Para tener varias
  cajas bastaría otra cuenta y otro vínculo con su clave: todo aquí recibe `account_key`.
- Los retiros guardados y los depósitos son miembros del vínculo (`link_members`), por huella:
  sobreviven a `parse --retry` y una huella está a lo sumo en un vínculo.
- Lo anotado a mano va en `cash_entries`; su categoría, nota y «gasto único», en
  `transaction_notes` por su huella (`caja-<id>`), como las correcciones de cualquier otro.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal

from finanzas.analysis import catalog, corrections, links
from finanzas.analysis.accounts import CASH_BOX_KEY, CASH_BOX_NAME, CASH_KIND
from finanzas.analysis.cash_box import (
    CURRENCIES,
    ENTRY_CATEGORY_KIND,
    CashBoxError,
    EntryKind,
    ManualEntry,
    check_day,
    check_entry,
    entry_fingerprint,
)


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
        raise LookupError(f"movimiento de la caja desconocido: {entry_id}")
    return found


def box_id(conn: sqlite3.Connection, account_key: str = CASH_BOX_KEY) -> int | None:
    row = conn.execute(
        "SELECT id FROM links WHERE kind = 'cash_box' AND account_key = ? ORDER BY id LIMIT 1",
        (account_key,),
    ).fetchone()
    return None if row is None else int(row[0])


def ensure_box(conn: sqlite3.Connection, account_key: str = CASH_BOX_KEY) -> int:
    """La cuenta y el vínculo de la caja (los crea si faltan); devuelve el id del vínculo."""
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


# --- Movimientos a mano ---------------------------------------------------------------------


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
    """Anota un movimiento a mano (quien llama abre la transacción). `category`: id o referencia,
    solo en una entrada (ingreso) o una salida (gasto); sin ella, la de por omisión. `today`: para
    validar la fecha (`cash_box.check_day`; por omisión, la del sistema). Devuelve el id."""
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
    """Cambia día, monto y moneda (el tipo no cambia); `category` y `note`, si vienen (una nota
    vacía la borra)."""
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
    """Borra el movimiento y todo lo guardado por su huella: su nota y categoría, lo revisado y
    su lugar en un grupo compartido (si era el último gasto del grupo, el grupo se borra)."""
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
        raise CashBoxError("el saldo inicial no lleva categoría")
    try:
        found_id = catalog.resolve_ref(conn, category)
    except ValueError as exc:
        raise CashBoxError(str(exc)) from None
    found = catalog.load(conn).by_id(found_id)
    if found is None or found.kind != wanted:
        what = "de ingreso" if wanted == "ingreso" else "de gasto"
        raise CashBoxError(f"la categoría tiene que ser {what}")
    return found_id


# --- Retiros guardados y depósitos ------------------------------------------------------------


def store(conn: sqlite3.Connection, fingerprint: str, account_key: str = CASH_BOX_KEY) -> None:
    """Marca el retiro como guardado en la caja (quien llama valida que pueda)."""
    _add_member(conn, fingerprint, "stored", None, None, account_key)


def deposit(
    conn: sqlite3.Connection,
    fingerprint: str,
    box_currency: str | None = None,
    box_amount: Decimal | None = None,
    account_key: str = CASH_BOX_KEY,
) -> None:
    """Marca el crédito como un depósito que salió de la caja. `box_currency`: la moneda en que
    salió de la caja si no es la del crédito; `box_amount`, cuánto salió en ella (sin él, a la
    tasa del mes). Quien llama valida que el crédito pueda y pasa None si es la misma moneda."""
    if box_currency is not None and box_currency not in CURRENCIES:
        raise CashBoxError("la moneda es RD$ o US$")
    if box_amount is not None:
        if box_currency is None:
            raise CashBoxError("el monto que salió de la caja va con su moneda")
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
        raise links.AlreadyLinked("la transacción ya está en otro vínculo")
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
    """Quita la marca de retiro guardado (`stored`) o de depósito (`deposit`): el movimiento
    vuelve a su categoría. LookupError si no la tenía."""
    cursor = conn.execute(
        "DELETE FROM link_members WHERE fingerprint = ? AND role = ? "
        "AND link_id IN (SELECT id FROM links WHERE kind = 'cash_box')",
        (fingerprint, role),
    )
    if cursor.rowcount == 0:
        what = "un retiro guardado" if role == "stored" else "un depósito de la caja"
        raise LookupError(f"esa transacción no es {what}")


def _cents(amount: Decimal) -> int:
    return int(amount * 100)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
