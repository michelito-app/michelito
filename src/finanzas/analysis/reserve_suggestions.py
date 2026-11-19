"""Sugerencias de reservas (nunca se crean solas; descartar es para siempre, por su clave). Pura.

Se mira lo gastado por categoría y mes **sin gastos únicos**, en los últimos `WINDOW_MONTHS`
meses completos. Tres fuentes, en este orden de preferencia:

1. **Recurrente anual activo** (`from_recurring`): su nombre, su monto anual en RD$ y el mes de su
   último cobro (`recurrente:<serie>:<moneda>`).
2. **Categoría irregular** (`irregular`): con gasto en menos de la mitad de los meses
   (`IRREGULAR_SHARE`) pero al menos `IRREGULAR_MIN_YEARLY` al año en promedio de los años
   completos (de enero a diciembre, los últimos 3), con gasto en al menos `IRREGULAR_YEARS` de
   ellos (una categoría nueva no cuenta), como Viajes: **una** sugerencia «Viajes ≈ RD$ X/año»,
   cada año, que vence en el mes del año con más gasto en la ventana (`irregular:<categoría>`).
3. **Pico de un mes concreto** (`peak`, en las demás categorías): un mismo mes del año que, en al
   menos `PEAK_YEARS` de los últimos `PEAK_LAST_YEARS` años, es el mes de más gasto de ese año o
   vale al menos `PEAK_FACTOR` veces la mediana de los meses con gasto de la categoría, **y**
   la pasa por `PEAK_EXCESS` o más. Se propone por el exceso del último de esos años
   («Diciembre: Entretenimiento», varios gastos; `pico:<categoría>:<MM>`). Un solo año nunca
   sugiere nada.

Las fuentes 2 y 3 no miran (`excluded`, lo decide `web.budget`) las categorías cuyo gasto viene
sobre todo (`RECURRING_SHARE` o más) de series recurrentes mensuales, las de los grupos Vivienda y
Préstamos de Recurrentes, ni Efectivo, Otros y Cargos del banco (`EXCLUDED_REFS`, por su
referencia estable). Un recurrente anual de esas categorías se sigue sugiriendo como tal.

Al final (`pending_suggestions`): fuera lo descartado, lo ya creado (de esa sugerencia o con una
reserva de esa categoría), **como mucho una por categoría** (la de mayor preferencia); primero los
picos que se repiten en los `PEAK_LAST_YEARS` años, luego de mayor a menor monto, y como mucho
`MAX_SUGGESTIONS`. Los montos se redondean hacia arriba a RD$ 100.
"""

from __future__ import annotations

import statistics
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finanzas.analysis import categories
from finanzas.analysis.reserves import NAME_MAX, Reserve, ceil_to, month_name, next_of_month

SUGGESTION_STEP = Decimal(100)
WINDOW_MONTHS = 36
IRREGULAR_SHARE = Decimal("0.5")
IRREGULAR_MIN_YEARLY = Decimal(36_000)  # RD$ 3,000 al mes en promedio
PEAK_FACTOR = Decimal(2)
PEAK_EXCESS = Decimal(10_000)
PEAK_YEARS = 2
PEAK_LAST_YEARS = 3
MAX_SUGGESTIONS = 8
IRREGULAR_YEARS = 2
RECURRING_SHARE = Decimal("0.5")
# Categorías que nunca se sugieren como irregulares ni por pico (sí como recurrente anual).
EXCLUDED_REFS = frozenset({categories.CASH, categories.OTHER, categories.BANK_FEES})
EXCLUDED_GROUPS = frozenset({"vivienda", "prestamos"})  # grupos de `recurring.GROUPS`
_ZERO = Decimal(0)


@dataclass(frozen=True)
class Suggestion:
    key: str  # «recurrente:…», «irregular:<categoría>» o «pico:<categoría>:<MM>»
    name: str
    amount: Decimal  # RD$, redondeado hacia arriba a RD$ 100
    category_id: int
    due_month: str  # el próximo vencimiento
    every_months: int
    multiple: bool
    reason: str
    repeats: int = 0  # en un pico: en cuántos de los últimos años se repite


