"""Whose an installment plan is: the user's, or a person's (whose installments are their share
of an expense in a group with the user).

The interface picks a person, never a group: `group_for` finds the group to record in (the
one the charge is already shared in with them, else a group of just the two of them) and
creates a two-person group when there is none. `set_owner` moves the installments already
recorded from one owner to another.

Nothing here commits: the caller wraps it in `with conn:` (and the change log).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from michelito.analysis import installment_store, ledger_store
from michelito.analysis.links import LinkError
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.migrations_v25 import NAME_MAX


@dataclass(frozen=True)
class Owner:
    """`contact_id` or `new_person` (a name) for a person; neither for the user."""

    contact_id: int | None = None
    new_person: str | None = None

    @property
    def is_mine(self) -> bool:
        return self.contact_id is None and not (self.new_person or "").strip()


@dataclass(frozen=True)
class Person:
    id: int
    name: str


def people(conn: sqlite3.Connection) -> list[Person]:
    """The people in the user's groups (not archived), by name."""
    me = ledger_store.me_id(conn)
    rows = conn.execute(
        "SELECT DISTINCT c.id, c.name FROM contacts c "
        "JOIN ledger_members m ON m.contact_id = c.id "
        "JOIN ledger_groups g ON g.id = m.group_id "
        "WHERE g.archived = 0 AND c.is_me = 0"
    ).fetchall()
    found = [Person(int(r[0]), str(r[1])) for r in rows if int(r[0]) != me]
    return sorted(found, key=lambda p: p.name.casefold())


def _members(conn: sqlite3.Connection, group_id: int) -> set[int]:
    rows = conn.execute("SELECT contact_id FROM ledger_members WHERE group_id = ?", (group_id,))
    return {int(r[0]) for r in rows}


def _shared_in(conn: sqlite3.Connection, fingerprint: str | None) -> int | None:
    if not fingerprint:
        return None
    row = conn.execute(
        "SELECT group_id FROM ledger_links WHERE fingerprint = ? AND entry_id IS NOT NULL",
        (fingerprint,),
    ).fetchone()
    return None if row is None else int(row[0])


def _pair_group(conn: sqlite3.Connection, me: int, contact_id: int) -> int | None:
    rows = conn.execute(
        "SELECT g.id FROM ledger_groups g JOIN ledger_members m ON m.group_id = g.id "
        "WHERE g.archived = 0 AND m.contact_id = ? ORDER BY g.updated_at DESC, g.id DESC",
        (contact_id,),
    ).fetchall()
    return next((int(r[0]) for r in rows if _members(conn, int(r[0])) == {me, contact_id}), None)


def _contact_name(conn: sqlite3.Connection, contact_id: int) -> str:
    row = conn.execute(
        "SELECT name FROM contacts WHERE id = ? AND is_me = 0", (contact_id,)
    ).fetchone()
    if row is None:
        raise LinkError(t("analysis.installments.unknown_person"))
    return str(row[0])


def suggested(conn: sqlite3.Connection, fingerprint: str) -> int | None:
    """The person a charge is already shared with, when its group is just the two of them
    (the likely owner of a plan made from it)."""
    group_id = _shared_in(conn, fingerprint)
    if group_id is None:
        return None
    others = _members(conn, group_id) - {ledger_store.me_id(conn)}
    return next(iter(others)) if len(others) == 1 else None


def group_for(conn: sqlite3.Connection, contact_id: int, fingerprint: str | None = None) -> int:
    """Where a person's installments go: the group the charge is already shared in with them,
    else a group of just the two of them, else a new one (named "you and <name>" in the UI
    language)."""
    name = _contact_name(conn, contact_id)
    me = ledger_store.ensure_me(conn)
    shared = _shared_in(conn, fingerprint)
    if shared is not None and contact_id in _members(conn, shared):
        return shared
    pair = _pair_group(conn, me, contact_id)
    if pair is not None:
        return pair
    title = t("analysis.installments.pair_group", name=name)
    return ledger_store.create_group(conn, title[:NAME_MAX], [contact_id])


def resolve(
    conn: sqlite3.Connection, owner: Owner, fingerprint: str | None = None
) -> tuple[int | None, int | None]:
    """(group, person) for an owner; (None, None) for the user. A new name is a new person
    (or the one already called that)."""
    if owner.is_mine:
        return None, None
    contact_id = owner.contact_id
    if contact_id is None:
        contact_id = ledger_store.contact_for(conn, owner.new_person or "")
    if contact_id == ledger_store.me_id(conn):
        raise LinkError(t("analysis.installments.not_a_member"))
    return group_for(conn, contact_id, fingerprint), contact_id


def set_owner(
    conn: sqlite3.Connection,
    plan_id: int,
    group_id: int | None,
    contact_id: int | None,
    flow: Sequence[Movement],
) -> None:
    """The plan becomes the user's or a person's: the group expenses it recorded go, and for a
    person each linked installment is recorded again in their group."""
    plan = installment_store.plan(conn, plan_id)
    if (plan.group_id, plan.contact_id) == (group_id, contact_id):
        return
    for number in plan.entries:
        installment_store.forget_entry(conn, plan, number)
    conn.execute(
        "UPDATE installment_plans SET group_id = ?, contact_id = ? WHERE id = ?",
        (group_id, contact_id, plan_id),
    )
    if group_id is None:
        return
    moved = installment_store.plan(conn, plan_id)
    by_fp = {m.fingerprint: m for m in flow}
    for number, fingerprint in moved.links.items():
        move = by_fp.get(fingerprint)
        if move is not None:
            installment_store.record(conn, moved, number, move)
