"""Meses atípicos y lo que los explica ("Qué pasó"). Funciones puras, todo en RD$.

Regla (determinista): un mes es atípico en gasto o en ingresos cuando se aparta de lo habitual
más que max(ANOMALY_SHARE de lo habitual, ANOMALY_FLOOR). Lo habitual es la mediana de los
mismos BASELINE meses completos anteriores que usa el Resumen (`web.summary`); con menos de
MIN_BASELINE meses no se marca nada. Los meses en curso (parciales) no se marcan, y los
ingresos tampoco cuando una cuenta bancaria corta antes del fin de mes. El gasto se compara
con la mediana sin gastos únicos, como el indicador "Gastos" del Resumen.

"Qué pasó" agrupa por comercio: lo del mes menos la mediana del comercio en los meses de
referencia (cero donde no apareció). En un mes alto salen los que más subieron; en uno bajo,
los que más bajaron (o no aparecieron). Cada uno enlaza su movimiento mayor del mes, si hay.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from finanzas.analysis.spending import Movement

ANOMALY_SHARE = Decimal("0.30")
ANOMALY_FLOOR = Decimal(10_000)
MIN_BASELINE = 3
TOP_CONTRIBUTIONS = 3

Direction = Literal["up", "down"]
Side = Literal["gasto", "ingreso"]

_ZERO = Decimal(0)


@dataclass(frozen=True)
class Entry:
    """Un movimiento con su monto en RD$ del lado que se mide (positivo = más de ese lado)."""

    move: Movement
    dop: Decimal


@dataclass(frozen=True)
class Contribution:
    side: Side
    merchant: str
    category: str
    amount: Decimal  # lo del comercio en el mes
    habitual: Decimal  # mediana del comercio en los meses de referencia
    diff: Decimal  # amount − habitual
    count: int  # movimientos del comercio en el mes
    fingerprint: str  # su movimiento mayor del mes; "" si no apareció
    day: date | None
    description: str


def deviation(
    value: Decimal,
    habitual: Decimal,
    *,
    share: Decimal = ANOMALY_SHARE,
    floor: Decimal = ANOMALY_FLOOR,
) -> Direction | None:
    """ "up" o "down" si `value` se aparta de `habitual` más que max(share, floor)."""
    diff = value - habitual
    if abs(diff) <= max(floor, abs(habitual) * share):
        return None
    return "up" if diff > 0 else "down"


def habitual(values: Sequence[Decimal]) -> Decimal | None:
    """Mediana de los meses de referencia; None con menos de MIN_BASELINE."""
    if len(values) < MIN_BASELINE:
        return None
    return statistics.median(values)


def contributions(
    current: Sequence[Entry],
    baseline: Mapping[str, Sequence[Entry]],
    direction: Direction,
    side: Side,
    limit: int = TOP_CONTRIBUTIONS,
) -> list[Contribution]:
    """Comercios que más explican el desvío del mes, en la dirección dada.

    `baseline`: entradas de cada mes de referencia (sin gastos únicos, como lo habitual).
    """
    now = _by_merchant(current)
    before = {month: _totals(entries) for month, entries in baseline.items()}
    merchants = set(now) | {m for totals in before.values() for m in totals}
    found = []
    for merchant in merchants:
        items = now.get(merchant, [])
        amount = sum((e.dop for e in items), _ZERO)
        usual = (
            statistics.median(totals.get(merchant, _ZERO) for totals in before.values())
            if before
            else _ZERO
        )
        diff = amount - usual
        if (diff > 0) if direction == "up" else (diff < 0):
            found.append(_contribution(side, merchant, items, amount, usual, diff, baseline))
    found.sort(key=lambda c: (-abs(c.diff), c.merchant))
    return found[:limit]


def _by_merchant(entries: Sequence[Entry]) -> dict[str, list[Entry]]:
    groups: defaultdict[str, list[Entry]] = defaultdict(list)
    for item in entries:
        groups[item.move.merchant].append(item)
    return groups


def _totals(entries: Sequence[Entry]) -> dict[str, Decimal]:
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    for item in entries:
        totals[item.move.merchant] += item.dop
    return totals


def _contribution(
    side: Side,
    merchant: str,
    items: Sequence[Entry],
    amount: Decimal,
    usual: Decimal,
    diff: Decimal,
    baseline: Mapping[str, Sequence[Entry]],
) -> Contribution:
    biggest = max(items, key=lambda e: (e.dop, e.move.day), default=None)
    sample = biggest or _last_seen(merchant, baseline)
    return Contribution(
        side=side,
        merchant=merchant,
        category=sample.move.category if sample else "",
        amount=amount,
        habitual=usual,
        diff=diff,
        count=len(items),
        fingerprint=biggest.move.fingerprint if biggest else "",
        day=biggest.move.day if biggest else None,
        description=biggest.move.description if biggest else "",
    )


def _last_seen(merchant: str, baseline: Mapping[str, Sequence[Entry]]) -> Entry | None:
    seen = [e for entries in baseline.values() for e in entries if e.move.merchant == merchant]
    return max(seen, key=lambda e: e.move.day, default=None)
