"""The encrypted SQLite engine (`michelito.encrypted`): a file that only opens with its key, no
plaintext anywhere on disk (database, journal or temp files), and the same `sqlite3` behaviour
for the rest of the code, schema migrations included. Synthetic data and throwaway keys only."""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from michelito import db, encrypted, migrations_live, migrations_v19
from michelito.parsers import bhd_savings
from tests import samples
from tests.helpers import store

FIXTURES = Path(__file__).parent / "fixtures"
STATEMENT = bhd_savings.parse(samples.BHD_AHORRO_PORTAL_PAGES)
MARKER = "ZEBRA-SYNTHETIC-MARKER-7731"


def _key() -> bytes:
    return secrets.token_bytes(encrypted.KEY_BYTES)


def _files_contain(folder: Path, needle: bytes) -> list[Path]:
    return [p for p in folder.rglob("*") if p.is_file() and needle in p.read_bytes()]


def test_a_new_encrypted_database_has_the_schema_and_no_plain_header(tmp_path: Path) -> None:
    key = _key()
    path = tmp_path / "michelito.db"
    with closing(db.connect(path, key)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA temp_store").fetchone()[0] == 2  # MEMORY
    assert not encrypted.is_plain(path)
    assert path.stat().st_mode & 0o777 == 0o600


def test_without_the_key_or_with_another_one_the_file_does_not_open(tmp_path: Path) -> None:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path, _key())) as conn, conn:
        conn.execute("CREATE TABLE note (text TEXT)")
        conn.execute("INSERT INTO note VALUES (?)", (MARKER,))
    with pytest.raises(sqlite3.DatabaseError), closing(sqlite3.connect(path)) as plain:
        plain.execute("SELECT count(*) FROM sqlite_master").fetchone()
    with pytest.raises(sqlite3.DatabaseError):
        db.connect(path, _key())  # another account's key
    with pytest.raises(sqlite3.DatabaseError):
        encrypted.connect(path, _key())


