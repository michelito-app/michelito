"""The e2e server's live-sync data and test routes (what the Playwright live specs rely on)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from michelito.web.app import create_app
from tests import e2e_live
from tests.e2e_server import DEMO_TODAY, build_demo_db

WRITE = {"X-Michelito": "1"}
FEBRUARY = "2026-02"


def _client(tmp_path: Path) -> TestClient:
    path = tmp_path / "live.db"
    build_demo_db(path, live=True)
    app = create_app(path, today=lambda: DEMO_TODAY)
    e2e_live.register(app, path, lambda target: build_demo_db(target, live=True))
    return TestClient(app, "http://127.0.0.1")


def _pending(client: TestClient) -> set[str]:
    params = {"month": FEBRUARY, "provisional": "true"}
    return {r["merchant"] for r in client.get("/api/transactions", params=params).json()["items"]}


def test_the_statement_confirms_one_and_leaves_one_to_review(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert _pending(client) == {e2e_live.CONFIRMED[1], e2e_live.PENDING[1], e2e_live.VANISHED[1]}
    review = client.get("/api/review", params={"month": FEBRUARY}).json()
    assert not [i for i in review if i["kind"] == "unconfirmed"]

    assert client.post("/e2e/live/statement", headers=WRITE).json() == {"status": "parsed"}
    assert _pending(client) == {e2e_live.PENDING[1], e2e_live.VANISHED[1]}
    review = client.get("/api/review", params={"month": FEBRUARY}).json()
    assert [i["merchant"] for i in review if i["kind"] == "unconfirmed"] == [e2e_live.VANISHED[1]]

    assert client.post("/e2e/live/reset", headers=WRITE).json() == {"status": "ok"}
    assert len(_pending(client)) == 3
