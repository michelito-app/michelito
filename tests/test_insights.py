"""Saved analyses (insights): schema 11 and storage, with made-up texts."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import insights
from michelito.i18n import t

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
            insights.save(conn, "2026-02", "A quiet February.", "abc", None, NOW)
    with closing(db.connect(path)) as again:  # idempotent
        assert insights.get(again, "2026-02").text == "A quiet February."


def test_a_failed_migration_leaves_the_v10_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v10.db"
    with closing(db.connect(path)) as conn:
        conn.executescript("DROP TABLE insights; PRAGMA user_version = 10;")
    monkeypatch.setattr(db, "INSIGHT_SCHEMA", (*db.INSIGHT_SCHEMA, "CREATE TABLE broken ("))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 10


def test_save_get_list_and_delete(conn) -> None:
    with conn:
        insights.save(conn, "2026-01", "  January: spent more on travel.  ", "h1", None, NOW)
        insights.save(conn, "2026-02", "February.", "h2", ("b", "a"), NOW)
    found = insights.get(conn, "2026-01")
    assert found is not None
    assert (found.month, found.text, found.data_hash, found.accounts) == (
        "2026-01",
        "January: spent more on travel.",
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
        insights.save(conn, "2026-01", "First.", "h1", None, NOW)
        insights.save(conn, "2026-01", "Second.", "h2", None, LATER)
    found = insights.get(conn, "2026-01")
    assert (found.text, found.data_hash, found.created_at, found.updated_at) == (
        "Second.",
        "h2",
        NOW,
        LATER,
    )


def test_edit_text_keeps_the_hash(conn) -> None:
    with conn:
        insights.save(conn, "2026-01", "First.", "h1", ("a",), NOW)
        insights.edit_text(conn, "2026-01", "Corrected.", LATER)
    found = insights.get(conn, "2026-01")
    assert (found.text, found.data_hash, found.accounts) == ("Corrected.", "h1", ("a",))
    with pytest.raises(LookupError):
        insights.edit_text(conn, "2030-01", "x", LATER)


@pytest.mark.parametrize(
    ("month", "text", "message"),
    [
        ("2026-13", "x", t("analysis.insights.invalid_month", month="2026-13")),
        ("2026-01", "   ", t("analysis.insights.empty")),
        ("2026-01", "a" * 4001, t("analysis.insights.too_long", max=4000, length=4001)),
    ],
)
def test_validation(conn, month, text, message) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        insights.save(conn, month, text, "h", None, NOW)


def test_the_limit_is_4000_characters(conn) -> None:
    with conn:
        insights.save(conn, "2026-01", "ä" * 4000, "h", None, NOW)
    assert len(insights.get(conn, "2026-01").text) == 4000
