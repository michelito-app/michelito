"""Live sync through the board API: provisional rows, filter, Summary, Budget, the review item
for an unmatched provisional and its decisions (logged and undoable)."""

from __future__ import annotations

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import categories
from michelito.i18n import t
from michelito.web.app import create_app
from tests import alert_samples as samples
from tests.ledger_helpers import share
from tests.live_helpers import alert, card_statement, ingest_card, known_card

WRITE = {"X-Michelito": "1"}
FEBRUARY = "2026-02"
MARCH = "2026-03"


@pytest.fixture
def path(tmp_path: Path) -> Path:
    found = tmp_path / "live.db"
    with closing(db.connect(found)) as conn:
        known_card(conn)
        # February is complete (statement up to the 28th) and March has only alerts.
        alert(conn, "a1", amount="700.00", day="05/02/2026", merchant="FARMACIA FICTICIA")
        ingest_card(
            conn,
            card_statement("2026-02-28", [("2026-02-20", "SUPERMERCADO FICTICIO", "1000.00")]),
        )
        alert(conn, "a2", amount="1,500.00", day="03/03/2026", merchant="COLMADO FICTICIO")
        alert(conn, "a3", amount="250.00", day="04/03/2026", merchant="CAFETERIA FICTICIA")
    return found


@pytest.fixture
def client(path: Path) -> TestClient:
    return TestClient(create_app(path, today=lambda: date(2026, 3, 6)), "http://127.0.0.1")


def _rows(client: TestClient, month: str, **params: str) -> list[dict]:
    response = client.get("/api/transactions", params={"month": month, **params})
    assert response.status_code == 200
    return response.json()["items"]


def test_provisional_rows_are_flagged_and_filterable(client: TestClient) -> None:
    rows = _rows(client, MARCH)
    assert {r["merchant"]: r["provisional"] for r in rows} == {
        "COLMADO FICTICIO": True,
        "CAFETERIA FICTICIA": True,
    }
    feb = _rows(client, FEBRUARY)
    assert {r["merchant"] for r in feb if not r["provisional"]} >= {"SUPERMERCADO FICTICIO"}
    only = _rows(client, FEBRUARY, provisional="true")
    assert [r["merchant"] for r in only] == ["FARMACIA FICTICIA"]


def test_a_provisional_can_be_categorized_and_noted(client: TestClient) -> None:
    mark = _rows(client, MARCH)[0]["fingerprint"]
    note = "para la casa"  # spanish-data
    body = {"note": note, "category": categories.RESTAURANTS}
    response = client.patch(f"/api/transactions/{mark}", json=body, headers=WRITE)
    assert response.status_code == 200
    row = response.json()
    assert (row["note"], row["provisional"], row["corrected"]) == (note, True, True)
    assert row["category"] == categories.RESTAURANTS


def test_the_summary_counts_provisionals_and_says_how_much(client: TestClient) -> None:
    march = client.get("/api/summary", params={"month": MARCH}).json()
    assert march["total_cents"] == 175000
    assert march["provisional_cents"] == 175000
    february = client.get("/api/summary", params={"month": FEBRUARY}).json()
    assert february["provisional_cents"] == 70000
    assert february["total_cents"] == 170000


def test_the_budget_counts_provisionals(client: TestClient) -> None:
    assert client.post("/api/budget/activate", headers=WRITE).status_code == 201
    before = client.get("/api/budget", params={"month": MARCH}).json()["spent_cents"]
    colmado = next(r for r in _rows(client, MARCH) if r["merchant"] == "COLMADO FICTICIO")
    discard = client.put(
        f"/api/provisional/{colmado['fingerprint']}", json={"decision": "discard"}, headers=WRITE
    )
    assert discard.status_code == 200
    after = client.get("/api/budget", params={"month": MARCH}).json()["spent_cents"]
    assert before - after == colmado["amount_cents"] == 150000


