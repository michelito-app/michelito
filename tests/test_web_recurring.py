from __future__ import annotations

from datetime import date
from decimal import Decimal

from michelito.analysis import categories as cat
from michelito.analysis.rates import Rate
from michelito.analysis.recurring import GROUPS
from michelito.analysis.recurring_marks import Mark
from michelito.i18n import t
from michelito.web.recurring import build_overview
from tests.test_recurring import charge

RATE = {"2026-04": Rate(Decimal("60.0000"), "2026-04", "manual")}


def monthly(merchant, amount, months, category=cat.SUBSCRIPTIONS, currency="DOP", day="05"):
    return [charge(f"2026-{m:02d}-{day}", amount, category, merchant, currency) for m in months]


def mark(status=None, left=None, status_on=None, installments_on=None):
    return Mark(
        status,
        left,
        date.fromisoformat(status_on) if status_on else None,
        date.fromisoformat(installments_on) if installments_on else None,
    )


def test_groups_and_totals_only_active():
    movements = (
        monthly("STREAMING INVENTADO", "9.99", [2, 3, 4, 5], currency="USD")
        + monthly("LUZ INVENTADA", "1000", [2, 3, 4, 5], cat.UTILITIES)
        + monthly("OLD MADE-UP", "300", [1, 2, 3])  # last charge in March: inactive
        + [charge("2026-05-20", "1", cat.GROCERIES, "ANOTHER")]
    )
    rates = {"2026-05": Rate(Decimal("60"), "2026-05", "manual")}
    view = build_overview(movements, {}, rates, None)
    assert view.as_of == date(2026, 5, 20)
    groups = {g.group: g for g in view.groups}
    assert groups[GROUPS["utilities"]].monthly_dop == Decimal("1000")
    assert groups[GROUPS["utilities"]].yearly_dop == Decimal("12000")
    assert groups[GROUPS["subscriptions"]].count == 1  # the old one is inactive and does not add up
    assert groups[GROUPS["subscriptions"]].monthly_dop == Decimal(
        "599"
    )  # 599.4 rounded to a whole amount
    assert groups[GROUPS["subscriptions"]].yearly_dop == Decimal("7188")
    assert view.monthly_dop == Decimal("1000") + Decimal("599")
    assert [g.group for g in view.groups] == [GROUPS["utilities"], GROUPS["subscriptions"]]
    # by group, and within a group by monthly cost, descending
    assert [i.merchant for i in view.items] == [
        "LUZ INVENTADA",
        "STREAMING INVENTADO",
        "OLD MADE-UP",
    ]
    assert {i.merchant: i.status for i in view.items}["OLD MADE-UP"] == "inactive"


def test_dismissed_moves_out_of_items():
    movements = monthly("STREAMING INVENTADO", "500", [1, 2, 3, 4])
    marks = {("STREAMING INVENTADO", "DOP"): mark("dismissed", status_on="2026-04-10")}
    view = build_overview(movements, marks, {}, None)
    assert view.items == []
    assert [d.merchant for d in view.dismissed] == ["STREAMING INVENTADO"]
    assert view.monthly_dop == 0


def test_confirmed_kept_when_rule_no_longer_detects():
    movements = [
        charge("2026-02-05", "300", cat.SUBSCRIPTIONS, "ODD MADE-UP"),
        charge("2026-04-03", "320", cat.SUBSCRIPTIONS, "ODD MADE-UP"),
        charge("2026-04-04", "1", cat.GROCERIES, "FILLER"),
    ]
    marks = {("ODD MADE-UP", "DOP"): mark("confirmed", status_on="2026-04-10")}
    view = build_overview(movements, marks, {}, None)
    [item] = view.items
    assert item.merchant == "ODD MADE-UP"
    assert item.cadence == "monthly"
    assert item.typical == Decimal("310")
    assert item.charges == 2
    assert item.price_change is None and item.variable is False
    assert item.mark == "confirmed"


