from dataclasses import replace
from pathlib import Path

import pytest

from michelito import db
from michelito.ingest import process_documents
from michelito.parsers.common import Page
from tests import samples

PAGES: dict[str, tuple[Page, ...]] = {
    "popular.pdf": samples.POPULAR_PAGES,
    "popular_copy.pdf": samples.POPULAR_PAGES,
    "bhd_tc.pdf": samples.BHD_TC_PAGES,
    "savings.pdf": samples.BHD_AHORRO_PAGES,
    "savings_portal.pdf": samples.BHD_AHORRO_PORTAL_PAGES,
    "wrong_total.pdf": (samples.POPULAR_DOP_WRONG_TOTAL,),
    "unknown.pdf": (samples.UNKNOWN,),
}


def fake_reader(path: Path, password: str) -> tuple[Page, ...]:
    assert password == "test-password"
    if path.name == "broken.pdf":
        raise RuntimeError("broken PDF")
    return PAGES[path.name]


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def add_document(conn, filename: str, received_at: str = "2026-01-14T12:00:00+00:00") -> int:
    message_id = f"m-{filename}"
    with conn:
        conn.execute(
            "INSERT INTO gmail_messages VALUES (?, 'banco', 'x', 'y', ?, 1, ?)",  # spanish-data
            (message_id, received_at, received_at),
        )
        cursor = conn.execute(
            "INSERT INTO documents (message_id, source, filename, path, sha256, size, "
            "received_at, status) VALUES (?, 'banco', ?, ?, ?, 1, ?, ?)",  # spanish-data
            (
                message_id,
                filename,
                f"/data/{filename}",
                filename,
                received_at,
                "archived" if not filename.endswith(".pdf") else "pending",
            ),
        )
    return int(cursor.lastrowid)


def status_of(conn, filename: str) -> tuple[str, str | None]:
    row = conn.execute(
        "SELECT status, detail FROM documents WHERE filename = ?", (filename,)
    ).fetchone()
    return row["status"], row["detail"]


def run(conn, retry: bool = False):
    return process_documents(conn, "test-password", fake_reader, retry=retry)


def test_parses_validates_and_stores(conn) -> None:
    for name in ("popular.pdf", "bhd_tc.pdf", "savings.pdf"):
        add_document(conn, name)
    outcome = run(conn)
    assert outcome == {"parsed": 3}
    assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 12
    keys = [r[0] for r in conn.execute("SELECT key FROM accounts ORDER BY key")]
    assert keys == ["bhd:credit_card", "bhd:savings:999-1", "popular:credit_card"]
    payment = conn.execute(
        "SELECT amount_cents, direction, mcc FROM transactions "
        "WHERE description = 'SU PAGO GRACIAS'"
    ).fetchone()
    assert tuple(payment) == (500000, "credit", None)
    card = conn.execute(
        "SELECT last4, first_seen, last_seen FROM cards WHERE last4 = '1234'"
    ).fetchone()
    assert tuple(card) == ("1234", "2026-01-13", "2026-01-13")
    assert status_of(conn, "popular.pdf") == ("parsed", "4 transacciones")  # spanish-ui


def test_classifies_every_failure(conn) -> None:
    for name in ("wrong_total.pdf", "unknown.pdf", "broken.pdf", "summary.jpg"):
        add_document(conn, name)
    outcome = run(conn)
    assert outcome == {"invalid": 1, "unsupported": 1, "error": 1}
    assert status_of(conn, "wrong_total.pdf")[0] == "invalid"
    assert "1600.50" in (status_of(conn, "wrong_total.pdf")[1] or "")
    assert status_of(conn, "unknown.pdf")[0] == "unsupported"
    assert status_of(conn, "broken.pdf") == (
        "error",
        "no se pudo leer el PDF: RuntimeError: broken PDF",  # spanish-ui
    )
    assert status_of(conn, "summary.jpg")[0] == "archived"
    assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0


