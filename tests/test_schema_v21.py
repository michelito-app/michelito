"""Schema 21 (`migrations_v21`): splits by parts and payments on behalf of others. A database at
schema 20 (entries' old CHECK, no parts, no allocations) migrates forward, plain and encrypted,
and every balance stays identical. Made-up people and amounts."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from michelito import db, encrypted, migrations_v21
from michelito.analysis import ledger, ledger_store, rates

_OLD_ENTRIES = """CREATE TABLE ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES ledger_groups(id) ON DELETE CASCADE,
    paid_by INTEGER NOT NULL REFERENCES contacts(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency IN ('DOP', 'USD')),
    day TEXT NOT NULL CHECK (length(day) = 10),
    description TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND 120),
    category_id INTEGER,
    split TEXT NOT NULL CHECK (split IN ('equal', 'exact')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""
_OLD_SPLITS = """CREATE TABLE ledger_splits (
    entry_id INTEGER NOT NULL REFERENCES ledger_entries(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    share_cents INTEGER NOT NULL CHECK (share_cents >= 0),
    PRIMARY KEY (entry_id, contact_id)
)"""
_ENTRY_COLUMNS = (
    "id, group_id, paid_by, amount_cents, currency, day, description, category_id, split, "
    "created_at, updated_at"
)


def _ledger(conn: sqlite3.Connection) -> None:
    """Varied groups: both directions, a payment against the balance, an unattributed one, one
    in another currency, a difference accepted and one pending, a write-off."""
    with conn:
        rates.store_bcrd(conn, {"2026-01": Decimal("60"), "2026-02": Decimal("61")})
        me = ledger_store.ensure_me(conn)
        ana = ledger_store.create_contact(conn, "Ana Ficticia")
        luis = ledger_store.create_contact(conn, "Luis Inventado")
        rosa = ledger_store.create_contact(conn, "Rosa Ficticia")
        trip = ledger_store.create_group(conn, "Viaje", [ana, luis])  # spanish-data
        dinners = ledger_store.create_group(conn, "Cenas", [ana, rosa])  # spanish-data
        for group, paid_by, cents, currency, day, people in (
            (trip, me, 900000, "DOP", date(2026, 1, 3), [me, ana, luis]),
            (trip, ana, 300001, "DOP", date(2026, 1, 9), [me, ana, luis]),
            (trip, me, 15000, "USD", date(2026, 1, 15), [me, luis]),
            (dinners, rosa, 120000, "DOP", date(2026, 2, 1), [me, ana, rosa]),
            (dinners, me, 80000, "DOP", date(2026, 2, 2), [ana, rosa]),
        ):
            amount = Decimal(cents).scaleb(-2)
            ledger_store.add_entry(
                conn,
                group,
                paid_by=paid_by,
                amount=amount,
                currency=currency,
                day=day,
                description="Gasto",  # spanish-data
                splits=ledger_store.build_splits(amount, paid_by, "equal", people),
                mode="equal",
            )
        for group, source, target, cents, currency, day, sent in (
            (trip, ana, me, 150000, "DOP", date(2026, 1, 20), None),
            (trip, me, ana, 50000, "DOP", date(2026, 1, 21), None),
            (trip, luis, me, 3000, "USD", date(2026, 1, 25), None),
            (trip, luis, me, 100000, "DOP", date(2026, 1, 26), 101000),
            (dinners, rosa, me, 20000, "DOP", date(2026, 2, 3), 20500),
            (dinners, None, me, 10000, "DOP", date(2026, 2, 4), None),
            (dinners, me, rosa, 40000, "DOP", date(2026, 2, 5), None),
        ):
            ledger_store.add_payment(
                conn,
                group,
                from_contact=source,
                to_contact=target,
                amount=Decimal(cents).scaleb(-2),
                currency=currency,
                day=day,
                sent=None if sent is None else Decimal(sent).scaleb(-2),
            )
        accepted = conn.execute(
            "SELECT id FROM ledger_payments WHERE sent_cents = 101000"
        ).fetchone()[0]
        ledger_store.update_payment(conn, int(accepted), accepted=True)
        ledger_store.set_written_off(conn, dinners, ana, True)


def _to_schema_20(conn: sqlite3.Connection) -> None:
    """The ledger as schema 20 had it: the old CHECK, no parts and no allocations."""
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        "BEGIN;"
        f"CREATE TABLE entries_old AS SELECT {_ENTRY_COLUMNS} FROM ledger_entries;"
        "CREATE TABLE splits_old AS SELECT entry_id, contact_id, share_cents FROM ledger_splits;"
        "DROP TABLE ledger_splits; DROP TABLE ledger_entries; DROP TABLE ledger_allocations;"
        f"{_OLD_ENTRIES}; {_OLD_SPLITS};"
        f"INSERT INTO ledger_entries ({_ENTRY_COLUMNS}) SELECT {_ENTRY_COLUMNS} FROM entries_old;"
        "INSERT INTO ledger_splits SELECT * FROM splits_old;"
        "DROP TABLE entries_old; DROP TABLE splits_old;"
        "PRAGMA user_version = 20;"
        "COMMIT;"
    )
    conn.execute("PRAGMA foreign_keys = ON")


def _c(value: Decimal) -> int:
    return int((value * 100).to_integral_value())