@dataclass(frozen=True)
class RecurringSource:
    """Un recurrente anual activo (de `web.recurring`), ya en RD$."""

    key: str
    name: str
    category_id: int
    yearly_dop: Decimal
    last_day: date


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    ref: str  # referencia estable (para la clave)


def window(complete: Iterable[str]) -> list[str]:
    """Los últimos `WINDOW_MONTHS` meses completos, de más viejo a más nuevo."""
    return sorted(set(complete))[-WINDOW_MONTHS:]


def from_recurring(sources: Iterable[RecurringSource], current: str) -> list[Suggestion]:
    """Una reserva por cada recurrente anual activo: vence el mes de su último cobro."""
    found = []
    for source in sources:
        if source.yearly_dop <= 0:
            continue
        due = next_of_month(source.last_day.month, current)
        found.append(
            Suggestion(
                key=source.key,
                name=source.name[:NAME_MAX],
                amount=ceil_to(source.yearly_dop, SUGGESTION_STEP),
                category_id=source.category_id,
                due_month=due,
                every_months=12,
                multiple=False,
                reason=f"Recurrente anual: se cobra en {month_name(due)}",
            )
        )
    return found


def is_irregular(by_month: Mapping[str, Decimal], months: Sequence[str]) -> bool:
    """Con gasto en menos de la mitad de los meses."""
    active = sum(1 for m in months if by_month.get(m, _ZERO) > 0)
    return bool(months) and active < len(months) * IRREGULAR_SHARE


def _complete_years(months: Sequence[str]) -> list[str]:
    present = set(months)
    years = sorted({m[:4] for m in months})
    return [y for y in years if all(f"{y}-{n:02d}" in present for n in range(1, 13))]


def irregular(
    category: Category, by_month: Mapping[str, Decimal], months: Sequence[str], current: str
) -> Suggestion | None:
    """«Viajes ≈ RD$ X/año» para una categoría irregular con un total anual que pesa."""
    if not is_irregular(by_month, months):
        return None
    years = _complete_years(months)[-PEAK_LAST_YEARS:]
    if not years:
        return None
    totals = [
        sum((by_month.get(f"{y}-{n:02d}", _ZERO) for n in range(1, 13)), _ZERO) for y in years
    ]
    if sum(1 for total in totals if total > 0) < IRREGULAR_YEARS:
        return None
    yearly = sum(totals, _ZERO) / len(totals)
    if yearly < IRREGULAR_MIN_YEARLY:
        return None
    by_number = {n: _ZERO for n in range(1, 13)}
    for month in months:
        by_number[int(month[5:])] += by_month.get(month, _ZERO)
    busiest = max(by_number, key=lambda n: (by_number[n], -n))
    due = next_of_month(busiest, current)
    amount = ceil_to(yearly, SUGGESTION_STEP)
    return Suggestion(
        key=f"irregular:{category.ref}",
        name=category.name[:NAME_MAX],
        amount=amount,
        category_id=category.id,
        due_month=due,
        every_months=12,
        multiple=True,
        reason=f"Gasto irregular: ≈ RD$ {int(amount):,}/año (promedio de {len(years)} "
        f"{'año' if len(years) == 1 else 'años'}); más en {month_name(due)}",
    )


