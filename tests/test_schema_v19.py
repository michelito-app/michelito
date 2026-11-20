"""Schema 19: shared groups move from `links` to the ledger with **identical balances**.

A schema 18 database is made by writing the old rows (`links` kind `shared`, `link_members`,
`link_manual`) and setting `user_version` to 18; opening it migrates. The balances of every group
(the user's share, what was paid back, what is pending and what was written off, by currency),
what each expense counts as spending and each credit's category are compared before (the old
math, frozen in `migrations_v19`, plus hand-computed figures) and after (the ledger). Made-up
data; a seeded random batch of varied groups on top of the hand-made ones."""

from __future__ import annotations

import random
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db, migrations_v19
from michelito.analysis import ledger, ledger_store, rates, spending
from tests.ledger_helpers import groups_summary, old_expense, old_group, old_manual, old_refund
from tests.test_spending import _add_bank_rows, seed

D = Decimal


def _open_raw(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _as_v18(path: Path) -> None:
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("PRAGMA user_version = 18")
        raw.commit()


def _fps(conn: sqlite3.Connection) -> dict[str, spending.Movement]:
    return {m.description: m for m in spending.load_all(conn)}


def _before(path: Path):
    """The old math on the schema 18 database (what the previous release showed)."""
    with closing(_open_raw(path)) as conn:
        _, old, by_fp, _ = migrations_v19.legacy_snapshot(conn)
        return (
            {gid: s.totals() for gid, s in old.items()},
            {e.move.fingerprint: e.counted for s in old.values() for e in s.expenses},
            {gid: s.uncounted for gid, s in old.items()},
            by_fp,
        )


def _cents(totals: dict[str, tuple[Decimal, ...]]) -> dict[str, tuple[int, ...]]:
    return {c: tuple(int(v * 100) for v in values) for c, values in totals.items()}


def _same(after: dict[int, dict], before: dict[int, dict]) -> bool:
    """Group by group through the old -> new id map (`ledger_migration`), in cents."""
    return {k: _cents(v) for k, v in after.items()} == {k: _cents(v) for k, v in before.items()}


def _after(conn: sqlite3.Connection):
    """The ledger's figures of each migrated group with expenses, by its OLD link id."""
    book = ledger_store.load(conn)
    states = ledger.states(book, rates.load(conn))
    mapping = dict(conn.execute("SELECT link_id, group_id FROM ledger_migration"))
    totals = {
        old: {t.currency: (t.share, t.reimbursed, t.pending, t.written_off) for t in s.totals}
        for old, new in mapping.items()
        if (s := states.get(new)) is not None and s.entries
    }
    return book, states, totals


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """The synthetic statements plus a few credits, with rates for both months."""
    found = tmp_path / "v18.db"
    with closing(db.connect(found)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-04", "TOKE DE PEDRO INVENTADO", "credit", "5000"),
                ("2026-01-06", "TOKE DE LUISA INVENTADA", "credit", "5000"),
                ("2026-01-07", "TRANSFERENCIA DE ANA FICTICIA", "credit", "200000"),
                ("2026-01-09", "TOKE DE ROSA FICTICIA", "credit", "123457"),
            ],
        )
        with conn:
            rates.store_bcrd(conn, {"2025-12": D("60"), "2026-01": D("61.5")})
    return found


