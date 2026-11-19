"""Modelos JSON de la bitácora (`/api/log`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from finanzas.analysis import changelog
from finanzas.analysis.changelog_rules import Session


class SideOut(BaseModel):
    """Un lado de la entrada: la línea legible y las filas tal como estaban (JSON)."""

    text: str
    rows: dict[str, list[dict[str, Any]]]


class EntryOut(BaseModel):
    id: int
    at: str  # ISO con zona (UTC)
    author: str  # "usuario" | "claude"
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
    undoes: int | None
    undone: bool
    can_undo: bool
    undo_message: str
    blocked_by: int | None
    # Para el enlace: la transacción (la del objetivo o la primera afectada) y el comercio.
    fingerprint: str | None
    month: str | None  # el mes de esa transacción (None: ya no aparece)
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
    ) -> EntryOut:
        """`present`: huella -> mes de las transacciones que hoy existen (para el enlace)."""

        def side(which: str) -> SideOut:
            rows: dict[str, list[dict[str, Any]]] = {}
            for change in entry.changes:
                row = change.before if which == "before" else change.after
                if row is not None:
                    rows.setdefault(change.table, []).append(row)
            text = entry.before_text if which == "before" else entry.after_text
            return SideOut(text=text, rows=rows)

        candidates = [entry.target] if entry.target_type == "transaccion" else []
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
            undone=state.undone,
            can_undo=state.allowed,
            undo_message=state.message,
            blocked_by=state.blocked_by,
            fingerprint=link,
            month=None if present is None or link is None else present.get(link),
            session_start=None if session is None else session.start.isoformat(),
            session_end=None if session is None else session.end.isoformat(),
            session_count=None if session is None else session.count,
        )


class LogOut(BaseModel):
    items: list[EntryOut]
    total: int  # las que cumplen los filtros
    offset: int
    kinds: list[str]  # los tipos que hay en la bitácora (para el filtro)


class ReasonBody(BaseModel):
    reason: str | None = Field(default=None, max_length=changelog.REASON_MAX)


class RuleHintOut(BaseModel):
    """«Las otras 2 veces lo pusiste en Delivery» (el comercio ya recibió esa categoría a mano)."""

    merchant: str
    category_id: int
    category: str
    count: int


class HistoryOut(BaseModel):
    items: list[EntryOut]
    rule_hint: RuleHintOut | None