def test_archive_only_sources_are_not_interpreted(conn) -> None:
    document_id = add_document(conn, "unknown.pdf")
    with conn:
        conn.execute("UPDATE documents SET source = 'afp_crecer' WHERE id = ?", (document_id,))
    assert run(conn) == {"archived": 1}
    detail = "fuente sin parser en la fase 1"  # spanish-ui
    assert status_of(conn, "unknown.pdf") == ("archived", detail)


def test_archive_only_sources_can_come_from_the_user_file(conn) -> None:
    document_id = add_document(conn, "unknown.pdf")
    with conn:
        conn.execute("UPDATE documents SET source = 'afp-x' WHERE id = ?", (document_id,))
    outcome = process_documents(conn, "password", fake_reader, archive_only={"afp-x"})
    assert outcome == {"archived": 1}


def test_same_period_twice_is_a_duplicate(conn) -> None:
    add_document(conn, "popular.pdf")
    add_document(conn, "popular_copy.pdf")
    assert run(conn) == {"parsed": 1, "duplicate": 1}
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 4


def test_portal_savings_statement_is_stored_under_the_email_account(conn) -> None:
    add_document(conn, "savings_portal.pdf")
    assert run(conn) == {"parsed": 1}
    keys = [r[0] for r in conn.execute("SELECT key FROM accounts")]
    assert keys == ["bhd:savings:999-1"]
    assert status_of(conn, "savings_portal.pdf") == ("parsed", "3 transacciones")  # spanish-ui


def test_portal_copy_of_a_stored_email_savings_statement_is_a_duplicate(conn) -> None:
    add_document(conn, "savings.pdf")
    add_document(conn, "savings_portal.pdf")
    assert run(conn) == {"parsed": 1, "duplicate": 1}
    assert status_of(conn, "savings_portal.pdf")[0] == "duplicate"
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_two_cards_of_one_bank_with_the_same_cut_are_both_kept(conn) -> None:
    PAGES["other_card.pdf"] = tuple(_with_card(p, "5678") for p in samples.POPULAR_PAGES)
    try:
        add_document(conn, "popular.pdf")
        add_document(conn, "other_card.pdf")
        assert run(conn) == {"parsed": 2}
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2
    finally:
        PAGES.pop("other_card.pdf")


def _with_card(page_: Page, last4: str) -> Page:
    """The same page with another card number."""
    return tuple(
        replace(
            line, words=tuple(replace(w, text=w.text.replace("1234", last4)) for w in line.words)
        )
        for line in page_
    )


def test_unexpected_parser_crash_is_recorded_and_the_run_continues(
    conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    from michelito.parsers import popular_card

    def explode(pages):
        raise KeyError("unexpected column")

    monkeypatch.setattr(popular_card, "parse", explode)
    add_document(conn, "popular.pdf")
    add_document(conn, "savings.pdf")
    assert run(conn) == {"error": 1, "parsed": 1}
    assert status_of(conn, "popular.pdf")[1] == "KeyError: 'unexpected column'"


def test_password_never_lands_in_stored_details(conn) -> None:
    def leaky_reader(path: Path, password: str) -> tuple[Page, ...]:
        raise RuntimeError(f"cannot open with {password}")

    add_document(conn, "popular.pdf")
    process_documents(conn, "test-password", leaky_reader)
    assert "test-password" not in (status_of(conn, "popular.pdf")[1] or "")


def test_retry_reprocesses_failures_only_when_asked(conn) -> None:
    add_document(conn, "broken.pdf")
    run(conn)
    PAGES["broken.pdf"] = samples.POPULAR_PAGES
    try:
        assert run(conn) == {}
        conn.execute("UPDATE documents SET filename = 'popular.pdf' WHERE filename = 'broken.pdf'")
        conn.execute("UPDATE documents SET path = '/data/popular.pdf'")
        assert run(conn, retry=True) == {"parsed": 1}
    finally:
        PAGES.pop("broken.pdf")


def test_only_processes_the_given_documents(conn) -> None:
    first = add_document(conn, "popular.pdf")
    other = add_document(conn, "savings.pdf")
    outcome = process_documents(conn, "test-password", fake_reader, only=(first,))
    assert outcome == {"parsed": 1}
    status = conn.execute("SELECT status FROM documents WHERE id = ?", (other,)).fetchone()[0]
    assert status == "pending"
