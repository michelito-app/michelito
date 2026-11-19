"""Schema 15: the change log (`change_log` and its indexes, `rule_dismissals`,
`reviewed_fingerprints`) and `AUTOINCREMENT` on `categories`, `links` and `link_manual`;
migration from 14 without losing anything (ids, rows or indexes)."""

import re
import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import cash_box_store, changelog, corrections, links, spending
from michelito.analysis import categories as cat
from tests.test_spending import _add_bank_rows, seed

D = Decimal
_NEW = ("change_log", "change_log_rows", "change_log_fingerprints", "rule_dismissals")
_NEW += ("reviewed_fingerprints",)
_REBUILT = ("categories", "links", "link_manual")
_KEPT = (
    "links",
    "link_members",
    "link_manual",
    "cash_entries",
    "transaction_notes",
    "merchant_categories",
    "categories",
    "accounts",
)


def _v14(path: Path) -> None:
    """A schema 14 database with made-up data: one link of each kind (shared with a manual
    reimbursement, exchange, investment with a mixed return and cash box with a stored
    withdrawal and a deposit in another currency), a manual cash entry, a note and a rule."""
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-08", "MB a 0000000066 SOCIO INVENTADO", "debit", "30000000"),
                ("2026-01-28", "TRANSF DE SOCIO INVENTADO", "credit", "900000"),
                ("2026-01-10", "RETIRO CAJERO AUTOMATICO INVENTADO", "debit", "2000000"),
                ("2026-01-25", "DEPOSITO EFECTIVO INVENTADO", "credit", "500000"),
            ],
        )
        fps = {m.description: m.fingerprint for m in spending.load_all(conn)}
        cafe = next(fp for text, fp in fps.items() if text.startswith("CAFE FICTICIO"))
        legs = [next(fp for text, fp in fps.items() if text.startswith("FARMACIA"))]
        legs.append(next(fp for text, fp in fps.items() if text.startswith("TIENDA ONLINE")))
        with conn:
            links.set_shared(conn, cafe, D(300), people=3, with_whom="Ana")
            links.add_manual(
                conn, links.group_of(conn, cafe), D(25), date(2026, 1, 3), "DOP", "Ana"
            )
            links.create_exchange(conn, legs, D("60"))
            made = links.create_investment(conn, fps["MB a 0000000066 SOCIO INVENTADO"])
            links.add_investment_member(
                conn, made, fps["TRANSF DE SOCIO INVENTADO"], "mixed", D(9000), D(5000)
            )
            cash_box_store.store(conn, fps["RETIRO CAJERO AUTOMATICO INVENTADO"])
            cash_box_store.deposit(conn, fps["DEPOSITO EFECTIVO INVENTADO"], "USD", D(80))
            cash_box_store.add_entry(conn, "expense", date(2026, 1, 20), D(500), "DOP", note="tip")
            corrections.set_note(conn, cafe, "with Ana")
            corrections.set_merchant_category(conn, "UBER EATS", cat.RESTAURANTS)
        # An id deleted before migrating: schema 14 would reuse it.
        conn.execute("INSERT INTO links (kind, created_at, updated_at) VALUES ('shared', 'x', 'x')")
        conn.execute("DELETE FROM links WHERE id = (SELECT MAX(id) FROM links)")
        for table in _NEW:
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version = 14")
        conn.commit()
        _without_autoincrement(conn)


def _without_autoincrement(conn: sqlite3.Connection) -> None:
    """Leave `categories`, `links` and `link_manual` as in schema 14 (no `AUTOINCREMENT`),
    with the same rows, ids and indexes."""
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in _REBUILT:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()[0]
        indexes = [
            r[0]
            for r in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
                "AND sql IS NOT NULL",
                (table,),
            )
        ]
        old = re.sub(
            rf'^CREATE TABLE (IF NOT EXISTS )?"?{table}"?',
            f"CREATE TABLE {table}_v14",
            sql.replace(" AUTOINCREMENT", ""),
            count=1,
        )
        conn.execute(old)
        conn.execute(f"INSERT INTO {table}_v14 SELECT * FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_v14 RENAME TO {table}")
        for index in indexes:
            conn.execute(index)
    conn.execute(f"DELETE FROM sqlite_sequence WHERE name IN {_REBUILT}")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def _snapshot(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in _KEPT}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _ddl(conn: sqlite3.Connection) -> dict[str, str]:
    """The SQL of the tables and indexes of `_KEPT` (for the rebuilt ones, without
    `AUTOINCREMENT`)."""
    return {
        r[0]: r[1].replace(" AUTOINCREMENT", "")
        for r in conn.execute("SELECT name, sql, tbl_name FROM sqlite_master WHERE sql NOT NULL")
        if r[2] in _KEPT
    }