def test_hand_made_groups_keep_every_figure(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        by_text = _fps(conn)
        cafe = next(m for t, m in by_text.items() if t.startswith("CAFE FICTICIO"))
        pharmacy = next(m for t, m in by_text.items() if t.startswith("FARMACIA"))
        online = next(m for t, m in by_text.items() if t.startswith("TIENDA ONLINE"))
        with conn:
            # Coffee RD$ 300 "we were 3" with Ana: a credit of 50 and RD$ 25 by hand.
            coffee = old_group(conn, cafe.fingerprint, people=3, with_whom="Ana")
            old_refund(conn, coffee, by_text["TOKE DE PEDRO INVENTADO"].fingerprint)
            place = "Banco Ficticio"  # spanish-data
            old_manual(conn, coffee, D(25), date(2026, 1, 3), "DOP", "Ana", place)
            # Pharmacy "my share" and the online store "for someone else", in a group with Luis
            # and Rosa; a credit in RD$ for a US$ expense.
            both = old_group(
                conn, pharmacy.fingerprint, my_share=D(100), with_whom="Luis y Rosa", name="Casa"
            )
            old_expense(conn, both, online.fingerprint, for_other=True)
            old_refund(conn, both, by_text["TOKE DE ROSA FICTICIA"].fingerprint)
            # A dormant group: its expense is not there anymore, its credit stays linked.
            dormant = old_group(conn, "a-fingerprint-that-is-gone", people=2, with_whom="Ana")
            old_refund(conn, dormant, by_text["TOKE DE LUISA INVENTADA"].fingerprint)
    _as_v18(path)
    totals, counted, _, by_fp = _before(path)
    # By hand: the coffee counts 100 and has 300 - 100 - 50 - 25 = 125 pending.
    assert totals[coffee]["DOP"] == (D(100), D(75), D(125), 0)
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 19
        assert conn.execute("SELECT COUNT(*) FROM links WHERE kind = 'shared'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM link_manual").fetchone()[0] == 0
        book, states, after = _after(conn)
        assert _same(after, totals)
        moves = {m.fingerprint: m for m in spending.load_all(conn)}
        for fp, value in counted.items():
            assert moves[fp].amount == value, fp
        assert moves[by_text["TOKE DE PEDRO INVENTADO"].fingerprint].link == "reimbursement"
        assert moves[by_text["TOKE DE LUISA INVENTADA"].fingerprint].link == "reimbursement"
        every = groups_summary(conn)
        summary = {g["name"]: g for g in every if not g["archived"]}
        assert summary["Ana"]["people"] == ["Ana", "Persona 3"]  # spanish-ui
        assert summary["Casa"]["people"] == ["Luis", "Rosa"]
        # One person: the payments are hers; two or more: unattributed ("unassigned").
        coffee_state = next(s for s in states.values() if s.group.name == "Ana" and s.entries)
        assert [p.payment.from_contact for p in coffee_state.payments] == [None, None]
        assert [g["archived"] for g in every].count(True) == 1  # the dormant one
        # The same contact for the same name in two groups; "Review your people" is offered.
        names = [c.name for c in book.contacts.values() if not c.is_me]
        assert names.count("Ana") == 1
        assert book.review_people
        assert by_fp  # the old math saw the movements


def _random_groups(conn: sqlite3.Connection, seed_value: int) -> None:
    """Varied old groups over the synthetic movements: every split form, one to three expenses
    in both currencies, credits and manual reimbursements in both currencies (some in excess),
    written off or not, several names or none."""
    rng = random.Random(seed_value)
    moves = spending.load_all(conn)
    expenses = [m for m in moves if m.kind == "expense" and m.amount > 0]
    credits = [m for m in moves if m.amount < 0 and m.kind != "transfer"]
    rng.shuffle(expenses)
    rng.shuffle(credits)
    names = ["Ana", "Luis", "Rosa", "Pedro", "Ana y Luis", "Rosa, Pedro & Ana", ""]
    while len(expenses) >= 3:
        chosen = [expenses.pop() for _ in range(rng.randint(1, 3))]
        group = None
        for move in chosen:
            form = rng.choice(("people", "share", "other"))
            split = {
                "people": {"people": rng.randint(2, 6)},
                "share": {
                    "my_share": max(D("0.01"), (move.amount * D(rng.random())).quantize(D("0.01")))
                },
                "other": {"for_other": True},
            }[form]
            if group is None:
                group = old_group(
                    conn,
                    move.fingerprint,
                    with_whom=rng.choice(names) or None,
                    written_off=rng.random() < 0.25,
                    **split,
                )
            else:
                old_expense(conn, group, move.fingerprint, **split)
        assert group is not None
        if credits and rng.random() < 0.7:
            old_refund(conn, group, credits.pop().fingerprint)
        for _ in range(rng.randint(0, 2)):
            old_manual(
                conn,
                group,
                D(rng.randint(1, 400_000)) / 100,
                date(2026, 1, rng.randint(1, 28)),
                rng.choice(("DOP", "USD")),
                rng.choice(("Ana", None)),
            )


@pytest.mark.parametrize("seed_value", range(1, 13))
def test_varied_groups_keep_identical_balances(path: Path, seed_value: int) -> None:
    with closing(db.connect(path)) as conn, conn:
        _random_groups(conn, seed_value)
    _as_v18(path)
    totals, counted, uncounted, _ = _before(path)
    assert totals  # there is something to compare
    with closing(db.connect(path)) as conn:
        _, states, after = _after(conn)
        assert _same(after, totals)
        moves = {m.fingerprint: m for m in spending.load_all(conn)}
        for fp, value in counted.items():
            assert moves[fp].amount == value
        assert {fp for s in states.values() for fp in s.uncounted} == {
            fp for found in uncounted.values() for fp in found
        }


def test_without_rates_too(path: Path) -> None:
    with closing(db.connect(path)) as conn, conn:
        conn.execute("DELETE FROM exchange_rates")
        _random_groups(conn, 9)
    _as_v18(path)
    totals, counted, _, _ = _before(path)
    with closing(db.connect(path)) as conn:
        _, _, after = _after(conn)
        assert _same(after, totals)
        moves = {m.fingerprint: m for m in spending.load_all(conn)}
        assert all(moves[fp].amount == value for fp, value in counted.items())


def test_a_mismatch_rolls_everything_back(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with closing(db.connect(path)) as conn, conn:
        cafe = next(m for t, m in _fps(conn).items() if t.startswith("CAFE FICTICIO"))
        old_group(conn, cafe.fingerprint, people=3, with_whom="Ana")
    _as_v18(path)
    # The ledger side splits the rest wrongly: the check must catch it.
    monkeypatch.setattr(migrations_v19, "_spread", lambda total, people: {people[0]: total + 1})
    with pytest.raises(migrations_v19.MigrationMismatch):
        db.connect(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 18
        assert raw.execute("SELECT COUNT(*) FROM links WHERE kind = 'shared'").fetchone()[0] == 1
        assert raw.execute("SELECT COUNT(*) FROM ledger_groups").fetchone()[0] == 0


def test_the_migration_runs_once(path: Path) -> None:
    with closing(db.connect(path)) as conn, conn:
        cafe = next(m for t, m in _fps(conn).items() if t.startswith("CAFE FICTICIO"))
        old_group(conn, cafe.fingerprint, people=2, with_whom="Ana")
    _as_v18(path)
    db.connect(path).close()
    with closing(db.connect(path)) as again:
        assert len(groups_summary(again)) == 1


def test_the_check_script_reports_ok_on_a_copy(path: Path) -> None:
    with closing(db.connect(path)) as conn, conn:
        _random_groups(conn, 4)
    _as_v18(path)
    script = Path(__file__).resolve().parent.parent / "scripts" / "check_shared_migration.py"
    done = subprocess.run(
        [sys.executable, str(script), str(path), "--figures"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "RESULT: OK" in done.stdout and "DIFF" not in done.stdout
    again = subprocess.run(
        [sys.executable, str(script), str(path)], capture_output=True, text=True, check=False
    )
    assert again.returncode == 2  # already migrated: it asks for a fresh copy


def test_split_names() -> None:
    assert migrations_v19.split_names("Ana y Luis, Pedro & Rosa") == [
        "Ana",
        "Luis",
        "Pedro",
        "Rosa",
    ]
    assert migrations_v19.split_names("  ana Y Ana ") == ["ana"]
    assert migrations_v19.split_names("") == []
    assert migrations_v19.split_names("Yolanda") == ["Yolanda"]
