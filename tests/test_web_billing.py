"""`GET /api/billing`: a card's billing by statement (demo data)."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito.analysis import billing
from michelito.web.app import create_app
from tests.e2e_server import build_demo_db

CARD = "ficticio:credit_card"  # three statements, Nov 2025 to Jan 2026
CHECKING = "ficticio:checking:777-0"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    path = Path(tmp_path_factory.mktemp("demo")) / "michelito.db"
    build_demo_db(path)
    app = create_app(path, today=lambda: date(2026, 2, 12))
    return TestClient(app, "http://127.0.0.1")


def _billing(client: TestClient, **params: str) -> dict:
    response = client.get("/api/billing", params={"account": CARD, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_billing_lists_statements_groups_and_coverage(client: TestClient) -> None:
    body = _billing(client, **{"from": "2025-01", "to": "2026-01"})
    assert body["account"] == CARD
    assert body["from"] == "2025-01" and body["to"] == "2026-01"
    assert body["statements"], "the demo card has statements"
    first = body["statements"][0]
    assert set(first["groups"]) == set(billing.GROUPS)
    assert {"period_end", "currency", "previous_balance_cents", "closing_balance_cents"} <= set(
        first
    )
    assert body["complete"] is (body["missing"] == [])
    assert "2025-01" in body["missing"]  # the demo starts later
    for currency, groups in body["totals"].items():
        assert currency in {"DOP", "USD"}
        assert set(groups) == set(billing.GROUPS)


def test_each_statement_balances_with_its_groups(client: TestClient) -> None:
    for card in (CARD, "popular:credit_card", "bhd:credit_card", "demo:credit_card"):
        _balanced(client, card)


def _balanced(client: TestClient, card: str) -> None:
    response = client.get(
        "/api/billing", params={"account": card, "from": "2025-01", "to": "2026-02"}
    )
    assert response.status_code == 200, response.text
    for line in response.json()["statements"]:
        if line["previous_balance_cents"] is None or line["closing_balance_cents"] is None:
            continue
        g = line["groups"]
        change = g["purchases"] + g["cash_advances"] + g["bank_fees"] - g["refunds"] - g["payments"]
        assert line["previous_balance_cents"] + change == line["closing_balance_cents"], line


def test_billing_defaults_to_twelve_months_up_to_the_latest_statement(client: TestClient) -> None:
    body = _billing(client)
    latest = max(line["period_end"] for line in body["statements"])[:7]
    assert body["to"] == latest
    assert body["from"] == billing.months_back(latest, 11)


def test_unknown_account_is_404_and_non_card_is_422(client: TestClient) -> None:
    assert client.get("/api/billing", params={"account": "missing:account"}).status_code == 404
    assert client.get("/api/billing", params={"account": CHECKING}).status_code == 422


def test_from_after_to_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/billing", params={"account": CARD, "from": "2026-02", "to": "2026-01"}
    )
    assert response.status_code == 422


def test_a_range_over_36_months_is_rejected(client: TestClient) -> None:
    params = {"account": CARD, "from": "0001-01", "to": "9999-12"}
    assert client.get("/api/billing", params=params).status_code == 422
    params = {"account": CARD, "from": "2023-02", "to": "2026-01"}  # exactly 36
    assert client.get("/api/billing", params=params).status_code == 200


def test_from_after_the_newest_statement_is_an_empty_range_not_an_error(client: TestClient) -> None:
    body = _billing(client, **{"from": "2026-05"})
    assert body["from"] == body["to"] == "2026-05"
    assert body["statements"] == [] and body["missing"] == ["2026-05"]
