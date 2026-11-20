"""JSON models of the change log (`/api/log`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from michelito.analysis import changelog, changelog_ledger
from michelito.analysis.changelog_rules import Session


class Toggle(BaseModel):
    """An original change's undo state: undone now, how many times it toggled and when last."""

    undone: bool = False
    count: int = 0
    last_at: str | None = None


class SideOut(BaseModel):
    """One side of an entry: the readable line and the rows as they were (JSON)."""

    text: str
    rows: dict[str, list[dict[str, Any]]]


class EntryOut(BaseModel):
    id: int
    at: str  # ISO with zone (UTC)
    author: str  # "user" | "claude"
    kind: str
    target_type: str
    target: str
    subject: str
    merchant: str | None
    before: SideOut
    after: SideOut
    affected: int
    fingerprints: list[str]
    reason: str | None
    undoes: int | None  # an audit record ("Undo"); the list only shows originals (None)
    undone: bool  # the original is undone now ("Redo" applies)
    can_undo: bool
    can_redo: bool = False
    undo_message: str  # why the action that applies (undo or redo) cannot be done now
    blocked_by: int | None
    toggles: int = 0  # how many times it was undone or redone
    toggled_at: str | None = None  # the last time
    # A sentence for Shared's changes ("You removed Javier from the group …"; None: before/after).
    summary: str | None = None
    # What a change that is not a transaction's points to: "group" or "contact" and its id.
    link_kind: str | None = None
    link_id: int | None = None
    # For the link: the transaction (the target one or the first affected) and the merchant.
    fingerprint: str | None
    month: str | None  # that transaction's month (None: it no longer exists)
    session_start: str | None = None
    session_end: str | None = None
    session_count: int | None = None

    @classmethod
    def of(
        cls,
        entry: changelog.Entry,
        state: changelog.UndoState,
        session: Session | None = None,
        present: Mapping[str, str] | None = None,
        toggle: Toggle | None = None,
        names: changelog_ledger.Names | None = None,
    ) -> EntryOut:
        """`present`: fingerprint -> month of the transactions that exist today (for the link).
        `toggle`: the original's state (undone, redo, records); `names`: for Shared's text."""

        def side(which: str) -> SideOut:
            rows: dict[str, list[dict[str, Any]]] = {}
            for change in entry.changes:
                row = change.before if which == "before" else change.after
                if row is not None:
                    rows.setdefault(change.table, []).append(row)
            text = entry.before_text if which == "before" else entry.after_text
            return SideOut(text=text, rows=rows)

        known = names or changelog_ledger.Names()
        summary = changelog_ledger.sentence(
            entry.kind, entry.subject, entry.target, entry.changes, known
        )
        linked = (
            changelog_ledger.link_of(entry.target, entry.changes)
            if entry.kind in changelog_ledger.LEDGER_KINDS
            else None
        )
        if linked is not None and names is not None:
            pool = known.groups if linked[0] == "group" else known.contacts
            linked = linked if linked[1] in pool else None
        turn = toggle or Toggle(undone=state.undone)
        candidates = [entry.target] if entry.target_type == "transaction" else []
        candidates += list(entry.fingerprints)
        link = next((fp for fp in candidates if present is None or fp in present), None)
        return cls(
            id=entry.id,
            at=entry.at.isoformat(),
            author=entry.author,
            kind=entry.kind,
            target_type=entry.target_type,
            target=entry.target,
            subject=entry.subject,
            merchant=entry.merchant,
            before=side("before"),
            after=side("after"),
            affected=entry.affected,
            fingerprints=list(entry.fingerprints),
            reason=entry.reason,
            undoes=entry.undoes,
            undone=turn.undone,
            can_undo=state.allowed and not turn.undone,
            can_redo=state.allowed and turn.undone,
            undo_message="" if state.allowed else state.message,
            blocked_by=state.blocked_by,
            toggles=turn.count,
            toggled_at=turn.last_at,
            summary=summary,
            link_kind=None if linked is None else linked[0],
            link_id=None if linked is None else linked[1],
            fingerprint=link,
            month=None if present is None or link is None else present.get(link),
            session_start=None if session is None else session.start.isoformat(),
            session_end=None if session is None else session.end.isoformat(),
            session_count=None if session is None else session.count,
        )


class LogOut(BaseModel):
    items: list[EntryOut]
    total: int  # the ones matching the filters
    offset: int
    kinds: list[str]  # the kinds present in the log (for the filter)


class ReasonBody(BaseModel):
    reason: str | None = Field(default=None, max_length=changelog.REASON_MAX)


class RuleHintOut(BaseModel):
    """The "the other 2 times you put it in X" hint (the merchant got that category by hand)."""

    merchant: str
    category_id: int
    category: str
    count: int


class HistoryOut(BaseModel):
    items: list[EntryOut]
    rule_hint: RuleHintOut | None
