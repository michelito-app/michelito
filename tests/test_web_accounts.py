from datetime import date, timedelta
from decimal import Decimal

import pytest

from finanzas import db
from finanzas.web import accounts
from tests.test_spending import seed

TODAY = date(2026, 2, 1)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)
    yield connection
    connection.close()


def view(conn, key, today=TODAY):
    return next(v for v in accounts.account_views(conn, today) if v.key == key)


def add_statement(
    conn, key, period_end, currency="DOP", closing=1000, card=True, due=None, minimum=50
):
    """Copia un estado existente de la cuenta con otro corte (valores inventados)."""
    with conn:
        cursor = conn.execute(
            "INSERT INTO statements (document_id, account_id, card_id, parser, product, currency,"
            " period_end, due_date, previous_balance_cents, closing_balance_cents,"
            " minimum_payment_cents, printed_debits_cents, printed_credits_cents)"
            " SELECT document_id, account_id, card_id, parser, product, ?, ?, ?, 0, ?, ?,"
            " 700, 300 FROM statements WHERE account_id ="
            " (SELECT id FROM accounts WHERE key = ?) LIMIT 1",
            (currency, period_end, due, closing, minimum, key),
        )
    return cursor.lastrowid


def add_payment(conn, statement_id, cents, description="PAGO RECIBIDO GRACIAS", on="2026-01-05"):
    with conn:
        conn.execute(
            "INSERT INTO transactions (statement_id, sequence, transacted_on, description, "
            "amount_cents, direction, currency, raw_line) "
            "VALUES (?, 7000 + (SELECT COUNT(*) FROM transactions), ?, ?, ?, "
            "'credit', 'DOP', 'x')",
            (statement_id, on, description, cents),
        )


def add_interest(conn, statement_id, cents):
    with conn:
        conn.execute(
            "INSERT INTO transactions (statement_id, sequence, transacted_on, description, "
            "amount_cents, direction, currency, raw_line) "
            "VALUES (?, 8000 + (SELECT COUNT(*) FROM transactions), '2026-01-05', "
            "'INTERESES FINANCIAMIENTO', ?, 'debit', 'DOP', 'x')",
            (statement_id, cents),
        )


def test_views_group_currencies_per_account(conn) -> None:
    expected = {
        row["currency"]
        for row in conn.execute(
            "SELECT s.currency FROM statements s JOIN accounts a ON a.id = s.account_id"
            " WHERE a.key = 'bhd:credit_card'"
        )
    }
    bhd = view(conn, "bhd:credit_card")
    assert set(bhd.currencies) == expected
    assert bhd.currencies[0] == "DOP"
    assert {line.currency for line in bhd.latest} == expected
    assert len(bhd.latest) == len(expected)
    assert bhd.cut_day == 26
    assert bhd.kind == "credit_card"


def test_line_amounts_come_from_printed_totals(conn) -> None:
    line = next(x for x in view(conn, "bhd:credit_card").latest if x.currency == "DOP")
    assert line.charges == Decimal("2500.00")
    assert line.payments == Decimal("1000.00")
    assert line.balance == Decimal("2500.00")
    assert line.due_date == date(2026, 2, 20)
    assert line.period_start is None


def test_period_start_from_previous_cut(conn) -> None:
    add_statement(conn, "bhd:credit_card", "2025-12-26")
    newest = view(conn, "bhd:credit_card").statements[0]
    assert newest.period_end == date(2026, 1, 26)
    assert newest.period_start == date(2025, 12, 27)
    assert view(conn, "bhd:credit_card").statements[-1].period_start is None


def test_statements_newest_first_and_capped_at_twelve(conn) -> None:
    for month in range(1, 14):
        year, mon = (2024, month) if month <= 12 else (2025, 1)
        add_statement(conn, "bhd:credit_card", f"{year}-{mon:02d}-26")
    ends = [s.period_end for s in view(conn, "bhd:credit_card").statements]
    assert ends == sorted(ends, reverse=True)
    assert len(set(ends)) == 12


def test_missing_statement_flag(conn) -> None:
    through = date(2026, 1, 26)
    assert view(conn, "bhd:credit_card", through + timedelta(days=36)).missing_statement
    assert not view(conn, "bhd:credit_card", through + timedelta(days=35)).missing_statement


