from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.web.app import create_app
from tests.test_spending import seed

WRITE = {"X-Michelito": "1"}
MONTH = "2026-01"
BIG = "MUEBLERIA INVENTADA SANTO DOMINGO"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Synthetic statements plus a large purchase at a new (made-up) merchant."""
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        statement_id = conn.execute(
            "SELECT s.id FROM statements s JOIN accounts a ON a.id = s.account_id "
            "WHERE a.key = 'popular:credit_card' AND s.currency = 'DOP'"
        ).fetchone()[0]
        with conn:
            conn.execute(
                "INSERT INTO transactions (statement_id, sequence, transacted_on, description, "
                "amount_cents, direction, currency, raw_line) "
                "VALUES (?, 9000, '2026-01-05', ?, 4500000, 'debit', 'DOP', 'x')",
                (statement_id, BIG),
            )
    return path


@pytest.fixture
def client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")


def _suggestions(client: TestClient) -> list[dict]:
    response = client.get("/api/one-off-suggestions", params={"month": MONTH})
    assert response.status_code == 200
    return response.json()


def test_suggestions_list_the_big_rare_purchase(client: TestClient) -> None:
    [found] = _suggestions(client)
    assert set(found) == {
        "fingerprint",
        "day",
        "merchant",
        "description",
        "account_label",
        "amount_cents",
        "currency",
        "amount_dop_cents",
        "reasons",
    }
    assert (found["day"], found["description"]) == ("2026-01-05", BIG)
    assert (found["amount_cents"], found["amount_dop_cents"]) == (4500000, 4500000)
    assert found["currency"] == "DOP"
    assert "comercio nuevo" in found["reasons"]  # spanish-ui
    assert found["account_label"] != "popular:credit_card"  # the label, not the key


def test_suggestions_validate_the_month(client: TestClient) -> None:
    assert client.get("/api/one-off-suggestions", params={"month": "2026-13"}).status_code == 422
    assert client.get("/api/one-off-suggestions", params={"month": "1999-01"}).json() == []


def test_transactions_flag_suggested_rows(client: TestClient) -> None:
    items = client.get("/api/transactions", params={"month": MONTH}).json()["items"]
    big = next(i for i in items if i["description"] == BIG)
    assert big["suggested_one_off"] is True
    assert "comercio nuevo" in big["one_off_reasons"]  # spanish-ui
    others = [i for i in items if i["description"] != BIG]
    assert others and not any(i["suggested_one_off"] or i["one_off_reasons"] for i in others)


def test_dismiss_and_undo(client: TestClient) -> None:
    [found] = _suggestions(client)
    path = f"/api/one-off-suggestions/{found['fingerprint']}"
    assert client.put(path, json={"dismissed": True}).status_code == 403  # missing header
    assert len(_suggestions(client)) == 1

    response = client.put(path, json={"dismissed": True}, headers=WRITE)
    assert response.status_code == 200
    assert response.json() == {"fingerprint": found["fingerprint"], "dismissed": True}
    assert _suggestions(client) == []
    items = client.get("/api/transactions", params={"month": MONTH}).json()["items"]
    assert not next(i for i in items if i["description"] == BIG)["suggested_one_off"]

    items = client.get("/api/transactions", params={"month": MONTH}).json()["items"]
    assert next(i for i in items if i["description"] == BIG)["one_off_dismissed"] is True

    client.put(path, json={"dismissed": False}, headers=WRITE)
    assert len(_suggestions(client)) == 1
    items = client.get("/api/transactions", params={"month": MONTH}).json()["items"]
    assert not any(i["one_off_dismissed"] for i in items)


def test_dismiss_rejects_unknown_and_bad_bodies(client: TestClient) -> None:
    assert (
        client.put("/api/one-off-suggestions/nope", json={"dismissed": True}, headers=WRITE)
    ).status_code == 404
    [found] = _suggestions(client)
    path = f"/api/one-off-suggestions/{found['fingerprint']}"
    assert client.put(path, json={}, headers=WRITE).status_code == 422
    assert client.put(path, json={"dismissed": "yes"}, headers=WRITE).status_code == 422


def test_confirming_through_the_one_off_mark_moves_it_out(client: TestClient) -> None:
    [found] = _suggestions(client)
    response = client.patch(
        f"/api/transactions/{found['fingerprint']}", json={"one_off": True}, headers=WRITE
    )
    assert response.status_code == 200
    assert response.json()["one_off"] is True
    assert response.json()["suggested_one_off"] is False
    assert _suggestions(client) == []
    summary = client.get("/api/summary", params={"month": MONTH}).json()
    assert summary["one_offs_cents"] == 4500000


def test_dismissals_survive_reprocessing(client: TestClient, db_path: Path) -> None:
    [found] = _suggestions(client)
    client.put(
        f"/api/one-off-suggestions/{found['fingerprint']}", json={"dismissed": True}, headers=WRITE
    )
    with closing(db.connect(db_path)) as conn, conn:  # like parse --retry: new rows
        conn.execute("UPDATE transactions SET id = id + 100000")
    assert _suggestions(client) == []


def test_a_recurring_mark_excludes_the_merchant(client: TestClient) -> None:
    body = {"merchant": "MUEBLERIA INVENTADA", "currency": "DOP", "status": "confirmed"}
    assert client.put("/api/recurring/mark", json=body, headers=WRITE).status_code == 200
    assert _suggestions(client) == []
    items = client.get("/api/transactions", params={"month": MONTH}).json()["items"]
    assert not any(i["suggested_one_off"] for i in items)
