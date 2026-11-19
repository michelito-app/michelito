"""Estados «históricos» del Popular: varios estados mensuales seguidos en un solo PDF."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzas import db, report
from finanzas.analysis import categories, spending
from finanzas.ingest import process_documents
from finanzas.parsers import detect, popular_cuenta, popular_historico, popular_web
from finanzas.parsers.common import Page, ParseError, count_notes, validate_statement
from tests import samples
from tests.helpers import store
from tests.test_ingest import add_document

CHECKING = "popular:checking:123456789"
SAVINGS = "popular:savings:987654321"

PAGES: dict[str, tuple[Page, ...]] = {
    "historico.pdf": samples.POPULAR_HISTORICO,
    "historico_copia.pdf": samples.POPULAR_HISTORICO,
    "historico_malo.pdf": samples.POPULAR_HISTORICO_BAD_DIC,
    "historico_usd.pdf": samples.POPULAR_HISTORICO_USD,
    "historico_digital.pdf": samples.POPULAR_HISTORICO_DIGITAL,
    "historico_espacios.pdf": samples.POPULAR_HISTORICO_BROKEN_SPACES,
    "historico_usd_nota.pdf": (
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
    return process_documents(conn, "clave", reader, retry=retry)


def store_parsed(conn: sqlite3.Connection, statement) -> None:
    """Guarda un estado ya interpretado y deja su documento como interpretado."""
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
            assert detect(pages) is popular_historico
        assert not popular_cuenta.matches(samples.HISTORICO_NOV)
        for other in (
            samples.POPULAR_CUENTA_DOP,
            samples.POPULAR_CUENTA_USD,
            samples.POPULAR_PAGES,
            samples.POPULAR_WEB,
            samples.BANRESERVAS,
            samples.BHD_AHORRO_PAGES,
        ):
            assert not popular_historico.matches(other)

    def test_split_starts_at_each_first_page_and_drops_blank_pages(self) -> None:
        split = popular_historico.split(samples.POPULAR_HISTORICO)
        assert split == (samples.HISTORICO_NOV, samples.HISTORICO_DIC, samples.HISTORICO_ENE)

    def test_statement_with_two_pages(self) -> None:
        statement = popular_historico.parse(samples.HISTORICO_NOV)
        assert (statement.kind, statement.product, statement.identifier) == (
            "checking",
            "Nómina",
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
             "PAGO IMPUESTO 0.15% DGII 3 TRANS POR $ 120,000.00 Del 06/10/2025 Al 12/10/2025"),
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
        statement = popular_historico.parse(samples.HISTORICO_DIC)
        assert statement.sections[0].transactions == ()
        assert statement.period_start == date(2025, 11, 13)
        assert validate_statement(statement) == ()

    def test_december_rows_of_a_january_statement_are_of_the_previous_year(self) -> None:
        statement = popular_historico.parse(samples.HISTORICO_ENE)
        days = [t.transacted_on for t in statement.sections[0].transactions]
        assert days == [date(2025, 12, 19), date(2026, 1, 5), date(2026, 1, 11)]
        assert statement.period_start == date(2025, 12, 13)
        assert validate_statement(statement) == ()

    def test_dollar_savings_with_interest_paid(self) -> None:
        statement = popular_historico.parse(samples.POPULAR_HISTORICO_USD)
        (section,) = statement.sections
        assert (statement.kind, statement.product, section.currency) == (
            "savings",
            "Ahorro US$ Pers",
            "USD",
        )
        assert section.printed_credits == Decimal("500.12")  # depósitos más el interés
        assert section.printed_credit_count == 2
        assert section.transactions[-1].amount == Decimal("0.12")
        assert validate_statement(statement) == ()

    def test_digital_account_closing_at_zero(self) -> None:
        statement = popular_historico.parse(samples.POPULAR_HISTORICO_DIGITAL)
        (section,) = statement.sections
        assert (statement.kind, statement.product) == ("checking", "Digital")
        assert section.closing_balance == Decimal("0")
        assert section.transactions[0].balance == Decimal("0")
        assert validate_statement(statement) == ()

    def test_a_row_count_that_does_not_match_is_a_note_not_a_problem(self) -> None:
        statement = popular_historico.parse(samples.HISTORICO_NOV)
        section = replace(statement.sections[0], printed_debit_count=4)
        changed = replace(statement, sections=(section,))
        assert validate_statement(changed) == ()
        assert count_notes(changed) == ("DOP: débitos: 3 filas ≠ 4 impresas",)
        assert count_notes(statement) == ()

    def test_a_month_with_interest_and_one_debit_less_in_the_count_balances(self) -> None:
        statement = popular_historico.parse(samples.POPULAR_HISTORICO_USD_SHORT_COUNT)
        assert validate_statement(statement) == ()
        assert count_notes(statement) == ("USD: débitos: 2 filas ≠ 1 impresas",)

    def test_a_statement_that_does_not_balance_is_reported(self) -> None:
        _, bad, _ = popular_historico.split(samples.POPULAR_HISTORICO_BAD_DIC)
        problems = validate_statement(popular_historico.parse(bad))
        assert len(problems) == 1 and "140000.00" in problems[0]


class TestIngest:
    def test_each_statement_is_its_own_cut_of_the_same_document(self, conn) -> None:
        document_id = add_document(conn, "historico.pdf")
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
        assert document(conn, "historico.pdf") == (
            "parsed",
            "3 de 3 estados guardados (8 transacciones)",
        )

    def test_a_statement_that_does_not_balance_does_not_stop_the_others(self, conn) -> None:
        add_document(conn, "historico_malo.pdf")
        assert run(conn) == {"parsed": 1}
        assert [cut for _, _, cut in cuts(conn)] == ["2025-11-12", "2026-01-12"]
        assert parts(conn) == [
            ("2025-11-12", "parsed"),
            ("2025-12-12", "invalid"),
            ("2026-01-12", "parsed"),
        ]
        status, detail = document(conn, "historico_malo.pdf")
        assert status == "parsed"
        assert detail.startswith("2 de 3 estados guardados (8 transacciones); 2025-12-12 invalid:")
        assert "140000.00" in detail
        alerts = report.build_report(conn, date(2026, 1, 20), commit_from=date(2025, 1, 1)).alerts
        assert any("tramo 2025-12-12" in alert and "invalid" in alert for alert in alerts)

    def test_retry_stores_the_fixed_statement_without_duplicating_the_others(self, conn) -> None:
        add_document(conn, "historico_malo.pdf")
        run(conn)
        assert run(conn) == {}  # sin --retry no se vuelve a tocar
        PAGES["historico_malo.pdf"] = samples.POPULAR_HISTORICO  # «se arregló el parser»
        try:
            assert run(conn, retry=True) == {"parsed": 1}
        finally:
            PAGES["historico_malo.pdf"] = samples.POPULAR_HISTORICO_BAD_DIC
        assert [cut for _, _, cut in cuts(conn)] == ["2025-11-12", "2025-12-12", "2026-01-12"]
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 8
        assert [status for _, status in parts(conn)] == ["parsed"] * 3
        assert run(conn, retry=True) == {}  # ya no queda nada por reintentar

    def test_the_same_statements_from_another_file_are_duplicates(self, conn) -> None:
        add_document(conn, "historico.pdf")
        add_document(conn, "historico_copia.pdf")
        assert run(conn) == {"parsed": 1, "duplicate": 1}
        assert len(cuts(conn)) == 3
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 8
        status, detail = document(conn, "historico_copia.pdf")
        assert status == "duplicate"
        assert "repetidos: 2025-11-12, 2025-12-12, 2026-01-12" in detail

    def test_a_cut_already_stored_from_a_monthly_statement_is_a_duplicate_tramo(self, conn) -> None:
        # El corte de diciembre ya estaba (p. ej., llegó por correo).
        store_parsed(conn, popular_historico.parse(samples.HISTORICO_DIC))
        add_document(conn, "historico.pdf")
        assert run(conn) == {"parsed": 1}
        assert parts(conn)[1] == ("2025-12-12", "duplicate")
        assert len(cuts(conn)) == 3

    def test_accounts_land_on_the_existing_keys(self, conn) -> None:
        store_parsed(conn, popular_cuenta.parse(samples.POPULAR_CUENTA_DOP))
        store_parsed(conn, popular_cuenta.parse(samples.POPULAR_CUENTA_USD))
        before = [tuple(r) for r in conn.execute("SELECT key, kind FROM accounts ORDER BY key")]
        assert before == [(CHECKING, "checking"), (SAVINGS, "savings")]
        add_document(conn, "historico.pdf")
        add_document(conn, "historico_usd.pdf")
        assert run(conn) == {"parsed": 2}
        after = [tuple(r) for r in conn.execute("SELECT key, kind FROM accounts ORDER BY key")]
        assert after == before
        currencies = conn.execute(
            "SELECT DISTINCT s.currency FROM statements s JOIN accounts a ON a.id = s.account_id "
            "WHERE a.key = ? AND s.parser = 'popular_historico'",
            (SAVINGS,),
        ).fetchall()
        assert [tuple(r) for r in currencies] == [("USD",)]

    def test_a_count_difference_enters_with_a_note(self, conn) -> None:
        add_document(conn, "historico_usd_nota.pdf")
        assert run(conn) == {"parsed": 1}
        assert [cut for _, _, cut in cuts(conn)] == ["2025-09-30", "2025-10-31"]
        notes = conn.execute("SELECT label, status, note FROM document_parts ORDER BY part")
        assert [tuple(r) for r in notes] == [
            ("2025-09-30", "parsed", None),
            ("2025-10-31", "parsed", "USD: débitos: 2 filas ≠ 1 impresas"),
        ]
        status, detail = document(conn, "historico_usd_nota.pdf")
        assert status == "parsed"
        assert detail == (
            "2 de 2 estados guardados (7 transacciones); "
            "2025-10-31 nota: USD: débitos: 2 filas ≠ 1 impresas"
        )
        assert db.failed_parts(conn, 1) == 0
        built = report.build_report(conn, date(2025, 11, 5), commit_from=date(2025, 1, 1))
        assert (
            "  historico_usd_nota.pdf (tramo 2025-10-31): USD: débitos: 2 filas ≠ 1 impresas"
            in (built.lines)
        )
        assert not any("historico_usd_nota" in alert for alert in built.alerts)

    def test_broken_spaces_become_a_single_space(self) -> None:
        statement = popular_historico.parse(samples.POPULAR_HISTORICO_BROKEN_SPACES)
        (movement,) = statement.sections[0].transactions
        assert movement.description == samples.HISTORICO_BROKEN_SPACES_DESCRIPTION
        assert validate_statement(statement) == ()
        # Un espacio duro dentro de una palabra del PDF (el generador no puede ponerlo ahí).
        assert popular_historico._clean("FULANO DE  TAL ") == "FULANO DE TAL"

    def test_a_transfer_to_the_holder_with_broken_spaces_is_own(self, conn) -> None:
        add_document(conn, "historico_espacios.pdf")
        assert run(conn) == {"parsed": 1}
        (movement,) = [
            m
            for m in spending.load_all(conn, ("FULANO DE TAL",))
            if m.description == samples.HISTORICO_BROKEN_SPACES_DESCRIPTION
        ]
        assert (movement.category, movement.kind) == (categories.OWN_TRANSFER, "transferencia")

    def test_digital_account_is_a_checking_account(self, conn) -> None:
        add_document(conn, "historico_digital.pdf")
        assert run(conn) == {"parsed": 1}
        account = conn.execute("SELECT key, name FROM accounts").fetchone()
        assert tuple(account) == ("popular:checking:555666777", "POPULAR Digital 555666777")


class TestOverlapWithPrintouts:
    def test_on_the_days_of_a_statement_only_the_statement_counts(self, conn) -> None:
        add_document(conn, "historico.pdf")
        run(conn)
        store(conn, popular_web.parse(samples.POPULAR_WEB))  # del 12 al 20 de enero de 2026
        movements = [m for m in spending.load_all(conn) if m.account == CHECKING]
        january = [(m.day.isoformat(), m.description) for m in movements if m.day.year == 2026]
        assert january == [
            ("2026-01-05", "MB desde 000000003 FULANO DE"),
            ("2026-01-11", "MB desde 000000003 FULANO DE"),  # el estado; no la impresión
            ("2026-01-16", "PAGO TARJETA TIENDA FICTICIA S.R.L. SANTO DOMINGO"),
            ("2026-01-17", "DEPOSITO CHEQUE Y EFECTIVO"),
            (
                "2026-01-19",
                "IMPUESTO 0.15% DGII 1 TRANS POR $ 1,500.00 DEL 16/01/2026 AL 16/01/2026",
            ),
            ("2026-01-20", "TRANSFERENCIA RECIBIDA DE PERSONA INVENTADA"),
        ]


UNKNOWN_PRODUCT = samples.popular_historico(
    *samples.HISTORICO_NOV_ROWS, account="CUENTA AHORRO 123456789 RD$ FULANO DE TAL"
)


@pytest.fixture(autouse=True)
def _restore_pages():
    """Las pruebas pueden cambiar el lector; se deja como estaba."""
    before = dict(PAGES)
    yield
    PAGES.clear()
    PAGES.update(before)


class TestReview:
    def test_unknown_product_is_recognized_and_parse_explains(self) -> None:
        assert popular_historico.matches(UNKNOWN_PRODUCT)  # no lanza
        with pytest.raises(ParseError, match="tipo de cuenta desconocido"):
            popular_historico.parse(UNKNOWN_PRODUCT)

    def test_unknown_product_does_not_stop_the_run(self, conn) -> None:
        PAGES["desconocido.pdf"] = UNKNOWN_PRODUCT
        add_document(conn, "desconocido.pdf")
        add_document(conn, "historico.pdf")
        assert run(conn) == {"error": 1, "parsed": 1}
        status, detail = document(conn, "desconocido.pdf")
        assert status == "error"
        assert "2025-11-12 error: ParseError: tipo de cuenta desconocido" in detail
        assert len(cuts(conn)) == 3

    def test_a_failing_detection_marks_the_document_and_the_run_continues(
        self, conn, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(pages):
            raise ValueError("matches roto")

        monkeypatch.setattr(popular_cuenta, "matches", explode)
        add_document(conn, "historico.pdf")
        add_document(conn, "historico_usd.pdf")
        assert run(conn) == {"error": 2}
        assert document(conn, "historico.pdf") == (
            "error",
            "al reconocer el formato: ValueError: matches roto",
        )

    def test_a_failed_reread_keeps_the_stored_statements_parsed(self, conn) -> None:
        add_document(conn, "historico_malo.pdf")
        run(conn)
        del PAGES["historico_malo.pdf"]  # el lector falla al reintentar
        assert run(conn, retry=True) == {"parsed": 1}
        status, detail = document(conn, "historico_malo.pdf")
        assert status == "parsed"
        assert detail.startswith("2 de 3 estados guardados")
        assert "2025-12-12 invalid:" in detail
        assert "reintento: error: no se pudo leer el PDF: KeyError" in detail
        assert db.failed_parts(conn, 1) == 1
        alerts = report.build_report(conn, date(2026, 1, 20), commit_from=date(2025, 1, 1)).alerts
        assert any("tramo 2025-12-12" in alert for alert in alerts)
        PAGES["historico_malo.pdf"] = samples.POPULAR_HISTORICO
        assert run(conn, retry=True) == {"parsed": 1}
        assert "reintento" not in document(conn, "historico_malo.pdf")[1]

    def test_pages_with_text_before_the_first_page_one_are_a_failed_tramo(self, conn) -> None:
        cover = samples.page("PORTADA INVENTADA", "ESTADOS DE CUENTA")
        pages = (cover, *samples.HISTORICO_NOV)
        assert popular_historico.split(pages) == ((cover,), samples.HISTORICO_NOV)
        PAGES["portada.pdf"] = pages
        add_document(conn, "portada.pdf")
        assert run(conn) == {"parsed": 1}
        assert parts(conn) == [("estado 1", "error"), ("2025-11-12", "parsed")]
        assert db.failed_parts(conn, 1) == 1

    @pytest.mark.parametrize("page_format", ["PAG{}", "PAG {} DE 2"])
    def test_other_ways_of_printing_the_page_number(self, page_format: str) -> None:
        pages = samples.popular_historico(*samples.HISTORICO_NOV_ROWS, page_format=page_format)
        assert popular_historico.matches(pages)
        (part,) = popular_historico.split((samples.page(), *pages))
        assert len(part) == 2
        assert validate_statement(popular_historico.parse(part)) == ()

    def test_a_stored_tramo_that_no_longer_balances_stays_stored(self, conn) -> None:
        add_document(conn, "historico_malo.pdf")
        run(conn)  # noviembre y enero entran; diciembre no cuadra
        bad_nov = samples.popular_historico(*samples.HISTORICO_NOV_ROWS, closing="1.00")
        PAGES["historico_malo.pdf"] = (*bad_nov, *samples.HISTORICO_DIC, *samples.HISTORICO_ENE)
        assert run(conn, retry=True) == {"parsed": 1}
        assert parts(conn) == [
            ("2025-11-12", "parsed"),
            ("2025-12-12", "parsed"),
            ("2026-01-12", "parsed"),
        ]
        assert document(conn, "historico_malo.pdf")[1].startswith("3 de 3 estados guardados")

    def test_a_footer_right_of_the_dates_is_not_part_of_the_description(self) -> None:
        pages = samples.popular_historico(
            *samples.HISTORICO_NOV_ROWS, footer=(60, "AVISO INVENTADO AL PIE")
        )
        expected = popular_historico.parse(samples.HISTORICO_NOV).sections[0].transactions
        found = popular_historico.parse(pages).sections[0].transactions
        assert [t.description for t in found] == [t.description for t in expected]

    def test_a_zero_debit_is_a_debit(self) -> None:
        pages = samples.popular_historico(
            (
                ("15 OCT", "15 OCT", "", "1,500.00-", ("MB a 000000009 PERSONA INVENTADA",)),
                ("16 OCT", "16 OCT", "", ".00-", ("COMISION INVENTADA",)),
            ),
            account="CUENTA DIGITAL 555666777 RD$ FULANO DE TAL",
            opening="1,500.00",
        )
        statement = popular_historico.parse(pages)
        zero = statement.sections[0].transactions[1]
        assert (zero.amount, zero.direction) == (Decimal("0"), "debit")
        assert validate_statement(statement) == ()
        assert count_notes(statement) == ()
