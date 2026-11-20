"""Hosted mode: the accounts database schema and migrations, the mail dispatcher and the
Resend adapter (against a fake HTTP server on loopback; nothing is sent anywhere)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from michelito.hosted import store
from michelito.hosted.mailer import (
    Dispatcher,
    Email,
    MailCapReached,
    MailError,
    MemoryMailer,
    OutboxMailer,
)
from michelito.hosted.resend import ResendMailer, key_from_environment
from tests.hosted_helpers import WRITE, Clock, hosted

FINANCIAL = re.compile(
    r"amount|balance|cents|bank|card|statement|transaction|merchant|category|currency|"
    r"income|expense|salary|holder|pdf|iban|routing",
    re.IGNORECASE,
)
FAKE_KEY = "re_test_not_a_real_key_0123456789"


def _columns(path: Path) -> dict[str, set[str]]:
    with sqlite3.connect(path) as conn:
        tables = [
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        return {
            table: {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for table in tables
        }


def test_the_accounts_schema_has_no_financial_fields(tmp_path: Path) -> None:
    columns = _columns(store.Store(tmp_path / "accounts.db").path)
    assert set(columns) == {
        "accounts",
        "login_codes",
        "sessions",
        "invitations",
        "passkeys",
        "known_devices",
        "mail_days",
        "data_keys",
        "deleted_folders",
        "bank_requests",
    }
    # "Notify me when it is supported": demand per bank name, tied to no account, email or date.
    assert columns.pop("bank_requests") == {"bank", "requests"}
    for table, names in columns.items():
        for name in names:
            assert not FINANCIAL.search(name), f"{table}.{name}"
    assert columns["accounts"] == {"id", "email", "created_at", "status", "folder"}
    assert columns["data_keys"] == {"account_id", "wrapped", "master_id", "created_at"}
    assert columns["deleted_folders"] == {"folder", "deleted_at"}


def test_migrations_are_forward_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "accounts.db"
    store.Store(path)
    store.Store(path)  # again: nothing to do, nothing breaks
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS)
        assert store.migrate(conn) == len(store.MIGRATIONS)
    assert path.stat().st_mode & 0o777 == 0o600


def test_the_dispatcher_keeps_the_daily_cap() -> None:
    clock = Clock()
    mailer = MemoryMailer()
    dispatcher = Dispatcher(mailer, daily_limit=2, background=False, clock=clock)
    email = Email("a@example.com", "s", "t")
    assert dispatcher.submit(email) and dispatcher.submit(email)
    assert not dispatcher.available()
    assert not dispatcher.submit(email)
    assert len(mailer.sent) == 2
    clock.advance(24 * 3600)
    assert dispatcher.available()


class _Capped:
    def send(self, email: Email) -> None:
        raise MailCapReached("daily_quota_exceeded")


def test_when_the_provider_caps_every_request_is_told_alike(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.service.invite("alice@example.com")
    h.app.state.dispatcher.mailer = _Capped()
    h.app.state.dispatcher.submit(Email("alice@example.com", "s", "t"))
    for email in ("alice@example.com", "nobody@example.com"):
        answer = h.client().post("/api/auth/code", json={"email": email}, headers=WRITE)
        assert answer.status_code == 503
        assert "más tarde" in answer.json()["detail"]  # spanish-ui


def test_background_sending_survives_errors(caplog: pytest.LogCaptureFixture) -> None:
    class Broken:
        def send(self, email: Email) -> None:
            raise MailError("Resend answered 500 (no error name)")

    dispatcher = Dispatcher(Broken(), background=True)
    dispatcher.submit(Email("a@example.com", "s", "secret-body-123456"))
    dispatcher.join()
    dispatcher.stop()
    assert "could not be sent" in caplog.text
    assert "secret-body-123456" not in caplog.text and "a@example.com" not in caplog.text


def test_the_outbox_writes_private_files(tmp_path: Path) -> None:
    outbox = OutboxMailer(tmp_path / "outbox")
    outbox.send(Email("a@example.com", "subject", "body"))
    (written,) = list((tmp_path / "outbox").glob("*.json"))
    assert json.loads(written.read_text())["to"] == "a@example.com"
    assert written.stat().st_mode & 0o777 == 0o600


class _Fake(BaseHTTPRequestHandler):
    received: list[tuple[dict[str, str], dict[str, object]]] = []
    answer: tuple[int, dict[str, object]] = (200, {"id": "fake"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        type(self).received.append(({k.lower(): v for k, v in self.headers.items()}, body))
        status, payload = type(self).answer
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@pytest.fixture
def fake_resend() -> Iterator[str]:
    _Fake.received = []
    _Fake.answer = (200, {"id": "fake"})
    server = HTTPServer(("127.0.0.1", 0), _Fake)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_resend_sends_plain_text_with_the_key_as_bearer(fake_resend: str) -> None:
    mailer = ResendMailer(FAKE_KEY, "Michelito <codigo@auth.example>", base_url=fake_resend)
    mailer.send(Email("a@example.com", "Tu código", "123456"))  # spanish-ui
    ((headers, body),) = _Fake.received
    assert headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert body == {
        "from": "Michelito <codigo@auth.example>",
        "to": ["a@example.com"],
        "subject": "Tu código",  # spanish-ui
        "text": "123456",
    }
    assert "html" not in body  # no HTML: no tracking pixel, no rewritten links
    assert FAKE_KEY not in repr(mailer)


def test_resend_quota_errors_become_the_cap(fake_resend: str) -> None:
    mailer = ResendMailer(FAKE_KEY, "x@auth.example", base_url=fake_resend)
    _Fake.answer = (429, {"name": "daily_quota_exceeded", "message": "quota"})
    with pytest.raises(MailCapReached):
        mailer.send(Email("a@example.com", "s", "t"))
    _Fake.answer = (401, {"name": "invalid_api_key", "message": "bad"})
    with pytest.raises(MailError) as error:
        mailer.send(Email("a@example.com", "s", "t"))
    assert FAKE_KEY not in str(error.value)
    assert "401" in str(error.value)


def test_resend_unreachable_is_a_mail_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    mailer = ResendMailer(FAKE_KEY, "x@auth.example", base_url="http://127.0.0.1:9", timeout=2)
    with pytest.raises(MailError) as error:
        mailer.send(Email("a@example.com", "s", "t"))
    assert FAKE_KEY not in str(error.value) and FAKE_KEY not in caplog.text


def test_the_key_comes_from_a_file_or_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY_FILE", raising=False)
    assert key_from_environment() is None
    monkeypatch.setenv("RESEND_API_KEY", FAKE_KEY)
    assert key_from_environment() == FAKE_KEY
    secret = tmp_path / "key"
    secret.write_text("re_from_file\n")
    monkeypatch.setenv("RESEND_API_KEY_FILE", str(secret))
    assert key_from_environment() == "re_from_file"


def test_a_version_one_database_is_migrated_forward(tmp_path: Path) -> None:
    path = tmp_path / "accounts.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(f"BEGIN; {store.MIGRATIONS[0]}; PRAGMA user_version = 1; COMMIT;")
        conn.execute(
            "INSERT INTO accounts (email, created_at, folder) VALUES (?, 1, ?)",
            ("alice@example.com", "0" * 32),
        )
    store.Store(path)
    columns = _columns(path)
    assert "known_devices" in columns
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM accounts").fetchone()[0] == 1
