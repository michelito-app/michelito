"""Feedback and usage counters: nothing that identifies the visitor."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from michelito import cli, legacy
from michelito.demo import feedback_store
from michelito.demo.app import PLAIN_COOKIE as COOKIE
from tests.demo_helpers import WRITE, _restore_providers, client  # noqa: F401


def _dump(path: Path) -> str:
    with closing(sqlite3.connect(path)) as conn:
        return "\n".join(conn.iterdump())


def test_opinion_with_context_and_no_personal_trace(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/session", headers=WRITE)
    body = {
        "text": "I liked the budget",
        "email": "person@example.com",
        "page": "/budget?month=2026-10",
        "width": 390,
        "version": "0.1.0",
        "ref": "forum-1",
    }
    assert api.post("/api/feedback", json=body, headers=WRITE).status_code == 201
    api.post("/api/usage", json={"screen": "budget"}, headers=WRITE)
    api.post("/api/usage", json={"screen": "/transactions/abc123"}, headers=WRITE)
    api.post("/api/usage", json={"screen": "/no-such-screen"}, headers=WRITE)
    api.app.state.maintenance.flush()  # the counts are flushed in batches
    feedback = feedback_store.Feedback(tmp_path / "demo" / feedback_store.FILENAME)
    [stored] = feedback.opinions()
    assert (stored.page, stored.width, stored.ref) == ("/budget", 390, "forum-1")
    usage = {(u["kind"], u["key"]): u["count"] for u in feedback.usage()}
    assert usage[("visit", "budget")] == 1
    assert usage[("visit", "transactions")] == 1
    assert usage[("visit", "other")] == 1
    assert usage[("copy", "created")] == 1
    dump = _dump(tmp_path / "demo" / feedback_store.FILENAME)
    assert api.cookies[COOKIE] not in dump
    assert "testclient" not in dump and "127.0.0.1" not in dump


@pytest.mark.parametrize(
    "body",
    [
        {"text": ""},
        {"text": "x" * 2001},
        {"text": "hello", "email": "not-an-email"},
        {"text": "hello", "ref": "<script>"},
    ],
)
def test_invalid_opinions_are_rejected(tmp_path: Path, body: dict) -> None:
    api = client(tmp_path)
    api.post("/api/demo/session", headers=WRITE)
    assert api.post("/api/feedback", json=body, headers=WRITE).status_code == 422


def test_opinions_need_a_session_and_are_capped(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert api.post("/api/feedback", json={"text": "x"}, headers=WRITE).status_code == 401
    api.post("/api/demo/session", headers=WRITE)
    codes = [
        api.post("/api/feedback", json={"text": f"n{i}"}, headers=WRITE).status_code
        for i in range(11)
    ]
    assert codes[:10] == [201] * 10 and codes[10] == 429


def test_key_events_are_counted(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/session", headers=WRITE)
    assert api.post("/api/budget/activate", json={}, headers=WRITE).status_code == 201
    api.post("/api/demo/sample-statement", headers=WRITE)
    entry = api.get("/api/log").json()["items"][0]["id"]
    assert api.post(f"/api/log/{entry}/undo", headers=WRITE).status_code == 200
    api.app.state.maintenance.flush()
    usage = feedback_store.Feedback(tmp_path / "demo" / feedback_store.FILENAME).usage()
    events = {u["key"] for u in usage if u["kind"] == "event"}
    assert {"budget_activated", "sample_statement", "undo"} <= events


def test_cli_lists_opinions_and_usage(tmp_path: Path, capsys) -> None:
    feedback = feedback_store.Feedback(tmp_path / feedback_store.FILENAME)
    feedback.save(feedback_store.Opinion("A dark mode is missing", page="/", width=1280))
    feedback.count("visit", "summary")
    feedback.flush()
    assert cli.main(["feedback", "--data", str(tmp_path)]) == 0
    assert "A dark mode is missing" in capsys.readouterr().out
    assert cli.main(["feedback", "--json", "--data", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["width"] == 1280
    assert cli.main(["feedback", "--usage", "--data", str(tmp_path)]) == 0
    assert "summary" in capsys.readouterr().out


def test_control_characters_never_reach_the_terminal(tmp_path: Path, capsys) -> None:
    feedback = feedback_store.Feedback(tmp_path / feedback_store.FILENAME)
    feedback.save(feedback_store.Opinion("hello\x1b[2J\nworld ‮dlrow", ref="a‮b"))
    [stored] = feedback.opinions()
    assert stored.text == "hello[2J\nworld dlrow" and stored.ref == "ab"
    # Whatever was already stored with control characters is printed escaped.
    import sqlite3 as _sqlite

    with closing(_sqlite.connect(tmp_path / feedback_store.FILENAME)) as conn, conn:
        conn.execute("UPDATE feedback SET text = ?", ("x\x1b[2Jy‮z\nend",))
    assert cli.main(["feedback", "--data", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "‮" not in out
    assert "x\\u001b[2Jy\\u202ez\nend" in out
    assert cli.main(["feedback", "--json", "--data", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "‮" not in out


def _legacy_store(directory: Path) -> None:
    """A feedback store as the release before the English rename wrote it."""
    directory.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(directory / legacy.FEEDBACK_FILE)) as conn, conn:
        # Old tables, columns and usage values (legacy data).
        # spanish-data: begin
        conn.executescript(
            "CREATE TABLE opiniones (id INTEGER PRIMARY KEY, creada TEXT NOT NULL, "
            "texto TEXT NOT NULL, correo TEXT, pagina TEXT, ancho INTEGER, version TEXT, ref TEXT);"
            "CREATE TABLE uso (dia TEXT NOT NULL, tipo TEXT NOT NULL, clave TEXT NOT NULL, "
            "conteo INTEGER NOT NULL, PRIMARY KEY (dia, tipo, clave));"
        )
        conn.executemany(
            "INSERT INTO opiniones VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (3, "2026-10-01T10:00:00+00:00", "First", None, "/", 390, "0.1.0", None),
                (7, "2026-10-02T11:00:00+00:00", "Second", "a@example.com", "/x", None, None, "r"),
            ],
        )
        conn.executemany(
            "INSERT INTO uso VALUES (?, ?, ?, ?)",
            [
                ("2026-10-01", "visita", "resumen", 5),
                ("2026-10-01", "visita", "otra", 2),
                ("2026-10-01", "copia", "creada", 3),
                ("2026-10-02", "evento", "copiar_claude", 1),
                ("2026-10-02", "evento", "deshacer", 4),
            ],
        )
        # spanish-data: end


def test_the_legacy_store_is_migrated_once_keeping_every_row(tmp_path: Path) -> None:
    _legacy_store(tmp_path)
    before = _dump(tmp_path / legacy.FEEDBACK_FILE)
    feedback = feedback_store.Feedback(tmp_path / feedback_store.FILENAME)
    stored = feedback.opinions()
    assert [
        (o.id, o.created_at, o.text, o.email, o.page, o.width, o.version, o.ref) for o in stored
    ] == [
        (7, "2026-10-02T11:00:00+00:00", "Second", "a@example.com", "/x", None, None, "r"),
        (3, "2026-10-01T10:00:00+00:00", "First", None, "/", 390, "0.1.0", None),
    ]
    assert feedback.usage() == [
        {"day": "2026-10-02", "kind": "event", "key": "copy_for_claude", "count": 1},
        {"day": "2026-10-02", "kind": "event", "key": "undo", "count": 4},
        {"day": "2026-10-01", "kind": "copy", "key": "created", "count": 3},
        {"day": "2026-10-01", "kind": "visit", "key": "other", "count": 2},
        {"day": "2026-10-01", "kind": "visit", "key": "summary", "count": 5},
    ]
    assert _dump(tmp_path / legacy.FEEDBACK_FILE) == before  # the old file is left as it was
    # New rows continue after the migrated ids; opening again does not copy anything twice.
    assert feedback.save(feedback_store.Opinion("Third")) == 8
    again = feedback_store.Feedback(tmp_path / feedback_store.FILENAME)
    assert [o.id for o in again.opinions()] == [8, 7, 3]
    assert len(again.usage()) == 5


def test_a_failed_legacy_migration_leaves_no_store_and_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _legacy_store(tmp_path)
    real = feedback_store._migrate_legacy

    def broken(conn, old) -> None:
        real(conn, old)
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(feedback_store, "_migrate_legacy", broken)
    with pytest.raises(sqlite3.OperationalError):
        feedback_store.Feedback(tmp_path / feedback_store.FILENAME)
    assert sorted(p.name for p in tmp_path.iterdir()) == [legacy.FEEDBACK_FILE]
    monkeypatch.setattr(feedback_store, "_migrate_legacy", real)
    retried = feedback_store.Feedback(tmp_path / feedback_store.FILENAME)
    assert [o.id for o in retried.opinions()] == [7, 3]
    assert len(retried.usage()) == 5


def test_the_cli_reads_a_folder_with_only_the_legacy_store(tmp_path: Path, capsys) -> None:
    _legacy_store(tmp_path)
    assert cli.main(["feedback", "--data", str(tmp_path)]) == 0
    assert "Second" in capsys.readouterr().out
    assert (tmp_path / feedback_store.FILENAME).is_file()