def figures(states: Iterable[Any]) -> list[tuple]:
    """Every figure the ledger gives per group, in cents: people, totals, each entry and each
    payment. Plain values, so the same function reads the old release's states (the golden
    figures below) and today's."""
    found = []
    for state in states:
        found.append(
            (
                state.id,
                tuple(
                    (p.contact_id, tuple((c, _c(v)) for c, v in p.net.items()))
                    for p in state.people
                ),
                tuple((c, _c(v)) for c, v in state.owed_to_me.items()),
                tuple((c, _c(v)) for c, v in state.i_owe.items()),
                tuple(
                    (
                        t.currency,
                        _c(t.share),
                        _c(t.reimbursed),
                        _c(t.pending),
                        _c(t.written_off),
                        _c(t.i_owe),
                    )
                    for t in state.totals
                ),  # fmt: skip
                tuple(
                    (
                        e.entry.id,
                        _c(e.counted),
                        _c(e.pending),
                        _c(e.written_off),
                        _c(e.debt_pending),
                    )
                    for e in state.entries
                ),
                tuple(
                    (p.payment.id, _c(p.excess), _c(p.turned), p.unconverted, p.uncounted)
                    for p in state.payments
                ),
                tuple((c, _c(v)) for c, v in state.loose),
            )
        )
    return found


def _balances(conn: sqlite3.Connection) -> list[tuple]:
    conn.row_factory = sqlite3.Row
    book = ledger_store.load(conn)
    return figures(ledger.states(book, rates.load(conn)).values())


# `figures` of `_ledger` at schema 20, computed with the release before schema 21 (8924dde's
# `analysis.ledger` and `ledger_store`, run on the downgraded database): the migration must give
# exactly these, not just what today's code says about the old rows.
GOLDEN = [
    (
        1,
        ((2, (("DOP", 100000),)), (3, (("DOP", 19000), ("USD", 7500)))),
        (("DOP", 119000), ("USD", 7500)),
        (),
        (("DOP", 300000, 431000, 169000, 0, 50000), ("USD", 7500, 0, 7500, 0, 0)),
        ((1, 300000, 169000, 0, 0), (2, 100000, 0, 0, 50000), (3, 7500, 7500, 0, 0)),
        (
            (1, 0, 0, False, False),
            (2, 0, 0, False, False),
            (3, 0, 0, False, False),
            (4, 0, 0, False, False),
        ),
        (),
    ),
    (
        2,
        ((2, ()), (4, (("DOP", 20000),))),
        (("DOP", 10000),),
        (),
        (("DOP", 0, 30000, 10000, 40000, 0),),
        ((4, 40000, 0, 0, 0), (5, 40000, 10000, 40000, 0)),
        ((5, 0, 0, False, False), (6, 0, 0, False, False), (7, 0, 0, False, False)),
        (("DOP", 10000),),
    ),
]


Opener = Callable[[Path], sqlite3.Connection]


def _plain(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)


@pytest.fixture(params=["plain", "encrypted"])
def opened(request: pytest.FixtureRequest) -> tuple[Opener, Opener]:
    """(open raw, open through `db.connect`) for a plain or an encrypted (hosted) database."""
    if request.param == "plain":
        return _plain, db.connect
    key = secrets.token_bytes(encrypted.KEY_BYTES)
    return (lambda path: encrypted.connect(path, key)), (lambda path: db.connect(path, key))


def test_schema_20_migrates_with_identical_balances(
    tmp_path: Path, opened: tuple[Opener, Opener]
) -> None:
    raw, connect = opened
    path = tmp_path / "michelito.db"
    with closing(connect(path)) as conn:
        _ledger(conn)
    with closing(raw(path)) as conn:
        _to_schema_20(conn)
        before = _balances(conn)
        assert (
            "'parts'"
            not in conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'ledger_entries'"
            ).fetchone()[0]
        )
    assert before == GOLDEN
    with closing(connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 21
        assert _balances(conn) == before == GOLDEN
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'ledger_entries'").fetchone()
        assert "'parts'" in sql[0]
        # One allocation per attributed payment: the other end, the whole amount.
        rows = conn.execute(
            "SELECT p.id, p.from_contact, p.to_contact, p.amount_cents, a.contact_id, "
            "a.amount_cents FROM ledger_payments p "
            "LEFT JOIN ledger_allocations a ON a.payment_id = p.id ORDER BY p.id"
        ).fetchall()
        me = ledger_store.me_id(conn)
        for _, source, target, cents, contact, allocated in rows:
            if source is None:
                assert contact is None
            else:
                assert (contact, allocated) == (source if target == me else target, cents)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # Ids and the sequence survive the rebuild: a new entry never reuses one.
        last = conn.execute("SELECT MAX(id) FROM ledger_entries").fetchone()[0]
        group = conn.execute("SELECT id FROM ledger_groups ORDER BY id").fetchone()[0]
        with conn:
            made = ledger_store.add_entry(
                conn,
                group,
                paid_by=me,
                amount=Decimal(10),
                currency="DOP",
                day=date(2026, 3, 1),
                description="Nuevo",  # spanish-data
                splits=ledger_store.build_splits(Decimal(10), me, "parts", (), None, {me: 2}),
                mode="parts",
            )
        assert made > last
    with closing(connect(path)) as conn:  # opening again changes nothing
        assert conn.execute("SELECT COUNT(*) FROM ledger_allocations").fetchone()[0] == 6


def test_allocations_that_do_not_add_up_stop_the_migration(tmp_path: Path) -> None:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        _ledger(conn)
    with closing(sqlite3.connect(path)) as conn:
        _to_schema_20(conn)
        conn.executescript(
            "CREATE TABLE ledger_allocations (payment_id INTEGER, contact_id INTEGER, "
            "amount_cents INTEGER, PRIMARY KEY (payment_id, contact_id));"
            "INSERT INTO ledger_allocations SELECT id, from_contact, amount_cents - 1 "
            "FROM ledger_payments WHERE from_contact IS NOT NULL LIMIT 1;"
        )
    with pytest.raises(migrations_v21.AllocationMismatch):
        db.connect(path)
    with closing(sqlite3.connect(path)) as conn:  # rolled back: still schema 20
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 20
