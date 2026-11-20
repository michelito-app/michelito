"""Live sync through the Gmail extraction (fake client) and the schema 20 migration."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from michelito import db, extract, migrations_live
from michelito.analysis import live_store
from michelito.config import DEFAULT_SOURCES, find_source
from michelito.gmail import MailMessage, message_from_api
from tests import alert_samples as samples
from tests.fakes import FakeClient
from tests.live_helpers import known_card

SOURCE = find_source("popular_alerts", DEFAULT_SOURCES)


def _message(message_id: str, **fields: str) -> tuple[MailMessage, dict[str, bytes]]:
    message = MailMessage(
        message_id=message_id,
        sender=samples.SENDER,
        subject=samples.SUBJECT,
        received_at=datetime(2026, 2, 14, 15, tzinfo=UTC),
        body_text="",
        attachments=(),
        body_html=samples.alert_html(**fields),
        auth_results=(samples.SIGNED,),
    )
    return message, {}


def test_alerts_are_read_in_memory_and_only_their_fields_stored(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    with closing(db.connect(tmp_path / "m.db")) as conn:
        known_card(conn)
        client = FakeClient(_message("alert1", amount="99.00"), _message("alert2"))
        stats = extract.extract_source(conn, client, SOURCE, raw)
        assert (stats.new_messages, stats.saved_files) == (2, 0)
        assert not raw.exists()  # nothing written to the raw archive
        rows = conn.execute("SELECT status, amount_cents FROM alerts ORDER BY id").fetchall()
        assert [tuple(r) for r in rows] == [("provisional", 9900), ("provisional", 125000)]
        # The alert is not a statement: no document, no stored email.
        messages = conn.execute(
            "SELECT COUNT(*) FROM gmail_messages WHERE source = ?", (SOURCE.name,)
        ).fetchone()[0]
        assert messages == 0
        again = extract.extract_source(conn, client, SOURCE, raw)
        assert again.new_messages == 0
        assert client.fetched == ["alert1", "alert2"]


def test_the_gmail_message_keeps_the_html_body() -> None:
    html = samples.alert_html()
    data = {
        "id": "abc",
        "internalDate": "1792005355000",
        "payload": {
            "headers": [
                {"name": "From", "value": samples.SENDER},
                {"name": "Authentication-Results", "value": samples.SIGNED},
                {"name": "Authentication-Results", "value": samples.FORGED},
            ],
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64(html)}},
            ],
        },
    }
    message = message_from_api(data)
    assert message.body_html == html
    assert message.auth_results == (samples.SIGNED, samples.FORGED)  # topmost first
    assert message.body_text == ""


def _b64(text: str) -> str:
    import base64  # noqa: PLC0415

    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_a_database_from_the_previous_schema_gains_the_live_tables(tmp_path: Path) -> None:
    path = tmp_path / "v19.db"
    with closing(db.connect(path)) as conn:
        known_card(conn)
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    with closing(sqlite3.connect(path)) as raw:
        raw.executescript(
            "DROP TABLE alerts; DROP TABLE provisional_decisions; PRAGMA user_version = 19;"
        )
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == migrations_live.VERSION
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"alerts", "provisional_decisions"} <= tables
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == count
    with closing(db.connect(path)) as again:  # idempotent
        assert again.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_the_report_lists_alerts_and_failures_without_values(tmp_path: Path) -> None:
    from michelito import report  # noqa: PLC0415
    from michelito.analysis import live_store  # noqa: PLC0415
    from tests.live_helpers import NOW  # noqa: PLC0415

    with closing(db.connect(tmp_path / "m.db")) as conn:
        known_card(conn)
        with conn:
            live_store.record(conn, samples.alert_email("a1", auth=()), "popular_alerts", NOW)
        text = report.build_report(conn, datetime(2026, 2, 20).date()).text
    assert "Bank alerts: failed: 1" in text
    assert "failed_field=authentication" in text
    assert "SUPERMERCADO" not in text and samples.CARD not in text


def _unsigned(message_id: str) -> tuple[MailMessage, dict[str, bytes]]:
    message, payloads = _message(message_id)
    return replace(message, auth_results=()), payloads


def _bad_currency(message_id: str) -> tuple[MailMessage, dict[str, bytes]]:
    return _message(message_id, currency="EUR")


def test_permanent_failures_are_never_downloaded_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with closing(db.connect(tmp_path / "m.db")) as conn:
        known_card(conn)
        client = FakeClient(_unsigned("unsigned"), _bad_currency("layout"))
        extract.extract_source(conn, client, SOURCE, tmp_path / "raw")
        extract.extract_source(conn, client, SOURCE, tmp_path / "raw")
        assert client.fetched == ["unsigned", "layout"]  # neither is retried as is
        monkeypatch.setattr(live_store, "PARSER_VERSION", "next")
        extract.extract_source(conn, client, SOURCE, tmp_path / "raw")
        # A new parser retries the layout failure, never the unauthenticated email.
        assert client.fetched == ["unsigned", "layout", "layout"]


def test_retries_are_capped_per_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract, "MAX_RETRIES", 2)
    with closing(db.connect(tmp_path / "m.db")) as conn:
        known_card(conn)
        bad = [_bad_currency(f"bad{i}") for i in range(5)]
        client = FakeClient(*bad)
        extract.extract_source(conn, client, SOURCE, tmp_path / "raw")
        assert len(client.fetched) == 5  # new messages are not capped
        monkeypatch.setattr(live_store, "PARSER_VERSION", "next")
        extract.extract_source(conn, client, SOURCE, tmp_path / "raw")
        assert len(client.fetched) == 7  # only two retried in this sync