def test_marked_without_any_charge_is_skipped():
    movements = monthly("STREAMING INVENTADO", "500", [1, 2, 3])
    marks = {("GHOST", "DOP"): mark("confirmed", status_on="2026-04-10")}
    assert [i.merchant for i in build_overview(movements, marks, {}, None).items] == [
        "STREAMING INVENTADO"
    ]


def test_cancelled_then_charged_alerts():
    movements = monthly("GYM INVENTADO", "1200", [1, 2, 3, 4], cat.OTHER)
    marks = {("GYM INVENTADO", "DOP"): mark("cancelled", status_on="2026-03-20")}
    view = build_overview(movements, marks, {}, "2026-04")
    [item] = view.items
    assert item.status == "cancelled"
    assert item.charged_after_cancel is True
    assert view.groups == []  # cancelled does not add up
    assert [(a.kind, a.detail) for a in view.alerts] == [
        ("charged_after_cancel", t("web.recurring.alert_charged_after_cancel", amount="RD$ 1,200"))
    ]
    assert build_overview(movements, marks, {}, "2026-03").alerts == []


def test_installments_count_down_to_ended():
    movements = monthly("TIENDA INVENTADA", "2000", [1, 2, 3, 4, 5], cat.SHOPPING)
    marks = {("TIENDA INVENTADA", "DOP"): mark(left=3, installments_on="2026-02-10")}
    [item] = build_overview(movements, marks, {}, None).items
    assert item.group == t("web.recurring.installments_group")
    assert item.installments_left == 0  # 3 noted, 3 later charges
    assert item.status == "ended"
    # never negative even when more charges than installments arrive
    marks = {("TIENDA INVENTADA", "DOP"): mark(left=1, installments_on="2026-01-10")}
    [item] = build_overview(movements, marks, {}, None).items
    assert item.installments_left == 0
    marks = {("TIENDA INVENTADA", "DOP"): mark(left=6, installments_on="2026-03-10")}
    [item] = build_overview(movements, marks, {}, None).items
    assert (item.installments_left, item.status) == (4, "active")


def test_inactive_after_one_and_half_periods():
    base = monthly("STREAMING INVENTADO", "500", [1, 2, 3])  # last one: 2026-03-05
    for last, expected in (("2026-04-19", "active"), ("2026-04-20", "inactive")):
        movements = [*base, charge(last, "1", cat.GROCERIES, "FILLER")]
        [item] = build_overview(movements, {}, {}, None).items
        assert item.status == expected  # exactly 45 days is still active


def test_usd_without_rate_has_no_cost_and_not_summed():
    movements = monthly("STREAMING INVENTADO", "9.99", [1, 2, 3, 4], currency="USD")
    movements += monthly("LUZ INVENTADA", "100", [1, 2, 3, 4], cat.UTILITIES)
    view = build_overview(movements, {}, {}, None)
    usd = next(i for i in view.items if i.currency == "USD")
    assert usd.monthly_dop is None and usd.yearly_dop is None
    assert view.monthly_dop == Decimal("100")  # the US$ one does not add up
    assert [g.group for g in view.groups] == [GROUPS["utilities"], GROUPS["subscriptions"]]
    assert view.groups[1].monthly_dop == 0


def test_month_alerts_new_and_price_increase():
    movements = (
        monthly("STREAMING INVENTADO", "9.99", [1, 2, 3], currency="USD")
        + [charge("2026-04-05", "11.99", cat.SUBSCRIPTIONS, "STREAMING INVENTADO", "USD")]
        + monthly("NEW MADE-UP", "450", [2, 3, 4])
    )  # the first transaction is from January
    view = build_overview(movements, {}, RATE, "2026-04")
    texts = {(a.kind, a.merchant): a.detail for a in view.alerts}
    assert texts == {
        ("price_up", "STREAMING INVENTADO"): t(
            "web.recurring.alert_price_up", before="US$ 9.99", after="US$ 11.99"
        ),
    }
    view = build_overview(movements, {}, RATE, "2026-02")
    assert [(a.kind, a.merchant, a.detail) for a in view.alerts] == [
        ("new", "NEW MADE-UP", t("web.recurring.alert_new", cost="RD$ 450"))
    ]
    assert build_overview(movements, {}, RATE, None).alerts == []


