"""Tasas de cambio (RD$ por US$) guardadas por mes y conversión a pesos."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class Rate:
    """Tasa usada para un mes; `month_used` es el mes del que sale (puede ser uno anterior)."""

    value: Decimal
    month_used: str
    source: str


def load(conn: sqlite3.Connection) -> dict[str, Rate]:
    rows = conn.execute("SELECT month, dop_per_usd, source FROM exchange_rates ORDER BY month")
    return {r["month"]: Rate(Decimal(r["dop_per_usd"]), r["month"], r["source"]) for r in rows}


def rate_for(rates: Mapping[str, Rate], month: str) -> Rate | None:
    """La tasa de `month` o, si no hay, la del mes anterior más cercano."""
    if month in rates:
        return rates[month]
    earlier = [m for m in rates if m < month]
    return rates[max(earlier)] if earlier else None


def set_manual(conn: sqlite3.Connection, month: str, value: Decimal) -> None:
    _upsert(conn, month, value, "manual")


def store_bcrd(conn: sqlite3.Connection, values: Mapping[str, Decimal]) -> int:
    """Guarda las tasas del BCRD sin pisar las manuales; devuelve cuántas guardó."""
    saved = 0
    for month, value in values.items():
        saved += _upsert(conn, month, value, "bcrd")
    return saved


def to_dop(amount: Decimal, currency: str, rate: Rate | None) -> Decimal | None:
    """Pesos sin cambio, dólares por la tasa, y `None` si es en dólares y no hay tasa."""
    if currency != "USD":
        return amount
    return None if rate is None else amount * rate.value


def _upsert(conn: sqlite3.Connection, month: str, value: Decimal, source: str) -> int:
    text = str(value.quantize(_QUANTUM))
    # Una importación del BCRD no toca los meses que se fijaron a mano.
    cursor = conn.execute(
        "INSERT INTO exchange_rates (month, dop_per_usd, source, updated_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(month) DO UPDATE SET "
        "dop_per_usd = excluded.dop_per_usd, source = excluded.source, "
        "updated_at = excluded.updated_at "
        "WHERE excluded.source = 'manual' OR exchange_rates.source = 'bcrd'",
        (month, text, source, datetime.now(UTC).isoformat(timespec="seconds")),
    )
    return cursor.rowcount
