"""Reading and writing the shared ledger (schema 19; the math is in `ledger`).

Tables (`db.LEDGER_SCHEMA`): `contacts` (global people; exactly one with `is_me`, the user,
created on first use), `contact_aliases` (names seen in transfers, unique once folded),
`ledger_groups`, `ledger_members`, `ledger_entries`, `ledger_splits` (each person's share, in
cents, and their parts in a split by parts), `ledger_payments`, `ledger_allocations` (who an
attributed payment is for: schema 21, `migrations_v21`), `ledger_dismissals` (payments whose
"paid for others too?" was answered "No": schema 22, `migrations_v22`, which also adds
`ledger_members.leftover_settled`) and, in the personal part,
`ledger_links` (a transaction's fingerprint -> an entry or a payment) and `ledger_settings`
(flags such as "Review your people"). Every id is `AUTOINCREMENT`: a deleted id is never
reused, so an undo never gives a row back to a parent that inherited its id.

Nothing here commits: the caller wraps each change in `with conn:` and the change log.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from michelito.analysis import links
from michelito.analysis.ledger import (
    CURRENCIES,
    SPLIT_MODES,
    Allocation,
    Contact,
    Entry,
    Group,
    Ledger,
    Member,
    Payment,
    Split,
    SplitMode,
    equal_split,
    parts_split,
    resplit_without,
    to_cents,
)
from michelito.analysis.links import AlreadyLinked, LinkError
from michelito.analysis.shared import fold
from michelito.i18n import t

NAME_MAX = 80
DESCRIPTION_MAX = 120
ME_NAME = "me"  # stored name of the user's contact (the interface shows "You")
REVIEW_PEOPLE = "review_people"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


# --- Reading --------------------------------------------------------------------------------


def me_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM contacts WHERE is_me = 1").fetchone()
    return None if row is None else int(row[0])


def ensure_me(conn: sqlite3.Connection) -> int:
    """The user's contact, created the first time."""
    found = me_id(conn)
    if found is not None:
        return found
    now = _now()
    cursor = conn.execute(
        "INSERT INTO contacts (name, is_me, created_at, updated_at) VALUES (?, 1, ?, ?)",
        (ME_NAME, now, now),
    )
    return int(cursor.lastrowid or 0)


def _cents(value: int | None) -> Decimal | None:
    return None if value is None else Decimal(value).scaleb(-2)


def load(conn: sqlite3.Connection) -> Ledger:
    if not _has_tables(conn):
        return Ledger(me=0)
    aliases: dict[int, list[str]] = {}
    for row in conn.execute("SELECT contact_id, alias FROM contact_aliases ORDER BY id"):
        aliases.setdefault(int(row[0]), []).append(row[1])
    contacts = {
        int(row["id"]): Contact(
            int(row["id"]), row["name"], bool(row["is_me"]), tuple(aliases.get(row["id"], ()))
        )
        for row in conn.execute("SELECT * FROM contacts ORDER BY id")
    }
    me = next((c.id for c in contacts.values() if c.is_me), 0)
    linked: dict[tuple[str, int], str] = {}
    for row in conn.execute("SELECT * FROM ledger_links"):
        if row["entry_id"] is not None:
            linked[("entry", int(row["entry_id"]))] = row["fingerprint"]
        else:
            linked[("payment", int(row["payment_id"]))] = row["fingerprint"]
    splits: dict[int, list[Split]] = {}
    # In the group's order of people (so an undo that brings a person back puts them where
    # they were), then as written.
    for row in conn.execute(
        "SELECT s.* FROM ledger_splits s JOIN ledger_entries e ON e.id = s.entry_id "
        "LEFT JOIN ledger_members m ON m.group_id = e.group_id AND m.contact_id = s.contact_id "
        "ORDER BY s.entry_id, m.added_at IS NULL, m.added_at, m.rowid, s.rowid"
    ):
        splits.setdefault(int(row["entry_id"]), []).append(
            Split(
                int(row["contact_id"]),
                Decimal(row["share_cents"]).scaleb(-2),
                _parts(row),
            )
        )
    entries: dict[int, list[Entry]] = {}
    for row in conn.execute("SELECT * FROM ledger_entries ORDER BY day, id"):
        entries.setdefault(int(row["group_id"]), []).append(
            Entry(
                id=int(row["id"]),
                group_id=int(row["group_id"]),
                paid_by=int(row["paid_by"]),
                amount=Decimal(row["amount_cents"]).scaleb(-2),
                currency=row["currency"],
                day=date.fromisoformat(row["day"]),
                description=row["description"],
                splits=tuple(splits.get(int(row["id"]), ())),
                split_mode=row["split"],
                category_id=row["category_id"],
                fingerprint=linked.get(("entry", int(row["id"]))),
            )
        )
    allocations: dict[int, list[Allocation]] = {}
    for row in _allocation_rows(conn):
        allocations.setdefault(int(row["payment_id"]), []).append(
            Allocation(int(row["contact_id"]), Decimal(row["amount_cents"]).scaleb(-2))
        )
    payments: dict[int, list[Payment]] = {}
    for row in conn.execute("SELECT * FROM ledger_payments ORDER BY day, id"):
        payments.setdefault(int(row["group_id"]), []).append(
            Payment(
                id=int(row["id"]),
                group_id=int(row["group_id"]),
                from_contact=row["from_contact"],
                to_contact=int(row["to_contact"]),
                amount=Decimal(row["amount_cents"]).scaleb(-2),
                currency=row["currency"],
                day=date.fromisoformat(row["day"]),
                sent=_cents(row["sent_cents"]),
                accepted=bool(row["accepted"]),
                note=row["note"] or "",
                fingerprint=linked.get(("payment", int(row["id"]))),
                allocations=tuple(allocations.get(int(row["id"]), ())),
            )
        )
    members: dict[int, list[Member]] = {}
    for row in conn.execute("SELECT * FROM ledger_members ORDER BY added_at, rowid"):
        members.setdefault(int(row["group_id"]), []).append(
            Member(int(row["contact_id"]), bool(row["written_off"]), _leftover_settled(row))
        )
    dismissed: dict[int, set[int]] = {}
    for row in _dismissal_rows(conn):
        dismissed.setdefault(int(row["group_id"]), set()).add(int(row["payment_id"]))
    groups = tuple(
        Group(
            id=int(row["id"]),
            name=row["name"],
            members=tuple(members.get(int(row["id"]), ())),
            entries=tuple(entries.get(int(row["id"]), ())),
            payments=tuple(payments.get(int(row["id"]), ())),
            category_id=row["category_id"],
            archived=bool(row["archived"]),
            dismissed=frozenset(dismissed.get(int(row["id"]), ())),
        )
        for row in conn.execute("SELECT * FROM ledger_groups ORDER BY id")
    )
    flag = conn.execute(
        "SELECT value FROM ledger_settings WHERE key = ?", (REVIEW_PEOPLE,)
    ).fetchone()
    return Ledger(me, contacts, groups, review_people=flag is not None and flag[0] == "1")


