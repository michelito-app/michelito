"""Bitácora: lógica pura (sesiones, deshacer, reglas posibles) y registro en la base (sin HTTP)."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from finanzas import db
from finanzas.analysis import catalog, changelog, corrections, links
from finanzas.analysis import categories as cat
from finanzas.analysis.changelog_rules import (
    CategoryEdit,
    Change,
    can_undo,
    changed_columns,
    describe,
    rule_suggestions,
    sessions,
    undone_ids,
)

T0 = datetime(2026, 2, 20, 18, 40, tzinfo=UTC)
FP = "a1b2c3d4e5f6a1b2c3d4e5f6"  # una huella de un estado (24 hexadecimales)
CAJA = "caja-7"  # una huella a mano de la caja fuerte


@pytest.fixture
def conn(tmp_path: Path):
    with closing(db.connect(tmp_path / "finanzas.db")) as connection:
        yield connection


def _cat(conn: sqlite3.Connection, ref: str) -> int:
    return catalog.resolve_ref(conn, ref)


# --- Lógica pura ---------------------------------------------------------------------------


def test_sessions_cut_after_30_minutes_without_changes() -> None:
    stamps = [
        (1, T0),
        (2, T0 + timedelta(minutes=10)),
        (3, T0 + timedelta(minutes=40)),  # 30 min justos después del 2: misma sesión
        (4, T0 + timedelta(minutes=71)),  # 31 min después: otra
    ]
    found = sessions(stamps)
    assert [(s.ids, s.count) for s in found] == [((4,), 1), ((3, 2, 1), 3)]
    assert (found[1].start, found[1].end) == (T0, T0 + timedelta(minutes=40))
    assert sessions([]) == []


def test_undone_ids_ignores_an_undo_that_was_undone() -> None:
    # 5 deshace a 1; 6 deshace a 5 (vuelve a aplicar 1); 7 deshace a 2.
    assert undone_ids({5: 1, 6: 5, 7: 2}) == {5, 2}
    assert undone_ids({}) == frozenset()


def test_soft_rows_compare_by_column_and_absent_means_defaults() -> None:
    after = {"fingerprint": FP, "category_id": 3, "one_off": 0, "note": None, "updated_at": "x"}
    assert changed_columns("transaction_notes", None, after) == ("category_id",)
    change = Change("transaction_notes", {"fingerprint": FP}, None, after, ("category_id",))
    # Otra columna de la misma fila (la nota) cambió después: no bloquea deshacer la categoría.
    assert can_undo([change], {change.row_key: {**after, "note": "con Ana"}})
    assert not can_undo([change], {change.row_key: {**after, "category_id": 4}})
    assert not can_undo([change], {change.row_key: None})


def test_a_row_needs_to_exist_as_it_was_left() -> None:
    row = {"merchant": "UBER EATS", "category_id": 3, "updated_at": "x"}
    made = Change("merchant_categories", {"merchant": "UBER EATS"}, None, row, ("merchant",))
    assert can_undo([made], {made.row_key: {**row, "updated_at": "y"}})  # el tiempo no cuenta
    assert not can_undo([made], {made.row_key: None})
    gone = Change("merchant_categories", {"merchant": "UBER EATS"}, row, None, ("category_id",))
    assert can_undo([gone], {gone.row_key: None})
    assert not can_undo([gone], {gone.row_key: row})
    assert not can_undo([], {})


def test_category_name_color_and_hidden_are_not_changes() -> None:
    before = {"id": 9, "name": "Viajes", "kind": "gasto", "color": None, "hidden": 0}
    assert changed_columns("categories", before, {**before, "name": "Paseos", "hidden": 1}) == ()
    assert changed_columns("categories", before, {**before, "kind": "ingreso"}) == ("kind",)


def _edit(entry_id: int, fp: str, category: int | None, merchant: str = "UBER EATS"):
    return CategoryEdit(entry_id, merchant, fp, category)


def test_rule_suggested_with_two_same_not_one_nor_contrary_nor_dismissed() -> None:
    two = [_edit(1, FP, 3), _edit(2, CAJA, 3)]
    found = rule_suggestions(two, {}, set())
    assert [(s.merchant, s.category_id, s.fingerprints) for s in found] == [
        ("UBER EATS", 3, (CAJA, FP))
    ]
    assert rule_suggestions(two[:1], {}, set()) == []
    assert rule_suggestions([_edit(1, FP, 3), _edit(2, FP, 3)], {}, set()) == []  # la misma
    assert rule_suggestions([*two, _edit(3, "otra", 4)], {}, set()) == []  # contraria
    assert rule_suggestions([*two, _edit(3, "otra", None)], {}, set()) == []  # a la automática
    assert rule_suggestions(two, {"UBER EATS": 3}, set()) == []  # ya hay esa regla
    assert rule_suggestions(two, {}, {("UBER EATS", 3)}) == []  # descartada
    assert len(rule_suggestions(two, {"UBER EATS": 4}, set())) == 1  # otra regla: se propone


def test_describe_links_and_rows() -> None:
    member = {"link_id": 1, "fingerprint": FP, "role": "stored", "added_at": "x"}
    change = Change("link_members", {"link_id": 1, "fingerprint": FP}, None, member, ("role",))
    assert (describe([change], "before"), describe([change], "after")) == (
        "—",
        "guardado en la caja",
    )


# --- En la base -----------------------------------------------------------------------------


def _note_category(conn: sqlite3.Connection, fp: str, ref: str | None) -> int | None:
    with conn, changelog.track(conn, "categoria", "transaccion", fp, "UBER EATS") as draft:
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
    assert (entry.author, entry.fingerprints, entry.affected) == ("usuario", (FP,), 1)


def test_no_entry_without_a_real_change(conn) -> None:
    with conn, changelog.track(conn, "nota", "transaccion", FP, "X") as draft:
        corrections.set_note(conn, FP, "")  # no había nota
    assert draft.entry_id is None
    assert changelog.load(conn) == []


def test_a_failed_change_leaves_no_entry(conn) -> None:
    with pytest.raises(ValueError), conn, changelog.track(conn, "nota", "transaccion", FP, "X"):
        corrections.set_note(conn, FP, "bien")
        corrections.set_note(conn, FP, "x" * 501)  # falla: todo se deshace
    assert changelog.load(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM transaction_notes").fetchone()[0] == 0


def test_undo_restores_and_is_its_own_entry(conn) -> None:
    first = _note_category(conn, CAJA, cat.RESTAURANTS)
    with conn:
        corrections.set_note(conn, CAJA, "sin bitácora")  # la otra columna sigue
    with conn:
        made = changelog.undo(conn, first)
    row = conn.execute("SELECT category_id, note FROM transaction_notes").fetchone()
    assert tuple(row) == (None, "sin bitácora")
    undo = changelog.get(conn, made)
    assert undo.undoes == first and undo.kind == "categoria"
    assert changelog.undone(conn) == {first}
    state = changelog.undo_state(conn, changelog.get(conn, first))
    assert (state.allowed, state.undone) == (False, True)
    with conn:  # deshacer el «Deshacer» vuelve a aplicar la corrección
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
        corrections.set_transaction_category(conn, FP, cat.GROCERIES)  # fuera de la bitácora
    later = changelog.undo_state(conn, changelog.get(conn, first))
    assert not later.allowed and "no queda en la bitácora" in later.message


def test_a_merchant_rule_undo_brings_back_the_previous_rule(conn) -> None:
    with conn:
        corrections.set_merchant_category(conn, "UBER EATS", cat.RESTAURANTS)
    with conn, changelog.track(conn, "regla", "comercio", "UBER EATS", "UBER EATS") as draft:
        corrections.set_merchant_category(conn, "UBER EATS", cat.HOME)
    with conn, changelog.track(conn, "regla", "comercio", "UBER", "UBER") as new:
        corrections.set_merchant_category(conn, "UBER", cat.HOME)
    with conn:
        changelog.undo(conn, draft.entry_id)
        changelog.undo(conn, new.entry_id)
    rules = dict(conn.execute("SELECT merchant, category_id FROM merchant_categories").fetchall())
    assert rules == {"UBER EATS": _cat(conn, cat.RESTAURANTS)}  # la de antes; la nueva, borrada


def _shared(conn: sqlite3.Connection, expense: str, credit: str) -> int:
    """Un grupo de un gasto «por otra persona» con un reembolso importado y uno a mano."""
    from decimal import Decimal  # noqa: PLC0415

    with conn:
        links.set_shared(conn, expense, Decimal("100.00"), for_other=True, with_whom="Ana")
        group = links.group_of(conn, expense)
        links.add_reimbursement(conn, group, credit)
        links.add_manual(conn, group, Decimal("20.00"), datetime(2026, 1, 9).date(), "DOP", "Ana")
    return group


def test_undo_of_deleting_a_group_restores_members_roles_and_manual(conn) -> None:
    group = _shared(conn, FP, CAJA)
    tables = ("links", "link_members", "link_manual")
    before = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in tables}
    with conn, changelog.track(conn, "compartido", "vinculo", str(group), "Ana") as draft:
        assert links.unshare(conn, FP)  # el último gasto: borra el grupo (en cascada)
    assert conn.execute("SELECT COUNT(*) FROM link_members").fetchone()[0] == 0
    entry = changelog.get(conn, draft.entry_id)
    assert set(entry.fingerprints) == {FP, CAJA}
    with conn:
        changelog.undo(conn, draft.entry_id)
    after = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in tables}
    assert after == before


def test_undo_never_touches_rows_of_a_later_entry(conn) -> None:
    from decimal import Decimal  # noqa: PLC0415

    with conn, changelog.track(conn, "compartido", "transaccion", FP, "X") as made:
        links.set_shared(conn, FP, Decimal("100.00"), people=2)
    group = links.group_of(conn, FP)
    with conn, changelog.track(conn, "compartido", "vinculo", str(group), "X") as joined:
        links.add_expense(conn, group, CAJA, Decimal("50.00"), people=2)
    # Deshacer la creación borraría el grupo y, en cascada, el gasto sumado después.
    with pytest.raises(changelog.UndoBlocked), conn:
        changelog.undo(conn, made.entry_id)
    assert conn.execute("SELECT COUNT(*) FROM link_members").fetchone()[0] == 2
    with conn:
        changelog.undo(conn, joined.entry_id)
        changelog.undo(conn, made.entry_id)
    assert conn.execute("SELECT COUNT(*) FROM links").fetchone()[0] == 0


def test_reason_is_trimmed_limited_and_not_a_change(conn) -> None:
    entry_id = _note_category(conn, FP, cat.RESTAURANTS)
    with conn:
        changelog.set_reason(conn, entry_id, "  lo pidió Ana  ")
    assert changelog.get(conn, entry_id).reason == "lo pidió Ana"
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
    second = _note_category(conn, CAJA, cat.RESTAURANTS)
    with conn:
        conn.execute("UPDATE change_log SET merchant = 'UBER EATS'")
        changelog.undo(conn, second)
    entries = changelog.load(conn)
    edits = changelog.category_edits(entries, changelog.undone(conn))
    assert [e.entry_id for e in edits] == [first]
