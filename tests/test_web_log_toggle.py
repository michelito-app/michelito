"""The change log shows one row per original change: "Undo" turns it to undone with "Redo" (and
back), the audit records stay under it, a later change on the same rows still blocks, older
chains of undos of undos collapse into the original's state, and Shared's changes read as a
sentence that links to the group. Made-up data."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import changelog, changelog_ledger
from michelito.analysis.changelog_rules import Change
from tests import test_web_ledger as base
from tests.test_web_ledger import WRITE, _group, _ids

db_path = base.db_path
client = base.client

GROUP = "Serie Mundial MLB"  # spanish-data


def _log(client: TestClient) -> list[dict]:
    return client.get("/api/log").json()["items"]


def _row(client: TestClient, entry_id: int) -> dict:
    return next(e for e in _log(client) if e["id"] == entry_id)


def _members(client: TestClient, group_id: int) -> list[str]:
    group = client.get(f"/api/shared/groups/{group_id}").json()
    return [m["name"] for m in group["members"] if not m["is_me"]]


def test_undo_and_redo_toggle_one_row(client: TestClient) -> None:
    group = _group(client, GROUP, [{"name": "Javier"}])
    added = client.post(
        f"/api/shared/groups/{group['id']}/members", json={"name": "El Gordo"}, headers=WRITE
    )
    assert added.status_code == 200
    entry = _log(client)[0]
    assert entry["summary"] == f"Agregaste a El Gordo al grupo {GROUP}"  # spanish-ui
    assert (entry["link_kind"], entry["link_id"]) == ("group", group["id"])
    assert entry["can_undo"] and not entry["can_redo"] and entry["toggles"] == 0
    rows = len(_log(client))

    undone = client.post(f"/api/log/{entry['id']}/undo", headers=WRITE)
    assert undone.status_code == 200
    assert (undone.json()["undone"], undone.json()["can_redo"], undone.json()["can_undo"]) == (
        True,
        True,
        False,
    )
    assert _members(client, group["id"]) == ["Javier"]
    # El Gordo's contact is gone with the undo: the sentence keeps the name from the change.
    assert undone.json()["summary"] == entry["summary"]
    assert len(_log(client)) == rows  # no new row
    again = client.post(f"/api/log/{entry['id']}/undo", headers=WRITE)
    assert again.status_code == 409

    redone = client.post(f"/api/log/{entry['id']}/redo", headers=WRITE)
    assert redone.status_code == 200 and not redone.json()["undone"]
    assert redone.json()["toggles"] == 2 and redone.json()["toggled_at"]
    assert _members(client, group["id"]) == ["Javier", "El Gordo"]
    assert client.post(f"/api/log/{entry['id']}/redo", headers=WRITE).status_code == 409
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
    assert _row(client, entry["id"])["toggles"] == 3
    assert len(_log(client)) == rows
    assert all(e["undoes"] is None for e in _log(client))


def test_an_audit_record_is_never_undone_directly(client: TestClient, db_path: Path) -> None:
    group = _group(client, GROUP, [{"name": "Javier"}])
    entry = _log(client)[0]
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
    with closing(db.connect(db_path)) as conn:
        record = conn.execute(
            "SELECT id FROM change_log WHERE undoes = ?", (entry["id"],)
        ).fetchone()[0]
    refused = client.post(f"/api/log/{record}/undo", headers=WRITE)
    assert refused.status_code == 409 and "original" in refused.json()["detail"]
    assert client.post(f"/api/log/{record}/redo", headers=WRITE).status_code == 409
    assert client.get(f"/api/shared/groups/{group['id']}").status_code == 404


def test_redo_is_refused_when_a_later_change_would_be_overwritten(client: TestClient) -> None:
    group = _group(client, GROUP, [{"name": "Javier"}])
    url = f"/api/shared/groups/{group['id']}"
    client.patch(url, json={"name": "Serie A"}, headers=WRITE)
    first = _log(client)[0]
    assert client.post(f"/api/log/{first['id']}/undo", headers=WRITE).status_code == 200
    client.patch(url, json={"name": "Serie B"}, headers=WRITE)
    later = _log(client)[0]
    row = _row(client, first["id"])
    assert row["undone"] and not row["can_redo"] and row["blocked_by"] == later["id"]
    assert str(later["id"]) in row["undo_message"]
    refused = client.post(f"/api/log/{first['id']}/redo", headers=WRITE)
    assert refused.status_code == 409
    assert client.get(url).json()["name"] == "Serie B"


def test_an_old_chain_of_undos_collapses_into_the_original(
    client: TestClient, db_path: Path
) -> None:
    """The owner's case: add -> remove -> undo -> undo of the undo ... six times, recorded the old
    way (each undo undoing the previous record)."""
    group = _group(client, GROUP, [{"name": "Javier"}])
    gid = group["id"]
    _, people = _ids(group)
    client.post(f"/api/shared/groups/{gid}/members", json={"name": "El Gordo"}, headers=WRITE)
    added = _log(client)[0]
    gordo = _ids(client.get(f"/api/shared/groups/{gid}").json())[1]["El Gordo"]
    client.delete(f"/api/shared/groups/{gid}/members/{gordo}", headers=WRITE)
    removed = _log(client)[0]
    with closing(db.connect(db_path)) as conn:
        tip = removed["id"]
        for _ in range(6):
            with conn:
                tip = changelog.undo(conn, tip)
        assert (
            conn.execute("SELECT COUNT(*) FROM change_log WHERE undoes IS NOT NULL").fetchone()[0]
            == 6
        )
    items = _log(client)
    assert [e["id"] for e in items[:2]] == [removed["id"], added["id"]]
    assert all(e["undoes"] is None for e in items)
    row = _row(client, removed["id"])
    # Six toggles: the removal is in effect again, and it says how many times it went back and
    # forth.
    assert (row["undone"], row["can_undo"], row["toggles"]) == (False, True, 6)
    assert row["summary"] == f"Quitaste a El Gordo del grupo {GROUP}"  # spanish-ui
    assert _members(client, gid) == ["Javier"]
    assert client.post(f"/api/log/{removed['id']}/undo", headers=WRITE).status_code == 200
    assert _members(client, gid) == ["Javier", "El Gordo"]
    row = _row(client, removed["id"])
    assert (row["undone"], row["can_redo"], row["toggles"]) == (True, True, 7)
    assert client.post(f"/api/log/{removed['id']}/redo", headers=WRITE).status_code == 200
    assert _members(client, gid) == ["Javier"]
    assert people["Javier"] in {
        m["id"] for m in client.get(f"/api/shared/groups/{gid}").json()["members"]
    }


def test_shared_changes_read_as_sentences(client: TestClient) -> None:
    group = _group(client, GROUP, [{"name": "Javier"}, {"name": "El Gordo"}])
    me, people = _ids(group)
    gid = group["id"]
    assert _log(client)[0]["summary"] == (
        f"Creaste el grupo {GROUP} con Javier y El Gordo"  # spanish-ui
    )
    client.post(
        f"/api/shared/groups/{gid}/entries",
        json={
            "paid_by": me,
            "amount_cents": 489600,
            "description": "Entradas",  # spanish-data
            "day": "2026-01-10",
            "people": [me, *people.values()],
        },
        headers=WRITE,
    )
    entry = _log(client)[0]
    assert entry["summary"] == (
        f"Agregaste el gasto «Entradas» de RD$ 4,896 al grupo {GROUP}"  # spanish-ui
    )
    assert entry["link_kind"] == "group" and entry["affected"] == 0
    client.post(
        f"/api/shared/groups/{gid}/payments",
        json={
            "from_contact": people["Javier"],
            "to_contact": me,
            "amount_cents": 326400,
            "day": "2026-01-20",
            "allocations": [
                {"contact_id": people["Javier"], "cents": 163200},
                {"contact_id": people["El Gordo"], "cents": 163200},
            ],
        },
        headers=WRITE,
    )
    assert _log(client)[0]["summary"] == (
        "Registraste un pago de Javier a ti de RD$ 3,264 (cubre a El Gordo) "  # spanish-ui
        f"en el grupo {GROUP}"
    )
    client.patch(f"/api/shared/contacts/{people['Javier']}", json={"name": "Javi"}, headers=WRITE)
    renamed = _log(client)[0]
    assert renamed["summary"] == "Renombraste a Javier como Javi"  # spanish-ui
    assert (renamed["link_kind"], renamed["link_id"]) == ("contact", people["Javier"])


def test_two_people_removed_at_once_read_as_one_sentence() -> None:
    names = changelog_ledger.Names({1: "me", 2: "Javier", 3: "El Gordo"}, {7: GROUP}, me=1)
    changes = [
        Change(
            "ledger_members",
            {"group_id": 7, "contact_id": c},
            {"group_id": 7, "contact_id": c},
            None,
            ("contact_id",),
        )  # fmt: skip
        for c in (2, 3)
    ]
    text = changelog_ledger.sentence("group_member", GROUP, "group-7", changes, names)
    assert text == f"Quitaste a Javier y El Gordo del grupo {GROUP}"  # spanish-ui
    assert changelog_ledger.sentence("category", "x", "fp", changes, names) is None
    assert changelog_ledger.link_of("group-7", changes) == ("group", 7)
