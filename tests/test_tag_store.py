"""Tags as stored (`analysis.tag_store`, schema 30), made-up names: manual tags with unique
names, one tag per shared group kept in sync, idempotent tagging and the undo of a deleted
group bringing its tag back."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import changelog, ledger_store, loan_store
from michelito.analysis import tag_store as store

NOW = "2026-05-20T12:00:00+00:00"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


def test_create_and_load(conn: sqlite3.Connection) -> None:
    with conn:
        made = store.create(conn, "Furnish the apartment", None, NOW)

    tags = store.load(conn)

    assert [(t.id, t.name, t.group_id) for t in tags] == [(made.id, "Furnish the apartment", None)]


@pytest.mark.parametrize("other", ["VIAJE", "viáje", "  Viaje "])  # spanish-ui
def test_names_are_unique_after_folding(conn: sqlite3.Connection, other: str) -> None:
    store.create(conn, "Viaje", None, NOW)

    with pytest.raises(store.DuplicateTag):
        store.create(conn, other, None, NOW)


def test_group_tags_may_share_a_name(conn: sqlite3.Connection) -> None:
    first = ledger_store.create_group(conn, "Trip")
    second = ledger_store.create_group(conn, "Trip")

    assert store.group_tag(conn, first) != store.group_tag(conn, second)
    with pytest.raises(store.DuplicateTag):
        store.create(conn, "trip", None, NOW)


def test_creating_and_renaming_a_group_keeps_its_tag(conn: sqlite3.Connection) -> None:
    group = ledger_store.create_group(conn, "Concert")
    tag = store.get(conn, store.group_tag(conn, group))
    assert (tag.name, tag.group_id) == ("Concert", group)

    ledger_store.update_group(conn, group, name="Concert 2026")

    assert store.get(conn, tag.id).name == "Concert 2026"


def test_group_tags_cannot_be_renamed_or_deleted_directly(conn: sqlite3.Connection) -> None:
    tag = store.group_tag(conn, ledger_store.create_group(conn, "Concert"))

    with pytest.raises(store.GroupTag):
        store.rename(conn, tag, "Other")
    with pytest.raises(store.GroupTag):
        store.delete(conn, tag)


def test_add_is_idempotent_and_remove_counts(conn: sqlite3.Connection) -> None:
    tag = store.create(conn, "Gifts", None, NOW).id

    assert store.add(conn, tag, ["a", "b"], NOW) == 2
    assert store.add(conn, tag, ["a", "b"], NOW) == 0
    assert store.remove(conn, tag, ["a", "x"]) == 1
    assert store.manual(conn) == {tag: {"b"}}


def test_targets_are_stored_per_kind(conn: sqlite3.Connection) -> None:
    tag = store.create(conn, "Kitchen", None, NOW).id

    store.add_target(conn, tag, "loan", 3, NOW)
    store.add_target(conn, tag, "installment", 3, NOW)
    store.remove_target(conn, tag, "loan", 3)

    assert store.targets(conn) == {tag: {("installment", 3)}}


def test_migration_backfills_one_tag_per_group(tmp_path: Path) -> None:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as opened, opened:
        ledger_store.create_group(opened, "One")
        ledger_store.create_group(opened, "Two")
        opened.execute("DELETE FROM tags")
        opened.execute("PRAGMA user_version = 27")

    with closing(db.connect(path)) as reopened:
        names = sorted(t.name for t in store.load(reopened) if t.group_id is not None)

    assert names == ["One", "Two"]


def test_deleting_a_group_removes_its_tag_and_undo_restores_it(
    conn: sqlite3.Connection,
) -> None:
    with conn:
        group = ledger_store.create_group(conn, "Trip")
        tag = store.group_tag(conn, group)
        store.add(conn, tag, ["hotel"], NOW)
    with conn, changelog.track(conn, "group_delete", "link", f"group-{group}", "Trip") as draft:
        ledger_store.delete_group(conn, group)
    assert store.load(conn) == []

    with conn:
        changelog.undo(conn, draft.entry_id)

    assert store.manual(conn) == {tag: {"hotel"}}
    assert store.get(conn, tag).group_id == group


def test_loans_get_has_payout_default_false(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO loans (name, number, currency, principal_cents, term, start_date, "
        "created_at, updated_at) VALUES ('Fridge', '42', 'DOP', 100000, 12, '2026-01-15', ?, ?)",
        (NOW, NOW),
    )

    (loan,) = loan_store.load(conn)

    assert loan.has_payout is False


def _old_entry(conn: sqlite3.Connection, kind: str, group: int, change) -> int:
    """A group change logged before schema 30: the group's tag is not among its rows."""
    with conn, changelog.track(conn, kind, "link", f"group-{group}", "Trip") as draft:
        change()
    return draft.entry_id


def test_undoing_a_group_created_before_tags_is_still_possible(conn: sqlite3.Connection) -> None:
    with conn, changelog.track(conn, "group_create", "link", "group-new", "Trip") as draft:
        conn.execute(
            "INSERT INTO ledger_groups (name, archived, created_at, updated_at) "
            "VALUES ('Trip', 0, ?, ?)",
            (NOW, NOW),
        )
    with conn:
        store.sync_group(conn, 1, "Trip", NOW)  # the schema 30 backfill, outside any entry

    with conn:
        changelog.undo(conn, draft.entry_id)

    assert store.load(conn) == []


def test_undoing_an_old_group_rename_keeps_its_tag_in_step(conn: sqlite3.Connection) -> None:
    with conn:
        group = ledger_store.create_group(conn, "Beach")
    entry = _old_entry(
        conn,
        "group_rename",
        group,
        lambda: conn.execute("UPDATE ledger_groups SET name = 'Trip' WHERE id = ?", (group,)),
    )
    with conn:
        store.sync_group(conn, group, "Trip", NOW)  # what the tag reads after the upgrade

    with conn:
        changelog.undo(conn, entry)

    assert store.get(conn, store.group_tag(conn, group)).name == "Beach"