def peak(
    category: Category, by_month: Mapping[str, Decimal], months: Sequence[str], current: str
) -> Suggestion | None:
    """El mes del año con pico repetido (ver el docstring del módulo), o None."""
    spending = [by_month[m] for m in months if by_month.get(m, _ZERO) > 0]
    if not spending:
        return None
    usual = statistics.median(spending)
    years = sorted({m[:4] for m in months})[-PEAK_LAST_YEARS:]
    best: tuple[str, Decimal, list[str]] | None = None
    for number in range(1, 13):
        hits: list[tuple[str, Decimal]] = []
        for year in years:
            month = f"{year}-{number:02d}"
            if month not in months:
                continue
            amount = by_month.get(month, _ZERO)
            top = max(by_month.get(m, _ZERO) for m in months if m[:4] == year)
            is_peak = amount > 0 and (amount >= top or amount >= usual * PEAK_FACTOR)
            if is_peak and amount - usual >= PEAK_EXCESS:
                hits.append((month, amount - usual))
        if len(hits) < PEAK_YEARS:
            continue
        last_month, excess = max(hits)
        if best is None or excess > best[1]:
            best = (last_month, excess, [m[:4] for m, _ in hits])
    if best is None:
        return None
    last_month, excess, hit_years = best
    due = next_of_month(int(last_month[5:]), current)
    return Suggestion(
        key=f"pico:{category.ref}:{last_month[5:]}",
        name=f"{month_name(due).capitalize()}: {category.name}"[:NAME_MAX],
        amount=ceil_to(excess, SUGGESTION_STEP),
        category_id=category.id,
        due_month=due,
        every_months=12,
        multiple=True,
        reason=f"Pico en {month_name(due)} en {len(hit_years)} años ({', '.join(hit_years)})",
        repeats=len(hit_years),
    )


def from_history(
    regular: Mapping[int, Mapping[str, Decimal]],
    complete: Iterable[str],
    categories: Iterable[Category],
    current: str,
    excluded: Collection[int] = (),
) -> list[Suggestion]:
    """Una por categoría a lo sumo: irregular o, si no lo es, su pico repetido (sin las de
    `excluded`)."""
    months = window(complete)
    found = []
    for category in categories:
        if category.id in excluded:
            continue
        by_month = regular.get(category.id, {})
        if not by_month:
            continue
        if is_irregular(by_month, months):
            item = irregular(category, by_month, months, current)
        else:
            item = peak(category, by_month, months, current)
        if item is not None:
            found.append(item)
    return found


def pending_suggestions(
    candidates: Iterable[Suggestion],
    reserves: Sequence[Reserve],
    dismissed: Collection[str],
    limit: int = MAX_SUGGESTIONS,
) -> list[Suggestion]:
    """Las que siguen en pie (ver el docstring del módulo), de mayor a menor monto."""
    sources = {r.source for r in reserves if r.source}
    taken = {r.category_id for r in reserves}
    found = []
    for item in candidates:
        if item.key in dismissed or item.key in sources or item.category_id in taken:
            continue
        taken.add(item.category_id)  # una por categoría: la primera (de mayor preferencia)
        found.append(item)
    found.sort(key=lambda s: (s.repeats < PEAK_LAST_YEARS, -s.amount, s.name))
    return found[:limit]


def excluded_categories(
    items: Iterable[Category],
    regular: Mapping[int, Mapping[str, Decimal]],
    monthly_recurring: Mapping[int, Mapping[str, Decimal]],
    complete: Iterable[str],
    groups: Mapping[int, str],
) -> set[int]:
    """Las categorías que no se sugieren como irregulares ni por pico: por referencia
    (`EXCLUDED_REFS`), por grupo de Recurrentes (`groups`: categoría -> clave de su grupo) o porque
    al menos `RECURRING_SHARE` de su gasto en la ventana es de recurrentes mensuales
    (`monthly_recurring`: lo de esas series, por categoría y mes)."""
    months = window(complete)
    found = set()
    for category in items:
        if category.ref in EXCLUDED_REFS or groups.get(category.id) in EXCLUDED_GROUPS:
            found.add(category.id)
            continue
        total = sum((regular.get(category.id, {}).get(m, _ZERO) for m in months), _ZERO)
        fixed = sum((monthly_recurring.get(category.id, {}).get(m, _ZERO) for m in months), _ZERO)
        if total > 0 and fixed >= total * RECURRING_SHARE:
            found.add(category.id)
    return found
