"""Receipts in the board's API: what a transaction shows, linking, removing and To review.
Synthetic emails and statements only."""

from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import receipt_match, receipt_store
from michelito.web.app import create_app
from tests import live_helpers
from tests import receipt_samples as samples

WRITE = {"X-Michelito": "1"}
NOW = "2026-02-14T15:00:00+00:00"
MONTH = "2026-02"
SHIPMENT_CHARGE = ("2026-02-15", "AMAZON MKTPL*AB1CD2EF3", "110.97", "USD")
TWIN_CHARGE = ("2026-02-16", "AMAZON RETAIL*ZZ9YY8XX7", "110.97", "USD")
OTHER_CHARGE = ("2026-02-10", "LIBRERIA FICTICIA", "500.00")


def _database(tmp_path: Path, *rows: live_helpers.Row, emails: tuple[object, ...]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        statement = live_helpers.card_statement(
            "2026-02-28", [OTHER_CHARGE, *rows], period_start="2026-02-01"
        )
        assert live_helpers.ingest_card(conn, statement) == "parsed"
        with conn:
            for email in emails:
                receipt_store.record(conn, email, "gmail", NOW)  # type: ignore[arg-type]
            receipt_match.reconcile_stored(conn, NOW)
    return path


def _client(path: Path) -> TestClient:
    return TestClient(create_app(path, today=lambda: date(2026, 2, 20)), "http://127.0.0.1")


def _rows(client: TestClient) -> list[dict]:
    return client.get("/api/transactions", params={"month": MONTH}).json()["items"]


def _amazon(client: TestClient) -> list[dict]:
    return [row for row in _rows(client) if "AMAZON" in row["description"]]


@pytest.fixture
def linked(tmp_path: Path) -> TestClient:
    """One Amazon charge with its shipment's receipt linked on its own."""
    return _client(_database(tmp_path, SHIPMENT_CHARGE, emails=(samples.shipment_email(),)))


@pytest.fixture
def proposed(tmp_path: Path) -> TestClient:
    """Two equal Amazon charges: the shipment's receipt is proposed for both."""
    path = _database(tmp_path, SHIPMENT_CHARGE, TWIN_CHARGE, emails=(samples.shipment_email(),))
    return _client(path)


def test_a_linked_transaction_carries_its_receipt(linked: TestClient) -> None:
    (row,) = _amazon(linked)

    (receipt,) = row["receipts"]
    assert receipt == {
        "id": receipt["id"],
        "merchant": "Amazon",
        "kind": "shipment",
        "orders": [samples.FIRST_ORDER],
        "amount_cents": 11097,
        "currency": "USD",
        "day": "2026-02-14",
        "summary": "Kitchen",
        "item_count": 3,
        "order_link": (
            f"https://www.amazon.com/gp/css/summary/print.html?orderID={samples.FIRST_ORDER}"
        ),
        "email_link": "https://mail.google.com/mail/u/0/#all/m-shipment-1",
        "origin": "automatic",
    }
    # What the statement printed is untouched.
    assert row["description"] == "AMAZON MKTPL*AB1CD2EF3"


def test_a_transaction_without_receipts_has_an_empty_list(linked: TestClient) -> None:
    other = next(row for row in _rows(linked) if "LIBRERIA" in row["description"])

    assert other["receipts"] == []


def test_a_forwarded_email_is_found_in_gmail_by_its_message_id(tmp_path: Path) -> None:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        statement = live_helpers.card_statement(
            "2026-02-28", [SHIPMENT_CHARGE], period_start="2026-02-01"
        )
        live_helpers.ingest_card(conn, statement)
        email = samples.shipment_email("abc+def@mail.example")
        with conn:
            receipt_store.record(conn, email, "forwarding", NOW)
            receipt_match.reconcile_stored(conn, NOW)

    client = _client(path)
    # A forwarded receipt is never linked on its own: the person confirms it in To review.
    (item,) = client.get("/api/review", params={"month": MONTH}).json()
    assert _amazon(client)[0]["receipts"] == []
    confirmed = client.put(
        f"/api/receipts/{item['receipt_id']}/transactions/{item['fingerprint']}", headers=WRITE
    )
    assert confirmed.status_code == 200
    (row,) = _amazon(client)

    assert row["receipts"][0]["origin"] == "confirmed"
    assert row["receipts"][0]["email_link"] == (
        "https://mail.google.com/mail/u/0/#search/rfc822msgid%3Aabc%2Bdef%40mail.example"
    )


def test_removing_a_link_takes_the_receipt_off_and_it_is_not_made_again(
    linked: TestClient,
) -> None:
    (row,) = _amazon(linked)
    receipt_id = row["receipts"][0]["id"]
    url = f"/api/receipts/{receipt_id}/transactions/{row['fingerprint']}"

    assert linked.delete(url).status_code == 403  # a write needs the local header
    removed = linked.delete(url, headers=WRITE)

    assert removed.status_code == 200
    assert removed.json() == {
        "receipt_id": receipt_id,
        "fingerprint": row["fingerprint"],
        "linked": False,
    }
    assert _amazon(linked)[0]["receipts"] == []
    assert linked.get("/api/review", params={"month": MONTH}).json() == []


def test_removing_a_link_is_in_the_history_and_can_be_undone(linked: TestClient) -> None:
    (row,) = _amazon(linked)
    receipt_id = row["receipts"][0]["id"]
    linked.delete(f"/api/receipts/{receipt_id}/transactions/{row['fingerprint']}", headers=WRITE)

    history = linked.get(f"/api/transactions/{row['fingerprint']}/history").json()
    entry = history["items"][0]
    assert entry["kind"] == "receipt"
    undone = linked.post(f"/api/log/{entry['id']}/undo", headers=WRITE)

    assert undone.status_code == 200, undone.text
    assert [r["id"] for r in _amazon(linked)[0]["receipts"]] == [receipt_id]


def test_two_candidates_show_in_to_review(proposed: TestClient) -> None:
    items = proposed.get("/api/review", params={"month": MONTH}).json()

    fingerprints = {row["fingerprint"] for row in _amazon(proposed)}
    assert {item["kind"] for item in items} == {"possible_receipt"}
    assert {item["fingerprint"] for item in items} == fingerprints
    first = items[0]
    assert first["receipt_id"] is not None
    assert "Amazon" in first["reason"] and samples.FIRST_ORDER in first["reason"]
    assert all(row["receipts"] == [] for row in _amazon(proposed))


def test_confirming_a_proposal_links_it_and_clears_the_other(proposed: TestClient) -> None:
    items = proposed.get("/api/review", params={"month": MONTH}).json()
    chosen = items[0]
    url = f"/api/receipts/{chosen['receipt_id']}/transactions/{chosen['fingerprint']}"

    assert proposed.put(url).status_code == 403
    made = proposed.put(url, headers=WRITE)

    assert made.status_code == 200
    assert made.json()["linked"] is True
    rows = {row["fingerprint"]: row for row in _amazon(proposed)}
    assert rows[chosen["fingerprint"]]["receipts"][0]["origin"] == "confirmed"
    assert sum(len(row["receipts"]) for row in rows.values()) == 1
    assert proposed.get("/api/review", params={"month": MONTH}).json() == []


def test_refusing_one_candidate_links_the_one_that_is_left(proposed: TestClient) -> None:
    items = proposed.get("/api/review", params={"month": MONTH}).json()
    refused, kept = items[0], items[1]

    marked = proposed.put(
        f"/api/review/possible_receipt/{refused['fingerprint']}",
        json={"reviewed": True},
        headers=WRITE,
    )

    assert marked.status_code == 200
    rows = {row["fingerprint"]: row for row in _amazon(proposed)}
    assert rows[refused["fingerprint"]]["receipts"] == []
    assert [r["origin"] for r in rows[kept["fingerprint"]]["receipts"]] == ["automatic"]
    assert proposed.get("/api/review", params={"month": MONTH}).json() == []


def test_a_transaction_that_was_not_proposed_cannot_be_linked(proposed: TestClient) -> None:
    receipt_id = proposed.get("/api/review", params={"month": MONTH}).json()[0]["receipt_id"]
    other = next(row for row in _rows(proposed) if "LIBRERIA" in row["description"])

    refused = proposed.put(
        f"/api/receipts/{receipt_id}/transactions/{other['fingerprint']}", headers=WRITE
    )

    assert refused.status_code == 409
    assert other["receipts"] == []


@pytest.mark.parametrize("method", ["put", "delete"])
def test_an_unknown_receipt_or_transaction_is_not_found(linked: TestClient, method: str) -> None:
    (row,) = _amazon(linked)
    receipt_id = row["receipts"][0]["id"]
    call = getattr(linked, method)

    assert (
        call(f"/api/receipts/99999/transactions/{row['fingerprint']}", headers=WRITE).status_code
        == 404
    )
    assert (
        call(f"/api/receipts/{receipt_id}/transactions/nothing", headers=WRITE).status_code == 404
    )


def test_the_summary_figures_do_not_change_with_receipts(tmp_path: Path) -> None:
    without = _client(_database(tmp_path / "a", SHIPMENT_CHARGE, emails=()))
    with_receipt = _client(
        _database(tmp_path / "b", SHIPMENT_CHARGE, emails=(samples.shipment_email(),))
    )

    assert (
        without.get("/api/summary", params={"month": MONTH}).json()["total_cents"]
        == with_receipt.get("/api/summary", params={"month": MONTH}).json()["total_cents"]
    )


def test_undoing_a_removal_does_not_leave_the_receipt_on_two_transactions(
    proposed: TestClient,
) -> None:
    # Two equal charges: confirm one, take it off (the other is then linked on its own), undo.
    first, second = proposed.get("/api/review", params={"month": MONTH}).json()
    receipt_id = first["receipt_id"]
    url = f"/api/receipts/{receipt_id}/transactions/{first['fingerprint']}"
    assert proposed.put(url, headers=WRITE).status_code == 200
    assert proposed.delete(url, headers=WRITE).status_code == 200
    rows = {row["fingerprint"]: row for row in _amazon(proposed)}
    assert len(rows[second["fingerprint"]]["receipts"]) == 1

    history = proposed.get(f"/api/transactions/{first['fingerprint']}/history").json()
    undone = proposed.post(f"/api/log/{history['items'][0]['id']}/undo", headers=WRITE)

    assert undone.status_code == 200, undone.text
    rows = {row["fingerprint"]: row for row in _amazon(proposed)}
    assert len(rows[first["fingerprint"]]["receipts"]) == 1
    assert rows[second["fingerprint"]]["receipts"] == []


def test_a_pair_that_was_neither_linked_nor_proposed_cannot_be_refused(
    linked: TestClient,
) -> None:
    (row,) = _amazon(linked)
    receipt_id = row["receipts"][0]["id"]
    other = next(r for r in _rows(linked) if "LIBRERIA" in r["description"])

    refused = linked.delete(
        f"/api/receipts/{receipt_id}/transactions/{other['fingerprint']}", headers=WRITE
    )

    assert refused.status_code == 409
    history = linked.get(f"/api/transactions/{other['fingerprint']}/history").json()
    assert history["items"] == []


def test_unmarking_a_receipt_item_changes_nothing(proposed: TestClient) -> None:
    item = proposed.get("/api/review", params={"month": MONTH}).json()[0]

    answer = proposed.put(
        f"/api/review/possible_receipt/{item['fingerprint']}",
        json={"reviewed": False},
        headers=WRITE,
    )

    assert answer.status_code == 200 and answer.json()["reviewed"] is False
    assert len(proposed.get("/api/review", params={"month": MONTH}).json()) == 2
