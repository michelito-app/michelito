"""Demo disk, CPU and memory caps, maintenance and cookie (`demo.app`, `demo.copies`)."""

from __future__ import annotations

import filecmp
import logging
import os
import sqlite3
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from michelito import db
from michelito.demo import feedback_store, network
from michelito.demo.app import (
    PLAIN_COOKIE,
    SECURE_COOKIE,
    PerCopy,
    Turns,
    create_demo_app,
)
from michelito.i18n import t
from michelito.web.app import _body_refusal
from tests.demo_helpers import HOST, TODAY, WRITE, _restore_providers, settings  # noqa: F401


def _app(tmp_path: Path, today=lambda: TODAY, **changes):  # noqa: ANN001, ANN202
    limits = changes.pop("limits", {})
    return create_demo_app(replace(settings(tmp_path, **limits), **changes), today=today)


def _visitor(app, client=("2001:db8:1::1", 1)) -> TestClient:  # noqa: ANN001
    api = TestClient(app, base_url=f"http://{HOST}", client=client)
    assert api.post("/api/demo/session", headers=WRITE).status_code == 201
    return api


def test_a_full_copy_answers_507_and_can_start_over(tmp_path: Path) -> None:
    api = _visitor(_app(tmp_path, copy_extra=0))
    items = api.get("/api/transactions", params={"month": "2026-10"}).json()["items"]
    codes = set()
    for item in items:
        answer = api.patch(
            f"/api/transactions/{item['fingerprint']}", json={"note": "x" * 500}, headers=WRITE
        )
        codes.add(answer.status_code)
        if answer.status_code == 507:
            assert answer.json()["detail"] == t("demo.copy_full")
            break
    assert 507 in codes
    old = api.cookies[PLAIN_COOKIE]
    assert api.post("/api/demo/restart", headers=WRITE).status_code == 201
    assert api.cookies[PLAIN_COOKIE] != old
    assert not (tmp_path / "demo" / "copies" / old).exists()
    fingerprint = items[0]["fingerprint"]
    answer = api.patch(f"/api/transactions/{fingerprint}", json={"note": "ok"}, headers=WRITE)
    assert answer.status_code == 200


def test_without_free_disk_the_demo_is_full(tmp_path: Path) -> None:
    app = _app(tmp_path, limits={"min_free": 10**18})
    answer = TestClient(app, base_url=f"http://{HOST}").post("/api/demo/session", headers=WRITE)
    assert answer.status_code == 503


def test_full_demo_evicts_the_oldest_idle_copy(tmp_path: Path) -> None:
    app = _app(tmp_path, limits={"max_live": 1})
    first = _visitor(app)
    folder = tmp_path / "demo" / "copies" / first.cookies[PLAIN_COOKIE]
    recent = time.time() - 60
    os.utime(folder, (recent, recent))
    blocked = TestClient(app, base_url=f"http://{HOST}", client=("2001:db8:2::1", 1))
    assert blocked.post("/api/demo/session", headers=WRITE).status_code == 503
    old = time.time() - 2 * 3600
    os.utime(folder, (old, old))
    _visitor(app, ("2001:db8:3::1", 1))
    assert not folder.exists()


def test_ipv6_wider_prefixes_have_their_own_quota(tmp_path: Path) -> None:
    app = _app(tmp_path, limits={"per_ip": 1})
    codes = []
    for subnet in range(4):  # four /64s of the same /56: the /56 has a quota of 2
        api = TestClient(app, base_url=f"http://{HOST}", client=(f"2001:db8:0:{subnet}::1", 1))
        codes.append(api.post("/api/demo/session", headers=WRITE).status_code)
    assert codes == [201, 201, 429, 429]


def test_expensive_routes_spend_more_of_the_budget(tmp_path: Path) -> None:
    # The budget is per wall-clock minute: if the test crosses into the next minute, the charge
    # resets halfway and the 429 never comes. Start far from the boundary.
    if time.time() % 60 > 45:
        time.sleep(61 - time.time() % 60)
    api = _visitor(_app(tmp_path, limits={"per_minute": 25}))
    assert api.get("/api/reports/compare").status_code == 200  # costs 20
    assert api.get("/api/summary").status_code == 200  # 3 more
    assert api.get("/api/reports/compare").status_code == 429
    assert api.get("/api/accounts").status_code == 200  # 1: still fits
    assert api.get("/api/mode").status_code == 200  # free


def test_one_turn_per_copy_and_bounded_global_turns() -> None:
    async def scenario() -> list[object]:
        turns = Turns(workers=1, copy_wait=0.05, global_wait=0.05)
        first = await turns.take("a")
        same_copy = await turns.take("a")
        other_copy = await turns.take("b")
        assert callable(first)
        first()
        again = await turns.take("b")
        assert callable(again)
        again()
        return [same_copy.status_code, other_copy.status_code]  # type: ignore[union-attr]

    assert anyio.run(scenario) == [429, 503]


def test_mode_refreshes_the_cookie(tmp_path: Path) -> None:
    api = _visitor(_app(tmp_path))
    answer = api.get("/api/mode")
    assert answer.json()["session"] is True
    assert f"{PLAIN_COOKIE}={api.cookies[PLAIN_COOKIE]}" in answer.headers["set-cookie"]


def test_secure_cookie_uses_the_host_prefix(tmp_path: Path) -> None:
    app = _app(tmp_path, secure_cookie=True)
    api = TestClient(app, base_url=f"https://{HOST}")
    cookie = api.post("/api/demo/session", headers=WRITE).headers["set-cookie"]
    assert cookie.startswith(f"{SECURE_COOKIE}=") and "Secure" in cookie and "Path=/" in cookie
    assert "Domain" not in cookie
    assert api.get("/api/mode").json()["session"] is True


