"""Net worth: what the user has minus what they owe, in RD$, today and month by month.

A holding is one balance in one currency (a card's US$ side, a loan, the cash box's RD$...),
asset or debt, with a function giving its value on a day (None while it is unknown, e.g. before
an account's first statement). US$ convert at the rate of the day's month (or the nearest earlier
one, `rates.rate_for`); without a rate a value does not add up and `unconverted` says so.

- **History**: one point per month, at its last day (the current month at today), from the first
  month in which any holding with history is known. A holding not known yet on a point's day
  (an account whose statements start later) counts with its first known value, and the point is
  `estimated`; a holding with no known day that is still unknown leaves the month out, never zero.
  Holdings without history (`historic=False`, e.g. what others owe today) count in today's
  totals but in no point of the history, so the points compare with each other.
- **Month change**: the value today minus the value at the end of last month, both at today's
  rate, so the exchange rate does not move it.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from michelito.analysis.rates import Rate, rate_for, to_dop

Side = Literal["asset", "debt"]
ValueOn = Callable[[date], Decimal | None]
_ZERO = Decimal(0)


@dataclass(frozen=True)
class Holding:
    key: str
    group: str
    currency: str
    side: Side
    value_on: ValueOn = field(compare=False)
    historic: bool = True
    label: str = ""
    known_from: date | None = None  # the first day its value is known (None: from always)


@dataclass(frozen=True)
class Point:
    month: str
    day: date
    assets: Decimal
    debts: Decimal
    estimated: bool = False  # some holding counts with its first known value

    @property
    def net(self) -> Decimal:
        return self.assets - self.debts


@dataclass(frozen=True)
class Totals:
    assets: Decimal
    debts: Decimal
    groups: dict[str, Decimal]
    unconverted: bool

    @property
    def net(self) -> Decimal:
        return self.assets - self.debts


def _month(day: date) -> str:
    return day.strftime("%Y-%m")


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _previous_month_end(day: date) -> date:
    year, month = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
    return _month_end(year, month)


def value_dop(
    holding: Holding, day: date, rates: Mapping[str, Rate], rate_day: date | None = None
) -> Decimal | None:
    """The holding's value on `day` in RD$ (at `rate_day`'s month rate, by default `day`'s)."""
    value = holding.value_on(day)
    if value is None:
        return None
    return to_dop(value, holding.currency, rate_for(rates, _month(rate_day or day)))


def totals(holdings: Sequence[Holding], today: date, rates: Mapping[str, Rate]) -> Totals:
    """Today's assets, debts and total per group (unknown values do not add up)."""
    groups: dict[str, Decimal] = {}
    sides = {"asset": _ZERO, "debt": _ZERO}
    unconverted = False
    for holding in holdings:
        known = holding.value_on(today) is not None
        found = value_dop(holding, today, rates)
        if found is None:
            unconverted = unconverted or known
            continue
        groups[holding.group] = groups.get(holding.group, _ZERO) + found
        sides[holding.side] += found
    return Totals(sides["asset"], sides["debt"], groups, unconverted)


def _carried_back(
    holding: Holding, first: date, day: date, rates: Mapping[str, Rate]
) -> Decimal | None:
    """Its value on `first`, at `day`'s rate (or `first`'s, when `day`'s month has none)."""
    found = value_dop(holding, first, rates, rate_day=day)
    return found if found is not None else value_dop(holding, first, rates)


def _point(holdings: Sequence[Holding], day: date, rates: Mapping[str, Rate]) -> Point | None:
    sides = {"asset": _ZERO, "debt": _ZERO}
    estimated = False
    for holding in holdings:
        first = holding.known_from
        if first is not None and day < first:
            found = _carried_back(holding, first, day, rates)
            estimated = True
        else:
            found = value_dop(holding, day, rates)
        if found is None:
            return None
        sides[holding.side] += found
    return Point(_month(day), day, sides["asset"], sides["debt"], estimated)


def _month_ends(first: date, today: date) -> list[date]:
    days, year, month = [], first.year, first.month
    while (year, month) < (today.year, today.month):
        days.append(_month_end(year, month))
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    return [*days, today]


def history(
    holdings: Sequence[Holding], rates: Mapping[str, Rate], today: date, since: date | None = None
) -> list[Point]:
    """Month-end points from the first month any holding is known to today (see the module)."""
    if not holdings:
        return []
    with_history = [h for h in holdings if h.historic]
    known = [h.known_from for h in with_history if h.known_from is not None]
    first = since or (min(known) if known else date(today.year - 10, 1, 1))
    ends = _month_ends(first, today)
    # Today's point too leaves out the holdings without history, so every point is comparable.
    return [p for day in ends if (p := _point(with_history, day, rates))]


def month_change(holding: Holding, today: date, rates: Mapping[str, Rate]) -> Decimal | None:
    """Today's value minus last month's end, both at today's rate (see the module)."""
    now = value_dop(holding, today, rates)
    before = value_dop(holding, _previous_month_end(today), rates, rate_day=today)
    if now is None or before is None:
        return None
    return now - before
