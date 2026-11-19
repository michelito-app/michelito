""" "Copy for Claude": `GET /api/dossier`, the fixed prompt and pasting the answer back.

Local mode on the e2e test database; the demo on copies from the generator (made-up data).
"""

from contextlib import closing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from michelito import db, dossier
from michelito.analysis import claude_prompt, corrections, insights
from michelito.demo import feedback_store
from michelito.web.app import create_app
from tests.demo_helpers import WRITE, _restore_providers, client, visitor  # noqa: F401
from tests.e2e_server import build_demo_db

FEBRUARY = "2026-02"
CARD = "demo:credit_card"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "local.db"
    build_demo_db(path)
    return path


@pytest.fixture
def local(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path), "http://127.0.0.1")


def _built(db_path: Path, month: str = FEBRUARY, accounts=None) -> dossier.Dossier:
    with closing(db.connect(db_path)) as conn:
        return dossier.build(conn, month, accounts=accounts)


def test_the_dossier_is_the_same_markdown_as_the_cli(local: TestClient, db_path: Path) -> None:
    found = local.get("/api/dossier", params={"month": FEBRUARY})
    assert found.status_code == 200
    assert found.headers["content-type"].startswith("text/markdown")
    assert found.headers["cache-control"] == "no-store"
    built = _built(db_path)
    assert found.text == built.markdown
    assert found.headers["x-michelito-fingerprint"] == built.data_hash
    # The dossier's safeguards arrive intact.
    assert dossier.DATA_NOTICE in found.text and "```text" in found.text


def test_accounts_filter_the_dossier(local: TestClient, db_path: Path) -> None:
    found = local.get("/api/dossier", params={"month": FEBRUARY, "accounts": f" {CARD},{CARD} "})
    assert found.status_code == 200
    assert found.text == _built(db_path, accounts=[CARD]).markdown
    assert found.text.startswith(dossier.header(FEBRUARY, [CARD]))
    assert local.get("/api/dossier", params={"month": FEBRUARY, "accounts": ""}).text == (
        _built(db_path).markdown
    )


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({}, 422),
        ({"month": "2026-13"}, 422),
        ({"month": "february"}, 422),
        ({"month": FEBRUARY, "accounts": "missing:account"}, 422),
        ({"month": FEBRUARY, "accounts": "x" * 2001}, 422),
        ({"month": FEBRUARY, "accounts": f"{CARD},{'x' * 101}"}, 422),
        ({"month": "2001-01"}, 404),
    ],
)
def test_invalid_requests(local: TestClient, params: dict, status: int) -> None:
    assert local.get("/api/dossier", params=params).status_code == status


def test_unknown_account_names_it(local: TestClient) -> None:
    found = local.get("/api/dossier", params={"month": FEBRUARY, "accounts": "missing:account"})
    assert "missing:account" in found.json()["detail"]


def test_the_dossier_only_reads(local: TestClient, db_path: Path) -> None:
    before = _built(db_path).data_hash
    local.get("/api/dossier", params={"month": FEBRUARY})
    assert _built(db_path).data_hash == before
    assert local.get("/api/log").json()["items"] == []


def test_the_instruction_is_the_single_source(local: TestClient) -> None:
    found = local.get("/api/dossier/prompt").json()
    assert found == {"text": claude_prompt.INSTRUCTION}
    text = found["text"]
    assert "```text" in text and "no instrucciones" in text  # spanish-ui
    assert f"menos de {claude_prompt.MAX_WORDS} palabras" in text  # spanish-ui
    assert "Tres ideas" in text  # spanish-ui


def test_pasting_back_saves_a_fresh_analysis_with_the_copied_accounts(local: TestClient) -> None:
    pasted = f"{dossier.header(FEBRUARY, [CARD])}\n## February\n\nI spent more on travel."
    body = {"text": pasted, "fresh": True, "accounts": [CARD]}
    saved = local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE)
    assert saved.status_code == 200, saved.text
    out = saved.json()
    assert out["text"] == "## February\n\nI spent more on travel."  # without the header
    assert (out["accounts"], out["stale"]) == ([CARD], False)
    # Pasting again replaces the text and the accounts (all of them).
    again = {"text": "Another analysis.", "fresh": True}
    replaced = local.put(f"/api/insights/{FEBRUARY}", json=again, headers=WRITE).json()
    assert (replaced["text"], replaced["accounts"], replaced["stale"]) == (
        "Another analysis.",
        None,
        False,
    )


