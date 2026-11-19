"""Reserves for expenses that do not come every month (YNAB: "embrace your true expenses").
Pure logic.

A reserve is a virtual plan that moves no money: a name, an estimated amount in RD$, an expense
category and its due dates. **Due-date model** (the minimum that covers "yearly", "every six
months" and "once, in a given month"): the first due month (`due_month`, YYYY-MM) and how many
months it repeats after (`every_months`: 12 yearly or 6 half-yearly; None: only once, in that
month). A repeating one is also due every N months backwards: the first due month only sets the
phase ("every year in January"), so an expense from last January belongs to it.

**Monthly contribution** (`monthly_contribution`): amount / months between due dates. When it
repeats, those months are `every_months` (yearly: amount / 12). Once only: the months from the
month the reserve was created (`start_month`) to its due month, **both included**
(`due - start + 1`): created in the month it is due, the contribution is the whole amount;
already past due, 0. It is rounded **up to RD$ 100** (`CONTRIBUTION_STEP`), so that setting that
aside every month never falls short. A reserve whose next due date already has its expense linked
(`paid_dues`) does not add to the month's contribution and does not show in the upcoming large
expenses.

Expenses linked to a reserve (`links`, role `'reserved'`) do not count against their category's
cap (`analysis.budget`) and are shown as covered by the reserve. A reserve can gather several
expenses (`multiple`, e.g. Christmas). Reserve suggestions live in `reserve_suggestions`.

**Suggested link** ("To review", `possible_reserve`; `link_suggestions`). Never for a due date
before the month the reserve was created.
- A single-expense one: an unlinked expense of the same category, in a month within
  ±`LINK_WINDOW` of a due date, within ±`LINK_TOLERANCE` of the estimate, if that due date does
  not have one yet.
- A multiple-expense one: only expenses **in the due month**, of the same category, not from a
  recurring merchant, and only **what exceeds the usual** for the category in that month (the
  median of the previous 6 complete months, `habitual_before`): largest first, while what is
  already linked plus the expense stays within that excess and within 150 % of the estimate;
  those under `MULTIPLE_MIN_SHARE` of the estimate are not proposed. With no usual amount for that
  month, nothing is proposed.
- If an expense fits two reserves, the one whose estimate is closest to its amount is proposed.

Still open (not built): comparing what was set aside with the balance of a reserve account.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal

from michelito.i18n import t

CONTRIBUTION_STEP = Decimal(100)
UPCOMING_DAYS = 60
LINK_WINDOW = 1  # months before or after a due date
LINK_TOLERANCE = Decimal("0.50")
MULTIPLE_MIN_SHARE = Decimal("0.05")
HABITUAL_MONTHS = 6
EVERY_CHOICES = (6, 12)  # every 6 months or every year (None: only once)
NAME_MAX = 80
AMOUNT_MAX = Decimal(100_000_000)

# The month names the UI shows ("enero" ... "diciembre"), from the catalog.
MONTH_NAMES = tuple(t(f"analysis.reserves.month_{number:02d}") for number in range(1, 13))
_ZERO = Decimal(0)

HabitualFor = Callable[[int, str], Decimal | None]


class ReserveError(ValueError):
    """Invalid request on a reserve (422)."""


@dataclass(frozen=True)
class Reserve:
    id: int
    name: str
    amount: Decimal  # estimated RD$ per due date
    category_id: int
    due_month: str  # first due month, YYYY-MM
    every_months: int | None  # None: only once
    multiple: bool = False
    members: tuple[str, ...] = ()  # fingerprints of the linked expenses
    created_month: str = ""  # the month saving starts from (`start_month`)
    source: str | None = None  # key of the suggestion it came from


@dataclass(frozen=True)
class Spent:
    """An expense already in RD$ (`dop` None: US$ without a rate) with its category (catalog id)."""

    fingerprint: str
    day: date
    category_id: int | None
    dop: Decimal | None
    recurring: bool = False  # from a recurring merchant (not proposed for multiple)

    @property
    def month(self) -> str:
        return self.day.strftime("%Y-%m")


# --- Months ---------------------------------------------------------------------------------


def month_index(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def month_at(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_name(month: str) -> str:
    return MONTH_NAMES[int(month[5:7]) - 1]


def check_month(month: str) -> str:
    if len(month) != 7 or month[4] != "-" or not (month[:4] + month[5:]).isdigit():
        raise ReserveError(t("analysis.reserves.due_format"))
    if not 1 <= int(month[5:]) <= 12:
        raise ReserveError(t("analysis.reserves.due_month_range"))
    return month


def due_months(reserve: Reserve, start: str, end: str) -> list[str]:
    """The due months between `start` and `end` (included)."""
    first, low, high = month_index(reserve.due_month), month_index(start), month_index(end)
    if reserve.every_months is None:
        return [reserve.due_month] if low <= first <= high else []
    # A repeating one is due every `step` months forwards and backwards: the first due month
    # only sets the phase ("every year in January").
    step = reserve.every_months
    index = first + -(-(low - first) // step) * step
    found = []
    while index <= high:
        found.append(month_at(index))
        index += step
    return found


def next_due(reserve: Reserve, current: str) -> str | None:
    """The first due month from `current` (included); None if it was one-time and has passed."""
    found = due_months(reserve, current, month_at(month_index(current) + 12 * 50))
    return found[0] if found else None


def near_due(reserve: Reserve, month: str, window: int = LINK_WINDOW) -> str | None:
    """The due month within ±`window` months of `month` (the closest one), or None."""
    index = month_index(month)
    found = due_months(reserve, month_at(index - window), month_at(index + window))
    return min(found, key=lambda d: (abs(month_index(d) - index), d), default=None)


def ceil_to(value: Decimal, step: Decimal) -> Decimal:
    """`value` rounded up to a multiple of `step`."""
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def next_of_month(number: int, current: str) -> str:
    """The next month `number` (1-12) from `current` (included)."""
    year = int(current[:4])
    if number < int(current[5:]):
        year += 1
    return f"{year:04d}-{number:02d}"


def monthly_contribution(reserve: Reserve, current: str) -> Decimal:
    """How much to set aside per month (see the module docstring), rounded up to RD$ 100."""
    if reserve.every_months is not None:
        return ceil_to(reserve.amount / reserve.every_months, CONTRIBUTION_STEP)
    due = month_index(reserve.due_month)
    if due < month_index(current):
        return _ZERO
    start = month_index(reserve.created_month or current)
    return ceil_to(reserve.amount / max(1, due - start + 1), CONTRIBUTION_STEP)


def paid_dues(reserves: Iterable[Reserve], spent: Mapping[str, Spent]) -> set[tuple[int, str]]:
    """(reserve, due month) pairs that already have a linked expense (within ±`LINK_WINDOW`
    months)."""
    found = set()
    for reserve in reserves:
        for fp in reserve.members:
            item = spent.get(fp)
            due = None if item is None else near_due(reserve, item.month)
            if due is not None:
                found.add((reserve.id, due))
    return found


def monthly_total(
    reserves: Iterable[Reserve], current: str, paid: Collection[tuple[int, str]] = ()
) -> Decimal:
    """What is set aside per month for all of them, without those whose next due date is paid."""
    return sum(
        (
            monthly_contribution(r, current)
            for r in reserves
            if (r.id, next_due(r, current)) not in paid
        ),
        _ZERO,
    )


@dataclass(frozen=True)
class YearStatus:
    spent: Decimal  # linked expenses dated in the year, in RD$
    estimated: Decimal  # the amount for each due date in the year
    without_rate: int  # linked US$ expenses without a rate (not added)


def year_status(reserve: Reserve, year: int, spent: Mapping[str, Spent]) -> YearStatus:
    total, missing = _ZERO, 0
    for fp in reserve.members:
        item = spent.get(fp)
        if item is None or item.day.year != year:
            continue
        if item.dop is None:
            missing += 1
        else:
            total += item.dop
    dues = due_months(reserve, f"{year:04d}-01", f"{year:04d}-12")
    return YearStatus(total, reserve.amount * len(dues), missing)


def upcoming(
    reserves: Iterable[Reserve],
    today: date,
    days: int = UPCOMING_DAYS,
    paid: Collection[tuple[int, str]] = (),
) -> list[tuple[Reserve, str]]:
    """The reserves due from this month to `days` days after today (the first day of the due month
    falls within that window), the closest first; without those whose expense for that due date
    is already linked (`paid`)."""
    current = today.strftime("%Y-%m")
    limit = today + timedelta(days=days)
    found = []
    for reserve in reserves:
        due = next_due(reserve, current)
        if due is None or (reserve.id, due) in paid:
            continue
        if date(int(due[:4]), int(due[5:]), 1) <= limit:
            found.append((reserve, due))
    return sorted(found, key=lambda pair: (pair[1], pair[0].name, pair[0].id))


# --- Suggested links ------------------------------------------------------------------------


def habitual_before(
    regular: Mapping[int, Mapping[str, Decimal]], complete: Sequence[str], category: int, month: str
) -> Decimal | None:
    """The category's usual amount in `month`: the median spent (without one-offs) over the
    previous `HABITUAL_MONTHS` complete months; None without any."""
    before = [m for m in sorted(set(complete)) if m < month][-HABITUAL_MONTHS:]
    if not before:
        return None
    usual = regular.get(category, {})
    return statistics.median(usual.get(m, _ZERO) for m in before)


def link_suggestions(
    expenses: Sequence[Spent],
    reserves: Sequence[Reserve],
    linked: Collection[str],
    habitual: HabitualFor | None = None,
) -> dict[str, int]:
    """Expense fingerprint -> the proposed reserve (see the module docstring). `linked`: the
    fingerprints already in some link; `habitual(category, month)`: the category's usual amount
    in that month (for multiple-expense reserves; without it they are not proposed)."""
    by_fp = {e.fingerprint: e for e in expenses}
    choices: dict[str, list[tuple[Decimal, int, int]]] = defaultdict(list)
    for reserve in reserves:
        found = (
            _multiple(reserve, expenses, by_fp, linked, habitual)
            if reserve.multiple
            else _single(reserve, expenses, by_fp, linked)
        )
        for item, distance in found:
            score = abs(reserve.amount - (item.dop or _ZERO))
            choices[item.fingerprint].append((score, distance, reserve.id))
    return {fp: min(options)[2] for fp, options in choices.items()}


def _usable(item: Spent, linked: Collection[str]) -> bool:
    return item.fingerprint not in linked and item.dop is not None and item.dop > 0


def _started(reserve: Reserve, due: str) -> bool:
    return not reserve.created_month or due >= reserve.created_month


def _cycle(reserve: Reserve, due: str, by_fp: Mapping[str, Spent]) -> list[Spent]:
    return [
        by_fp[fp]
        for fp in reserve.members
        if fp in by_fp and near_due(reserve, by_fp[fp].month) == due
    ]


def _single(
    reserve: Reserve, expenses: Sequence[Spent], by_fp: Mapping[str, Spent], linked: Collection[str]
) -> list[tuple[Spent, int]]:
    low = reserve.amount * (1 - LINK_TOLERANCE)
    high = reserve.amount * (1 + LINK_TOLERANCE)
    found = []
    for item in expenses:
        if item.category_id != reserve.category_id or not _usable(item, linked):
            continue
        due = near_due(reserve, item.month)
        if due is None or not _started(reserve, due) or _cycle(reserve, due, by_fp):
            continue
        if low <= (item.dop or _ZERO) <= high:
            found.append((item, abs(month_index(due) - month_index(item.month))))
    return found


def _multiple(
    reserve: Reserve,
    expenses: Sequence[Spent],
    by_fp: Mapping[str, Spent],
    linked: Collection[str],
    habitual: HabitualFor | None,
) -> list[tuple[Spent, int]]:
    if habitual is None:
        return []
    by_month: dict[str, list[Spent]] = defaultdict(list)
    for item in expenses:
        if item.category_id == reserve.category_id:
            by_month[item.month].append(item)
    found = []
    for month, items in sorted(by_month.items()):
        if not due_months(reserve, month, month) or not _started(reserve, month):
            continue
        usual = habitual(reserve.category_id, month)
        if usual is None:
            continue
        total = sum((i.dop for i in items if i.dop is not None), _ZERO)
        already = sum((c.dop for c in _cycle(reserve, month, by_fp) if c.dop is not None), _ZERO)
        room = min(total - usual, reserve.amount * (1 + LINK_TOLERANCE)) - already
        floor = reserve.amount * MULTIPLE_MIN_SHARE
        for item in sorted(items, key=lambda i: (-(i.dop or _ZERO), i.fingerprint)):
            if not _usable(item, linked) or item.recurring:
                continue
            amount = item.dop or _ZERO
            if floor <= amount <= room:
                found.append((item, 0))
                room -= amount
    return found
