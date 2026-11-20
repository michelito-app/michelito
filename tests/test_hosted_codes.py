"""Hosted mode: sign-in codes (expiry, single use, lockout, hashed storage, no enumeration,
rate limits) and invitations. Synthetic addresses only."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tests.hosted_helpers import WRITE, hosted

ALICE = "alice@example.com"


def _verify(client: TestClient, email: str, code: str) -> int:
    answer = client.post("/api/auth/verify", json={"email": email, "code": code}, headers=WRITE)
    return answer.status_code


def _ask(client: TestClient, email: str) -> int:
    return client.post("/api/auth/code", json={"email": email}, headers=WRITE).status_code


def test_an_invited_email_signs_in_with_its_code(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.service.invite(ALICE)
    client = h.client()
    assert client.get("/api/mode").json()["session"] is False
    assert _verify(client, ALICE, h.last_code(ALICE)) == 204
    assert client.get("/api/mode").json() == {
        "mode": "hosted",
        "name": "Michelito",
        "demo_url": "https://demo.michelito.app",
        "session": True,
    }
    # A new account is behind the upload gate: signed in, but only the gate's routes answer.
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/accounts").status_code == 403


def test_a_login_code_works_once(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    other = h.client()
    assert _ask(other, ALICE) == 202
    code = h.last_code(ALICE)
    assert _verify(other, ALICE, code) == 204
    assert _verify(h.client(), ALICE, code) == 400


def test_a_code_expires_after_ten_minutes(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    client = h.client()
    _ask(client, ALICE)
    code = h.last_code(ALICE)
    h.clock.advance(10 * 60 + 1)
    assert _verify(client, ALICE, code) == 400


def test_five_wrong_attempts_invalidate_the_code(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    client = h.client()
    _ask(client, ALICE)
    code = h.last_code(ALICE)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(5):
        assert _verify(client, ALICE, wrong) == 400
    assert _verify(client, ALICE, code) == 400


def test_four_wrong_attempts_still_leave_the_code(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    client = h.client()
    _ask(client, ALICE)
    code = h.last_code(ALICE)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(4):
        _verify(client, ALICE, wrong)
    assert _verify(client, ALICE, code) == 204


def test_only_hashes_are_stored(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    _ask(client, ALICE)
    code = h.last_code(ALICE)
    token = client.cookies.get("session")
    assert token
    raw = (h.data / "accounts.db").read_bytes()
    for wal in h.data.glob("accounts.db-*"):
        raw += wal.read_bytes()
    assert code.encode() not in raw
    assert token.encode() not in raw
    with sqlite3.connect(h.data / "accounts.db") as conn:
        hashes = [row[0] for row in conn.execute("SELECT code_hash FROM login_codes")]
    assert all(len(value) == 64 and code not in value for value in hashes)


def test_asking_for_a_code_answers_alike_for_unknown_emails(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    sent = len(h.mailer.sent)
    known = h.client().post("/api/auth/code", json={"email": ALICE}, headers=WRITE)
    unknown = h.client().post("/api/auth/code", json={"email": "nobody@example.com"}, headers=WRITE)
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert len(h.mailer.sent) == sent + 1  # only the account got an email
    assert _verify(h.client(), "nobody@example.com", "123456") == 400


def test_asking_for_a_code_takes_the_same_minimum_time(tmp_path: Path) -> None:
    h = hosted(tmp_path, floor=0.2)
    h.sign_in(ALICE)

    def timed(email: str) -> float:
        started = time.perf_counter()
        _ask(h.client(), email)
        return time.perf_counter() - started

    known, unknown = timed(ALICE), timed("nobody@example.com")
    assert known >= 0.2 and unknown >= 0.2
    assert abs(known - unknown) < 0.1
    wrong = time.perf_counter()
    _verify(h.client(), "nobody@example.com", "000000")
    assert time.perf_counter() - wrong >= 0.2


def test_three_codes_per_email_per_quarter_hour(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    for email in (ALICE, "nobody@example.com"):  # unknown emails are limited alike
        statuses = [_ask(h.client(), email) for _ in range(4)]
        assert statuses == [202, 202, 202, 429]
    h.clock.advance(15 * 60 + 1)
    assert _ask(h.client(), ALICE) == 202


def test_codes_per_ip_are_capped(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    statuses = [_ask(client, f"person{n}@example.com") for n in range(11)]
    assert statuses[:10] == [202] * 10
    assert statuses[10] == 429


def test_checks_per_ip_are_capped(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    statuses = [_verify(client, f"p{n}@example.com", "123456") for n in range(31)]
    assert statuses[-1] == 429
    assert set(statuses[:30]) == {400}


def test_without_an_invitation_no_account_is_created(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    assert _ask(client, "stranger@example.com") == 202
    assert h.mailer.sent == []
    for code in ("000000", "123456"):
        assert _verify(client, "stranger@example.com", code) == 400
    assert h.service.store.account_by_email("stranger@example.com") is None
    assert not (h.data / "users").exists()


def test_an_invitation_is_single_use_and_bound_to_its_email(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.service.invite(ALICE)
    code = h.last_code(ALICE)
    assert _verify(h.client(), "bob@example.com", code) == 400
    assert _verify(h.client(), ALICE, code) == 204
    assert _verify(h.client(), ALICE, code) == 400
    with sqlite3.connect(h.data / "accounts.db") as conn:
        assert conn.execute("SELECT count(*) FROM accounts").fetchone()[0] == 1
        assert conn.execute("SELECT used_at FROM invitations").fetchone()[0] is not None


def test_an_invited_email_can_also_ask_for_a_fresh_code(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.service.invite(ALICE)
    client = h.client()
    assert _ask(client, ALICE) == 202
    assert len(h.mailer.sent) == 1  # the invitation's code is in the inbox: no second email yet
    h.clock.advance(61)
    assert _ask(client, ALICE) == 202
    assert len(h.mailer.sent) == 2
    assert _verify(client, ALICE, h.last_code(ALICE)) == 204


def test_an_invitation_expires(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.service.invite(ALICE)
    code = h.last_code(ALICE)
    h.clock.advance(7 * 24 * 3600 + 1)
    assert _verify(h.client(), ALICE, code) == 400
    assert h.service.store.account_by_email(ALICE) is None


def test_the_desktop_link_signs_in_once(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    _ask(h.client(), ALICE)
    token = h.last_link(ALICE)
    assert "https://app.example/#link=" in h.mailer.sent[-1].text
    desk = h.client()
    assert desk.post("/api/auth/link", json={"token": token}, headers=WRITE).status_code == 204
    assert desk.get("/api/accounts").status_code == 200
    again = h.client().post("/api/auth/link", json={"token": token}, headers=WRITE)
    assert again.status_code == 400


def test_the_email_says_only_code_expiry_and_warning(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    _ask(h.client(), ALICE)
    email = h.mailer.sent[-1]
    assert email.to == ALICE
    assert h.last_code(ALICE) in email.text
    assert "10 minutos" in email.text  # spanish-ui
    assert "Si no fuiste tú" in email.text  # spanish-ui
    assert "RD$" not in email.text and "<" not in email.text  # plain text, nothing financial


def test_a_malformed_email_is_rejected_without_sending(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    assert _ask(h.client(), "not-an-email") == 422
    assert h.mailer.sent == []
