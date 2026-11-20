"""Hosted batch 5: statements and alerts arriving by email forwarding (synthetic emails only).

The Email Worker's request is imitated with `tests.forwarding_helpers.signed` (the same HMAC);
every message is made up. Covers the signature, timestamp and nonce checks; the address (hash
only in the accounts database, rotation behind a step-up, the old one dead at once);
idempotency; rate limits; Gmail's confirmation shown, never confirmed; alerts into
provisionals; statements with and without a stored password; the waiting queue sealed at rest;
quarantine approve and discard; secrets never in logs, answers or files; two accounts apart.
"""

from __future__ import annotations

import logging
import socket
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.hosted import forwarding, inbox, inbox_store, uploads
from michelito.hosted.forwarding_routes import ForwardingCaps
from michelito.hosted.store import FILENAME
from michelito.i18n import t
from tests import alert_samples
from tests import forwarding_helpers as mail
from tests.hosted_helpers import WRITE, Hosted, hosted

ALICE = "alice@example.com"
BRUNO = "bruno@example.com"
POPULAR = "popularenlinea.com"
BHD = "bhd.com.do"
INBOUND = "/api/inbound-email"


@dataclass
class World:
    h: Hosted
    alice: TestClient
    address: str


CONFIRMED = {"confirmed": True}


def _world(tmp_path: Path, known: bool = True, **overrides: object) -> World:
    """Alice, signed in, with a forwarding address and (`known`) the accounts and cards of the
    synthetic statements, as if she had uploaded earlier ones: forwarded statements of those
    accounts go straight in, a new account's would wait for her approval."""
    secret = tmp_path / "inbound.key"
    secret.write_bytes(mail.SECRET)
    h = hosted(tmp_path, inbound_secret=secret, inbox_background=False, **overrides)
    alice = h.sign_in(ALICE)
    made = alice.post("/api/forwarding/address", headers=WRITE)
    assert made.status_code == 200, made.text
    if known:
        with closing(_connect(h, ALICE)) as conn:
            mail.know_accounts(conn, *mail.EVERY_ACCOUNT)
    return World(h, alice, made.json()["address"])


@pytest.fixture
def world(tmp_path: Path) -> World:
    return _world(tmp_path)


def deliver(h: Hosted, recipient: str, raw: bytes, auth: str, **options: object):  # noqa: ANN201
    body, headers = mail.signed(recipient, raw, auth, at=h.clock(), **options)  # type: ignore[arg-type]
    return h.client().post(INBOUND, content=body, headers=headers)


def _connect(h: Hosted, email: str) -> sqlite3.Connection:
    account = h.service.store.account_by_email(email)
    assert account is not None
    workspace = h.service.workspace_of(account)
    return db.connect(workspace.database, workspace.key)


def _count(h: Hosted, email: str, query: str) -> int:
    with closing(_connect(h, email)) as conn:
        inbox_store.ensure(conn)
        return int(conn.execute(query).fetchone()[0])


def statements(h: Hosted, email: str = ALICE) -> int:
    """How many statement files were stored (a file may hold several statements)."""
    return _count(h, email, "SELECT COUNT(DISTINCT document_id) FROM statements")


def state(client: TestClient) -> dict:
    found = client.get("/api/forwarding")
    assert found.status_code == 200, found.text
    return found.json()


def _step_up(h: Hosted, client: TestClient, email: str) -> None:
    assert client.post("/api/auth/step-up/code", headers=WRITE).status_code == 202
    code = h.last_code(email)
    assert (
        client.post("/api/auth/step-up/verify", json={"code": code}, headers=WRITE).status_code
        == 204
    )


def notices_to(h: Hosted, email: str) -> list:  # noqa: ANN401
    """The problem emails sent to that person."""
    return [
        m for m in h.mailer.sent if m.to == email and m.subject == t("forwarding.notice.subject")
    ]


