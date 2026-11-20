"""Email forwarding, the security review's round: budgets, idempotency by trust class, approving
with care, someone else's genuine mail, Gmail's link, limits before the signature and the
address race. Synthetic emails only (see `tests.forwarding_helpers`)."""

from __future__ import annotations

import threading
from contextlib import closing
from pathlib import Path

import anyio
import pytest
from starlette.requests import Request

from michelito.hosted import forwarding, inbound_mail, inbox_store
from michelito.hosted.forwarding_routes import ENVELOPE, ForwardingCaps, read_exactly
from michelito.hosted.keys import load_master
from tests import alert_samples, samples
from tests import forwarding_helpers as mail
from tests.hosted_helpers import WRITE, hosted, master_file
from tests.test_hosted_forwarding import (
    ALICE,
    BHD,
    CONFIRMED,
    INBOUND,
    POPULAR,
    World,
    _connect,
    _count,
    _world,
    deliver,
    notices_to,
    state,
    statements,
)

STRANGER_DOMAIN = "unknown-sender.example"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return _world(tmp_path)


@pytest.fixture
def newcomer(tmp_path: Path) -> World:
    """Alice without any account yet (nothing uploaded)."""
    return _world(tmp_path, known=False)


# 2. The global budget is charged only once the address resolves.


def test_unknown_recipients_never_spend_the_real_accounts_budget(tmp_path: Path) -> None:
    w = _world(tmp_path, forwarding=ForwardingCaps(global_hour=2, unknown_hour=3))
    raw = mail.statement_email(mail.STRANGER)
    auth = mail.worker_auth(STRANGER_DOMAIN)
    guessed = f"{forwarding.PREFIX}.{'a' * 32}@{forwarding.DOMAIN}"
    for _ in range(10):  # well past both budgets: always the same permanent 404
        assert deliver(w.h, guessed, raw, auth).status_code == 404
        assert deliver(w.h, "not-an-address@example.com", raw, auth).status_code == 404
    for _ in range(2):
        fresh = mail.statement_email(mail.STRANGER)
        assert deliver(w.h, w.address, fresh, auth).status_code == 202
    assert deliver(w.h, w.address, mail.statement_email(mail.STRANGER), auth).status_code == 429


# 3. Idempotency by trust class.


def test_a_forged_message_id_never_blocks_the_genuine_message(world: World) -> None:
    h = world.h
    forged = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card(), message_id="real")
    assert deliver(h, world.address, forged, mail.worker_auth(POPULAR, dkim=False)).status_code
    assert len(state(world.alice)["quarantine"]) == 1
    assert statements(h) == 0
    genuine = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card(), message_id="real")
    assert deliver(h, world.address, genuine, mail.worker_auth(POPULAR)).status_code == 202
    assert statements(h) == 1
    # The genuine one again is a duplicate; the forged one again stays a single item.
    deliver(h, world.address, genuine, mail.worker_auth(POPULAR))
    deliver(h, world.address, forged, mail.worker_auth(POPULAR, dkim=False))
    assert statements(h) == 1
    assert len(state(world.alice)["quarantine"]) == 1


def test_quarantine_dedupes_by_bytes_and_discarding_forgets_the_key(world: World) -> None:
    h, alice = world.h, world.alice
    auth = mail.worker_auth(STRANGER_DOMAIN)
    one = mail.statement_email(mail.STRANGER, mail.bhd_savings(), message_id="same")
    other = mail.statement_email(mail.STRANGER, mail.other_bank(), message_id="same")
    deliver(h, world.address, one, auth)
    deliver(h, world.address, one, auth)
    deliver(h, world.address, other, auth)  # same Message-ID, other bytes: its own item
    held = state(alice)["quarantine"]
    assert len(held) == 2
    for item in held:
        assert alice.delete(f"/api/forwarding/quarantine/{item['id']}", headers=WRITE).status_code
    assert _count(h, ALICE, "SELECT COUNT(*) FROM inbox_messages") == 0
    deliver(h, world.address, one, auth)  # discarded: received again
    assert len(state(alice)["quarantine"]) == 1


# 4. Approving takes an explicit step; what entered is marked and can be taken back.


