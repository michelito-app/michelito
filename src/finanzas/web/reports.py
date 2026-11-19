"""Reportes: comparar meses (categorías × meses) con lo habitual de cada categoría.

Cada mes sale de `summary.build_summary` (los mismos números y la misma referencia que el
Resumen), así una celda nunca contradice al Resumen de ese mes. Una celda se destaca si se
aparta de lo habitual de su categoría más que max(30 %, CATEGORY_FLOOR); la intensidad de una
subida (1 a 3) crece con el desvío relativo (ver `cell_flag`).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from finanzas.analysis import anomalies
from finanzas.analysis.accounts import AccountInfo
from finanzas.analysis.rates import Rate
from finanzas.analysis.spending import Movement
from finanzas.web import summary

MAX_MONTHS = 24
DEFAULT_MONTHS = 12
CATEGORY_FLOOR = Decimal(1_000)
# Desvío relativo (sobre lo habitual) desde el que una subida pasa a intensidad 2 y 3.
LEVEL_STEPS = (Decimal("0.6"), Decimal(1))

_ZERO = Decimal(0)


@dataclass(frozen=True)
class Cell:
    amount: Decimal
    habitual: Decimal | None  # None: el mes no se compara (en curso o sin meses anteriores)
    flag: anomalies.Direction | None
    level: int  # 0 sin desvío o a la baja; 1 a 3 en una subida


@dataclass(frozen=True)
class Row:
    key: str  # "ingresos", "gastos", "terceros", "neto" o el nombre de la categoría
    label: str
    cells: list[Cell]


@dataclass(frozen=True)
class Comparison:
    months: list[summary.MonthOption]  # del más viejo al más nuevo
    totals: list[Row]
    categories: list[Row]
    # Los ingresos por categoría (clave `ingreso:<nombre>`; «Cripto» aparte de «Otros ingresos»),
    # por total del rango. Sin comparación con lo habitual: solo los montos.
    incomes: list[Row] = field(default_factory=list)


def cell_flag(amount: Decimal, habitual: Decimal | None) -> tuple[anomalies.Direction | None, int]:
    """Desvío de una celda frente a lo habitual de su categoría, y su intensidad."""
    if habitual is None:
        return None, 0
    flag = anomalies.deviation(amount, habitual, floor=CATEGORY_FLOOR)
    if flag != "up":
        return flag, 0
    if habitual <= 0:
        return flag, 3
    ratio = (amount - habitual) / habitual
    return flag, 1 + sum(1 for step in LEVEL_STEPS if ratio >= step)


def month_range(available: Sequence[str], first: str | None, last: str | None) -> list[str]:
    """Los meses con datos entre `first` y `last` (del más viejo al más nuevo). Sin rango, los
    DEFAULT_MONTHS más recientes. ValueError si el rango está al revés o pasa de MAX_MONTHS."""
    months = sorted(available)
    if first is None and last is None:
        return months[-DEFAULT_MONTHS:]
    start, end = first or months[0], last or months[-1]
    if start > end:
        raise ValueError("el mes «desde» va después del mes «hasta»")
    chosen = [m for m in months if start <= m <= end]
    if len(chosen) > MAX_MONTHS:
        raise ValueError(f"a lo sumo {MAX_MONTHS} meses")
    return chosen


def compare(
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    rates: Mapping[str, Rate],
    *,
    first: str | None = None,
    last: str | None = None,
    selected: Collection[str] | None = None,
) -> Comparison:
    options = summary.month_options(movements, accounts, selected)
    wanted = month_range([o.month for o in options], first, last)
    built = [summary.build_summary(movements, accounts, rates, m, selected) for m in wanted]
    return Comparison(
        months=[s.option for s in built],
        totals=_totals(built),
        categories=_categories(built),
        incomes=_incomes(built),
    )


INCOME_PREFIX = "ingreso:"


def _incomes(built: Sequence[summary.Summary]) -> list[Row]:
    by_month = [{line.category: line.amount for line in s.income_lines} for s in built]
    totals: dict[str, Decimal] = {}
    for lines in by_month:
        for name, amount in lines.items():
            totals[name] = totals.get(name, _ZERO) + amount
    names = sorted(totals, key=lambda name: (-totals[name], name))
    return [
        Row(f"{INCOME_PREFIX}{name}", name, [_plain(lines.get(name, _ZERO)) for lines in by_month])
        for name in names
    ]


def _totals(built: Sequence[summary.Summary]) -> list[Row]:
    def trend_cell(s: summary.Summary, income: bool) -> Cell:
        point = s.trend[-1]
        if income:
            return Cell(s.income, point.income_habitual, point.income_flag, 0)
        flag = point.spent_flag
        return Cell(
            s.total, point.spent_habitual, flag, cell_flag(s.total, point.spent_habitual)[1]
        )

    return [
        Row("ingresos", "Ingresos", [trend_cell(s, income=True) for s in built]),
        Row("gastos", "Gastos", [trend_cell(s, income=False) for s in built]),
        Row("terceros", "Transferencias a terceros", [_plain(s.third_party) for s in built]),
        Row("neto", "Te quedó", [_plain(s.net) for s in built]),
    ]


def _plain(amount: Decimal | None) -> Cell:
    return Cell(amount if amount is not None else _ZERO, None, None, 0)


def _categories(built: Sequence[summary.Summary]) -> list[Row]:
    by_month = [{line.category: line for line in s.categories} for s in built]
    totals: dict[str, Decimal] = {}
    for lines in by_month:
        for name, line in lines.items():
            totals[name] = totals.get(name, _ZERO) + line.amount
    names = sorted(totals, key=lambda name: (-totals[name], name))
    return [
        Row(
            name,
            name,
            [_category_cell(lines.get(name), s) for lines, s in zip(by_month, built, strict=True)],
        )
        for name in names
    ]


def _category_cell(line: summary.CategoryLine | None, built: summary.Summary) -> Cell:
    if line is None:
        # Ni en el mes ni en sus meses de referencia: cero contra cero (si se compara).
        habitual = None if built.habitual is None else _ZERO
        return Cell(_ZERO, habitual, None, 0)
    flag, level = cell_flag(line.amount, line.habitual)
    return Cell(line.amount, line.habitual, flag, level)
