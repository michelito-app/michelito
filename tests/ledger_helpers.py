"""Helpers to build shared groups in tests (not tests themselves): the old one-call forms ("we
were N", "my share", "I paid it for someone else") written with the ledger, made-up people."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from michelito.analysis import ledger, ledger_store, spending
from michelito.migrations_v19 import LegacyExpense, legacy_share


def _movement(conn: sqlite3.Connection, fingerprint: str) -> spending.Movement | None:
    return next((m for m in spending.load_all(conn) if m.fingerprint == fingerprint), None)


def share(
    conn: sqlite3.Connection,
    fingerprint: str,
    amount: Decimal,
    *,
    people: int | None = None,
    my_share: Decimal | None = None,
    for_other: bool = False,
    with_whom: str = "",
    name: str | None = None,
    group: int | None = None,
    currency: str | None = None,
    day: date | None = None,
) -> int:
    """The user's expense `fingerprint` in a group (a new one, or `group`), split like the old
    forms: the user's share as before and the rest equally among the others (named in
    `with_whom`, or made-up ones). Returns the group id."""
    move = _movement(conn, fingerprint)
    me = ledger_store.ensure_me(conn)
    if group is None:
        names = [n.strip() for n in with_whom.replace(" y ", ",").split(",") if n.strip()]
        needed = (people - 1) if people is not None else 1
        names += [f"Person {i}" for i in range(len(names) + 2, needed + 2)]
        others = [ledger_store.contact_for(conn, n) for n in names]
        title = name or with_whom or (move.merchant if move else fingerprint) or "Group"
        group = ledger_store.create_group(conn, title[:80], others)
    else:
        others = [
            int(r[0])
            for r in conn.execute(
                "SELECT contact_id FROM ledger_members WHERE group_id = ? AND contact_id != ? "
                "ORDER BY added_at, rowid",
                (group, me),
            )
        ]
    split = LegacyExpense(fingerprint, people, my_share, for_other)
    mine = legacy_share(split, amount)
    chosen = others[: people - 1] if people is not None else others
    rest = amount - mine
    shares = {me: mine}
    if rest > 0:
        spread = ledger.equal_split(rest, chosen, chosen[0])
        shares.update({s.contact_id: s.share for s in spread})
    ledger_store.add_entry(
        conn,
        group,
        paid_by=me,
        amount=amount,
        currency=currency or (move.currency if move else "DOP"),
        day=day or (move.day if move else date(2026, 1, 1)),
        description=(move.merchant if move and move.merchant else fingerprint)[:120],
        splits=[ledger.Split(c, v) for c, v in shares.items() if v > 0],
        mode="exact" if my_share is not None else "equal",
        fingerprint=fingerprint,
    )
    return group


def pay(
    conn: sqlite3.Connection,
    group: int,
    fingerprint: str | None = None,
    *,
    amount: Decimal | None = None,
    currency: str | None = None,
    day: date | None = None,
    from_contact: int | None | str = "only",
) -> int:
    """A payment to the user in `group`: the credit `fingerprint` (its amount, currency and day)
    or one by hand. `from_contact`: "only" (the group's only other person, else unattributed),
    None (unattributed) or a contact id."""
    me = ledger_store.ensure_me(conn)
    move = None if fingerprint is None else _movement(conn, fingerprint)
    if from_contact == "only":
        others = [
            int(r[0])
            for r in conn.execute(
                "SELECT contact_id FROM ledger_members WHERE group_id = ? AND contact_id != ?",
                (group, me),
            )
        ]
        from_contact = others[0] if len(others) == 1 else None
    return ledger_store.add_payment(
        conn,
        group,
        from_contact=from_contact if isinstance(from_contact, int) else None,
        to_contact=me,
        amount=amount if amount is not None else (-move.amount if move else Decimal(0)),
        currency=currency or (move.currency if move else "DOP"),
        day=day or (move.day if move else date(2026, 1, 1)),
        fingerprint=fingerprint,
    )


_NOW = "2026-01-05T00:00:00+00:00"


def old_group(
    conn: sqlite3.Connection,
    expense: str,
    *,
    people: int | None = None,
    my_share: Decimal | None = None,
    for_other: bool = False,
    with_whom: str | None = None,
    name: str | None = None,
    written_off: bool = False,
) -> int:
    """A schema 18 shared group (a `links` row of kind `shared`), written as that release did:
    for the migration tests. Returns its id."""
    cursor = conn.execute(
        "INSERT INTO links (kind, with_whom, name, written_off, created_at, updated_at) "
        "VALUES ('shared', ?, ?, ?, ?, ?)",
        (with_whom, name, int(written_off), _NOW, _NOW),
    )
    group = int(cursor.lastrowid or 0)
    old_expense(conn, group, expense, people=people, my_share=my_share, for_other=for_other)
    return group


def old_expense(
    conn: sqlite3.Connection,
    group: int,
    expense: str,
    *,
    people: int | None = None,
    my_share: Decimal | None = None,
    for_other: bool = False,
) -> None:
    cents = None if my_share is None else int(my_share * 100)
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at, people, my_share_cents, "
        "for_other) VALUES (?, ?, 'expense', ?, ?, ?, ?)",
        (group, expense, _NOW, people, cents, int(for_other)),
    )


def old_refund(conn: sqlite3.Connection, group: int, credit: str) -> None:
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at) "
        "VALUES (?, ?, 'reimbursement', ?)",
        (group, credit, _NOW),
    )


def old_manual(
    conn: sqlite3.Connection,
    group: int,
    amount: Decimal,
    day: date,
    currency: str = "DOP",
    person: str | None = None,
    place: str | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO link_manual (link_id, amount_cents, day, person, place, currency, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (group, int(amount * 100), day.isoformat(), person, place, currency, _NOW),
    )
    return int(cursor.lastrowid or 0)


def groups_summary(conn: sqlite3.Connection) -> list[dict]:
    """Every ledger group, short: name, people (not the user), linked entries and payments
    (fingerprint or "manual" with its amount) and who was written off."""
    book = ledger_store.load(conn)
    found = []
    for group in book.groups:
        others = [m for m in group.members if m.contact_id != book.me]
        found.append(
            {
                "name": group.name,
                "people": [book.name(m.contact_id) for m in others],
                "entries": [e.fingerprint for e in group.entries],
                "payments": [(p.fingerprint or "manual", p.amount) for p in group.payments],
                "written_off": [book.name(m.contact_id) for m in others if m.written_off],
                "archived": group.archived,
            }
        )
    return found
