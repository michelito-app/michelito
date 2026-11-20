"""Schema 17 (budget and reserves): migration from 16 without losing links, reviews or the
change log (which can still be undone); afterwards a reserve with its expense, a cap and a
dismissed suggestion fit, and all of it is logged and undone. Made-up data."""

import sqlite3
from contextlib import closing
from decimal import Decimal as D
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import (
    budget,
    budget_store,
    catalog,
    changelog,
    links,
    reserve_store,
    review_marks,
    spending,
)
from michelito.analysis import categories as cat
from tests.test_spending import seed

_RESERVE_COLUMNS = [name for name, _ in db.RESERVE_COLUMNS["links"]]
# What schema 17 added to each CHECK (to go back to how they were in 16).
_ADDED = {
    "links": ", 'reserve'",
    "link_members": ", 'reserved'",
    "review_marks": ", 'possible_reserve', 'possible_payment'",  # 'possible_payment': schema 19
}


def _downgrade(raw: sqlite3.Connection) -> None:
    """Leave the database as in schema 16: without the new columns and tables and with the old
    CHECKs (rebuilding each table with its rows, like `db._rebuild_check`)."""
    for column in reversed(_RESERVE_COLUMNS):
        raw.execute(f"ALTER TABLE links DROP COLUMN {column}")
    for table, added in _ADDED.items():
        sql = raw.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()[0]
        assert added in sql
        columns = ", ".join(r[1] for r in raw.execute(f"PRAGMA table_info({table})"))
        old = sql.replace(added, "").replace(
            f"CREATE TABLE {table}", f"CREATE TABLE {table}_v16", 1
        )
        old = old.replace(f'CREATE TABLE "{table}"', f"CREATE TABLE {table}_v16", 1)
        seq = raw.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
        raw.execute(old)
        raw.execute(f"INSERT INTO {table}_v16 ({columns}) SELECT {columns} FROM {table}")
        raw.execute(f"DROP TABLE {table}")
        raw.execute(f"ALTER TABLE {table}_v16 RENAME TO {table}")
        if seq is not None:  # as in a real schema 16 database: the sequence does not go down
            raw.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (seq[0], table))
    raw.execute("DROP TABLE budget_caps")
    raw.execute("DROP TABLE reserve_dismissals")
    raw.execute("PRAGMA user_version = 16")
    raw.commit()


def _v16(path: Path) -> dict[str, str]:
    """A schema 16 database: a linked expense (an investment contribution: since schema 19
    shared groups live in the ledger) and a reviewed transaction, made through the change log.
    Returns the fingerprints used."""
    with closing(db.connect(path)) as conn:
        seed(conn)
        flow = [m for m in spending.load_all(conn) if m.kind == "expense" and m.amount > 0]
        shared, reviewed, free = flow[0], flow[1], flow[2]
        with conn, changelog.track(conn, "investment", "transaction", shared.fingerprint, "x"):
            links.create_investment(conn, shared.fingerprint)
        with conn, changelog.track(conn, "reviewed", "transaction", reviewed.fingerprint, "y"):
            review_marks.set_reviewed(conn, reviewed.fingerprint, "duplicate", True)
    with closing(sqlite3.connect(path)) as raw:
        _downgrade(raw)
    return {
        "shared": shared.fingerprint,
        "reviewed": reviewed.fingerprint,
        "free": free.fingerprint,
    }


def _rows(conn: sqlite3.Connection, table: str, columns: str = "*") -> list[tuple]:
    return [tuple(r) for r in conn.execute(f"SELECT {columns} FROM {table} ORDER BY rowid")]


def _sql(conn: sqlite3.Connection, table: str) -> str:
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()[0]


