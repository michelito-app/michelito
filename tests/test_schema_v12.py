"""Esquema 12: grupos compartidos (varios gastos por vínculo, el reparto va en cada gasto, «Con
quién» y nombre del grupo, moneda de los reembolsos a mano); migración desde el 11."""

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzas import db
from finanzas.analysis import links, rates, shared, spending
from finanzas.analysis.links import ManualEntry, SharedExpense
from tests.test_spending import _add_bank_rows, seed

D = Decimal

# Las tablas de vínculos como las dejaba el esquema 11 (reparto y «para quién» en `links`, un
# solo gasto por vínculo).
_V11_LINKS = (
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
    """CREATE UNIQUE INDEX link_one_expense ON link_members (link_id) WHERE role = 'expense'""",
    """CREATE TABLE link_manual (
    id INTEGER PRIMARY KEY,
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    day TEXT NOT NULL,
    person TEXT CHECK (person IS NULL OR length(person) <= 80),
    place TEXT CHECK (place IS NULL OR length(place) <= 80),
    created_at TEXT NOT NULL
)""",
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _v11(path: Path) -> tuple[str, str, str]:
    """Una base del esquema 11 con datos inventados: el café compartido entre 3 con un
    reembolso importado y uno a mano, y un regalo pagado por otra persona («para Luis»), ya
    dado por perdido. Devuelve las huellas del café, el regalo y el crédito."""
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(conn, [("2026-01-04", "TOKE DE PEDRO INVENTADO", "credit", "5000")])
        moves = spending.load_all(conn)
        cafe = next(m for m in moves if m.description.startswith("CAFE FICTICIO"))
        gift = next(m for m in moves if m.description.startswith("FARMACIA"))
        toke = next(m for m in moves if m.description.startswith("TOKE DE PEDRO"))
        conn.executescript(
            "DROP TABLE link_manual; DROP TABLE link_members; DROP TABLE links;"
            "PRAGMA user_version = 11;"
        )
        for statement in _V11_LINKS:
            conn.execute(statement)
        now = "2026-01-05T00:00:00+00:00"
        conn.execute(
            "INSERT INTO links (id, kind, people, created_at, updated_at) "
            "VALUES (1, 'shared', 3, ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO links (id, kind, for_other, for_whom, written_off, created_at, "
            "updated_at) VALUES (2, 'shared', 1, 'Luis', 1, ?, ?)",
            (now, now),
        )
        conn.executemany(
            "INSERT INTO link_members VALUES (?, ?, ?, ?)",
            [
                (1, cafe.fingerprint, "expense", now),
                (1, toke.fingerprint, "reimbursement", now),
                (2, gift.fingerprint, "expense", now),
            ],
        )
        conn.execute(
            "INSERT INTO link_manual (link_id, amount_cents, day, person, place, created_at) "
            "VALUES (1, 2500, '2026-01-03', 'Ana', NULL, ?)",
            (now,),
        )
        conn.commit()
        return cafe.fingerprint, gift.fingerprint, toke.fingerprint


def test_v11_groups_keep_every_figure(tmp_path: Path) -> None:
    path = tmp_path / "v11.db"
    cafe, gift, toke = _v11(path)
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 12
        assert {"name", "with_whom"} <= _columns(conn, "links")
        assert {"people", "my_share_cents", "for_other"} <= _columns(conn, "link_members")
        assert "currency" in _columns(conn, "link_manual")
        found = links.load(conn)
        first, second = found.shared
        assert first.expenses == (SharedExpense(cafe, people=3),)
        assert first.reimbursements == (toke,)
        assert first.manual == (ManualEntry(1, D(25), date(2026, 1, 3), "DOP", "Ana", ""),)
        assert (second.expenses, second.with_whom, second.written_off) == (
            (SharedExpense(gift, for_other=True),),
            "Luis",
            True,
        )
        moves = spending.load_all(conn)
        by_fp = {m.fingerprint: m for m in moves}
        # Café RD$ 300 entre 3: cuenta RD$ 100; te devolvieron 50 + 25: te deben 125.
        assert (by_fp[cafe].amount, by_fp[cafe].gross) == (D(100), D(300))
        assert by_fp[toke].link == "reimbursement"
        state = shared.states(moves, found, rates.load(conn))[1]
        assert state.pending == {"DOP": D(125)}
        # El regalo dado por perdido cuenta entero.
        assert by_fp[gift].amount == by_fp[gift].gross
    with closing(db.connect(path)) as again:  # idempotente
        assert links.load(again) == found


def test_v12_allows_several_expenses_in_a_group(tmp_path: Path) -> None:
    path = tmp_path / "v11.db"
    cafe, gift, _ = _v11(path)
    with closing(db.connect(path)) as conn, conn:
        conn.execute("DELETE FROM link_members WHERE fingerprint = ?", (gift,))
        links.add_expense(conn, 1, gift, D(500), people=2)
        assert [e.fingerprint for e in links.load(conn).group(1).expenses] == [cafe, gift]


def test_migrated_cash_keeps_its_currency_when_an_older_dollar_expense_joins(
    tmp_path: Path,
) -> None:
    """La farmacia (RD$ 500 entre 2) con RD$ 200 en efectivo, del esquema 11. Tras migrar se
    suma la tienda en línea (US$ 25, por otra persona), más vieja: el efectivo sigue siendo en
    pesos (a 60, US$ 3.33 para la tienda), no US$ 200."""
    path = tmp_path / "v11.db"
    _, pharmacy, _ = _v11(path)
    with closing(db.connect(path)) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM link_manual WHERE currency IS NULL").fetchone()[0]
            == 0
        )
        with conn:
            conn.execute("UPDATE link_members SET people = 2, for_other = 0 WHERE link_id = 2")
            conn.execute("UPDATE links SET written_off = 0 WHERE id = 2")
            conn.execute(
                "INSERT INTO link_manual (link_id, amount_cents, day, person, place, currency, "
                "created_at) SELECT 2, 20000, '2026-01-11', NULL, NULL, NULL, 'x'"
            )
    # Una base v12 que haya quedado con NULL también se rellena al conectar.
    with closing(db.connect(path)) as conn:
        assert {m.currency for g in links.load(conn).shared for m in g.manual} == {"DOP"}
        rates.store_bcrd(conn, {"2026-01": D(60)})
        moves = spending.load_all(conn)
        store = next(m for m in moves if m.description.startswith("TIENDA ONLINE"))
        with conn:
            links.add_expense(conn, 2, store.fingerprint, store.amount, for_other=True)
        moves = spending.load_all(conn)
        state = shared.states(moves, links.load(conn), rates.load(conn))[2]
        older, newer = state.expenses
        assert (older.currency, older.reimbursed, older.pending) == ("USD", D("3.33"), D("21.67"))
        assert (newer.fingerprint, newer.reimbursed, newer.pending) == (pharmacy, 0, D(250))
        assert state.excess == {}


def test_a_failed_migration_leaves_the_v11_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v11.db"
    _v11(path)
    monkeypatch.setattr(db, "INSIGHT_SCHEMA", (*db.INSIGHT_SCHEMA, "CREATE TABLE roto ("))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 11
        assert "with_whom" not in _columns(raw, "links")
        assert "people" not in _columns(raw, "link_members")
