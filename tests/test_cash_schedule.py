"""Due dates of scheduled cash payments and collections (`analysis.cash_schedule`), pure."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from michelito.analysis import cash_schedule
from michelito.analysis.cash_box import CashBoxError
from michelito.analysis.cash_schedule import Schedule, due_dates, materializable, next_due


def _schedule(frequency: str, start: date, **extra) -> Schedule:
    return Schedule(
        id=1,
        kind="payment",
        concept="Cleaning",
        amount=Decimal("3000"),
        currency="DOP",
        category_id=None,
        frequency=frequency,  # type: ignore[arg-type]
        start=start,
        **extra,
    )


def _dates(frequency: str, start: date, until: date, **extra) -> list[date]:
    return list(due_dates(_schedule(frequency, start, **extra), until))


def test_weekly_keeps_the_start_weekday() -> None:
    found = _dates("weekly", date(2026, 11, 6), date(2026, 11, 30))
    assert found == [date(2026, 11, 6), date(2026, 11, 13), date(2026, 11, 20), date(2026, 11, 27)]
    assert {day.weekday() for day in found} == {4}  # Fridays


def test_every_two_weeks_from_a_date_crosses_the_year() -> None:
    found = _dates("biweekly", date(2026, 12, 18), date(2027, 1, 31))
    assert found == [date(2026, 12, 18), date(2027, 1, 1), date(2027, 1, 15), date(2027, 1, 29)]


def test_quincenal_is_the_15th_and_the_last_day() -> None:
    found = _dates("semimonthly", date(2026, 1, 20), date(2026, 4, 30))
    assert found == [
        date(2026, 1, 31),
        date(2026, 2, 15),
        date(2026, 2, 28),
        date(2026, 3, 15),
        date(2026, 3, 31),
        date(2026, 4, 15),
        date(2026, 4, 30),
    ]


def test_quincenal_in_a_leap_february() -> None:
    found = _dates("semimonthly", date(2028, 2, 1), date(2028, 3, 1))
    assert found == [date(2028, 2, 15), date(2028, 2, 29)]


def test_monthly_on_the_31st_takes_the_last_day_of_shorter_months() -> None:
    found = _dates("monthly", date(2026, 1, 31), date(2026, 5, 31))
    assert found == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
    ]


def test_monthly_on_the_29th_in_leap_and_common_years() -> None:
    assert _dates("monthly", date(2027, 12, 29), date(2028, 3, 1)) == [
        date(2027, 12, 29),
        date(2028, 1, 29),
        date(2028, 2, 29),
    ]
    assert _dates("monthly", date(2026, 12, 29), date(2027, 3, 1)) == [
        date(2026, 12, 29),
        date(2027, 1, 29),
        date(2027, 2, 28),
    ]


def test_monthly_on_the_30th_does_not_drift_after_february() -> None:
    found = _dates("monthly", date(2026, 1, 30), date(2026, 4, 30))
    assert found == [date(2026, 1, 30), date(2026, 2, 28), date(2026, 3, 30), date(2026, 4, 30)]


def test_an_end_date_and_a_count_stop_the_dates() -> None:
    assert _dates("weekly", date(2026, 11, 6), date(2027, 1, 1), end=date(2026, 11, 20)) == [
        date(2026, 11, 6),
        date(2026, 11, 13),
        date(2026, 11, 20),
    ]
    assert _dates("monthly", date(2026, 1, 15), date(2027, 1, 1), max_count=2) == [
        date(2026, 1, 15),
        date(2026, 2, 15),
    ]


def test_paused_has_nothing_and_a_resume_skips_the_missed_dates() -> None:
    start = date(2026, 11, 6)
    assert list(materializable(_schedule("weekly", start, paused=True), date(2026, 11, 30))) == []
    resumed = _schedule("weekly", start, resume_day=date(2026, 11, 21))
    assert list(materializable(resumed, date(2026, 11, 30))) == [date(2026, 11, 27)]


def test_next_due_and_finished() -> None:
    weekly = _schedule("weekly", date(2026, 11, 6))
    assert next_due(weekly, date(2026, 11, 21)) == date(2026, 11, 27)
    assert next_due(_schedule("weekly", date(2026, 11, 6), paused=True), date(2026, 11, 21)) is None
    done = _schedule("weekly", date(2026, 11, 6), max_count=2)
    assert next_due(done, date(2026, 11, 21)) is None
    assert cash_schedule.finished(done, date(2026, 11, 21))
    assert not cash_schedule.finished(weekly, date(2026, 11, 21))


@pytest.mark.parametrize(
    ("kind", "frequency", "start", "end", "count"),
    [
        ("gift", "weekly", date(2026, 1, 1), None, None),
        ("payment", "daily", date(2026, 1, 1), None, None),
        ("payment", "weekly", date(1999, 12, 31), None, None),
        ("payment", "weekly", date(2026, 1, 1), date(2025, 12, 31), None),
        ("payment", "weekly", date(2026, 1, 1), date(2026, 2, 1), 3),
        ("payment", "weekly", date(2026, 1, 1), None, 0),
    ],
)
def test_check_rejects_bad_shapes(kind, frequency, start, end, count) -> None:
    with pytest.raises(CashBoxError):
        cash_schedule.check(kind, frequency, start, end, count, date(2026, 11, 21))
