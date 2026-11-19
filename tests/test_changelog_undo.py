"""The change log's "Undo" against what changed afterwards: a parent (link or category) that no
longer exists or whose id another one inherited, a rehearsal that would clash with or cascade-delete
another entry's rows, and the domain rules (investments, categories only their link sets)."""

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import cash_box_store, catalog, changelog, corrections, links
from michelito.analysis import categories as cat

EXPENSE = "a1b2c3d4e5f6a1b2c3d4e5f6"
CREDIT = "b1b2c3d4e5f6a1b2c3d4e5f6"
OTHER = "c1b2c3d4e5f6a1b2c3d4e5f6"
D = Decimal


@pytest.fixture
def conn(tmp_path: Path):
    with closing(db.connect(tmp_path / "michelito.db")) as connection:
        yield connection


def _tracked(conn: sqlite3.Connection, kind: str, action, *args, **kwargs) -> int:
    with conn, changelog.track(conn, kind, "link", "x", "X") as draft:
        action(conn, *args, **kwargs)
    assert draft.entry_id is not None
    return draft.entry_id


def _state(conn: sqlite3.Connection, entry_id: int, days=None) -> changelog.UndoState:
    return changelog.undo_state(conn, changelog.get(conn, entry_id), days=days)


def _group(conn: sqlite3.Connection) -> int:
    with conn:
        links.set_shared(conn, EXPENSE, D(100), for_other=True, with_whom="Ana")
        group = links.group_of(conn, EXPENSE)
        links.add_reimbursement(conn, group, CREDIT)
    return group


def _members(conn: sqlite3.Connection) -> list[tuple]:
    return [tuple(r) for r in conn.execute("SELECT link_id, fingerprint, role FROM link_members")]


@pytest.mark.parametrize("reused", [False, True])
def test_a_reimbursement_never_returns_to_another_group(conn, reused: bool) -> None:
    group = _group(conn)
    removed = _tracked(conn, "shared", links.remove_reimbursement, group, CREDIT)
    deleted = _tracked(conn, "shared", links.unshare, EXPENSE)
    with conn:
        if reused:  # a database from before schema 15 reused the deleted id
            conn.execute(
                "INSERT INTO links (id, kind, with_whom, created_at, updated_at) "
                "VALUES (?, 'shared', 'Other', 'another date', 'another date')",
                (group,),
            )
        else:
            links.set_shared(conn, OTHER, D(50), people=2, with_whom="Other")
    if not reused:
        assert links.group_of(conn, OTHER) != group  # AUTOINCREMENT: the id is not inherited
    state = _state(conn, removed)
    assert (state.allowed, state.blocked_by) == (False, deleted)
    assert f"vínculo n.º {group}" in state.message  # spanish-ui
    assert f"n.º {deleted}" in state.message
    before = _members(conn)
    with pytest.raises(changelog.UndoBlocked), conn:
        changelog.undo(conn, removed)
    assert _members(conn) == before


@pytest.mark.parametrize("reused", [False, True])
def test_a_correction_never_returns_to_a_category_that_inherited_the_id(conn, reused: bool) -> None:
    with conn:
        orders = catalog.create(conn, "Orders", "expense")
        corrections.set_transaction_category(conn, EXPENSE, orders.id)
    with conn, changelog.track(conn, "category", "transaction", EXPENSE, "X") as moved:
        corrections.set_transaction_category(conn, EXPENSE, cat.RESTAURANTS)
    deleted = _tracked(conn, "category_deleted", catalog.delete, orders.id, None)
    with conn:
        if reused:
            conn.execute(
                "INSERT INTO categories (id, name, kind, created_at) "
                "VALUES (?, 'Gym', 'expense', 'another date')",
                (orders.id,),
            )
        else:
            assert catalog.create(conn, "Gym", "expense").id != orders.id
    state = _state(conn, moved.entry_id)
    assert (state.allowed, state.blocked_by) == (False, deleted)
    assert f"categoría n.º {orders.id}" in state.message  # spanish-ui
    # Undoing the deletion first (with no other category holding its id) brings the category back,
    # and then it can be undone.
    if not reused:
        with conn:
            changelog.undo(conn, deleted)
        assert _state(conn, moved.entry_id).allowed


def test_a_first_store_in_the_box_waits_for_a_later_deposit(conn) -> None:
    stored = _tracked(conn, "cash_box", cash_box_store.store, EXPENSE)
    deposit = _tracked(conn, "cash_box", cash_box_store.deposit, CREDIT, None, None)
    # Undoing the first store would delete the box and, cascading, the deposit.
    state = _state(conn, stored)
    assert (state.allowed, state.blocked_by) == (False, deposit)
    assert "entrada posterior" in state.message  # spanish-ui
    assert len(_members(conn)) == 2  # the rehearsal left nothing behind
    with conn:
        changelog.undo(conn, deposit)
    assert _state(conn, stored).allowed


def test_a_credit_that_moved_to_another_link_blocks_its_undo(conn) -> None:
    group = _group(conn)
    removed = _tracked(conn, "shared", links.remove_reimbursement, group, CREDIT)

    def other_group(conn: sqlite3.Connection) -> None:
        links.set_shared(conn, OTHER, D(50), people=2)
        links.add_reimbursement(conn, links.group_of(conn, OTHER), CREDIT)

    moved = _tracked(conn, "shared", other_group)
    state = _state(conn, removed)
    assert (state.allowed, state.blocked_by) == (False, moved)
    assert "otro vínculo" in state.message  # spanish-ui


def test_an_investment_never_keeps_a_return_before_its_first_contribution(conn) -> None:
    days = {EXPENSE: date(2026, 1, 10), OTHER: date(2026, 1, 1), CREDIT: date(2026, 1, 5)}
    with conn:
        made = links.create_investment(conn, EXPENSE, with_whom="Partner")
    early = _tracked(
        conn, "investment", links.add_investment_member, made, OTHER, "contribution", D(100)
    )
    paid = _tracked(conn, "investment", links.add_investment_member, made, CREDIT, "return", D(5))
    # Without contribution B on day 1, the return on day 5 would come before the first
    # contribution (day 10).
    state = _state(conn, early, days)
    assert (state.allowed, state.blocked_by) == (False, paid)
    assert "anterior a su primer aporte (2026-01-10)" in state.message  # spanish-ui
    with pytest.raises(changelog.UndoBlocked), conn:
        changelog.undo(conn, early, days)
    assert len(_members(conn)) == 3
    with conn:
        changelog.undo(conn, paid, days)
    assert _state(conn, early, days).allowed


def test_a_link_only_category_is_not_restored_by_hand(conn) -> None:
    with conn:  # an older correction, to a category that today only its link sets
        corrections.set_transaction_category(conn, EXPENSE, cat.CASH_BOX)
    with conn, changelog.track(conn, "category", "transaction", EXPENSE, "X") as moved:
        corrections.set_transaction_category(conn, EXPENSE, cat.RESTAURANTS)
    state = _state(conn, moved.entry_id)
    assert not state.allowed and "solo la pone su vínculo" in state.message  # spanish-ui


def test_the_rehearsal_leaves_nothing_behind(conn) -> None:
    group = _group(conn)
    removed = _tracked(conn, "shared", links.remove_reimbursement, group, CREDIT)
    before = _members(conn)
    assert _state(conn, removed).allowed
    assert _members(conn) == before and not conn.in_transaction