def test_new_usd_without_rate_uses_original_currency():
    movements = monthly("STREAMING INVENTADO", "9.99", [2, 3, 4], currency="USD")
    movements += monthly("FILLER", "1", [1], cat.GROCERIES)
    [alert] = build_overview(movements, {}, {}, "2026-02").alerts
    assert alert.detail == t("web.recurring.alert_new", cost="US$ 9.99")


def test_empty_movements_give_empty_overview():
    view = build_overview([], {}, {}, "2026-04")
    assert view.as_of is None
    assert view.items == [] and view.groups == [] and view.dismissed == []
    assert view.monthly_dop == 0 and view.alerts == []


def test_usd_cost_rounded_once_so_yearly_is_twelve_times_monthly():
    movements = monthly("STREAMING INVENTADO", "11.99", [2, 3, 4], currency="USD")
    rates = {"2026-04": Rate(Decimal("63.70"), "2026-04", "manual")}
    view = build_overview(movements, {}, rates, None)
    [item] = view.items
    assert (item.monthly_dop, item.yearly_dop) == (Decimal("764"), Decimal("9168"))
    assert item.yearly_dop == item.monthly_dop * 12
    assert view.groups[0].yearly_dop == Decimal("9168")
    assert view.monthly_dop == Decimal("764")


def test_annual_cost_yearly_equals_typical_exactly():
    movements = [
        charge("2025-03-10", "3500", cat.BANK_FEES, "MEMBERSHIP MADE-UP"),
        charge("2026-03-10", "3500", cat.BANK_FEES, "MEMBERSHIP MADE-UP"),
    ]
    view = build_overview(movements, {}, {}, None)
    [item] = view.items
    assert (item.yearly_dop, item.monthly_dop) == (Decimal("3500"), Decimal("292"))
    assert view.groups[0].yearly_dop == Decimal("3500")
    assert view.groups[0].monthly_dop == Decimal("292")


def test_confirmed_yearly_fallback_stays_annual():
    movements = [
        charge("2024-03-10", "3500", cat.BANK_FEES, "MEMBERSHIP MADE-UP"),
        charge("2025-03-10", "3500", cat.BANK_FEES, "MEMBERSHIP MADE-UP"),
        charge("2026-03-10", "6000", cat.BANK_FEES, "MEMBERSHIP MADE-UP"),
    ]
    marks = {("MEMBERSHIP MADE-UP", "DOP"): mark("confirmed", status_on="2026-03-12")}
    [item] = build_overview(movements, marks, {}, None).items
    assert item.cadence == "yearly"
    assert item.yearly_dop == Decimal("6000")
    assert item.monthly_dop == Decimal("500")
    assert item.status == "active"


def test_big_price_rise_alerts_in_the_month_of_the_change():
    movements = monthly("STREAMING INVENTADO", "4.99", [1, 2, 3]) + monthly(
        "STREAMING INVENTADO", "15.99", [4, 5]
    )
    kinds = lambda month: [  # noqa: E731
        (a.kind, a.detail) for a in build_overview(movements, {}, {}, month).alerts
    ]
    assert kinds("2026-04") == [
        ("price_up", t("web.recurring.alert_price_up", before="RD$ 5", after="RD$ 16"))
    ]
    assert kinds("2026-05") == []


def test_no_new_alert_in_first_month_of_data():
    movements = monthly("STREAMING INVENTADO", "500", [1, 2, 3])
    view = build_overview(movements, {}, {}, "2026-01")
    assert view.first_month == "2026-01"
    assert view.alerts == []


def test_cancelled_item_gets_no_new_or_price_alert():
    movements = monthly("STREAMING INVENTADO", "9.99", [1, 2, 3]) + monthly(
        "STREAMING INVENTADO", "11.99", [4]
    )
    marks = {("STREAMING INVENTADO", "DOP"): mark("cancelled", status_on="2026-03-20")}
    view = build_overview(movements, marks, {}, "2026-04")
    assert [a.kind for a in view.alerts] == ["charged_after_cancel"]