@pytest.mark.parametrize(
    "body",
    [
        {"text": dossier.header("2026-01", None) + "\nJanuary.", "fresh": True},
        {"text": "   ", "fresh": True},
        {"text": "x", "fresh": True, "accounts": ["missing:account"]},
        {"text": "x", "fresh": True, "accounts": ["missing:account"], "fingerprint": "0" * 16},
        # The header says one account and the body says all (or the other way round): no guessing.
        {"text": dossier.header(FEBRUARY, [CARD]) + "\nX.", "fresh": True, "accounts": None},
        {"text": dossier.header(FEBRUARY, None) + "\nX.", "fresh": True, "accounts": [CARD]},
        {"text": "x", "fresh": True, "fingerprint": "not-a-fingerprint"},
        {"text": "x", "fresh": True, "fingerprint": "A" * 16},
        {"text": "x", "fresh": True, "accounts": ["x" * 101]},
        {"text": "x", "fresh": True, "accounts": [""]},
    ],
)
def test_pasting_back_rejects_bad_answers(local: TestClient, body: dict) -> None:
    assert local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE).status_code == 422
    assert local.get(f"/api/insights/{FEBRUARY}").status_code == 404


def test_without_accounts_the_header_decides(local: TestClient) -> None:
    pasted = f"{dossier.header(FEBRUARY, [CARD])}\nJust the card."
    body = {"text": pasted, "fresh": True}
    saved = local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE).json()
    assert (saved["text"], saved["accounts"], saved["stale"]) == ("Just the card.", [CARD], False)


def test_the_copied_hash_is_kept_so_later_changes_show(local: TestClient, db_path: Path) -> None:
    copied = local.get("/api/dossier", params={"month": FEBRUARY, "accounts": CARD})
    copied_hash = copied.headers["x-michelito-fingerprint"]
    # The data changes while the visitor is in Claude.
    with closing(db.connect(db_path)) as conn:
        rows = dossier.build(conn, FEBRUARY).data["transactions"]
        agency = next(m for m in rows if m["merchant"] == "AGENCIA FICTICIA")
        with conn:
            corrections.set_one_off(conn, agency["fingerprint"], True)
    body = {"text": "February.", "fresh": True, "accounts": [CARD], "fingerprint": copied_hash}
    saved = local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE).json()
    assert saved["stale"] is True  # the analysis belongs to the earlier dossier
    with closing(db.connect(db_path)) as conn:
        assert insights.get(conn, FEBRUARY).data_hash == copied_hash  # type: ignore[union-attr]
    # With today's fingerprint, up to date.
    fresh = local.get("/api/dossier", params={"month": FEBRUARY, "accounts": CARD})
    body["fingerprint"] = fresh.headers["x-michelito-fingerprint"]
    assert local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE).json()["stale"] is False


def test_without_fresh_the_put_is_unchanged(local: TestClient, db_path: Path) -> None:
    made = {"text": "Created.", "accounts": [CARD], "fingerprint": "0" * 16}
    created = local.put(f"/api/insights/{FEBRUARY}", json=made, headers=WRITE).json()
    assert (created["accounts"], created["stale"]) == (
        None,
        False,
    )  # all accounts, today's fingerprint
    edit = {"text": "Edited.", "accounts": [CARD], "fingerprint": "0" * 16}
    edited = local.put(f"/api/insights/{FEBRUARY}", json=edit, headers=WRITE).json()
    assert (edited["text"], edited["accounts"], edited["stale"]) == ("Edited.", None, False)
    with closing(db.connect(db_path)) as conn:
        assert insights.get(conn, FEBRUARY).data_hash == _built(db_path).data_hash  # type: ignore[union-attr]


# --- demo ---


def _demo_month(api: TestClient) -> str:
    return api.get("/api/months").json()[1]["month"]


