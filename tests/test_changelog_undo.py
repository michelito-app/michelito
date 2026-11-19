"""«Deshacer» de la bitácora frente a lo que cambió después: una madre (vínculo o categoría) que
ya no existe o cuyo id heredó otra, un ensayo que chocaría o borraría en cascada lo de otra
entrada, y las reglas de dominio (inversiones, categorías que solo pone su vínculo)."""

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzas import db
from finanzas.analysis import cash_box_store, catalog, changelog, corrections, links
from finanzas.analysis import categories as cat

EXPENSE = "a1b2c3d4e5f6a1b2c3d4e5f6"
CREDIT = "b1b2c3d4e5f6a1b2c3d4e5f6"
OTHER = "c1b2c3d4e5f6a1b2c3d4e5f6"
D = Decimal


@pytest.fixture
def conn(tmp_path: Path):
    with closing(db.connect(tmp_path / "finanzas.db")) as connection:
        yield connection


def _tracked(conn: sqlite3.Connection, kind: str, action, *args, **kwargs) -> int:
    with conn, changelog.track(conn, kind, "vinculo", "x", "X") as draft:
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
    removed = _tracked(conn, "compartido", links.remove_reimbursement, group, CREDIT)
    deleted = _tracked(conn, "compartido", links.unshare, EXPENSE)
    with conn:
        if reused:  # una base de antes del esquema 15 reusaba el id borrado
            conn.execute(
                "INSERT INTO links (id, kind, with_whom, created_at, updated_at) "
                "VALUES (?, 'shared', 'Otro', 'otra fecha', 'otra fecha')",
                (group,),
            )
        else:
            links.set_shared(conn, OTHER, D(50), people=2, with_whom="Otro")
    if not reused:
        assert links.group_of(conn, OTHER) != group  # AUTOINCREMENT: no hereda el id
    state = _state(conn, removed)
    assert (state.allowed, state.blocked_by) == (False, deleted)
    assert f"vínculo n.º {group}" in state.message and f"n.º {deleted}" in state.message
    before = _members(conn)
    with pytest.raises(changelog.UndoBlocked), conn:
        changelog.undo(conn, removed)
    assert _members(conn) == before


@pytest.mark.parametrize("reused", [False, True])
def test_a_correction_never_returns_to_a_category_that_inherited_the_id(conn, reused: bool) -> None:
    with conn:
        orders = catalog.create(conn, "Pedidos", "gasto")
        corrections.set_transaction_category(conn, EXPENSE, orders.id)
    with conn, changelog.track(conn, "categoria", "transaccion", EXPENSE, "X") as moved:
        corrections.set_transaction_category(conn, EXPENSE, cat.RESTAURANTS)
    deleted = _tracked(conn, "categoria_borrada", catalog.delete, orders.id, None)
    with conn:
        if reused:
            conn.execute(
                "INSERT INTO categories (id, name, kind, created_at) "
                "VALUES (?, 'Gimnasio', 'gasto', 'otra fecha')",
                (orders.id,),
            )
        else:
            assert catalog.create(conn, "Gimnasio", "gasto").id != orders.id
    state = _state(conn, moved.entry_id)
    assert (state.allowed, state.blocked_by) == (False, deleted)
    assert f"categoría n.º {orders.id}" in state.message
    # Deshacer el borrado primero (sin la otra con su id) devuelve la categoría y entonces sí.
    if not reused:
        with conn:
            changelog.undo(conn, deleted)
        assert _state(conn, moved.entry_id).allowed


def test_a_first_store_in_the_box_waits_for_a_later_deposit(conn) -> None:
    stored = _tracked(conn, "caja_fuerte", cash_box_store.store, EXPENSE)
    deposit = _tracked(conn, "caja_fuerte", cash_box_store.deposit, CREDIT, None, None)
    # Deshacer el primer guardado borraría la caja y, en cascada, el depósito.
    state = _state(conn, stored)
    assert (state.allowed, state.blocked_by) == (False, deposit)
    assert "entrada posterior" in state.message
    assert len(_members(conn)) == 2  # el ensayo no dejó nada
    with conn:
        changelog.undo(conn, deposit)
    assert _state(conn, stored).allowed


def test_a_credit_that_moved_to_another_link_blocks_its_undo(conn) -> None:
    group = _group(conn)
    removed = _tracked(conn, "compartido", links.remove_reimbursement, group, CREDIT)

    def other_group(conn: sqlite3.Connection) -> None:
        links.set_shared(conn, OTHER, D(50), people=2)
        links.add_reimbursement(conn, links.group_of(conn, OTHER), CREDIT)

    moved = _tracked(conn, "compartido", other_group)
    state = _state(conn, removed)
    assert (state.allowed, state.blocked_by) == (False, moved)
    assert "otro vínculo" in state.message


def test_an_investment_never_keeps_a_return_before_its_first_contribution(conn) -> None:
    days = {EXPENSE: date(2026, 1, 10), OTHER: date(2026, 1, 1), CREDIT: date(2026, 1, 5)}
    with conn:
        made = links.create_investment(conn, EXPENSE, with_whom="Socio")
    early = _tracked(
        conn, "inversion", links.add_investment_member, made, OTHER, "contribution", D(100)
    )
    paid = _tracked(conn, "inversion", links.add_investment_member, made, CREDIT, "return", D(5))
    # Sin el aporte B del día 1, el cobro del 5 quedaría antes del primer aporte (el 10).
    state = _state(conn, early, days)
    assert (state.allowed, state.blocked_by) == (False, paid)
    assert "anterior a su primer aporte (2026-01-10)" in state.message
    with pytest.raises(changelog.UndoBlocked), conn:
        changelog.undo(conn, early, days)
    assert len(_members(conn)) == 3
    with conn:
        changelog.undo(conn, paid, days)
    assert _state(conn, early, days).allowed


def test_a_link_only_category_is_not_restored_by_hand(conn) -> None:
    with conn:  # una corrección de antes, a una categoría que hoy solo pone su vínculo
        corrections.set_transaction_category(conn, EXPENSE, cat.CASH_BOX)
    with conn, changelog.track(conn, "categoria", "transaccion", EXPENSE, "X") as moved:
        corrections.set_transaction_category(conn, EXPENSE, cat.RESTAURANTS)
    state = _state(conn, moved.entry_id)
    assert not state.allowed and "solo la pone su vínculo" in state.message


def test_the_rehearsal_leaves_nothing_behind(conn) -> None:
    group = _group(conn)
    removed = _tracked(conn, "compartido", links.remove_reimbursement, group, CREDIT)
    before = _members(conn)
    assert _state(conn, removed).allowed
    assert _members(conn) == before and not conn.in_transaction
