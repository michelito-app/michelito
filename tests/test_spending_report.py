from datetime import date
from decimal import Decimal

from finanzas.analysis import categories as cat
from finanzas.analysis import report
from tests.test_spending import movement

MOVEMENTS = (
    movement("2025-11-03", "1000.00"),
    movement("2025-12-05", "3000.00"),
    movement("2025-12-06", "500.00", cat.RESTAURANTS, "CAFE FICTICIO"),
    movement("2025-12-09", "250.00", cat.BANK_FEES, "INTERES FINANCIAMIENTO"),
    movement("2025-12-08", "40.00", cat.BOOKS, "TIENDA ONLINE", currency="USD"),
    movement("2026-01-02", "999.00"),  # mes incompleto: después del último corte común
)


def build() -> report.SpendingReport:
    return report.build(MOVEMENTS, date(2026, 1, 13), months=3)


def test_window_ends_at_last_full_month() -> None:
    built = build()
    assert built.months == ("2025-10", "2025-11", "2025-12")
    dop, usd = built.sections
    assert (dop.currency, usd.currency) == ("DOP", "USD")
    assert dop.total == Decimal("4750.00")
    assert dop.monthly_average == Decimal("4750.00") / 3
    assert dop.bank_fees == Decimal("250.00")
    assert dop.changes[0].category == cat.GROCERIES


def test_currency_without_movements_is_left_out() -> None:
    only_dop = report.build(MOVEMENTS[:2], date(2026, 1, 13), months=3)
    assert [s.currency for s in only_dop.sections] == ["DOP"]


def test_without_data() -> None:
    empty = report.build((), None, months=3)
    assert empty.sections == ()
    assert "No hay estados de tarjeta" in report.to_text(empty)


def test_text_summary() -> None:
    text = report.to_text(build())
    assert "RD$ 4,750" in text
    assert "Supermercado" in text and "84%" in text  # 4000 de 4750
    assert "COLMADO INVENTADO" in text
    assert "Cargos del banco: RD$ 250" in text
    assert "US$ 40.00" in text
    assert text.endswith("finanzas board")


def test_text_wording_and_only_real_increases() -> None:
    refund_only = movement("2025-12-11", "-30.00", cat.SHOPPING, "TIENDA ROPA")
    text = report.to_text(report.build((*MOVEMENTS, refund_only), date(2026, 1, 13), months=3))
    assert "CAFE FICTICIO" in text and "1 compra\n" in text
    comparison = text.split("meses previos:")[1]
    assert "Ropa y tiendas" not in comparison  # bajó: no es un aumento


def test_months_before_the_first_full_month_are_left_out() -> None:
    # Solo hay datos completos desde diciembre: octubre y noviembre no cuentan
    # ni en el total ni en el promedio ni en la comparación.
    built = report.build(MOVEMENTS, date(2026, 1, 13), months=3, first_full_month="2025-12")
    assert built.months == ("2025-12",)
    dop = built.sections[0]
    assert dop.monthly_average == dop.total == Decimal("3750.00")
    assert dop.changes == []  # sin meses previos con datos no hay contra qué comparar
    too_early = report.build(MOVEMENTS, date(2026, 1, 13), months=3, first_full_month="2026-01")
    assert too_early.sections == ()
    assert "Todavía no hay un mes cubierto entero" in report.to_text(too_early)


def test_other_currencies_are_not_dropped() -> None:
    euro = movement("2025-12-12", "15.00", cat.TRAVEL, "MUSEO", currency="EUR")
    built = report.build((*MOVEMENTS, euro), date(2026, 1, 13), months=3)
    assert [s.currency for s in built.sections] == ["DOP", "USD", "EUR"]
    assert "EUR 15.00" in report.to_text(built)


def test_money_has_no_negative_zero() -> None:
    assert report.money(Decimal("-0.40"), "DOP") == "RD$ 0"


def test_share() -> None:
    assert report.share(Decimal(1), Decimal(4)) == "25%"
    assert report.share(Decimal(1), Decimal(0)) == "-"
