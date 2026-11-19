"""The public demo: one copy per visitor, limits and what is not served."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from michelito.demo.app import PLAIN_COOKIE as COOKIE
from michelito.i18n import t
from tests.demo_helpers import HOST, WRITE, _restore_providers, client, visitor  # noqa: F401


def _first_fingerprint(api: TestClient) -> str:
    return api.get("/api/transactions", params={"month": "2026-10"}).json()["items"][0][
        "fingerprint"
    ]


def test_without_session_nothing_is_opened_or_written(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert api.get("/api/health").json() == {"status": "ok"}
    mode = api.get("/api/mode").json()
    assert mode["mode"] == "demo" and mode["session"] is False
    assert mode["name"] == "Michelito" and mode["repo"] == "https://example.com/repo"
    assert mode["notice"] == t("demo.notice")
    assert api.get("/api/summary").status_code == 401
    answer = api.put("/api/rates/2026-10", json={"value": "70"}, headers=WRITE)
    assert answer.status_code == 401
    assert list((tmp_path / "demo" / "copies").iterdir()) == []


def test_session_creates_a_copy_with_a_secure_cookie(tmp_path: Path) -> None:
    api = client(tmp_path)
    created = api.post("/api/demo/session", headers=WRITE)
    assert created.status_code == 201
    cookie = created.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    copy_id = api.cookies[COOKIE]
    assert len(copy_id) == 32 and int(copy_id, 16).bit_length() <= 128
    assert (tmp_path / "demo" / "copies" / copy_id / "michelito.db").is_file()
    assert api.post("/api/demo/session", headers=WRITE).json() == {"created": False}
    assert api.get("/api/mode").json()["session"] is True
    assert api.get("/api/summary").status_code == 200


def test_secure_flag_is_on_by_default(tmp_path: Path) -> None:
    from michelito.demo.app import Settings, create_demo_app

    app = create_demo_app(Settings(data=tmp_path / "d", public_host=HOST))
    answer = TestClient(app, base_url=f"https://{HOST}").post("/api/demo/session", headers=WRITE)
    assert "Secure" in answer.headers["set-cookie"]


def test_two_visitors_do_not_see_each_other(tmp_path: Path) -> None:
    one = client(tmp_path)
    one.post("/api/demo/session", headers=WRITE)
    two = visitor(one)
    fingerprint = _first_fingerprint(one)
    note = one.patch(f"/api/transactions/{fingerprint}", json={"note": "mine only"}, headers=WRITE)
    assert note.status_code == 200, note.text
    assert one.get(f"/api/transactions/{fingerprint}").json()["note"] == "mine only"
    assert not two.get(f"/api/transactions/{fingerprint}").json()["note"]
    template = tmp_path / "demo" / "template" / "michelito.db"
    with closing(sqlite3.connect(template)) as conn:
        found = conn.execute("SELECT COUNT(*) FROM transaction_notes WHERE note IS NOT NULL")
        assert found.fetchone()[0] == 0


def test_bad_cookies_never_reach_the_filesystem(tmp_path: Path) -> None:
    api = client(tmp_path)
    (tmp_path / "demo" / "copies" / "secret").mkdir()
    for bad in ("../template", "..", "secret", "A" * 32, "0" * 31, "0" * 33, "/etc"):
        api.cookies.set(COOKIE, bad)
        assert api.get("/api/accounts").status_code == 401, bad
        assert api.get("/api/mode").json()["session"] is False


def test_claude_is_rejected_and_the_header_still_required(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/session", headers=WRITE)
    fingerprint = _first_fingerprint(api)
    claude = {**WRITE, "X-Michelito-Author": "claude"}
    assert api.patch(f"/api/transactions/{fingerprint}", json={}, headers=claude).status_code == 403
    assert api.patch(f"/api/transactions/{fingerprint}", json={"note": "x"}).status_code == 403
    assert api.post("/api/demo/session").status_code == 403


def test_hosts_public_and_loopback_only(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert TestClient(api.app, base_url="http://127.0.0.1").get("/api/health").status_code == 200
    assert (
        TestClient(api.app, base_url="http://other.example").get("/api/health").status_code == 400
    )


def test_system_routes_are_not_served(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/session", headers=WRITE)
    for path in ("/api/sync", "/api/gmail/auth", "/api/secrets", "/api/import", "/api/system"):
        assert api.post(path, headers=WRITE).status_code == 403, path
    assert api.get("/api/archivos").status_code == 404


def test_body_size_is_capped(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/session", headers=WRITE)
    big = {"text": "x" * 70_000}
    assert api.post("/api/feedback", json=big, headers=WRITE).status_code == 413


def test_copies_per_ip_and_live_copies_are_capped(tmp_path: Path) -> None:
    api = client(tmp_path, per_ip=2, max_live=3)
    for _ in range(2):
        fresh = TestClient(api.app, base_url=f"http://{HOST}")
        assert fresh.post("/api/demo/session", headers=WRITE).status_code == 201
    third = TestClient(api.app, base_url=f"http://{HOST}").post("/api/demo/session", headers=WRITE)
    assert third.status_code == 429 and third.json()["detail"] == t("demo.too_many_copies")
    other_ip = TestClient(api.app, base_url=f"http://{HOST}", client=("2001:db8:a::9", 1))
    assert other_ip.post("/api/demo/session", headers=WRITE).status_code == 201
    last = TestClient(api.app, base_url=f"http://{HOST}", client=("2001:db8:b::9", 1))
    full = last.post("/api/demo/session", headers=WRITE)
    assert full.status_code == 503 and full.json()["detail"] == t("demo.full")


def test_requests_per_minute_are_capped(tmp_path: Path) -> None:
    api = client(tmp_path, per_minute=5)
    api.post("/api/demo/session", headers=WRITE)
    codes = [api.get("/api/accounts").status_code for _ in range(6)]
    assert codes[:4] == [200] * 4 and codes[-1] == 429


def test_sample_statement_route(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert api.post("/api/demo/sample-statement", headers=WRITE).status_code == 401
    api.post("/api/demo/session", headers=WRITE)
    result = api.post("/api/demo/sample-statement", headers=WRITE).json()
    assert result["balanced"] is True and result["transactions"] > 10
    assert result["period_end"] == "2026-12-10" and result["months"] == ["2026-11", "2026-12"]
    review = api.get("/api/review", params={"month": "2026-11"}).json()
    assert any(r["kind"] == "duplicate" for r in review)