def _parts(row: sqlite3.Row) -> int | None:
    """A split's parts (a `Row` has no `in` for its columns: before schema 21 there are none)."""
    names = row.keys()  # noqa: SIM118
    return None if "parts" not in names or row["parts"] is None else int(row["parts"])


def _leftover_settled(row: sqlite3.Row) -> bool:
    """A member's exchange-leftover toggle (on before schema 22, which has no column)."""
    names = row.keys()  # noqa: SIM118
    return "leftover_settled" not in names or bool(row["leftover_settled"])


def _dismissal_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The dismissed suggestions with their payment's group (none before schema 22)."""
    present = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ledger_dismissals'"
    ).fetchone()
    if present is None:
        return []
    return conn.execute(
        "SELECT d.payment_id, p.group_id FROM ledger_dismissals d "
        "JOIN ledger_payments p ON p.id = d.payment_id"
    ).fetchall()


def _allocation_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The payments' allocations (none before schema 21, while an earlier step migrates)."""
    present = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ledger_allocations'"
    ).fetchone()
    if present is None:
        return []
    return conn.execute("SELECT * FROM ledger_allocations ORDER BY payment_id, rowid").fetchall()


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ledger_links'"
    ).fetchone()
    return row is not None


def linked_fingerprints(conn: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    """Fingerprint -> (group id, "entry" or "payment")."""
    if not _has_tables(conn):
        return {}
    return {
        row["fingerprint"]: (int(row["group_id"]), "entry" if row["entry_id"] else "payment")
        for row in conn.execute("SELECT * FROM ledger_links")
    }


# --- Validation -----------------------------------------------------------------------------


def clean_name(value: str | None, *, required: bool = True, limit: int = NAME_MAX) -> str:
    text = " ".join((value or "").split())
    if required and not text:
        raise LinkError(t("analysis.ledger.name_required"))
    if len(text) > limit:
        raise LinkError(t("analysis.ledger.text_too_long", max=limit))
    return text


def cents_of(amount: Decimal) -> int:
    try:
        scaled = amount * 100
        if not scaled.is_finite() or scaled != scaled.to_integral_value():
            raise LinkError(t("analysis.links.too_many_decimals"))
    except InvalidOperation:
        raise LinkError(t("analysis.links.invalid_amount")) from None
    if scaled <= 0:
        raise LinkError(t("analysis.links.amount_positive"))
    return int(scaled)


def _check_currency(currency: str) -> None:
    if currency not in CURRENCIES:
        raise LinkError(t("analysis.links.currency_choice"))


def _require_group(conn: sqlite3.Connection, group_id: int) -> None:
    if conn.execute("SELECT 1 FROM ledger_groups WHERE id = ?", (group_id,)).fetchone() is None:
        raise LookupError(t("analysis.links.unknown_group", id=group_id))


def _require_contact(conn: sqlite3.Connection, contact_id: int) -> None:
    if conn.execute("SELECT 1 FROM contacts WHERE id = ?", (contact_id,)).fetchone() is None:
        raise LookupError(t("analysis.ledger.unknown_contact", id=contact_id))


def _members(conn: sqlite3.Connection, group_id: int) -> set[int]:
    rows = conn.execute("SELECT contact_id FROM ledger_members WHERE group_id = ?", (group_id,))
    return {int(r[0]) for r in rows}


def _check_free(conn: sqlite3.Connection, fingerprint: str) -> None:
    if links.link_of(conn, fingerprint) is not None:
        raise AlreadyLinked(t("analysis.links.already_linked"))


# --- Contacts -------------------------------------------------------------------------------


def find_contact(conn: sqlite3.Connection, name: str) -> int | None:
    """A contact (not the user) by its name or one of its aliases, ignoring accents and case."""
    folded = fold(" ".join(name.split()))
    for row in conn.execute("SELECT id, name FROM contacts WHERE is_me = 0 ORDER BY id"):
        if fold(row["name"]) == folded:
            return int(row["id"])
    row = conn.execute(
        "SELECT contact_id FROM contact_aliases WHERE folded = ?", (folded,)
    ).fetchone()
    return None if row is None else int(row[0])


def create_contact(conn: sqlite3.Connection, name: str, alias: str | None = None) -> int:
    text = clean_name(name)
    now = _now()
    cursor = conn.execute(
        "INSERT INTO contacts (name, is_me, created_at, updated_at) VALUES (?, 0, ?, ?)",
        (text, now, now),
    )
    found = int(cursor.lastrowid or 0)
    if alias:
        add_alias(conn, found, alias)
    return found


def contact_for(conn: sqlite3.Connection, name: str, alias: str | None = None) -> int:
    """The contact with that name (or alias), else a new one."""
    found = find_contact(conn, name)
    if found is None and alias:
        found = find_contact(conn, alias)
    if found is not None:
        if alias:
            add_alias(conn, found, alias)
        return found
    return create_contact(conn, name, alias)


def rename_contact(conn: sqlite3.Connection, contact_id: int, name: str) -> None:
    _require_contact(conn, contact_id)
    if contact_id == me_id(conn):
        raise LinkError(t("analysis.ledger.me_fixed"))
    conn.execute(
        "UPDATE contacts SET name = ?, updated_at = ? WHERE id = ?",
        (clean_name(name), _now(), contact_id),
    )


def add_alias(conn: sqlite3.Connection, contact_id: int, alias: str) -> None:
    """Notes a name seen in transfers; one already noted (for any contact) is left as it is."""
    _require_contact(conn, contact_id)
    text = clean_name(alias)
    folded = fold(text)
    taken = conn.execute(
        "SELECT contact_id FROM contact_aliases WHERE folded = ?", (folded,)
    ).fetchone()
    if taken is not None:
        if int(taken[0]) != contact_id:
            raise LinkError(t("analysis.ledger.alias_taken"))
        return
    conn.execute(
        "INSERT INTO contact_aliases (contact_id, alias, folded, created_at) VALUES (?, ?, ?, ?)",
        (contact_id, text, folded, _now()),
    )


def remove_alias(conn: sqlite3.Connection, contact_id: int, alias: str) -> None:
    cursor = conn.execute(
        "DELETE FROM contact_aliases WHERE contact_id = ? AND folded = ?",
        (contact_id, fold(" ".join(alias.split()))),
    )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.ledger.unknown_alias"))


def merge_contacts(conn: sqlite3.Connection, source: int, target: int) -> None:
    """`source` becomes `target` everywhere (groups, shares, payments, aliases); its name stays
    as an alias of `target`. Shares of both in the same entry are added up."""
    _require_contact(conn, source)
    _require_contact(conn, target)
    me = me_id(conn)
    if source == target or me in (source, target):
        raise LinkError(t("analysis.ledger.merge_invalid"))
    name = conn.execute("SELECT name FROM contacts WHERE id = ?", (source,)).fetchone()[0]
    for row in conn.execute(
        "SELECT group_id, written_off, leftover_settled FROM ledger_members WHERE contact_id = ?",
        (source,),
    ).fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO ledger_members "
            "(group_id, contact_id, written_off, leftover_settled, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (row[0], target, row[1], row[2], _now()),
        )
    conn.execute("DELETE FROM ledger_members WHERE contact_id = ?", (source,))
    for row in conn.execute(
        "SELECT entry_id, share_cents, parts FROM ledger_splits WHERE contact_id = ?", (source,)
    ).fetchall():
        updated = conn.execute(
            "UPDATE ledger_splits SET share_cents = share_cents + ?, "
            "parts = CASE WHEN parts IS NULL OR ? IS NULL THEN parts ELSE parts + ? END "
            "WHERE entry_id = ? AND contact_id = ?",
            (row[1], row[2], row[2], row[0], target),
        )
        if updated.rowcount == 0:
            conn.execute(
                "INSERT INTO ledger_splits (entry_id, contact_id, share_cents, parts) "
                "VALUES (?, ?, ?, ?)",
                (row[0], target, row[1], row[2]),
            )
    conn.execute("DELETE FROM ledger_splits WHERE contact_id = ?", (source,))
    for row in conn.execute(
        "SELECT payment_id, amount_cents FROM ledger_allocations WHERE contact_id = ?", (source,)
    ).fetchall():
        updated = conn.execute(
            "UPDATE ledger_allocations SET amount_cents = amount_cents + ? "
            "WHERE payment_id = ? AND contact_id = ?",
            (row[1], row[0], target),
        )
        if updated.rowcount == 0:
            conn.execute(
                "INSERT INTO ledger_allocations (payment_id, contact_id, amount_cents) "
                "VALUES (?, ?, ?)",
                (row[0], target, row[1]),
            )
    conn.execute("DELETE FROM ledger_allocations WHERE contact_id = ?", (source,))
    conn.execute("UPDATE ledger_entries SET paid_by = ? WHERE paid_by = ?", (target, source))
    conn.execute(
        "UPDATE ledger_payments SET from_contact = ? WHERE from_contact = ?", (target, source)
    )
    conn.execute("UPDATE ledger_payments SET to_contact = ? WHERE to_contact = ?", (target, source))
    conn.execute("UPDATE contact_aliases SET contact_id = ? WHERE contact_id = ?", (target, source))
    conn.execute("DELETE FROM contacts WHERE id = ?", (source,))
    target_name = conn.execute("SELECT name FROM contacts WHERE id = ?", (target,)).fetchone()[0]
    if fold(name) != fold(target_name):
        add_alias(conn, target, name)


