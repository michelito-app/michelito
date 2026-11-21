"""Change log: a human sentence for each change to Shared (the ledger), pure.

The generic description of a change lists the rows it touched ("Javier, in the group → —"),
which says little. Here each kind of ledger change becomes one sentence from the user's point of
view ("You removed Javier and El Gordo from the group «World Series»"), built from the change's
rows and today's names (`Names`). A kind it does not know, or rows it cannot read, give None
(the generic description stays).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from michelito.analysis.changelog_rules import Change, Row
from michelito.i18n import t

LEDGER_KINDS = frozenset(
    {
        "group_new",
        "group",
        "group_member",
        "group_member_resplit",
        "write_off",
        "group_entry",
        "group_entry_delete",
        "group_payment",
        "group_payment_delete",
        "contact",
        "contact_rename",
        "contact_alias",
        "contact_merge",
        "review_people",
    }
)


@dataclass(frozen=True)
class Names:
    """Today's names: contacts and groups by id, and the user's contact."""

    contacts: Mapping[int, str] = field(default_factory=dict)
    groups: Mapping[int, str] = field(default_factory=dict)
    me: int | None = None


@dataclass(frozen=True)
class _Rows:
    """A change's rows by table: inserted, deleted and updated (before, after)."""

    changes: Sequence[Change]

    def added(self, table: str) -> list[Row]:
        return [c.after for c in self.changes if c.table == table and c.before is None and c.after]

    def removed(self, table: str) -> list[Row]:
        return [c.before for c in self.changes if c.table == table and c.after is None and c.before]

    def updated(self, table: str) -> list[tuple[Row, Row]]:
        return [
            (c.before, c.after)
            for c in self.changes
            if c.table == table and c.before is not None and c.after is not None
        ]

    def any_row(self, table: str) -> Row | None:
        for change in self.changes:
            if change.table == table:
                return change.after or change.before
        return None


def money(cents: Any, currency: Any) -> str:
    """ "RD$ 1,632" (cents only when there are)."""
    value = int(cents or 0)
    prefix = "US$" if currency == "USD" else "RD$"
    whole = f"{prefix} {abs(value) // 100:,}"
    return whole if value % 100 == 0 else f"{whole}.{abs(value) % 100:02d}"


def join(names: Sequence[str]) -> str:
    """ "a", "a y b", "a, b y c"."""
    if len(names) <= 1:
        return "".join(names)
    return t("analysis.changelog_ledger.and", head=", ".join(names[:-1]), last=names[-1])


class _Sentence:
    def __init__(self, kind: str, subject: str, target: str, rows: _Rows, names: Names) -> None:
        self.kind = kind
        self.subject = subject
        self.target = target
        self.rows = rows
        self.names = names

    def person(self, contact_id: Any) -> str:
        if contact_id is None:
            return t("analysis.changelog_ledger.someone")
        found = int(contact_id)
        if found == self.names.me:
            return t("analysis.changelog_ledger.you")
        name = self.names.contacts.get(found)
        if name is None:  # gone (merged, or created by a change now undone): its row here
            rows = [
                r
                for c in self.rows.changes
                if c.table == "contacts"
                for r in (c.before, c.after)
                if r
            ]
            row = next((r for r in rows if int(r.get("id", -1)) == found), None)
            name = None if row is None else str(row.get("name"))
        return name or t("analysis.changelog_ledger.person_number", id=found)

    def people(self, rows: Sequence[Row]) -> list[str]:
        ids = [r.get("contact_id") for r in rows if r.get("contact_id") != self.names.me]
        return [self.person(i) for i in dict.fromkeys(ids)]

    @property
    def group(self) -> str:
        row = self.rows.any_row("ledger_groups")
        if row is not None and row.get("name"):
            return str(row["name"])
        return self.subject


def _group_new(s: _Sentence) -> str | None:
    people = s.people(s.rows.added("ledger_members"))
    if people:
        return t("analysis.changelog_ledger.group_new_with", group=s.group, names=join(people))
    return t("analysis.changelog_ledger.group_new", group=s.group)


def _group(s: _Sentence) -> str | None:
    for before, after in s.rows.updated("ledger_groups"):
        if before.get("name") != after.get("name"):
            return t(
                "analysis.changelog_ledger.group_renamed",
                old=before.get("name"),
                new=after.get("name"),
            )
        if before.get("archived") != after.get("archived"):
            key = "group_archived" if after.get("archived") else "group_unarchived"
            return t(f"analysis.changelog_ledger.{key}", group=after.get("name"))
        if before.get("category_id") != after.get("category_id"):
            return t("analysis.changelog_ledger.group_category", group=after.get("name"))
    return None


