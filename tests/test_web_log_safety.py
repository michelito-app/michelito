"""Undo and redo in Shared stay safe: never taking out of a group a person who has shares or
payments there after the change, undoing payment changes recorded before schema 21 (their
allocations came with the migration), and saying which later change to undo or redo first.
Made-up data."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import changelog
from michelito.i18n import t
from michelito.web import log_routes
from tests import test_web_ledger as base
from tests.test_web_ledger import WRITE, _group, _ids, _pay

db_path = base.db_path
client = base.client


def _last(client: TestClient) -> dict:
    return client.get("/api/log").json()["items"][0]


def _row(client: TestClient, entry_id: int) -> dict:
    return next(e for e in client.get("/api/log").json()["items"] if e["id"] == entry_id)


def _members(client: TestClient, group_id: int) -> list[str]:
    group = client.get(f"/api/shared/groups/{group_id}").json()
    return [m["name"] for m in group["members"] if not m["is_me"]]


def _expense_with(client: TestClient, group_id: int, me: int, person: int) -> int:
    body = {
        "paid_by": me,
        "amount_cents": 60000,
        "description": "Taxi",
        "day": "2026-01-12",
        "people": [me, person],
    }
    made = client.post(f"/api/shared/groups/{group_id}/entries", json=body, headers=WRITE)
    assert made.status_code == 201, made.text
    return int(_last(client)["id"])


def test_undoing_an_add_person_is_refused_once_they_have_a_share(client: TestClient) -> None:
    group = _group(client, people=[{"name": "Ana"}])
    me, _ = _ids(group)
    pedro = client.post("/api/shared/contacts", json={"name": "Pedro"}, headers=WRITE).json()["id"]
    added = client.post(
        f"/api/shared/groups/{group['id']}/members", json={"contact_id": pedro}, headers=WRITE
    )
    assert added.status_code == 200
    add = _last(client)["id"]
    taxi = _expense_with(client, group["id"], me, pedro)
    row = _row(client, add)
    assert not row["can_undo"] and row["blocked_by"] == taxi
    assert "Pedro" in row["undo_message"] and f"n.º {taxi}" in row["undo_message"]
    assert client.post(f"/api/log/{add}/undo", headers=WRITE).status_code == 409
    assert "Pedro" in _members(client, group["id"])
    # Once the expense is undone, so can the person be.
    assert client.post(f"/api/log/{taxi}/undo", headers=WRITE).status_code == 200
    assert client.post(f"/api/log/{add}/undo", headers=WRITE).status_code == 200
    assert "Pedro" not in _members(client, group["id"])


def test_redoing_a_removal_is_refused_once_they_have_a_share(client: TestClient) -> None:
    group = _group(client, people=[{"name": "Ana"}, {"name": "Pedro"}])
    me, people = _ids(group)
    url = f"/api/shared/groups/{group['id']}/members/{people['Pedro']}"
    assert client.delete(url, headers=WRITE).status_code == 200
    removal = _last(client)["id"]
    assert client.post(f"/api/log/{removal}/undo", headers=WRITE).status_code == 200
    taxi = _expense_with(client, group["id"], me, people["Pedro"])
    row = _row(client, removal)
    assert row["undone"] and not row["can_redo"] and row["blocked_by"] == taxi
    tail = t("analysis.changelog.blocked_by", reason="", id=taxi).removeprefix(": ")
    assert row["undo_message"].endswith(tail)
    refused = client.post(f"/api/log/{removal}/redo", headers=WRITE)
    assert refused.status_code == 409
    assert "Pedro" in _members(client, group["id"])


def _strip_allocations(db_path: Path, entry_id: int) -> None:
    """The entry as schema 20 recorded it: without the allocation rows."""
    with closing(db.connect(db_path)) as conn, conn:
        raw = conn.execute("SELECT changes FROM change_log WHERE id = ?", (entry_id,)).fetchone()
        changes = [c for c in json.loads(raw[0]) if c["table"] != "ledger_allocations"]
        conn.execute(
            "UPDATE change_log SET changes = ? WHERE id = ?", (json.dumps(changes), entry_id)
        )
        conn.execute(
            "DELETE FROM change_log_rows WHERE entry_id = ? "
            "AND row_key LIKE 'ledger_allocations:%'",
            (entry_id,),
        )


def test_payment_changes_from_before_schema_21_undo(client: TestClient, db_path: Path) -> None:
    group = _group(client, people=[{"name": "Ana"}])
    me, people = _ids(group)
    body = {"from_contact": people["Ana"], "to_contact": me, "amount_cents": 1000}
    before = client.get(f"/api/shared/groups/{group['id']}").json()
    assert _pay(client, group["id"], {**body, "day": "2026-01-20"}).status_code == 201
    paid = _last(client)["id"]
    _strip_allocations(db_path, paid)
    assert _row(client, paid)["can_undo"]
    assert client.post(f"/api/log/{paid}/undo", headers=WRITE).status_code == 200
    assert client.get(f"/api/shared/groups/{group['id']}").json() == before
    # Redo brings the payment back (with its allocation, which the undo recorded).
    assert client.post(f"/api/log/{paid}/redo", headers=WRITE).status_code == 200

    loose = {"to_contact": me, "amount_cents": 500, "day": "2026-01-21"}
    made = _pay(client, group["id"], loose).json()
    payment = made["unattributed"][0]["id"]
    assigned = client.patch(
        f"/api/shared/payments/{payment}", json={"from_contact": people["Ana"]}, headers=WRITE
    )
    assert assigned.status_code == 200
    assign = _last(client)["id"]
    _strip_allocations(db_path, assign)
    assert client.post(f"/api/log/{assign}/undo", headers=WRITE).status_code == 200
    with closing(db.connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM ledger_allocations WHERE payment_id = ?", (payment,)
        ).fetchone()[0]
    assert rows == 0  # unassigned again: nobody's
    group_now = client.get(f"/api/shared/groups/{group['id']}").json()
    assert [p["id"] for p in group_now["unattributed"]] == [payment]


def test_the_blocking_change_is_named_by_its_original_and_the_right_verb() -> None:
    chains = changelog.Toggles({30: 20, 31: 30})  # 20 undone (30), then redone (31)
    blocked = changelog.UndoState(False, blocked_by=30, message="old", reason="Choca")
    undo = log_routes._rooted(blocked, chains, frozenset({30}))  # 20 in effect: undo it
    assert (undo.blocked_by, undo.message) == (
        20,
        "Choca: primero deshaz la entrada posterior n.º 20.",  # spanish-ui
    )
    redo = log_routes._rooted(blocked, chains, frozenset({20}))  # 20 undone: redo it
    assert redo.message == "Choca: primero rehaz la entrada posterior n.º 20."  # spanish-ui
    bare = changelog.UndoState(False, blocked_by=31, message="old")
    assert log_routes._rooted(bare, chains, frozenset({20})).message == (
        "Primero rehaz la entrada posterior n.º 20."  # spanish-ui
    )