def test_an_unmatched_provisional_is_a_review_item_with_its_decisions(client: TestClient) -> None:
    items = client.get("/api/review", params={"month": FEBRUARY}).json()
    found = [i for i in items if i["kind"] == "unconfirmed"]
    assert len(found) == 1
    item = found[0]
    assert item["merchant"] == "FARMACIA FICTICIA"
    assert item["reason"] == "No apareció en tu estado de febrero. ¿Se reversó?"  # spanish-ui
    mark = item["fingerprint"]

    keep = client.put(f"/api/provisional/{mark}", json={"decision": "keep"}, headers=WRITE)
    assert keep.status_code == 200
    pending = client.get("/api/review", params={"month": FEBRUARY}).json()
    assert not [i for i in pending if i["kind"] == "unconfirmed"]
    reviewed = client.get("/api/review", params={"month": FEBRUARY, "reviewed": "true"}).json()
    assert [i["reviewed"] for i in reviewed if i["kind"] == "unconfirmed"] == [True]

    discard = client.put(f"/api/provisional/{mark}", json={"decision": "discard"}, headers=WRITE)
    assert discard.status_code == 200
    assert "FARMACIA FICTICIA" not in {r["merchant"] for r in _rows(client, FEBRUARY)}

    # Both are in the transaction's history and the discard can be undone.
    entries = client.get("/api/log").json()["items"]
    entries = [e for e in entries if mark in e["fingerprints"]]
    assert [e["kind"] for e in entries][:2] == ["provisional", "provisional"]
    undo = client.post(f"/api/log/{entries[0]['id']}/undo", headers=WRITE)
    assert undo.status_code in (200, 201)
    assert "FARMACIA FICTICIA" in {r["merchant"] for r in _rows(client, FEBRUARY)}


def test_decisions_only_for_provisionals(client: TestClient) -> None:
    statement_row = next(r for r in _rows(client, FEBRUARY) if not r["provisional"])
    response = client.put(
        f"/api/provisional/{statement_row['fingerprint']}",
        json={"decision": "discard"},
        headers=WRITE,
    )
    assert response.status_code == 404
    bad = client.put("/api/provisional/alert-1", json={"decision": "void"}, headers=WRITE)
    assert bad.status_code == 422
    assert client.put("/api/provisional/alert-1", json={"decision": "keep"}).status_code == 403


def _row_of(client: TestClient, month: str, merchant: str) -> dict:
    return next(r for r in _rows(client, month) if r["merchant"] == merchant)


def test_a_linked_provisional_cannot_be_discarded(client: TestClient, path: Path) -> None:
    mark = _row_of(client, MARCH, "COLMADO FICTICIO")["fingerprint"]
    with closing(db.connect(path)) as conn, conn:
        share(conn, mark, Decimal("1500.00"), people=2, with_whom="Ana")
    discard = client.put(f"/api/provisional/{mark}", json={"decision": "discard"}, headers=WRITE)
    assert discard.status_code == 409
    assert discard.json()["detail"] == t("web.provisional.linked")
    keep = client.put(f"/api/provisional/{mark}", json={"decision": "keep"}, headers=WRITE)
    assert keep.status_code == 200


def test_a_reversal_on_a_linked_provisional_is_a_review_item(
    client: TestClient, path: Path
) -> None:
    mark = _row_of(client, MARCH, "COLMADO FICTICIO")["fingerprint"]
    with closing(db.connect(path)) as conn:
        with conn:
            share(conn, mark, Decimal("1500.00"), people=2, with_whom="Ana")
        alert(
            conn,
            "r1",
            amount="1,500.00",
            day="04/03/2026",
            merchant="COLMADO FICTICIO",
            status=samples.REVERSED,
        )
    assert mark in {r["fingerprint"] for r in _rows(client, MARCH)}  # still counted
    items = client.get("/api/review", params={"month": MARCH}).json()
    found = [i for i in items if i["kind"] == "reversal"]
    assert [(i["fingerprint"], i["provisional"]) for i in found] == [(mark, True)]
    assert found[0]["reason"] == t("web.review.reversal_linked")


def test_undoing_a_discard_from_the_board_reconciles(client: TestClient, path: Path) -> None:
    mark = _row_of(client, FEBRUARY, "FARMACIA FICTICIA")["fingerprint"]
    discard = client.put(f"/api/provisional/{mark}", json={"decision": "discard"}, headers=WRITE)
    assert discard.status_code == 200
    # A later statement has the purchase: while discarded, it is just a statement row.
    with closing(db.connect(path)) as conn:
        row = ("2026-02-06", "FARMACIA FICTICIA", "700.00")
        assert ingest_card(conn, card_statement("2026-03-31", [row])) == "parsed"
    entry = next(e for e in client.get("/api/log").json()["items"] if mark in e["fingerprints"])
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code in (200, 201)
    rows = [r for r in _rows(client, FEBRUARY) if r["merchant"] == "FARMACIA FICTICIA"]
    assert len(rows) == 1  # counted once: the statement's row, with its own identity
    assert not rows[0]["provisional"] and rows[0]["fingerprint"] != mark