def test_sweep_with_an_open_connection(tmp_path: Path) -> None:
    app = _app(tmp_path)
    api = _visitor(app)
    copy_id = api.cookies[PLAIN_COOKIE]
    folder = tmp_path / "demo" / "copies" / copy_id
    conn = db.connect(folder / "michelito.db")
    try:
        old = time.time() - 2 * 24 * 3600
        os.utime(folder, (old, old))
        app.state.maintenance.sweep()
        assert not folder.exists()
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] > 0
    finally:
        conn.close()
    assert not folder.exists()  # closing does not recreate it
    assert api.get("/api/accounts").status_code == 401


def test_session_survives_a_failing_counter(tmp_path: Path, monkeypatch) -> None:
    app = _app(tmp_path)

    def broken(*args: object) -> None:
        raise sqlite3.OperationalError("failing disk")

    monkeypatch.setattr(feedback_store.Feedback, "count", broken)
    api = TestClient(app, base_url=f"http://{HOST}")
    answer = api.post("/api/demo/session", headers=WRITE)
    assert answer.status_code == 201 and PLAIN_COOKIE in api.cookies


def test_new_month_gets_a_new_template_and_live_copies_keep_theirs(tmp_path: Path) -> None:
    day = [TODAY]
    app = _app(tmp_path, today=lambda: day[0])
    api = _visitor(app)
    copy = tmp_path / "demo" / "copies" / api.cookies[PLAIN_COOKIE] / "michelito.db"
    template = tmp_path / "demo" / "template" / "michelito.db"
    assert filecmp.cmp(copy, template, shallow=False)
    before = copy.read_bytes()
    day[0] = date(2026, 12, 2)
    app.state.maintenance.run_once()
    assert not filecmp.cmp(copy, template, shallow=False)
    assert copy.read_bytes() == before
    months = [m["month"] for m in _visitor(app, ("2001:db8:9::1", 1)).get("/api/months").json()]
    assert max(months) == "2026-12"
    assert not list((tmp_path / "demo").glob(".template-*"))


def test_template_build_cleans_leftovers(tmp_path: Path) -> None:
    (tmp_path / "demo").mkdir()
    for leftover in (".template-old", ".template-new-abc"):
        (tmp_path / "demo" / leftover).mkdir()
    _app(tmp_path)
    assert not list((tmp_path / "demo").glob(".template-*"))


def test_per_copy_limits_are_pruned() -> None:
    limits = PerCopy(1)
    assert limits.take("a") and limits.take("b") and not limits.take("a")
    limits.prune({"b"})
    assert limits.take("a")


def test_global_opinion_caps(tmp_path: Path) -> None:
    app = _app(tmp_path, feedback_caps=feedback_store.Caps(per_minute=2))
    codes = []
    for n in range(3):
        api = _visitor(app, (f"2001:db8:{n}::1", 1))
        codes.append(api.post("/api/feedback", json={"text": "hello"}, headers=WRITE).status_code)
    assert codes == [201, 201, 503]
    full = feedback_store.Feedback(tmp_path / "other.db", feedback_store.Caps(rows=1))
    full.save(feedback_store.Opinion("one"))
    with pytest.raises(feedback_store.FeedbackFull):
        full.save(feedback_store.Opinion("two"))


def test_unconfigured_proxy_is_reported_once(caplog, monkeypatch) -> None:
    monkeypatch.setattr(network, "_warned", False)
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 1),
        "headers": [(b"x-forwarded-for", b"2001:db8::5")],
    }
    with caplog.at_level(logging.WARNING):
        network.warn_unconfigured_proxy(Request(scope), ())
        network.warn_unconfigured_proxy(Request(scope), ())
    assert len([r for r in caplog.records if "--trusted-proxy" in r.message]) == 1


def test_repeated_forwarded_headers_are_joined() -> None:
    scope = {
        "type": "http",
        "client": ("10.0.0.5", 1),
        "headers": [(b"x-forwarded-for", b"2001:db8::bad"), (b"x-forwarded-for", b"2001:db8::7")],
    }
    assert network.client_ip(Request(scope), network.networks(["10.0.0.0/8"])) == "2001:db8::7"


@pytest.mark.parametrize("length", ["١٢", "12x", "-1", "99999999"])
def test_body_length_must_be_ascii_digits_within_the_cap(length: str) -> None:
    scope = {"type": "http", "headers": [(b"content-length", length.encode())]}
    refusal = _body_refusal(Request(scope), 1000)
    assert refusal is not None and refusal.status_code == 413


def test_restart_does_not_reset_per_copy_limits(tmp_path: Path) -> None:
    api = _visitor(_app(tmp_path, samples_per_copy=1, opinions_per_copy=1))
    assert api.post("/api/demo/sample-statement", headers=WRITE).status_code == 200
    assert api.post("/api/feedback", json={"text": "one"}, headers=WRITE).status_code == 201
    assert api.post("/api/demo/restart", headers=WRITE).status_code == 201
    assert api.post("/api/demo/sample-statement", headers=WRITE).status_code == 429
    assert api.post("/api/feedback", json={"text": "two"}, headers=WRITE).status_code == 429
    again = api.post("/api/demo/restart", headers=WRITE)
    assert again.status_code == 429 and again.json()["detail"] == t("demo.restarts")


def test_per_copy_transfer() -> None:
    limits = PerCopy(1)
    assert limits.take("old")
    limits.transfer("old", "new")
    assert not limits.take("new") and limits.take("old")
