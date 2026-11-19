"""Marcas hechas a mano sobre cargos recurrentes, y uniones de comercios.

Cada serie (por moneda) puede estar confirmada, descartada o cancelada, llevar cuántas cuotas
le quedan y, si se eligieron a mano («Es recurrente…»), su cadencia y su grupo. La clave es la
de la serie (`recurring.series_key`): un comercio, o `proveedor:<id>` para uno de la lista.
`status_on` e `installments_on` son las fechas de la última marca de cada una: desde ellas se
cuentan los cobros posteriores a una cancelación o las cuotas ya pagadas. Van separadas para que
anotar cuotas no mueva la fecha de cancelación.

Una marca guardada con la clave de un comercio que hoy va en una serie mayor (un proveedor o
una unión a mano) no se mueve ni se borra: `for_series` la pasa a esa serie mientras la serie
no tenga marca propia, y vuelve a valer sola si el comercio se separa.

Las uniones (`recurring_unions`) van por comercio, en todas sus monedas: comercio -> clave de
la serie a la que se une (otro comercio o un proveedor). Unir un comercio consigo mismo lo
separa de su proveedor de la lista.

Como en `corrections`, nada aquí hace commit: quien llama envuelve la escritura en
`with conn:`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal, get_args

from finanzas.analysis import categories
from finanzas.analysis.recurring import GROUPS, Cadence

if TYPE_CHECKING:
    from finanzas.analysis.spending import Movement

MarkStatus = Literal["confirmed", "dismissed", "cancelled"]
_STATUSES = frozenset(get_args(MarkStatus))
_CADENCES = frozenset(get_args(Cadence))
_CURRENCIES = frozenset({"DOP", "USD"})
# Columna -> la de su fecha (None: no lleva). Los nombres van en el SQL: lista cerrada.
_COLUMNS: dict[str, str | None] = {
    "status": "status_on",
    "installments_left": "installments_on",
    "cadence": None,
    "group_key": None,
}
_EMPTY = " AND ".join(f"{c} IS NULL" for c in _COLUMNS)
KEY_MAX = 200


@dataclass(frozen=True)
class Mark:
    status: MarkStatus | None
    installments_left: int | None
    status_on: date | None
    installments_on: date | None
    cadence: Cadence | None = None  # elegida a mano
    group: str | None = None  # clave de `recurring.GROUPS` elegida a mano


def load(conn: sqlite3.Connection) -> dict[tuple[str, str], Mark]:
    rows = conn.execute(
        "SELECT merchant, currency, status, installments_left, status_on, installments_on, "
        "cadence, group_key FROM recurring_marks"
    )
    return {
        (row["merchant"], row["currency"]): Mark(
            row["status"],
            row["installments_left"],
            _day(row["status_on"]),
            _day(row["installments_on"]),
            row["cadence"],
            row["group_key"],
        )
        for row in rows
    }


def load_for(
    conn: sqlite3.Connection, movements: Iterable[Movement]
) -> dict[tuple[str, str], Mark]:
    """Las marcas, con las de claves bancarias anteriores pasadas a la actual (ver abajo)."""
    return with_previous_keys(load(conn), movements)


def with_previous_keys(
    marks: Mapping[tuple[str, str], Mark], movements: Iterable[Movement]
) -> dict[tuple[str, str], Mark]:
    """Pasa a la clave actual de un movimiento bancario la marca guardada con su clave
    anterior (`categories.previous_bank_key`), si la actual no tiene una.

    La marca vieja deja de estar bajo su clave salvo que algún movimiento todavía tenga esa
    clave: así no queda un recurrente marcado sin cargos. Las tarjetas no cambian de clave.
    """
    items = list(movements)
    in_use = {(m.merchant, m.currency) for m in items}
    resolved = dict(marks)
    moved: set[tuple[str, str]] = set()
    for item in items:
        if item.merchant != categories.bank_merchant_key(item.description):
            continue  # tarjeta (o una clave que no es la bancaria)
        old = (categories.previous_bank_key(item.description), item.currency)
        new = (item.merchant, item.currency)
        if old == new or old not in marks:
            continue
        if new not in marks:
            resolved[new] = marks[old]
        moved.add(old)
    for old in moved - in_use:
        resolved.pop(old, None)
    return resolved


def for_series(
    marks: Mapping[tuple[str, str], Mark], members: Mapping[str, Collection[str]]
) -> dict[tuple[str, str], Mark]:
    """Las marcas por serie: la de la serie si tiene fila propia (aunque esté vacía: «sin
    marca» explícito); si no, las de sus comercios juntas (`merge`). Las de un comercio que va en
    otra serie salen de su clave (no queda un recurrente aparte con ese comercio). Nada se borra
    de la base: es solo la lectura. La primera escritura sobre la serie copia antes lo heredado a
    su fila (`materialize`), así la mezcla es campo a campo: lo que se cambia manda y lo demás
    sale de los comercios.

    `members`: clave de serie -> sus comercios (`recurring.members`)."""
    resolved = dict(marks)
    absorbed: set[str] = set()
    for key, names in members.items():
        others = [name for name in names if name != key]
        if not others:
            continue
        absorbed.update(others)
        currencies = {cur for (name, cur) in marks if name in others}
        for currency in currencies:
            if (key, currency) in marks:
                continue
            found = [marks[(name, currency)] for name in others if (name, currency) in marks]
            resolved[(key, currency)] = merge(found)
    own = set(members)
    for name, currency in list(resolved):
        if name in absorbed and name not in own:
            resolved.pop((name, currency))
    return resolved


def merge(found: Iterable[Mark]) -> Mark:
    """Varias marcas de comercios de una misma serie: el estado de la marcada más tarde, las
    cuotas de la anotada más tarde, y la cadencia y el grupo de la primera que los tenga
    (en ese mismo orden)."""
    items = list(found)
    by_status = sorted(
        (m for m in items if m.status is not None), key=lambda m: m.status_on or date.min
    )
    by_left = sorted(
        (m for m in items if m.installments_left is not None),
        key=lambda m: m.installments_on or date.min,
    )
    base = Mark(None, None, None, None)
    if by_status:
        base = replace(base, status=by_status[-1].status, status_on=by_status[-1].status_on)
    if by_left:
        latest = by_left[-1]
        base = replace(
            base, installments_left=latest.installments_left, installments_on=latest.installments_on
        )
    ordered = [*reversed(by_status), *items]
    cadence = next((m.cadence for m in ordered if m.cadence is not None), None)
    group = next((m.group for m in ordered if m.group is not None), None)
    return replace(base, cadence=cadence, group=group)


def set_status(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    status: MarkStatus | None,
    today: date,
    *,
    keep: bool = False,
) -> None:
    if status is not None and status not in _STATUSES:
        raise ValueError(f"estado desconocido: {status}")
    _write(conn, merchant, currency, "status", status, today, keep)


def set_installments(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    left: int | None,
    today: date,
    *,
    keep: bool = False,
) -> None:
    if left is not None and left < 0:
        raise ValueError(f"cuotas restantes negativas: {left}")
    _write(conn, merchant, currency, "installments_left", left, today, keep)


def set_cadence(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    cadence: Cadence | None,
    today: date,
    *,
    keep: bool = False,
) -> None:
    if cadence is not None and cadence not in _CADENCES:
        raise ValueError(f"cadencia desconocida: {cadence}")
    _write(conn, merchant, currency, "cadence", cadence, today, keep)


def set_group(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    group: str | None,
    today: date,
    *,
    keep: bool = False,
) -> None:
    if group is not None and group not in GROUPS:
        raise ValueError(f"grupo desconocido: {group}")
    _write(conn, merchant, currency, "group_key", group, today, keep)


def _write(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    column: str,
    value: str | int | None,
    today: date,
    keep: bool = False,
) -> None:
    """`keep`: una fila que queda vacía no se borra (es el «sin marca» explícito de una serie
    que, sin fila, heredaría las marcas de sus comercios)."""
    if column not in _COLUMNS:  # los nombres van en el SQL: lista cerrada
        raise ValueError(f"columna desconocida: {column}")
    if currency not in _CURRENCIES:
        raise ValueError(f"moneda desconocida: {currency}")
    if not merchant or len(merchant) > KEY_MAX:
        raise ValueError("comercio inválido")
    key = (merchant, currency)
    current = conn.execute(
        f"SELECT {column} FROM recurring_marks WHERE merchant = ? AND currency = ?", key
    ).fetchone()
    if current is None and value is None:
        return
    if current is not None and current[column] == value:
        return  # mismo valor: conserva la fecha
    day_column = _COLUMNS[column]
    names = [column] if day_column is None else [column, day_column]
    values: list[str | int | None] = [value]
    if day_column is not None:
        values.append(None if value is None else today.isoformat())
    updates = ", ".join(f"{n} = excluded.{n}" for n in [*names, "updated_at"])
    conn.execute(
        f"INSERT INTO recurring_marks (merchant, currency, {', '.join(names)}, updated_at) "
        f"VALUES (?, ?, {', '.join('?' * len(names))}, ?) ON CONFLICT(merchant, currency) "
        f"DO UPDATE SET {updates}",
        (*key, *values, _now()),
    )
    if not keep:
        conn.execute(
            f"DELETE FROM recurring_marks WHERE merchant = ? AND currency = ? AND {_EMPTY}", key
        )


def inherited(
    marks: Mapping[tuple[str, str], Mark], key: str, currency: str, names: Collection[str]
) -> Mark | None:
    """Lo que la serie `key` hereda de sus comercios `names` (sin ella), o None."""
    found = [marks[(n, currency)] for n in names if n != key and (n, currency) in marks]
    return merge(found) if found else None


def materialize(conn: sqlite3.Connection, key: str, currency: str, mark: Mark) -> None:
    """Guarda en la fila propia de la serie la marca que hereda (antes de cambiarla: así lo
    que no se toca se conserva, también las fechas). No hace nada si la serie ya tiene fila."""
    if currency not in _CURRENCIES:
        raise ValueError(f"moneda desconocida: {currency}")
    conn.execute(
        "INSERT INTO recurring_marks (merchant, currency, status, installments_left, status_on, "
        "installments_on, cadence, group_key, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(merchant, currency) DO NOTHING",
        (
            key,
            currency,
            mark.status,
            mark.installments_left,
            None if mark.status_on is None else mark.status_on.isoformat(),
            None if mark.installments_on is None else mark.installments_on.isoformat(),
            mark.cadence,
            mark.group,
            _now(),
        ),
    )


def load_unions(conn: sqlite3.Connection) -> dict[str, str]:
    """Comercio -> la clave de la serie a la que se unió a mano."""
    return {row[0]: row[1] for row in conn.execute("SELECT merchant, target FROM recurring_unions")}


def set_union(conn: sqlite3.Connection, merchant: str, target: str | None) -> None:
    """Une el comercio a la serie `target` (o a sí mismo: lo separa); None borra la unión."""
    for text in (merchant, target or "x"):
        if not text or len(text) > KEY_MAX:
            raise ValueError("comercio inválido")
    if target is None:
        conn.execute("DELETE FROM recurring_unions WHERE merchant = ?", (merchant,))
        return
    conn.execute(
        "INSERT INTO recurring_unions (merchant, target, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(merchant) DO UPDATE SET target = excluded.target, "
        "updated_at = excluded.updated_at WHERE target != excluded.target",
        (merchant, target, _now()),
    )


def _day(text: str | None) -> date | None:
    return None if text is None else date.fromisoformat(text)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
