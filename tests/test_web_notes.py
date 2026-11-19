"""Notas libres desde el board: PATCH, búsqueda y validación."""

from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.web.app import create_app
from tests.test_spending import seed

WRITE = {"X-Finanzas": "1"}
MONTH = "2026-01"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "finanzas.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
    return TestClient(create_app(path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")


def _cafe(client: TestClient) -> dict:
    items = client.get("/api/transactions", params={"month": MONTH}).json()["items"]
    return next(i for i in items if i["merchant"].startswith("CAFE"))


def test_patch_saves_the_note_and_search_finds_it(client: TestClient) -> None:
    cafe = _cafe(client)
    assert cafe["note"] == ""
    response = client.patch(
        f"/api/transactions/{cafe['fingerprint']}", json={"note": "con Ana"}, headers=WRITE
    )
    assert response.status_code == 200
    assert response.json()["note"] == "con Ana"
    assert response.json()["category"] == cafe["category"]  # no toca lo demás
    found = client.get("/api/transactions", params={"month": MONTH, "q": "ana"}).json()
    assert [i["fingerprint"] for i in found["items"]] == [cafe["fingerprint"]]
    cleared = client.patch(
        f"/api/transactions/{cafe['fingerprint']}", json={"note": ""}, headers=WRITE
    )
    assert cleared.json()["note"] == ""


def test_a_note_longer_than_500_is_422(client: TestClient) -> None:
    cafe = _cafe(client)
    response = client.patch(
        f"/api/transactions/{cafe['fingerprint']}", json={"note": "x" * 501}, headers=WRITE
    )
    assert response.status_code == 422
