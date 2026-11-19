"""Recurrentes del hogar (lógica pura): proveedores con varios nombres y suma por mes, luz que
varía mucho, recargas fuera, «subió» sostenido, préstamos con abonos extra, grupos Vivienda y
Préstamos por referencia, uniones y marcas por serie. Proveedores y montos inventados."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import get_args

import pytest

from finanzas.analysis import categories as cat
from finanzas.analysis import providers
from finanzas.analysis import recurring as rec
from finanzas.analysis.recurring_marks import Mark, for_series, merge
from finanzas.analysis.spending import Movement
from finanzas.web.recurring import GROUP_ORDER, build_overview
from finanzas.web.recurring_schemas import GroupKey
from tests.test_recurring import charge

D = Decimal
TEL = "proveedor:telfic"
FAKES = (
    providers.make_provider("telfic", "Telefónica Ficticia", r"TELFIC|TELEFONICA FICTICIA"),
    providers.make_provider("luzfic", "Luz Ficticia", r"LUZFIC"),
)


@pytest.fixture(autouse=True)
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proveedores inventados en lugar de la lista real (los datos de prueba no usan nombres
    reales)."""
    monkeypatch.setattr(providers, "PROVIDERS", FAKES)


def bill(day: str, amount: str, merchant: str, category: str = cat.UTILITIES) -> Movement:
    return charge(day, amount, category, merchant)


def phone_bills() -> list[Movement]:
    """Cuatro nombres del mismo proveedor; marzo sin pago, abril doble, mayo en dos pagos."""
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
    assert found.name == "Telefónica Ficticia"
    assert found.members == ("TELFIC IBANKING", "TELFIC P", "TELFIC PAGO", "TELFIC WB")
    assert found.cadence == "mensual"
    assert [c.amount for c in found.charges] == [D(1000), D(1000), D(2000), D(1000), D(1000)]
    assert found.charges[3].day == date(2026, 5, 20)  # la suma lleva el día del último pago
    assert found.variable is True
    assert found.typical == D("1000.00")  # el doble de abril cubre marzo
    assert found.price_change is None


def test_provider_only_inside_utilities() -> None:
    other = [bill(f"2026-0{m}-05", "300", "TELFIC TIENDA", cat.HOME) for m in (1, 2, 3)]
    found = {r.merchant for r in rec.detect([*phone_bills(), *other])}
    assert found == {TEL, "TELFIC TIENDA"}


def test_electricity_varying_sixty_percent_is_detected() -> None:
    amounts = ("1000", "1600", "400", "1600", "400")
    movements = [bill(f"2026-0{i + 1}-15", a, "LUZFIC PAGO") for i, a in enumerate(amounts)]
    [found] = rec.detect(movements)
    assert found.merchant == "proveedor:luzfic"
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


def test_sustained_rise_reports_subio() -> None:
    amounts = ["1000"] * 3 + ["1300"] * 3
    movements = [bill(f"2026-0{i + 1}-10", a, "LUZFIC PAGO") for i, a in enumerate(amounts)]
    [found] = rec.detect(movements)
    assert found.price_change == rec.PriceChange(D("1000.00"), D("1300.00"), date(2026, 6, 10))


@pytest.mark.parametrize(
    "amounts",
    [
        ["1000"] * 5 + ["1900"],  # un mes caro suelto al final
        ["1000"] * 4 + ["1900", "1000"],  # un mes caro suelto entre los últimos tres
        ["1000"] * 3 + ["1200"] * 3,  # +20 %: no llega al umbral
    ],
)
def test_utility_spike_or_small_rise_is_not_subio(amounts: list[str]) -> None:
    movements = [bill(f"2026-0{i + 1}-10", a, "LUZFIC PAGO") for i, a in enumerate(amounts)]
    [found] = rec.detect(movements)
    assert found.price_change is None


def test_double_payment_after_empty_month_is_not_a_rise() -> None:
    # 1000, 1000, 1000, (nada), 2000, 1000: repartido es 1000 todos los meses.
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
    assert found.cadence == "mensual"
    assert found.typical == D(15000)
    assert len(found.charges) == 6
    assert all(c.amount == D(15000) for c in found.charges)
    assert [c.amount for c in found.extras] == [D(50000), D(20000)]
    assert found.price_change is None
    assert rec.group_of(found.category_ref) == "Préstamos"