def set_review_people(conn: sqlite3.Connection, pending: bool) -> None:
    if pending:
        conn.execute(
            "INSERT OR REPLACE INTO ledger_settings (key, value) VALUES (?, '1')", (REVIEW_PEOPLE,)
        )
    else:
        conn.execute("DELETE FROM ledger_settings WHERE key = ?", (REVIEW_PEOPLE,))


# --- Groups ---------------------------------------------------------------------------------


def create_group(
    conn: sqlite3.Connection,
    name: str,
    people: Iterable[int] = (),
    category_id: int | None = None,
) -> int:
    """A new group with the user and these contacts."""
    text = clean_name(name)
    me = ensure_me(conn)
    now = _now()
    cursor = conn.execute(
        "INSERT INTO ledger_groups (name, category_id, archived, created_at, updated_at) "
        "VALUES (?, ?, 0, ?, ?)",
        (text, category_id, now, now),
    )
    found = int(cursor.lastrowid or 0)
    for contact in dict.fromkeys((me, *people)):
        add_member(conn, found, contact)
    return found


def update_group(
    conn: sqlite3.Connection,
    group_id: int,
    *,
    name: str | None = None,
    archived: bool | None = None,
    category_id: int | None | object = ...,
) -> None:
    _require_group(conn, group_id)
    if name is not None:
        conn.execute("UPDATE ledger_groups SET name = ? WHERE id = ?", (clean_name(name), group_id))
    if archived is not None:
        conn.execute(
            "UPDATE ledger_groups SET archived = ? WHERE id = ?", (int(archived), group_id)
        )
    if category_id is not ...:
        conn.execute(
            "UPDATE ledger_groups SET category_id = ? WHERE id = ?", (category_id, group_id)
        )
    _touch(conn, group_id)


