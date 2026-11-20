"""Hosted mode: fixes from the independent review (races, link confirmation, event loop, mail
count shared across processes, proxy warning). Synthetic addresses only."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import cli
from michelito.demo import network
from michelito.hosted import store as store_module
from michelito.hosted.auth import AuthError
from michelito.hosted.mailer import MemoryMailer
from michelito.hosted.routes import ERROR_HEADER
from tests.hosted_helpers import WRITE, hosted

ALICE = "alice@example.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) Firefox/132.0"
SOURCE = network.quota_keys("2001:db8::1")


def test_two_first_sign_ins_at_once_both_get_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = hosted(tmp_path)
    h.service.invite(ALICE)
    code = h.last_code(ALICE)
    real = h.service.store.create_account

    def other_one_was_first(email: str, folder: str, now: int, invitation: int | None, seal):  # noqa: ANN001, ANN202
        real(email, "f" * 32, now, invitation, seal)  # the concurrent sign-in wins the race…
        raise LookupError("account already exists")  # …and this one finds it taken

    monkeypatch.setattr(h.service.store, "create_account", other_one_was_first)
    assert h.service.verify(ALICE, code, UA, SOURCE)
    with sqlite3.connect(h.data / "accounts.db") as conn:
        assert conn.execute("SELECT count(*) FROM accounts").fetchone()[0] == 1


def test_creating_the_same_email_twice_is_a_lookup_error(tmp_path: Path) -> None:
    accounts = store_module.Store(tmp_path / "accounts.db")
    accounts.create_account(ALICE, "a" * 32, 1, None)
    with pytest.raises(LookupError):
        accounts.create_account(ALICE, "b" * 32, 1, None)


def test_invitation_codes_only_work_while_there_is_no_account(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.service.invite(ALICE)
    assert h.service.verify(ALICE, h.last_code(ALICE), UA, SOURCE)
    with sqlite3.connect(h.data / "accounts.db") as conn:
        left = conn.execute("SELECT count(*) FROM login_codes WHERE purpose = 'invitation'")
        assert left.fetchone()[0] == 0
    # An invitation code that somehow exists for an existing account is refused.
    code = "424242"
    now = int(h.clock.now)
    digest = h.service._keyed("code", ALICE, code)
    h.service.store.add_code(ALICE, "invitation", digest, None, now, now + 600)
    with pytest.raises(AuthError):
        h.service.verify(ALICE, code, UA, SOURCE)


def test_a_link_is_confirmed_before_it_is_used(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    h.clock.advance(61)
    client = h.client()
    client.post("/api/auth/code", json={"email": ALICE}, headers=WRITE)
    link = h.last_link(ALICE)
    peek = h.client().post("/api/auth/link/peek", json={"token": link}, headers=WRITE)
    assert peek.status_code == 200
    assert peek.json() == {"email": "a•••@example.com"}
    assert "set-cookie" not in peek.headers  # looking does not sign anyone in…
    used = h.client().post("/api/auth/link", json={"token": link}, headers=WRITE)
    assert used.status_code == 204  # …and the link still works after it
    gone = h.client().post("/api/auth/link/peek", json={"token": link}, headers=WRITE)
    assert gone.status_code == 400


def test_the_step_up_refusal_says_so_in_a_header(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    h.clock.advance(11 * 60)
    refused = client.post("/api/auth/sign-out-everywhere", headers=WRITE)
    assert refused.status_code == 403
    assert refused.headers[ERROR_HEADER] == "step_up_required"
    missing = client.post("/api/auth/sign-out-everywhere")  # no X-Michelito: another 403
    assert missing.status_code == 403
    assert ERROR_HEADER not in missing.headers


def test_async_routes_do_no_database_work_on_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = hosted(tmp_path)
    on_loop: list[str] = []
    real = store_module.Store.connect

    def watched(self: store_module.Store):  # noqa: ANN202
        try:
            asyncio.get_running_loop()
            on_loop.append("connect")
        except RuntimeError:
            pass
        return real(self)

    monkeypatch.setattr(store_module.Store, "connect", watched)
    client = h.sign_in(ALICE)
    h.clock.advance(61)
    client.post("/api/auth/code", json={"email": ALICE}, headers=WRITE)
    client.post("/api/auth/link/peek", json={"token": h.last_link(ALICE)}, headers=WRITE)
    client.post("/api/auth/link", json={"token": h.last_link(ALICE)}, headers=WRITE)
    client.post("/api/auth/step-up/code", headers=WRITE)
    client.get("/api/auth/devices")
    assert on_loop == []


def test_the_days_mail_count_is_shared_through_the_accounts_database(tmp_path: Path) -> None:
    first = hosted(tmp_path, daily_mail_limit=2)
    first.service.invite("a@example.com")
    first.service.invite("b@example.com")
    assert not first.app.state.dispatcher.available()
    # Another process on the same folder (e.g. `michelito invite`) sees the same count.
    second = hosted(tmp_path, daily_mail_limit=2)
    assert not second.app.state.dispatcher.available()
    with pytest.raises(AuthError) as error:
        second.service.invite("c@example.com")
    assert error.value.kind == "mail"
    second.clock.advance(24 * 3600)
    assert second.app.state.dispatcher.available()


def test_the_invite_command_counts_in_the_same_day(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(tmp_path / "real-data"))
    monkeypatch.delenv("MICHELITO_MODE", raising=False)
    data = tmp_path / "hosted"
    argv = ["invite", "a@example.com", "--data", str(data), "--mailer", "outbox"]
    assert cli.main(argv) == 0
    with sqlite3.connect(data / "accounts.db") as conn:
        assert conn.execute("SELECT sum(sent) FROM mail_days").fetchone()[0] == 1


def test_an_unconfigured_proxy_is_warned_about(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(network, "_warned", False)
    h = hosted(tmp_path)
    client = TestClient(h.app, base_url="http://127.0.0.1", client=("127.0.0.1", 5000))
    with caplog.at_level(logging.WARNING):
        client.get("/api/mode", headers={"X-Forwarded-For": "203.0.113.9"})
    assert "without --trusted-proxy" in caplog.text


def test_insecure_cookies_only_on_loopback(tmp_path: Path, monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(tmp_path / "real-data"))
    monkeypatch.delenv("MICHELITO_MODE", raising=False)
    argv = [
        "hosted",
        "--listen",
        "0.0.0.0",
        "--insecure-cookie",
        "--data",
        str(tmp_path / "h"),
        "--trusted-proxy",
        "10.0.0.1",
    ]
    monkeypatch.setenv("RESEND_API_KEY", "re_test_not_a_real_key_0123456789")
    assert cli.main(argv) == 2
    assert "only for this machine" in capsys.readouterr().err


def test_memory_mailer_is_still_the_default_ledger_free_path(tmp_path: Path) -> None:
    from michelito.hosted.mailer import Dispatcher, Email

    dispatcher = Dispatcher(MemoryMailer(), daily_limit=1, background=False)
    assert dispatcher.submit(Email("a@example.com", "s", "t"))
    assert not dispatcher.available()


def _step_up_code(h, client: TestClient) -> str:  # noqa: ANN001
    h.clock.advance(11 * 60)
    assert client.post("/api/auth/step-up/code", headers=WRITE).status_code == 202
    return h.last_code(ALICE)


def _codes(h, purpose: str) -> list[tuple[int, object]]:  # noqa: ANN001
    with sqlite3.connect(h.data / "accounts.db") as conn:
        query = "SELECT attempts, used_at FROM login_codes WHERE purpose = ?"
        return conn.execute(query, (purpose,)).fetchall()


def test_the_anonymous_sign_in_never_touches_a_step_up_code(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    phone = h.sign_in(ALICE)
    code = _step_up_code(h, phone)
    with pytest.raises(AuthError):
        h.service.verify(ALICE, code, UA, SOURCE)
    assert _codes(h, "step_up") == [(0, None)]  # not even an attempt was spent on it
    answer = phone.post("/api/auth/step-up/verify", json={"code": code}, headers=WRITE)
    assert answer.status_code == 204


def test_a_step_up_code_only_works_for_the_session_that_asked(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    phone = h.sign_in(ALICE)
    h.clock.advance(61)
    desktop = h.sign_in(ALICE, h.client(UA))
    code = _step_up_code(h, phone)
    refused = desktop.post("/api/auth/step-up/verify", json={"code": code}, headers=WRITE)
    assert refused.status_code == 400
    assert _codes(h, "step_up") == [(0, None)]
    answer = phone.post("/api/auth/step-up/verify", json={"code": code}, headers=WRITE)
    assert answer.status_code == 204


def test_a_sign_in_request_cancels_neither_step_up_nor_invitation_codes(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    phone = h.sign_in(ALICE)
    code = _step_up_code(h, phone)
    h.clock.advance(61)
    h.service.request_code(ALICE, SOURCE)  # someone asks for a sign-in code for Alice
    answer = phone.post("/api/auth/step-up/verify", json={"code": code}, headers=WRITE)
    assert answer.status_code == 204

    bob = "bob@example.com"
    h.service.invite(bob)
    link = h.last_link(bob)
    h.clock.advance(61)
    h.service.request_code(bob, SOURCE)
    with sqlite3.connect(h.data / "accounts.db") as conn:
        query = "SELECT used_at FROM login_codes WHERE email = ? AND purpose = 'invitation'"
        assert conn.execute(query, (bob,)).fetchone() == (None,)
    token, email = h.service.verify_link(link, UA, SOURCE)  # the invitation still works
    assert token and email == bob


def test_a_version_three_database_keeps_its_codes(tmp_path: Path) -> None:
    path = tmp_path / "accounts.db"
    with sqlite3.connect(path) as conn:
        for number, script in enumerate(store_module.MIGRATIONS[:3], start=1):
            conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {number}; COMMIT;")
        conn.execute(
            "INSERT INTO login_codes (email, purpose, code_hash, created_at, expires_at) "
            "VALUES (?, 'login', ?, 1, 2)",
            (ALICE, "0" * 64),
        )
    store_module.Store(path)
    with sqlite3.connect(path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == len(store_module.MIGRATIONS)
        rows = conn.execute("SELECT email, session_id FROM login_codes").fetchall()
        assert rows == [(ALICE, None)]