def test_installment_amount_mode_and_fallback() -> None:
    assert rec.installment_amount(loan_payments()) == D(15000)
    odd = [
        charge(f"2026-0{m}-25", str(14000 + m), cat.LOANS, "PRESTAMO FICTICIO") for m in (1, 2, 3)
    ]
    assert rec.installment_amount(odd) == D(14002)  # nada se repite: la mediana


def test_loan_in_overview_shows_extras_this_year_and_stays_in_loans_with_installments() -> None:
    key = ("AUT PAGO 0000000099", "DOP")
    marks = {key: Mark(None, 12, None, date(2026, 3, 30))}
    view = build_overview(loan_payments(), marks, {}, "2026-06")
    [item] = view.items
    assert item.group == "Préstamos"
    assert item.installments_left == 9  # abril, mayo y junio
    assert item.extras_year == D(70000)
    assert [a.kind for a in view.alerts] == []


def test_groups_by_reference_even_if_category_renamed() -> None:
    rent = [
        replace(
            charge(f"2026-0{m}-01", "25000", "Mi casa", "ALQUILER FICTICIO"),
            category_key=cat.HOUSING,
        )
        for m in (1, 2, 3)
    ]
    loan = [replace(m, category="Deudas", category_key=cat.LOANS) for m in loan_payments()]
    view = build_overview([*rent, *loan], {}, {}, None)
    assert [(i.group, i.category) for i in view.items] == [
        ("Vivienda", "Mi casa"),
        ("Préstamos", "Deudas"),
    ]
    assert GROUP_ORDER == (
        "Vivienda",
        "Préstamos",
        "Servicios",
        "Seguros",
        "Suscripciones",
        "Cargos del banco",
        "Cuotas",
        "Otros recurrentes",
    )
    assert get_args(GroupKey) == tuple(rec.GROUPS)


def test_union_joins_two_merchants_and_separate_undoes_it() -> None:
    movements = [
        bill("2026-01-05", "900", "AGUA FICTICIA PAGO"),
        bill("2026-02-05", "900", "AGUA FICTICIA WEB"),
        bill("2026-03-05", "900", "AGUA FICTICIA PAGO"),
        bill("2026-04-05", "900", "AGUA FICTICIA WEB"),
    ]
    assert rec.detect(movements) == []  # cada nombre por su lado no llega a tres meses
    groups = rec.members(movements)
    plan = rec.join_plan(groups, "AGUA FICTICIA WEB", "AGUA FICTICIA PAGO")
    assert plan == {"AGUA FICTICIA WEB": "AGUA FICTICIA PAGO"}
    [found] = rec.detect(movements, plan)
    assert found.merchant == "AGUA FICTICIA PAGO"
    assert found.members == ("AGUA FICTICIA PAGO", "AGUA FICTICIA WEB")
    assert rec.separate_plan(movements, plan, "AGUA FICTICIA WEB") is None  # borra la unión
    with pytest.raises(rec.JoinError):
        rec.separate_plan(movements, {}, "AGUA FICTICIA WEB")


def test_join_with_a_provider_and_separate_from_the_list() -> None:
    movements = [*phone_bills(), bill("2026-06-12", "100", "PAGO FIJO FICTICIO")]
    groups = rec.members(movements)
    plan = rec.join_plan(groups, "PAGO FIJO FICTICIO", TEL)
    assert plan == {"PAGO FIJO FICTICIO": TEL}
    assert "PAGO FIJO FICTICIO" in rec.detect(movements, plan)[0].members
    # Un comercio de la lista se separa con una unión consigo mismo.
    assert rec.separate_plan(movements, {}, "TELFIC P") == "TELFIC P"
    found = rec.detect(movements, {"TELFIC P": "TELFIC P"})
    assert "TELFIC P" not in found[0].members
    with pytest.raises(LookupError):
        rec.join_plan(groups, "NO EXISTE", TEL)
    with pytest.raises(LookupError):
        rec.join_plan(groups, TEL, "proveedor:no-existe")
    with pytest.raises(rec.JoinError):
        rec.join_plan(groups, TEL, TEL)


