"""Change log: the pure logic (no database, no HTTP).

- `Change`: a row touched by a change, with what it was before and what it became after.
- `changed_columns` and `can_undo`: what counts as a change and when it can be undone (the
  current state of those columns is still the entry's *after*).
- `sessions`: entries grouped by editing session (a break after `SESSION_GAP` without changes).
- `undone_ids`: which entries ended up undone (an "Undo" that was itself undone does not count).
- `rule_suggestions`: the proposed per-merchant rules (`possible_rule`).
- `describe`: the readable line for one side (before or after) when the caller gives none.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from michelito.analysis.categories import KIND_LABELS
from michelito.analysis.providers import display_name
from michelito.analysis.recurring import CADENCE_LABELS, GROUPS
from michelito.i18n import t

Row = dict[str, Any]

SESSION_GAP = timedelta(minutes=30)
RULE_MIN_TIMES = 2  # "only this one" with the same category on this many of the merchant's rows
CATEGORY_KIND = "category"
# Category change of several at once (`web.batch_edit`): it does not teach rules, but it does
# contradict them.
BATCH_KIND = "category_batch"

# Columns that do not count as a change (timestamps) and, per table, those edited without a
# change-log entry (a category's name, color and "hidden").
IGNORED_COLUMNS = frozenset(
    {"updated_at", "added_at", "reviewed_at", "created_at", "dismissed_at", "decided_at"}
)
IGNORED_BY_TABLE: Mapping[str, frozenset[str]] = {
    "categories": frozenset({"name", "color", "hidden"}),
}
# Tables where having no row is the same as having one with these values (`transaction_notes`
# deletes a row left empty): compared column by column, never the whole row.
SOFT_DEFAULTS: Mapping[str, Mapping[str, Any]] = {
    "transaction_notes": {"category_id": None, "one_off": 0, "note": None},
}


# Child tables that point to a parent (column, parent table) and what identifies each parent
# beyond its id (in case an id is reused: databases from before schema 15 or hand-made rows).
PARENT_COLUMNS: Mapping[str, tuple[str, str]] = {
    "link_members": ("link_id", "links"),
    "link_manual": ("link_id", "links"),
    "transaction_notes": ("category_id", "categories"),
    "merchant_categories": ("category_id", "categories"),
    "category_keywords": ("category_id", "categories"),
    "budget_caps": ("category_id", "categories"),
    "contact_aliases": ("contact_id", "contacts"),
    "ledger_members": ("group_id", "ledger_groups"),
    "ledger_entries": ("group_id", "ledger_groups"),
    "ledger_splits": ("entry_id", "ledger_entries"),
    "ledger_payments": ("group_id", "ledger_groups"),
    "ledger_allocations": ("payment_id", "ledger_payments"),
    "ledger_links": ("group_id", "ledger_groups"),
}
PARENT_IDENTITY: Mapping[str, tuple[str, ...]] = {
    "links": ("kind", "created_at"),
    "categories": ("builtin_key", "created_at"),
    "contacts": ("created_at",),
    "ledger_groups": ("created_at",),
    "ledger_entries": ("created_at",),
    "ledger_payments": ("created_at",),
}


@dataclass(frozen=True)
class Change:
    table: str
    key: Row  # the row's primary key
    before: Row | None  # None: it did not exist
    after: Row | None  # None: it was deleted
    columns: tuple[str, ...]  # what changed (for a new or deleted row: the whole row)
    # The parent the *before* points to (`links` or `categories`): its key (`row_key`) and its
    # identity back then (`PARENT_IDENTITY`); empty if it points to none.
    parent: Row = field(default_factory=dict)

    @property
    def row_key(self) -> str:
        return row_key(self.table, self.key)

    def to_json(self) -> Row:
        return {
            "table": self.table,
            "key": self.key,
            "before": self.before,
            "after": self.after,
            "columns": list(self.columns),
            "parent": self.parent,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Change:
        return cls(
            table=str(data["table"]),
            key=dict(data["key"]),
            before=None if data["before"] is None else dict(data["before"]),
            after=None if data["after"] is None else dict(data["after"]),
            columns=tuple(str(c) for c in data["columns"]),
            parent=dict(data.get("parent") or {}),
        )


def row_key(table: str, key: Mapping[str, Any]) -> str:
    return f"{table}:{json.dumps(list(key.values()), ensure_ascii=False)}"


def identity(table: str, row: Mapping[str, Any]) -> Row:
    return {c: row.get(c) for c in PARENT_IDENTITY[table]}


def changed_columns(table: str, before: Row | None, after: Row | None) -> tuple[str, ...]:
    """The columns that really changed (no timestamps nor what is not logged)."""
    soft = SOFT_DEFAULTS.get(table)
    if soft is not None:
        old, new = before or soft, after or soft
        return tuple(c for c in soft if old.get(c, soft[c]) != new.get(c, soft[c]))
    ignored = IGNORED_COLUMNS | IGNORED_BY_TABLE.get(table, frozenset())
    if before is None or after is None:
        row = after if before is None else before
        return tuple(c for c in (row or {}) if c not in ignored)
    return tuple(c for c in after if c not in ignored and before.get(c) != after.get(c))


def _matches(change: Change, current: Row | None) -> bool:
    soft = SOFT_DEFAULTS.get(change.table)
    if soft is not None:
        now, after = current or soft, change.after or soft
        return all(now.get(c, soft[c]) == after.get(c, soft[c]) for c in change.columns)
    if change.after is None:
        return current is None
    if current is None:
        return False
    return all(current.get(c) == change.after.get(c) for c in change.columns)


def can_undo(changes: Sequence[Change], current: Mapping[str, Row | None]) -> bool:
    """It can be undone if every touched row is still as the entry left it (`current`: today's
    row by `row_key`, None if it does not exist)."""
    return bool(changes) and all(_matches(c, current.get(c.row_key)) for c in changes)


@dataclass(frozen=True)
class Session:
    start: datetime
    end: datetime
    count: int
    ids: tuple[int, ...]  # newest to oldest


def sessions(stamps: Sequence[tuple[int, datetime]], gap: timedelta = SESSION_GAP) -> list[Session]:
    """Group (id, instant) pairs into sessions: a new one after more than `gap` without changes.
    Newest session first; inside, newest to oldest."""
    ordered = sorted(stamps, key=lambda s: (s[1], s[0]), reverse=True)
    found: list[list[tuple[int, datetime]]] = []
    for item in ordered:
        if found and found[-1][-1][1] - item[1] <= gap:
            found[-1].append(item)
        else:
            found.append([item])
    return [
        Session(start=g[-1][1], end=g[0][1], count=len(g), ids=tuple(i for i, _ in g))
        for g in found
    ]


def undone_ids(undoes: Mapping[int, int]) -> frozenset[int]:
    """The undone entries. `undoes`: id of each "Undo" -> the entry it undoes. An "Undo" that
    was later undone does not count (the newest wins)."""
    undone: set[int] = set()
    for undo_id in sorted(undoes, reverse=True):
        if undo_id not in undone:
            undone.add(undoes[undo_id])
    return frozenset(undone)


@dataclass(frozen=True)
class CategoryEdit:
    """An "only this one" correction from the change log (without undone entries or "Undo"s)."""

    entry_id: int
    merchant: str
    fingerprint: str
    category_id: int | None  # None: back to the automatic one
    # False: from a batch; counts as a contrary correction, but not toward a proposal.
    counts: bool = True


@dataclass(frozen=True)
class RuleSuggestion:
    merchant: str
    category_id: int
    fingerprints: tuple[str, ...]  # the corrected transactions, newest first

    @property
    def count(self) -> int:
        return len(self.fingerprints)


def rule_suggestions(
    edits: Iterable[CategoryEdit],
    rules: Mapping[str, int],
    dismissed: Iterable[tuple[str, int]],
) -> list[RuleSuggestion]:
    """Merchants that got the same category by hand ("only this one") on at least
    `RULE_MIN_TIMES` transactions and no contrary correction (another category, or back to the
    automatic one; also one from a batch, which does not count toward the minimum). Not proposed
    when the merchant's rule is already that one (`rules`) or it was dismissed (`dismissed`:
    merchant and category pairs). Never applied on its own."""
    skip = set(dismissed)
    by_merchant: dict[str, list[CategoryEdit]] = {}
    for edit in sorted(edits, key=lambda e: e.entry_id):
        if edit.merchant:
            by_merchant.setdefault(edit.merchant, []).append(edit)
    found: list[RuleSuggestion] = []
    for merchant, items in by_merchant.items():
        chosen = {e.category_id for e in items}
        if len(chosen) != 1:
            continue
        category = next(iter(chosen))
        if category is None or rules.get(merchant) == category or (merchant, category) in skip:
            continue
        fingerprints = tuple(dict.fromkeys(e.fingerprint for e in reversed(items) if e.counts))
        if len(fingerprints) >= RULE_MIN_TIMES:
            found.append(RuleSuggestion(merchant, category, fingerprints))
    return sorted(found, key=lambda s: s.merchant)


_ROLES = (
    "expense",
    "reimbursement",
    "leg",
    "contribution",
    "return",
    "capital",
    "mixed",
    "stored",
    "deposit",
    "reserved",
)
ROLE_LABELS = {role: t(f"analysis.changelog_rules.role_{role}") for role in _ROLES}
_LINK_KINDS = ("shared", "exchange", "investment", "cash_box", "reserve")
LINK_LABELS = {kind: t(f"analysis.changelog_rules.link_{kind}") for kind in _LINK_KINDS}
_ENTRY_LABELS = {
    kind: t(f"analysis.changelog_rules.entry_{kind}") for kind in ("initial", "income", "expense")
}
_MARK_LABELS = {
    status: t(f"analysis.changelog_rules.mark_{status}")
    for status in ("confirmed", "dismissed", "cancelled")
}
_NOTHING = "—"


def _money(cents: Any, currency: Any) -> str:
    value = int(cents or 0)
    prefix = "US$" if currency == "USD" else "RD$"
    return f"{prefix} {value // 100:,}.{value % 100:02d}"


def _row_text(table: str, row: Row, columns: Sequence[str], whole: bool) -> str:  # noqa: PLR0911
    if table == "link_members":
        return ROLE_LABELS.get(str(row.get("role")), str(row.get("role")))
    if table == "links":
        label = LINK_LABELS.get(str(row.get("kind")), t("analysis.changelog_rules.link"))
        if not whole:
            parts = [f"{c}: {row.get(c) if row.get(c) is not None else _NOTHING}" for c in columns]
            return f"{label} ({', '.join(parts)})"
        return label + (f" «{row['name']}»" if row.get("name") else "")
    if table == "link_manual":
        money = _money(row.get("amount_cents"), row.get("currency"))
        return t("analysis.changelog_rules.manual_reimbursement", amount=money)
    if table.startswith(("ledger_", "contact")):
        return _ledger_text(table, row)
    if table == "cash_entries":
        kind = _ENTRY_LABELS.get(str(row.get("kind")), t("analysis.changelog_rules.entry"))
        money = _money(row.get("amount_cents"), row.get("currency"))
        text = t("analysis.changelog_rules.cash_entry", kind=kind, amount=money, day=row.get("day"))
        if row.get("concept"):
            text = f"{text} «{row['concept']}»"
        if row.get("status") == "pending":
            text = f"{text} ({t('analysis.changelog_rules.cash_pending')})"
        return text
    if table.startswith("cash_"):
        return _cash_text(table, row)
    if table == "recurring_marks":
        status = _MARK_LABELS.get(str(row.get("status")), t("analysis.changelog_rules.mark_none"))
        cadence = str(row.get("cadence") or "")
        extra = [CADENCE_LABELS.get(cadence, cadence)] if cadence else []
        if row.get("group_key"):
            group = GROUPS.get(str(row["group_key"]), row["group_key"])
            extra.append(t("analysis.changelog_rules.in_group", group=group))
        left = row.get("installments_left")
        if left is not None:
            extra.append(t("analysis.changelog_rules.installments", count=left))
        return ", ".join([status, *extra])
    if table == "recurring_unions":
        if row.get("target") == row.get("merchant"):
            return t("analysis.changelog_rules.union_separate")
        return t("analysis.changelog_rules.union_with", name=display_name(str(row.get("target"))))
    if table in ("review_marks", "one_off_dismissals", "rule_dismissals"):
        return t("analysis.changelog_rules.reviewed")
    if table == "reserve_dismissals":
        return t("analysis.changelog_rules.suggestion_dismissed")
    if table == "budget_caps":
        return cap_text(row.get("cap_cents"))
    if table == "category_keywords":
        return f"«{row.get('keyword')}»"
    if table == "categories":
        kind = str(row.get("kind"))
        return f"{row.get('name')} ({KIND_LABELS.get(kind, kind)})"
    if table == "transaction_notes":
        return ", ".join(_note_text(c, row.get(c)) for c in columns) or _NOTHING
    return ", ".join(f"{c}: {row.get(c)}" for c in columns) or _NOTHING


def _cash_text(table: str, row: Row) -> str:
    """A row of the schema 23 cash tables, short."""
    if table == "cash_schedules":
        kind = t(f"analysis.changelog_rules.cash_schedule_{row.get('kind')}")
        text = t(
            "analysis.changelog_rules.cash_schedule",
            kind=kind,
            concept=row.get("concept"),
            amount=_money(row.get("amount_cents"), row.get("currency")),
        )
        return text + (
            f", {t('analysis.changelog_rules.cash_schedule_paused')}" if row.get("paused") else ""
        )
    if table == "cash_skips":
        return t("analysis.changelog_rules.cash_skip", day=row.get("day"))
    if table == "cash_spent_direct":
        return t("analysis.changelog_rules.cash_spent_direct")
    if table == "cash_reconciliations":
        return t("analysis.changelog_rules.cash_reconciliation", month=row.get("month"))
    return ", ".join(f"{k}: {v}" for k, v in row.items()) or _NOTHING


def _ledger_text(table: str, row: Row) -> str:
    """A row of the shared ledger, short."""
    money = _money(row.get("amount_cents"), row.get("currency"))
    if table == "contacts":
        return str(row.get("name") or _NOTHING)
    if table == "contact_aliases":
        return f"«{row.get('alias')}»"
    if table == "ledger_groups":
        name = t("analysis.changelog_rules.ledger_group", name=row.get("name"))
        return name + (t("analysis.changelog_rules.ledger_archived") if row.get("archived") else "")
    if table == "ledger_members":
        if row.get("written_off"):
            return t("analysis.changelog_rules.ledger_member_written_off")
        return t("analysis.changelog_rules.ledger_member")
    if table == "ledger_entries":
        return t("analysis.changelog_rules.ledger_entry", what=row.get("description"), amount=money)
    if table == "ledger_splits":
        share = _money(row.get("share_cents"), None)
        return t("analysis.changelog_rules.ledger_split", amount=share)
    if table == "ledger_payments":
        return t("analysis.changelog_rules.ledger_payment", amount=money)
    if table == "ledger_allocations":
        share = _money(row.get("amount_cents"), None)
        return t("analysis.changelog_rules.ledger_allocation", amount=share)
    if table == "ledger_settings":
        return t("analysis.changelog_rules.ledger_setting")
    return t("analysis.changelog_rules.ledger_link")


def cap_text(cents: Any) -> str:
    """The cap as the change log shows it ("cap RD$ 16,500"), or "no budget" when None."""
    if cents is None:
        return t("analysis.changelog_rules.no_budget")
    return t("analysis.changelog_rules.cap", amount=f"{int(cents) // 100:,}")


def _note_text(column: str, value: Any) -> str:
    if column == "note":
        return str(value) if value else t("analysis.changelog_rules.no_note")
    if column == "one_off":
        return t(
            "analysis.changelog_rules.one_off" if value else "analysis.changelog_rules.not_one_off"
        )
    if value is None:
        return t("analysis.changelog_rules.automatic_category")
    return t("analysis.changelog_rules.category_number", id=value)


def describe(changes: Sequence[Change], side: str) -> str:
    """A short line for one side (`before` or `after`) of the touched rows."""
    parts: list[str] = []
    for change in changes:
        row = change.before if side == "before" else change.after
        if row is None:
            continue
        whole = change.before is None or change.after is None
        text = _row_text(change.table, row, change.columns, whole)
        if text not in parts:
            parts.append(text)
    if not parts:
        return _NOTHING
    shown = ", ".join(parts[:3])
    return (
        shown
        if len(parts) <= 3
        else t("analysis.changelog_rules.and_more", shown=shown, count=len(parts) - 3)
    )
