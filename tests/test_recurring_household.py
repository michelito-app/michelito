"""Household recurring charges (pure logic): providers with several names summed by month,
electricity that varies a lot, recharges left out, a sustained price rise, loans with extra
payments, the Housing and Loans groups by reference, unions and marks per series. Providers and
amounts are made up."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import get_args

import pytest

from michelito.analysis import categories as cat
from michelito.analysis import providers
from michelito.analysis import recurring as rec
from michelito.analysis.recurring_marks import Mark, for_series, merge
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web.recurring import GROUP_ORDER, build_overview
from michelito.web.recurring_schemas import GroupKey
from tests.test_recurring import charge

D = Decimal
TEL = "provider:telfic"
FAKES = (
    providers.make_provider("telfic", "Fictional Phone Co", r"TELFIC|TELEFONICA FICTICIA"),
    providers.make_provider("luzfic", "Fictional Power", r"LUZFIC"),
)


@pytest.fixture(autouse=True)
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Made-up providers instead of the real list (test data never uses real names)."""
    monkeypatch.setattr(providers, "PROVIDERS", FAKES)


def bill(day: str, amount: str, merchant: str, category: str = cat.UTILITIES) -> Movement:
    return charge(day, amount, category, merchant)


def phone_bills() -> list[Movement]:
    """Four names of the same provider; nothing in March, double in April, two payments in May."""
    return [
        bill("2026-01-10", "1000", "TELFIC PAGO"),
        bill("2026-02-11", "1000", "TELFIC IBANKING"),
        bill("2026-04-09", "2000", "TELFIC WB"),
        bill("2026-05-08", "600", "TELFIC P"),
        bill("2026-05-20", "400", "TELFIC PAGO"),
        bill("2026-06-10", "1000", "TELFIC PAGO"),
    ]


def test_provider_with_four_names_is_one_monthly_series_summed_by_month() -> None:
    [found] = rec.detect(phone_bills())
    assert found.merchant == TEL
    assert found.name == "Fictional Phone Co"
    assert found.members == ("TELFIC IBANKING", "TELFIC P", "TELFIC PAGO", "TELFIC WB")
    assert found.cadence == "monthly"
    assert [c.amount for c in found.charges] == [D(1000), D(1000), D(2000), D(1000), D(1000)]
    assert found.charges[3].day == date(2026, 5, 20)  # the sum carries the day of the last payment
    assert found.variable is True
    assert found.typical == D("1000.00")  # April's double covers March
    assert found.price_change is None


def test_provider_only_inside_utilities() -> None:
    other = [bill(f"2026-0{m}-05", "300", "TELFIC TIENDA", cat.HOME) for m in (1, 2, 3)]
    found = {r.merchant for r in rec.detect([*phone_bills(), *other])}
    assert found == {TEL, "TELFIC TIENDA"}


def test_electricity_varying_sixty_percent_is_detected() -> None:
    amounts = ("1000", "1600", "400", "1600", "400")
    movements = [bill(f"2026-0{i + 1}-15", a, "LUZFIC PAGO") for i, a in enumerate(amounts)]
    [found] = rec.detect(movements)
    assert found.merchant == "provider:luzfic"
    assert found.variable is True
    assert found.typical == D("800.00")


def test_too_many_empty_months_is_not_monthly() -> None:
    days = ("2026-01-10", "2026-03-10", "2026-05-10", "2026-07-10")
    assert rec.detect([bill(d, "1000", "TELFIC PAGO") for d in days]) == []


def test_recharges_are_not_in_the_bill_nor_recurring() -> None:
    recharges = [
        replace(bill(f"2026-0{m}-03", "200", "TELFIC RECARGA"), description="TELFIC RECARGA 809")
        for m in range(1, 7)
    ]
    recharges.append(
        replace(bill("2026-06-04", "300", "RECAR TELFIC"), description="RECAR TELFIC PREPAGO")
    )
    found = rec.detect([*phone_bills(), *recharges])
    assert [r.merchant for r in found] == [TEL]
    assert sum(c.amount for c in found[0].charges) == D(6000)
    assert all(rec.series_key(m) is None for m in recharges)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("RECARGA PREPAGO", True),
        ("RECARGAS TELFIC", True),
        ("RECAR TELFIC", True),
        ("TOPUP TELFIC", True),
        ("TOP UP TELFIC", True),
        ("RECARGO POR MORA", False),
        ("TELFIC PAGO", False),
    ],
)
def test_recharge_regex(text: str, expected: bool) -> None:
    assert providers.is_recharge(text) is expected


def test_sustained_rise_reports_price_up() -> None:
    amounts = ["1000"] * 3 + ["1300"] * 3
    movements = [bill(f"2026-0{i + 1}-10", a, "LUZFIC PAGO") for i, a in enumerate(amounts)]
    [found] = rec.detect(movements)
    assert found.price_change == rec.PriceChange(D("1000.00"), D("1300.00"), date(2026, 6, 10))