def test_inactive_account_is_not_flagged_as_missing(conn) -> None:
    # La cuenta de ahorro cerró hace más de ACTIVE_DAYS respecto al corte más nuevo de todas.
    savings = next(v for v in accounts.account_views(conn, TODAY) if v.kind == "savings")
    newest_other = max(
        v.latest[0].period_end for v in accounts.account_views(conn, TODAY) if v.latest
    )
    add_statement(conn, "bhd:credit_card", (newest_other + timedelta(days=46)).isoformat())
    late = date(2027, 1, 1)
    assert not view(conn, savings.key, late).missing_statement
    assert view(conn, "bhd:credit_card", late).missing_statement


def test_savings_account_has_no_payment_verdict(conn) -> None:
    key = next(v.key for v in accounts.account_views(conn, TODAY) if v.kind == "savings")
    add_statement(conn, key, "2026-02-28", closing=100_000)
    add_statement(conn, key, "2026-03-28", closing=200_000)
    add_statement(conn, key, "2026-04-28", closing=300)
    lines = view(conn, key).statements
    assert len(lines) >= 4
    for line in lines:
        assert (line.paid_full, line.paid_late, line.left_over) == (None, False, None)
        assert line.next_interest == Decimal(0)


def test_savings_account_listed_after_cards(conn) -> None:
    views = accounts.account_views(conn, TODAY)
    kinds = [v.kind for v in views]
    assert kinds == sorted(kinds, key=lambda k: k != "credit_card")
    assert views[-1].kind == "savings"
    assert views[-1].latest[0].balance == Decimal("12000.50")


def test_account_without_statements(conn) -> None:
    with conn:
        conn.execute(
            "INSERT INTO accounts (key, institution, kind, name) VALUES ('x', 'x', 'savings', 'V')"
        )
    empty = view(conn, "x")
    assert empty.cut_day is None and empty.latest == [] and empty.statements == []
    assert empty.currencies == [] and not empty.missing_statement


def _chain(conn, closing, payment=0, interest_cents=0):
    """Estado (corte 2026-02-26) con saldo `closing` y el siguiente con pagos/intereses."""
    add_statement(conn, "bhd:credit_card", "2026-02-26", closing=closing)
    second = add_statement(conn, "bhd:credit_card", "2026-03-26", closing=500)
    if payment:
        add_payment(conn, second, payment)
    if interest_cents:
        add_interest(conn, second, interest_cents)
    return second


def _line_for(conn, period_end, currency="DOP"):
    return next(
        x
        for x in view(conn, "bhd:credit_card").statements
        if x.period_end == period_end and x.currency == currency
    )


FIRST_CUT = date(2026, 2, 26)


def test_paid_full_and_left_over(conn) -> None:
    _chain(conn, closing=100_000, payment=100_000)
    full = _line_for(conn, FIRST_CUT)
    assert (full.paid_full, full.left_over, full.next_interest) == (True, None, Decimal(0))

    other = _chain_second_only(conn)
    add_payment(conn, other, 40_000)
    add_interest(conn, other, 3_500)
    partial = _line_for(conn, date(2026, 4, 26))
    assert partial.paid_full is False
    assert partial.left_over == Decimal("600.00")
    assert partial.next_interest == Decimal("35.00")


def test_late_payment_is_not_on_time(conn) -> None:
    first = add_statement(conn, "bhd:credit_card", "2026-02-26", closing=100_000, due="2026-03-18")
    second = add_statement(conn, "bhd:credit_card", "2026-03-26", closing=500)
    add_payment(conn, second, 100_000, on="2026-03-25")  # después del 18 mar
    line = _line_for(conn, FIRST_CUT)
    assert (line.paid_full, line.paid_late, line.left_over) == (False, True, Decimal("1000.00"))
    add_payment(conn, second, 100_000, on="2026-03-18")  # el día límite cuenta
    line = _line_for(conn, FIRST_CUT)
    assert (line.paid_full, line.paid_late, line.left_over) == (True, False, None)
    assert first


def test_partial_payment_is_not_late(conn) -> None:
    add_statement(conn, "bhd:credit_card", "2026-02-26", closing=100_000, due="2026-03-18")
    second = add_statement(conn, "bhd:credit_card", "2026-03-26", closing=500)
    add_payment(conn, second, 40_000, on="2026-03-25")
    line = _line_for(conn, FIRST_CUT)
    assert (line.paid_full, line.paid_late) == (False, False)