def delete_group(conn: sqlite3.Connection, group_id: int) -> None:
    _require_group(conn, group_id)
    conn.execute("DELETE FROM ledger_groups WHERE id = ?", (group_id,))


def add_member(conn: sqlite3.Connection, group_id: int, contact_id: int) -> None:
    _require_group(conn, group_id)
    _require_contact(conn, contact_id)
    conn.execute(
        "INSERT OR IGNORE INTO ledger_members (group_id, contact_id, written_off, added_at) "
        "VALUES (?, ?, 0, ?)",
        (group_id, contact_id, _now()),
    )


@dataclass(frozen=True)
class UsedIn:
    """An expense or a payment that names a person (for "remove from the group")."""

    id: int
    day: date
    description: str  # the expense's (empty for a payment)
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class MemberUsage:
    """Where a person appears in a group: expenses they have a share in (without having paid
    them), expenses they paid and payments from, to or on behalf of them."""

    shares: tuple[UsedIn, ...] = ()
    paid: tuple[UsedIn, ...] = ()
    payments: tuple[UsedIn, ...] = ()

    @property
    def free(self) -> bool:
        return not (self.shares or self.paid or self.payments)

    @property
    def resplittable(self) -> bool:
        """Only shares: they can be taken out of those expenses (re-split among the rest)."""
        return bool(self.shares) and not (self.paid or self.payments)


def _used_in(row: sqlite3.Row, description: str = "") -> UsedIn:
    return UsedIn(
        int(row["id"]),
        date.fromisoformat(row["day"]),
        description,
        Decimal(row["amount_cents"]).scaleb(-2),
        row["currency"],
    )


def member_usage(conn: sqlite3.Connection, group_id: int, contact_id: int) -> MemberUsage:
    _require_group(conn, group_id)
    paid = conn.execute(
        "SELECT * FROM ledger_entries WHERE group_id = ? AND paid_by = ? ORDER BY day, id",
        (group_id, contact_id),
    ).fetchall()
    shares = conn.execute(
        "SELECT e.* FROM ledger_entries e JOIN ledger_splits s ON s.entry_id = e.id "
        "WHERE e.group_id = ? AND s.contact_id = ? AND e.paid_by != ? ORDER BY e.day, e.id",
        (group_id, contact_id, contact_id),
    ).fetchall()
    payments = conn.execute(
        "SELECT * FROM ledger_payments p WHERE group_id = ? AND (from_contact = ? "
        "OR to_contact = ? OR EXISTS (SELECT 1 FROM ledger_allocations a "
        "WHERE a.payment_id = p.id AND a.contact_id = ?)) ORDER BY day, id",
        (group_id, contact_id, contact_id, contact_id),
    ).fetchall()
    return MemberUsage(
        shares=tuple(_used_in(r, r["description"]) for r in shares),
        paid=tuple(_used_in(r, r["description"]) for r in paid),
        payments=tuple(_used_in(r) for r in payments),
    )


def resplit_preview(
    conn: sqlite3.Connection, group_id: int, contact_id: int
) -> dict[int, tuple[Split, ...]]:
    """What each expense the person has a share in would become without them (entry id ->
    splits), as `remove_member` with `resplit` would write it."""
    group = load(conn).group(group_id)
    if group is None:
        raise LookupError(t("analysis.links.unknown_group", id=group_id))
    return {
        e.id: resplit_without(e, contact_id)
        for e in group.entries
        if contact_id in e.people and e.paid_by != contact_id
    }


