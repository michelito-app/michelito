"""Saved-insights API, on the demo database (made-up data)."""

from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db, dossier
from michelito.analysis import corrections, insights
from michelito.web.app import create_app
from tests.e2e_server import build_demo_db

WRITE = {"X-Michelito": "1"}
FEBRUARY = "2026-02"
NOW = "2026-03-01T12:00:00+00:00"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    return path


@pytest.fixture
def client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path), "http://127.0.0.1")


def _save_from_cli(db_path: Path, month: str = FEBRUARY, accounts=None) -> None:
    """Like `michelito insight save`: with the dossier fingerprint."""
    with closing(db.connect(db_path)) as conn:
        built = dossier.build(conn, month, accounts=accounts)
        with conn:
            insights.save(conn, month, "February: big trip.", built.data_hash, accounts, NOW)


def test_list_and_get(client: TestClient, db_path: Path) -> None:
    assert client.get("/api/insights").json() == []
    assert client.get(f"/api/insights/{FEBRUARY}").status_code == 404
    _save_from_cli(db_path)
    [item] = client.get("/api/insights").json()
    assert item == {
        "month": FEBRUARY,
        "label": "Febrero 2026",  # spanish-ui
        "text": "February: big trip.",
        "accounts": None,
        "created_at": NOW,
        "updated_at": NOW,
        "stale": False,
    }
    assert client.get(f"/api/insights/{FEBRUARY}").json() == item


def test_stale_when_the_data_changed(client: TestClient, db_path: Path) -> None:
    _save_from_cli(db_path, accounts=["demo:credit_card"])
    assert client.get(f"/api/insights/{FEBRUARY}").json()["stale"] is False
    with closing(db.connect(db_path)) as conn:
        rows = dossier.build(conn, FEBRUARY).data["transactions"]
        agency = next(m for m in rows if m["merchant"] == "AGENCIA FICTICIA")
        with conn:
            corrections.set_one_off(conn, agency["fingerprint"], True)
    assert client.get(f"/api/insights/{FEBRUARY}").json()["stale"] is True


def test_edit_keeps_the_hash_and_create_takes_the_current_one(
    client: TestClient, db_path: Path
) -> None:
    _save_from_cli(db_path)
    edited = client.put(f"/api/insights/{FEBRUARY}", json={"text": "  Edited.  "}, headers=WRITE)
    assert edited.status_code == 200
    assert (edited.json()["text"], edited.json()["stale"]) == ("Edited.", False)
    made = client.put("/api/insights/2025-12", json={"text": "December."}, headers=WRITE)
    assert made.status_code == 200 and made.json()["stale"] is False
    assert [i["month"] for i in client.get("/api/insights").json()] == [FEBRUARY, "2025-12"]


def test_delete(client: TestClient, db_path: Path) -> None:
    _save_from_cli(db_path)
    assert client.delete(f"/api/insights/{FEBRUARY}", headers=WRITE).status_code == 204
    assert client.delete(f"/api/insights/{FEBRUARY}", headers=WRITE).status_code == 404


def test_errors(client: TestClient) -> None:
    assert client.put("/api/insights/2026-02", json={"text": "x"}).status_code == 403
    assert client.put("/api/insights/2026-13", json={"text": "x"}, headers=WRITE).status_code == 422
    assert client.put("/api/insights/2026-02", json={"text": " "}, headers=WRITE).status_code == 422
    long = {"text": "x" * 4001}
    assert client.put("/api/insights/2026-02", json=long, headers=WRITE).status_code == 422
    # No data, nothing to analyze.
    assert client.put("/api/insights/2030-01", json={"text": "x"}, headers=WRITE).status_code == 404
