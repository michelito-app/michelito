"""Popular "history" statements: several monthly statements in a row in a single PDF."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db, report
from michelito.analysis import categories, spending
from michelito.ingest import process_documents
from michelito.parsers import detect, popular_account, popular_history, popular_web
from michelito.parsers.common import Page, ParseError, count_notes, validate_statement
from tests import samples
from tests.helpers import store
from tests.test_ingest import add_document

CHECKING = "popular:checking:123456789"
SAVINGS = "popular:savings:987654321"

PAGES: dict[str, tuple[Page, ...]] = {
    "history.pdf": samples.POPULAR_HISTORICO,
    "history_copy.pdf": samples.POPULAR_HISTORICO,
    "history_bad.pdf": samples.POPULAR_HISTORICO_BAD_DIC,
    "history_usd.pdf": samples.POPULAR_HISTORICO_USD,
    "history_digital.pdf": samples.POPULAR_HISTORICO_DIGITAL,
    "history_spaces.pdf": samples.POPULAR_HISTORICO_BROKEN_SPACES,
    "history_usd_note.pdf": (
        *samples.POPULAR_HISTORICO_USD,
        samples.page(),
        *samples.POPULAR_HISTORICO_USD_SHORT_COUNT,
    ),
}


def reader(path: Path, password: str) -> tuple[Page, ...]:
    return PAGES[path.name]


@pytest.fixture
def conn():
    with closing(db.connect(":memory:")) as connection:
        yield connection


def run(conn: sqlite3.Connection, retry: bool = False):
    return process_documents(conn, "password", reader, retry=retry)


def store_parsed(conn: sqlite3.Connection, statement) -> None:
    """Store an already parsed statement and mark its document as parsed."""
    store(conn, statement)
    with conn:
        conn.execute("UPDATE documents SET status = 'parsed' WHERE status = 'pending'")


def parts(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return [
        (row[0], row[1])
        for row in conn.execute("SELECT label, status FROM document_parts ORDER BY part")
    ]


def document(conn: sqlite3.Connection, filename: str) -> tuple[str, str]:
    row = conn.execute(
        "SELECT status, detail FROM documents WHERE filename = ?", (filename,)
    ).fetchone()
    return row[0], row[1]


def cuts(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        "SELECT s.document_id, a.key, s.period_end FROM statements s "
        "JOIN accounts a ON a.id = s.account_id ORDER BY s.period_end"
    )
    return [tuple(row) for row in rows]


class TestParser:
    def test_detects_the_format_and_not_the_others(self) -> None:
        for pages in (
            samples.POPULAR_HISTORICO,
            samples.POPULAR_HISTORICO_USD,
            samples.POPULAR_HISTORICO_DIGITAL,
        ):
            assert detect(pages) is popular_history
        assert not popular_account.matches(samples.HISTORICO_NOV)
        for other in (
            samples.POPULAR_CUENTA_DOP,
            samples.POPULAR_CUENTA_USD,
            samples.POPULAR_PAGES,
            samples.POPULAR_WEB,
            samples.BANRESERVAS,
            samples.BHD_AHORRO_PAGES,
        ):
            assert not popular_history.matches(other)

    def test_split_starts_at_each_first_page_and_drops_blank_pages(self) -> None:
        split = popular_history.split(samples.POPULAR_HISTORICO)
        assert split == (samples.HISTORICO_NOV, samples.HISTORICO_DIC, samples.HISTORICO_ENE)

    def test_statement_with_two_pages(self) -> None:
        statement = popular_history.parse(samples.HISTORICO_NOV)
        assert (statement.kind, statement.product, statement.identifier) == (
            "checking",
            "Nómina",  # spanish-data
            "123456789",
        )
        assert (statement.period_start, statement.period_end) == (
            date(2025, 10, 10),
            date(2025, 11, 12),
        )
        (section,) = statement.sections
        rows = [
            (t.posted_on, t.transacted_on, t.direction, t.amount, t.balance, t.description)
            for t in section.transactions
        ]
        assert rows == [
            (date(2025, 10, 14), date(2025, 10, 14), "credit", Decimal("43275.81"),
             Decimal("95894.18"), "PAGO DE NOMINAS EMPRESA INVENTADA"),
            (date(2025, 10, 14), date(2025, 10, 14), "debit", Decimal("60000.00"),
             Decimal("35894.18"), "MB a 000000001 PERSONA INVENTADA"),
            (date(2025, 10, 17), date(2025, 10, 17), "debit", Decimal("180.00"),
             Decimal("35714.18"),
             # spanish-data: begin
             "PAGO IMPUESTO 0.15% DGII 3 TRANS POR $ 120,000.00 Del 06/10/2025 Al 12/10/2025"),
             # spanish-data: end
            (date(2025, 11, 3), date(2025, 11, 3), "debit", Decimal("5412.66"),
             Decimal("30301.52"), "AUT PAGO 850000000 008-00000"),
            (date(2025, 11, 10), date(2025, 11, 8), "credit", Decimal("100000.00"),
             Decimal("130301.52"), "DEPOSITO INVENTADO"),
        ]  # fmt: skip
        assert (section.currency, section.previous_balance, section.closing_balance) == (
            "DOP",
            Decimal("52618.37"),
            Decimal("130301.52"),
        )
        assert (section.printed_credit_count, section.printed_debit_count) == (2, 3)
        assert validate_statement(statement) == ()

    def test_statement_without_movements(self) -> None:
        statement = popular_history.parse(samples.HISTORICO_DIC)
        assert statement.sections[0].transactions == ()
        assert statement.period_start == date(2025, 11, 13)
        assert validate_statement(statement) == ()

    def test_december_rows_of_a_january_statement_are_of_the_previous_year(self) -> None:
        statement = popular_history.parse(samples.HISTORICO_ENE)
        days = [t.transacted_on for t in statement.sections[0].transactions]
        assert days == [date(2025, 12, 19), date(2026, 1, 5), date(2026, 1, 11)]
        assert statement.period_start == date(2025, 12, 13)
        assert validate_statement(statement) == ()

    def test_dollar_savings_with_interest_paid(self) -> None:
        statement = popular_history.parse(samples.POPULAR_HISTORICO_USD)
        (section,) = statement.sections
        assert (statement.kind, statement.product, section.currency) == (
            "savings",
            "Ahorro US$ Pers",  # spanish-data
            "USD",
        )
        assert section.printed_credits == Decimal("500.12")  # deposits plus the interest
        assert section.printed_credit_count == 2
        assert section.transactions[-1].amount == Decimal("0.12")
        assert validate_statement(statement) == ()

    def test_digital_account_closing_at_zero(self) -> None:
        statement = popular_history.parse(samples.POPULAR_HISTORICO_DIGITAL)
        (section,) = statement.sections
        assert (statement.kind, statement.product) == ("checking", "Digital")
        assert section.closing_balance == Decimal("0")
        assert section.transactions[0].balance == Decimal("0")
        assert validate_statement(statement) == ()

    def test_a_row_count_that_does_not_match_is_a_note_not_a_problem(self) -> None:
        statement = popular_history.parse(samples.HISTORICO_NOV)
        section = replace(statement.sections[0], printed_debit_count=4)
        changed = replace(statement, sections=(section,))
        assert validate_statement(changed) == ()
        assert count_notes(changed) == ("DOP: débitos: 3 filas ≠ 4 impresas",)  # spanish-ui
        assert count_notes(statement) == ()

    def test_a_month_with_interest_and_one_debit_less_in_the_count_balances(self) -> None:
        statement = popular_history.parse(samples.POPULAR_HISTORICO_USD_SHORT_COUNT)
        assert validate_statement(statement) == ()
        assert count_notes(statement) == ("USD: débitos: 2 filas ≠ 1 impresas",)  # spanish-ui

    def test_a_statement_that_does_not_balance_is_reported(self) -> None:
        _, bad, _ = popular_history.split(samples.POPULAR_HISTORICO_BAD_DIC)
        problems = validate_statement(popular_history.parse(bad))
        assert len(problems) == 1 and "140000.00" in problems[0]


class TestIngest:
    def test_each_statement_is_its_own_cut_of_the_same_document(self, conn) -> None:
        document_id = add_document(conn, "history.pdf")
        assert run(conn) == {"parsed": 1}
        assert cuts(conn) == [
            (document_id, CHECKING, "2025-11-12"),
            (document_id, CHECKING, "2025-12-12"),
            (document_id, CHECKING, "2026-01-12"),
        ]
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 8
        assert parts(conn) == [
            ("2025-11-12", "parsed"),
            ("2025-12-12", "parsed"),
            ("2026-01-12", "parsed"),
        ]
        assert document(conn, "history.pdf") == (
            "parsed",
            "3 de 3 estados guardados (8 transacciones)",  # spanish-ui
        )

    def test_a_statement_that_does_not_balance_does_not_stop_the_others(self, conn) -> None:
        add_document(conn, "history_bad.pdf")
        assert run(conn) == {"parsed": 1}
        assert [cut for _, _, cut in cuts(conn)] == ["2025-11-12", "2026-01-12"]
        assert parts(conn) == [
            ("2025-11-12", "parsed"),
            ("2025-12-12", "invalid"),
            ("2026-01-12", "parsed"),
        ]
        status, detail = document(conn, "history_bad.pdf")
        assert status == "parsed"
        assert detail.startswith(
            "2 de 3 estados guardados (8 transacciones); 2025-12-12 invalid:"  # spanish-ui
        )
        assert "140000.00" in detail
        alerts = report.build_report(conn, date(2026, 1, 20), commit_from=date(2025, 1, 1)).alerts
        assert any("part 2025-12-12" in alert and "invalid" in alert for alert in alerts)

    def test_retry_stores_the_fixed_statement_without_duplicating_the_others(self, conn) -> None:
        add_document(conn, "history_bad.pdf")
        run(conn)
        assert run(conn) == {}  # without --retry it is not touched again
        PAGES["history_bad.pdf"] = samples.POPULAR_HISTORICO  # "the parser was fixed"
        try:
            assert run(conn, retry=True) == {"parsed": 1}
        finally:
            PAGES["history_bad.pdf"] = samples.POPULAR_HISTORICO_BAD_DIC
        assert [cut for _, _, cut in cuts(conn)] == ["2025-11-12", "2025-12-12", "2026-01-12"]
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 8
        assert [status for _, status in parts(conn)] == ["parsed"] * 3
        assert run(conn, retry=True) == {}  # nothing left to retry

    def test_the_same_statements_from_another_file_are_duplicates(self, conn) -> None:
        add_document(conn, "history.pdf")
        add_document(conn, "history_copy.pdf")
        assert run(conn) == {"parsed": 1, "duplicate": 1}
        assert len(cuts(conn)) == 3
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 8
        status, detail = document(conn, "history_copy.pdf")
        assert status == "duplicate"
        assert "repetidos: 2025-11-12, 2025-12-12, 2026-01-12" in detail  # spanish-ui

    def test_a_cut_already_stored_from_a_monthly_statement_is_a_duplicate_part(self, conn) -> None:
        # The December cut was already there (e.g. it arrived by email).
        store_parsed(conn, popular_history.parse(samples.HISTORICO_DIC))
        add_document(conn, "history.pdf")
        assert run(conn) == {"parsed": 1}
        assert parts(conn)[1] == ("2025-12-12", "duplicate")
        assert len(cuts(conn)) == 3

    def test_accounts_land_on_the_existing_keys(self, conn) -> None:
        store_parsed(conn, popular_account.parse(samples.POPULAR_CUENTA_DOP))
        store_parsed(conn, popular_account.parse(samples.POPULAR_CUENTA_USD))
        before = [tuple(r) for r in conn.execute("SELECT key, kind FROM accounts ORDER BY key")]
        assert before == [(CHECKING, "checking"), (SAVINGS, "savings")]
        add_document(conn, "history.pdf")
        add_document(conn, "history_usd.pdf")
        assert run(conn) == {"parsed": 2}
        after = [tuple(r) for r in conn.execute("SELECT key, kind FROM accounts ORDER BY key")]
        assert after == before
        currencies = conn.execute(
            "SELECT DISTINCT s.currency FROM statements s JOIN accounts a ON a.id = s.account_id "
            "WHERE a.key = ? AND s.parser = 'popular_history'",
            (SAVINGS,),
        ).fetchall()
        assert [tuple(r) for r in currencies] == [("USD",)]

    def test_a_count_difference_enters_with_a_note(self, conn) -> None:
        add_document(conn, "history_usd_note.pdf")
        assert run(conn) == {"parsed": 1}
        assert [cut for _, _, cut in cuts(conn)] == ["2025-09-30", "2025-10-31"]
        notes = conn.execute("SELECT label, status, note FROM document_parts ORDER BY part")
        assert [tuple(r) for r in notes] == [
            ("2025-09-30", "parsed", None),
            ("2025-10-31", "parsed", "USD: débitos: 2 filas ≠ 1 impresas"),  # spanish-ui
        ]
        status, detail = document(conn, "history_usd_note.pdf")
        assert status == "parsed"
        assert detail == (
            "2 de 2 estados guardados (7 transacciones); "  # spanish-ui
            "2025-10-31 nota: USD: débitos: 2 filas ≠ 1 impresas"  # spanish-ui
        )
        assert db.failed_parts(conn, 1) == 0
        built = report.build_report(conn, date(2025, 11, 5), commit_from=date(2025, 1, 1))
        line = (
            "  history_usd_note.pdf (part 2025-10-31): "
            "USD: débitos: 2 filas ≠ 1 impresas"  # spanish-ui
        )
        assert line in built.lines
        assert not any("history_usd_note" in alert for alert in built.alerts)

    def test_broken_spaces_become_a_single_space(self) -> None:
        statement = popular_history.parse(samples.POPULAR_HISTORICO_BROKEN_SPACES)
        (movement,) = statement.sections[0].transactions
        assert movement.description == samples.HISTORICO_BROKEN_SPACES_DESCRIPTION
        assert validate_statement(statement) == ()
        # A hard space inside a word of the PDF (the generator cannot put it there).
        assert popular_history._clean("FULANO DE  TAL ") == "FULANO DE TAL"

    def test_a_transfer_to_the_holder_with_broken_spaces_is_own(self, conn) -> None:
        add_document(conn, "history_spaces.pdf")
        assert run(conn) == {"parsed": 1}
        (movement,) = [
            m
            for m in spending.load_all(conn, ("FULANO DE TAL",))
            if m.description == samples.HISTORICO_BROKEN_SPACES_DESCRIPTION
        ]
        assert (movement.category, movement.kind) == (categories.OWN_TRANSFER, "transfer")

    def test_digital_account_is_a_checking_account(self, conn) -> None:
        add_document(conn, "history_digital.pdf")
        assert run(conn) == {"parsed": 1}
        account = conn.execute("SELECT key, name FROM accounts").fetchone()
        assert tuple(account) == ("popular:checking:555666777", "POPULAR Digital 555666777")


class TestOverlapWithPrintouts:
    def test_on_the_days_of_a_statement_only_the_statement_counts(self, conn) -> None:
        add_document(conn, "history.pdf")
        run(conn)
        store(conn, popular_web.parse(samples.POPULAR_WEB))  # from 12 to 20 January 2026
        movements = [m for m in spending.load_all(conn) if m.account == CHECKING]
        january = [(m.day.isoformat(), m.description) for m in movements if m.day.year == 2026]
        assert january == [
            ("2026-01-05", "MB desde 000000003 FULANO DE"),  # spanish-data
            ("2026-01-11", "MB desde 000000003 FULANO DE"),  # spanish-data: the statement
            ("2026-01-16", "PAGO TARJETA TIENDA FICTICIA S.R.L. SANTO DOMINGO"),
            ("2026-01-17", "DEPOSITO CHEQUE Y EFECTIVO"),
            (
                "2026-01-19",
                "IMPUESTO 0.15% DGII 1 TRANS POR $ 1,500.00 DEL 16/01/2026 AL 16/01/2026",
            ),
            ("2026-01-20", "TRANSFERENCIA RECIBIDA DE PERSONA INVENTADA"),
        ]


UNKNOWN_PRODUCT = samples.popular_history(
    *samples.HISTORICO_NOV_ROWS, account="CUENTA AHORRO 123456789 RD$ FULANO DE TAL"
)


@pytest.fixture(autouse=True)
def _restore_pages():
    """Tests may change the reader; put it back as it was."""
    before = dict(PAGES)
    yield
    PAGES.clear()
    PAGES.update(before)


class TestReview:
    def test_unknown_product_is_recognized_and_parse_explains(self) -> None:
        assert popular_history.matches(UNKNOWN_PRODUCT)  # does not raise
        with pytest.raises(ParseError, match="unknown account type"):
            popular_history.parse(UNKNOWN_PRODUCT)

    def test_unknown_product_does_not_stop_the_run(self, conn) -> None:
        PAGES["unknown.pdf"] = UNKNOWN_PRODUCT
        add_document(conn, "unknown.pdf")
        add_document(conn, "history.pdf")
        assert run(conn) == {"error": 1, "parsed": 1}
        status, detail = document(conn, "unknown.pdf")
        assert status == "error"
        assert "2025-11-12 error: ParseError: unknown account type" in detail
        assert len(cuts(conn)) == 3

    def test_a_failing_detection_marks_the_document_and_the_run_continues(
        self, conn, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(pages):
            raise ValueError("matches broken")

        monkeypatch.setattr(popular_account, "matches", explode)
        add_document(conn, "history.pdf")
        add_document(conn, "history_usd.pdf")
        assert run(conn) == {"error": 2}
        assert document(conn, "history.pdf") == (
            "error",
            "al reconocer el formato: ValueError: matches broken",  # spanish-ui
        )

    def test_a_failed_reread_keeps_the_stored_statements_parsed(self, conn) -> None:
        add_document(conn, "history_bad.pdf")
        run(conn)
        PAGES.pop("history_bad.pdf")  # the reader fails on retry
        assert run(conn, retry=True) == {"parsed": 1}
        status, detail = document(conn, "history_bad.pdf")
        assert status == "parsed"
        assert detail.startswith("2 de 3 estados guardados")  # spanish-ui
        assert "2025-12-12 invalid:" in detail
        assert "reintento: error: no se pudo leer el PDF: KeyError" in detail  # spanish-ui
        assert db.failed_parts(conn, 1) == 1
        alerts = report.build_report(conn, date(2026, 1, 20), commit_from=date(2025, 1, 1)).alerts
        assert any("part 2025-12-12" in alert for alert in alerts)
        PAGES["history_bad.pdf"] = samples.POPULAR_HISTORICO
        assert run(conn, retry=True) == {"parsed": 1}
        retry_detail = "reintento"  # spanish-ui
        assert retry_detail not in document(conn, "history_bad.pdf")[1]

    def test_pages_with_text_before_the_first_page_one_are_a_failed_part(self, conn) -> None:
        cover = samples.page("PORTADA INVENTADA", "ESTADOS DE CUENTA")
        pages = (cover, *samples.HISTORICO_NOV)
        assert popular_history.split(pages) == ((cover,), samples.HISTORICO_NOV)
        PAGES["cover.pdf"] = pages
        add_document(conn, "cover.pdf")
        assert run(conn) == {"parsed": 1}
        assert parts(conn) == [("estado 1", "error"), ("2025-11-12", "parsed")]  # spanish-ui
        assert db.failed_parts(conn, 1) == 1

    @pytest.mark.parametrize("page_format", ["PAG{}", "PAG {} DE 2"])
    def test_other_ways_of_printing_the_page_number(self, page_format: str) -> None:
        pages = samples.popular_history(*samples.HISTORICO_NOV_ROWS, page_format=page_format)
        assert popular_history.matches(pages)
        (part,) = popular_history.split((samples.page(), *pages))
        assert len(part) == 2
        assert validate_statement(popular_history.parse(part)) == ()

    def test_a_stored_part_that_no_longer_balances_stays_stored(self, conn) -> None:
        add_document(conn, "history_bad.pdf")
        run(conn)  # November and January go in; December does not balance
        bad_nov = samples.popular_history(*samples.HISTORICO_NOV_ROWS, closing="1.00")
        PAGES["history_bad.pdf"] = (*bad_nov, *samples.HISTORICO_DIC, *samples.HISTORICO_ENE)
        assert run(conn, retry=True) == {"parsed": 1}
        assert parts(conn) == [
            ("2025-11-12", "parsed"),
            ("2025-12-12", "parsed"),
            ("2026-01-12", "parsed"),
        ]
        assert document(conn, "history_bad.pdf")[1].startswith(
            "3 de 3 estados guardados"  # spanish-ui
        )

    def test_a_footer_right_of_the_dates_is_not_part_of_the_description(self) -> None:
        pages = samples.popular_history(
            *samples.HISTORICO_NOV_ROWS, footer=(60, "AVISO INVENTADO AL PIE")
        )
        expected = popular_history.parse(samples.HISTORICO_NOV).sections[0].transactions
        found = popular_history.parse(pages).sections[0].transactions
        assert [t.description for t in found] == [t.description for t in expected]

    def test_a_zero_debit_is_a_debit(self) -> None:
        pages = samples.popular_history(
            (
                ("15 OCT", "15 OCT", "", "1,500.00-", ("MB a 000000009 PERSONA INVENTADA",)),
                ("16 OCT", "16 OCT", "", ".00-", ("COMISION INVENTADA",)),
            ),
            account="CUENTA DIGITAL 555666777 RD$ FULANO DE TAL",
            opening="1,500.00",
        )
        statement = popular_history.parse(pages)
        zero = statement.sections[0].transactions[1]
        assert (zero.amount, zero.direction) == (Decimal("0"), "debit")
        assert validate_statement(statement) == ()
        assert count_notes(statement) == ()