def _money(amount: Decimal, currency: str) -> str:
    """ "RD$ 1,632" (cents only when there are), as the change log writes it."""
    cents = to_cents(amount)
    prefix = "US$" if currency == "USD" else "RD$"
    whole = f"{prefix} {abs(cents) // 100:,}"
    return whole if cents % 100 == 0 else f"{whole}.{abs(cents) % 100:02d}"


def _payments_listed(items: Sequence[UsedIn]) -> str:
    return ", ".join(
        t(
            "analysis.ledger.used_payment_item",
            day=i.day.strftime("%d/%m/%Y"),
            amount=_money(i.amount, i.currency),
        )
        for i in items
    )


def _listed(items: Sequence[UsedIn]) -> str:
    return ", ".join(
        t("analysis.ledger.used_entry", what=i.description, day=i.day.strftime("%d/%m/%Y"))
        for i in items
    )


def usage_text(name: str, usage: MemberUsage) -> str:
    """Why a person cannot just leave the group: where they have a share, what they paid and
    which payments name them (date and amount), and what can be done."""
    parts = []
    if usage.shares:
        parts.append(t("analysis.ledger.used_shares", list=_listed(usage.shares)))
    if usage.paid:
        parts.append(t("analysis.ledger.used_paid", list=_listed(usage.paid)))
    if usage.payments:
        key = "used_payment" if len(usage.payments) == 1 else "used_payments"
        parts.append(t(f"analysis.ledger.{key}", list=_payments_listed(usage.payments)))
    text = t("analysis.ledger.used_in", name=name, what="; ".join(parts))
    if usage.resplittable:
        return text + t("analysis.ledger.used_resplit_hint", count=len(usage.shares))
    return text + t("analysis.ledger.used_blocked_hint")


def remove_member(
    conn: sqlite3.Connection, group_id: int, contact_id: int, *, resplit: bool = False
) -> int:
    """Takes a person out of the group; never the user. Someone who paid an expense or is in a
    payment stays (the refusal says where). Someone with shares only leaves with `resplit`:
    each of those expenses is split again among the rest keeping its mode
    (`ledger.resplit_without`). Returns how many expenses were split again."""
    _require_group(conn, group_id)
    if contact_id == me_id(conn):
        raise LinkError(t("analysis.ledger.me_fixed"))
    _require_contact(conn, contact_id)
    usage = member_usage(conn, group_id, contact_id)
    if not usage.free and not (resplit and usage.resplittable):
        name = conn.execute("SELECT name FROM contacts WHERE id = ?", (contact_id,)).fetchone()[0]
        raise LinkError(usage_text(str(name), usage))
    if usage.shares:
        wanted = {u.id for u in usage.shares}
        group = load(conn).group(group_id)
        for entry in () if group is None else group.entries:
            if entry.id in wanted:
                _replace_splits(conn, entry.id, resplit_without(entry, contact_id))
    conn.execute(
        "DELETE FROM ledger_members WHERE group_id = ? AND contact_id = ?", (group_id, contact_id)
    )
    _touch(conn, group_id)
    return len(usage.shares)


def _replace_splits(conn: sqlite3.Connection, entry_id: int, splits: Sequence[Split]) -> None:
    """Writes an entry's new splits, touching only the rows that change (so the change log shows
    what moved)."""
    current = {
        int(r["contact_id"]): (int(r["share_cents"]), r["parts"])
        for r in conn.execute("SELECT * FROM ledger_splits WHERE entry_id = ?", (entry_id,))
    }
    wanted = {s.contact_id: (to_cents(s.share), s.parts) for s in splits}
    for contact in current.keys() - wanted.keys():
        conn.execute(
            "DELETE FROM ledger_splits WHERE entry_id = ? AND contact_id = ?", (entry_id, contact)
        )
    for contact, (cents, parts) in wanted.items():
        if current.get(contact) == (cents, parts):
            continue
        conn.execute(
            "INSERT INTO ledger_splits (entry_id, contact_id, share_cents, parts) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(entry_id, contact_id) DO UPDATE SET "
            "share_cents = excluded.share_cents, parts = excluded.parts",
            (entry_id, contact, cents, parts),
        )
    conn.execute("UPDATE ledger_entries SET updated_at = ? WHERE id = ?", (_now(), entry_id))


