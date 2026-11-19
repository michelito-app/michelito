"""Schema 14: the cash box (`links.kind = 'cash_box'`, its roles, its columns and
`cash_entries`); migration from 13 without losing anything."""

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import cash_box, cash_box_store, links, spending
from michelito.analysis import categories as cat
from tests.test_spending import _add_bank_rows, seed

D = Decimal
NOW = "2026-01-05T00:00:00+00:00"

# The link tables as schema 13 left them (the CHECKs without the cash box, with the columns of
# schemas 12 and 13).
_V13 = (
    """CREATE TABLE links (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('shared', 'exchange', 'investment')),
    people INTEGER CHECK (people IS NULL OR people >= 2),
    my_share_cents INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0),
    for_other INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1)),
    for_whom TEXT CHECK (for_whom IS NULL OR length(for_whom) <= 80),
    written_off INTEGER NOT NULL DEFAULT 0 CHECK (written_off IN (0, 1)),
    agreed_rate TEXT,
    closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    name TEXT CHECK (name IS NULL OR length(name) <= 80),
    with_whom TEXT CHECK (with_whom IS NULL OR length(with_whom) <= 80)
)""",
    """CREATE TABLE link_members (
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('expense', 'reimbursement', 'leg', 'contribution',
        'return', 'capital', 'mixed')),
    added_at TEXT NOT NULL,
    people INTEGER CHECK (people IS NULL OR people >= 2),
    my_share_cents INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0),
    for_other INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1)),
    capital_cents INTEGER CHECK (capital_cents IS NULL OR capital_cents > 0),
    PRIMARY KEY (link_id, fingerprint)
)""",
    """CREATE TABLE link_manual (
    id INTEGER PRIMARY KEY,
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    day TEXT NOT NULL,
    person TEXT CHECK (person IS NULL OR length(person) <= 80),
    place TEXT CHECK (place IS NULL OR length(place) <= 80),
    created_at TEXT NOT NULL,
    currency TEXT CHECK (currency IS NULL OR currency IN ('DOP', 'USD'))
)""",
)
_TABLES = ("links", "link_members", "link_manual")
_NEW_COLUMNS = {"account_key", "box_currency", "box_amount_cents"}
_NEW_COLUMNS |= {name for name, _ in db.RESERVE_COLUMNS["links"]}  # schema 17


def _v13(path: Path) -> dict[str, str]:
    """A schema 13 database with made-up data: a shared group (with one imported reimbursement
    and one manual), a two-leg exchange and an investment with a mixed return. Returns the
    fingerprints left free for the cash box."""
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-04", "TOKE DE PEDRO INVENTADO", "credit", "5000"),
                ("2026-01-08", "MB a 0000000066 SOCIO INVENTADO", "debit", "30000000"),
                ("2026-01-28", "TRANSF DE SOCIO INVENTADO", "credit", "900000"),
                ("2026-01-10", "RETIRO CAJERO AUTOMATICO INVENTADO", "debit", "2000000"),
                ("2026-01-25", "DEPOSITO EFECTIVO INVENTADO", "credit", "500000"),
            ],
        )
        fps = {m.description: m.fingerprint for m in spending.load_all(conn)}
        cafe = next(fp for text, fp in fps.items() if text.startswith("CAFE FICTICIO"))
        legs = [fp for text, fp in fps.items() if text.startswith("FARMACIA")]
        legs.append(next(fp for text, fp in fps.items() if text.startswith("TIENDA ONLINE")))
        conn.executescript(
            "DROP TABLE link_manual; DROP TABLE link_members; DROP TABLE links;"
            "DROP TABLE cash_entries; PRAGMA user_version = 13;"
        )
        for statement in _V13:
            conn.execute(statement)
        conn.executemany(
            "INSERT INTO links (id, kind, with_whom, name, agreed_rate, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "shared", "Ana", None, None, NOW, NOW),
                (2, "exchange", None, None, "60.0000", NOW, NOW),
                (3, "investment", "Partner", "Business", None, NOW, NOW),
            ],
        )
        conn.executemany(
            "INSERT INTO link_members (link_id, fingerprint, role, added_at, people, "
            "capital_cents) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, cafe, "expense", NOW, 3, None),
                (1, fps["TOKE DE PEDRO INVENTADO"], "reimbursement", NOW, None, None),
                (2, legs[0], "leg", NOW, None, None),
                (2, legs[1], "leg", NOW, None, None),
                (3, fps["MB a 0000000066 SOCIO INVENTADO"], "contribution", NOW, None, None),
                (3, fps["TRANSF DE SOCIO INVENTADO"], "mixed", NOW, None, 500000),
            ],
        )
        conn.execute(
            "INSERT INTO link_manual (link_id, amount_cents, day, person, place, currency, "
            "created_at) VALUES (1, 2500, '2026-01-03', 'Ana', NULL, 'DOP', ?)",
            (NOW,),
        )
        conn.commit()
        return {
            "withdrawal": fps["RETIRO CAJERO AUTOMATICO INVENTADO"],
            "deposit": fps["DEPOSITO EFECTIVO INVENTADO"],
        }


