"""Schema 23 (the cash account): migrating existing data changes no figure.

The invariant: spending, income and the cash balances are identical before and after the step.
"Before" comes from `fixtures/schema_v17_expected.json` (what an earlier release read from
`fixtures/schema_v17.sql`, which has a cash box with entries, a withdrawal stored by hand and
others that were not); "after" is the same database migrated by this code, also after the
board's automatic pass (`cash_activation.refresh`), which must not touch anything recorded
before the upgrade.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db, migrations_v23
from michelito.analysis import (
    cash_activation,
    cash_box,
    cash_box_store,
    links,
    providers,
    rates,
    spending,
)
from michelito.analysis.accounts import CASH_BOX_KEY
from tests import e2e_server as e2e

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "schema_v17_expected.json").read_text(encoding="utf-8"))
Totals = dict[tuple[str, str, str], Decimal]


@pytest.fixture(autouse=True)
def _demo_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    known = {p.key for p in providers.PROVIDERS}
    extra = tuple(p for p in e2e.DEMO_PROVIDERS if p.key not in known)
    monkeypatch.setattr(providers, "PROVIDERS", (*providers.PROVIDERS, *extra))


@pytest.fixture
def migrated(tmp_path: Path) -> Path:
    path = tmp_path / "v17.db"
    with closing(sqlite3.connect(path)) as raw:
        raw.executescript((FIXTURES / "schema_v17.sql").read_text(encoding="utf-8"))
    with closing(db.connect(path)):
        pass
    return path


def _expected_totals() -> Totals:
    found: Totals = defaultdict(Decimal)
    for day, kind, amount, currency, *_ in EXPECTED["movements"].values():
        found[(day[:7], kind, currency)] += Decimal(amount)
    return dict(found)


def _totals(movements: tuple[spending.Movement, ...]) -> Totals:
    found: Totals = defaultdict(Decimal)
    for move in movements:
        found[(move.month, move.kind, move.currency)] += move.amount
    return dict(found)


def _expected_balances() -> dict[str, Decimal]:
    """Entries of the fixture (read straight from its SQL rows) plus the movements linked to
    the box (stored withdrawals in, deposits out), each in its currency."""
    with closing(sqlite3.connect(":memory:")) as raw:
        raw.executescript((FIXTURES / "schema_v17.sql").read_text(encoding="utf-8"))
        rows = raw.execute("SELECT kind, amount_cents, currency FROM cash_entries").fetchall()
    found: dict[str, Decimal] = defaultdict(Decimal)
    for kind, cents, currency in rows:
        found[currency] += Decimal(-cents if kind == "expense" else cents) / 100
    for _day, _kind, amount, currency, *_rest, link, _account in EXPECTED["movements"].values():
        if link == "cash_box":
            found[currency] += Decimal(amount)
    return dict(found)


def _balances(conn: sqlite3.Connection, flow: tuple[spending.Movement, ...]) -> dict[str, Decimal]:
    box = next(b for b in links.load(conn).cash_boxes if b.account_key == CASH_BOX_KEY)
    state = cash_box.state_of(
        box, cash_box_store.load_entries(conn), flow, rates.load(conn), today=date.today()
    )
    return dict(state.balances)


def test_spending_income_and_balances_are_identical(migrated: Path) -> None:
    with closing(db.connect(migrated)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 22
        flow = spending.load_all(conn, ())
        assert _totals(flow) == _expected_totals()
        assert _balances(conn, flow) == _expected_balances()
        # The board's pass on the day of the upgrade (and later ones) leaves them as they were.
        for day in (date.today(), date.today() + timedelta(days=40)):
            cash_activation.refresh(conn, day, lambda c, d=day: spending.load_all(c, (), None, d))
            after = spending.load_all(conn, (), None, day)
            assert _totals(after) == _expected_totals()
            assert _balances(conn, after) == _expected_balances()


def test_an_existing_box_is_activated_from_tomorrow_and_renamed(migrated: Path) -> None:
    with closing(db.connect(migrated)) as conn:
        assert cash_activation.activated_on(conn) == date.today() + timedelta(days=1)
        name = conn.execute("SELECT name FROM accounts WHERE key = ?", (CASH_BOX_KEY,)).fetchone()
        assert name[0] == migrations_v23.NEW_ACCOUNT_NAME
        renamed = conn.execute(
            "SELECT name FROM categories WHERE builtin_key = 'CASH_BOX'"
        ).fetchone()
        assert renamed[0] == migrations_v23.NEW_CATEGORY_NAME
        new = conn.execute(
            "SELECT COUNT(*) FROM cash_entries WHERE concept IS NOT NULL OR schedule_id IS NOT "
            "NULL OR occurrence_day IS NOT NULL OR status IS NOT NULL"
        ).fetchone()[0]
        assert new == 0


def test_the_step_is_idempotent_and_keeps_a_renamed_category(migrated: Path) -> None:
    with closing(db.connect(migrated)) as conn, conn:
        conn.execute("UPDATE categories SET name = 'Mine' WHERE builtin_key = 'CASH_BOX'")
        conn.execute("DELETE FROM cash_settings")
        conn.execute("PRAGMA user_version = 21")
    with closing(db.connect(migrated)) as conn:
        assert (
            conn.execute("SELECT name FROM categories WHERE builtin_key = 'CASH_BOX'").fetchone()[0]
            == "Mine"
        )
        assert cash_activation.activated_on(conn) == date.today() + timedelta(days=1)
        assert _totals(spending.load_all(conn, ())) == _expected_totals()


def test_an_unused_database_is_not_activated(tmp_path: Path) -> None:
    with closing(db.connect(tmp_path / "fresh.db")) as conn:
        assert cash_activation.activated_on(conn) is None


# --- From schema 22 (Shared's exchange leftovers and dismissals) and from 21 ---------------

_TO_SCHEMA_22 = (
    "BEGIN;"
    "DROP INDEX cash_entries_occurrence;"
    + "".join(
        f"DROP TABLE {table};"
        for table in (
            "cash_schedules",
            "cash_skips",
            "cash_spent_direct",
            "cash_reconciliations",
            "cash_auto_marks",
            "cash_renames",
            "cash_settings",
        )
    )
    + "".join(
        f"ALTER TABLE cash_entries DROP COLUMN {name};" for name, _ in migrations_v23.ENTRY_COLUMNS
    )
    + "UPDATE accounts SET name = 'Caja fuerte' WHERE key = 'manual:cash-box';"  # spanish-data
    + "UPDATE categories SET name = 'Caja fuerte' WHERE builtin_key = 'CASH_BOX';"  # spanish-data
    + "PRAGMA user_version = 22;"
    "COMMIT;"
)


def _cash_and_shared(path: Path) -> None:
    from tests import test_schema_v22 as v22
    from tests.test_schema_v21 import _ledger

    with closing(db.connect(path)) as conn:
        _ledger(conn)
        v22._cover_group(conn)
        with conn:
            cash_box_store.add_entry(conn, "initial", date(2025, 12, 1), Decimal(200), "USD")
            cash_box_store.add_entry(conn, "expense", date(2026, 1, 5), Decimal(50), "USD")
            payment = conn.execute("SELECT MIN(id) FROM ledger_payments").fetchone()[0]
            conn.execute(
                "INSERT INTO ledger_dismissals (payment_id, dismissed_at) VALUES (?, 'x')",
                (payment,),
            )
            conn.execute(
                "UPDATE ledger_members SET leftover_settled = 0 WHERE rowid = "
                "(SELECT MIN(rowid) FROM ledger_members)"
            )


def _everything(conn: sqlite3.Connection) -> tuple:
    from tests import test_schema_v22 as v22

    flow = spending.load_all(conn, ())
    entries = [tuple(r) for r in conn.execute("SELECT kind, day, amount_cents FROM cash_entries")]
    shared = [
        tuple(r)
        for r in conn.execute(
            "SELECT group_id, contact_id, leftover_settled FROM ledger_members "
            "ORDER BY group_id, contact_id"
        )
    ]
    dismissed = [tuple(r) for r in conn.execute("SELECT payment_id FROM ledger_dismissals")]
    return _totals(flow), entries, shared, dismissed, v22._figures(conn)


@pytest.mark.parametrize("start", [22, 21])
def test_schema_22_and_21_migrate_to_23_with_identical_figures(tmp_path: Path, start: int) -> None:
    """The same data built at schema 23 (no migration) is the reference: migrating it from 22
    (with Shared's dismissals and leftover toggles) or from 21 gives the same spending, income,
    cash entries and ledger figures; from 21 the toggles come back on and there are no
    dismissals (that is all 21 knew)."""
    reference = tmp_path / "reference.db"
    _cash_and_shared(reference)
    with closing(db.connect(reference)) as conn:
        expected = _everything(conn)
    path = tmp_path / "michelito.db"
    _cash_and_shared(path)
    with closing(sqlite3.connect(path)) as raw:
        raw.executescript(_TO_SCHEMA_22)
        if start == 21:
            raw.executescript(
                "BEGIN; DROP TABLE ledger_dismissals;"
                "ALTER TABLE ledger_members DROP COLUMN leftover_settled;"
                "PRAGMA user_version = 21; COMMIT;"
            )
    with closing(db.connect(path)) as conn:
        assert db.SCHEMA_VERSION >= 23  # noqa: PLR2004 (later schemas only add to it)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert cash_activation.activated_on(conn) == date.today() + timedelta(days=1)
        assert conn.execute("SELECT COUNT(*) FROM cash_renames").fetchone()[0] == 3
        totals, entries, shared, dismissed, ledger_figures = _everything(conn)
    assert (totals, entries) == expected[:2]
    if start == 22:
        assert (shared, dismissed, ledger_figures) == expected[2:]
    else:
        assert shared == [(group, person, 1) for group, person, _ in expected[2]]
        assert dismissed == []