def set_written_off(
    conn: sqlite3.Connection, group_id: int, contact_id: int | None, written_off: bool
) -> None:
    """ "They won't pay me" for one person of the group (None: everyone but the user)."""
    _require_group(conn, group_id)
    me = me_id(conn)
    if contact_id is None:
        conn.execute(
            "UPDATE ledger_members SET written_off = ? WHERE group_id = ? AND contact_id != ?",
            (int(written_off), group_id, me),
        )
    else:
        if contact_id == me:
            raise LinkError(t("analysis.ledger.me_fixed"))
        cursor = conn.execute(
            "UPDATE ledger_members SET written_off = ? WHERE group_id = ? AND contact_id = ?",
            (int(written_off), group_id, contact_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(t("analysis.ledger.not_member"))
    _touch(conn, group_id)


def set_leftover_settled(
    conn: sqlite3.Connection, group_id: int, contact_id: int, settled: bool
) -> None:
    """Whether a person's exchange leftovers in the group count as settled (`ledger` rule 5)."""
    _require_group(conn, group_id)
    if contact_id == me_id(conn):
        raise LinkError(t("analysis.ledger.me_fixed"))
    cursor = conn.execute(
        "UPDATE ledger_members SET leftover_settled = ? WHERE group_id = ? AND contact_id = ?",
        (int(settled), group_id, contact_id),
    )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.ledger.not_member"))
    _touch(conn, group_id)


def _touch(conn: sqlite3.Connection, group_id: int) -> None:
    conn.execute("UPDATE ledger_groups SET updated_at = ? WHERE id = ?", (_now(), group_id))


# --- Entries --------------------------------------------------------------------------------


def build_splits(
    amount: Decimal,
    paid_by: int,
    mode: SplitMode,
    people: Sequence[int] = (),
    shares: Mapping[int, Decimal] | None = None,
    parts: Mapping[int, int] | None = None,
) -> tuple[Split, ...]:
    """The shares of an entry: equal among `people` (cent rule), by `parts` (person -> number
    of parts, at least 1; the same cent rule) or exactly `shares`."""
    if mode not in SPLIT_MODES:
        raise LinkError(t("analysis.ledger.unknown_split"))
    if mode == "equal":
        if not people:
            raise LinkError(t("analysis.ledger.split_needs_people"))
        return equal_split(amount, people, paid_by)
    if mode == "parts":
        counts = dict(parts or {})
        if not counts:
            raise LinkError(t("analysis.ledger.split_needs_people"))
        if any(count < 1 for count in counts.values()):
            raise LinkError(t("analysis.ledger.parts_positive"))
        return parts_split(amount, list(counts.items()), paid_by)
    given = {c: v for c, v in (shares or {}).items()}
    if not given or any(v < 0 for v in given.values()):
        raise LinkError(t("analysis.ledger.split_needs_people"))
    for value in given.values():
        if value and cents_of(value) != to_cents(value):  # validates the decimals
            raise LinkError(t("analysis.links.too_many_decimals"))
    if sum(given.values(), Decimal(0)) != amount:
        raise LinkError(t("analysis.ledger.exact_must_add_up"))
    return tuple(Split(c, v) for c, v in given.items() if v > 0)


def add_entry(
    conn: sqlite3.Connection,
    group_id: int,
    *,
    paid_by: int,
    amount: Decimal,
    currency: str,
    day: date,
    description: str,
    splits: Sequence[Split],
    mode: SplitMode,
    category_id: int | None = None,
    fingerprint: str | None = None,
) -> int:
    """An expense of the group. Its people (payer and shares) become members if they were not.
    `fingerprint`: the user's transaction it comes from (only when the user paid)."""
    _require_group(conn, group_id)
    _check_currency(currency)
    cents = cents_of(amount)
    if fingerprint is not None:
        if paid_by != me_id(conn):
            raise LinkError(t("analysis.ledger.link_needs_me"))
        _check_free(conn, fingerprint)
    now = _now()
    cursor = conn.execute(
        "INSERT INTO ledger_entries (group_id, paid_by, amount_cents, currency, day, "
        "description, category_id, split, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            group_id,
            paid_by,
            cents,
            currency,
            day.isoformat(),
            clean_name(description, limit=DESCRIPTION_MAX),
            category_id,
            mode,
            now,
            now,
        ),
    )
    found = int(cursor.lastrowid or 0)
    _write_splits(conn, group_id, found, paid_by, splits)
    if fingerprint is not None:
        conn.execute(
            "INSERT INTO ledger_links (fingerprint, group_id, entry_id, added_at) "
            "VALUES (?, ?, ?, ?)",
            (fingerprint, group_id, found, now),
        )
    _touch(conn, group_id)
    return found


def _write_splits(
    conn: sqlite3.Connection, group_id: int, entry_id: int, paid_by: int, splits: Sequence[Split]
) -> None:
    for contact in dict.fromkeys((paid_by, *(s.contact_id for s in splits))):
        add_member(conn, group_id, contact)
    conn.executemany(
        "INSERT INTO ledger_splits (entry_id, contact_id, share_cents, parts) VALUES (?, ?, ?, ?)",
        [(entry_id, s.contact_id, to_cents(s.share), s.parts) for s in splits],
    )


def entry_group(conn: sqlite3.Connection, entry_id: int) -> int:
    row = conn.execute("SELECT group_id FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise LookupError(t("analysis.ledger.unknown_entry", id=entry_id))
    return int(row[0])


def update_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    *,
    paid_by: int,
    amount: Decimal,
    currency: str,
    day: date,
    description: str,
    splits: Sequence[Split],
    mode: SplitMode,
    category_id: int | None = None,
) -> None:
    group_id = entry_group(conn, entry_id)
    _check_currency(currency)
    linked = conn.execute("SELECT 1 FROM ledger_links WHERE entry_id = ?", (entry_id,)).fetchone()
    if linked is not None and paid_by != me_id(conn):
        raise LinkError(t("analysis.ledger.link_needs_me"))
    conn.execute(
        "UPDATE ledger_entries SET paid_by = ?, amount_cents = ?, currency = ?, day = ?, "
        "description = ?, category_id = ?, split = ?, updated_at = ? WHERE id = ?",
        (
            paid_by,
            cents_of(amount),
            currency,
            day.isoformat(),
            clean_name(description, limit=DESCRIPTION_MAX),
            category_id,
            mode,
            _now(),
            entry_id,
        ),
    )
    conn.execute("DELETE FROM ledger_splits WHERE entry_id = ?", (entry_id,))
    _write_splits(conn, group_id, entry_id, paid_by, splits)
    _touch(conn, group_id)


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> int:
    group_id = entry_group(conn, entry_id)
    conn.execute("DELETE FROM ledger_entries WHERE id = ?", (entry_id,))
    _touch(conn, group_id)
    return group_id


# --- Payments -------------------------------------------------------------------------------


def add_payment(
    conn: sqlite3.Connection,
    group_id: int,
    *,
    from_contact: int | None,
    to_contact: int,
    amount: Decimal,
    currency: str,
    day: date,
    sent: Decimal | None = None,
    note: str | None = None,
    fingerprint: str | None = None,
    allocations: Mapping[int, Decimal] | None = None,
) -> int:
    """A payment between two members (`from_contact` None: unattributed, to the user). One of
    the two ends must be the user. `fingerprint`: the user's transaction (credit if received,
    debit if paid). `allocations` ("Paid for others": only a payment another person made to
    the user): who it is for (person -> amount, adding up to `amount`; people of the group);
    without them, all of it is for the person at the other end."""
    _require_group(conn, group_id)
    _check_currency(currency)
    me = me_id(conn)
    if from_contact == to_contact or me not in (from_contact, to_contact):
        raise LinkError(t("analysis.ledger.payment_needs_me"))
    if from_contact is None and to_contact != me:
        raise LinkError(t("analysis.ledger.payment_needs_me"))
    for contact in (from_contact, to_contact):
        if contact is not None:
            add_member(conn, group_id, contact)
    principal = None if from_contact is None else (from_contact if to_contact == me else to_contact)
    if allocations and to_contact != me:
        raise LinkError(t("analysis.ledger.allocations_need_payer"))
    shares = _allocations(conn, group_id, amount, principal, me, allocations)
    if fingerprint is not None:
        _check_free(conn, fingerprint)
    now = _now()
    cursor = conn.execute(
        "INSERT INTO ledger_payments (group_id, from_contact, to_contact, amount_cents, currency, "
        "sent_cents, accepted, day, note, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
        (
            group_id,
            from_contact,
            to_contact,
            cents_of(amount),
            currency,
            None if sent is None else cents_of(sent),
            day.isoformat(),
            clean_name(note, required=False, limit=DESCRIPTION_MAX) or None,
            now,
            now,
        ),
    )
    found = int(cursor.lastrowid or 0)
    _write_allocations(conn, found, shares)
    if fingerprint is not None:
        link_payment(conn, found, fingerprint)
    _touch(conn, group_id)
    return found


def _allocations(
    conn: sqlite3.Connection,
    group_id: int,
    amount: Decimal,
    principal: int | None,
    me: int | None,
    given: Mapping[int, Decimal] | None,
) -> dict[int, int]:
    """The allocations to store, in cents (none for an unattributed payment)."""
    if principal is None:
        if given:
            raise LinkError(t("analysis.ledger.allocations_need_payer"))
        return {}
    total = cents_of(amount)
    if not given:
        return {principal: total}
    members = _members(conn, group_id)
    found: dict[int, int] = {}
    for contact, value in given.items():
        if contact == me:
            raise LinkError(t("analysis.ledger.allocation_not_me"))
        if contact not in members:
            raise LinkError(t("analysis.ledger.not_member"))
        if value < 0:
            raise LinkError(t("analysis.ledger.allocations_add_up"))
        if value > 0:
            found[contact] = cents_of(value)
    if sum(found.values()) != total:
        raise LinkError(t("analysis.ledger.allocations_add_up"))
    return found


def _write_allocations(
    conn: sqlite3.Connection, payment_id: int, shares: Mapping[int, int]
) -> None:
    conn.executemany(
        "INSERT INTO ledger_allocations (payment_id, contact_id, amount_cents) VALUES (?, ?, ?)",
        [(payment_id, contact, cents) for contact, cents in shares.items()],
    )


def set_allocations(
    conn: sqlite3.Connection, payment_id: int, allocations: Mapping[int, Decimal] | None
) -> None:
    """Replaces who a payment another person made to the user is for ("Also paid for…"): the
    allocations as given (person -> amount, adding up to the payment's amount; people of the
    group) or, without any, all of it for the payer. They add up to what it settles (what was
    sent, once a difference was accepted). Only the rows that change are touched, so
    the change log shows what moved; one call is one change."""
    group_id = payment_group(conn, payment_id)
    me = me_id(conn)
    row = conn.execute(
        "SELECT from_contact, to_contact, amount_cents, sent_cents, accepted "
        "FROM ledger_payments WHERE id = ?",
        (payment_id,),
    ).fetchone()
    if row["from_contact"] is None or int(row["to_contact"]) != me:
        raise LinkError(t("analysis.ledger.allocations_need_payer"))
    # What it settles (`Payment.settles`): what was sent once a difference was accepted.
    settles = row["sent_cents"] if row["accepted"] and row["sent_cents"] else row["amount_cents"]
    amount = Decimal(int(settles)).scaleb(-2)
    wanted = _allocations(conn, group_id, amount, int(row["from_contact"]), me, allocations or None)
    current = {
        int(r["contact_id"]): int(r["amount_cents"])
        for r in conn.execute(
            "SELECT contact_id, amount_cents FROM ledger_allocations WHERE payment_id = ?",
            (payment_id,),
        )
    }
    for contact in current.keys() - wanted.keys():
        conn.execute(
            "DELETE FROM ledger_allocations WHERE payment_id = ? AND contact_id = ?",
            (payment_id, contact),
        )
    for contact, cents in wanted.items():
        if current.get(contact) == cents:
            continue
        conn.execute(
            "INSERT INTO ledger_allocations (payment_id, contact_id, amount_cents) "
            "VALUES (?, ?, ?) ON CONFLICT(payment_id, contact_id) DO UPDATE SET "
            "amount_cents = excluded.amount_cents",
            (payment_id, contact, cents),
        )
    if current != wanted:
        conn.execute("UPDATE ledger_payments SET updated_at = ? WHERE id = ?", (_now(), payment_id))
        _touch(conn, group_id)


def require_payments_of(
    conn: sqlite3.Connection, group_id: int, payment_ids: Iterable[int]
) -> None:
    """Every payment is one of the group's (a plan or a "No" is about one group)."""
    _require_group(conn, group_id)
    for payment_id in payment_ids:
        if payment_group(conn, payment_id) != group_id:
            raise LinkError(t("analysis.ledger.cover_other_group"))


def set_cover_dismissed(conn: sqlite3.Connection, payment_id: int, dismissed: bool) -> None:
    """ "Was that payment for someone else too?" answered "No" (or asked again)."""
    group_id = payment_group(conn, payment_id)
    if dismissed:
        conn.execute(
            "INSERT OR IGNORE INTO ledger_dismissals (payment_id, dismissed_at) VALUES (?, ?)",
            (payment_id, _now()),
        )
    else:
        conn.execute("DELETE FROM ledger_dismissals WHERE payment_id = ?", (payment_id,))
    _touch(conn, group_id)


def payment_group(conn: sqlite3.Connection, payment_id: int) -> int:
    row = conn.execute(
        "SELECT group_id FROM ledger_payments WHERE id = ?", (payment_id,)
    ).fetchone()
    if row is None:
        raise LookupError(t("analysis.ledger.unknown_payment", id=payment_id))
    return int(row[0])


def assign_payment(conn: sqlite3.Connection, payment_id: int, from_contact: int) -> None:
    """Gives a payment the user received to a person of the group: an unattributed one, or one
    attributed to the wrong person. All of it becomes theirs (who else it covered starts over)."""
    group_id = payment_group(conn, payment_id)
    me = me_id(conn)
    if from_contact == me:
        raise LinkError(t("analysis.ledger.payment_needs_me"))
    to_contact = conn.execute(
        "SELECT to_contact FROM ledger_payments WHERE id = ?", (payment_id,)
    ).fetchone()[0]
    if int(to_contact) != me:
        raise LinkError(t("analysis.ledger.payer_change_needs_received"))
    if from_contact not in _members(conn, group_id):
        raise LinkError(t("analysis.ledger.not_member"))
    conn.execute(
        "UPDATE ledger_payments SET from_contact = ?, updated_at = ? WHERE id = ?",
        (from_contact, _now(), payment_id),
    )
    conn.execute("DELETE FROM ledger_allocations WHERE payment_id = ?", (payment_id,))
    cents = conn.execute(
        "SELECT amount_cents FROM ledger_payments WHERE id = ?", (payment_id,)
    ).fetchone()[0]
    _write_allocations(conn, payment_id, {from_contact: int(cents)})
    _touch(conn, group_id)


def update_payment(
    conn: sqlite3.Connection,
    payment_id: int,
    *,
    amount: Decimal | None = None,
    sent: Decimal | None | object = ...,
    accepted: bool | None = None,
    day: date | None = None,
) -> None:
    group_id = payment_group(conn, payment_id)
    if amount is not None:
        conn.execute(
            "UPDATE ledger_payments SET amount_cents = ? WHERE id = ?",
            (cents_of(amount), payment_id),
        )
    if sent is not ...:
        value = None if not isinstance(sent, Decimal) else cents_of(sent)
        conn.execute("UPDATE ledger_payments SET sent_cents = ? WHERE id = ?", (value, payment_id))
    if accepted is not None:
        conn.execute(
            "UPDATE ledger_payments SET accepted = ? WHERE id = ?", (int(accepted), payment_id)
        )
    if day is not None:
        conn.execute(
            "UPDATE ledger_payments SET day = ? WHERE id = ?", (day.isoformat(), payment_id)
        )
    conn.execute("UPDATE ledger_payments SET updated_at = ? WHERE id = ?", (_now(), payment_id))
    _touch(conn, group_id)


def link_payment(conn: sqlite3.Connection, payment_id: int, fingerprint: str) -> None:
    group_id = payment_group(conn, payment_id)
    current = conn.execute(
        "SELECT fingerprint FROM ledger_links WHERE payment_id = ?", (payment_id,)
    ).fetchone()
    if current is not None:
        raise AlreadyLinked(t("analysis.ledger.payment_linked"))
    _check_free(conn, fingerprint)
    conn.execute(
        "INSERT INTO ledger_links (fingerprint, group_id, payment_id, added_at) "
        "VALUES (?, ?, ?, ?)",
        (fingerprint, group_id, payment_id, _now()),
    )


def unlink(conn: sqlite3.Connection, fingerprint: str) -> None:
    cursor = conn.execute("DELETE FROM ledger_links WHERE fingerprint = ?", (fingerprint,))
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.ledger.not_linked"))


def delete_payment(conn: sqlite3.Connection, payment_id: int) -> int:
    group_id = payment_group(conn, payment_id)
    conn.execute("DELETE FROM ledger_payments WHERE id = ?", (payment_id,))
    _touch(conn, group_id)
    return group_id
