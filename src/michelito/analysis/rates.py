"""Exchange rates (RD$ per US$) stored per month, and conversion to RD$."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class Rate:
    """Rate used for a month; `month_used` is the month it comes from (may be an earlier one)."""

    value: Decimal
    month_used: str
    source: str


def load(conn: sqlite3.Connection) -> dict[str, Rate]:
    rows = conn.execute("SELECT month, dop_per_usd, source FROM exchange_rates ORDER BY month")
    return {r["month"]: Rate(Decimal(r["dop_per_usd"]), r["month"], r["source"]) for r in rows}


def rate_for(rates: Mapping[str, Rate], month: str) -> Rate | None:
    """The rate of `month` or, if there is none, that of the closest earlier month."""
    if month in rates:
        return rates[month]
    earlier = [m for m in rates if m < month]
    return rates[max(earlier)] if earlier else None


def set_manual(conn: sqlite3.Connection, month: str, value: Decimal) -> None:
    _upsert(conn, month, value, "manual")


def store_bcrd(conn: sqlite3.Connection, values: Mapping[str, Decimal]) -> int:
    """Stores the BCRD rates without overwriting manual ones; returns how many were stored."""
    saved = 0
    for month, value in values.items():
        saved += _upsert(conn, month, value, "bcrd")
    return saved


def to_dop(amount: Decimal, currency: str, rate: Rate | None) -> Decimal | None:
    """RD$ unchanged, US$ times the rate, and `None` for US$ with no rate."""
    if currency != "USD":
        return amount
    return None if rate is None else amount * rate.value


def _upsert(conn: sqlite3.Connection, month: str, value: Decimal, source: str) -> int:
    text = str(value.quantize(_QUANTUM))
    # A BCRD import does not touch months that were set by hand.
    cursor = conn.execute(
        "INSERT INTO exchange_rates (month, dop_per_usd, source, updated_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(month) DO UPDATE SET "
        "dop_per_usd = excluded.dop_per_usd, source = excluded.source, "
        "updated_at = excluded.updated_at "
        "WHERE excluded.source = 'manual' OR exchange_rates.source = 'bcrd'",
        (month, text, source, datetime.now(UTC).isoformat(timespec="seconds")),
    )
    return cursor.rowcount
