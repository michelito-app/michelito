"""Hosted mode: sessions (cookie, sliding and absolute expiry, revocation, devices), step-up and
per-account databases. Synthetic addresses only."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from tests.hosted_helpers import PHONE, WRITE, hosted, past_the_gate

ALICE = "alice@example.com"
BOB = "bob@example.com"
DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"
DAY = 24 * 3600


def test_the_secure_cookie_follows_the_host_prefix_rules(tmp_path: Path) -> None:
    h = hosted(tmp_path, secure_cookie=True)
    h.service.invite(ALICE)
    client = TestClient(h.app, base_url="https://127.0.0.1")
    answer = client.post(
        "/api/auth/verify", json={"email": ALICE, "code": h.last_code(ALICE)}, headers=WRITE
    )
    assert answer.status_code == 204
    cookies = {}
    for cookie in answer.headers.get_list("set-cookie"):
        name, _, rest = cookie.partition("=")
        cookies[name] = cookie
        attributes = {part.strip().split("=")[0].lower() for part in rest.split(";")[1:]}
        assert name.startswith("__Host-")
        assert {"secure", "httponly", "path"} <= attributes
        assert "domain" not in attributes
        assert "Path=/;" in cookie or cookie.endswith("Path=/")
        assert "samesite=lax" in cookie.lower()
    assert set(cookies) == {"__Host-session", "__Host-device"}
    assert "max-age=7776000" in cookies["__Host-session"].lower()  # 90 days: the absolute limit
    assert client.get("/api/auth/me").status_code == 200


def test_unauthenticated_api_answers_401_except_the_open_routes(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    for path in ("/api/accounts", "/api/summary", "/api/auth/devices", "/api/nothing", "/api"):
        assert client.get(path).status_code == 401, path
    assert client.patch("/api/transactions/x", json={}, headers=WRITE).status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/mode").status_code == 200
    assert not (h.data / "users").exists()


def test_writes_still_need_the_header(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    assert client.post("/api/auth/sign-out").status_code == 403
    assert client.post("/api/auth/code", json={"email": ALICE}).status_code == 403


def test_sessions_slide_for_thirty_idle_days(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    for _ in range(2):  # used every 29 days: still signed in after 58 days
        h.clock.advance(29 * DAY)
        assert client.get("/api/accounts").status_code == 200
    h.clock.advance(30 * DAY + 1)  # then 30 idle days (89 in total, under the absolute limit)
    assert client.get("/api/accounts").status_code == 401


def test_an_idle_session_ends_after_thirty_days(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    h.clock.advance(30 * DAY + 1)
    assert client.get("/api/accounts").status_code == 401
    assert h.service.store.sessions_of(1) == []


def test_a_session_ends_after_ninety_days_even_in_use(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    for _ in range(3):
        h.clock.advance(29 * DAY)
        assert client.get("/api/accounts").status_code == 200
    h.clock.advance(3 * DAY + 1)  # 90 days and a second since the sign-in
    assert client.get("/api/accounts").status_code == 401


def test_signing_out_is_immediate(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    token = client.cookies.get("session")
    answer = client.post("/api/auth/sign-out", headers=WRITE)
    assert answer.status_code == 204
    assert (
        'session=""' in answer.headers["set-cookie"] or "Max-Age=0" in answer.headers["set-cookie"]
    )
    replay = h.client()
    replay.cookies.set("session", token or "")
    assert replay.get("/api/accounts").status_code == 401


def test_devices_list_this_and_other_sessions_without_ip(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    phone = h.sign_in(ALICE)
    h.sign_in(ALICE, h.client(DESKTOP))
    devices = phone.get("/api/auth/devices").json()
    assert {(d["browser"], d["os"], d["current"]) for d in devices} == {
        ("Chrome", "Android", True),
        ("Firefox", "Windows", False),
    }
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["last_seen"]) for d in devices)
    with sqlite3.connect(h.data / "accounts.db") as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert not columns & {"ip", "address", "user_agent"}


def test_sign_out_everywhere_needs_a_fresh_verification(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    phone = h.sign_in(ALICE)
    desktop = h.sign_in(ALICE, h.client(DESKTOP))
    h.clock.advance(11 * 60)
    assert phone.get("/api/auth/me").json() == {"email": ALICE, "step_up_fresh": False}
    refused = phone.post("/api/auth/sign-out-everywhere", headers=WRITE)
    assert refused.status_code == 403
    assert desktop.get("/api/accounts").status_code == 200
    assert phone.post("/api/auth/step-up/code", headers=WRITE).status_code == 202
    code = h.last_code(ALICE)
    assert "#link=" not in h.mailer.sent[-1].text
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    bad = phone.post("/api/auth/step-up/verify", json={"code": wrong}, headers=WRITE)
    assert bad.status_code == 400
    ok = phone.post("/api/auth/step-up/verify", json={"code": code}, headers=WRITE)
    assert ok.status_code == 204
    assert phone.post("/api/auth/sign-out-everywhere", headers=WRITE).status_code == 204
    assert desktop.get("/api/accounts").status_code == 401
    assert phone.get("/api/accounts").status_code == 401


def test_right_after_signing_in_the_step_up_is_fresh(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    phone = h.sign_in(ALICE)
    assert phone.get("/api/auth/me").json()["step_up_fresh"] is True
    assert phone.post("/api/auth/sign-out-everywhere", headers=WRITE).status_code == 204


def test_deleting_the_account_needs_a_fresh_step_up(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    h.clock.advance(11 * 60)
    assert client.delete("/api/account", headers=WRITE).status_code == 403
    assert h.service.store.account_by_email(ALICE) is not None
    assert client.post("/api/auth/step-up/code", headers=WRITE).status_code == 202
    code = h.last_code(ALICE)
    assert (
        client.post("/api/auth/step-up/verify", json={"code": code}, headers=WRITE).status_code
        == 204
    )
    assert client.delete("/api/account", headers=WRITE).status_code == 204
    assert h.service.store.account_by_email(ALICE) is None
    assert client.get("/api/accounts").status_code == 401


def test_people_cannot_invite_people_by_default(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    answer = client.post("/api/invitations", json={"email": BOB}, headers=WRITE)
    assert answer.status_code == 403
    assert h.service.store.open_invitation(BOB, int(h.clock.now)) is None


def test_a_new_account_gets_an_empty_database_of_its_own(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    account = h.service.store.account_by_email(ALICE)
    assert account is not None
    folder = h.data / "users" / account.folder
    assert (folder / "michelito.db").is_file()
    assert folder.stat().st_mode & 0o777 == 0o700
    with pytest.raises(sqlite3.DatabaseError), sqlite3.connect(folder / "michelito.db") as conn:
        conn.execute("SELECT count(*) FROM transactions")  # encrypted: not without its key
    session = h.service.store.sessions_of(account.id)[0]
    workspace = h.service.workspace(session)
    conn = db.connect(workspace.database, workspace.key)
    try:
        assert conn.execute("SELECT count(*) FROM transactions").fetchone()[0] == 0
    finally:
        conn.close()


def test_a_session_only_ever_opens_its_own_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = hosted(tmp_path)
    alice = h.sign_in(ALICE)
    bob = h.sign_in(BOB)
    past_the_gate(h, ALICE, BOB)
    folders = {
        email: h.data / "users" / h.service.store.account_by_email(email).folder
        for email in (ALICE, BOB)
    }
    opened: list[Path] = []
    real = db.connect

    def spy(path: Path | str, key: bytes | None = None) -> sqlite3.Connection:
        opened.append(Path(path))
        return real(path, key)

    monkeypatch.setattr(db, "connect", spy)
    category = {"name": "Solo de Alice", "kind": "expense"}  # spanish-data
    assert alice.post("/api/categories", json=category, headers=WRITE).status_code == 201
    for path in ("/api/categories", "/api/accounts", "/api/log"):
        assert alice.get(path).status_code == 200
    assert opened and all(p.is_relative_to(folders[ALICE]) for p in opened)
    opened.clear()
    names = {c["name"] for c in bob.get("/api/categories").json()}
    assert "Solo de Alice" not in names  # spanish-data
    assert opened and all(p.is_relative_to(folders[BOB]) for p in opened)


def test_no_code_or_token_reaches_logs_or_error_bodies(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    token = client.cookies.get("session") or ""
    bodies = []
    bodies.append(client.post("/api/auth/code", json={"email": ALICE}, headers=WRITE).text)
    code = h.last_code(ALICE)
    link = h.last_link(ALICE)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    bodies.append(
        h.client()
        .post("/api/auth/verify", json={"email": ALICE, "code": wrong}, headers=WRITE)
        .text
    )
    bodies.append(h.client().post("/api/auth/link", json={"token": "x" * 40}, headers=WRITE).text)
    bodies.append(client.get("/api/auth/devices").text)
    bodies.append(client.get("/api/auth/me").text)
    bodies.append(client.get("/api/mode").text)
    everything = caplog.text + "".join(bodies) + repr(h.service) + repr(h.app.state.dispatcher)
    for secret in (code, link, token):
        assert secret not in everything


def test_a_signed_in_browser_replaces_its_old_session(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    h.sign_in(ALICE, client)
    assert len(h.service.store.sessions_of(1)) == 1


def test_phone_user_agent_is_reduced_to_names(tmp_path: Path) -> None:
    from michelito.hosted.devices import describe

    assert describe(PHONE) == ("Chrome", "Android")
    assert describe(DESKTOP) == ("Firefox", "Windows")
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Safari/604.1"
    assert describe(iphone) == ("Safari", "iOS")
    assert describe(None) == ("", "")


def test_each_account_has_its_own_shared_ledger(tmp_path: Path) -> None:
    """The Shared routes go through the same per-session database seam as the rest."""
    h = hosted(tmp_path)
    alice, bob = h.sign_in(ALICE), h.sign_in(BOB, h.client(DESKTOP))
    past_the_gate(h, ALICE, BOB)
    made = alice.post("/api/shared/groups", json={"name": "Trip"}, headers=WRITE)
    assert made.status_code == 201, made.text
    group = made.json()["id"]
    assert [g["name"] for g in alice.get("/api/shared").json()["groups"]] == ["Trip"]
    assert bob.get("/api/shared").json()["groups"] == []
    assert bob.get(f"/api/shared/groups/{group}").status_code == 404
    assert h.client().get("/api/shared").status_code == 401
