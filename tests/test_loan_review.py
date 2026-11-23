"""What a loan sends to review (`analysis.loan_review`) and the statement hook
(`analysis.loan_statements`), made-up values."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import loan_statements, loan_store
from michelito.analysis.links import LinkError
from michelito.analysis.loan_review import Payment, differences
from michelito.analysis.loan_schedule import Contract, Rate, StatementLine

CONTRACT = Contract(Decimal("100000.00"), 12, date(2026, 1, 15))
RATES = (Rate(CONTRACT.start, Decimal("12")),)
ON_SCRIPT = StatementLine(
    date(2026, 2, 15), Decimal("7884.88"), Decimal("1000.00"), Decimal("92115.12")
)


def test_nothing_to_review_without_statements() -> None:
    paid = [Payment("a", date(2026, 2, 15), Decimal("1"))]

    assert differences(CONTRACT, RATES, (), (), paid) == []


def test_a_statement_that_matches_contract_and_payments_is_quiet() -> None:
    paid = [Payment("a", date(2026, 2, 15), Decimal("8884.88"))]

    assert differences(CONTRACT, RATES, (), (ON_SCRIPT,), paid) == []


def test_payments_that_do_not_add_up_to_the_statement_are_reviewed() -> None:
    paid = [
        Payment("a", date(2026, 2, 3), Decimal("5000.00")),
        Payment("b", date(2026, 2, 20), Decimal("2000.00")),
    ]

    (found,) = differences(CONTRACT, RATES, (), (ON_SCRIPT,), paid)

    assert found.kind == "payments"
    assert found.month == "2026-02"
    assert found.expected == Decimal("8884.88")
    assert found.found == Decimal("7000.00")
    assert found.fingerprints == ("a", "b")


def test_a_balance_far_from_the_contract_is_reviewed() -> None:
    line = StatementLine(date(2026, 2, 15), Decimal("1000"), Decimal("1000"), Decimal("99000"))
    paid = [Payment("a", date(2026, 2, 15), Decimal("2000"))]

    (found,) = differences(CONTRACT, RATES, (), (line,), paid)

    assert found.kind == "contract"
    assert found.expected == Decimal("92115.12")
    assert found.found == Decimal("99000")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


def test_an_imported_statement_goes_to_the_loan_with_its_number(conn: sqlite3.Connection) -> None:
    with conn:
        loan_id = loan_store.create(
            conn,
            name="Car loan",
            number="1234567890",
            currency="DOP",
            principal_cents=10_000_000,
            rate_bp=1200,
            term=12,
            start=CONTRACT.start,
            now="2026-05-20T12:00:00+00:00",
        )
    statement = loan_statements.LoanStatement(number="001234567890", lines=(ON_SCRIPT,))

    with conn:
        found = loan_statements.store(conn, statement, "test-doc", "2026-05-20T12:00:00+00:00")

    assert found == (loan_id, 1)
    assert loan_store.plan(conn, loan_id).statement_lines == (ON_SCRIPT,)


def test_a_statement_of_an_unknown_loan_is_refused(conn: sqlite3.Connection) -> None:
    statement = loan_statements.LoanStatement(number="5555555555", lines=(ON_SCRIPT,))

    with pytest.raises(LinkError):
        loan_statements.store(conn, statement, None, "2026-05-20T12:00:00+00:00")


def test_no_loan_statement_parser_is_registered_yet() -> None:
    # The format is learned from a real sample first (see the module docstring).
    assert loan_statements.parser_for([["anything"]]) is None
