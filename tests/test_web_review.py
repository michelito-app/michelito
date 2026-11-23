"""The "to review" API on the demo database (made-up data)."""

from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.web.app import create_app
from tests.e2e_server import _store_extra, build_demo_db
from tests.test_spending import seed

WRITE = {"X-Michelito": "1"}
FEBRUARY = "2026-02"
VISA = "demo:credit_card"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    return path


@pytest.fixture
def client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path), "http://127.0.0.1")


def _items(client: TestClient, **params: str) -> list[dict]:
    response = client.get("/api/review", params={"month": FEBRUARY, **params})
    assert response.status_code == 200
    return response.json()


def _by_kind(items: list[dict]) -> dict[str, dict]:
    return {item["kind"]: item for item in items}


def test_february_has_one_item_of_each_kind_found(client: TestClient) -> None:
    found = _by_kind(_items(client))
    assert set(found) == {"one_off", "unusual_income", "large_third_party", "price_up"}
    assert found["one_off"]["merchant"] == "AGENCIA FICTICIA"
    assert found["unusual_income"]["merchant"] == "DEPOSITO CAMBIO FICTICIO"
    assert found["price_up"]["reason"] == "Subió de US$ 9.99 a US$ 11.99"  # spanish-ui
    third = found["large_third_party"]
    assert (third["amount_cents"], third["currency"], third["amount_dop_cents"]) == (
        100000,
        "USD",
        6370000,
    )
    assert set(third) == {
        "kind",
        "fingerprint",
        "day",
        "month",
        "merchant",
        "description",
        "account_label",
        "amount_cents",
        "currency",
        "amount_dop_cents",
        "reason",
        "reviewed",
        "investment_id",
        "category_id",
        "reserve_id",
        "group_id",
        "contact_id",
        "payment_id",
        "payment_ids",
        "provisional",
        "receipt_id",
        "plan_id",
        "installment_number",
    }
    assert third["investment_id"] is None
    assert third["provisional"] is False
    assert third["account_label"] != third["fingerprint"] and third["month"] == FEBRUARY
    assert not any(item["reviewed"] for item in found.values())


def test_already_reviewed_leaves_the_card_but_stays_in_history(client: TestClient) -> None:
    third = _by_kind(_items(client))["large_third_party"]
    path = f"/api/review/large_third_party/{third['fingerprint']}"
    response = client.put(path, json={"reviewed": True}, headers=WRITE)
    assert response.json() == {
        "kind": "large_third_party",
        "fingerprint": third["fingerprint"],
        "reviewed": True,
    }
    assert "large_third_party" not in _by_kind(_items(client))
    assert _by_kind(_items(client, reviewed="true"))["large_third_party"]["reviewed"] is True
    history = client.get("/api/review/history", params={"kind": "large_third_party"}).json()
    # December has the demo investment transfers to Pedro, still unmarked.
    february = [(h["fingerprint"], h["reviewed"]) for h in history if h["month"] == FEBRUARY]
    assert february == [(third["fingerprint"], True)]

    client.put(path, json={"reviewed": False}, headers=WRITE)
    assert "large_third_party" in _by_kind(_items(client))


def test_reviewing_a_one_off_is_the_old_dismissal(client: TestClient) -> None:
    one_off = _by_kind(_items(client))["one_off"]
    client.put(
        f"/api/review/one_off/{one_off['fingerprint']}", json={"reviewed": True}, headers=WRITE
    )
    assert client.get("/api/one-off-suggestions", params={"month": FEBRUARY}).json() == []
    assert _by_kind(_items(client, reviewed="true"))["one_off"]["reviewed"] is True


def test_reviewed_survives_reprocessing(client: TestClient, db_path: Path) -> None:
    income = _by_kind(_items(client))["unusual_income"]
    client.put(
        f"/api/review/unusual_income/{income['fingerprint']}",
        json={"reviewed": True},
        headers=WRITE,
    )
    with closing(db.connect(db_path)) as conn:
        with conn:
            for table in ("transactions", "statements", "documents", "gmail_messages"):
                conn.execute(f"DELETE FROM {table}")
        seed(conn)  # like parse --retry: new rows, same fingerprints
        _store_extra(conn)
    assert "unusual_income" not in _by_kind(_items(client))


def test_honors_the_account_filter(client: TestClient) -> None:
    assert set(_by_kind(_items(client, accounts=VISA))) == {"one_off", "price_up"}
    history = client.get("/api/review/history", params={"accounts": VISA}).json()
    assert {h["kind"] for h in history} == {"one_off", "price_up"}


def test_history_is_newest_first(client: TestClient) -> None:
    history = client.get("/api/review/history").json()
    assert history and [h["day"] for h in history] == sorted(
        (h["day"] for h in history), reverse=True
    )


def test_errors(client: TestClient) -> None:
    assert client.get("/api/review", params={"month": "2026-13"}).status_code == 422
    assert client.get("/api/review", params={"month": FEBRUARY, "accounts": "x"}).status_code == 422
    assert client.get("/api/review/history", params={"kind": "other"}).status_code == 422
    body = {"reviewed": True}
    assert client.put("/api/review/duplicate/none", json=body, headers=WRITE).status_code == 404
    assert client.put("/api/review/other/none", json=body, headers=WRITE).status_code == 422
    assert client.put("/api/review/duplicate/none", json=body).status_code == 403
    one = _items(client)[0]["fingerprint"]
    bad = client.put(f"/api/review/duplicate/{one}", json={"reviewed": "yes"}, headers=WRITE)
    assert bad.status_code == 422