@pytest.mark.parametrize(
    "amounts",
    [
        ["1000"] * 5 + ["1900"],  # a single expensive month at the end
        ["1000"] * 4 + ["1900", "1000"],  # a single expensive month among the last three
        ["1000"] * 3 + ["1200"] * 3,  # +20 %: below the threshold
    ],
)
def test_utility_spike_or_small_rise_is_not_price_up(amounts: list[str]) -> None:
    movements = [bill(f"2026-0{i + 1}-10", a, "LUZFIC PAGO") for i, a in enumerate(amounts)]
    [found] = rec.detect(movements)
    assert found.price_change is None


def test_double_payment_after_empty_month_is_not_a_rise() -> None:
    # 1000, 1000, 1000, (nothing), 2000, 1000: spread out it is 1000 every month.
    days = ("2026-01-10", "2026-02-10", "2026-03-10", "2026-05-10", "2026-06-10")
    amounts = ("1000", "1000", "1000", "2000", "1000")
    [found] = rec.detect([bill(d, a, "LUZFIC PAGO") for d, a in zip(days, amounts, strict=True)])
    assert found.price_change is None
    assert found.typical == D("1000.00")


def loan_payments() -> list[Movement]:
    months = [f"2026-0{m}-25" for m in range(1, 7)]
    payments = [charge(day, "15000", cat.LOANS, "AUT PAGO 0000000099") for day in months]
    extras = [
        charge("2026-03-28", "50000", cat.LOANS, "AUT PAGO 0000000099"),
        charge("2026-05-02", "20000", cat.LOANS, "AUT PAGO 0000000099"),
    ]
    return [*payments, *extras]


def test_loan_with_extra_payments_keeps_installment_series() -> None:
    [found] = rec.detect(loan_payments())
    assert found.cadence == "monthly"
    assert found.typical == D(15000)
    assert len(found.charges) == 6
    assert all(c.amount == D(15000) for c in found.charges)
    assert [c.amount for c in found.extras] == [D(50000), D(20000)]
    assert found.price_change is None
    assert rec.group_of(found.category_ref) == t("analysis.recurring.group.loans")


def test_installment_amount_mode_and_fallback() -> None:
    assert rec.installment_amount(loan_payments()) == D(15000)
    odd = [
        charge(f"2026-0{m}-25", str(14000 + m), cat.LOANS, "PRESTAMO FICTICIO") for m in (1, 2, 3)
    ]
    assert rec.installment_amount(odd) == D(14002)  # nothing repeats: the median


def test_loan_in_overview_shows_extras_this_year_and_stays_in_loans_with_installments() -> None:
    key = ("AUT PAGO 0000000099", "DOP")
    marks = {key: Mark(None, 12, None, date(2026, 3, 30))}
    view = build_overview(loan_payments(), marks, {}, "2026-06")
    [item] = view.items
    assert item.group == t("analysis.recurring.group.loans")
    assert item.installments_left == 9  # April, May and June
    assert item.extras_year == D(70000)
    assert [a.kind for a in view.alerts] == []


def test_groups_by_reference_even_if_category_renamed() -> None:
    rent = [
        replace(
            charge(f"2026-0{m}-01", "25000", "My home", "ALQUILER FICTICIO"),
            category_key=cat.HOUSING,
        )
        for m in (1, 2, 3)
    ]
    loan = [replace(m, category="Debts", category_key=cat.LOANS) for m in loan_payments()]
    view = build_overview([*rent, *loan], {}, {}, None)
    assert [(i.group, i.category) for i in view.items] == [
        (t("analysis.recurring.group.housing"), "My home"),
        (t("analysis.recurring.group.loans"), "Debts"),
    ]
    assert (
        t("analysis.recurring.group.housing"),
        t("analysis.recurring.group.loans"),
        t("analysis.recurring.group.utilities"),
        t("analysis.recurring.group.insurance"),
        t("analysis.recurring.group.subscriptions"),
        t("analysis.recurring.group.fees"),
        t("web.recurring.installments_group"),
        t("analysis.recurring.group.other"),
    ) == GROUP_ORDER
    assert get_args(GroupKey) == tuple(rec.GROUPS)


def test_union_joins_two_merchants_and_separate_undoes_it() -> None:
    movements = [
        bill("2026-01-05", "900", "AGUA FICTICIA PAGO"),
        bill("2026-02-05", "900", "AGUA FICTICIA WEB"),
        bill("2026-03-05", "900", "AGUA FICTICIA PAGO"),
        bill("2026-04-05", "900", "AGUA FICTICIA WEB"),
    ]
    assert rec.detect(movements) == []  # each name on its own has fewer than three months
    groups = rec.members(movements)
    plan = rec.join_plan(groups, "AGUA FICTICIA WEB", "AGUA FICTICIA PAGO")
    assert plan == {"AGUA FICTICIA WEB": "AGUA FICTICIA PAGO"}
    [found] = rec.detect(movements, plan)
    assert found.merchant == "AGUA FICTICIA PAGO"
    assert found.members == ("AGUA FICTICIA PAGO", "AGUA FICTICIA WEB")
    assert rec.separate_plan(movements, plan, "AGUA FICTICIA WEB") is None  # removes the union
    with pytest.raises(rec.JoinError):
        rec.separate_plan(movements, {}, "AGUA FICTICIA WEB")


