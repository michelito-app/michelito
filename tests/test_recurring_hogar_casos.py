"""Recurrentes del hogar, segunda ronda (lógica pura, datos inventados): cuota de préstamo que
cambia o que se paga en dos partes, Servicios que no quedan inactivos por un mes sin pago, compras
en tiendas del proveedor fuera de la factura, uniones obsoletas y categorías del usuario que se
sugieren en Vivienda."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from finanzas.analysis import categories as cat
from finanzas.analysis import providers
from finanzas.analysis import recurring as rec
from finanzas.analysis.recurring_marks import Mark
from finanzas.analysis.spending import Movement
from finanzas.web.recurring import build_overview, series_view
from tests.test_recurring import charge

D = Decimal
TEL = "proveedor:telfic"
LOAN = "AUT PAGO 0000000077"


@pytest.fixture(autouse=True)
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = providers.make_provider("telfic", "Telefónica Ficticia", r"TELFIC")
    monkeypatch.setattr(providers, "PROVIDERS", (fake,))


def month_day(index: int, day: int = 15) -> str:
    """El día `day` del mes `index` contando desde enero de 2025."""
    return date(2025 + index // 12, index % 12 + 1, day).isoformat()


def test_loan_installment_change_keeps_the_series_without_fake_extras() -> None:
    payments = [charge(month_day(i), "10000", cat.LOANS, LOAN) for i in range(9)]
    payments += [charge(month_day(i), "12000", cat.LOANS, LOAN) for i in range(9, 14)]
    [found] = rec.detect(payments)
    assert found.typical == D(12000)
    assert found.extras == ()
    assert len(found.charges) == 14
    assert rec.installment_amount(payments) == D(12000)
    [item] = build_overview(payments, {}, {}, None).items
    assert item.status == "activo"


def test_repeated_extra_payment_does_not_beat_the_installment() -> None:
    payments = [charge(month_day(i), "10000", cat.LOANS, LOAN) for i in range(8)]
    payments += [charge(month_day(i, 28), "30000", cat.LOANS, LOAN) for i in (2, 5)]
    [found] = rec.detect(payments)
    assert found.typical == D(10000)
    assert [c.amount for c in found.extras] == [D(30000), D(30000)]


def test_installment_paid_in_two_parts_is_the_monthly_sum() -> None:
    payments = [
        charge(month_day(i, day), "5000", cat.LOANS, LOAN) for i in range(5) for day in (5, 20)
    ]
    [found] = rec.detect(payments)
    assert found.typical == D(10000)
    assert found.extras == ()
    assert [c.amount for c in found.charges] == [D(10000)] * 5


def bill(day: str, amount: str, merchant: str) -> Movement:
    return charge(day, amount, cat.UTILITIES, merchant)


@pytest.mark.parametrize(("days", "expected"), [(89, "activo"), (91, "inactivo")])
def test_one_month_without_payment_does_not_make_a_utility_inactive(
    days: int, expected: str
) -> None:
    bills = [bill(f"2026-0{m}-10", "1000", "TELFIC PAGO") for m in (1, 2, 3)]
    filler = charge(
        (date(2026, 3, 10) + timedelta(days=days)).isoformat(), "1", cat.GROCERIES, "RELLENO"
    )
    [item] = build_overview([*bills, filler], {}, {}, None).items
    assert item.status == expected


def test_store_charges_are_not_the_bill_nor_recurring() -> None:
    bills = [bill(f"2026-0{m}-10", "1000", "TELFIC PAGO") for m in range(1, 7)]
    stores = [bill(f"2026-0{m}-20", "1800", "TELFIC AGORA") for m in (4, 5, 6)]
    stores += [bill(f"2026-0{m}-22", "900", "TELFIC CAC") for m in (4, 5, 6)]
    found = rec.detect([*bills, *stores])
    assert [(r.merchant, r.members, r.price_change) for r in found] == [
        (TEL, ("TELFIC PAGO",), None)
    ]
    assert all(rec.series_key(m) is None for m in stores)
    assert "tienda" in rec.mark_problem(stores[0])
    # Unido a mano, sí entra.
    joined = rec.detect([*bills, *stores], {"TELFIC CAC": TEL})
    assert "TELFIC CAC" in joined[0].members


@pytest.mark.parametrize(
    ("merchant", "provider"),
    [("TELFIC", "telfic"), ("TELFIC PAGO", "telfic"), ("TELFIC APP", "telfic")],
)
def test_channel_words_are_the_bill(merchant: str, provider: str) -> None:
    found = providers.provider_of(merchant)
    assert found is not None and found.id == provider


def test_join_rewrites_stored_unions_that_point_to_the_joined_series() -> None:
    groups = {"AGUA B": frozenset({"AGUA B"}), "AGUA C": frozenset({"AGUA C"})}
    unions = {"AGUA VIEJA": "AGUA B", "OTRA": "AGUA C"}
    assert rec.join_plan(groups, "AGUA B", "AGUA C", unions) == {
        "AGUA B": "AGUA C",
        "AGUA VIEJA": "AGUA C",
    }


def rent(category: str, ref: str) -> list[Movement]:
    return [
        replace(charge(f"2026-0{m}-01", "25000", category, "ALQUILER FICTICIO"), category_key=ref)
        for m in (1, 2, 3)
    ]


@pytest.mark.parametrize(
    ("name", "group"),
    [("Alquiler", "Vivienda"), ("Renta", "Vivienda"), ("Mantenimiento", "Vivienda")],
)
def test_user_category_named_like_housing_is_suggested_in_vivienda(name: str, group: str) -> None:
    [item] = build_overview(rent(name, "user:41"), {}, {}, None).items
    assert item.group == group


def test_other_user_categories_and_manual_group_win() -> None:
    [item] = build_overview(rent("Gimnasio", "user:42"), {}, {}, None).items
    assert item.group == "Otros recurrentes"
    chosen = {
        ("ALQUILER FICTICIO", "DOP"): Mark("confirmed", None, date(2026, 3, 2), None, None, "otros")
    }
    [item] = build_overview(rent("Alquiler", "user:41"), chosen, {}, None).items
    assert item.group == "Otros recurrentes"


def test_series_view_matches_the_overview_for_one_series() -> None:
    bills = [bill(f"2026-0{m}-10", "1000", "TELFIC PAGO") for m in (1, 2, 3)]
    other = [charge(f"2026-0{m}-05", "300", cat.SUBSCRIPTIONS, "STREAM") for m in (1, 2, 3)]
    movements = [*bills, *other]
    full = {(i.merchant, i.currency): i for i in build_overview(movements, {}, {}, None).items}
    one = series_view(movements, {}, {}, TEL, "DOP", as_of=date(2026, 3, 10))
    assert one == full[(TEL, "DOP")]
    assert series_view(movements, {}, {}, "NO EXISTE", "DOP", as_of=date(2026, 3, 10)) is None
