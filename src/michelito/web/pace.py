"""The month's spending pace: cumulative spending per day against the previous month.

Feeds the Summary's "Month spending" card: the curve of this month (without one-off expenses)
against last month's, the comparison "up to today against last month up to the same day" and
the one-off expenses as dots on the curve. Same expenses and conversion as the Summary
(`web.summary`): calendar month by purchase date, everything in RD$, US$ without a rate left out.
"""

from __future__ import annotations

import calendar
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from michelito.analysis.accounts import AccountInfo
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.spending import Movement
from michelito.web.summary import selection

_ZERO = Decimal(0)


@dataclass(frozen=True)
class OneOff:
    """A one-off expense of the month: a dot on the curve that opens the transaction."""

    fingerprint: str
    day: date
    merchant: str
    amount: Decimal  # RD$


@dataclass(frozen=True)
class Pace:
    month: str
    previous_month: str
    # Days of `month` counted: up to today in the current month, all of them in a past month,
    # none in a future one.
    through_day: int
    days_in_month: int
    # Cumulative spending without one-off expenses, one value per day (day 1 first): this
    # month up to `through_day`, last month for all its days.
    current: list[Decimal]
    previous: list[Decimal]
    total_to_date: Decimal  # with one-off expenses and provisional ones, up to `through_day`
    # Last month without one-offs (and with them) up to the same day; once `month` is over, the
    # whole of last month (a finished month is compared month against month).
    previous_same_day: Decimal
    previous_same_day_total: Decimal
    one_offs: list[OneOff]
    finished: bool = False  # every day of `month` has happened


def previous_month(month: str) -> str:
    year, number = (int(part) for part in month.split("-"))
    return f"{year - 1:04d}-12" if number == 1 else f"{year:04d}-{number - 1:02d}"


def days_in(month: str) -> int:
    year, number = (int(part) for part in month.split("-"))
    return calendar.monthrange(year, number)[1]


def through_day(month: str, today: date) -> int:
    """How many days of `month` have happened by `today`."""
    current = f"{today.year:04d}-{today.month:02d}"
    if month < current:
        return days_in(month)
    return today.day if month == current else 0


def build_pace(
    movements: Iterable[Movement],
    accounts: Sequence[AccountInfo],
    rates: Mapping[str, Rate],
    month: str,
    today: date,
    selected: Collection[str] | None = None,
) -> Pace:
    """The pace of `month` up to `today` with the chosen accounts (None: all)."""
    chosen = selection(accounts, selected)
    before = previous_month(month)
    expenses = [
        m
        for m in movements
        if m.kind == "expense"
        and m.month in (month, before)
        and (chosen is None or m.account in chosen)
    ]
    converted = [(m, dop) for m, dop in _convert(expenses, rates)]
    now = [(m, dop) for m, dop in converted if m.month == month]
    then = [(m, dop) for m, dop in converted if m.month == before]
    counted = through_day(month, today)
    finished = counted == days_in(month)
    same_day = days_in(before) if finished else min(counted, days_in(before))
    previous = _cumulative(then, days_in(before), regular=True)
    one_offs = [
        OneOff(m.fingerprint, m.day, m.merchant, dop)
        for m, dop in sorted(now, key=lambda item: (item[0].day, item[0].fingerprint))
        if m.one_off and m.day.day <= counted
    ]
    return Pace(
        month=month,
        previous_month=before,
        through_day=counted,
        days_in_month=days_in(month),
        current=_cumulative(now, counted, regular=True),
        previous=previous,
        total_to_date=_up_to(now, counted),
        previous_same_day=previous[same_day - 1] if same_day else _ZERO,
        previous_same_day_total=_up_to(then, same_day),
        one_offs=one_offs,
        finished=finished,
    )


def _convert(
    movements: Iterable[Movement], rates: Mapping[str, Rate]
) -> list[tuple[Movement, Decimal]]:
    found = []
    for move in movements:
        dop = to_dop(move.amount, move.currency, rate_for(rates, move.month))
        if dop is not None:
            found.append((move, dop))
    return found


def _cumulative(
    items: Sequence[tuple[Movement, Decimal]], days: int, *, regular: bool
) -> list[Decimal]:
    per_day = [_ZERO] * days
    for move, dop in items:
        if regular and move.one_off:
            continue
        if move.day.day <= days:
            per_day[move.day.day - 1] += dop
    running, out = _ZERO, []
    for amount in per_day:
        running += amount
        out.append(running)
    return out


def _up_to(items: Sequence[tuple[Movement, Decimal]], day: int) -> Decimal:
    return sum((dop for move, dop in items if move.day.day <= day), _ZERO)
