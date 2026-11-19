"""Esquema 10: lo revisado de «Para revisar» (por huella y tipo); migración desde el 9."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from finanzas import db
from finanzas.analysis import review_marks


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _v9(path: Path) -> None:
    """Una base como la dejaba el esquema 9."""
    with closing(db.connect(path)) as conn:
        conn.executescript("DROP TABLE review_marks; PRAGMA user_version = 9;")


def test_v9_database_gains_review_marks(tmp_path: Path) -> None:
    path = tmp_path / "v9.db"
    _v9(path)
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 10
        assert "review_marks" in _tables(conn)
        with conn:
            review_marks.set_reviewed(conn, "huella-1", "duplicado", True)
    with closing(db.connect(path)) as again:  # idempotente
        assert review_marks.load(again) == frozenset({("huella-1", "duplicado")})


def test_a_failed_migration_leaves_the_v9_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v9.db"
    _v9(path)
    monkeypatch.setattr(db, "REVIEW_SCHEMA", (*db.REVIEW_SCHEMA, "CREATE TABLE roto ("))
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
            review_marks.set_reviewed(conn, "h", "duplicado", True)
            review_marks.set_reviewed(conn, "h", "duplicado", True)  # repetir no falla
            review_marks.set_reviewed(conn, "h", "subio", True)
        assert review_marks.load(conn) == frozenset({("h", "duplicado"), ("h", "subio")})
        with conn:
            review_marks.set_reviewed(conn, "h", "subio", False)
        assert review_marks.load(conn) == frozenset({("h", "duplicado")})

    def test_unknown_kind_is_rejected(self, conn) -> None:
        with pytest.raises(ValueError, match="tipo"):
            review_marks.set_reviewed(conn, "h", "otro", True)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO review_marks (fingerprint, kind, reviewed_at) VALUES ('h', 'x', 'z')"
            )