def test_approving_needs_an_explicit_confirmation(world: World) -> None:
    h, alice = world.h, world.alice
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    deliver(h, world.address, raw, mail.worker_auth(POPULAR, dkim=False))
    item = state(alice)["quarantine"][0]
    assert item["claims_bank"] is True and item["reason"] == "unauthenticated"
    path = f"/api/forwarding/quarantine/{item['id']}/approve"
    for body in (None, {"confirmed": False}):
        refused = alice.post(path, json=body, headers=WRITE)
        assert refused.status_code == 409
        assert refused.headers["X-Michelito-Error"] == "confirmation_required"
    assert statements(h) == 0
    assert alice.post(path, json=CONFIRMED, headers=WRITE).status_code == 200
    assert statements(h) == 1


def test_what_entered_by_approval_is_marked_and_can_be_taken_back(world: World) -> None:
    h, alice = world.h, world.alice
    raw = mail.statement_email(mail.STRANGER, mail.bhd_savings())
    deliver(h, world.address, raw, mail.worker_auth(STRANGER_DOMAIN))
    item = state(alice)["quarantine"][0]
    approved = alice.post(
        f"/api/forwarding/quarantine/{item['id']}/approve", json=CONFIRMED, headers=WRITE
    ).json()
    assert [(a["kind"], a["sender_domain"]) for a in approved["approvals"]] == [
        ("statement", STRANGER_DOMAIN)
    ]
    with closing(_connect(h, ALICE)) as conn:
        months = [
            str(r[0])
            for r in conn.execute("SELECT DISTINCT substr(transacted_on, 1, 7) FROM transactions")
        ]
    rows = [
        row
        for month in months
        for row in alice.get("/api/transactions", params={"month": month}).json()["items"]
    ]
    assert rows and all(row["approved"] for row in rows)
    approval = approved["approvals"][0]
    back = alice.post(f"/api/forwarding/approvals/{approval['id']}/undo", headers=WRITE)
    assert back.status_code == 200
    assert back.json()["approvals"] == []
    assert statements(h) == 0
    assert _count(h, ALICE, "SELECT COUNT(*) FROM transactions") == 0


def test_an_approved_alert_is_taken_back_through_the_log(world: World) -> None:
    h, alice = world.h, world.alice
    alert = mail.alert_email(card="1234", merchant="CAFE APROBADO")  # spanish-data
    deliver(h, world.address, alert, mail.worker_auth(POPULAR, dkim=False))
    item = state(alice)["quarantine"][0]
    approved = alice.post(
        f"/api/forwarding/quarantine/{item['id']}/approve", json=CONFIRMED, headers=WRITE
    ).json()
    assert [a["kind"] for a in approved["approvals"]] == ["alert"]
    assert _count(h, ALICE, "SELECT COUNT(*) FROM alerts") == 1
    approval = approved["approvals"][0]
    assert (
        alice.post(f"/api/forwarding/approvals/{approval['id']}/undo", headers=WRITE).status_code
        == 200
    )
    entries = alice.get("/api/log").json()["items"]
    assert any(entry.get("kind") == "provisional" for entry in entries), entries
    # Its provisional no longer counts (discarded), and the log can undo that.
    assert _count(h, ALICE, "SELECT COUNT(*) FROM provisional_decisions") == 1


# 5. Someone else's genuine mail: what would be a first waits for the person.


def test_an_alert_on_a_card_never_seen_goes_to_quarantine(world: World) -> None:
    h, alice = world.h, world.alice
    alert = mail.alert_email(card=alert_samples.OTHER_CARD)
    assert deliver(h, world.address, alert, mail.worker_auth(POPULAR)).status_code == 202
    assert _count(h, ALICE, "SELECT COUNT(*) FROM alerts") == 0
    held = state(alice)["quarantine"]
    assert [(q["reason"], q["claims_bank"]) for q in held] == [("unknown_card", True)]
    alice.post(f"/api/forwarding/quarantine/{held[0]['id']}/approve", json=CONFIRMED, headers=WRITE)
    assert _count(h, ALICE, "SELECT COUNT(*) FROM alerts") == 1