def test_mark_problem() -> None:
    assert rec.mark_problem(bill("2026-01-05", "100", "TELFIC PAGO")) == ""
    assert "devolución" in rec.mark_problem(bill("2026-01-05", "-100", "TELFIC PAGO"))
    assert "recargas" in rec.mark_problem(bill("2026-01-05", "100", "TELFIC RECARGA"))
    income = charge("2026-01-05", "100", cat.SALARY, "NOMINA FICTICIA")
    assert "gasto" in rec.mark_problem(income)


def test_marked_series_with_chosen_cadence() -> None:
    movements = [charge("2026-02-14", "4800", cat.OTHER, "SEGURO CASA FICTICIO")]
    found = rec.marked(movements, "SEGURO CASA FICTICIO", "DOP", cadence="anual")
    assert found is not None
    assert (found.cadence, found.typical, found.monthly) == ("anual", D(4800), D(400))


def test_member_marks_count_for_the_provider_series() -> None:
    day = date(2026, 1, 1)
    marks = {
        ("TELFIC PAGO", "DOP"): Mark("confirmed", None, day, None),
        ("TELFIC WB", "DOP"): Mark("dismissed", None, date(2026, 2, 1), None, None, "otros"),
        ("TELFIC P", "DOP"): Mark(None, 3, None, day),
        ("OTRO FICTICIO", "DOP"): Mark("confirmed", None, day, None),
    }
    groups = rec.members(phone_bills())
    resolved = for_series(marks, groups)
    assert resolved[(TEL, "DOP")] == Mark("dismissed", 3, date(2026, 2, 1), day, None, "otros")
    assert ("TELFIC PAGO", "DOP") not in resolved  # no queda un recurrente aparte
    assert resolved[("OTRO FICTICIO", "DOP")] == marks[("OTRO FICTICIO", "DOP")]
    # La marca propia de la serie gana a las de sus comercios.
    own = {**marks, (TEL, "DOP"): Mark("confirmed", None, day, None)}
    assert for_series(own, groups)[(TEL, "DOP")] == own[(TEL, "DOP")]
    assert merge([]) == Mark(None, None, None, None)


def test_overview_uses_member_marks_and_manual_group() -> None:
    marks = {("TELFIC IBANKING", "DOP"): Mark("dismissed", None, date(2026, 6, 1), None)}
    view = build_overview(phone_bills(), marks, {}, None)
    assert view.items == []
    assert [d.merchant for d in view.dismissed] == [TEL]
    chosen = {(TEL, "DOP"): Mark("confirmed", None, date(2026, 6, 1), None, None, "vivienda")}
    [item] = build_overview(phone_bills(), chosen, {}, None).items
    assert (item.group, item.name, item.provider) == ("Vivienda", "Telefónica Ficticia", True)
    assert item.members == ("TELFIC IBANKING", "TELFIC P", "TELFIC PAGO", "TELFIC WB")


def test_manual_cadence_overrides_detected_one() -> None:
    movements = [charge(f"2026-0{m}-05", "1200", cat.OTHER, "CLUB FICTICIO") for m in (1, 2, 3)]
    marks = {("CLUB FICTICIO", "DOP"): Mark("confirmed", None, date(2026, 3, 6), None, "anual")}
    [item] = build_overview(movements, marks, {}, None).items
    assert (item.cadence, item.yearly_dop) == ("anual", D(1200))


def test_utility_sustained_rise_alerts_in_its_month() -> None:
    amounts = ["1000"] * 3 + ["1300"] * 3
    movements = [bill(f"2026-0{i + 1}-10", a, "LUZFIC PAGO") for i, a in enumerate(amounts)]
    [alert] = build_overview(movements, {}, {}, "2026-06").alerts
    assert (alert.kind, alert.name) == ("subio", "Luz Ficticia")
    assert alert.detail == "Subió de RD$ 1,000 a RD$ 1,300"
