from datetime import date
from decimal import Decimal

import pytest

from finanzas import db
from finanzas.analysis import interest
from finanzas.analysis.interest import StatementMoney
from tests.test_spending import seed


@pytest.mark.parametrize(
    ("description", "direction", "expected"),
    [
        ("INTERESES FINANCIAMIENTO", "debit", True),
        ("Intereses Financiamiento", "debit", True),
        ("INTERES", "debit", True),
        ("CR INTERES FINANCIAMIENTO", "debit", False),
        ("CR INTERES FINANCIAMIENTO", "credit", False),
        ("INTERES", "credit", False),
        ("TIENDA INTERESANTE", "debit", False),
        ("123 CR INTERES FINANCIAMIENTO", "debit", False),
        ("00045 INTERES FINANCIAMIENTO", "debit", True),
        ("CREDITO INTERES", "debit", True),
    ],
)
def test_is_interest(description: str, direction: str, expected: bool) -> None:
    assert interest.is_interest(description, direction) is expected


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)
    yield connection
    connection.close()


def _add(conn, statement_id: int, sequence: int, description: str, cents: int, direction: str):
    with conn:
        conn.execute(
            "INSERT INTO transactions (statement_id, sequence, transacted_on, description, "
            "amount_cents, direction, currency, raw_line) "
            "VALUES (?, ?, '2026-01-05', ?, ?, ?, 'DOP', 'x')",
            (statement_id, sequence, description, cents, direction),
        )


def test_statement_money_sums_payments_and_interest(conn) -> None:
    before = interest.statement_money(conn)
    sid = conn.execute("SELECT MAX(id) FROM statements").fetchone()[0]
    base = before.get(sid, StatementMoney(Decimal(0), Decimal(0)))
    _add(conn, sid, 9001, "PAGO RECIBIDO GRACIAS", 100_050, "credit")
    _add(conn, sid, 9002, "PAGO RECIBIDO GRACIAS", 20_000, "credit")
    _add(conn, sid, 9003, "INTERESES FINANCIAMIENTO", 35_075, "debit")
    _add(conn, sid, 9004, "CR INTERES FINANCIAMIENTO", 9_999, "credit")
    _add(conn, sid, 9005, "TIENDA INTERESANTE", 5_000, "debit")

    after = interest.statement_money(conn)

    assert after[sid] == StatementMoney(
        payments=base.payments + Decimal("1200.50"),
        interest=base.interest + Decimal("350.75"),
    )
    assert all(isinstance(v, StatementMoney) for v in after.values())


def test_payments_through_cutoff(conn) -> None:
    sid = conn.execute("SELECT MAX(id) FROM statements").fetchone()[0]
    _add(conn, sid, 9001, "PAGO RECIBIDO GRACIAS", 10_000, "credit")  # 2026-01-05
    money = interest.statement_money(conn)[sid]
    assert money.payments_through(None) == Decimal("100.50")
    assert money.payments_through(date(2026, 1, 5)) == Decimal("100.00")  # sin el del 31
    assert money.payments_through(date(2026, 1, 4)) == Decimal(0)
