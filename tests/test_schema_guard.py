"""Opening a database goes by its stored version: one that is up to date is not migrated again,
one written by a newer Michelito is refused, and a schema change without a new version is caught
here before it ships."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from michelito import db

# What a new database looks like at `VERSION`. When this test fails, the schema or the system
# categories changed: give `db.SCHEMA_VERSION` a new number (an up-to-date database skips the
# migrations, so without it the change never reaches the databases that already exist), then
# record the new pair here. (A step that only changes rows does not show here: it needs its new
# version all the same.)
VERSION = 31
FINGERPRINT = "3e814ccde4f06ded41322e6c3e3e0083bf460f2bd30aa9db344723b4fc4ad6d9"


def _fingerprint(conn: sqlite3.Connection) -> str:
    objects = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name"
    ).fetchall()
    builtins = conn.execute(
        "SELECT builtin_key, kind FROM categories WHERE builtin = 1 ORDER BY builtin_key"
    ).fetchall()
    text = repr([tuple(row) for row in (*objects, *builtins)])
    return hashlib.sha256(text.encode()).hexdigest()


def _stamp(path: Path, version: int) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"PRAGMA user_version = {version}")


def _version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def test_a_schema_change_comes_with_a_new_version() -> None:
    with closing(db.connect(":memory:")) as conn:
        assert (db.SCHEMA_VERSION, _fingerprint(conn)) == (VERSION, FINGERPRINT)


def test_a_database_from_a_newer_version_is_refused_and_left_as_it_was(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "newer.db"
    db.connect(path).close()
    _stamp(path, db.SCHEMA_VERSION + 1)

    # Act
    with pytest.raises(db.NewerSchemaError) as raised:
        db.connect(path)

    # Assert
    assert str(db.SCHEMA_VERSION + 1) in str(raised.value)
    assert _version(path) == db.SCHEMA_VERSION + 1


def test_an_up_to_date_database_is_not_migrated_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    path = tmp_path / "current.db"
    db.connect(path).close()

    def fail(conn: sqlite3.Connection) -> None:
        raise AssertionError("the migrations ran on an up-to-date database")

    monkeypatch.setattr(db, "_migrate", fail)

    # Act
    with closing(db.connect(path)) as conn:
        # Assert: it is still the connection the rest of the code expects
        assert isinstance(conn.execute("SELECT 1 AS one").fetchone(), sqlite3.Row)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_an_up_to_date_database_opens_while_another_connection_writes(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "busy.db"
    db.connect(path).close()
    with closing(sqlite3.connect(path, isolation_level=None)) as writer:
        writer.execute("BEGIN IMMEDIATE")

        # Act: opening needs no write lock (it used to wait for the writer and then fail)
        with closing(sqlite3.connect(path, timeout=0)) as reader:
            db.upgrade(reader)

            # Assert
            assert reader.execute("SELECT COUNT(*) FROM categories").fetchone()[0] > 0
        writer.execute("ROLLBACK")


def test_an_older_database_is_still_migrated(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "older.db"
    db.connect(path).close()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("DROP TABLE tags")
    _stamp(path, db.SCHEMA_VERSION - 1)

    # Act
    with closing(db.connect(path)) as conn:
        # Assert
        assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 0
    assert _version(path) == db.SCHEMA_VERSION