def _members(s: _Sentence) -> str | None:
    added = s.people(s.rows.added("ledger_members"))
    removed = s.people(s.rows.removed("ledger_members"))
    if removed and s.kind == "group_member_resplit":
        entries = {
            int(r["entry_id"])
            for c in s.rows.changes
            if c.table == "ledger_splits"
            for r in (c.before, c.after)
            if r is not None
        }
        return t(
            "analysis.changelog_ledger.member_removed_resplit",
            names=join(removed),
            group=s.group,
            count=len(entries),
        )
    if removed:
        return t("analysis.changelog_ledger.member_removed", names=join(removed), group=s.group)
    if added:
        return t("analysis.changelog_ledger.member_added", names=join(added), group=s.group)
    return _leftover_toggle(s)


def _leftover_toggle(s: _Sentence) -> str | None:
    """ "Exchange differences of X count as settled again in G" (schema 22's toggle)."""
    changed = [
        after
        for before, after in s.rows.updated("ledger_members")
        if before.get("leftover_settled") != after.get("leftover_settled")
    ]
    people = s.people(changed)
    if not people:
        return None
    key = "leftover_on" if changed[0].get("leftover_settled") else "leftover_off"
    return t(f"analysis.changelog_ledger.{key}", names=join(people), group=s.group)


def _write_off(s: _Sentence) -> str | None:
    marked = [a for b, a in s.rows.updated("ledger_members") if a.get("written_off")]
    cleared = [a for b, a in s.rows.updated("ledger_members") if not a.get("written_off")]
    rows, key = (marked, "written_off") if marked else (cleared, "written_back")
    people = s.people(rows)
    if not people:
        return None
    suffix = "_one" if len(people) == 1 else "_many"
    return t(f"analysis.changelog_ledger.{key}{suffix}", names=join(people), group=s.group)


def _entry_text(row: Row) -> tuple[str, str]:
    return str(row.get("description") or ""), money(row.get("amount_cents"), row.get("currency"))


def _entry(s: _Sentence) -> str | None:
    added = s.rows.added("ledger_entries")
    if added:
        what, amount = _entry_text(added[0])
        return t("analysis.changelog_ledger.entry_added", what=what, amount=amount, group=s.group)
    removed = s.rows.removed("ledger_entries")
    if removed:
        what, amount = _entry_text(removed[0])
        return t("analysis.changelog_ledger.entry_deleted", what=what, amount=amount, group=s.group)
    updated = s.rows.updated("ledger_entries")
    if updated:
        what, _ = _entry_text(updated[0][1])
        return t("analysis.changelog_ledger.entry_changed", what=what, group=s.group)
    if s.rows.any_row("ledger_splits") is not None:
        return t("analysis.changelog_ledger.split_changed", group=s.group)
    return None


def _payment_line(s: _Sentence, row: Row) -> str:
    amount = money(row.get("amount_cents"), row.get("currency"))
    if row.get("from_contact") is None:
        return t("analysis.changelog_ledger.payment_unassigned", amount=amount)
    return t(
        "analysis.changelog_ledger.payment_between",
        source=s.person(row.get("from_contact")),
        target=s.person(row.get("to_contact")),
        amount=amount,
    )


def _covered(s: _Sentence, payment: Row) -> str:
    """ " (for El Gordo too)" when an inserted payment covers other people."""
    others = [
        r
        for r in s.rows.added("ledger_allocations")
        if r.get("contact_id") != payment.get("from_contact")
    ]
    if not others:
        return ""
    return t("analysis.changelog_ledger.covering", names=join(s.people(others)))


def _payment(s: _Sentence) -> str | None:
    added = s.rows.added("ledger_payments")
    if added:
        line = _payment_line(s, added[0]) + _covered(s, added[0])
        return t("analysis.changelog_ledger.payment_added", payment=line, group=s.group)
    removed = s.rows.removed("ledger_payments")
    if removed:
        line = _payment_line(s, removed[0])
        return t("analysis.changelog_ledger.payment_deleted", payment=line, group=s.group)
    for before, after in s.rows.updated("ledger_payments"):
        amount = money(after.get("amount_cents"), after.get("currency"))
        if before.get("from_contact") is None and after.get("from_contact") is not None:
            return t(
                "analysis.changelog_ledger.payment_assigned",
                amount=amount,
                name=s.person(after.get("from_contact")),
                group=s.group,
            )
        if not before.get("accepted") and after.get("accepted"):
            return t("analysis.changelog_ledger.payment_accepted", amount=amount, group=s.group)
    covered = _allocations_changed(s)
    if covered is not None:
        return covered
    for rows, key in (
        (s.rows.added("ledger_dismissals"), "cover_dismissed"),
        (s.rows.removed("ledger_dismissals"), "cover_asked"),
    ):
        if len(rows) > 1:
            return t(f"analysis.changelog_ledger.{key}_many", count=len(rows), group=s.group)
        if rows:
            return t(f"analysis.changelog_ledger.{key}", group=s.group)
    if s.rows.added("ledger_links"):
        return t("analysis.changelog_ledger.payment_linked", group=s.group)
    if s.rows.removed("ledger_links"):
        return t("analysis.changelog_ledger.payment_unlinked", group=s.group)
    return None