def test_a_statement_of_a_new_account_waits_for_approval(newcomer: World) -> None:
    h, alice = newcomer.h, newcomer.alice
    raw = mail.statement_email(mail.POPULAR_STATEMENTS, mail.popular_card())
    assert deliver(h, newcomer.address, raw, mail.worker_auth(POPULAR)).status_code == 202
    assert statements(h) == 0
    held = state(alice)["waiting"]
    assert [(w["state"], w["reason"]) for w in held] == [("approval", "new_account")]
    assert len(notices_to(h, ALICE)) == 1
    path = f"/api/forwarding/waiting/{held[0]['id']}/approve"
    assert alice.post(path, headers=WRITE).status_code == 409  # the explicit step first
    done = alice.post(path, json=CONFIRMED, headers=WRITE)
    assert done.status_code == 200
    assert done.json()["waiting"] == []
    assert statements(h) == 1
    # A later statement of the same account goes straight in.
    again = mail.statement_email(mail.BHD_STATEMENTS, mail.bhd_savings())
    deliver(h, newcomer.address, again, mail.worker_auth(BHD))
    assert [w["state"] for w in state(alice)["waiting"]] == ["approval"]
    discarded = state(alice)["waiting"][0]
    assert alice.delete(f"/api/forwarding/waiting/{discarded['id']}", headers=WRITE).status_code
    assert _count(h, ALICE, "SELECT COUNT(*) FROM inbox_waiting") == 0


def test_a_full_queue_tells_the_person(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inbox_store, "MAX_QUARANTINE", 1)
    w = _world(tmp_path)
    auth = mail.worker_auth(STRANGER_DOMAIN)
    deliver(w.h, w.address, mail.statement_email(mail.STRANGER), auth)
    deliver(w.h, w.address, mail.statement_email(mail.STRANGER), auth)
    assert len(state(w.alice)["quarantine"]) == 1
    texts = [m.text for m in notices_to(w.h, ALICE)]
    assert any("espera est" in text for text in texts)  # spanish-ui: the queue-full notice
    assert [p["outcome"] for p in state(w.alice)["problems"]] == ["full"]


# 6. Gmail's confirmation.


@pytest.mark.parametrize(
    "link",
    [
        "https://mail-settings.google.com/mail/vf-%5Bx%5D-../../evil",
        "https://mail-settings.google.com/mail/vf-%2e%2e/x",
        "https://mail-settings.google.com/url?q=https://evil.example",
        "https://mail.google.com/mail/vf-x?continue=https://evil.example",
        "https://mail-settings.google.com.evil.example/mail/vf-x",
        "http://mail-settings.google.com/mail/vf-x",
        "https://evil.example/mail/vf-x",
    ],
)
def test_gmails_link_is_rebuilt_from_the_allowlist_only(world: World, link: str) -> None:
    raw = mail.gmail_confirmation(link=link)
    deliver(world.h, world.address, raw, mail.worker_auth("google.com"))
    found = state(world.alice)["confirmation"]
    assert found["code"] == mail.GMAIL_CODE
    if "?continue=" in link:  # the query is dropped, the path kept
        assert found["link"] == "https://mail.google.com/mail/vf-x"
    else:
        assert found["link"] is None


def test_the_confirmation_shows_who_asked(world: World) -> None:
    deliver(world.h, world.address, mail.gmail_confirmation(), mail.worker_auth("google.com"))
    found = state(world.alice)["confirmation"]
    assert found["requester"] == "someone@example.com"
    assert found["link"] == mail.GMAIL_LINK


def test_an_approved_quarantined_confirmation_never_reaches_the_panel(world: World) -> None:
    h, alice = world.h, world.alice
    deliver(h, world.address, mail.gmail_confirmation(), mail.worker_auth("google.com", dkim=False))
    item = state(alice)["quarantine"][0]
    alice.post(f"/api/forwarding/quarantine/{item['id']}/approve", json=CONFIRMED, headers=WRITE)
    after = state(alice)
    assert after["confirmation"] is None and after["quarantine"] == []


