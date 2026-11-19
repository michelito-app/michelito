"""Análisis guardados (insights): esquema 11 y almacenamiento, con textos inventados."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from finanzas import db
from finanzas.analysis import insights

NOW = "2026-03-02T10:00:00+00:00"
LATER = "2026-03-05T09:30:00+00:00"


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def test_v10_database_gains_insights(tmp_path: Path) -> None:
    path = tmp_path / "v10.db"
    with closing(db.connect(path)) as conn:
        conn.executescript("DROP TABLE insights; PRAGMA user_version = 10;")
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 11
        with conn:
            insights.save(conn, "2026-02", "Febrero tranquilo.", "abc", None, NOW)
    with closing(db.connect(path)) as again:  # idempotente
        assert insights.get(again, "2026-02").text == "Febrero tranquilo."


def test_a_failed_migration_leaves_the_v10_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v10.db"
    with closing(db.connect(path)) as conn:
        conn.executescript("DROP TABLE insights; PRAGMA user_version = 10;")
    monkeypatch.setattr(db, "INSIGHT_SCHEMA", (*db.INSIGHT_SCHEMA, "CREATE TABLE roto ("))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 10


def test_save_get_list_and_delete(conn) -> None:
    with conn:
        insights.save(conn, "2026-01", "  Enero: gasté más en viajes.  ", "h1", None, NOW)
        insights.save(conn, "2026-02", "Febrero.", "h2", ("b", "a"), NOW)
    found = insights.get(conn, "2026-01")
    assert found is not None
    assert (found.month, found.text, found.data_hash, found.accounts) == (
        "2026-01",
        "Enero: gasté más en viajes.",
        "h1",
        None,
    )
    assert found.created_at == found.updated_at == NOW
    assert insights.get(conn, "2026-02").accounts == ("a", "b")
    assert [i.month for i in insights.list_all(conn)] == ["2026-02", "2026-01"]
    with conn:
        assert insights.delete(conn, "2026-01") is True
        assert insights.delete(conn, "2026-01") is False
    assert insights.get(conn, "2026-01") is None


def test_saving_again_replaces_text_and_keeps_created_at(conn) -> None:
    with conn:
        insights.save(conn, "2026-01", "Primero.", "h1", None, NOW)
        insights.save(conn, "2026-01", "Segundo.", "h2", None, LATER)
    found = insights.get(conn, "2026-01")
    assert (found.text, found.data_hash, found.created_at, found.updated_at) == (
        "Segundo.",
        "h2",
        NOW,
        LATER,
    )


def test_edit_text_keeps_the_hash(conn) -> None:
    with conn:
        insights.save(conn, "2026-01", "Primero.", "h1", ("a",), NOW)
        insights.edit_text(conn, "2026-01", "Corregido.", LATER)
    found = insights.get(conn, "2026-01")
    assert (found.text, found.data_hash, found.accounts) == ("Corregido.", "h1", ("a",))
    with pytest.raises(LookupError):
        insights.edit_text(conn, "2030-01", "x", LATER)


@pytest.mark.parametrize(
    ("month", "text", "message"),
    [
        ("2026-13", "x", "mes"),
        ("2026-01", "   ", "vacío"),
        ("2026-01", "a" * 4001, "4000"),
    ],
)
def test_validation(conn, month, text, message) -> None:
    with pytest.raises(ValueError, match=message):
        insights.save(conn, month, text, "h", None, NOW)


def test_the_limit_is_4000_characters(conn) -> None:
    with conn:
        insights.save(conn, "2026-01", "á" * 4000, "h", None, NOW)
    assert len(insights.get(conn, "2026-01").text) == 4000