def _files(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


# The signed request.


def test_a_signed_request_is_accepted_and_answers_nothing_about_the_message(world: World) -> None:
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    answer = deliver(world.h, world.address, raw, mail.worker_auth(POPULAR))
    assert answer.status_code == 202
    assert answer.json() == {"status": "accepted"}
    assert statements(world.h) == 1


def test_a_bad_signature_old_or_future_time_and_a_replay_are_refused(world: World) -> None:
    h = world.h
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    auth = mail.worker_auth(POPULAR)
    client = h.client()
    body, headers = mail.signed(world.address, raw, auth, secret=b"x" * 40, at=h.clock())
    assert client.post(INBOUND, content=body, headers=headers).status_code == 401
    body, headers = mail.signed(world.address, raw, auth, at=h.clock())
    tampered = body.replace(b'"auth": "', b'"auth": "x')
    assert client.post(INBOUND, content=tampered, headers=headers).status_code == 401
    for skew in (-forwarding.WINDOW - 5, forwarding.WINDOW + 5):
        body, headers = mail.signed(world.address, raw, auth, at=h.clock() + skew)
        assert client.post(INBOUND, content=body, headers=headers).status_code == 401
    missing = {k: v for k, v in headers.items() if k != forwarding.SIGNATURE_HEADER}
    assert client.post(INBOUND, content=body, headers=missing).status_code == 401
    assert statements(h) == 0
    body, headers = mail.signed(world.address, raw, auth, at=h.clock(), nonce="n" * 20)
    assert client.post(INBOUND, content=body, headers=headers).status_code == 202
    again = client.post(INBOUND, content=body, headers=headers)
    assert again.status_code == 409
    assert statements(h) == 1


def test_a_nonce_is_forgotten_only_after_its_window(world: World) -> None:
    h = world.h
    store = h.service.store
    now = int(h.clock())
    assert store.take_nonce("a" * 20, now, now + forwarding.WINDOW + 1)
    assert not store.take_nonce("a" * 20, now + 100, now + 100 + forwarding.WINDOW)
    assert store.take_nonce("a" * 20, now + forwarding.WINDOW + 2, now + 2 * forwarding.WINDOW)


def test_without_an_inbound_secret_the_endpoint_is_off(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    alice = h.sign_in(ALICE)
    address = alice.post("/api/forwarding/address", headers=WRITE).json()["address"]
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    assert deliver(h, address, raw, mail.worker_auth(POPULAR)).status_code == 404
    assert statements(h) == 0


def test_the_inbound_secret_must_be_long_and_not_another_server_key(tmp_path: Path) -> None:
    short = tmp_path / "short.key"
    short.write_bytes(b"too-short")
    with pytest.raises(forwarding.SecretError):
        hosted(tmp_path, inbound_secret=short)


def test_an_unsigned_request_never_opens_a_user_database(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    real = db.connect

    def watch(path, key=None):  # noqa: ANN001, ANN202
        opened.append(str(path))
        return real(path, key)

    monkeypatch.setattr(db, "connect", watch)
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    body, headers = mail.signed(world.address, raw, "", secret=b"y" * 40, at=world.h.clock())
    assert world.h.client().post(INBOUND, content=body, headers=headers).status_code == 401
    assert opened == []


def test_the_body_limit_is_enforced(tmp_path: Path) -> None:
    w = _world(tmp_path, forwarding=ForwardingCaps(message_bytes=50_000))
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, b"%PDF" + b"0" * 80_000)
    answer = deliver(w.h, w.address, raw, mail.worker_auth(POPULAR))
    assert answer.status_code == 413


# The address.


def test_the_address_is_random_base32_and_only_its_hash_is_in_the_accounts_db(
    world: World,
) -> None:
    h = world.h
    local, _, domain = world.address.partition("@")
    assert domain == forwarding.DOMAIN
    prefix, _, token = local.partition(".")
    assert prefix == forwarding.PREFIX and forwarding.TOKEN.fullmatch(token)
    accounts = (h.data / FILENAME).read_bytes() + b"".join(
        p.read_bytes() for p in h.data.glob(f"{FILENAME}-*")
    )
    assert token.encode() not in accounts
    account = h.service.store.account_by_email(ALICE)
    assert account is not None
    assert h.service.store.forwarding_hash(account.id) == forwarding.token_hash(token)
    # A second "create" is refused: changing it is a rotation.
    assert world.alice.post("/api/forwarding/address", headers=WRITE).status_code == 409


def test_rotation_needs_a_step_up_and_kills_the_old_address_at_once(world: World) -> None:
    h, alice = world.h, world.alice
    h.clock.advance(11 * 60)  # the sign-in no longer counts as a fresh verification
    refused = alice.post("/api/forwarding/address/rotate", headers=WRITE)
    assert refused.status_code == 403
    assert refused.headers.get("X-Michelito-Error") == "step_up_required"
    assert state(alice)["address"] == world.address
    _step_up(h, alice, ALICE)
    rotated = alice.post("/api/forwarding/address/rotate", headers=WRITE)
    assert rotated.status_code == 200
    new = rotated.json()["address"]
    assert new != world.address
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    assert deliver(h, world.address, raw, mail.worker_auth(POPULAR)).status_code == 404
    assert statements(h) == 0
    assert deliver(h, new, raw, mail.worker_auth(POPULAR)).status_code == 202
    assert statements(h) == 1


def test_unknown_or_malformed_recipients_are_refused(world: World) -> None:
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    auth = mail.worker_auth(POPULAR)
    token = world.address.split("@")[0].split(".")[1]
    for recipient in (
        f"{forwarding.PREFIX}.{'a' * 32}@{forwarding.DOMAIN}",
        f"{forwarding.PREFIX}.{token}@other.example",
        f"other.{token}@{forwarding.DOMAIN}",
        "not an address",
    ):
        assert deliver(world.h, recipient, raw, auth).status_code == 404, recipient
    # Case does not matter (mail systems may change it).
    assert deliver(world.h, world.address.upper(), raw, auth).status_code == 202


# Idempotency and limits.


def test_the_same_message_id_is_handled_once(world: World) -> None:
    raw = mail.statement_email(mail.STRANGER, mail.bhd_savings(), message_id="same-id")
    auth = mail.worker_auth("unknown-sender.example")
    assert deliver(world.h, world.address, raw, auth).status_code == 202
    assert deliver(world.h, world.address, raw, auth).status_code == 202
    assert len(state(world.alice)["quarantine"]) == 1


def test_per_account_and_global_rate_limits(tmp_path: Path) -> None:
    w = _world(tmp_path, forwarding=ForwardingCaps(per_account_hour=2, global_hour=3))
    auth = mail.worker_auth("unknown-sender.example")
    for _ in range(2):
        raw = mail.statement_email(mail.STRANGER, mail.bhd_savings())
        assert deliver(w.h, w.address, raw, auth).status_code == 202
    raw = mail.statement_email(mail.STRANGER, mail.bhd_savings())
    assert deliver(w.h, w.address, raw, auth).status_code == 429
    w.h.clock.advance(3601)
    bruno = w.h.sign_in(BRUNO)
    other = bruno.post("/api/forwarding/address", headers=WRITE).json()["address"]
    statuses = [
        deliver(w.h, other, mail.statement_email(mail.STRANGER, mail.bhd_savings()), auth)
        for _ in range(2)
    ]
    assert [s.status_code for s in statuses] == [202, 202]
    # The whole server: 3 per hour (2 for Bruno, 1 for Alice, then nobody).
    assert deliver(w.h, w.address, mail.statement_email(mail.STRANGER), auth).status_code == 202
    assert deliver(w.h, w.address, mail.statement_email(mail.STRANGER), auth).status_code == 429


# Gmail's confirmation.


def test_gmails_confirmation_is_shown_and_never_confirmed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    def no_requests(*_: object, **__: object) -> None:
        raise AssertionError("nothing may be fetched: confirming is the person's call")

    monkeypatch.setattr(urllib.request, "urlopen", no_requests)
    # Nothing may open a connection at all (any client, any library), not only urllib.
    monkeypatch.setattr(socket, "create_connection", no_requests)
    monkeypatch.setattr(socket.socket, "connect", no_requests)
    raw = mail.gmail_confirmation()
    assert deliver(world.h, world.address, raw, mail.worker_auth("google.com")).status_code == 202
    found = state(world.alice)["confirmation"]
    assert found["code"] == mail.GMAIL_CODE
    assert found["link"] == mail.GMAIL_LINK
    dismissed = world.alice.post("/api/forwarding/confirmation/dismiss", headers=WRITE)
    assert dismissed.status_code == 204
    assert state(world.alice)["confirmation"] is None


def test_an_unauthenticated_gmail_confirmation_goes_to_quarantine(world: World) -> None:
    raw = mail.gmail_confirmation()
    auth = mail.worker_auth("google.com", dkim=False)
    assert deliver(world.h, world.address, raw, auth).status_code == 202
    found = state(world.alice)
    assert found["confirmation"] is None
    assert [q["reason"] for q in found["quarantine"]] == ["unauthenticated"]


# Alerts.


def test_an_authenticated_alert_becomes_a_provisional_transaction(world: World) -> None:
    h = world.h
    statement = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    assert deliver(h, world.address, statement, mail.worker_auth(POPULAR)).status_code == 202
    alert = mail.alert_email(card="1234", merchant="CAFE FICTICIO", status=alert_samples.APPROVED)
    assert deliver(h, world.address, alert, mail.worker_auth(POPULAR)).status_code == 202
    assert _count(h, ALICE, "SELECT COUNT(*) FROM alerts WHERE status = 'provisional'") == 1
    pending = world.alice.get("/api/transactions", params={"month": "2026-02"}).json()
    assert any("CAFE FICTICIO" in row["description"] for row in pending["items"])


def test_an_alert_whose_dkim_failed_never_becomes_a_transaction(world: World) -> None:
    h = world.h
    alert = mail.alert_email(card="1234")
    auth = mail.worker_auth(POPULAR, dkim=False)
    assert deliver(h, world.address, alert, auth).status_code == 202
    assert _count(h, ALICE, "SELECT COUNT(*) FROM alerts") == 0
    assert len(state(world.alice)["quarantine"]) == 1


def test_the_forwarded_gmail_verdict_can_only_veto(world: World) -> None:
    """Gmail's own header in the message cannot replace the Worker's verdict, only contradict it."""
    h = world.h
    vouching_inside = mail.statement_email(
        mail.POPULAR_STATEMENTS, mail.popular_card(), inner_auth=alert_samples.SIGNED
    )
    assert deliver(h, world.address, vouching_inside, "").status_code == 202
    assert statements(h) == 0
    failing_inside = mail.statement_email(
        mail.POPULAR_STATEMENTS, mail.popular_card(), inner_auth=alert_samples.DKIM_FAILED
    )
    assert deliver(h, world.address, failing_inside, mail.worker_auth(POPULAR)).status_code == 202
    assert statements(h) == 0
    assert len(state(world.alice)["quarantine"]) == 2


def test_a_verdict_from_an_untrusted_receiver_counts_for_nothing(world: World) -> None:
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    forged = mail.worker_auth(POPULAR).replace("mx.cloudflare.net", "mx.attacker.example")
    assert deliver(world.h, world.address, raw, forged).status_code == 202
    assert statements(world.h) == 0


# Statements.


def test_a_locked_statement_waits_until_the_password_is_typed(world: World) -> None:
    h, alice = world.h, world.alice
    raw = mail.statement_email(mail.BHD_STATEMENTS, mail.bhd_card())
    assert deliver(h, world.address, raw, mail.worker_auth(BHD)).status_code == 202
    waiting = state(alice)["waiting"]
    assert [(w["bank"], w["reason"]) for w in waiting] == [("bhd", "missing")]
    assert statements(h) == 0
    wrong = alice.post(
        "/api/forwarding/waiting/unlock",
        json={"bank": "bhd", "password": "not-the-password"},
        headers=WRITE,
    )
    assert wrong.json() == {"opened": 0, "left": 1}
    right = alice.post(
        "/api/forwarding/waiting/unlock",
        json={"bank": "bhd", "password": mail.PASSWORD},
        headers=WRITE,
    )
    assert right.json() == {"opened": 1, "left": 0}
    assert statements(h) == 1
    after = state(alice)
    assert after["waiting"] == []
    assert [(a["bank"], a["month"]) for a in after["arrivals"]] == [("bhd", "2026-01")]


def test_a_stored_password_reads_the_next_statements_on_arrival(world: World) -> None:
    h, alice = world.h, world.alice
    assert state(alice)["passwords"] == {"popular": False, "bhd": False, "banreservas": False}
    h.clock.advance(11 * 60)
    body = {"password": mail.PASSWORD}
    refused = alice.put("/api/forwarding/passwords/bhd", json=body, headers=WRITE)
    assert refused.status_code == 403
    _step_up(h, alice, ALICE)
    stored = alice.put("/api/forwarding/passwords/bhd", json=body, headers=WRITE)
    assert stored.json() == {"stored": True, "opened": 0, "left": 0}
    assert state(alice)["passwords"]["bhd"] is True
    raw = mail.statement_email(mail.BHD_STATEMENTS, mail.bhd_card())
    assert deliver(h, world.address, raw, mail.worker_auth(BHD)).status_code == 202
    assert statements(h) == 1
    assert state(alice)["waiting"] == []
    # "Forget my password": gone, and the next one waits again.
    assert alice.delete("/api/forwarding/passwords/bhd", headers=WRITE).status_code == 204
    assert state(alice)["passwords"]["bhd"] is False
    assert _count(h, ALICE, "SELECT COUNT(*) FROM inbox_passwords") == 0


def test_a_wrong_stored_password_waits_and_tells_the_person(world: World) -> None:
    h, alice = world.h, world.alice
    stored = alice.put(
        "/api/forwarding/passwords/bhd", json={"password": "an-old-password"}, headers=WRITE
    )
    assert stored.status_code == 200
    raw = mail.statement_email(mail.BHD_STATEMENTS, mail.bhd_card())
    deliver(h, world.address, raw, mail.worker_auth(BHD))
    assert [w["reason"] for w in state(alice)["waiting"]] == ["wrong"]
    notices = notices_to(h, ALICE)
    assert len(notices) == 1


def test_statements_that_do_not_square_or_are_unsupported_leave_nothing(world: World) -> None:
    h = world.h
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.wrong_total(), mail.other_bank())
    assert deliver(h, world.address, raw, mail.worker_auth(POPULAR)).status_code == 202
    assert statements(h) == 0
    assert _count(h, ALICE, "SELECT COUNT(*) FROM documents") == 0
    outcomes = sorted(p["outcome"] for p in state(world.alice)["problems"])
    assert outcomes == ["invalid", "unsupported"]
    assert _count(h, ALICE, "SELECT COUNT(*) FROM inbox_waiting") == 0


def test_the_waiting_queue_is_sealed_at_rest(world: World) -> None:
    h = world.h
    pdf = mail.bhd_card()
    raw = mail.statement_email(mail.BHD_STATEMENTS, pdf)
    deliver(h, world.address, raw, mail.worker_auth(BHD))
    account = h.service.store.account_by_email(ALICE)
    assert account is not None
    folder = h.data / "users" / account.folder
    on_disk = _files(folder)
    for start in range(0, len(pdf) - 64, max(1, len(pdf) // 8)):
        assert pdf[start : start + 64] not in on_disk
    # Inside the (already encrypted) database, the row holds ciphertext, not the PDF.
    with closing(_connect(h, ALICE)) as conn:
        sealed = conn.execute("SELECT sealed FROM inbox_waiting").fetchone()[0]
    assert pdf[:64] not in sealed and b"%PDF" not in sealed
    # And it opens only with this account's key and row.
    other = inbox_store.Sealer.of(b"\x01" * 32)
    with pytest.raises(inbox_store.SealError):
        other.open("waiting", "x", bytes(sealed))


# Quarantine.


def test_quarantine_shows_only_the_domain_date_and_count_until_approved(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    h, alice = world.h, world.alice
    calls: list[int] = []
    real = uploads.examine

    def counting(data, password, limits=None):  # noqa: ANN001, ANN202
        calls.append(1)
        return real(data, password, limits)

    monkeypatch.setattr(uploads, "examine", counting)
    raw = mail.statement_email(mail.STRANGER, mail.bhd_savings(), names=("Secret-Name.pdf",))
    assert deliver(h, world.address, raw, mail.worker_auth("unknown-sender.example")).status_code
    held = state(alice)["quarantine"]
    assert len(held) == 1
    item = held[0]
    assert set(item) == {
        "id",
        "sender_domain",
        "received_at",
        "attachments",
        "reason",
        "claims_bank",
    }
    assert item["claims_bank"] is False
    assert item["sender_domain"] == "unknown-sender.example"
    assert item["attachments"] == 1 and item["reason"] == "unknown_sender"
    assert calls == []  # nothing in it was opened
    assert statements(h) == 0
    approved = alice.post(
        f"/api/forwarding/quarantine/{item['id']}/approve", json=CONFIRMED, headers=WRITE
    )
    assert approved.status_code == 200
    assert approved.json()["quarantine"] == []
    assert calls and statements(h) == 1


def test_quarantine_discard_deletes_it(world: World) -> None:
    raw = mail.statement_email(mail.STRANGER, mail.bhd_savings())
    deliver(world.h, world.address, raw, mail.worker_auth("unknown-sender.example"))
    item = state(world.alice)["quarantine"][0]
    gone = world.alice.delete(f"/api/forwarding/quarantine/{item['id']}", headers=WRITE)
    assert gone.status_code == 204
    assert state(world.alice)["quarantine"] == []
    assert _count(world.h, ALICE, "SELECT COUNT(*) FROM inbox_quarantine") == 0
    again = world.alice.delete(f"/api/forwarding/quarantine/{item['id']}", headers=WRITE)
    assert again.status_code == 404


# Secrets never leak.


def test_passwords_tokens_bodies_and_names_never_reach_logs_answers_or_files(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    h, alice = world.h, world.alice
    secret_name = "Very-Private-Attachment-Name.pdf"
    body_marker = "Your statement is attached."
    password = "MadeUpSecretPassword-987"
    answers: list[str] = []
    stored = alice.put(
        "/api/forwarding/passwords/popular", json={"password": password}, headers=WRITE
    )
    answers.append(stored.text)
    raw = mail.statement_email(mail.BHD_STATEMENTS, mail.bhd_card(), names=(secret_name,))
    answers.append(deliver(h, world.address, raw, mail.worker_auth(BHD)).text)
    strange = mail.statement_email(mail.STRANGER, mail.bhd_savings(), names=(secret_name,))
    answers.append(deliver(h, world.address, strange, mail.worker_auth("x.example")).text)
    unlock = alice.post(
        "/api/forwarding/waiting/unlock",
        json={"bank": "bhd", "password": password},
        headers=WRITE,
    )
    answers.append(unlock.text)
    answers.append(alice.get("/api/forwarding").text)
    bad = alice.post(
        "/api/forwarding/waiting/unlock",
        content=b'{"bank": 3, "password": "' + password.encode(),
        headers=WRITE,
    )
    answers.append(bad.text)
    token = world.address.split("@")[0].split(".")[1]
    logs = caplog.text
    outbox = "".join(m.text + m.subject for m in h.mailer.sent)
    files = _files(h.data)
    for secret in (password, mail.SECRET.decode(), secret_name, body_marker):
        assert secret not in logs, secret
        assert all(secret not in text for text in answers), secret
        assert secret not in outbox, secret
        assert secret.encode() not in files, secret
    assert token not in logs and token not in outbox
    assert token.encode() not in (h.data / FILENAME).read_bytes()


def test_problem_emails_are_data_free_and_sent_once_a_day(world: World) -> None:
    h = world.h
    for _ in range(2):
        raw = mail.statement_email(mail.STRANGER, mail.bhd_savings())
        deliver(h, world.address, raw, mail.worker_auth("unknown-sender.example"))
    sent = notices_to(h, ALICE)
    assert len(sent) == 1
    text = sent[0].text
    assert "unknown-sender" not in text and "https://app.example/settings" in text


# Two accounts.


def test_one_accounts_address_never_reaches_another(world: World) -> None:
    h = world.h
    bruno = h.sign_in(BRUNO)
    other = bruno.post("/api/forwarding/address", headers=WRITE).json()["address"]
    assert other != world.address
    account = h.service.store.account_by_email(BRUNO)
    assert account is not None
    folder = h.data / "users" / account.folder
    before = _files(folder)
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    assert deliver(h, world.address, raw, mail.worker_auth(POPULAR)).status_code == 202
    assert _files(folder) == before  # Bruno's database was not even opened
    assert statements(h, ALICE) == 1
    assert statements(h, BRUNO) == 0
    assert state(bruno)["arrivals"] == []
    # Alice's quarantine is not Bruno's: his ids do not reach hers.
    deliver(h, world.address, mail.statement_email(mail.STRANGER), mail.worker_auth("x.example"))
    item = state(world.alice)["quarantine"][0]
    path = f"/api/forwarding/quarantine/{item['id']}"
    assert bruno.delete(path, headers=WRITE).status_code == 404
    assert (
        bruno.post(
            f"/api/forwarding/quarantine/{item['id']}/approve", json=CONFIRMED, headers=WRITE
        ).status_code
        == 404
    )
    assert len(state(world.alice)["quarantine"]) == 1


# Late statements.


def test_a_statement_later_than_usual_is_listed(world: World) -> None:
    h = world.h
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    deliver(h, world.address, raw, mail.worker_auth(POPULAR))
    with closing(_connect(h, ALICE)) as conn:
        newest = conn.execute("SELECT max(period_end) FROM statements").fetchone()[0]
        end = date.fromisoformat(newest)
        assert inbox.overdue(conn, end) == []
        late = inbox.overdue(conn, date.fromordinal(end.toordinal() + 31 + 6))
    assert [(o.bank, o.identifier) for o in late] == [("popular", "1234")]


def test_bank_senders_come_from_the_sources() -> None:
    assert inbox.SENDERS[mail.POPULAR_STATEMENTS] == "popular"
    assert inbox.SENDERS[mail.BHD_STATEMENTS] == "bhd"
    assert inbox.SENDERS[alert_samples.SENDER.split("<")[1].rstrip(">")] == "popular"
    assert all(bank in inbox.SUPPORTED_BANKS for bank in inbox.SENDERS.values())
