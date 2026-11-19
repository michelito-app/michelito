"""Esquema 13: inversiones (`links.kind = 'investment'`, sus roles, `capital_cents` y los tipos
nuevos de «Para revisar»); migración desde el 12 sin perder nada."""

import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest

from finanzas import db
from finanzas.analysis import links, review_marks, spending
from tests.test_spending import _add_bank_rows, seed

D = Decimal

# Las tablas como las dejaba el esquema 12: las del 11 (los CHECK sin las inversiones) más las
# columnas que el 12 agregaba con ALTER (`db.GROUP_COLUMNS`), como en una base real.
_V12 = (
    """CREATE TABLE links (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('shared', 'exchange')),
    people INTEGER CHECK (people IS NULL OR people >= 2),
    my_share_cents INTEGER CHECK (my_share_cents IS NULL OR my_share_cents >= 0),
    for_other INTEGER NOT NULL DEFAULT 0 CHECK (for_other IN (0, 1)),
    for_whom TEXT CHECK (for_whom IS NULL OR length(for_whom) <= 80),
    written_off INTEGER NOT NULL DEFAULT 0 CHECK (written_off IN (0, 1)),
    agreed_rate TEXT,
    closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """CREATE TABLE link_members (
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('expense', 'reimbursement', 'leg')),
    added_at TEXT NOT NULL,
    PRIMARY KEY (link_id, fingerprint)
)""",
    """CREATE TABLE link_manual (
    id INTEGER PRIMARY KEY,
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    day TEXT NOT NULL,
    person TEXT CHECK (person IS NULL OR length(person) <= 80),
    place TEXT CHECK (place IS NULL OR length(place) <= 80),
    created_at TEXT NOT NULL
)""",
    *(
        f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
        for table, columns in db.GROUP_COLUMNS.items()
        for name, definition in columns
    ),
    """CREATE TABLE review_marks (
    fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('ingreso_inusual', 'tercero_grande', 'duplicado',
        'subio')),
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY (fingerprint, kind)
)""",
)
NOW = "2026-01-05T00:00:00+00:00"


def _v12(path: Path) -> dict[str, str]:
    """Una base del esquema 12 con datos inventados: un grupo compartido (café entre 3, con un
    reembolso importado y uno a mano), un cambio de dos patas y una transferencia grande ya
    revisada. Devuelve las huellas por descripción."""
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-04", "TOKE DE PEDRO INVENTADO", "credit", "5000"),
                ("2026-01-08", "MB a 0000000066 SOCIO INVENTADO", "debit", "30000000"),
                ("2026-01-28", "TRANSF DE SOCIO INVENTADO", "credit", "900000"),
            ],
        )
        fps = {m.description: m.fingerprint for m in spending.load_all(conn)}
        cafe = next(fp for text, fp in fps.items() if text.startswith("CAFE FICTICIO"))
        toke = fps["TOKE DE PEDRO INVENTADO"]
        legs = [fp for text, fp in fps.items() if text.startswith("FARMACIA")]
        legs.append(next(fp for text, fp in fps.items() if text.startswith("TIENDA ONLINE")))
        conn.executescript(
            "DROP TABLE link_manual; DROP TABLE link_members; DROP TABLE links;"
            "DROP TABLE review_marks; PRAGMA user_version = 12;"
        )
        for statement in _V12:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO links (id, kind, with_whom, created_at, updated_at) "
            "VALUES (1, 'shared', 'Ana', ?, ?)",
            (NOW, NOW),
        )
        conn.execute(
            "INSERT INTO links (id, kind, agreed_rate, created_at, updated_at) "
            "VALUES (2, 'exchange', '60.0000', ?, ?)",
            (NOW, NOW),
        )
        conn.executemany(
            "INSERT INTO link_members (link_id, fingerprint, role, added_at, people) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (1, cafe, "expense", NOW, 3),
                (1, toke, "reimbursement", NOW, None),
                (2, legs[0], "leg", NOW, None),
                (2, legs[1], "leg", NOW, None),
            ],
        )
        conn.execute(
            "INSERT INTO link_manual (link_id, amount_cents, day, person, place, currency, "
            "created_at) VALUES (1, 2500, '2026-01-03', 'Ana', NULL, 'DOP', ?)",
            (NOW,),
        )
        sent = fps["MB a 0000000066 SOCIO INVENTADO"]
        conn.execute("INSERT INTO review_marks VALUES (?, 'tercero_grande', ?)", (sent, NOW))
        conn.commit()
        return {"cafe": cafe, "toke": toke, "sent": sent, "back": fps["TRANSF DE SOCIO INVENTADO"]}


def _sql(conn: sqlite3.Connection, table: str) -> str:
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()[0]


def test_v12_links_and_marks_survive_and_investments_fit(tmp_path: Path) -> None:
    path = tmp_path / "v12.db"
    fps = _v12(path)
    with closing(sqlite3.connect(path)) as raw:
        before = {
            table: raw.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("links", "link_members", "link_manual", "review_marks")
        }
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert "'investment'" in _sql(conn, "links")
        assert "'mixed'" in _sql(conn, "link_members")
        assert "'aporte_posible'" in _sql(conn, "review_marks")
        # Ninguna fila se perdió ni cambió (las tablas rehechas tienen las mismas columnas).
        for table, rows in before.items():
            columns = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
            added = {"capital_cents", "account_key", "box_currency", "box_amount_cents"}
            added |= {name for name, _ in db.RESERVE_COLUMNS["links"]}
            kept = [c for c in columns if c not in added]
            found = conn.execute(f"SELECT {', '.join(kept)} FROM {table} ORDER BY rowid")
            assert [tuple(r) for r in found] == rows, table
        found = links.load(conn)
        [group] = found.shared
        assert (group.with_whom, group.reimbursements, len(group.manual)) == (
            "Ana",
            (fps["toke"],),
            1,
        )
        assert found.exchanges[0].agreed_rate == D(60)
        assert review_marks.load(conn) == {(fps["sent"], "tercero_grande")}
        # Lo nuevo cabe: una inversión con un crédito mixto y lo revisado de los tipos nuevos.
        with conn:
            investment = links.create_investment(conn, fps["sent"], with_whom="Socio")
            links.add_investment_member(
                conn, investment, fps["back"], "mixed", D(9000), capital=D(5000)
            )
            review_marks.set_reviewed(conn, fps["back"], "cobro_posible", True)
        [stored] = links.load(conn).investments
        assert [(m.role, m.capital) for m in stored.members] == [
            ("contribution", None),
            ("mixed", D(5000)),
        ]
        # Las claves foráneas siguen: borrar el vínculo borra sus miembros.
        with conn:
            conn.execute("DELETE FROM links WHERE id = 1")
        left = conn.execute("SELECT COUNT(*) FROM link_members WHERE link_id = 1").fetchone()[0]
        assert left == 0
        assert conn.execute("SELECT COUNT(*) FROM link_manual").fetchone()[0] == 0
    with closing(db.connect(path)) as again:  # idempotente
        assert len(links.load(again).investments) == 1


def test_a_fresh_database_takes_investments(tmp_path: Path) -> None:
    with closing(db.connect(tmp_path / "nueva.db")) as conn:
        seed(conn)
        move = next(m for m in spending.load_all(conn) if m.amount > 0)
        with conn:
            links.create_investment(conn, move.fingerprint)
        assert links.load(conn).investments[0].contributions == (move.fingerprint,)


def test_a_failed_migration_leaves_the_v12_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v12.db"
    _v12(path)
    broken = {"link_members": (("capital_cents", "INTEGER CHECK ("),)}
    monkeypatch.setattr(db, "INVESTMENT_COLUMNS", broken)
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 12
        assert "'investment'" not in _sql(raw, "links")
        assert raw.execute("SELECT COUNT(*) FROM link_members").fetchone()[0] == 4
        assert raw.execute("SELECT COUNT(*) FROM review_marks").fetchone()[0] == 1


def test_an_unrelated_orphan_does_not_stop_opening_the_database(tmp_path: Path) -> None:
    """Una nota con una categoría que ya no existe (huérfana ajena a los vínculos) no impide
    migrar desde el 12 ni volver a abrir: solo se revisan las hijas de `links` rehechas."""
    path = tmp_path / "v12.db"
    _v12(path)
    with closing(sqlite3.connect(path)) as raw:  # sin claves foráneas, como una base vieja
        raw.execute(
            "INSERT INTO transaction_notes (fingerprint, category_id, one_off, updated_at) "
            "VALUES ('huella-huerfana', 99999, 0, ?)",
            (NOW,),
        )
        raw.commit()
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with closing(db.connect(path)) as again:
        assert len(links.load(again).shared) == 1
