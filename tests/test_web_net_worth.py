"""`/api/net-worth`: a card's statements and a loan give today's debts, the groups, the month's
change and the monthly history. Synthetic statements only."""

from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.web.app import create_app
from tests import live_helpers

WRITE = {"X-Michelito": "1"}
LOAN = {
    "name": "Car loan",
    "number": "1234567890",
    "principal_cents": 10_000_000,
    "rate_bp": 1200,
    "term": 12,
    "start_date": "2026-01-15",
}


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        for month, amount in (("2026-02", "500.00"), ("2026-03", "700.00")):
            rows = [(f"{month}-05", "LIBRERIA FICTICIA", amount)]
            statement = live_helpers.card_statement(f"{month}-28", rows, period_start=f"{month}-01")
            assert live_helpers.ingest_card(conn, statement) == "parsed"
    return path


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = _database(tmp_path)
    return TestClient(create_app(path, today=lambda: date(2026, 4, 20)), "http://127.0.0.1")


def test_a_card_is_a_debt_with_its_latest_closing_balance(client: TestClient) -> None:
    # Act
    found = client.get("/api/net-worth").json()
    # Assert
    assert found["debts_cents"] == 70_000
    assert found["net_cents"] == -70_000
    assert found["groups"] == [{"group": "cards", "side": "debt", "total_cents": 70_000}]
    (card,) = found["holdings"]
    assert card["value_cents"] == 70_000
    assert card["change_dop_cents"] == 0  # no statement since the end of March


def test_history_has_a_point_per_month_from_the_first_statement(client: TestClient) -> None:
    found = client.get("/api/net-worth").json()
    assert [(p["month"], p["net_cents"]) for p in found["history"]] == [
        ("2026-02", -50_000),
        ("2026-03", -70_000),
        ("2026-04", -70_000),
    ]
    assert found["history"][-1]["day"] == "2026-04-20"


def test_a_loan_adds_its_balance_as_a_debt(client: TestClient) -> None:
    # Arrange
    created = client.post("/api/loans", json=LOAN, headers=WRITE)
    assert created.status_code == 201, created.text
    loan = created.json()
    # Act
    found = client.get("/api/net-worth").json()
    # Assert
    groups = {g["group"]: g["total_cents"] for g in found["groups"]}
    assert groups["loans"] == loan["balance_cents"]
    holding = next(h for h in found["holdings"] if h["key"] == f"loan-{loan['id']}")
    assert holding["change_dop_cents"] < 0  # an installment was due since the end of March
