"""Reservas en la base (esquema 17; la lógica está en `reserves`).

Una reserva es un vínculo `'reserve'` en `links` (su plan en `reserve_cents`, `category_id`,
`due_month`, `every_months`, `multiple`, `source` y el nombre en `name`) y sus gastos son miembros
`'reserved'` en `link_members`, por huella como los demás vínculos: el índice único de
`link_members.fingerprint` asegura que una huella esté en un solo vínculo (una reserva, un grupo,
una inversión…). El vínculo **no** cambia la categoría del gasto: solo lo saca del tope.
Las sugerencias descartadas van por su clave en `reserve_dismissals`.

Nada aquí hace commit: quien llama envuelve la escritura en `with conn:` (y en `changelog.track`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from finanzas.analysis import catalog
from finanzas.analysis.links import AlreadyLinked
from finanzas.analysis.reserves import (
    AMOUNT_MAX,
    EVERY_CHOICES,
    NAME_MAX,
    Reserve,
    ReserveError,
    check_month,
)

_UNSET = object()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def load(conn: sqlite3.Connection) -> list[Reserve]:
    members: dict[int, list[str]] = {}
    for row in conn.execute(
        "SELECT m.link_id, m.fingerprint FROM link_members m JOIN links l ON l.id = m.link_id "
        "WHERE l.kind = 'reserve' ORDER BY m.added_at, m.rowid"
    ):
        members.setdefault(int(row[0]), []).append(str(row[1]))
    found = []
    for row in conn.execute("SELECT * FROM links WHERE kind = 'reserve' ORDER BY id"):
        found.append(
            Reserve(
                id=int(row["id"]),
                name=row["name"] or f"Reserva n.º {row['id']}",
                amount=Decimal(row["reserve_cents"] or 0) / 100,
                category_id=int(row["category_id"] or 0),
                due_month=row["due_month"] or "",
                every_months=row["every_months"],
                multiple=bool(row["multiple"]),
                members=tuple(members.get(int(row["id"]), ())),
                created_month=row["start_month"] or str(row["created_at"])[:7],
                source=row["source"],
            )
        )
    return found


def get(conn: sqlite3.Connection, reserve_id: int) -> Reserve:
    found = next((r for r in load(conn) if r.id == reserve_id), None)
    if found is None:
        raise LookupError(f"reserva desconocida: {reserve_id}")
    return found


def _name(value: str) -> str:
    text = " ".join((value or "").split())
    if not text:
        raise ReserveError("la reserva necesita un nombre")
    if len(text) > NAME_MAX:
        raise ReserveError(f"el nombre tiene más de {NAME_MAX} letras")
    return text


def _amount_cents(value: Decimal) -> int:
    if value <= 0 or value > AMOUNT_MAX:
        raise ReserveError("el monto va de RD$ 1 a RD$ 100,000,000")
    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise ReserveError("el monto tiene más de dos decimales")
    return int(scaled)


def _every(value: int | None) -> int | None:
    if value is not None and value not in EVERY_CHOICES:
        raise ReserveError("se repite cada año, cada 6 meses o una sola vez")
    return value


def _category(conn: sqlite3.Connection, category_id: int) -> int:
    found = catalog.load(conn).by_id(category_id)
    if found is None:
        raise ReserveError("categoría desconocida")
    if found.kind != "gasto":
        raise ReserveError("una reserva es de una categoría de gasto")
    catalog.check_choosable(found)
    return category_id


def create(
    conn: sqlite3.Connection,
    *,
    name: str,
    amount: Decimal,
    category_id: int,
    due_month: str,
    every_months: int | None,
    multiple: bool = False,
    source: str | None = None,
    start_month: str | None = None,
) -> int:
    """Una reserva nueva. `start_month`: desde qué mes se aparta (el de hoy; por omisión, el del
    reloj), que fija el aporte de una reserva de una sola vez."""
    now = _now()
    cursor = conn.execute(
        "INSERT INTO links (kind, name, reserve_cents, category_id, due_month, every_months, "
        "multiple, source, start_month, created_at, updated_at) "
        "VALUES ('reserve', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _name(name),
            _amount_cents(amount),
            _category(conn, category_id),
            check_month(due_month),
            _every(every_months),
            int(multiple),
            (source or "")[:200] or None,
            check_month(start_month or now[:7]),
            now,
            now,
        ),
    )
    return int(cursor.lastrowid or 0)


def update(
    conn: sqlite3.Connection,
    reserve_id: int,
    *,
    name: str | None = None,
    amount: Decimal | None = None,
    category_id: int | None = None,
    due_month: str | None = None,
    every_months: int | None | object = _UNSET,
    multiple: bool | None = None,
) -> None:
    """Cambia lo pedido (None o ausente: no lo toca; `every_months=None`: una sola vez)."""
    get(conn, reserve_id)
    sets: list[tuple[str, object]] = []
    if name is not None:
        sets.append(("name", _name(name)))
    if amount is not None:
        sets.append(("reserve_cents", _amount_cents(amount)))
    if category_id is not None:
        sets.append(("category_id", _category(conn, category_id)))
    if due_month is not None:
        sets.append(("due_month", check_month(due_month)))
    if every_months is not _UNSET:
        sets.append(("every_months", _every(every_months)))  # type: ignore[arg-type]
    if multiple is not None:
        sets.append(("multiple", int(multiple)))
    if not sets:
        return
    columns = ", ".join(f"{column} = ?" for column, _ in sets)
    conn.execute(
        f"UPDATE links SET {columns}, updated_at = ? WHERE id = ?",
        (*(value for _, value in sets), _now(), reserve_id),
    )


def delete(conn: sqlite3.Connection, reserve_id: int) -> None:
    """Borra la reserva; sus gastos vuelven al tope de su categoría (los miembros, en cascada)."""
    get(conn, reserve_id)
    conn.execute("DELETE FROM links WHERE id = ? AND kind = 'reserve'", (reserve_id,))


def add_member(conn: sqlite3.Connection, reserve_id: int, fingerprint: str) -> None:
    """Vincula el gasto (quien llama valida que sea un gasto). `AlreadyLinked` si ya está en un
    vínculo (también en esta reserva)."""
    get(conn, reserve_id)
    row = conn.execute(
        "SELECT 1 FROM link_members WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    if row is not None:
        raise AlreadyLinked("la transacción ya está en otro vínculo")
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at) "
        "VALUES (?, ?, 'reserved', ?)",
        (reserve_id, fingerprint, _now()),
    )
    conn.execute("UPDATE links SET updated_at = ? WHERE id = ?", (_now(), reserve_id))


def remove_member(conn: sqlite3.Connection, reserve_id: int, fingerprint: str) -> None:
    """Quita el gasto de la reserva: vuelve al tope de su categoría."""
    cursor = conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ? AND role = 'reserved'",
        (reserve_id, fingerprint),
    )
    if cursor.rowcount == 0:
        raise LookupError("ese gasto no es de la reserva")
    conn.execute("UPDATE links SET updated_at = ? WHERE id = ?", (_now(), reserve_id))


def dismissed(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(str(r[0]) for r in conn.execute("SELECT key FROM reserve_dismissals"))


def dismiss(conn: sqlite3.Connection, key: str) -> None:
    text = key.strip()
    if not 1 <= len(text) <= 200:
        raise ReserveError("clave de sugerencia inválida")
    conn.execute(
        "INSERT INTO reserve_dismissals (key, dismissed_at) VALUES (?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        (text, _now()),
    )


def uses_category(conn: sqlite3.Connection, category_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM links WHERE kind = 'reserve' AND category_id = ? LIMIT 1", (category_id,)
    ).fetchone()
    return row is not None


def reassign_category(conn: sqlite3.Connection, old: int, new: int) -> None:
    conn.execute(
        "UPDATE links SET category_id = ? WHERE kind = 'reserve' AND category_id = ?", (new, old)
    )


def fingerprints(reserves: Iterable[Reserve]) -> dict[str, int]:
    """Huella -> la reserva que la cubre."""
    return {fp: r.id for r in reserves for fp in r.members}
