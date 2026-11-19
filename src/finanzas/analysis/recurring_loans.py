"""Préstamos en Recurrentes (lógica pura): qué pago de cada mes es la cuota y cuáles son abonos
extra.

- **Cuota en dos partes**: si en los últimos meses la suma del mes es estable (a
  `TOLERANCE` de su mediana) y ningún pago suelto se acerca a ella, la cuota es la suma del mes
  (un pago por mes con la suma, el día y la huella del último) y no hay abonos.
- **Tramos**: si no, cada monto exacto que se repite en dos o más meses es un tramo de cuota
  que va de su primer a su último mes. La cuota de un mes es el tramo que lo cubre (si varios,
  el que más se repite y, en empate, el más reciente: un abono que se repite dos veces no le gana
  a la cuota); un mes fuera de todo tramo usa el más cercano. Así una cuota que cambia (9 meses
  de 10k y luego 12k) es la serie entera y la nueva no pasa a abonos. Sin montos repetidos, la
  cuota es la mediana del pago más chico de cada mes.
- El pago del mes más cercano a su cuota (a `TOLERANCE` o menos) es la cuota; lo demás, abonos.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from statistics import median

from finanzas.analysis.spending import Movement

TOLERANCE = Decimal("0.10")
RECENT_MONTHS = 3  # los meses en que se mira si la suma es estable


@dataclass(frozen=True)
class LoanParts:
    regular: list[Movement]  # la cuota de cada mes (una por mes), por fecha
    extras: list[Movement]  # los abonos extra, por fecha
    cuota: Decimal  # la cuota del último mes


def _month(day: date) -> int:
    return day.year * 12 + day.month - 1


def _by_day(m: Movement) -> tuple[date, str]:
    return (m.day, m.fingerprint)


def _by_month(items: Iterable[Movement]) -> dict[int, list[Movement]]:
    found: dict[int, list[Movement]] = defaultdict(list)
    for m in items:
        found[_month(m.day)].append(m)
    return {index: sorted(paid, key=_by_day) for index, paid in found.items()}


def _gap(amount: Decimal, reference: Decimal) -> Decimal:
    return abs(amount - reference) / reference


def _split_in_parts(months: dict[int, list[Movement]]) -> list[Movement] | None:
    """La suma de cada mes como cuota, si los últimos meses pagan una suma estable en partes
    sin ningún pago suelto cerca de ella; None si no."""
    recent = sorted(months)[-RECENT_MONTHS:]
    if len(recent) < RECENT_MONTHS:
        return None
    sums = [sum((m.amount for m in months[i]), Decimal(0)) for i in recent]
    center = median(sums)
    if center <= 0 or any(_gap(s, center) > TOLERANCE for s in sums):
        return None
    if any(_gap(m.amount, center) <= TOLERANCE for i in recent for m in months[i]):
        return None
    return [
        replace(months[i][-1], amount=sum((m.amount for m in months[i]), Decimal(0)))
        for i in sorted(months)
    ]


def _tiers(months: dict[int, list[Movement]]) -> dict[int, Decimal]:
    """La cuota de cada mes (ver el docstring del módulo)."""
    seen: dict[Decimal, set[int]] = defaultdict(set)
    for index, paid in months.items():
        for m in paid:
            seen[m.amount].add(index)
    repeated = {amount: sorted(found) for amount, found in seen.items() if len(found) >= 2}
    if not repeated:
        single = median(min(m.amount for m in paid) for paid in months.values())
        return dict.fromkeys(months, single)

    def rank(amount: Decimal) -> tuple[int, int]:
        return (len(repeated[amount]), repeated[amount][-1])

    found = {}
    for index in months:
        covering = [a for a, ms in repeated.items() if ms[0] <= index <= ms[-1]]
        if covering:
            found[index] = max(covering, key=rank)
            continue

        def distance(amount: Decimal, index: int = index) -> int:
            ms = repeated[amount]
            return min(abs(index - ms[0]), abs(index - ms[-1]))

        found[index] = min(repeated, key=lambda a: (distance(a), -rank(a)[0], -rank(a)[1]))
    return found


def split(items: Sequence[Movement]) -> LoanParts:
    """La cuota de cada mes y los abonos extra de los pagos (positivos) de un préstamo."""
    months = _by_month(items)
    in_parts = _split_in_parts(months)
    if in_parts is not None:
        return LoanParts(in_parts, [], in_parts[-1].amount)
    tiers = _tiers(months)
    regular: list[Movement] = []
    extras: list[Movement] = []
    for index in sorted(months):
        cuota = tiers[index]
        paid = sorted(months[index], key=lambda m: (abs(m.amount - cuota), *_by_day(m)))
        if cuota > 0 and _gap(paid[0].amount, cuota) <= TOLERANCE:
            regular.append(paid[0])
            extras.extend(paid[1:])
        else:
            extras.extend(paid)
    return LoanParts(sorted(regular, key=_by_day), sorted(extras, key=_by_day), tiers[max(months)])


def installment_amount(items: Sequence[Movement]) -> Decimal:
    """La cuota del último mes con pagos."""
    return split(items).cuota