def _allocations_changed(s: _Sentence) -> str | None:
    """ "You changed who a payment of G covers: El Gordo too" when only an existing payment's
    allocations moved (the payment row itself does not change, so the sentence goes by the
    allocation rows: the people added, else the people taken out, else only the amounts)."""
    rows = [
        r for c in s.rows.changes if c.table == "ledger_allocations" for r in (c.after or c.before,)
    ]
    if not rows:
        return None
    count = len({r.get("payment_id") for r in rows if r})
    added = s.people(s.rows.added("ledger_allocations"))
    if added and count > 1:
        return t(
            "analysis.changelog_ledger.covering_changed_many",
            count=count,
            names=join(added),
            group=s.group,
        )
    if added:
        return t("analysis.changelog_ledger.covering_changed", names=join(added), group=s.group)
    gone = s.people(s.rows.removed("ledger_allocations"))
    if gone:
        return t("analysis.changelog_ledger.covering_removed", names=join(gone), group=s.group)
    return t("analysis.changelog_ledger.covering_amounts", group=s.group)


def _contact_id(target: str) -> int | None:
    prefix, _, raw = target.partition("-")
    return int(raw) if prefix == "contact" and raw.isdigit() else None


def _contact(s: _Sentence) -> str | None:
    added = s.rows.added("contacts")
    if s.kind == "contact" and added:
        return t("analysis.changelog_ledger.contact_added", name=added[0].get("name"))
    if s.kind == "contact_rename":
        for before, after in s.rows.updated("contacts"):
            return t(
                "analysis.changelog_ledger.contact_renamed",
                old=before.get("name"),
                new=after.get("name"),
            )
    if s.kind == "contact_alias":
        name = s.person(_contact_id(s.target))
        alias_added = s.rows.added("contact_aliases")
        if alias_added:
            alias = alias_added[0].get("alias")
            return t("analysis.changelog_ledger.alias_added", alias=alias, name=name)
        alias_removed = s.rows.removed("contact_aliases")
        if alias_removed:
            alias = alias_removed[0].get("alias")
            return t("analysis.changelog_ledger.alias_removed", alias=alias, name=name)
    if s.kind == "contact_merge":
        return t(
            "analysis.changelog_ledger.contact_merged",
            source=s.subject,
            target=s.person(_contact_id(s.target)),
        )
    return None


_BUILDERS: Mapping[str, Callable[[_Sentence], str | None]] = {
    "group_new": _group_new,
    "group": _group,
    "group_member": _members,
    "group_member_resplit": _members,
    "write_off": _write_off,
    "group_entry": _entry,
    "group_entry_delete": _entry,
    "group_payment": _payment,
    "group_payment_delete": _payment,
    "contact": _contact,
    "contact_rename": _contact,
    "contact_alias": _contact,
    "contact_merge": _contact,
    "review_people": lambda s: t("analysis.changelog_ledger.review_people"),
}


def sentence(
    kind: str, subject: str, target: str, changes: Sequence[Change], names: Names
) -> str | None:
    """The change as one sentence, or None for a kind that is not the ledger's (or rows that
    say nothing readable)."""
    builder = _BUILDERS.get(kind)
    if builder is None:
        return None
    try:
        return builder(_Sentence(kind, subject, target, _Rows(changes), names))
    except (KeyError, TypeError, ValueError):  # a row from an older schema: the generic text
        return None


def link_of(target: str, changes: Sequence[Change]) -> tuple[str, int] | None:
    """What a ledger change points to: ("group", id) or ("contact", id); a new group's id comes
    from its inserted row."""
    prefix, _, raw = target.partition("-")
    if prefix in ("group", "contact") and raw.isdigit():
        return prefix, int(raw)
    if prefix == "group":
        for change in changes:
            if change.table == "ledger_groups" and change.after is not None:
                return "group", int(change.after["id"])
    if prefix == "contact":
        for change in changes:
            if change.table == "contacts" and change.after is not None:
                return "contact", int(change.after["id"])
    return None