def test_safe_link_rejects_encoded_tricks() -> None:
    assert inbound_mail.safe_link(mail.GMAIL_LINK) == mail.GMAIL_LINK
    for bad in ("https://mail.google.com/mail/vf-%2Fx", "https://mail.google.com/url", None, ""):
        assert inbound_mail.safe_link(bad) is None


# 7. Failed signatures are limited (never signed mail), and the body limit fits the message.


def test_failed_signatures_are_limited_and_never_block_signed_mail(tmp_path: Path) -> None:
    """The Worker's egress is shared: junk from the same network (or anywhere) fills only the
    failed-signature buckets, and a validly signed request still goes through."""
    w = _world(tmp_path, forwarding=ForwardingCaps(per_source_minute=3, unsigned_minute=100))
    client = w.h.client()
    unsigned = {"Content-Type": "application/json", "X-Michelito": "1"}
    statuses = [client.post(INBOUND, content=b"{}", headers=unsigned).status_code for _ in range(5)]
    assert statuses == [401, 401, 401, 429, 429]
    for _ in range(3):  # a valid request from the same exhausted source: never refused
        raw = mail.statement_email(mail.STRANGER)
        assert deliver(w.h, w.address, raw, mail.worker_auth(STRANGER_DOMAIN)).status_code == 202
    w.h.clock.advance(61)
    assert client.post(INBOUND, content=b"{}", headers=unsigned).status_code == 401


def test_the_whole_server_budget_for_failed_signatures(tmp_path: Path) -> None:
    w = _world(tmp_path, forwarding=ForwardingCaps(per_source_minute=1000, unsigned_minute=2))
    client = w.h.client()
    body, headers = mail.signed(
        w.address, mail.statement_email(mail.STRANGER), "", secret=b"z" * 40
    )
    statuses = [client.post(INBOUND, content=body, headers=headers).status_code for _ in range(3)]
    assert statuses == [401, 401, 429]
    raw = mail.statement_email(mail.STRANGER)
    assert deliver(w.h, w.address, raw, mail.worker_auth(STRANGER_DOMAIN)).status_code == 202


def test_bad_headers_or_time_are_refused_without_reading_the_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, forwarding=ForwardingCaps(per_source_minute=4))
    read: list[int] = []
    real = Request.stream

    def watched(self: Request):  # noqa: ANN202
        read.append(1)
        return real(self)

    monkeypatch.setattr(Request, "stream", watched)
    body, good = mail.signed(w.address, mail.statement_email(mail.STRANGER), "", at=w.h.clock())
    stale = dict(good, **{forwarding.TIMESTAMP_HEADER: str(int(w.h.clock()) - 400)})
    cases = [
        {k: v for k, v in good.items() if k != forwarding.SIGNATURE_HEADER},
        dict(good, **{forwarding.NONCE_HEADER: "short"}),
        dict(good, **{forwarding.SIGNATURE_HEADER: "not-hex"}),
        stale,
    ]
    client = w.h.client()
    assert [client.post(INBOUND, content=body, headers=h).status_code for h in cases] == [401] * 4
    assert read == []  # none of them got its body read
    # They count as failed signatures: the source's bucket (4) is now full.
    assert client.post(INBOUND, content=body, headers=cases[0]).status_code == 429
    assert read == []
    # A full failed-signature bucket never refuses a well-formed request before its body:
    assert client.post(INBOUND, content=body, headers=good).status_code == 202
    assert read  # only this one was read


def test_concurrent_body_reads_are_capped(tmp_path: Path) -> None:
    w = _world(tmp_path, forwarding=ForwardingCaps(concurrent_reads=1))
    slots = w.h.app.state.forwarding.reads
    assert slots.enter()  # another request is reading its body
    raw = mail.statement_email(mail.STRANGER)
    busy = deliver(w.h, w.address, raw, mail.worker_auth(STRANGER_DOMAIN))
    assert busy.status_code == 503  # the Worker throws on it: Email Routing retries
    slots.leave()
    again = deliver(w.h, w.address, raw, mail.worker_auth(STRANGER_DOMAIN))
    assert again.status_code == 202
    assert slots.enter()  # released after each request, whatever happened
    slots.leave()


