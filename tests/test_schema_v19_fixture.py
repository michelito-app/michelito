"""Schema 19 from a real schema 18 file: `fixtures/schema_v18_shared.sql` was written by the
schema 18 release itself (0be7009, see `fixtures/make_schema_v18_shared.py`), and
`schema_v18_shared_expected.json` holds the figures that release's own math computed. Opening it
migrates (table creation, the widened `review_marks` CHECK, AUTOINCREMENT sequences) and every
group must keep its figures, compared group by group through the old -> new id map. Also: the
frozen old math with hand-computed multi-currency figures, dormant links, old log entries that
can no longer be undone and splits stored exactly. Synthetic data only."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db, migrations_v19
from michelito.analysis import categories as cat
from michelito.analysis import changelog, ledger, ledger_store, rates, spending
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "schema_v18_shared_expected.json").read_text(encoding="utf-8"))


@pytest.fixture
def path(tmp_path: Path) -> Path:
    found = tmp_path / "v18.db"
    with closing(sqlite3.connect(found)) as raw:
        raw.executescript((FIXTURES / "schema_v18_shared.sql").read_text(encoding="utf-8"))
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 18
        sql = raw.execute("SELECT sql FROM sqlite_master WHERE name = 'review_marks'").fetchone()
        assert "possible_payment" not in sql[0]
        assert (
            raw.execute("SELECT name FROM sqlite_master WHERE name = 'contacts'").fetchone() is None
        )
    return found


def _mapping(conn: sqlite3.Connection) -> dict[int, int]:
    return dict(conn.execute("SELECT link_id, group_id FROM ledger_migration"))


def test_the_schema_18_file_migrates_with_every_figure_of_the_old_release(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 19
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'review_marks'").fetchone()
        assert "'possible_payment'" in sql[0] and "'possible_reserve'" in sql[0]
        sequences = dict(conn.execute("SELECT name, seq FROM sqlite_sequence"))
        assert {"contacts", "ledger_groups", "ledger_entries", "ledger_payments"} <= set(sequences)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        book = ledger_store.load(conn)
        states = ledger.states(book, rates.load(conn))
        mapping = _mapping(conn)
        assert set(mapping) == {int(i) for i in EXPECTED["ids"].values()}
        for old_id, figures in EXPECTED["groups"].items():
            state = states[mapping[int(old_id)]]
            found = {
                t.currency: [t.share, t.reimbursed, t.pending, t.written_off] for t in state.totals
            }
            expected = {c: [D(v) for v in values] for c, values in figures.items()}
            assert found == expected, old_id
        moves = {m.fingerprint: m for m in spending.load_all(conn)}
        for fp, (amount, link) in EXPECTED["movements"].items():
            assert (moves[fp].amount, moves[fp].link) == (D(amount), link), fp
        # The dormant group stays (archived) and its credit stays a reimbursement.
        for old_id in EXPECTED["dormant_groups"]:
            group = book.group(mapping[old_id])
            assert group is not None and group.archived and not group.entries


def test_attribution_only_with_one_person_and_no_excess(path: Path) -> None:
    ids = EXPECTED["ids"]
    with closing(db.connect(path)) as conn:
        book = ledger_store.load(conn)
        mapping = _mapping(conn)

        def froms(key: str) -> set[int | None]:
            group = book.group(mapping[ids[key]])
            assert group is not None
            return {p.from_contact for p in group.payments}

        assert froms("g1") == {None}  # "we were 3": two other people
        assert froms("g3") == {None}  # one person, but paid back in excess
        [luis] = froms("g4")  # one person, US$ and RD$ payments, no excess
        assert book.name(luis) == "Luis"


def test_links_that_counted_nothing_are_kept_dormant(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        assert migrations_v19.dormant_counts(conn) == {"expense": 1, "payment": 1}
        rows = dict(conn.execute("SELECT fingerprint, role FROM ledger_dormant"))
        assert rows["0f0f0f0f0f0f0f0f0f0f0f0f"] == "expense"
        # Zero effect: they are not links (the transaction can be shared again).
        from michelito.analysis import links  # noqa: PLC0415

        assert not any(links.load(conn).is_linked(fp) for fp in rows)


def test_old_log_entries_on_shared_groups_cannot_be_undone(path: Path) -> None:
    log = EXPECTED["log"]
    with closing(db.connect(path)) as conn:
        for entry_id in (log["made"], log["removed"]):
            entry = changelog.get(conn, entry_id)
            state = changelog.undo_state(conn, entry)
            assert not state.allowed
            assert "antes de la versión 19" in state.message  # spanish-ui
            with pytest.raises(changelog.UndoBlocked), conn:
                changelog.undo(conn, entry_id)
        # The removed manual reimbursement did not come back.
        assert conn.execute("SELECT COUNT(*) FROM link_manual").fetchone()[0] == 0


def test_migrated_splits_are_exact(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        book = ledger_store.load(conn)
        assert {e.split_mode for g in book.groups for e in g.entries} == {"exact"}


def test_the_check_script_counts_dormant_links(path: Path) -> None:
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    script = Path(__file__).resolve().parent.parent / "scripts" / "check_shared_migration.py"
    done = subprocess.run(
        [sys.executable, str(script), str(path)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 expense(s), 1 credit(s)" in done.stdout
    assert "old groups mapped to a new one: 6/6" in done.stdout
    assert "RESULT: OK" in done.stdout


# --- The frozen old math, by hand -----------------------------------------------------------


def _move(fp: str, day: str, amount: str, currency: str) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=fp,
        description=fp,
        category=cat.TRAVEL,
        amount=D(amount),
        currency=currency,
        institution="x",
        fingerprint=fp,
    )


def test_the_old_math_with_hand_computed_multi_currency_figures() -> None:
    """A US$ 100 hotel among 2 (US$ 50 owed) and a RD$ 3,000 dinner among 3 (RD$ 2,000 owed);
    RD$ 1,240 in February at 62 (US$ 20 for the hotel), then RD$ 4,000 in February: US$ 30 =
    RD$ 1,860 finish the hotel and the RD$ 2,140 left go to the dinner (RD$ 2,000) with RD$ 140
    in excess."""
    rates_ = {"2026-01": Rate(D("60"), "2026-01", "bcrd"), "2026-02": Rate(D("62"), "2026-02", "x")}
    hotel = _move("hotel", "2026-01-10", "100", "USD")
    dinner = _move("dinner", "2026-01-20", "3000", "DOP")
    group = migrations_v19.LegacyGroup(
        1,
        (
            migrations_v19.LegacyExpense("hotel", people=2),
            migrations_v19.LegacyExpense("dinner", people=3),
        ),
        manual=(
            migrations_v19.LegacyManual(1, D(1240), date(2026, 2, 5), "DOP"),
            migrations_v19.LegacyManual(2, D(4000), date(2026, 2, 9), "DOP"),
        ),
    )
    state = migrations_v19.legacy_state(group, {"hotel": hotel, "dinner": dinner}, rates_)
    assert state is not None
    assert state.totals() == {
        "DOP": (D("1000.00"), D(2000), D(0), D(0)),
        "USD": (D("50.00"), D("50.00"), D(0), D(0)),
    }
    assert state.excess == (("DOP", D("140.00")),) and state.leftover
    # With only January's rate, February uses the closest earlier month (60).
    january = {"2026-01": Rate(D("60"), "2026-01", "bcrd")}
    state = migrations_v19.legacy_state(group, {"hotel": hotel, "dinner": dinner}, january)
    assert state is not None
    assert state.expenses[0].reimbursed == D("50.00")
    assert migrations_v19.legacy_convert(D(1240), "DOP", "USD", date(2026, 2, 5), january) == D(
        "20.67"
    )
    assert migrations_v19.legacy_convert(D(10), "USD", "DOP", date(2025, 1, 5), january) is None
