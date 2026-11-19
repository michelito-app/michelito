"""Topes del presupuesto en la base (`budget_caps`, esquema 17; la lógica está en `budget`).

Sin filas, el presupuesto no está activo. Nada aquí hace commit: quien llama envuelve la escritura
en `with conn:` (y en `changelog.track`, para la bitácora).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from finanzas.analysis.budget import CAP_MAX, Cap


class BudgetError(ValueError):
    """Pedido inválido sobre el presupuesto (422)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _cents(value: Decimal | None) -> int | None:
    return None if value is None else int(value * 100)


def _pesos(cents: int | None) -> Decimal | None:
    return None if cents is None else Decimal(cents) / 100


def load(conn: sqlite3.Connection) -> dict[int, Cap]:
    rows = conn.execute("SELECT category_id, cap_cents, manual, basis_cents FROM budget_caps")
    return {int(r[0]): Cap(int(r[0]), _pesos(r[1]), bool(r[2]), _pesos(r[3])) for r in rows}


def is_active(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM budget_caps LIMIT 1").fetchone() is not None


def activate(conn: sqlite3.Connection, caps: Iterable[Cap]) -> int:
    """Crea los topes iniciales; BudgetError si ya está activo. Devuelve cuántos creó."""
    if is_active(conn):
        raise BudgetError("el presupuesto ya está activo")
    now = _now()
    rows = [(c.category_id, _cents(c.cap), int(c.manual), _cents(c.basis), now, now) for c in caps]
    conn.executemany(
        "INSERT INTO budget_caps (category_id, cap_cents, manual, basis_cents, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def check_cap(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if value < 0 or value > CAP_MAX:
        raise BudgetError("el tope va de RD$ 0 a RD$ 100,000,000")
    if value != value.quantize(Decimal(1)):
        raise BudgetError("el tope va en pesos enteros")
    return value


def set_cap(conn: sqlite3.Connection, category_id: int, cap: Decimal | None) -> None:
    """Tope a mano (None: «Sin presupuesto»): queda fijo, sin avisos de «lo habitual cambió»."""
    value = check_cap(cap)
    now = _now()
    conn.execute(
        "INSERT INTO budget_caps (category_id, cap_cents, manual, basis_cents, created_at, "
        "updated_at) VALUES (?, ?, 1, NULL, ?, ?) ON CONFLICT(category_id) DO UPDATE SET "
        "cap_cents = excluded.cap_cents, manual = 1, updated_at = excluded.updated_at",
        (category_id, _cents(value), now, now),
    )


def resolve_warning(
    conn: sqlite3.Connection, category_id: int, habitual: Decimal, accept: bool
) -> None:
    """Aceptar pone el tope en lo habitual redondeado (0: «Sin presupuesto»); ignorar solo lo da
    por visto. Los dos dejan `basis` en ese valor. LookupError si la categoría no tiene fila."""
    cap = None if habitual <= 0 else habitual
    if accept:
        cursor = conn.execute(
            "UPDATE budget_caps SET cap_cents = ?, basis_cents = ?, updated_at = ? "
            "WHERE category_id = ? AND manual = 0",
            (_cents(cap), _cents(habitual), _now(), category_id),
        )
    else:
        cursor = conn.execute(
            "UPDATE budget_caps SET basis_cents = ?, updated_at = ? "
            "WHERE category_id = ? AND manual = 0",
            (_cents(habitual), _now(), category_id),
        )
    if cursor.rowcount == 0:
        raise LookupError("esa categoría no tiene un tope sin tocar")