def test_the_mac_is_computed_incrementally_like_the_whole_body() -> None:
    body = b'{"recipient": "x", "raw": "' + b"A" * 70_000 + b'"}'
    mac = forwarding.Mac(mail.SECRET, "1800000000", "n" * 20)
    for start in range(0, len(body), 4096):
        mac.update(body[start : start + 4096])
    assert mac.matches(forwarding.sign(mail.SECRET, "1800000000", "n" * 20, body))
    assert not mac.matches(forwarding.sign(mail.SECRET, "1800000000", "n" * 20, body + b" "))
    tag = forwarding.preauth(mail.SECRET, "1800000000", "n" * 20, len(body))
    args = (mail.SECRET, "1800000000", "n" * 20, "0" * 64, tag, len(body))
    assert forwarding.precheck(*args, 1_800_000_100) == 1_800_000_000
    assert forwarding.precheck(*args, 1_800_000_400) is None  # outside the window
    wrong_length = (*args[:5], len(body) + 1)
    assert forwarding.precheck(*wrong_length, 1_800_000_100) is None
    other_key = (b"k" * 40, *args[1:])
    assert forwarding.precheck(*other_key, 1_800_000_100) is None


def test_without_a_valid_preauth_no_read_slot_is_taken(tmp_path: Path) -> None:
    """Only the Worker can make the tag: a request without it never takes a slot (refused
    cheaply as a failed signature, even while every slot is busy), one with it does."""
    w = _world(tmp_path, forwarding=ForwardingCaps(concurrent_reads=1))
    slots = w.h.app.state.forwarding.reads
    assert slots.enter()  # every slot busy
    client = w.h.client()
    body, good = mail.signed(w.address, mail.statement_email(mail.STRANGER), "", at=w.h.clock())
    forged = dict(good, **{forwarding.PREAUTH_HEADER: "0" * 64})
    missing = {k: v for k, v in good.items() if k != forwarding.PREAUTH_HEADER}
    other_length = dict(
        good,
        **{
            forwarding.PREAUTH_HEADER: forwarding.preauth(
                mail.SECRET,
                good[forwarding.TIMESTAMP_HEADER],
                good[forwarding.NONCE_HEADER],
                len(body) + 10,
            )
        },
    )
    for headers in (forged, missing, other_length):
        assert client.post(INBOUND, content=body, headers=headers).status_code == 401
    assert client.post(INBOUND, content=body, headers=good).status_code == 503  # a slot: busy
    slots.leave()
    assert client.post(INBOUND, content=body, headers=good).status_code == 202


class _Slow:
    """A request whose body arrives in chunks, with pauses (seconds) before each."""

    def __init__(self, chunks: list[tuple[float, bytes]]) -> None:
        self.chunks = chunks

    async def stream(self):  # noqa: ANN201
        for pause, chunk in self.chunks:
            await anyio.sleep(pause)
            yield chunk


def _read(chunks: list[tuple[float, bytes]], length: int, caps: ForwardingCaps):  # noqa: ANN202
    mac = forwarding.Mac(mail.SECRET, "1", "n" * 20)
    return anyio.run(read_exactly, _Slow(chunks), length, mac, caps)  # type: ignore[arg-type]


def test_the_body_must_be_exactly_the_declared_length_and_arrive_in_time() -> None:
    caps = ForwardingCaps(read_seconds=0.5, idle_seconds=0.2)
    body, mac = _read([(0, b"abc"), (0, b"def")], 6, caps)  # type: ignore[misc]
    assert body == b"abcdef" and mac.matches(forwarding.sign(mail.SECRET, "1", "n" * 20, body))
    assert _read([(0, b"abcdefg")], 6, caps).status_code == 400  # longer than declared
    assert _read([(0, b"abc")], 6, caps).status_code == 400  # shorter than declared
    assert _read([(0, b"abc"), (0.3, b"def")], 6, caps).status_code == 408  # idle too long
    slow = [(0.15, b"a")] * 6  # never idle too long, but too slow in all
    assert _read(slow, 6, caps).status_code == 408


