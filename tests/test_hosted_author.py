"""Hosted mode accepts `X-Michelito-Author: claude`, so what Claude Code applies through the API
on the person's behalf shows up in their change log as Claude's (and can be undone there).
Synthetic statements only."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.hosted_helpers import WRITE, Hosted
from tests.test_hosted_onboarding import signed_in_with_one_statement

CLAUDE = {**WRITE, "X-Michelito-Author": "claude"}


def _first_expense(alice: TestClient) -> dict:
    month = alice.get("/api/months").json()[0]["month"]
    rows = alice.get("/api/transactions", params={"month": month}).json()["items"]
    return next(row for row in rows if row["kind"] == "expense")


def _other_category(alice: TestClient, current: int) -> int:
    categories = alice.get("/api/categories").json()
    return next(c["id"] for c in categories if c["id"] != current and c["kind"] == "expense")


def _signed_in(tmp_path: Path) -> tuple[Hosted, TestClient]:
    return signed_in_with_one_statement(tmp_path)


def test_a_change_made_as_claude_is_logged_as_claude(tmp_path: Path) -> None:
    _, alice = _signed_in(tmp_path)
    row = _first_expense(alice)
    target = _other_category(alice, row["category_id"])
    changed = alice.patch(
        f"/api/transactions/{row['fingerprint']}", json={"category_id": target}, headers=CLAUDE
    )
    assert changed.status_code == 200, changed.text
    entry = alice.get("/api/log").json()["items"][0]
    assert entry["author"] == "claude"
    assert row["fingerprint"] in entry["fingerprints"]
    undone = alice.post(f"/api/log/{entry['id']}/undo", headers=WRITE)
    assert undone.is_success, undone.text


def test_without_the_header_the_change_is_the_users(tmp_path: Path) -> None:
    _, alice = _signed_in(tmp_path)
    row = _first_expense(alice)
    target = _other_category(alice, row["category_id"])
    alice.patch(
        f"/api/transactions/{row['fingerprint']}", json={"category_id": target}, headers=WRITE
    )
    assert alice.get("/api/log").json()["items"][0]["author"] == "user"


def test_an_unknown_author_is_still_refused(tmp_path: Path) -> None:
    _, alice = _signed_in(tmp_path)
    row = _first_expense(alice)
    other = {**WRITE, "X-Michelito-Author": "someone"}
    answer = alice.patch(f"/api/transactions/{row['fingerprint']}", json={}, headers=other)
    assert answer.status_code == 400


def test_claude_still_needs_a_session(tmp_path: Path) -> None:
    h, _ = _signed_in(tmp_path)
    stranger = h.client()
    assert stranger.patch("/api/transactions/x", json={}, headers=CLAUDE).status_code == 401
