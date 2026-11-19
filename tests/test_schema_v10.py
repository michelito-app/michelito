"""Schema 10: what was reviewed in "To review" (by fingerprint and kind); migration from 9."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import review_marks


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _v9(path: Path) -> None:
    """A database as schema 9 left it."""
    with closing(db.connect(path)) as conn:
        conn.executescript("DROP TABLE review_marks; PRAGMA user_version = 9;")


def test_v9_database_gains_review_marks(tmp_path: Path) -> None:
    path = tmp_path / "v9.db"
    _v9(path)
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 10
        assert "review_marks" in _tables(conn)
        with conn:
            review_marks.set_reviewed(conn, "fingerprint-1", "duplicate", True)
    with closing(db.connect(path)) as again:  # idempotent
        assert review_marks.load(again) == frozenset({("fingerprint-1", "duplicate")})


def test_a_failed_migration_leaves_the_v9_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v9.db"
    _v9(path)
    monkeypatch.setattr(db, "REVIEW_SCHEMA", (*db.REVIEW_SCHEMA, "CREATE TABLE broken ("))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 9
        assert "review_marks" not in _tables(raw)


class TestMarks:
    @pytest.fixture
    def conn(self):
        connection = db.connect(":memory:")
        yield connection
        connection.close()

    def test_mark_and_unmark_per_kind(self, conn) -> None:
        with conn:
            review_marks.set_reviewed(conn, "h", "duplicate", True)
            review_marks.set_reviewed(conn, "h", "duplicate", True)  # repeating does not fail
            review_marks.set_reviewed(conn, "h", "price_up", True)
        assert review_marks.load(conn) == frozenset({("h", "duplicate"), ("h", "price_up")})
        with conn:
            review_marks.set_reviewed(conn, "h", "price_up", False)
        assert review_marks.load(conn) == frozenset({("h", "duplicate")})

    def test_unknown_kind_is_rejected(self, conn) -> None:
        with pytest.raises(ValueError, match="unknown review kind"):
            review_marks.set_reviewed(conn, "h", "other", True)

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO review_marks (fingerprint, kind, reviewed_at) VALUES ('h', 'x', 'z')"
            )
