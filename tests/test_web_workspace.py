"""The board's database provider (`web.workspace`): locally, always the same database."""

from pathlib import Path

from fastapi.testclient import TestClient
from starlette.requests import Request

from michelito.web.app import create_app
from michelito.web.workspace import FixedProvider, Mode, Resolution, Workspace


def test_health_and_mode_do_not_open_the_database(tmp_path: Path) -> None:
    path = tmp_path / "michelito.db"
    client = TestClient(create_app(path), base_url="http://127.0.0.1")
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/mode").json() == {"mode": "local", "session": True}
    assert not path.exists()


def test_routes_use_the_workspace_the_provider_gives(tmp_path: Path) -> None:
    chosen = Workspace(tmp_path / "chosen.db", tmp_path / "holders.txt")
    mode = Mode("test", FixedProvider(chosen), ("127.0.0.1",), ("user",))
    client = TestClient(create_app(tmp_path / "other.db", mode=mode), base_url="http://127.0.0.1")
    assert client.get("/api/accounts").status_code == 200
    assert chosen.database.exists()
    assert not (tmp_path / "other.db").exists()


class _Nobody:
    async def resolve(self, request: Request) -> Resolution:
        return Resolution(None)

    def has_session(self, request: Request) -> bool:
        return False


def test_without_workspace_no_database_is_opened(tmp_path: Path) -> None:
    mode = Mode("test", _Nobody(), ("127.0.0.1",), ("user",))
    client = TestClient(create_app(tmp_path / "x.db", mode=mode), base_url="http://127.0.0.1")
    answer = client.patch("/api/transactions/abc", json={}, headers={"X-Michelito": "1"})
    assert answer.status_code == 401
    assert client.get("/api/accounts").status_code == 401
    assert client.get("/api/mode").json()["session"] is False
    assert list(tmp_path.iterdir()) == []


def test_mode_rejects_other_authors_and_blocked_routes(tmp_path: Path) -> None:
    fixed = FixedProvider(Workspace(tmp_path / "f.db", tmp_path / "t.txt"))
    mode = Mode("test", fixed, ("127.0.0.1",), ("user",), blocked=("/api/sync",), max_body=10)
    client = TestClient(create_app(tmp_path / "f.db", mode=mode), base_url="http://127.0.0.1")
    headers = {"X-Michelito": "1", "X-Michelito-Author": "claude"}
    assert client.put("/api/rates/2026-01", json={}, headers=headers).status_code == 403
    assert client.post("/api/sync", headers={"X-Michelito": "1"}).status_code == 403
    big = client.put("/api/rates/2026-01", content=b"x" * 11, headers={"X-Michelito": "1"})
    assert big.status_code == 413
