"""Scheduled cash payments and collections (pure functions; storage in `cash_schedule_store`).

A schedule is a kind (`payment`: money that leaves the cash; `collection`: money that comes in),
a concept, an amount, a currency, a category, a frequency, a start date and an optional end (a
last date or a number of occurrences), and whether it is paused. Its due dates (`due_dates`):

- `weekly`: the start date and every 7 days after it (the start's weekday).
- `biweekly`: the start date and every 14 days after it.
- `semimonthly` ("quincenal", twice a month): the 15th and the last day of every month.
- `monthly`: the start's day of the month every month; in a month without that day (the 31st
  in April, the 30th in February), the month's last day.

`max_count` counts due dates from the start (a skipped occurrence still uses its turn); `end_day`
is the last day a date may fall on. Dates are local dates: the caller passes its `today`.

On each due date up to today an occurrence is *materialized* as a pending cash entry
(`cash_schedule_store.materialize`): once per schedule and date (a unique index), never on a
date the user said did not happen (`cash_skips`), never while the schedule is paused and, after
resuming, only from the resume date on (`resume_day`). Changing the amount changes the
occurrences still to come; those already materialized keep theirs. Deleting a schedule keeps its
past occurrences.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, get_args

from michelito.analysis.accounts import CASH_BOX_KEY
from michelito.analysis.cash_box import FIRST_DAY, CashBoxError, EntryKind
from michelito.i18n import t

ScheduleKind = Literal["payment", "collection"]
SCHEDULE_KINDS: tuple[ScheduleKind, ...] = get_args(ScheduleKind)
Frequency = Literal["weekly", "biweekly", "semimonthly", "monthly"]
FREQUENCIES: tuple[Frequency, ...] = get_args(Frequency)
MAX_COUNT = 1000
# How far ahead "next due" looks (the Summary's "Next: …").
UPCOMING_DAYS = 7
# The last start or end date accepted: ten years from today.
_YEARS_AHEAD = 10
_SEMIMONTHLY_DAY = 15


@dataclass(frozen=True)
class Schedule:
    id: int
    kind: ScheduleKind
    concept: str
    amount: Decimal
    currency: str
    category_id: int | None
    frequency: Frequency
    start: date
    end: date | None = None
    max_count: int | None = None
    paused: bool = False
    resume_day: date | None = None
    account_key: str = CASH_BOX_KEY

    @property
    def entry_kind(self) -> EntryKind:
        return "expense" if self.kind == "payment" else "income"


def entry_kind(kind: ScheduleKind) -> EntryKind:
    return "expense" if kind == "payment" else "income"


def _month_day(year: int, month: int, day: int) -> date:
    """`day` in that month, or its last day when the month is shorter."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _raw_dates(frequency: Frequency, start: date) -> Iterator[date]:
    """Every due date from `start` on, without end (in order)."""
    if frequency in ("weekly", "biweekly"):
        step = timedelta(days=7 if frequency == "weekly" else 14)
        day = start
        while True:
            yield day
            day += step
    year, month = start.year, start.month
    while True:
        last = calendar.monthrange(year, month)[1]
        days = (
            (date(year, month, _SEMIMONTHLY_DAY), date(year, month, last))
            if frequency == "semimonthly"
            else (_month_day(year, month, start.day),)
        )
        for day in days:
            if day >= start:
                yield day
        year, month = _next_month(year, month)


def due_dates(schedule: Schedule, until: date) -> Iterator[date]:
    """The schedule's due dates up to `until` (inclusive), honoring its end and its count; the
    pause and the resume date are not applied here (see `materializable`)."""
    for index, day in enumerate(_raw_dates(schedule.frequency, schedule.start)):
        if day > until:
            return
        if schedule.max_count is not None and index >= schedule.max_count:
            return
        if schedule.end is not None and day > schedule.end:
            return
        yield day


def materializable(schedule: Schedule, today: date) -> Iterator[date]:
    """The dates that should have an occurrence by `today`: none while paused; after a resume,
    only from the resume date."""
    if schedule.paused:
        return
    for day in due_dates(schedule, today):
        if schedule.resume_day is None or day >= schedule.resume_day:
            yield day


def next_due(schedule: Schedule, after: date) -> date | None:
    """The first due date after `after` (None when paused or finished)."""
    if schedule.paused:
        return None
    # From the later of `after` and the start (which may be years ahead): a year and a month
    # holds the next date of every frequency.
    limit = max(after, schedule.start) + timedelta(days=400)
    return next((day for day in due_dates(schedule, limit) if day > after), None)


def finished(schedule: Schedule, today: date) -> bool:
    """No due date left after `today` (paused or not)."""
    return next_due(replace(schedule, paused=False), today) is None


def check(
    kind: str,
    frequency: str,
    start: date,
    end: date | None,
    max_count: int | None,
    today: date,
) -> None:
    """A schedule's shape: a known kind and frequency, a start from FIRST_DAY to ten years ahead,
    an end not before the start (or a count from 1 to MAX_COUNT), not both."""
    if kind not in SCHEDULE_KINDS:
        raise CashBoxError(t("analysis.cash_schedule.unknown_kind", kind=kind))
    if frequency not in FREQUENCIES:
        raise CashBoxError(t("analysis.cash_schedule.unknown_frequency", frequency=frequency))
    last = date(today.year + _YEARS_AHEAD, 12, 31)
    if not FIRST_DAY <= start <= last:
        raise CashBoxError(
            t("analysis.cash_schedule.start_range", first=FIRST_DAY.isoformat(), last=last)
        )
    if end is not None and max_count is not None:
        raise CashBoxError(t("analysis.cash_schedule.end_or_count"))
    if end is not None and not start <= end <= last:
        raise CashBoxError(t("analysis.cash_schedule.end_range"))
    if max_count is not None and not 1 <= max_count <= MAX_COUNT:
        raise CashBoxError(t("analysis.cash_schedule.count_range", max=MAX_COUNT))
