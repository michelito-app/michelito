from datetime import date
from decimal import Decimal

import pytest

from finanzas import db
from finanzas.analysis import rates
from finanzas.web import interest
from tests.test_spending import seed
from tests.test_web_accounts import add_statement

TODAY = date(2026, 3, 1)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)
    yield connection
    connection.close()


def add_charge(conn, statement_id, day, cents, currency="DOP", text="INTERESES FINANCIAMIENTO"):
    with conn:
        conn.execute(
            "INSERT INTO transactions (statement_id, sequence, transacted_on, description, "
            "amount_cents, direction, currency, raw_line) "
            "VALUES (?, 9000 + (SELECT COUNT(*) FROM transactions), ?, ?, ?, 'debit', ?, 'x')",
            (statement_id, day, text, cents, currency),
        )


def test_interest_year_totals_and_conversion(conn) -> None:
    dop = add_statement(conn, "bhd:credit_card", "2026-03-26", closing=0)
    usd = add_statement(conn, "bhd:credit_card", "2026-03-26", currency="USD", closing=0)
    add_charge(conn, dop, "2026-01-10", 3_500)
    add_charge(conn, dop, "2026-02-10", 1_500)
    add_charge(conn, dop, "2026-02-11", 999, text="CR INTERESES FINANCIAMIENTO")  # reversa
    add_charge(conn, dop, "2025-12-31", 7_000)  # otro año
    add_charge(conn, usd, "2026-01-12", 1_000, "USD")  # 10.00 US$ con tasa
    add_charge(conn, usd, "2026-02-12", 500, "USD")
    with conn:
        rates.set_manual(conn, "2026-01", Decimal("60"))
        rates.set_manual(conn, "2026-02", Decimal("61"))

    result = interest.interest_year(conn, rates.load(conn), 2026, TODAY)

    by = {(line.key, line.currency): line.total for line in result.lines}
    assert by[("bhd:credit_card", "DOP")] == Decimal("50.00")
    assert by[("bhd:credit_card", "USD")] == Decimal("15.00")
    assert result.total_dop == Decimal("50.00") + Decimal("600") + Decimal("305")
    assert result.unconverted_usd == 0
    assert result.year == 2026


def test_interest_year_usd_without_rate(conn) -> None:
    usd = add_statement(conn, "bhd:credit_card", "2026-03-26", currency="USD", closing=0)
    add_charge(conn, usd, "2026-01-12", 1_000, "USD")

    result = interest.interest_year(conn, rates.load(conn), 2026, TODAY)

    assert result.unconverted_usd == Decimal("10.00")
    assert result.total_dop == 0
    assert [line.total for line in result.lines] == [Decimal("10.00")]


def test_next_due_is_earliest_not_past(conn) -> None:
    add_statement(conn, "bhd:credit_card", "2026-02-26", closing=1000, due="2026-03-20")
    assert interest.interest_year(conn, {}, 2026, date(2026, 3, 1)).next_due is not None
    late = interest.interest_year(conn, {}, 2026, date(2026, 4, 1))
    assert late.next_due is None