def test_a_key_must_be_256_bits(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        encrypted.connect(tmp_path / "x.db", b"short")


def test_no_plaintext_in_any_file_during_and_after_a_transaction(tmp_path: Path) -> None:
    key = _key()
    folder = tmp_path / "account"
    folder.mkdir()
    path = folder / "michelito.db"
    needle = MARKER.encode()
    with closing(db.connect(path, key)) as conn:
        store(conn, STATEMENT)
        with conn:
            conn.execute("UPDATE transactions SET description = ?", (MARKER,))
        assert _files_contain(folder, needle) == []
        # A second transaction: the rollback journal now holds the pages with the marker.
        conn.execute("PRAGMA cache_size = 1")  # and the cache spills changed pages to the file
        conn.execute("BEGIN")
        conn.execute("UPDATE transactions SET description = description || ' 2'")
        conn.execute("CREATE TEMP TABLE scratch AS SELECT description FROM transactions")
        journal = folder / "michelito.db-journal"
        assert journal.is_file() and journal.stat().st_size > 0
        assert _files_contain(folder, needle) == []
        conn.rollback()
    with closing(db.connect(path, key)) as conn:
        found = conn.execute("SELECT count(*) FROM transactions WHERE description = ?", (MARKER,))
        assert found.fetchone()[0] > 0
    assert _files_contain(folder, needle) == []
    assert _files_contain(folder, b"SQLite format 3") == []


def test_the_plaintext_check_sees_a_plain_file_and_journal(tmp_path: Path) -> None:
    """Control for the test above: the same steps on a plain database leak the marker."""
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        store(conn, STATEMENT)
        with conn:
            conn.execute("UPDATE transactions SET description = ?", (MARKER,))
        conn.execute("PRAGMA cache_size = 1")
        conn.execute("BEGIN")
        conn.execute("UPDATE transactions SET description = description || ' 2'")
        leaking = {p.name for p in _files_contain(tmp_path, MARKER.encode())}
        conn.rollback()
    assert leaking == {"michelito.db", "michelito.db-journal"}


def test_errors_are_the_standard_sqlite3_ones(tmp_path: Path) -> None:
    with closing(db.connect(tmp_path / "x.db", _key())) as conn:
        conn.execute("CREATE TABLE note (text TEXT NOT NULL CHECK (text <> 'bad'))")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO note VALUES (NULL)")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("SELECT * FROM no_such_table")
        with pytest.raises(sqlite3.IntegrityError), conn:
            conn.execute("INSERT INTO note VALUES ('bad')")
        row = conn.execute("SELECT 1 AS one").fetchone()
        assert row["one"] == 1 and dict(row) == {"one": 1}
        cursor = conn.execute("INSERT INTO note VALUES ('fine')")
        assert cursor.lastrowid and cursor.rowcount == 1
        assert [r[0] for r in conn.execute("SELECT 1 UNION SELECT 2")] == [1, 2]
        assert "x'" not in repr(conn)


@pytest.mark.parametrize(
    ("fixture", "version"),
    [
        ("schema_v17.sql", 17),  # through v18 (English), v19 (Shared ledger) and v20 (live sync)
        ("schema_v18_shared.sql", 18),  # v19's own fixture: shared expenses to migrate
    ],
)
def test_schema_migrations_run_unchanged_on_an_encrypted_database(
    tmp_path: Path, fixture: str, version: int
) -> None:
    """An old fixture, loaded into a plain and an encrypted file, migrates to the same result
    through `db.connect` (every later migration takes the same path)."""
    assert db.SCHEMA_VERSION >= migrations_v19.VERSION
    script = (FIXTURES / fixture).read_text(encoding="utf-8")
    key = _key()
    plain_path, sealed_path = tmp_path / "plain.db", tmp_path / "sealed.db"
    with closing(sqlite3.connect(plain_path)) as conn:
        conn.executescript(script)
    with closing(encrypted.connect(sealed_path, key)) as conn:
        conn.executescript(script)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version

    today = datetime.now(UTC).date().isoformat()

    def same(value: object) -> object:
        # A migration may stamp rows with the current time: the two runs differ by microseconds.
        return "<now>" if isinstance(value, str) and value.startswith(f"{today}T") else value

    def dump(conn: sqlite3.Connection) -> list[tuple]:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        rows: list[tuple] = [("version", conn.execute("PRAGMA user_version").fetchone()[0])]
        for table in sorted(tables):
            rows += [(table, *map(same, r)) for r in conn.execute(f"SELECT * FROM {table}")]
        return sorted(rows, key=repr)

    def schema(conn: sqlite3.Connection) -> list[tuple]:
        rows = conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
        return sorted((tuple(r) for r in rows), key=repr)

    with closing(db.connect(plain_path)) as plain, closing(db.connect(sealed_path, key)) as sealed:
        assert sealed.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert dump(sealed) == dump(plain)
        assert schema(sealed) == schema(plain)
        assert set(_LIVE_TABLES) <= {r[1] for r in schema(sealed)}  # schema 20 (live sync)
    assert not encrypted.is_plain(sealed_path)


_LIVE_TABLES = ("alerts", "provisional_decisions")


def test_the_live_sync_step_runs_on_an_encrypted_schema_19_database(tmp_path: Path) -> None:
    """A database at schema 19 (before live sync) gets the v20 step when opened encrypted."""
    assert db.SCHEMA_VERSION >= migrations_live.VERSION == 20
    key = _key()
    path = tmp_path / "sealed.db"
    with closing(encrypted.connect(path, key)) as conn:
        conn.executescript((FIXTURES / "schema_v18_shared.sql").read_text(encoding="utf-8"))
    with closing(db.connect(path, key)) as conn:  # to the current schema, then back to 19
        with conn:
            for table in _LIVE_TABLES:
                conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version = 19")
    with closing(db.connect(path, key)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(_LIVE_TABLES) <= names
    assert not encrypted.is_plain(path)


def test_an_encrypted_copy_keeps_rows_and_version(tmp_path: Path) -> None:
    plain_path, sealed_path = tmp_path / "plain.db", tmp_path / "sealed.db"
    with closing(db.connect(plain_path)) as conn:
        store(conn, STATEMENT)
        count = conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
    key = _key()
    encrypted.encrypt_copy(plain_path, sealed_path, key)
    assert not encrypted.is_plain(sealed_path)
    with closing(db.connect(sealed_path, key)) as conn:
        assert conn.execute("SELECT count(*) FROM transactions").fetchone()[0] == count
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    with pytest.raises(FileExistsError):
        encrypted.encrypt_copy(plain_path, sealed_path, key)