def test_v14_data_survives_and_the_log_fits(tmp_path: Path) -> None:
    path = tmp_path / "v14.db"
    _v14(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 14
        assert not set(_NEW) & _tables(raw)
        before, ddl = _snapshot(raw), _ddl(raw)
        kinds = {r[0] for r in raw.execute("SELECT kind FROM links")}
        assert kinds == {"shared", "exchange", "investment", "cash_box"}
        assert raw.execute("SELECT COUNT(*) FROM cash_entries").fetchone()[0] == 1
        assert not any("AUTOINCREMENT" in raw_sql(raw, t) for t in _REBUILT)
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 15
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert set(_NEW) <= _tables(conn)
        assert _snapshot(conn) == before  # no row was lost or changed (nor its id)
        assert _ddl(conn) == ddl  # same columns, CHECKs and indexes
        for table in _REBUILT:
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()[0]
            assert "id INTEGER PRIMARY KEY AUTOINCREMENT" in sql, table
            assert conn.execute(f"PRAGMA foreign_key_check({table})").fetchone() is None
        # A deleted id is no longer reused: the next group comes after the highest one.
        top = conn.execute("SELECT MAX(id) FROM links").fetchone()[0]
        with conn:
            made = conn.execute(
                "INSERT INTO links (kind, created_at, updated_at) VALUES ('shared', 'y', 'y')"
            ).lastrowid
            conn.execute("DELETE FROM links WHERE id = ?", (made,))
            again = conn.execute(
                "INSERT INTO links (kind, created_at, updated_at) VALUES ('shared', 'z', 'z')"
            ).lastrowid
            conn.execute("DELETE FROM links WHERE id = ?", (again,))
        assert top < made < again
        for table in _NEW:
            assert conn.execute(f"PRAGMA foreign_key_check({table})").fetchone() is None
        member = conn.execute(
            "SELECT capital_cents FROM link_members WHERE role = 'mixed'"
        ).fetchone()[0]
        assert member == 500000
        assert changelog.load(conn) == []  # no backfill
        # The new things work: a change is logged and undone.
        fp = conn.execute("SELECT fingerprint FROM transaction_notes WHERE note = 'with Ana'")
        cafe = fp.fetchone()[0]
        with conn, changelog.track(conn, "note", "transaction", cafe, "CAFE") as draft:
            corrections.set_note(conn, cafe, "with Ana and Luis")
        with conn:
            changelog.undo(conn, draft.entry_id)
        note = conn.execute("SELECT note FROM transaction_notes WHERE fingerprint = ?", (cafe,))
        assert note.fetchone()[0] == "with Ana"
    with closing(db.connect(path)) as again:  # idempotent
        assert len(changelog.load(again)) == 2


def test_a_failed_migration_leaves_the_v14_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v14.db"
    _v14(path)
    with closing(sqlite3.connect(path)) as raw:
        before, ddl = _snapshot(raw), _ddl(raw)
    monkeypatch.setattr(db, "LOG_SCHEMA", (*db.LOG_SCHEMA[:2], "CREATE TABLE broken ("))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 14
        assert not set(_NEW) & _tables(raw)
        assert _snapshot(raw) == before
        assert _ddl(raw) == ddl
        assert not any("AUTOINCREMENT" in raw_sql(raw, t) for t in _REBUILT)


def raw_sql(conn: sqlite3.Connection, table: str) -> str:
    query = "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?"
    return conn.execute(query, (table,)).fetchone()[0]