def test_to_pay_only_for_credit_cards(conn) -> None:
    add_statement(conn, "bhd:credit_card", "2026-02-26", closing=100_000, due="2026-03-18")
    assert view(conn, "bhd:credit_card").to_pay is not None
    with conn:
        conn.execute("UPDATE accounts SET kind = 'loan' WHERE key = 'bhd:credit_card'")
    assert view(conn, "bhd:credit_card").to_pay is None


def _chain_second_only(conn):
    add_statement(conn, "bhd:credit_card", "2026-04-26", closing=100_000)
    return add_statement(conn, "bhd:credit_card", "2026-05-26", closing=500)


def test_latest_statement_has_no_verdict(conn) -> None:
    _chain(conn, closing=100_000)
    newest = _line_for(conn, date(2026, 3, 26))
    assert (newest.paid_full, newest.left_over, newest.next_interest) == (None, None, Decimal(0))
    unpaid = _line_for(conn, FIRST_CUT)
    assert unpaid.paid_full is False
    assert unpaid.left_over == Decimal("1000.00")


def test_zero_or_credit_balance_has_no_payment(conn) -> None:
    add_statement(conn, "bhd:credit_card", "2026-02-26", closing=0)
    add_statement(conn, "bhd:credit_card", "2026-03-26", closing=-5_000)
    add_statement(conn, "bhd:credit_card", "2026-04-26", closing=100)
    zero = _line_for(conn, FIRST_CUT)
    credit = _line_for(conn, date(2026, 3, 26))
    assert zero.paid_full is None and zero.left_over is None
    assert credit.paid_full is None and credit.left_over is None


def test_to_pay_per_currency_dop_first(conn) -> None:
    add_statement(
        conn,
        "bhd:credit_card",
        "2026-02-26",
        currency="USD",
        closing=12_345,
        due="2026-03-18",
        minimum=500,
    )
    add_statement(
        conn,
        "bhd:credit_card",
        "2026-02-26",
        currency="DOP",
        closing=250_000,
        due="2026-03-20",
        minimum=9_000,
    )
    due = view(conn, "bhd:credit_card").to_pay
    assert due is not None
    assert due.key == "bhd:credit_card"
    assert due.label == view(conn, "bhd:credit_card").label
    assert due.due_date == date(2026, 3, 18)  # la más temprana si las monedas difieren
    assert due.amounts == [("DOP", Decimal("2500.00")), ("USD", Decimal("123.45"))]
    assert due.minimums == [("DOP", Decimal("90.00")), ("USD", Decimal("5.00"))]


def test_to_pay_none_without_positive_balance_or_due_date(conn) -> None:
    add_statement(conn, "bhd:credit_card", "2026-02-26", closing=0, due="2026-03-20")
    assert view(conn, "bhd:credit_card").to_pay is None
    add_statement(conn, "bhd:credit_card", "2026-03-26", closing=1000, due=None)
    assert view(conn, "bhd:credit_card").to_pay is None


def _upcoming(conn, today, dues):
    for key, due in dues.items():
        add_statement(conn, key, "2026-02-26", closing=1000, due=due)
    return accounts.upcoming_payments(accounts.account_views(conn, today), today)


def test_upcoming_window_bounds(conn) -> None:
    today = date(2026, 3, 10)
    edge = (today + timedelta(days=accounts.DUE_WINDOW_DAYS)).isoformat()
    got = _upcoming(
        conn, today, {"bhd:credit_card": edge, "popular:credit_card": today.isoformat()}
    )
    assert accounts.DUE_WINDOW_DAYS == 8
    assert [p.due_date for p in got] == [today, today + timedelta(days=8)]
    assert [p.key for p in got] == ["popular:credit_card", "bhd:credit_card"]


@pytest.mark.parametrize("offset", [9, -1])
def test_upcoming_excludes_outside_window(conn, offset) -> None:
    today = date(2026, 3, 10)
    due = (today + timedelta(days=offset)).isoformat()
    assert _upcoming(conn, today, {"bhd:credit_card": due}) == []


def test_upcoming_excludes_missing_due_date(conn) -> None:
    assert _upcoming(conn, date(2026, 3, 10), {"bhd:credit_card": None}) == []