def _sql(conn: sqlite3.Connection, table: str) -> str:
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()[0]


def test_v13_links_survive_and_the_cash_box_fits(tmp_path: Path) -> None:
    path = tmp_path / "v13.db"
    fps = _v13(path)
    with closing(sqlite3.connect(path)) as raw:
        before = {
            table: raw.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in _TABLES
        }
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 14
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert "'cash_box'" in _sql(conn, "links")
        assert "'deposit'" in _sql(conn, "link_members")
        assert "AUTOINCREMENT" in _sql(conn, "cash_entries")
        # No row was lost or changed (the rebuilt tables have the same columns).
        for table, rows in before.items():
            columns = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
            kept = [c for c in columns if c not in _NEW_COLUMNS]
            found = conn.execute(f"SELECT {', '.join(kept)} FROM {table} ORDER BY rowid")
            assert [tuple(r) for r in found] == rows, table
        found = links.load(conn)
        [group], [exchange], [investment] = found.shared, found.exchanges, found.investments
        assert (group.with_whom, len(group.reimbursements), len(group.manual)) == ("Ana", 1, 1)
        assert exchange.agreed_rate == D(60)
        assert [(m.role, m.capital) for m in investment.members] == [
            ("contribution", None),
            ("mixed", D(5000)),
        ]
        # The new things fit: a stored withdrawal, a deposit in another currency and a manual
        # outflow.
        with conn:
            cash_box_store.store(conn, fps["withdrawal"])
            cash_box_store.deposit(conn, fps["deposit"], "USD", D(80))
            entry = cash_box_store.add_entry(conn, "expense", date(2026, 1, 20), D(500), "DOP")
        [box] = links.load(conn).cash_boxes
        assert [(m.role, m.box_currency, m.box_amount) for m in box.members] == [
            ("stored", None, None),
            ("deposit", "USD", D(80)),
        ]
        flow = {m.fingerprint: m for m in spending.load_all(conn)}
        assert flow[fps["withdrawal"]].ref == cat.CASH_BOX
        assert flow[cash_box.entry_fingerprint(entry)].ref == cat.CASH
        # Foreign keys still hold: deleting the link deletes its members.
        with conn:
            conn.execute("DELETE FROM links WHERE id = 1")
        left = conn.execute("SELECT COUNT(*) FROM link_members WHERE link_id = 1").fetchone()[0]
        assert left == 0
        assert conn.execute("SELECT COUNT(*) FROM link_manual").fetchone()[0] == 0
    with closing(db.connect(path)) as again:  # idempotent
        assert len(links.load(again).cash_boxes) == 1
        assert len(cash_box_store.load_entries(again)) == 1


def test_a_failed_migration_leaves_the_v13_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v13.db"
    _v13(path)
    broken = {"links": (("account_key", "TEXT CHECK ("),)}
    monkeypatch.setattr(db, "CASH_BOX_COLUMNS", broken)
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 13
        assert "'cash_box'" not in _sql(raw, "links")
        assert raw.execute("SELECT COUNT(*) FROM link_members").fetchone()[0] == 6
        assert raw.execute("SELECT COUNT(*) FROM link_manual").fetchone()[0] == 1
        tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "cash_entries" not in tables


def test_an_unrelated_orphan_does_not_stop_the_migration(tmp_path: Path) -> None:
    """Only the foreign keys of the tables the migration rebuilds (and the children of `links`)
    are checked: a note with a category that no longer exists does not block opening."""
    path = tmp_path / "v13.db"
    _v13(path)
    with closing(sqlite3.connect(path)) as raw:
        raw.execute(
            "INSERT INTO transaction_notes (fingerprint, category_id, one_off, updated_at) "
            "VALUES ('orphan-fingerprint', 99999, 0, ?)",
            (NOW,),
        )
        raw.commit()
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_a_broken_link_child_stops_the_migration(tmp_path: Path) -> None:
    """A member without its link (something the rebuild must not leave) is caught before the
    COMMIT and the database stays as it was."""
    path = tmp_path / "v13.db"
    _v13(path)
    with closing(sqlite3.connect(path)) as raw:
        raw.execute(
            "INSERT INTO link_members (link_id, fingerprint, role, added_at) "
            "VALUES (999, 'loose-fingerprint', 'leg', ?)",
            (NOW,),
        )
        raw.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 13