def test_join_with_a_provider_and_separate_from_the_list() -> None:
    movements = [*phone_bills(), bill("2026-06-12", "100", "PAGO FIJO FICTICIO")]
    groups = rec.members(movements)
    plan = rec.join_plan(groups, "PAGO FIJO FICTICIO", TEL)
    assert plan == {"PAGO FIJO FICTICIO": TEL}
    assert "PAGO FIJO FICTICIO" in rec.detect(movements, plan)[0].members
    # A merchant on the list is separated by a union with itself.
    assert rec.separate_plan(movements, {}, "TELFIC P") == "TELFIC P"
    found = rec.detect(movements, {"TELFIC P": "TELFIC P"})
    assert "TELFIC P" not in found[0].members
    with pytest.raises(LookupError):
        rec.join_plan(groups, "MISSING", TEL)
    with pytest.raises(LookupError):
        rec.join_plan(groups, TEL, "provider:missing")
    with pytest.raises(rec.JoinError):
        rec.join_plan(groups, TEL, TEL)


def test_mark_problem() -> None:
    assert rec.mark_problem(bill("2026-01-05", "100", "TELFIC PAGO")) == ""
    refund = bill("2026-01-05", "-100", "TELFIC PAGO")
    assert rec.mark_problem(refund) == t("analysis.recurring.mark.refund")
    top_up = bill("2026-01-05", "100", "TELFIC RECARGA")
    assert rec.mark_problem(top_up) == t("analysis.recurring.mark.top_up")
    income = charge("2026-01-05", "100", cat.SALARY, "NOMINA FICTICIA")
    assert rec.mark_problem(income) == t("analysis.recurring.mark.not_expense")


def test_marked_series_with_chosen_cadence() -> None:
    movements = [charge("2026-02-14", "4800", cat.OTHER, "SEGURO CASA FICTICIO")]
    found = rec.marked(movements, "SEGURO CASA FICTICIO", "DOP", cadence="yearly")
    assert found is not None
    assert (found.cadence, found.typical, found.monthly) == ("yearly", D(4800), D(400))


def test_member_marks_count_for_the_provider_series() -> None:
    day = date(2026, 1, 1)
    marks = {
        ("TELFIC PAGO", "DOP"): Mark("confirmed", None, day, None),
        ("TELFIC WB", "DOP"): Mark("dismissed", None, date(2026, 2, 1), None, None, "other"),
        ("TELFIC P", "DOP"): Mark(None, 3, None, day),
        ("OTRO FICTICIO", "DOP"): Mark("confirmed", None, day, None),
    }
    groups = rec.members(phone_bills())
    resolved = for_series(marks, groups)
    assert resolved[(TEL, "DOP")] == Mark("dismissed", 3, date(2026, 2, 1), day, None, "other")
    assert ("TELFIC PAGO", "DOP") not in resolved  # no separate recurring charge is left
    assert resolved[("OTRO FICTICIO", "DOP")] == marks[("OTRO FICTICIO", "DOP")]
    # The series' own mark wins over its merchants' marks.
    own = {**marks, (TEL, "DOP"): Mark("confirmed", None, day, None)}
    assert for_series(own, groups)[(TEL, "DOP")] == own[(TEL, "DOP")]
    assert merge([]) == Mark(None, None, None, None)


def test_overview_uses_member_marks_and_manual_group() -> None:
    marks = {("TELFIC IBANKING", "DOP"): Mark("dismissed", None, date(2026, 6, 1), None)}
    view = build_overview(phone_bills(), marks, {}, None)
    assert view.items == []
    assert [d.merchant for d in view.dismissed] == [TEL]
    chosen = {(TEL, "DOP"): Mark("confirmed", None, date(2026, 6, 1), None, None, "housing")}
    [item] = build_overview(phone_bills(), chosen, {}, None).items
    assert (item.group, item.name, item.provider) == (
        t("analysis.recurring.group.housing"),
        "Fictional Phone Co",
        True,
    )
    assert item.members == ("TELFIC IBANKING", "TELFIC P", "TELFIC PAGO", "TELFIC WB")


def test_manual_cadence_overrides_detected_one() -> None:
    movements = [charge(f"2026-0{m}-05", "1200", cat.OTHER, "CLUB FICTICIO") for m in (1, 2, 3)]
    marks = {("CLUB FICTICIO", "DOP"): Mark("confirmed", None, date(2026, 3, 6), None, "yearly")}
    [item] = build_overview(movements, marks, {}, None).items
    assert (item.cadence, item.yearly_dop) == ("yearly", D(1200))


def test_utility_sustained_rise_alerts_in_its_month() -> None:
    amounts = ["1000"] * 3 + ["1300"] * 3
    movements = [bill(f"2026-0{i + 1}-10", a, "LUZFIC PAGO") for i, a in enumerate(amounts)]
    [alert] = build_overview(movements, {}, {}, "2026-06").alerts
    assert (alert.kind, alert.name) == ("price_up", "Fictional Power")
    assert alert.detail == t("web.recurring.alert_price_up", before="RD$ 1,000", after="RD$ 1,300")
