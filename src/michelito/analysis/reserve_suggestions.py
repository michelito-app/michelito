"""Reserve suggestions (never created on their own; dismissing is forever, by key). Pure.

It looks at spending per category and month **without one-offs**, over the last `WINDOW_MONTHS`
complete months. Three sources, in this order of preference:

1. **Active yearly recurring** (`from_recurring`): its name, its yearly amount in RD$ and the month
   of its last charge (`recurring:<series>:<currency>`).
2. **Irregular category** (`irregular`): with spending in fewer than half the months
   (`IRREGULAR_SHARE`) but at least `IRREGULAR_MIN_YEARLY` a year on average over the complete
   years (January to December, the last 3), with spending in at least `IRREGULAR_YEARS` of them (a
   new category does not count), such as travel: **one** suggestion "Travel ~ RD$ X/year", every
   year, due in the month of the year with the most spending in the window
   (`irregular:<category>`).
3. **Peak in a given month** (`peak`, for the other categories): the same month of the year that,
   in at least `PEAK_YEARS` of the last `PEAK_LAST_YEARS` years, is that year's month with the
   most spending or is worth at least `PEAK_FACTOR` times the median of the category's months with
   spending, **and** exceeds it by `PEAK_EXCESS` or more. It is proposed for the excess of the
   last of those years ("December: Entertainment", multiple expenses; `peak:<category>:<MM>`). A
   single year never suggests anything.

Sources 2 and 3 skip (`excluded`, decided by `web.budget`) the categories whose spending comes
mostly (`RECURRING_SHARE` or more) from monthly recurring series, those in the housing and loans
groups of Recurring, and cash, other and bank fees (`EXCLUDED_REFS`, by their stable reference). A
yearly recurring charge in those categories is still suggested as such.

At the end (`pending_suggestions`): drop what was dismissed and what already exists (from that
suggestion or as a reserve of that category), **at most one per category** (the most preferred);
first the peaks repeated in all `PEAK_LAST_YEARS` years, then by amount, largest first, and at
most `MAX_SUGGESTIONS`. Amounts are rounded up to RD$ 100.
"""

from __future__ import annotations

import statistics
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from michelito.analysis import categories
from michelito.analysis.reserves import NAME_MAX, Reserve, ceil_to, month_name, next_of_month
from michelito.i18n import t

SUGGESTION_STEP = Decimal(100)
WINDOW_MONTHS = 36
IRREGULAR_SHARE = Decimal("0.5")
IRREGULAR_MIN_YEARLY = Decimal(36_000)  # RD$ 3,000 a month on average
PEAK_FACTOR = Decimal(2)
PEAK_EXCESS = Decimal(10_000)
PEAK_YEARS = 2
PEAK_LAST_YEARS = 3
MAX_SUGGESTIONS = 8
IRREGULAR_YEARS = 2
RECURRING_SHARE = Decimal("0.5")
# Categories never suggested as irregular or by peak (still as yearly recurring).
EXCLUDED_REFS = frozenset({categories.CASH, categories.OTHER, categories.BANK_FEES})
EXCLUDED_GROUPS = frozenset({"housing", "loans"})  # groups of `recurring.GROUPS`
_ZERO = Decimal(0)


@dataclass(frozen=True)
class Suggestion:
    key: str  # "recurring:...", "irregular:<category>" or "peak:<category>:<MM>"
    name: str
    amount: Decimal  # RD$, rounded up to RD$ 100
    category_id: int
    due_month: str  # the next due month
    every_months: int
    multiple: bool
    reason: str
    repeats: int = 0  # for a peak: in how many of the last years it repeats


@dataclass(frozen=True)
class RecurringSource:
    """An active yearly recurring charge (from `web.recurring`), already in RD$."""

    key: str
    name: str
    category_id: int
    yearly_dop: Decimal
    last_day: date


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    ref: str  # stable reference (for the key)


def window(complete: Iterable[str]) -> list[str]:
    """The last `WINDOW_MONTHS` complete months, oldest first."""
    return sorted(set(complete))[-WINDOW_MONTHS:]


def from_recurring(sources: Iterable[RecurringSource], current: str) -> list[Suggestion]:
    """One reserve per active yearly recurring charge: due in the month of its last charge."""
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
                reason=t("analysis.reserve_suggestions.yearly_recurring", month=month_name(due)),
            )
        )
    return found


def is_irregular(by_month: Mapping[str, Decimal], months: Sequence[str]) -> bool:
    """With spending in fewer than half the months."""
    active = sum(1 for m in months if by_month.get(m, _ZERO) > 0)
    return bool(months) and active < len(months) * IRREGULAR_SHARE


def _complete_years(months: Sequence[str]) -> list[str]:
    present = set(months)
    years = sorted({m[:4] for m in months})
    return [y for y in years if all(f"{y}-{n:02d}" in present for n in range(1, 13))]


def irregular(
    category: Category, by_month: Mapping[str, Decimal], months: Sequence[str], current: str
) -> Suggestion | None:
    """ "Travel ~ RD$ X/year" for an irregular category with a significant yearly total."""
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
        reason=t(
            "analysis.reserve_suggestions.irregular_one_year"
            if len(years) == 1
            else "analysis.reserve_suggestions.irregular_years",
            amount=f"{int(amount):,}",
            years=len(years),
            month=month_name(due),
        ),
    )


def peak(
    category: Category, by_month: Mapping[str, Decimal], months: Sequence[str], current: str
) -> Suggestion | None:
    """The month of the year with a repeated peak (see the module docstring), or None."""
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
        key=f"peak:{category.ref}:{last_month[5:]}",
        name=t(
            "analysis.reserve_suggestions.peak_name",
            month=month_name(due).capitalize(),
            category=category.name,
        )[:NAME_MAX],
        amount=ceil_to(excess, SUGGESTION_STEP),
        category_id=category.id,
        due_month=due,
        every_months=12,
        multiple=True,
        reason=t(
            "analysis.reserve_suggestions.peak",
            month=month_name(due),
            count=len(hit_years),
            years=", ".join(hit_years),
        ),
        repeats=len(hit_years),
    )


def from_history(
    regular: Mapping[int, Mapping[str, Decimal]],
    complete: Iterable[str],
    categories: Iterable[Category],
    current: str,
    excluded: Collection[int] = (),
) -> list[Suggestion]:
    """At most one per category: irregular or, if it is not, its repeated peak (without those in
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
    """The ones still standing (see the module docstring), largest amount first."""
    sources = {r.source for r in reserves if r.source}
    taken = {r.category_id for r in reserves}
    found = []
    for item in candidates:
        if item.key in dismissed or item.key in sources or item.category_id in taken:
            continue
        taken.add(item.category_id)  # one per category: the first (most preferred)
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
    """The categories not suggested as irregular or by peak: by reference (`EXCLUDED_REFS`), by
    Recurring group (`groups`: category -> its group key) or because at least `RECURRING_SHARE`
    of their spending in the window comes from monthly recurring series (`monthly_recurring`: the
    amounts of those series, per category and month)."""
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