def test_the_body_limit_is_what_a_full_message_needs() -> None:
    caps = ForwardingCaps(message_bytes=10 * 1024 * 1024)
    assert caps.base64_limit == (10 * 1024 * 1024 + 2) // 3 * 4
    assert caps.body_limit == caps.base64_limit + ENVELOPE
    assert ENVELOPE < 10 * 1024


def test_a_message_of_exactly_the_cap_fits(tmp_path: Path) -> None:
    w = _world(tmp_path, forwarding=ForwardingCaps(message_bytes=60_000))
    base = mail.statement_email(mail.STRANGER)
    raw = base + b"x" * (60_000 - len(base))
    long_verdict = mail.worker_auth("x" * 3500)  # the verdict near its own cap, too
    assert len(long_verdict) > 7000
    assert deliver(w.h, w.address, raw, long_verdict).status_code == 202
    assert deliver(w.h, w.address, raw + b"x", mail.worker_auth(STRANGER_DOMAIN)).status_code == 413


# 8. The address: one change at a time, account database first, a half-done change healed.


def test_concurrent_creations_make_a_single_address(world: World) -> None:
    h = world.h
    bruno = h.sign_in("bruno@example.com")
    answers: list[int] = []

    def create() -> None:
        answers.append(bruno.post("/api/forwarding/address", headers=WRITE).status_code)

    threads = [threading.Thread(target=create) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [200, 409, 409, 409]
    address = state(bruno)["address"]
    raw = mail.statement_email(mail.STRANGER)
    assert deliver(h, address, raw, mail.worker_auth(STRANGER_DOMAIN)).status_code == 202


def test_a_half_done_change_is_finished_on_the_next_read(world: World) -> None:
    h, alice = world.h, world.alice
    token = forwarding.new_token()
    with closing(_connect(h, ALICE)) as conn, conn:
        inbox_store.set_token(conn, token)  # the account's database written, the hash not yet
    old = world.address
    raw = mail.statement_email(mail.STRANGER)
    auth = mail.worker_auth(STRANGER_DOMAIN)
    assert deliver(h, old, raw, auth).status_code == 202  # still the old one, until healed
    shown = state(alice)["address"]
    assert shown == forwarding.address(token)
    assert deliver(h, old, mail.statement_email(mail.STRANGER), auth).status_code == 404
    assert deliver(h, shown, mail.statement_email(mail.STRANGER), auth).status_code == 202


# Strengthened: the inbound secret may not be another server key.


def test_the_inbound_secret_may_not_be_the_master_key(tmp_path: Path) -> None:
    master = master_file(tmp_path)
    same = tmp_path / "inbound.key"
    same.write_bytes(master.read_bytes())
    with pytest.raises(Exception, match="inbound secret must not be another server key"):
        hosted(tmp_path, inbound_secret=same)
    assert load_master(master, tmp_path / "x").secret  # the master key itself is fine


def test_a_locked_new_account_statement_is_not_asked_for_its_password_twice(
    newcomer: World,
) -> None:
    h, alice = newcomer.h, newcomer.alice
    raw = mail.statement_email(mail.BHD_STATEMENTS, mail.bhd_card())
    deliver(h, newcomer.address, raw, mail.worker_auth(BHD))
    unlocked = alice.post(
        "/api/forwarding/waiting/unlock",
        json={"bank": "bhd", "password": mail.PASSWORD},
        headers=WRITE,
    )
    assert unlocked.json() == {"opened": 1, "left": 0}
    held = state(alice)["waiting"]
    assert [w["state"] for w in held] == ["approval"]
    # Held, its read pages are sealed too: no statement text in any file of the account.
    word = max(
        (w.text for page in samples.BHD_TC_PAGES for line in page for w in line.words),
        key=len,
    )
    assert len(word) >= 8
    account = h.service.store.account_by_email(ALICE)
    assert account is not None
    folder = h.data / "users" / account.folder
    assert word.encode() not in b"".join(p.read_bytes() for p in folder.rglob("*") if p.is_file())
    done = alice.post(
        f"/api/forwarding/waiting/{held[0]['id']}/approve", json=CONFIRMED, headers=WRITE
    )
    assert done.json()["waiting"] == []
    assert statements(h) == 1
