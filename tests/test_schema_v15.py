"""Esquema 15: la bitácora (`change_log` y sus índices, `rule_dismissals`,
`reviewed_fingerprints`) y `AUTOINCREMENT` en `categories`, `links` y `link_manual`; migración
desde el 14 sin perder nada (ni ids, ni filas, ni índices)."""

import re
import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzas import db
from finanzas.analysis import cash_box_store, changelog, corrections, links, spending
from finanzas.analysis import categories as cat
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
    """Una base del esquema 14 con datos inventados: un vínculo de cada tipo (compartido con un
    reembolso a mano, cambio, inversión con un cobro mixto y caja fuerte con un retiro guardado y
    un depósito en otra moneda), un movimiento a mano de la caja, una nota y una regla."""
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
            cash_box_store.add_entry(
                conn, "expense", date(2026, 1, 20), D(500), "DOP", note="propina"
            )
            corrections.set_note(conn, cafe, "con Ana")
            corrections.set_merchant_category(conn, "UBER EATS", cat.RESTAURANTS)
        # Un id borrado antes de migrar: el esquema 14 lo reusaría.
        conn.execute("INSERT INTO links (kind, created_at, updated_at) VALUES ('shared', 'x', 'x')")
        conn.execute("DELETE FROM links WHERE id = (SELECT MAX(id) FROM links)")
        for table in _NEW:
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version = 14")
        conn.commit()
        _without_autoincrement(conn)


def _without_autoincrement(conn: sqlite3.Connection) -> None:
    """Deja `categories`, `links` y `link_manual` como en el esquema 14 (sin `AUTOINCREMENT`),
    con las mismas filas, ids e índices."""
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
    """El SQL de las tablas y los índices de `_KEPT` (en las rehechas, sin `AUTOINCREMENT`)."""
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
        assert _snapshot(conn) == before  # ninguna fila se perdió ni cambió (ni su id)
        assert _ddl(conn) == ddl  # mismas columnas, CHECK e índices
        for table in _REBUILT:
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()[0]
            assert "id INTEGER PRIMARY KEY AUTOINCREMENT" in sql, table
            assert conn.execute(f"PRAGMA foreign_key_check({table})").fetchone() is None
        # Un id borrado ya no se reusa: el siguiente grupo sale después del más alto.
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
        assert changelog.load(conn) == []  # sin relleno hacia atrás
        # Lo nuevo funciona: un cambio queda en la bitácora y se deshace.
        fp = conn.execute("SELECT fingerprint FROM transaction_notes WHERE note = 'con Ana'")
        cafe = fp.fetchone()[0]
        with conn, changelog.track(conn, "nota", "transaccion", cafe, "CAFE") as draft:
            corrections.set_note(conn, cafe, "con Ana y Luis")
        with conn:
            changelog.undo(conn, draft.entry_id)
        note = conn.execute("SELECT note FROM transaction_notes WHERE fingerprint = ?", (cafe,))
        assert note.fetchone()[0] == "con Ana"
    with closing(db.connect(path)) as again:  # idempotente
        assert len(changelog.load(again)) == 2


def test_a_failed_migration_leaves_the_v14_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v14.db"
    _v14(path)
    with closing(sqlite3.connect(path)) as raw:
        before, ddl = _snapshot(raw), _ddl(raw)
    monkeypatch.setattr(db, "LOG_SCHEMA", (*db.LOG_SCHEMA[:2], "CREATE TABLE roto ("))
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
