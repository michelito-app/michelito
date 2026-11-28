"""Popular's loan history (`parsers.popular_loan`): parsing, and how a document with one reaches
its loan through the ingestion. Made-up values."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import loan_statements, loan_store
from michelito.analysis.loan_schedule import StatementLine
from michelito.ingest import process_documents
from michelito.parsers import detect, popular_loan
from michelito.parsers.common import Page, ParseError
from tests import samples
from tests.test_ingest import add_document, status_of

NUMBER = "1234567"
PAGES: dict[str, tuple[Page, ...]] = {
    "loan.pdf": samples.POPULAR_LOAN_HISTORY,
    "loan_again.pdf": samples.POPULAR_LOAN_HISTORY,
    "loan_bad.pdf": samples.POPULAR_LOAN_HISTORY_WRONG_BALANCE,
    "unknown.pdf": (samples.UNKNOWN,),
}


def reader(path: Path, password: str) -> tuple[Page, ...]:
    return PAGES[path.name]


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


def create_loan(conn: sqlite3.Connection, number: str = NUMBER) -> int:
    with conn:
        return loan_store.create(
            conn,
            name="Car loan",
            number=number,
            currency="DOP",
            principal_cents=12_000_000,
            rate_bp=1200,
            term=12,
            start=date(2025, 3, 5),
            now="2025-07-15T12:00:00+00:00",
        )


def test_recognizes_the_loan_history_and_no_account_parser_does() -> None:
    pages = samples.POPULAR_LOAN_HISTORY

    assert popular_loan.matches(pages)
    assert loan_statements.parser_for(pages) is popular_loan
    assert detect(pages) is None


def test_does_not_recognize_other_documents() -> None:
    assert not popular_loan.matches((samples.UNKNOWN,))
    assert not popular_loan.matches(samples.POPULAR_PAGES)
    assert loan_statements.parser_for((samples.UNKNOWN,)) is None


def test_reads_the_number_and_one_line_per_day_of_payments() -> None:
    statement = popular_loan.parse(samples.POPULAR_LOAN_HISTORY)

    assert statement.number == NUMBER
    assert statement.lines == (
        # Two charges on the disbursement day that pay no principal: fees, not interest.
        StatementLine(
            date(2025, 3, 5), Decimal(0), Decimal(0), Decimal("120000.00"), Decimal("2000.00")
        ),
        StatementLine(
            date(2025, 4, 7), Decimal("10000.00"), Decimal("1200.00"), Decimal("110000.00")
        ),
        StatementLine(
            date(2025, 5, 5), Decimal("10000.00"), Decimal("1100.00"), Decimal("100000.00")
        ),
        # Two partial payments on the same day are one line.
        StatementLine(
            date(2025, 6, 9), Decimal("10050.00"), Decimal("950.00"), Decimal("89950.00")
        ),
        StatementLine(
            date(2025, 6, 10), Decimal(0), Decimal(0), Decimal("89950.00"), Decimal("300.00")
        ),
    )


def test_what_was_paid_is_principal_plus_interest_plus_other() -> None:
    statement = popular_loan.parse(samples.POPULAR_LOAN_HISTORY)

    paid = sum((line.principal + line.interest + line.other for line in statement.lines), 0)

    assert paid == Decimal("35600.00")


def test_a_printed_balance_that_the_payments_do_not_reach_is_refused() -> None:
    with pytest.raises(ParseError, match="printed principal balance"):
        popular_loan.parse(samples.POPULAR_LOAN_HISTORY_WRONG_BALANCE)


def test_a_payment_smaller_than_the_principal_it_pays_is_refused() -> None:
    with pytest.raises(ParseError, match="row 2"):
        popular_loan.parse(samples.POPULAR_LOAN_HISTORY_BROKEN_CHAIN)


def test_an_unknown_movement_is_refused() -> None:
    with pytest.raises(ParseError, match="row 2"):
        popular_loan.parse(samples.POPULAR_LOAN_HISTORY_UNKNOWN_ROW)


def test_a_history_without_payments_is_refused() -> None:
    pages = samples.popular_loan_history(
        ("         5-May-25    DESEMBOLSO SIEBEL     50,000.00       50,000.00",),
        capital="50,000.00",
    )

    with pytest.raises(ParseError, match="no payments"):
        popular_loan.parse(pages)


def test_month_names_in_spanish_are_read_too() -> None:
    pages = samples.popular_loan_history(
        (
            "         5-Dic-25    DESEMBOLSO SIEBEL     50,000.00       50,000.00",
            "         5-Ene-26    PAGO                   5,500.00       45,000.00",
        ),
        capital="45,000.00",
    )

    (line,) = popular_loan.parse(pages).lines

    assert line.day == date(2026, 1, 5)


def test_a_document_with_a_loan_history_goes_to_its_loan(conn: sqlite3.Connection) -> None:
    loan_id = create_loan(conn)
    add_document(conn, "loan.pdf")

    outcome = process_documents(conn, "", reader)

    assert outcome == {"parsed": 1}
    assert status_of(conn, "loan.pdf") == ("parsed", "5 pagos del préstamo")  # spanish-data
    assert len(loan_store.plan(conn, loan_id).statement_lines) == 5
    assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0


def test_the_same_history_again_is_a_duplicate(conn: sqlite3.Connection) -> None:
    loan_id = create_loan(conn)
    add_document(conn, "loan.pdf")
    process_documents(conn, "", reader)
    add_document(conn, "loan_again.pdf")

    outcome = process_documents(conn, "", reader)

    assert outcome == {"duplicate": 1}
    assert len(loan_store.plan(conn, loan_id).statement_lines) == 5


def test_a_history_of_an_unknown_loan_is_an_error_until_the_loan_exists(
    conn: sqlite3.Connection,
) -> None:
    add_document(conn, "loan.pdf")

    assert process_documents(conn, "", reader) == {"error": 1}
    assert conn.execute("SELECT COUNT(*) FROM loan_statement_lines").fetchone()[0] == 0

    create_loan(conn)

    assert process_documents(conn, "", reader, retry=True) == {"parsed": 1}


def test_a_history_that_does_not_square_stores_nothing(conn: sqlite3.Connection) -> None:
    create_loan(conn)
    add_document(conn, "loan_bad.pdf")

    assert process_documents(conn, "", reader) == {"error": 1}
    assert conn.execute("SELECT COUNT(*) FROM loan_statement_lines").fetchone()[0] == 0


def test_other_unknown_documents_stay_unsupported(conn: sqlite3.Connection) -> None:
    add_document(conn, "unknown.pdf")

    assert process_documents(conn, "", reader) == {"unsupported": 1}


DISBURSED = "         5-May-25    DESEMBOLSO SIEBEL     50,000.00       50,000.00"


def test_a_disbursement_after_the_last_payment_counts_for_the_printed_balance() -> None:
    pages = samples.popular_loan_history(
        (
            DISBURSED,
            "         5-Jun-25    PAGO                   1,000.00       49,500.00",
            "         9-Jun-25    DESEMBOLSO ADIC       10,000.00       59,500.00",
        ),
        capital="59,500.00",
    )

    (line,) = popular_loan.parse(pages).lines

    assert line.balance == Decimal("49500.00")


def test_a_negative_balance_is_refused() -> None:
    pages = samples.popular_loan_history(
        (DISBURSED, "         5-Jun-25    PAGO                  60,000.00      -10,000.00"),
        capital="-10,000.00",
    )

    with pytest.raises(ParseError, match="row 2"):
        popular_loan.parse(pages)


def test_dates_that_go_backwards_are_refused() -> None:
    pages = samples.popular_loan_history(
        (
            DISBURSED,
            "         9-Jun-25    PAGO                   1,500.00       49,000.00",
            "         3-Jun-25    PAGO                   1,500.00       48,000.00",
        ),
        capital="48,000.00",
    )

    with pytest.raises(ParseError, match="row 3"):
        popular_loan.parse(pages)


def test_a_history_the_database_refuses_is_an_error_and_the_run_goes_on(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object) -> tuple[int, int]:
        raise sqlite3.IntegrityError("CHECK constraint failed")

    create_loan(conn)
    add_document(conn, "loan.pdf")
    add_document(conn, "unknown.pdf")
    monkeypatch.setattr(loan_statements, "store", refuse)

    assert process_documents(conn, "", reader) == {"error": 1, "unsupported": 1}
