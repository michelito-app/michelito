"""Merchant receipts arriving by email forwarding (hosted mode), with synthetic emails only."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from email.message import EmailMessage
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import receipt_store
from michelito.hosted import inbox_store
from tests import forwarding_helpers as mail
from tests import receipt_samples as samples
from tests.hosted_helpers import WRITE, Hosted, hosted

ALICE = "alice@example.com"
AMAZON = "amazon.com"
INBOUND = "/api/inbound-email"


def _raw(email: object, message_id: str = "receipt-1") -> bytes:
    message = EmailMessage()
    message["From"] = email.sender  # type: ignore[attr-defined]
    message["To"] = "person@example.com"
    message["Subject"] = email.subject  # type: ignore[attr-defined]
    message["Date"] = "Sat, 14 Feb 2026 10:33:00 -0400"
    message["Message-ID"] = f"<{message_id}@example.com>"
    message.set_content(email.text)  # type: ignore[attr-defined]
    message.add_alternative(email.html, subtype="html")  # type: ignore[attr-defined]
    return bytes(message)


@pytest.fixture
def world(tmp_path: Path) -> tuple[Hosted, TestClient, str]:
    secret = tmp_path / "inbound.key"
    secret.write_bytes(mail.SECRET)
    h = hosted(tmp_path, inbound_secret=secret, inbox_background=False)
    alice = h.sign_in(ALICE)
    made = alice.post("/api/forwarding/address", headers=WRITE)
    assert made.status_code == 200, made.text
    return h, alice, made.json()["address"]


def _deliver(h: Hosted, recipient: str, raw: bytes, auth: str) -> int:
    body, headers = mail.signed(recipient, raw, auth, at=h.clock())
    return h.client().post(INBOUND, content=body, headers=headers).status_code


def _connect(h: Hosted) -> sqlite3.Connection:
    account = h.service.store.account_by_email(ALICE)
    assert account is not None
    workspace = h.service.workspace_of(account)
    return db.connect(workspace.database, workspace.key)


def _quarantined(h: Hosted) -> int:
    with closing(_connect(h)) as conn:
        inbox_store.ensure(conn)
        return int(conn.execute("SELECT COUNT(*) FROM inbox_quarantine").fetchone()[0])


def test_an_authenticated_receipt_is_stored_without_waiting(
    world: tuple[Hosted, TestClient, str],
) -> None:
    h, _, address = world

    assert _deliver(h, address, _raw(samples.order_email()), mail.worker_auth(AMAZON)) == 202

    with closing(_connect(h)) as conn:
        found = receipt_store.load(conn)
    assert [(r.orders, r.amount_cents, r.source) for r in found] == [
        ((samples.FIRST_ORDER,), 13056, "forwarding"),
        ((samples.SECOND_ORDER,), 3580, "forwarding"),
    ]
    assert _quarantined(h) == 0


def test_a_receipt_whose_signature_failed_is_quarantined_and_never_read(
    world: tuple[Hosted, TestClient, str],
) -> None:
    h, _, address = world
    auth = mail.worker_auth(AMAZON, dkim=False)

    assert _deliver(h, address, _raw(samples.order_email()), auth) == 202

    with closing(_connect(h)) as conn:
        assert receipt_store.load(conn) == ()
        assert receipt_store.failures(conn) == []
    assert _quarantined(h) == 1


def test_a_receipt_signed_by_another_domain_is_quarantined(
    world: tuple[Hosted, TestClient, str],
) -> None:
    h, _, address = world

    code = _deliver(h, address, _raw(samples.order_email()), mail.worker_auth("attacker.example"))

    assert code == 202
    with closing(_connect(h)) as conn:
        assert receipt_store.load(conn) == ()
    assert _quarantined(h) == 1


def test_the_same_receipt_twice_is_stored_once(world: tuple[Hosted, TestClient, str]) -> None:
    h, _, address = world
    raw = _raw(samples.shipment_email())

    assert _deliver(h, address, raw, mail.worker_auth(AMAZON)) == 202
    assert _deliver(h, address, raw, mail.worker_auth(AMAZON)) == 202

    with closing(_connect(h)) as conn:
        assert len(receipt_store.load(conn)) == 1


def test_another_amazon_address_is_not_a_receipt(world: tuple[Hosted, TestClient, str]) -> None:
    h, _, address = world
    other = samples.order_email(sender="Amazon <store-news@amazon.com>")

    assert _deliver(h, address, _raw(other), mail.worker_auth(AMAZON)) == 202

    with closing(_connect(h)) as conn:
        assert receipt_store.load(conn) == ()
    assert _quarantined(h) == 1


def test_a_receipt_that_cannot_be_read_leaves_only_a_data_free_failure(
    world: tuple[Hosted, TestClient, str],
) -> None:
    h, _, address = world
    broken = samples.order_email(
        html="<p>Grand Total:</p><p>$10.00</p>", text="Grand Total:\n10.00 USD"
    )

    assert _deliver(h, address, _raw(broken), mail.worker_auth(AMAZON)) == 202

    with closing(_connect(h)) as conn:
        assert receipt_store.load(conn) == ()
        (failure,) = receipt_store.failures(conn)
    assert failure["failed_field"] == "order"
    assert "10.00" not in str(failure)
    assert _quarantined(h) == 0


def test_the_receipt_does_not_show_among_the_transactions(
    world: tuple[Hosted, TestClient, str],
) -> None:
    h, alice, address = world
    _deliver(h, address, _raw(samples.order_email()), mail.worker_auth(AMAZON))

    with closing(_connect(h)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0