def test_demo_dossier_is_the_visitor_copy(tmp_path: Path) -> None:
    one = client(tmp_path)
    assert one.get("/api/dossier", params={"month": "2026-10"}).status_code == 401  # no session
    one.post("/api/demo/session", headers=WRITE)
    two = visitor(one)
    month = _demo_month(one)
    before = one.get("/api/dossier", params={"month": month}).text
    assert two.get("/api/dossier", params={"month": month}).text == before
    category = next(c for c in one.get("/api/categories").json() if c["name"] in before)
    renamed = one.patch(
        f"/api/categories/{category['id']}", json={"name": "Renamed Only Mine"}, headers=WRITE
    )
    assert renamed.status_code == 200, renamed.text
    assert "Renamed Only Mine" in one.get("/api/dossier", params={"month": month}).text
    assert two.get("/api/dossier", params={"month": month}).text == before


def test_demo_pasting_back_only_writes_the_visitor_copy(tmp_path: Path) -> None:
    one = client(tmp_path)
    one.post("/api/demo/session", headers=WRITE)
    two = visitor(one)
    month = _demo_month(one)
    copied = one.get("/api/dossier", params={"month": month})
    body = {
        "text": "My analysis.",
        "fresh": True,
        "fingerprint": copied.headers["x-michelito-fingerprint"],
    }
    saved = one.put(f"/api/insights/{month}", json=body, headers=WRITE)
    assert saved.status_code == 200, saved.text
    assert saved.json()["stale"] is False
    assert two.get(f"/api/insights/{month}").status_code == 404
    template = tmp_path / "demo" / "template" / "michelito.db"
    with closing(db.connect(template)) as conn:
        assert insights.list_all(conn) == []
    # Claude does not write in the demo, not through here either.
    claude = {**WRITE, "X-Michelito-Author": "claude"}
    assert one.put(f"/api/insights/{month}", json=body, headers=claude).status_code == 403


def test_demo_dossier_is_an_expensive_route(tmp_path: Path) -> None:
    api = client(tmp_path, per_minute=10)
    api.post("/api/demo/session", headers=WRITE)
    month = "2026-10"
    assert api.get("/api/dossier", params={"month": month}).status_code == 200  # costs 4
    assert api.get("/api/dossier", params={"month": month}).status_code == 200  # 8
    assert api.get("/api/dossier", params={"month": month}).status_code == 429
    assert api.get("/api/dossier/prompt").status_code == 200  # 1: still fits


def test_demo_counts_copy_for_claude(tmp_path: Path) -> None:
    api = client(tmp_path)
    event = {"event": "copy_for_claude"}
    assert api.post("/api/demo/event", json=event, headers=WRITE).status_code == 401
    api.post("/api/demo/session", headers=WRITE)
    assert api.post("/api/demo/event", json=event, headers=WRITE).status_code == 204
    assert api.post("/api/demo/event", json=event, headers=WRITE).status_code == 204
    unknown = api.post("/api/demo/event", json={"event": "other"}, headers=WRITE)
    assert unknown.status_code == 422
    app = api.app
    assert isinstance(app, FastAPI)
    app.state.maintenance.flush()
    usage = feedback_store.Feedback(tmp_path / "demo" / feedback_store.FILENAME).usage()
    counts = {u["key"]: u["count"] for u in usage if u["kind"] == "event"}
    assert counts == {"copy_for_claude": 2}


def test_demo_ui_events_have_their_own_cap(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/session", headers=WRITE)
    event = {"event": "copy_for_claude"}
    codes = {api.post("/api/demo/event", json=event, headers=WRITE).status_code for _ in range(55)}
    assert codes == {204}  # past the cap it is silently ignored
    assert api.post("/api/usage", json={"screen": ""}, headers=WRITE).status_code == 204
    app = api.app
    assert isinstance(app, FastAPI)
    app.state.maintenance.flush()
    usage = feedback_store.Feedback(tmp_path / "demo" / feedback_store.FILENAME).usage()
    counts = {(u["kind"], u["key"]): u["count"] for u in usage}
    assert counts[("event", "copy_for_claude")] == 50
    assert counts[("visit", "summary")] == 1  # visits have their own cap


def test_local_mode_has_no_demo_event_route(local: TestClient) -> None:
    event = {"event": "copy_for_claude"}
    assert local.post("/api/demo/event", json=event, headers=WRITE).status_code == 404