def test_v16_rows_and_log_survive_and_reserves_fit(tmp_path: Path) -> None:
    path = tmp_path / "v16.db"
    fps = _v16(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 16
        assert "'reserve'" not in _sql(raw, "links")
        before = {t: _rows(raw, t) for t in ("links", "link_members", "review_marks", "change_log")}
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 17
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert "'reserve'" in _sql(conn, "links")
        assert "'reserved'" in _sql(conn, "link_members")
        assert "'possible_reserve'" in _sql(conn, "review_marks")
        assert "AUTOINCREMENT" in _sql(conn, "budget_caps")
        assert "AUTOINCREMENT" in _sql(conn, "reserve_dismissals")
        # No row was lost or changed; the new columns stay empty.
        old = [c for c in (r[1] for r in conn.execute("PRAGMA table_info(links)"))]
        kept = ", ".join(c for c in old if c not in _RESERVE_COLUMNS)
        assert _rows(conn, "links", kept) == before["links"]
        assert _rows(conn, "links", "reserve_cents, category_id, multiple") == [(None, None, 0)]
        for table in ("link_members", "review_marks", "change_log"):
            assert _rows(conn, table) == before[table], table
        # The earlier changes can still be undone.
        assert all(changelog.undo_state(conn, e).allowed for e in changelog.load(conn))

        # The new things fit: a reserve with its expense, a cap and a dismissed suggestion.
        tax = catalog.resolve_ref(conn, cat.GOVERNMENT)
        with conn, changelog.track(conn, "reserve", "link", "0", "Vehicle tax") as made:
            reserve = reserve_store.create(
                conn, name="Vehicle tax", amount=D(3500), category_id=tax, due_month="2027-01",
                every_months=12,
            )  # fmt: skip
        with (
            conn,
            changelog.track(conn, "reserve_expense", "transaction", fps["free"], "z") as tied,
        ):
            reserve_store.add_member(conn, reserve, fps["free"])
        with pytest.raises(links.AlreadyLinked):  # one fingerprint, a single link
            reserve_store.add_member(conn, reserve, fps["shared"])
        with conn, changelog.track(conn, "budget", "category", str(tax), "Gov") as capped:
            budget_store.set_cap(conn, tax, D(2000))
        with conn, changelog.track(conn, "reserve_dismissal", "link", "k", "k") as dropped:
            reserve_store.dismiss(conn, "peak:x:12")
        assert links.load(conn).reserve_for(fps["free"]) == reserve
        assert budget_store.load(conn) == {tax: budget.Cap(tax, D(2000), True, None)}
        assert reserve_store.dismissed(conn) == {"peak:x:12"}
        # Each one was logged and is undone (also the dry run in a SAVEPOINT).
        for draft in (dropped, capped, tied, made):
            assert draft.entry_id is not None
            entry = changelog.get(conn, draft.entry_id)
            assert changelog.undo_state(conn, entry).allowed
            with conn:
                changelog.undo(conn, draft.entry_id)
        assert reserve_store.load(conn) == [] and budget_store.load(conn) == {}
        assert reserve_store.dismissed(conn) == frozenset()
        assert links.load(conn).reserve_for(fps["free"]) is None
    with closing(db.connect(path)) as again:  # idempotent
        assert again.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_a_failed_v17_migration_leaves_the_v16_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v16.db"
    _v16(path)
    with closing(sqlite3.connect(path)) as raw:
        before = _rows(raw, "links")
    monkeypatch.setattr(db, "BUDGET_SCHEMA", ("CREATE TABLE broken (",))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 16
        assert "'reserve'" not in _sql(raw, "links")
        assert _rows(raw, "links") == before


def test_deleting_a_category_moves_its_reserves_and_drops_its_cap(tmp_path: Path) -> None:
    with closing(db.connect(tmp_path / "x.db")) as conn:
        with conn:
            mine = catalog.create(conn, "Made-up school", "expense")
            other = catalog.create(conn, "Made-up education", "expense")
            reserve = reserve_store.create(
                conn, name="Enrollment", amount=D(9000), category_id=mine.id,
                due_month="2026-08", every_months=None,
            )  # fmt: skip
            budget_store.set_cap(conn, mine.id, D(5000))
        assert catalog.in_use(conn, mine.id)
        with pytest.raises(catalog.Forbidden):
            catalog.delete(conn, mine.id, None)
        with conn:
            catalog.delete(conn, mine.id, other.id)
        assert reserve_store.get(conn, reserve).category_id == other.id
        assert budget_store.load(conn) == {}


def test_rebuilding_links_keeps_the_sequence_of_deleted_ids(tmp_path: Path) -> None:
    """A deleted link leaves the sequence above the highest id: rebuilding `links` does not
    lower it, so the deleted id is not reused and its old "Undo" still stands."""
    path = tmp_path / "v16.db"
    _v16(path)
    with closing(db.connect(path)) as conn:
        flow = [m for m in spending.load_all(conn) if m.kind == "expense" and m.amount > 0]
        gone = flow[3]
        with conn, changelog.track(conn, "investment", "transaction", gone.fingerprint, "w"):
            made = links.create_investment(conn, gone.fingerprint)
        with conn, changelog.track(conn, "investment", "transaction", gone.fingerprint, "w") as d:
            links.remove_investment_member(conn, made, gone.fingerprint)
        deleted = d.entry_id
    with closing(sqlite3.connect(path)) as raw:
        _downgrade(raw)
        seq = raw.execute("SELECT seq FROM sqlite_sequence WHERE name = 'links'").fetchone()[0]
        top = raw.execute("SELECT MAX(id) FROM links").fetchone()[0]
        assert seq > top
    with closing(db.connect(path)) as conn:
        after = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'links'").fetchone()
        assert after[0] == seq
        assert deleted is not None
        assert changelog.undo_state(conn, changelog.get(conn, deleted)).allowed
        with conn:
            new = reserve_store.create(
                conn,
                name="New",
                amount=D(100),
                category_id=catalog.resolve_ref(conn, cat.GOVERNMENT),
                due_month="2027-01",
                every_months=12,
            )
        assert new > seq
