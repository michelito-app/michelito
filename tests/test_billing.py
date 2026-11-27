"""Billing of a credit card from its statements: the fixed bank-side classification."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from michelito import db
from michelito.analysis import billing
from michelito.analysis import rates as rates_store
from michelito.parsers.common import CREDIT, DEBIT, Section, Statement, Transaction
from tests.helpers import store


@pytest.mark.parametrize(
    ("direction", "mcc", "description", "group"),
    [
        (DEBIT, "5411", "SUPERMERCADO FICTICIO", billing.PURCHASES),
        (DEBIT, None, "TIENDA SIN CODIGO", billing.PURCHASES),
        (DEBIT, "3005", "AEROLINEA DEMO", billing.PURCHASES),
        (DEBIT, "6011", "BANCO DEMO", billing.CASH_ADVANCES),
        (DEBIT, "4829", "ENVIO DE DINERO", billing.CASH_ADVANCES),
        (DEBIT, None, "RETIRO CAJERO PLAZA", billing.CASH_ADVANCES),
        (DEBIT, None, "COD CASH ADVANCE", billing.CASH_ADVANCES),
        (DEBIT, None, "INTERESES", billing.BANK_FEES),
        (DEBIT, None, "COMISION POR MEMBRESIA", billing.BANK_FEES),
        (DEBIT, None, "PROTECCION POR FRAUDE", billing.BANK_FEES),
        # An MCC wins over fee words: a merchant called like a fee is still a purchase.
        (DEBIT, "5999", "INTERESES COMERCIO", billing.PURCHASES),
        (CREDIT, None, "DEV TIENDA FICTICIA", billing.REFUNDS),
        (CREDIT, None, "DEVOLUCION TIENDA FICTICIA", billing.REFUNDS),
        (CREDIT, "5411", "SUPERMERCADO FICTICIO", billing.REFUNDS),
        (CREDIT, None, "CR INTERES", billing.BANK_FEES),
        (CREDIT, None, "DEVOLUCION COMISION MEMBRESIA", billing.BANK_FEES),
        (CREDIT, None, "DEV INTERESES", billing.BANK_FEES),
        (CREDIT, None, "PAGO RECIBIDO GRACIAS", billing.PAYMENTS),
        (CREDIT, None, "ABONO", billing.PAYMENTS),
    ],
)
def test_group_of(direction: str, mcc: str | None, description: str, group: str) -> None:
    assert billing.group_of(direction, mcc, description) == group


def test_signed_amount_reverses_credits() -> None:
    # A fee reversal lowers the fees; every other group keeps the amount positive.
    assert billing.signed_cents(CREDIT, billing.BANK_FEES, 350_00) == -350_00
    assert billing.signed_cents(DEBIT, billing.BANK_FEES, 350_00) == 350_00
    assert billing.signed_cents(CREDIT, billing.REFUNDS, 500_00) == 500_00
    assert billing.signed_cents(DEBIT, billing.PURCHASES, 12_000_00) == 12_000_00


# --- account_billing over stored statements (made-up card) ---

CARD = "ficticio:credit_card"


def _tx(
    day: date, text: str, amount: str, direction: str, currency: str, mcc: str | None
) -> Transaction:
    return Transaction(day, None, text, Decimal(amount), direction, currency, None, mcc, text)


def _card(
    period_end: date, sections: tuple[Section, ...], parser: str = "popular_card"
) -> Statement:
    return Statement(
        parser, "ficticio", "credit_card", "VISA DEMO", "4242", period_end, None, sections
    )


def _dop(period_end: date) -> Section:
    day = period_end.replace(day=5)
    rows = (
        _tx(day, "SUPERMERCADO FICTICIO", "12000.00", DEBIT, "DOP", "5411"),
        _tx(day, "RETIRO CAJERO PLAZA", "2000.00", DEBIT, "DOP", None),
        _tx(day, "INTERESES", "350.00", DEBIT, "DOP", None),
        _tx(day, "DEV TIENDA FICTICIA", "500.00", CREDIT, "DOP", None),
        _tx(day, "PAGO RECIBIDO GRACIAS", "10000.00", CREDIT, "DOP", None),
    )
    return Section("DOP", Decimal("1000.00"), Decimal("4850.00"), None, None, None, None, rows)


def _usd(period_end: date) -> Section:
    rows = (_tx(period_end.replace(day=6), "AEROLINEA DEMO", "100.00", DEBIT, "USD", "3005"),)
    return Section("USD", Decimal("0"), Decimal("100.00"), None, None, None, None, rows)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    store(connection, _card(date(2026, 1, 20), (_dop(date(2026, 1, 20)), _usd(date(2026, 1, 20)))))
    store(connection, _card(date(2026, 2, 20), (_dop(date(2026, 2, 20)),)))
    with connection:
        rates_store.set_manual(connection, "2026-01", Decimal("60.00"))
    yield connection
    connection.close()


def test_billing_groups_each_statement_and_totals_by_currency(conn) -> None:
    result = billing.account_billing(conn, CARD, "2026-01", "2026-02", rates_store.load(conn))
    assert [(s.period_end, s.currency) for s in result.statements] == [
        (date(2026, 1, 20), "DOP"),
        (date(2026, 1, 20), "USD"),
        (date(2026, 2, 20), "DOP"),
    ]
    assert result.totals["DOP"] == {
        billing.PURCHASES: 24_000_00,
        billing.CASH_ADVANCES: 4_000_00,
        billing.BANK_FEES: 700_00,
        billing.REFUNDS: 1_000_00,
        billing.PAYMENTS: 20_000_00,
    }
    assert result.totals["USD"][billing.PURCHASES] == 100_00
    assert result.statements[0].closing_balance_cents == 4_850_00
    assert result.complete and result.missing == ()


def test_usd_converts_at_the_closing_month_rate(conn) -> None:
    result = billing.account_billing(conn, CARD, "2026-01", "2026-02", rates_store.load(conn))
    usd = result.statements[1]
    assert usd.rate is not None and usd.rate.month_used == "2026-01"
    assert usd.converted_dop == {**dict.fromkeys(billing.GROUPS, 0), billing.PURCHASES: 6_000_00}
    converted = result.converted_dop
    assert converted is not None and converted[billing.PURCHASES] == 24_000_00 + 6_000_00


def test_usd_without_any_rate_leaves_the_conversion_out(conn) -> None:
    result = billing.account_billing(conn, CARD, "2026-01", "2026-02", {})
    assert result.statements[1].converted_dop is None
    assert result.converted_dop is None
    assert result.totals["USD"][billing.PURCHASES] == 100_00


def test_missing_months_make_it_incomplete(conn) -> None:
    result = billing.account_billing(conn, CARD, "2025-12", "2026-03", rates_store.load(conn))
    assert result.missing == ("2025-12", "2026-03")
    assert not result.complete


def test_printouts_never_count(conn) -> None:
    printout = _card(date(2026, 3, 10), (_dop(date(2026, 3, 10)),), parser=db.PRINTOUT_PARSER)
    store(conn, printout)
    result = billing.account_billing(conn, CARD, "2026-03", "2026-03", {})
    assert result.statements == ()
    assert result.missing == ("2026-03",)


def test_unknown_account_and_non_card_are_refused(conn) -> None:
    with pytest.raises(billing.AccountNotFound):
        billing.account_billing(conn, "missing:account", "2026-01", "2026-01", {})
    savings = Statement(
        "bhd_savings",
        "ficticio",
        "savings",
        "AHORRO",
        "777-0",
        date(2026, 1, 31),
        None,
        (Section("DOP", Decimal(0), Decimal(0), None, None, None, None, ()),),
    )
    store(conn, savings)
    with pytest.raises(billing.NotACard):
        billing.account_billing(conn, "ficticio:savings:777-0", "2026-01", "2026-01", {})


def test_months_between_crosses_the_year() -> None:
    assert billing.months_between("2025-11", "2026-02") == [
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
    ]
    assert billing.months_between("2026-03", "2026-02") == []


def test_months_back_crosses_the_year() -> None:
    assert billing.months_back("2026-02", 11) == "2025-03"
    assert billing.months_back("2026-12", 0) == "2026-12"


def test_latest_month_skips_printouts(conn) -> None:
    store(conn, _card(date(2026, 4, 10), (_dop(date(2026, 4, 10)),), parser=db.PRINTOUT_PARSER))
    assert billing.latest_month(conn, CARD) == "2026-02"
    assert billing.latest_month(conn, "missing:account") is None


def test_span_counts_both_ends() -> None:
    assert billing.span("2025-02", "2026-01") == 12
    assert billing.span("2026-01", "2026-01") == 1
    assert billing.span("2026-02", "2026-01") == 0
