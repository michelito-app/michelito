"""Loans as stored (`analysis.loan_store`, schemas 26 and 27), made-up values."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db, migrations_v26, migrations_v27
from michelito.analysis import loan_store as store
from michelito.analysis.links import LinkError
from michelito.analysis.loan_schedule import StatementLine
from michelito.analysis.spending import Movement

NOW = "2026-05-20T12:00:00+00:00"
NUMBER = "1234567890"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


def pay(fingerprint: str, day: date, amount: str = "8884.88", **extra: object) -> Movement:
    fields: dict = {
        "day": day,
        "merchant": "AUT PAGO",
        "description": f"AUT PAGO {NUMBER} 101-00001 5555555555",
        "category": "Loans",
        "amount": Decimal(amount),
        "currency": "DOP",
        "institution": "bank",
        "fingerprint": fingerprint,
        "account": "bank:savings:1",
    }
    fields.update(extra)
    return Movement(**fields)


FLOW = [
    pay("a", date(2026, 2, 15)),
    pay("b", date(2026, 3, 15), account="other:savings:2"),
    pay("c", date(2026, 3, 18), amount="1000.00"),
    pay("x", date(2026, 3, 16), description="CLARO PAGO 1234567890"),  # mentions it too
    pay("y", date(2026, 3, 16), description="AUT PAGO 9999999999 101-00001"),
    pay("z", date(2026, 3, 16), currency="USD"),
    pay("p", date(2026, 3, 16), provisional=True),
]


def create(conn: sqlite3.Connection, number: str = NUMBER) -> int:
    with conn:
        return store.create(
            conn,
            name="Car loan",
            number=number,
            currency="DOP",
            principal_cents=10_000_000,
            rate_bp=1200,
            term=12,
            start=date(2026, 1, 15),
            now=NOW,
        )


def test_the_schema_has_the_loan_tables(conn: sqlite3.Connection) -> None:
    assert db.SCHEMA_VERSION == migrations_v27.VERSION > migrations_v26.VERSION
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "loans",
        "loan_rates",
        "loan_balances",
        "loan_links",
        "loan_statement_lines",
        "loan_installments",
    } <= tables


def test_a_new_loan_keeps_its_contract_and_its_starting_rate(conn: sqlite3.Connection) -> None:
    loan_id = create(conn, number=" 00-1234567890 ")

    (loan,) = store.load(conn)

    assert loan.id == loan_id
    assert loan.number == "001234567890"  # kept as typed; matched without its zeros
    assert loan.contract.principal == Decimal("100000.00")
    assert loan.contract.term == 12
    assert [(r.effective, r.annual) for r in loan.rates] == [(date(2026, 1, 15), Decimal("12"))]


def test_two_loans_cannot_share_a_number(conn: sqlite3.Connection) -> None:
    create(conn)
    with pytest.raises(LinkError):
        create(conn, number="1234567890")


def test_a_number_too_short_is_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(LinkError):
        create(conn, number="12")


def test_reconcile_links_every_payment_with_the_number_from_any_account(
    conn: sqlite3.Connection,
) -> None:
    loan_id = create(conn)

    with conn:
        linked = store.reconcile(conn, FLOW, NOW)

    assert linked == 4
    assert set(store.plan(conn, loan_id).links) == {"a", "b", "c", "x"}


def test_an_unlinked_payment_is_not_linked_again(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    with conn:
        store.reconcile(conn, FLOW, NOW)
        store.unlink(conn, loan_id, "x", NOW)
        store.reconcile(conn, FLOW, NOW)

    assert "x" not in store.plan(conn, loan_id).links


def test_a_payment_can_be_linked_by_hand(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    with conn:
        store.unlink(conn, loan_id, "y", NOW)  # refused before, linked by hand after
        store.link(conn, loan_id, FLOW[4], NOW)

    assert store.plan(conn, loan_id).links == {"y": "confirmed"}


def test_a_hand_link_refuses_another_loans_payment_or_another_currency(
    conn: sqlite3.Connection,
) -> None:
    first = create(conn)
    second = create(conn, number="9999999999")
    with conn:
        store.reconcile(conn, FLOW, NOW)

    with pytest.raises(LinkError):
        store.link(conn, first, FLOW[4], NOW)  # it is the second loan's
    with pytest.raises(LinkError):
        store.link(conn, second, FLOW[5], NOW)  # US$ for a RD$ loan


def test_rates_balances_and_statement_lines_are_kept(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    line = StatementLine(date(2026, 2, 15), Decimal("7000"), Decimal("1100"), Decimal("93000"))
    with conn:
        store.set_rate(conn, loan_id, date(2026, 7, 1), 1800)
        store.set_balance(conn, loan_id, date(2026, 4, 20), 5_000_000)
        added = store.add_statement_lines(conn, loan_id, [line, line], "test", NOW)

    loan = store.plan(conn, loan_id)
    assert added == 1  # the same line twice is stored once
    assert [r.annual for r in loan.rates] == [Decimal("12"), Decimal("18")]
    assert [(a.day, a.balance) for a in loan.anchors] == [(date(2026, 4, 20), Decimal("50000"))]
    assert loan.statement_lines == (line,)


def test_the_starting_rate_cannot_be_removed(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    with pytest.raises(LinkError):
        store.delete_rate(conn, loan_id, date(2026, 1, 15))


def test_editing_the_number_relinks_from_scratch(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    with conn:
        store.reconcile(conn, FLOW, NOW)
        store.update(conn, loan_id, NOW, number="9999999999")
        store.reconcile(conn, FLOW, NOW)

    assert set(store.plan(conn, loan_id).links) == {"y"}


def test_deleting_a_loan_leaves_the_payments_as_they_are(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    with conn:
        store.reconcile(conn, FLOW, NOW)
        store.delete(conn, loan_id)

    assert store.load(conn) == []
    assert store.taken(conn) == {}


def test_moving_the_start_past_a_rate_change_is_refused(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    with conn:
        store.set_rate(conn, loan_id, date(2026, 6, 1), 1500)

    with pytest.raises(LinkError):
        store.update(conn, loan_id, NOW, start=date(2026, 6, 1))
    with conn:
        store.update(conn, loan_id, NOW, start=date(2026, 2, 1))

    loan = store.plan(conn, loan_id)
    assert [(r.effective, r.annual) for r in loan.rates] == [
        (date(2026, 2, 1), Decimal("12")),
        (date(2026, 6, 1), Decimal("15")),
    ]


def test_the_banks_installment_is_kept_with_its_history(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    with conn:
        store.set_installment(conn, loan_id, date(2026, 1, 15), 900_000)
        store.set_installment(conn, loan_id, date(2026, 6, 1), 950_000)
        store.set_installment(conn, loan_id, date(2026, 6, 1), 960_000)  # replaces that day's

    loan = store.plan(conn, loan_id)
    assert [(i.effective, i.amount) for i in loan.installments] == [
        (date(2026, 1, 15), Decimal("9000")),
        (date(2026, 6, 1), Decimal("9600")),
    ]
    with conn:
        store.delete_installment(conn, loan_id, date(2026, 1, 15))
    assert [i.effective for i in store.plan(conn, loan_id).installments] == [date(2026, 6, 1)]


def test_a_bank_installment_must_be_positive(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    with pytest.raises(LinkError):
        store.set_installment(conn, loan_id, date(2026, 1, 15), 0)


def test_a_new_loan_can_start_with_the_banks_installment(conn: sqlite3.Connection) -> None:
    with conn:
        loan_id = store.create(
            conn,
            name="Car loan",
            number=NUMBER,
            currency="DOP",
            principal_cents=10_000_000,
            rate_bp=1200,
            term=12,
            start=date(2026, 1, 15),
            now=NOW,
            installment_cents=900_000,
        )

    (found,) = store.plan(conn, loan_id).installments
    assert (found.effective, found.amount) == (date(2026, 1, 15), Decimal("9000"))


def test_moving_the_start_moves_the_installment_from_the_start(conn: sqlite3.Connection) -> None:
    loan_id = create(conn)
    with conn:
        store.set_installment(conn, loan_id, date(2026, 1, 15), 900_000)
        store.update(conn, loan_id, NOW, start=date(2026, 2, 1))

    (found,) = store.plan(conn, loan_id).installments
    assert found.effective == date(2026, 2, 1)
