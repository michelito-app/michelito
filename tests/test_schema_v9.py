"""Schema 9: free-text notes per transaction and link tables; migration from 8."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import catalog, corrections, spending
from michelito.analysis import categories as cat
from michelito.web import transactions
from tests.test_spending import seed
from tests.test_web_transactions import ACCOUNTS, movement

V8_NOTES = """
CREATE TABLE transaction_notes_old (
    fingerprint TEXT PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id),
    one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)),
    updated_at TEXT NOT NULL
);
INSERT INTO transaction_notes_old SELECT fingerprint, category_id, one_off, updated_at
    FROM transaction_notes;
DROP TABLE transaction_notes;
ALTER TABLE transaction_notes_old RENAME TO transaction_notes;
DROP TABLE link_manual;
DROP TABLE link_members;
DROP TABLE links;
DELETE FROM categories WHERE builtin_key IN ('REIMBURSEMENT', 'CURRENCY_EXCHANGE');
PRAGMA user_version = 8;
"""


def _v8(path: Path) -> None:
    """A database as schema 8 left it, with one saved correction."""
    with closing(db.connect(path)) as conn:
        with conn:
            corrections.set_one_off(conn, "fingerprint-1", True)
        conn.executescript(V8_NOTES)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_v8_database_is_migrated_and_keeps_its_corrections(tmp_path: Path) -> None:
    path = tmp_path / "v8.db"
    _v8(path)
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert "note" in _columns(conn, "transaction_notes")
        assert {"links", "link_members", "link_manual"} <= {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        known = catalog.load(conn)
        assert known.by_ref(cat.CURRENCY_EXCHANGE).kind == "transfer"
        assert known.by_ref(cat.REIMBURSEMENT).kind == "transfer"
        assert corrections.load(conn).is_one_off("fingerprint-1")
    # Idempotent: opening it again changes nothing and does not fail.
    with closing(db.connect(path)) as again:
        assert again.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert again.execute("SELECT COUNT(*) FROM transaction_notes").fetchone()[0] == 1


def test_a_failed_migration_leaves_the_v8_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v8.db"
    _v8(path)
    monkeypatch.setattr(db, "LINK_SCHEMA", (*db.LINK_SCHEMA, "CREATE TABLE broken ("))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        raw.row_factory = sqlite3.Row
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 8
        assert "note" not in _columns(raw, "transaction_notes")
        tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master")}
        assert "links" not in tables
    monkeypatch.undo()
    with closing(db.connect(path)) as conn:  # with the good code, it migrates
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


class TestNotes:
    @pytest.fixture
    def conn(self):
        connection = db.connect(":memory:")
        seed(connection)
        yield connection
        connection.close()

    def _cafe(self, conn) -> spending.Movement:
        return next(m for m in spending.load_all(conn) if m.description.startswith("CAFE"))

    def test_a_note_is_saved_trimmed_and_cleared_when_empty(self, conn) -> None:
        cafe = self._cafe(conn)
        with conn:
            corrections.set_note(conn, cafe.fingerprint, "  Ana's birthday  ")
        assert self._cafe(conn).note == "Ana's birthday"
        with conn:
            corrections.set_note(conn, cafe.fingerprint, "   ")
        assert self._cafe(conn).note == ""
        assert conn.execute("SELECT COUNT(*) FROM transaction_notes").fetchone()[0] == 0

    def test_a_note_does_not_drop_other_corrections(self, conn) -> None:
        cafe = self._cafe(conn)
        with conn:
            corrections.set_one_off(conn, cafe.fingerprint, True)
            corrections.set_note(conn, cafe.fingerprint, "x")
            corrections.set_note(conn, cafe.fingerprint, None)
        assert self._cafe(conn).one_off

    def test_too_long_note_is_rejected(self, conn) -> None:
        with pytest.raises(ValueError, match="500"):
            corrections.set_note(conn, self._cafe(conn).fingerprint, "a" * 501)
        corrections.set_note(conn, self._cafe(conn).fingerprint, "a" * 500)

    def test_note_survives_reprocessing(self, conn) -> None:
        cafe = self._cafe(conn)
        with conn:
            corrections.set_note(conn, cafe.fingerprint, "with Pedro")
            for table in ("transactions", "statements", "documents", "gmail_messages"):
                conn.execute(f"DELETE FROM {table}")
        seed(conn)  # like parse --retry: new rows, same fingerprints
        assert self._cafe(conn).note == "with Pedro"


def test_search_matches_the_note_text() -> None:
    from dataclasses import replace

    # The search folds accents: "animo" finds the accented name.
    note = "Gift for Ánimo"  # spanish-data
    noted = replace(movement("2026-10-02", merchant="COLMADO"), note=note)
    other = movement("2026-10-03", merchant="OTHER")
    found = transactions.list_transactions(
        [noted, other], ACCOUNTS, {}, transactions.Filters("2026-10", q="animo")
    )
    assert [v.merchant for v in found] == ["COLMADO"]
    assert found[0].note == note
