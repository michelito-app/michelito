"""Detecting recurring charges (monthly and yearly series) from movements."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from michelito.analysis import categories as cat
from michelito.analysis.recurring import PriceChange, detect, group_of, series
from michelito.analysis.spending import Movement
from michelito.i18n import t
from tests.test_spending import movement


def charge(
    day: str,
    amount: str,
    category: str = cat.SUBSCRIPTIONS,
    merchant: str = "STREAMING INVENTADO",
    currency: str = "DOP",
) -> Movement:
    return replace(
        movement(day, amount, category, merchant, currency), fingerprint=f"{merchant}-{day}"
    )


def test_monthly_subscription_detected():
    movements = [charge(f"2026-0{m}-05", "9.99", currency="USD") for m in (1, 2, 3, 4)]
    [found] = detect(movements)
    assert found.cadence == "monthly"
    assert found.typical == Decimal("9.99")
    assert found.variable is False
    assert found.price_change is None
    assert found.currency == "USD"
    assert found.first_day.isoformat() == "2026-01-05"
    assert found.last_day.isoformat() == "2026-04-05"
    assert found.monthly == Decimal("9.99")
    assert len(found.charges) == 4


def test_yearly_fee_detected():
    movements = [
        charge("2025-03-10", "3500", cat.BANK_FEES, "MEMBRESIA INVENTADA"),
        charge("2026-03-10", "3500", cat.BANK_FEES, "MEMBRESIA INVENTADA"),
    ]
    [found] = detect(movements)
    assert found.cadence == "yearly"
    assert found.monthly == Decimal("3500") / 12


def test_two_charges_same_month_excludes_merchant():
    movements = [
        charge("2026-01-05", "500", cat.GROCERIES, "SUPER INVENTADO"),
        charge("2026-01-25", "500", cat.GROCERIES, "SUPER INVENTADO"),
        charge("2026-02-20", "500", cat.GROCERIES, "SUPER INVENTADO"),
        charge("2026-03-20", "500", cat.GROCERIES, "SUPER INVENTADO"),
    ]
    assert detect(movements) == []


def test_irregular_gaps_excluded():
    movements = [
        charge(day, "500", cat.RESTAURANTS, "A")
        for day in ("2026-01-01", "2026-02-20", "2026-04-30")
    ]
    assert detect(movements) == []


def test_irregular_amounts_excluded():
    movements = [
        charge(day, amount, cat.RESTAURANTS, "B")
        for day, amount in (("2026-01-05", "500"), ("2026-02-05", "900"), ("2026-03-05", "1400"))
    ]
    assert detect(movements) == []


def _spaced(gap: int, count: int) -> list[Movement]:
    day = date(2024, 1, 31)  # with 20 days, three charges land in different months
    out = []
    for _ in range(count):
        out.append(charge(day.isoformat(), "100"))
        day += timedelta(days=gap)
    return out


@pytest.mark.parametrize(("gap", "expected"), [(19, False), (20, True), (40, True), (41, False)])
def test_monthly_gap_boundaries(gap, expected):
    # 41 days means skipped months: two such gaps exceed the tolerance
    found = detect(_spaced(gap, 3))
    assert bool(found) is expected


@pytest.mark.parametrize(
    ("gap", "expected"), [(329, False), (330, True), (400, True), (401, False)]
)
def test_yearly_gap_boundaries(gap, expected):
    found = detect(_spaced(gap, 2))
    assert bool(found) is expected
    if expected:
        assert found[0].cadence == "yearly"


def test_below_monthly_minimum_excluded():
    assert detect(_spaced(30, 2)) == []


def test_one_skipped_month_tolerated():
    days = ("2026-01-05", "2026-02-05", "2026-04-05", "2026-05-05", "2026-06-05")
    [found] = detect([charge(d, "9.99") for d in days])
    assert found.cadence == "monthly"


def test_two_skipped_months_in_five_charges_excluded():
    days = ("2026-01-05", "2026-03-05", "2026-05-05", "2026-06-05", "2026-07-05")
    assert detect([charge(d, "9.99") for d in days]) == []


def test_jump_beyond_fifty_percent_waits_for_repeat():
    assert _run(["500", "500", "900"]) == []
    [found] = _run(["9.99", "9.99", "11.99"])
    assert found.typical == Decimal("11.99")


def test_single_first_charge_allowed():
    [found] = _run(["4.99", "9.99", "9.99", "9.99"])
    assert found.typical == Decimal("9.99")
    assert found.price_change == PriceChange(Decimal("4.99"), Decimal("9.99"), date(2026, 2, 5))


def test_small_jitter_is_not_a_price_change():
    [found] = _run(["100.00", "100.00", "100.50"])
    assert found.price_change is None


def test_category_is_most_common_ties_to_latest():
    movements = [
        charge("2026-01-05", "100", cat.SUBSCRIPTIONS),
        charge("2026-02-05", "100", cat.SUBSCRIPTIONS),
        charge("2026-03-05", "100", cat.ENTERTAINMENT),
    ]
    assert detect(movements)[0].category == cat.SUBSCRIPTIONS
    tie = [
        charge("2026-01-05", "100", cat.SUBSCRIPTIONS),
        charge("2026-02-05", "100", cat.ENTERTAINMENT),
        charge("2026-03-05", "100", cat.SUBSCRIPTIONS),
        charge("2026-04-05", "100", cat.ENTERTAINMENT),
    ]
    assert detect(tie)[0].category == cat.ENTERTAINMENT


def test_utilities_variable_amount():
    movements = [
        charge(day, amount, cat.UTILITIES, "LUZ INVENTADA")
        for day, amount in (("2026-01-05", "2000"), ("2026-02-05", "2600"), ("2026-03-05", "1800"))
    ]
    [found] = detect(movements)
    assert found.variable is True
    assert found.price_change is None
    assert found.typical == Decimal("2133.33")  # average of the last 3


def test_utilities_are_always_variable():
    movements = [
        charge(day, "2000", cat.UTILITIES, "LUZ INVENTADA")
        for day in ("2026-01-05", "2026-02-05", "2026-03-05")
    ]
    [found] = detect(movements)
    assert found.variable is True
    assert found.typical == Decimal("2000.00")


def test_price_increase_in_original_currency():
    movements = [
        charge(day, amount, currency="USD")
        for day, amount in (("2026-01-05", "9.99"), ("2026-02-05", "9.99"), ("2026-03-05", "11.99"))
    ]
    [found] = detect(movements)
    assert found.price_change == PriceChange(Decimal("9.99"), Decimal("11.99"), movements[2].day)
    assert found.typical == Decimal("11.99")


def test_refunds_ignored():
    movements = [
        charge("2026-01-05", "9.99"),
        charge("2026-02-05", "9.99"),
        charge("2026-02-10", "-9.99"),
        charge("2026-03-05", "9.99"),
    ]
    [found] = detect(movements)
    assert len(found.charges) == 3


def test_currencies_are_separate_series():
    movements = [charge(f"2026-0{m}-05", "9.99", currency="USD") for m in (1, 2)] + [
        charge("2026-03-05", "9.99", currency="DOP")
    ]
    assert detect(movements) == []


def test_series_returns_positive_charges_sorted():
    movements = [
        charge("2026-03-05", "9.99"),
        charge("2026-01-05", "9.99"),
        charge("2026-02-05", "-9.99"),
        charge("2026-02-05", "9.99", merchant="OTHER"),
    ]
    result = series(movements, "STREAMING INVENTADO", "DOP")
    assert [c.day.isoformat() for c in result] == ["2026-01-05", "2026-03-05"]
    assert result[0].fingerprint == "STREAMING INVENTADO-2026-01-05"


def test_detect_sorted_by_merchant():
    movements = [
        charge(f"2026-0{m}-05", "100", merchant=name)
        for name in ("ZETA", "ALFA")
        for m in (1, 2, 3)
    ]
    assert [r.merchant for r in detect(movements)] == ["ALFA", "ZETA"]


def test_group_of():
    assert group_of(cat.SUBSCRIPTIONS) == t("analysis.recurring.group.subscriptions")
    assert group_of(cat.UTILITIES) == t("analysis.recurring.group.utilities")
    assert group_of(cat.INSURANCE) == t("analysis.recurring.group.insurance")
    assert group_of(cat.BANK_FEES) == t("analysis.recurring.group.fees")
    assert group_of(cat.RESTAURANTS) == t("analysis.recurring.group.other")


def _run(amounts: list[str], category: str = cat.SUBSCRIPTIONS):
    movements = [charge(f"2026-{i + 1:02d}-05", a, category) for i, a in enumerate(amounts)]
    return detect(movements)


def test_two_price_rises_detected():
    [found] = _run(["9.99"] * 3 + ["10.99"] * 3 + ["12.99"])
    assert found.typical == Decimal("12.99")
    assert found.variable is False
    assert found.price_change == PriceChange(Decimal("10.99"), Decimal("12.99"), found.last_day)


def test_random_amounts_still_excluded():
    assert _run(["500", "900", "1400", "700"], cat.RESTAURANTS) == []


def test_single_outlier_in_the_middle_excluded():
    assert _run(["9.99", "9.99", "15.00", "9.99"]) == []


def test_big_rise_that_repeats_is_reported():
    [found] = _run(["4.99"] * 3 + ["15.99"] * 2)
    assert found.typical == Decimal("15.99")
    assert found.price_change == PriceChange(Decimal("4.99"), Decimal("15.99"), date(2026, 4, 5))


def test_price_change_with_repeated_new_price_points_at_first_new_charge():
    [found] = _run(["9.99"] * 3 + ["10.99"] * 3)
    assert found.price_change == PriceChange(Decimal("9.99"), Decimal("10.99"), date(2026, 4, 5))


@pytest.mark.parametrize(("gap", "expected"), [(80, True), (81, False)])
def test_skipped_month_gap_boundaries(gap, expected):
    days = [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5), date(2026, 4, 5)]
    days.append(days[-1] + timedelta(days=gap))
    assert bool(detect([charge(d.isoformat(), "100") for d in days])) is expected


def test_old_one_off_does_not_hide_current_subscription():
    movements = [charge("2024-03-10", "100")] + [
        charge(f"2026-0{m}-05", "100") for m in (1, 2, 3, 4)
    ]
    [found] = detect(movements)
    assert found.cadence == "monthly"
    assert found.first_day == date(2026, 1, 5)
    assert len(found.charges) == 4


def test_old_same_month_duplicate_does_not_hide_resumed_run():
    movements = [charge("2024-03-10", "100"), charge("2024-03-25", "100")] + [
        charge(f"2026-0{m}-05", "100") for m in (1, 2, 3)
    ]
    [found] = detect(movements)
    assert len(found.charges) == 3


def test_paused_and_resumed_subscription_detected_from_last_run():
    days = ("2025-01-05", "2025-02-05", "2025-03-05", "2025-09-05", "2025-10-05", "2025-11-05")
    [found] = detect([charge(d, "9.99") for d in days])
    assert found.first_day == date(2025, 9, 5)
    assert len(found.charges) == 3


def test_short_run_after_pause_is_not_detected():
    days = ("2025-01-05", "2025-02-05", "2025-03-05", "2025-09-05", "2025-10-05")
    assert detect([charge(d, "9.99") for d in days]) == []


def test_bank_loan_payment_with_changing_reference_is_one_series():
    # The payment reference changes every month; the bank key keeps the account.
    from michelito import db
    from michelito.analysis import spending
    from tests.test_spending import _add_bank_rows, seed

    conn = db.connect(":memory:")
    seed(conn)
    _add_bank_rows(
        conn,
        [
            (f"2025-{month}-25", f"AUT PAGO 1234567890 123-4567{month[-1]}", "debit", "200000")
            for month in ("09", "10", "11", "12")
        ],
    )
    found = [r for r in detect(spending.load_all(conn)) if r.merchant.startswith("AUT PAGO")]
    assert [(r.merchant, r.cadence, len(r.charges)) for r in found] == [
        ("AUT PAGO 1234567890", "monthly", 4)
    ]
    conn.close()
