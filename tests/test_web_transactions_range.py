"""`GET /api/transactions` over a range of months, by pages (demo data)."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito.web.app import create_app
from tests.e2e_server import build_demo_db


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    path = Path(tmp_path_factory.mktemp("demo")) / "michelito.db"
    build_demo_db(path)
    app = create_app(path, today=lambda: date(2026, 2, 12))
    return TestClient(app, "http://127.0.0.1")


def _list(client: TestClient, **params: str | int) -> dict:
    response = client.get("/api/transactions", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_range_joins_its_months(client: TestClient) -> None:
    december = _list(client, month="2025-12")
    january = _list(client, month="2026-01")
    both = _list(client, **{"from": "2025-12", "to": "2026-01"})
    assert both["count"] == december["count"] + january["count"]
    assert both["total_cents"] == december["total_cents"] + january["total_cents"]
    assert both["searched"] == {"from": "2025-12", "to": "2026-01"}
    days = [row["day"] for row in both["items"]]
    assert days == sorted(days, reverse=True)


def test_one_month_says_where_it_searched_even_when_empty(client: TestClient) -> None:
    body = _list(client, month="2026-01", q="no merchant is called like this")
    assert body["items"] == [] and body["count"] == 0
    assert body["searched"] == {"from": "2026-01", "to": "2026-01"}
    assert body["next_offset"] is None


def test_pages_cover_everything_once_and_totals_are_of_the_whole_filter(
    client: TestClient,
) -> None:
    whole = _list(client, **{"from": "2025-11", "to": "2026-02"})
    assert whole["count"] > 5 and whole["next_offset"] is None
    seen: list[str] = []
    offset: int | None = 0
    while offset is not None:
        page = _list(client, **{"from": "2025-11", "to": "2026-02", "limit": 5, "offset": offset})
        assert len(page["items"]) <= 5
        assert page["count"] == whole["count"]
        assert page["total_cents"] == whole["total_cents"]
        seen += [row["fingerprint"] for row in page["items"]]
        offset = page["next_offset"]
    assert seen == [row["fingerprint"] for row in whole["items"]]


@pytest.mark.parametrize(
    "params",
    [
        {"month": "2026-01", "from": "2025-12"},
        {"from": "2026-02", "to": "2026-01"},
        {"month": "2026-01", "limit": 0},
        {"month": "2026-01", "limit": 501},
        {"month": "2026-01", "offset": -1},
        {"from": "0001-01", "to": "9999-12"},
        {"from": "2023-01", "to": "2026-01"},
    ],
)
def test_bad_range_or_page_is_rejected(client: TestClient, params: dict) -> None:
    assert client.get("/api/transactions", params=params).status_code == 422


def test_one_end_alone_is_a_single_month(client: TestClient) -> None:
    january = _list(client, month="2026-01")
    assert _list(client, **{"from": "2026-01"})["count"] == january["count"]
    assert _list(client, to="2026-01")["searched"] == {"from": "2026-01", "to": "2026-01"}
