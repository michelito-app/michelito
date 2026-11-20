"""Schema 12: shared groups (several expenses per link, the split goes on each expense, "with
whom" and the group name, currency of manual reimbursements); migration from 11."""

import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import ledger, ledger_store, rates, spending
from tests.ledger_helpers import groups_summary, share
from tests.test_spending import _add_bank_rows, seed

D = Decimal

# The link tables as schema 11 left them (split and "for whom" on `links`, a single expense
# per link).
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
    """A schema 11 database with made-up data: the coffee shared among 3 with one imported
    reimbursement and one manual, and a gift paid for someone else ("for Luis"), already
    written off. Returns the fingerprints of the coffee, the gift and the credit."""
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


def _state(conn: sqlite3.Connection, name: str) -> ledger.GroupState:
    book = ledger_store.load(conn)
    group = next(g for g in book.groups if g.name == name)
    return ledger.group_state(group, book.me, rates.load(conn))


def test_v11_groups_keep_every_figure(tmp_path: Path) -> None:
    path = tmp_path / "v11.db"
    cafe, gift, toke = _v11(path)
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 12
        assert {"name", "with_whom"} <= _columns(conn, "links")
        assert {"people", "my_share_cents", "for_other"} <= _columns(conn, "link_members")
        assert "currency" in _columns(conn, "link_manual")
        # Schema 19 moved both groups to the ledger.
        first, second = groups_summary(conn)
        assert first["entries"] == [cafe]
        assert sorted(first["payments"], key=str) == sorted(
            [(toke, D(50)), ("manual", D(25))], key=str
        )
        assert (second["entries"], second["people"], second["written_off"]) == (
            [gift],
            ["Luis"],
            ["Luis"],
        )
        moves = spending.load_all(conn)
        by_fp = {m.fingerprint: m for m in moves}
        # Coffee RD$ 300 among 3: counts RD$ 100; 50 + 25 were paid back: 125 still owed.
        assert (by_fp[cafe].amount, by_fp[cafe].gross) == (D(100), D(300))
        assert by_fp[toke].link == "reimbursement"
        assert _state(conn, first["name"]).owed_to_me == {"DOP": D(125)}
        # The written-off gift counts in full.
        assert by_fp[gift].amount == by_fp[gift].gross
        found = groups_summary(conn)
    with closing(db.connect(path)) as again:  # idempotent
        assert groups_summary(again) == found


def test_after_migrating_a_group_takes_more_expenses(tmp_path: Path) -> None:
    path = tmp_path / "v11.db"
    cafe, _, _ = _v11(path)
    with closing(db.connect(path)) as conn:
        store = next(m for m in spending.load_all(conn) if m.description.startswith("TIENDA"))
        group = int(
            conn.execute(
                "SELECT group_id FROM ledger_links WHERE fingerprint = ?", (cafe,)
            ).fetchone()[0]
        )
        with conn:
            share(conn, store.fingerprint, store.amount, people=2, group=group)
        assert groups_summary(conn)[0]["entries"] == sorted(
            [cafe, store.fingerprint],
            key=lambda fp: next(m.day for m in spending.load_all(conn) if m.fingerprint == fp),
        )


def test_migrated_cash_keeps_its_currency_when_an_older_dollar_expense_joins(
    tmp_path: Path,
) -> None:
    """The pharmacy (RD$ 500 split by 2) with RD$ 200 in cash, from schema 11 (no currency:
    filled in as DOP). After migrating, the older online store purchase (US$ 25, for someone
    else) joins: the cash stays in DOP (at 60, US$ 3.33 for the store), not US$ 200."""
    path = tmp_path / "v11.db"
    _, pharmacy, _ = _v11(path)
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("UPDATE links SET written_off = 0, for_other = 0, people = 2 WHERE id = 2")
        raw.execute(
            "INSERT INTO link_manual (link_id, amount_cents, day, person, place, created_at) "
            "VALUES (2, 20000, '2026-01-11', NULL, NULL, 'x')"
        )
        raw.commit()
    with closing(db.connect(path)) as conn:
        [luis] = [g for g in groups_summary(conn) if g["people"] == ["Luis"]]
        assert luis["payments"] == [("manual", D(200))]
        with conn:
            rates.store_bcrd(conn, {"2026-01": D(60)})
        moves = spending.load_all(conn)
        store = next(m for m in moves if m.description.startswith("TIENDA ONLINE"))
        group = int(
            conn.execute(
                "SELECT group_id FROM ledger_links WHERE fingerprint = ?", (pharmacy,)
            ).fetchone()[0]
        )
        with conn:
            share(conn, store.fingerprint, store.amount, for_other=True, group=group)
        state = _state(conn, luis["name"])
        older, newer = state.entries
        assert (older.currency, older.reimbursed, older.pending) == ("USD", D("3.33"), D("21.67"))
        assert (newer.entry.fingerprint, newer.reimbursed, newer.pending) == (pharmacy, 0, D(250))
        assert state.excess == {}


def test_a_failed_migration_leaves_the_v11_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v11.db"
    _v11(path)
    monkeypatch.setattr(db, "INSIGHT_SCHEMA", (*db.INSIGHT_SCHEMA, "CREATE TABLE broken ("))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 11
        assert "with_whom" not in _columns(raw, "links")
        assert "people" not in _columns(raw, "link_members")
