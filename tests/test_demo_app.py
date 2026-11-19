"""La demo pública: una copia por visitante, límites y lo que no se sirve."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from finanzas.demo.app import PLAIN_COOKIE as COOKIE
from tests.demo_helpers import HOST, WRITE, _restore_providers, client, visitor  # noqa: F401


def _first_fingerprint(api: TestClient) -> str:
    return api.get("/api/transactions", params={"month": "2026-10"}).json()["items"][0][
        "fingerprint"
    ]


def test_without_session_nothing_is_opened_or_written(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert api.get("/api/health").json() == {"estado": "ok"}
    mode = api.get("/api/modo").json()
    assert mode["modo"] == "demo" and mode["sesion"] is False
    assert mode["nombre"] == "Michelito" and mode["repo"] == "https://example.com/repo"
    assert api.get("/api/summary").status_code == 401
    answer = api.put("/api/rates/2026-10", json={"value": "70"}, headers=WRITE)
    assert answer.status_code == 401
    assert list((tmp_path / "demo" / "copias").iterdir()) == []


def test_session_creates_a_copy_with_a_secure_cookie(tmp_path: Path) -> None:
    api = client(tmp_path)
    created = api.post("/api/demo/sesion", headers=WRITE)
    assert created.status_code == 201
    cookie = created.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    copy_id = api.cookies[COOKIE]
    assert len(copy_id) == 32 and int(copy_id, 16).bit_length() <= 128
    assert (tmp_path / "demo" / "copias" / copy_id / "finanzas.db").is_file()
    assert api.post("/api/demo/sesion", headers=WRITE).json() == {"creada": False}
    assert api.get("/api/modo").json()["sesion"] is True
    assert api.get("/api/summary").status_code == 200


def test_secure_flag_is_on_by_default(tmp_path: Path) -> None:
    from finanzas.demo.app import Settings, create_demo_app

    app = create_demo_app(Settings(data=tmp_path / "d", public_host=HOST))
    answer = TestClient(app, base_url=f"https://{HOST}").post("/api/demo/sesion", headers=WRITE)
    assert "Secure" in answer.headers["set-cookie"]


def test_two_visitors_do_not_see_each_other(tmp_path: Path) -> None:
    one = client(tmp_path)
    one.post("/api/demo/sesion", headers=WRITE)
    two = visitor(one)
    fingerprint = _first_fingerprint(one)
    note = one.patch(f"/api/transactions/{fingerprint}", json={"note": "solo mía"}, headers=WRITE)
    assert note.status_code == 200, note.text
    assert one.get(f"/api/transactions/{fingerprint}").json()["note"] == "solo mía"
    assert not two.get(f"/api/transactions/{fingerprint}").json()["note"]
    template = tmp_path / "demo" / "plantilla" / "finanzas.db"
    with closing(sqlite3.connect(template)) as conn:
        found = conn.execute("SELECT COUNT(*) FROM transaction_notes WHERE note IS NOT NULL")
        assert found.fetchone()[0] == 0


def test_bad_cookies_never_reach_the_filesystem(tmp_path: Path) -> None:
    api = client(tmp_path)
    (tmp_path / "demo" / "copias" / "secreto").mkdir()
    for bad in ("../plantilla", "..", "secreto", "A" * 32, "0" * 31, "0" * 33, "/etc"):
        api.cookies.set(COOKIE, bad)
        assert api.get("/api/accounts").status_code == 401, bad
        assert api.get("/api/modo").json()["sesion"] is False


def test_claude_is_rejected_and_the_header_still_required(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/sesion", headers=WRITE)
    fingerprint = _first_fingerprint(api)
    claude = {**WRITE, "X-Finanzas-Autor": "claude"}
    assert api.patch(f"/api/transactions/{fingerprint}", json={}, headers=claude).status_code == 403
    assert api.patch(f"/api/transactions/{fingerprint}", json={"note": "x"}).status_code == 403
    assert api.post("/api/demo/sesion").status_code == 403


def test_hosts_public_and_loopback_only(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert TestClient(api.app, base_url="http://127.0.0.1").get("/api/health").status_code == 200
    assert TestClient(api.app, base_url="http://otro.example").get("/api/health").status_code == 400


def test_system_routes_are_not_served(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/sesion", headers=WRITE)
    for path in ("/api/sync", "/api/gmail/auth", "/api/secretos", "/api/importar", "/api/sistema"):
        assert api.post(path, headers=WRITE).status_code == 403, path
    assert api.get("/api/archivos").status_code == 404


def test_body_size_is_capped(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/sesion", headers=WRITE)
    big = {"texto": "x" * 70_000}
    assert api.post("/api/opiniones", json=big, headers=WRITE).status_code == 413


def test_copies_per_ip_and_live_copies_are_capped(tmp_path: Path) -> None:
    api = client(tmp_path, per_ip=2, max_live=3)
    for _ in range(2):
        fresh = TestClient(api.app, base_url=f"http://{HOST}")
        assert fresh.post("/api/demo/sesion", headers=WRITE).status_code == 201
    third = TestClient(api.app, base_url=f"http://{HOST}").post("/api/demo/sesion", headers=WRITE)
    assert third.status_code == 429 and "conexión" in third.json()["detail"]
    other_ip = TestClient(api.app, base_url=f"http://{HOST}", client=("2001:db8:a::9", 1))
    assert other_ip.post("/api/demo/sesion", headers=WRITE).status_code == 201
    last = TestClient(api.app, base_url=f"http://{HOST}", client=("2001:db8:b::9", 1))
    full = last.post("/api/demo/sesion", headers=WRITE)
    assert full.status_code == 503 and "llena" in full.json()["detail"]


def test_requests_per_minute_are_capped(tmp_path: Path) -> None:
    api = client(tmp_path, per_minute=5)
    api.post("/api/demo/sesion", headers=WRITE)
    codes = [api.get("/api/accounts").status_code for _ in range(6)]
    assert codes[:4] == [200] * 4 and codes[-1] == 429


def test_sample_statement_route(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert api.post("/api/demo/estado-ejemplo", headers=WRITE).status_code == 401
    api.post("/api/demo/sesion", headers=WRITE)
    result = api.post("/api/demo/estado-ejemplo", headers=WRITE).json()
    assert result["cuadra"] is True and result["transacciones"] > 10
    assert result["hasta"] == "2026-12-10" and result["meses"] == ["2026-11", "2026-12"]
    review = api.get("/api/review", params={"month": "2026-11"}).json()
    assert any(r["kind"] == "duplicado" for r in review)
