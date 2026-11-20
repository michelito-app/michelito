"""Change log: pure logic (sessions, undo, possible rules) and recording in the database (no
HTTP)."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import catalog, changelog, corrections, ledger_store
from michelito.analysis import categories as cat
from michelito.analysis.changelog_rules import (
    CategoryEdit,
    Change,
    can_undo,
    changed_columns,
    describe,
    rule_suggestions,
    sessions,
    undone_ids,
)
from tests.ledger_helpers import pay, share

T0 = datetime(2026, 2, 20, 18, 40, tzinfo=UTC)
FP = "a1b2c3d4e5f6a1b2c3d4e5f6"  # a statement fingerprint (24 hex digits)
CASH = "cash-7"  # a hand-entered cash box fingerprint


@pytest.fixture
def conn(tmp_path: Path):
    with closing(db.connect(tmp_path / "michelito.db")) as connection:
        yield connection


def _cat(conn: sqlite3.Connection, ref: str) -> int:
    return catalog.resolve_ref(conn, ref)


# --- Pure logic ----------------------------------------------------------------------------


def test_sessions_cut_after_30_minutes_without_changes() -> None:
    stamps = [
        (1, T0),
        (2, T0 + timedelta(minutes=10)),
        (3, T0 + timedelta(minutes=40)),  # exactly 30 min after 2: same session
        (4, T0 + timedelta(minutes=71)),  # 31 min later: another
    ]
    found = sessions(stamps)
    assert [(s.ids, s.count) for s in found] == [((4,), 1), ((3, 2, 1), 3)]
    assert (found[1].start, found[1].end) == (T0, T0 + timedelta(minutes=40))
    assert sessions([]) == []


def test_undone_ids_ignores_an_undo_that_was_undone() -> None:
    # 5 undoes 1; 6 undoes 5 (applies 1 again); 7 undoes 2.
    assert undone_ids({5: 1, 6: 5, 7: 2}) == {5, 2}
    assert undone_ids({}) == frozenset()


def test_soft_rows_compare_by_column_and_absent_means_defaults() -> None:
    after = {"fingerprint": FP, "category_id": 3, "one_off": 0, "note": None, "updated_at": "x"}
    assert changed_columns("transaction_notes", None, after) == ("category_id",)
    change = Change("transaction_notes", {"fingerprint": FP}, None, after, ("category_id",))
    # Another column of the same row (the note) changed later: it does not block undoing the
    # category.
    assert can_undo([change], {change.row_key: {**after, "note": "with Ana"}})
    assert not can_undo([change], {change.row_key: {**after, "category_id": 4}})
    assert not can_undo([change], {change.row_key: None})


def test_a_row_needs_to_exist_as_it_was_left() -> None:
    row = {"merchant": "UBER EATS", "category_id": 3, "updated_at": "x"}
    made = Change("merchant_categories", {"merchant": "UBER EATS"}, None, row, ("merchant",))
    assert can_undo(
        [made], {made.row_key: {**row, "updated_at": "y"}}
    )  # the timestamp does not count
    assert not can_undo([made], {made.row_key: None})
    gone = Change("merchant_categories", {"merchant": "UBER EATS"}, row, None, ("category_id",))
    assert can_undo([gone], {gone.row_key: None})
    assert not can_undo([gone], {gone.row_key: row})
    assert not can_undo([], {})


def test_category_name_color_and_hidden_are_not_changes() -> None:
    before = {"id": 9, "name": "Travel", "kind": "expense", "color": None, "hidden": 0}
    assert changed_columns("categories", before, {**before, "name": "Trips", "hidden": 1}) == ()
    assert changed_columns("categories", before, {**before, "kind": "income"}) == ("kind",)


def _edit(entry_id: int, fp: str, category: int | None, merchant: str = "UBER EATS"):
    return CategoryEdit(entry_id, merchant, fp, category)


def test_rule_suggested_with_two_same_not_one_nor_contrary_nor_dismissed() -> None:
    two = [_edit(1, FP, 3), _edit(2, CASH, 3)]
    found = rule_suggestions(two, {}, set())
    assert [(s.merchant, s.category_id, s.fingerprints) for s in found] == [
        ("UBER EATS", 3, (CASH, FP))
    ]
    assert rule_suggestions(two[:1], {}, set()) == []
    assert rule_suggestions([_edit(1, FP, 3), _edit(2, FP, 3)], {}, set()) == []  # the same one
    assert rule_suggestions([*two, _edit(3, "other", 4)], {}, set()) == []  # contrary
    assert rule_suggestions([*two, _edit(3, "other", None)], {}, set()) == []  # back to automatic
    assert rule_suggestions(two, {"UBER EATS": 3}, set()) == []  # that rule already exists
    assert rule_suggestions(two, {}, {("UBER EATS", 3)}) == []  # dismissed
    assert len(rule_suggestions(two, {"UBER EATS": 4}, set())) == 1  # a different rule: proposed


def test_describe_links_and_rows() -> None:
    member = {"link_id": 1, "fingerprint": FP, "role": "stored", "added_at": "x"}
    change = Change("link_members", {"link_id": 1, "fingerprint": FP}, None, member, ("role",))
    assert (describe([change], "before"), describe([change], "after")) == (
        "—",
        "guardado en la caja",  # spanish-ui
    )


# --- In the database --------------------------------------------------------------------------


def _note_category(conn: sqlite3.Connection, fp: str, ref: str | None) -> int | None:
    with conn, changelog.track(conn, "category", "transaction", fp, "UBER EATS") as draft:
        corrections.set_transaction_category(conn, fp, ref)
    return draft.entry_id


def test_track_records_before_and_after_in_the_same_transaction(conn) -> None:
    entry_id = _note_category(conn, FP, cat.RESTAURANTS)
    entry = changelog.get(conn, entry_id)
    (change,) = entry.changes
    assert (change.table, change.before, change.columns) == (
        "transaction_notes",
        None,
        ("category_id",),
    )
    assert change.after["category_id"] == _cat(conn, cat.RESTAURANTS)
    assert (entry.author, entry.fingerprints, entry.affected) == ("user", (FP,), 1)


def test_no_entry_without_a_real_change(conn) -> None:
    with conn, changelog.track(conn, "note", "transaction", FP, "X") as draft:
        corrections.set_note(conn, FP, "")  # there was no note
    assert draft.entry_id is None
    assert changelog.load(conn) == []


def test_a_failed_change_leaves_no_entry(conn) -> None:
    with pytest.raises(ValueError), conn, changelog.track(conn, "note", "transaction", FP, "X"):
        corrections.set_note(conn, FP, "fine")
        corrections.set_note(conn, FP, "x" * 501)  # fails: everything is rolled back
    assert changelog.load(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM transaction_notes").fetchone()[0] == 0


def test_undo_restores_and_is_its_own_entry(conn) -> None:
    first = _note_category(conn, CASH, cat.RESTAURANTS)
    with conn:
        corrections.set_note(conn, CASH, "outside the log")  # the other column stays
    with conn:
        made = changelog.undo(conn, first)
    row = conn.execute("SELECT category_id, note FROM transaction_notes").fetchone()
    assert tuple(row) == (None, "outside the log")
    undo = changelog.get(conn, made)
    assert undo.undoes == first and undo.kind == "category"
    assert changelog.undone(conn) == {first}
    state = changelog.undo_state(conn, changelog.get(conn, first))
    assert (state.allowed, state.undone) == (False, True)
    with conn:  # undoing the "Undo" applies the correction again
        changelog.undo(conn, made)
    assert conn.execute("SELECT category_id FROM transaction_notes").fetchone()[0] is not None
    assert changelog.undone(conn) == {made}


def test_undo_blocked_after_a_later_change_names_it(conn) -> None:
    first = _note_category(conn, FP, cat.RESTAURANTS)
    second = _note_category(conn, FP, cat.HOME)
    state = changelog.undo_state(conn, changelog.get(conn, first))
    assert (state.allowed, state.blocked_by) == (False, second)
    with pytest.raises(changelog.UndoBlocked), conn:
        changelog.undo(conn, first)
    with conn:
        changelog.undo(conn, second)
    assert changelog.undo_state(conn, changelog.get(conn, first)).allowed
    with conn:
        corrections.set_transaction_category(conn, FP, cat.GROCERIES)  # outside the change log
    later = changelog.undo_state(conn, changelog.get(conn, first))
    assert not later.allowed and "no queda en la bitácora" in later.message  # spanish-ui


def test_a_merchant_rule_undo_brings_back_the_previous_rule(conn) -> None:
    with conn:
        corrections.set_merchant_category(conn, "UBER EATS", cat.RESTAURANTS)
    with (
        conn,
        changelog.track(conn, "merchant_rule", "merchant", "UBER EATS", "UBER EATS") as draft,
    ):
        corrections.set_merchant_category(conn, "UBER EATS", cat.HOME)
    with conn, changelog.track(conn, "merchant_rule", "merchant", "UBER", "UBER") as new:
        corrections.set_merchant_category(conn, "UBER", cat.HOME)
    with conn:
        changelog.undo(conn, draft.entry_id)
        changelog.undo(conn, new.entry_id)
    rules = dict(conn.execute("SELECT merchant, category_id FROM merchant_categories").fetchall())
    assert rules == {
        "UBER EATS": _cat(conn, cat.RESTAURANTS)
    }  # the previous one; the new one, deleted


_LEDGER = (
    "contacts",
    "ledger_groups",
    "ledger_members",
    "ledger_entries",
    "ledger_splits",
    "ledger_payments",
    "ledger_links",
)


def _shared(conn: sqlite3.Connection, expense: str, credit: str) -> int:
    """A group of an expense "for someone else" with an imported payment and a hand-entered
    one."""
    from decimal import Decimal  # noqa: PLC0415

    with conn:
        group = share(conn, expense, Decimal("100.00"), for_other=True, with_whom="Ana")
        pay(conn, group, credit, amount=Decimal("30.00"), day=datetime(2026, 1, 8).date())
        pay(conn, group, amount=Decimal("20.00"), day=datetime(2026, 1, 9).date())
    return group


def _rows(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")] for t in _LEDGER}


def test_undo_of_deleting_a_group_restores_members_entries_and_payments(conn) -> None:
    group = _shared(conn, FP, CASH)
    before = _rows(conn)
    with conn, changelog.track(conn, "group", "link", f"group-{group}", "Ana") as draft:
        ledger_store.delete_group(conn, group)  # cascading
    assert conn.execute("SELECT COUNT(*) FROM ledger_links").fetchone()[0] == 0
    entry = changelog.get(conn, draft.entry_id)
    assert set(entry.fingerprints) == {FP, CASH}
    with conn:
        changelog.undo(conn, draft.entry_id)
    assert _rows(conn) == before


def test_undo_never_touches_rows_of_a_later_entry(conn) -> None:
    from decimal import Decimal  # noqa: PLC0415

    with conn, changelog.track(conn, "group_entry", "link", "group-new", "X") as made:
        group = share(conn, FP, Decimal("100.00"), people=2)
    with conn, changelog.track(conn, "group_entry", "link", f"group-{group}", "X") as joined:
        share(conn, CASH, Decimal("50.00"), people=2, group=group)
    # Undoing the creation would delete the group and, cascading, the expense added later.
    with pytest.raises(changelog.UndoBlocked), conn:
        changelog.undo(conn, made.entry_id)
    assert conn.execute("SELECT COUNT(*) FROM ledger_links").fetchone()[0] == 2
    with conn:
        changelog.undo(conn, joined.entry_id)
        changelog.undo(conn, made.entry_id)
    assert conn.execute("SELECT COUNT(*) FROM ledger_groups").fetchone()[0] == 0


def test_reason_is_trimmed_limited_and_not_a_change(conn) -> None:
    entry_id = _note_category(conn, FP, cat.RESTAURANTS)
    with conn:
        changelog.set_reason(conn, entry_id, "  Ana asked for it  ")
    assert changelog.get(conn, entry_id).reason == "Ana asked for it"
    with pytest.raises(ValueError):
        changelog.set_reason(conn, entry_id, "x" * 501)
    with pytest.raises(LookupError):
        changelog.set_reason(conn, 999, "x")
    with conn:
        changelog.set_reason(conn, entry_id, "")
    assert changelog.get(conn, entry_id).reason is None
    assert len(changelog.load(conn)) == 1


def test_category_edits_skip_undone_and_undo_entries(conn) -> None:
    first = _note_category(conn, FP, cat.RESTAURANTS)
    with conn:
        conn.execute("UPDATE change_log SET merchant = 'UBER EATS'")
    second = _note_category(conn, CASH, cat.RESTAURANTS)
    with conn:
        conn.execute("UPDATE change_log SET merchant = 'UBER EATS'")
        changelog.undo(conn, second)
    entries = changelog.load(conn)
    edits = changelog.category_edits(entries, changelog.undone(conn))
    assert [e.entry_id for e in edits] == [first]
