"""Hosted onboarding after the gate: landing month, checklist (with the missing months), the first
review of the top merchants and the demo/user isolation. Synthetic data only."""

from __future__ import annotations

import base64
import dataclasses
import time
from contextlib import closing
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from michelito import db
from michelito.demo.app import create_demo_app
from michelito.hosted import onboarding
from michelito.parsers import popular_card
from tests import samples
from tests.demo_helpers import (
    HOST,
    TODAY,
    _restore_providers,  # noqa: F401
    visitor,
)
from tests.demo_helpers import client as demo_client
from tests.demo_helpers import settings as demo_settings
from tests.helpers import store
from tests.hosted_helpers import WRITE, Hosted, hosted
from tests.synthetic_pdf import build

ALICE = "alice@example.com"


def signed_in_with_one_statement(tmp_path: Path) -> tuple[Hosted, TestClient]:
    h = hosted(tmp_path)
    alice = h.sign_in(ALICE)
    data = base64.b64encode(build(samples.POPULAR_PAGES)).decode()
    started = alice.post(
        "/api/uploads", json={"files": [{"name": "card.pdf", "data": data}]}, headers=WRITE
    )
    for _ in range(200):
        if alice.get(f"/api/uploads/{started.json()['id']}").json()["done"]:
            break
        time.sleep(0.02)
    return h, alice


def test_checklist_and_first_review_after_one_statement(tmp_path: Path) -> None:
    _, alice = signed_in_with_one_statement(tmp_path)
    state = alice.get("/api/onboarding").json()
    assert state["open"] is True
    assert state["first_review"] is True
    checklist = state["checklist"]
    assert checklist["visible"] is True
    assert checklist["months"] == 1 and checklist["more_months_done"] is False
    assert checklist["accounts"] == 1 and checklist["other_account_done"] is False


def test_top_merchants_by_amount_and_correct_marks_them_reviewed(tmp_path: Path) -> None:
    _, alice = signed_in_with_one_statement(tmp_path)
    merchants = alice.get("/api/onboarding/merchants").json()
    assert merchants, "a card statement has merchants"
    totals = [float(m["total"]) for m in merchants]
    assert totals == sorted(totals, reverse=True)
    assert all(m["status"] == "pending" for m in merchants)
    first = merchants[0]
    after = alice.put(
        "/api/onboarding/merchants/review", json={"merchant": first["merchant"]}, headers=WRITE
    ).json()
    assert next(m for m in after if m["merchant"] == first["merchant"])["status"] == "reviewed"
    # "Change" is the usual correction: a merchant rule.
    second = merchants[1]
    other = next(c for c in alice.get("/api/categories").json() if c["id"] != second["category_id"])
    changed = alice.patch(
        f"/api/transactions/{second['fingerprint']}",
        json={"category_id": other["id"], "scope": "merchant"},
        headers=WRITE,
    )
    assert changed.status_code == 200, changed.text
    statuses = {m["merchant"]: m["status"] for m in alice.get("/api/onboarding/merchants").json()}
    assert statuses[second["merchant"]] == "rule"
    unknown = alice.put(
        "/api/onboarding/merchants/review", json={"merchant": "NOBODY"}, headers=WRITE
    )
    assert unknown.status_code == 404


def test_later_and_dismiss_hide_the_card_and_the_checklist(tmp_path: Path) -> None:
    _, alice = signed_in_with_one_statement(tmp_path)
    for flag in ("first_review_closed", "checklist_dismissed"):
        assert alice.put(f"/api/onboarding/flags/{flag}", headers=WRITE).status_code == 204
    state = alice.get("/api/onboarding").json()
    assert state["first_review"] is False and state["checklist"]["visible"] is False
    assert alice.put("/api/onboarding/flags/other", headers=WRITE).status_code == 422


def test_missing_months_are_listed_like_the_report(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "michelito.db")
    january = popular_card.parse(samples.POPULAR_PAGES)
    store(conn, january)
    store(conn, dataclasses.replace(january, period_end=date(2026, 4, 13)))
    missing = onboarding.build_state(conn, ()).checklist.missing
    assert [(m.bank, m.kind, m.identifier, m.month) for m in missing] == [
        ("popular", "credit_card", "1234", "2026-02"),
        ("popular", "credit_card", "1234", "2026-03"),
    ]


def test_the_demo_never_touches_a_user_database_and_vice_versa(tmp_path: Path) -> None:
    """The demo is its own deployment (its own process, folder and cookie): the hosted app links
    to it and serves none of its routes, and writes on either side stay on that side."""
    (tmp_path / "app").mkdir()
    h, alice = signed_in_with_one_statement(tmp_path / "app")
    account = h.service.store.account_by_email(ALICE)
    user_db = h.data / "users" / account.folder / "michelito.db"
    key = h.service._data_key(account)
    assert alice.post("/api/demo/session", headers=WRITE).status_code in (403, 404)
    mode = alice.get("/api/mode").json()
    assert mode["mode"] == "hosted" and mode["demo_url"].startswith("https://")

    demo = visitor(demo_client(tmp_path / "demo"))
    assert demo.get("/api/mode").json()["mode"] == "demo"

    def categories(client: TestClient) -> set[str]:
        return {c["name"] for c in client.get("/api/categories").json()}

    made = demo.post(
        "/api/categories", json={"name": "Demo only", "kind": "expense"}, headers=WRITE
    )
    assert made.status_code == 201, made.text
    assert "Demo only" not in categories(alice)
    made = alice.post(
        "/api/categories", json={"name": "Mine only", "kind": "expense"}, headers=WRITE
    )
    assert made.status_code == 201, made.text
    assert "Mine only" not in categories(demo)
    with closing(db.connect(user_db, key)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM categories")}
    assert "Demo only" not in names and "Mine only" in names
    assert not any(user_db.parent == p.parent for p in (tmp_path / "demo").rglob("*.db"))


def test_the_demo_reports_the_way_back_only_when_configured(tmp_path: Path) -> None:
    """The sample-data band depends only on `/api/mode`: the usual demo stays as it was."""
    plain = demo_client(tmp_path / "plain").get("/api/mode").json()
    assert "return_url" not in plain
    configured = dataclasses.replace(
        demo_settings(tmp_path / "back"), return_url="https://app.example"
    )
    app = create_demo_app(configured, today=lambda: TODAY)
    mode = TestClient(app, base_url=f"http://{HOST}").get("/api/mode").json()
    assert mode["mode"] == "demo" and mode["return_url"] == "https://app.example"
