"""Rutas de la bitácora: `GET /api/log` (paginado y con filtros), `PATCH /api/log/{id}` (el
motivo), `POST /api/log/{id}/undo` y el historial de una transacción.

La lógica está en `analysis.changelog` (base) y `analysis.changelog_rules` (pura); aquí se arma
la respuesta con el estado de «Deshacer» de cada entrada y su sesión de edición.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from finanzas.analysis import catalog, changelog, changelog_rules
from finanzas.analysis.spending import Movement
from finanzas.web.log_schemas import EntryOut, HistoryOut, LogOut, ReasonBody, RuleHintOut

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
PAGE = 50


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def matches(
    entry: changelog.Entry, kinds: set[str] | None, author: str | None, q: str | None
) -> bool:
    """Filtros de la vista: tipos, autor y texto (comercio, antes, después, motivo)."""
    if kinds is not None and entry.kind not in kinds:
        return False
    if author is not None and entry.author != author:
        return False
    if not q or not q.strip():
        return True
    text = " ".join(
        (entry.subject, entry.before_text, entry.after_text, entry.reason or "", entry.target)
    )
    return _fold(q.strip()) in _fold(text)


def rule_suggestions(
    conn: sqlite3.Connection, flow: Sequence[Movement] = ()
) -> list[changelog_rules.RuleSuggestion]:
    """Las reglas por comercio que se proponen hoy (de categorías que se pueden elegir). `flow`:
    los movimientos de hoy, para saber el comercio de cada transacción de un lote."""
    entries = [
        *changelog.load(conn, kind=changelog_rules.CATEGORY_KIND),
        *changelog.load(conn, kind=changelog_rules.BATCH_KIND),
    ]
    merchants = {m.fingerprint: m.merchant for m in flow}
    edits = changelog.category_edits(entries, changelog.undone(conn), merchants)
    found = changelog_rules.rule_suggestions(
        edits, changelog.merchant_rules(conn), changelog.rule_dismissals(conn)
    )
    known = catalog.load(conn)
    usable = {c.id for c in known.selectable()}
    return [s for s in found if s.category_id in usable]


def entry_views(
    conn: sqlite3.Connection,
    entries: Sequence[changelog.Entry],
    sessions_of: dict[int, changelog_rules.Session] | None = None,
    flow: Sequence[Movement] = (),
) -> list[EntryOut]:
    """Las entradas con su estado de «Deshacer» (ensayado con los días de `flow`, el flujo de
    hoy) y el mes de su transacción para el enlace."""
    done = changelog.undone(conn)
    present: Mapping[str, str] = {m.fingerprint: m.month for m in flow}
    days = {m.fingerprint: m.day for m in flow}
    return [
        EntryOut.of(
            e,
            changelog.undo_state(conn, e, done, days),
            None if sessions_of is None else sessions_of.get(e.id),
            present,
        )
        for e in entries
    ]


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @app.get("/api/log")
    def get_log(
        kind: Annotated[str | None, Query(max_length=400)] = None,
        author: Annotated[str | None, Query(pattern="^(usuario|claude)$")] = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = PAGE,
    ) -> LogOut:
        """Las entradas, la más reciente primero, con su sesión (calculada con toda la bitácora:
        los filtros no la cortan). `kind`: tipos separados por coma."""
        kinds = {k.strip() for k in kind.split(",") if k.strip()} if kind else None
        with connection() as conn:
            entries = changelog.load(conn)
            groups = changelog_rules.sessions([(e.id, e.at) for e in entries])
            sessions_of = {i: s for s in groups for i in s.ids}
            wanted = [e for e in entries if matches(e, kinds, author, q)]
            page = wanted[offset : offset + limit]
            items = entry_views(conn, page, sessions_of, load_flow(conn))
        return LogOut(
            items=items,
            total=len(wanted),
            offset=offset,
            kinds=sorted({e.kind for e in entries}),
        )

    @app.patch("/api/log/{entry_id}")
    def patch_log(entry_id: int, body: ReasonBody) -> EntryOut:
        """El motivo (≤ 500; vacío lo borra). Editarlo no es un cambio: no se registra."""
        with connection() as conn:
            try:
                with conn:
                    changelog.set_reason(conn, entry_id, body.reason)
            except LookupError:
                raise HTTPException(404, "entrada desconocida") from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return entry_views(conn, [changelog.get(conn, entry_id)], None, load_flow(conn))[0]

    @app.post("/api/log/{entry_id}/undo")
    def post_undo(entry_id: int) -> EntryOut:
        """Deshace la entrada; devuelve la entrada nueva que lo registra. 409 si ya no se puede
        (el mensaje dice qué entrada posterior deshacer primero)."""
        with connection() as conn:
            days = {m.fingerprint: m.day for m in load_flow(conn)}
            try:
                with conn:
                    made = changelog.undo(conn, entry_id, days)
            except LookupError:
                raise HTTPException(404, "entrada desconocida") from None
            except changelog.UndoBlocked as exc:
                raise HTTPException(409, str(exc)) from None
            return entry_views(conn, [changelog.get(conn, made)], None, load_flow(conn))[0]

    @app.get("/api/transactions/{fingerprint}/history")
    def get_history(fingerprint: str) -> HistoryOut:
        """Las entradas que tocan la transacción y, si su comercio ya recibió a mano la misma
        categoría en otras, esa pista («Las otras 2 veces lo pusiste en …»)."""
        with connection() as conn:
            flow = load_flow(conn)
            target = next((m for m in flow if m.fingerprint == fingerprint), None)
            if target is None:
                raise HTTPException(404, "transacción desconocida")
            items = entry_views(conn, changelog.load(conn, fingerprint), None, flow)
            hint = _hint(conn, target, flow)
        return HistoryOut(items=items, rule_hint=hint)

    def _hint(
        conn: sqlite3.Connection, target: Movement, flow: Sequence[Movement]
    ) -> RuleHintOut | None:
        known = catalog.load(conn)
        for found in rule_suggestions(conn, flow):
            category = known.by_id(found.category_id)
            if (
                found.merchant != target.merchant
                or target.fingerprint in found.fingerprints
                or category is None
                or category.ref == target.ref
            ):
                continue
            return RuleHintOut(
                merchant=found.merchant,
                category_id=category.id,
                category=category.name,
                count=found.count,
            )
        return None
