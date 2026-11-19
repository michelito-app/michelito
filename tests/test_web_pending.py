"""`GET /api/pending` sobre la base de la demo (datos inventados de `tests.e2e_server`)."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas.web.app import create_app
from tests.e2e_server import PENDING_GAVE, PENDING_GIFT, PENDING_GOT, build_demo_db

VISA = "demo:credit_card"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    return TestClient(create_app(path, today=lambda: date(2026, 3, 1)), "http://127.0.0.1")


def _descriptions(client: TestClient, items: list[dict]) -> list[str]:
    def text(fingerprint: str) -> str:
        return client.get(f"/api/transactions/{fingerprint}").json()["description"]

    return [text(i["fingerprint"]) for i in items]


def test_both_lists_with_totals_in_pesos(client: TestClient) -> None:
    body = client.get("/api/pending").json()

    assert _descriptions(client, body["owed_to_me"]) == [PENDING_GAVE, PENDING_GIFT]
    exchange, gift = body["owed_to_me"]
    assert (exchange["kind"], exchange["day"]) == ("exchange", "2025-12-03")
    assert exchange["age_days"] == 88
    # US$ 100 a la tasa acordada del cambio (63.10), no a la más reciente (63.70).
    assert (exchange["pending_cents"], exchange["currency"]) == (10000, "USD")
    assert (exchange["pending_dop_cents"], exchange["rate"]) == (631000, "63.1000")
    assert (gift["kind"], gift["who"], gift["currency"]) == ("shared", "Luis", "DOP")
    assert (gift["pending_cents"], gift["pending_dop_cents"]) == (400000, 400000)
    assert gift["rate"] is None
    assert gift["account_label"].startswith("VISA DEMO")

    [owe] = body["i_owe"]
    assert _descriptions(client, [owe]) == [PENDING_GOT]
    assert (owe["pending_cents"], owe["pending_dop_cents"]) == (20000, 1262000)
    assert owe["who"] == "Cambio con Pedro"

    assert body["owed_to_me_dop_cents"] == 1031000
    assert body["i_owe_dop_cents"] == 1262000
    assert body["net_dop_cents"] == -231000
    assert body["unconverted_usd_cents"] == {"owed_to_me": 0, "i_owe": 0}
    assert body["rate_month"] == "2026-02"


def test_account_filter_and_unknown_accounts(client: TestClient) -> None:
    body = client.get("/api/pending", params={"accounts": VISA}).json()

    assert _descriptions(client, body["owed_to_me"]) == [PENDING_GIFT]
    assert body["i_owe"] == []
    assert body["net_dop_cents"] == 400000
    assert client.get("/api/pending", params={"accounts": "nada"}).status_code == 422


def test_the_first_leg_opens_its_page(client: TestClient) -> None:
    [owe] = client.get("/api/pending").json()["i_owe"]

    tx = client.get(f"/api/transactions/{owe['fingerprint']}").json()

    assert (tx["link"], tx["exchange"]["pending_cents"]) == ("exchange", 20000)


def test_totals_are_the_sum_of_the_rows(client: TestClient) -> None:
    for params in ({}, {"accounts": VISA}):
        body = client.get("/api/pending", params=params).json()

        owed = sum(i["pending_dop_cents"] or 0 for i in body["owed_to_me"])
        owing = sum(i["pending_dop_cents"] or 0 for i in body["i_owe"])
        assert (body["owed_to_me_dop_cents"], body["i_owe_dop_cents"]) == (owed, owing)
        assert body["net_dop_cents"] == owed - owing
