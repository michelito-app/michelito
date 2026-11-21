"""Schema 22 (`migrations_v22`): the per-person exchange-leftover toggle and the dismissed
"paid for others" suggestions. A database at schema 21 (no column, no table) migrates forward,
plain and encrypted, and every balance (with the leftovers, and without them) stays identical.
Made-up people and amounts."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

from michelito import db
from michelito.analysis import changelog, ledger, ledger_store, rates
from tests import ledger_cover_case as case
from tests import test_schema_v21 as v21
from tests.test_schema_v21 import Opener, _ledger, figures

opened = v21.opened  # the same plain and encrypted databases


def _cover_group(conn: sqlite3.Connection) -> None:
    """The synthetic cover case with Ana's last payment already covering Beto: Ana keeps a
    RD$ 20.78 exchange leftover, which schema 22's default counts as settled."""
    with conn:
        rates.store_bcrd(conn, {m: r.value for m, r in case.RATES.items()})
        me = ledger_store.ensure_me(conn)
        ana = ledger_store.create_contact(conn, "Ana Cubre")
        beto = ledger_store.create_contact(conn, "Beto Cubierto")
        group = ledger_store.create_group(conn, "Viaje", [ana, beto])  # spanish-data
        for amount, day in ((case.HOTEL, date(2025, 12, 5)), (case.FLIGHTS, date(2025, 12, 10))):
            ledger_store.add_entry(
                conn,
                group,
                paid_by=me,
                amount=amount,
                currency="USD",
                day=day,
                description="Hotel",
                splits=ledger_store.build_splits(amount, me, "equal", [me, ana, beto]),
                mode="equal",
            )
        ids = {case.ANA: ana, case.BETO: beto}
        for pid, who, amount, day in case.PAYMENTS:
            parts = (
                {ana: Decimal("732.95"), beto: Decimal("40087.05")} if pid == case.LAST else None
            )
            ledger_store.add_payment(
                conn,
                group,
                from_contact=ids[who],
                to_contact=me,
                amount=amount,
                currency="DOP",
                day=day,
                allocations=parts,
            )


def _to_schema_21(conn: sqlite3.Connection) -> None:
    conn.executescript(
        "BEGIN;"
        "DROP TABLE ledger_dismissals;"
        "ALTER TABLE ledger_members DROP COLUMN leftover_settled;"
        "PRAGMA user_version = 21;"
        "COMMIT;"
    )


def _figures(conn: sqlite3.Connection) -> tuple[list[tuple], list[tuple]]:
    """`figures` of every group, and each person's raw balance and leftover, in cents."""
    conn.row_factory = sqlite3.Row
    states = ledger.states(ledger_store.load(conn), rates.load(conn)).values()
    raw = [
        (s.id, p.contact_id, sorted(p.raw_net.items()), sorted(p.leftover))
        for s in states
        for p in s.people
    ]
    return figures(states), raw


def test_schema_21_migrates_with_identical_balances(
    tmp_path: Path, opened: tuple[Opener, Opener]
) -> None:
    raw, connect = opened
    path = tmp_path / "michelito.db"
    with closing(connect(path)) as conn:
        _ledger(conn)
        _cover_group(conn)
    with closing(raw(path)) as conn:
        _to_schema_21(conn)
        before = _figures(conn)
    # The cover group: Ana's leftover is settled, Beto owes nothing (read without the column).
    leftovers = [row for row in before[1] if row[3]]
    assert [(r[2], r[3]) for r in leftovers] == [
        ([("DOP", Decimal("-20.78"))], [("DOP", Decimal("-20.78"))])
    ]
    with closing(connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 22
        assert _figures(conn) == before
        flags = conn.execute("SELECT DISTINCT leftover_settled FROM ledger_members").fetchall()
        assert [tuple(f) for f in flags] == [(1,)]
        assert conn.execute("SELECT COUNT(*) FROM ledger_dismissals").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with closing(connect(path)) as conn:  # opening again changes nothing
        assert _figures(conn) == before


def test_a_dismissal_goes_with_its_payment_and_comes_back_with_it(tmp_path: Path) -> None:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        _cover_group(conn)
        payment = conn.execute("SELECT MAX(id) FROM ledger_payments").fetchone()[0]
        with conn:
            ledger_store.set_cover_dismissed(conn, payment, True)
        assert ledger_store.load(conn).groups[0].dismissed == frozenset({payment})
        with (
            conn,
            changelog.track(conn, "group_payment_delete", "link", "group-1", "Viaje") as draft,
        ):
            ledger_store.delete_payment(conn, payment)
        assert conn.execute("SELECT COUNT(*) FROM ledger_dismissals").fetchone()[0] == 0
        assert draft.entry_id is not None
        with conn:  # the cascade was recorded: the undo brings the payment and its "No" back
            changelog.undo_original(conn, draft.entry_id)
        assert ledger_store.load(conn).groups[0].dismissed == frozenset({payment})


def test_small_converted_leftovers_now_show_as_settled(tmp_path: Path) -> None:
    """A behaviour change for existing data, on purpose: a group already holding a converted
    leftover below RD$ 50 / US$ 1 before schema 22 shows it as settled after it (the default
    toggle is on); turning the toggle off gives back exactly the old balance."""
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        _cover_group(conn)
        state = next(iter(ledger.states(ledger_store.load(conn), rates.load(conn)).values()))
        ana = next(p for p in state.people if p.leftover)
        assert ana.net == {} and ana.raw_net == {"DOP": Decimal("-20.78")}
        group = state.group.id
        with conn:
            ledger_store.set_leftover_settled(conn, group, ana.contact_id, False)
        state = ledger.states(ledger_store.load(conn), rates.load(conn))[group]
        assert state.person(ana.contact_id).net == {"DOP": Decimal("-20.78")}  # type: ignore[union-attr]
