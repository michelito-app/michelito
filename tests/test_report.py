from datetime import date
from decimal import Decimal

import pytest

from finanzas import db
from finanzas.parsers.common import DEBIT, Section, Statement, Transaction
from finanzas.report import build_report, missing_months
from tests.test_ingest import add_document


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def statement(period_end: date) -> Statement:
    transaction = Transaction(period_end, None, "X", Decimal("10"), DEBIT, "DOP", None, None, "X")
    section = Section("DOP", Decimal("0"), Decimal("10"), None, None, None, None, (transaction,))
    return Statement("p", "popular", "credit_card", "VISA", "1234", period_end, None, (section,))


def store(conn, period_end: date) -> None:
    document_id = add_document(conn, f"{period_end}.pdf")
    with conn:
        db.store_statement(conn, document_id, statement(period_end))
        conn.execute("UPDATE documents SET status = 'parsed' WHERE id = ?", (document_id,))


def test_missing_months_only_inside_commitment_window() -> None:
    ends = [date(2023, 5, 13), date(2024, 1, 13), date(2024, 3, 13), date(2024, 4, 13)]
    assert missing_months(ends, date(2024, 1, 1)) == ["2024-02"]
    assert missing_months([date(2023, 1, 1), date(2023, 6, 1)], date(2024, 1, 1)) == []


def test_reports_coverage_gaps_and_overdue(conn) -> None:
    for period in (date(2024, 1, 13), date(2024, 3, 13)):
        store(conn, period)
    report = build_report(conn, date(2024, 6, 1), commit_from=date(2024, 1, 1), overdue_days=45)
    assert "POPULAR VISA DOP: 2 cortes, 2024-01 a 2024-03" in report.text
    assert "2024-02" in report.text
    assert any("faltan 1 meses" in alert for alert in report.alerts)
    assert any("hace 80 días" in alert for alert in report.alerts)


def test_failures_inside_window_are_alerts_and_old_ones_are_counted(conn) -> None:
    recent = add_document(conn, "nuevo.pdf", "2024-05-01T00:00:00+00:00")
    old = add_document(conn, "viejo.pdf", "2019-05-01T00:00:00+00:00")
    other = add_document(conn, "corriente.pdf", "2024-05-02T00:00:00+00:00")
    with conn:
        conn.execute(
            "UPDATE documents SET status='invalid', detail='DOP: descuadre' WHERE id=?", (recent,)
        )
        conn.execute("UPDATE documents SET status='error', detail='x' WHERE id=?", (old,))
        conn.execute("UPDATE documents SET status='unsupported', detail='y' WHERE id=?", (other,))
    report = build_report(conn, date(2024, 6, 1), commit_from=date(2024, 1, 1))
    assert report.alerts == ("nuevo.pdf (banco, invalid): DOP: descuadre",)
    assert "Históricos sin interpretar: error 1" in report.text
    assert "corriente.pdf" in report.text


def test_lists_recent_notices_without_attachment(conn) -> None:
    with conn:
        conn.execute(
            "INSERT INTO gmail_messages VALUES ('n1', 'bhd', 'x', 'Ya están disponibles', "
            "'2026-11-07T14:39:16+00:00', 0, 'z')"
        )
    report = build_report(conn, date(2026, 11, 13))
    assert "2026-11-07 bhd: Ya están disponibles" in report.text


def test_empty_database_has_no_alerts(conn) -> None:
    report = build_report(conn, date(2026, 11, 13))
    assert report.alerts == ()
    assert "Sin alertas." in report.text


def test_terminal_control_sequences_are_neutralized(conn) -> None:
    with conn:
        conn.execute(
            "INSERT INTO gmail_messages VALUES ('n1', 'bhd', 'x', 'Hola\x1b]0;falso\x07\x1b[2J', "
            "'2026-11-07T14:39:16+00:00', 0, 'z')"
        )
    text = build_report(conn, date(2026, 11, 13)).text
    assert "\x1b" not in text and "\x07" not in text
    assert "Hola?]0;falso??[2J" in text
