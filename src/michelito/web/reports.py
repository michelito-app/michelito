"""Reports: compare months (categories x months) against each category's usual amount.

Each month comes from `summary.build_summary` (the same numbers and the same baseline as the
Summary), so a cell never contradicts that month's Summary. A cell stands out when it deviates
from its category's usual amount by more than max(30 %, CATEGORY_FLOOR); the intensity of a
rise (1 to 3) grows with the relative deviation (see `cell_flag`).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from michelito.analysis import anomalies
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import summary

MAX_MONTHS = 24
DEFAULT_MONTHS = 12
CATEGORY_FLOOR = Decimal(1_000)
# Relative deviation (over the usual amount) from which a rise becomes intensity 2 and 3.
LEVEL_STEPS = (Decimal("0.6"), Decimal(1))

_ZERO = Decimal(0)


@dataclass(frozen=True)
class Cell:
    amount: Decimal
    habitual: Decimal | None  # None: the month is not compared (in progress or no earlier months)
    flag: anomalies.Direction | None
    level: int  # 0 without deviation or on a drop; 1 to 3 on a rise


@dataclass(frozen=True)
class Row:
    key: str  # "income", "expenses", "third_party", "net" or the category name
    label: str
    cells: list[Cell]


@dataclass(frozen=True)
class Comparison:
    months: list[summary.MonthOption]  # oldest to newest
    totals: list[Row]
    categories: list[Row]
    # Income by category (key `income:<name>`; crypto apart from other income), by range
    # total. Not compared with the usual amount: only the amounts.
    incomes: list[Row] = field(default_factory=list)


def cell_flag(amount: Decimal, habitual: Decimal | None) -> tuple[anomalies.Direction | None, int]:
    """A cell's deviation from its category's usual amount, and its intensity."""
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
    """The months with data between `first` and `last` (oldest to newest). Without a range, the
    DEFAULT_MONTHS most recent. ValueError if the range is reversed or exceeds MAX_MONTHS."""
    months = sorted(available)
    if first is None and last is None:
        return months[-DEFAULT_MONTHS:]
    start, end = first or months[0], last or months[-1]
    if start > end:
        raise ValueError(t("web.report.reversed_range"))
    chosen = [m for m in months if start <= m <= end]
    if len(chosen) > MAX_MONTHS:
        raise ValueError(t("web.report.too_many_months", max=MAX_MONTHS))
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


INCOME_PREFIX = "income:"


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
        Row("income", t("web.report.income"), [trend_cell(s, income=True) for s in built]),
        Row("expenses", t("web.report.expenses"), [trend_cell(s, income=False) for s in built]),
        Row("third_party", t("web.report.third_party"), [_plain(s.third_party) for s in built]),
        Row("net", t("web.report.net"), [_plain(s.net) for s in built]),
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
        # Neither in the month nor in its baseline months: zero against zero (if compared).
        habitual = None if built.habitual is None else _ZERO
        return Cell(_ZERO, habitual, None, 0)
    flag, level = cell_flag(line.amount, line.habitual)
    return Cell(line.amount, line.habitual, flag, level)
