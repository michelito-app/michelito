"""Rutas de «Para revisar»: lo del mes, el historial y "Ya lo revisé"."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from finanzas.analysis import accounts as account_data
from finanzas.analysis import catalog, changelog, links, rates, review_marks
from finanzas.analysis import one_off_dismissals as dismissals
from finanzas.analysis import recurring_marks as marks
from finanzas.analysis.review import Kind
from finanzas.analysis.spending import Movement
from finanzas.web import budget as budget_view
from finanzas.web import edit_log, log_routes, summary
from finanzas.web import review as review_view
from finanzas.web.budget_routes import load_inputs
from finanzas.web.review_schemas import ReviewBody, ReviewItemOut, ReviewMarkOut

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]


def register(
    app: FastAPI, connection: Connection, load_flow: LoadFlow, parse_accounts: ParseAccounts
) -> None:
    def context(
        conn: sqlite3.Connection, flow: Sequence[Movement], accounts: str | None
    ) -> review_view.Context:
        infos = account_data.account_infos(conn)
        known = catalog.load(conn)
        linked = links.load(conn)
        rules = [
            (s, found.name)
            for s in log_routes.rule_suggestions(conn, flow)
            if (found := known.by_id(s.category_id)) is not None
        ]
        return review_view.Context(
            flow=flow,
            accounts=infos,
            rates=rates.load(conn),
            marks=marks.load_for(conn, flow),
            unions=marks.load_unions(conn),
            reviewed=review_marks.load(conn),
            dismissed=dismissals.load(conn),
            selected=parse_accounts(accounts, infos),
            links=linked,
            rules=rules,
            # Las sugerencias de vínculo no dependen del día de hoy (solo de los vencimientos).
            reserve_hints=budget_view.link_hints(
                load_inputs(conn, flow, date.today(), with_marks=True), linked.fingerprints
            ),
        )

    @app.get("/api/review")
    def get_review(
        month: Annotated[str, Query(pattern=_MONTH_PATTERN)],
        accounts: Annotated[str | None, Query(max_length=2000)] = None,
        reviewed: bool = False,
    ) -> list[ReviewItemOut]:
        """Lo del mes para revisar; con `reviewed=true` también lo ya revisado."""
        with connection() as conn:
            flow = load_flow(conn)
            views = review_view.month_items(context(conn, flow, accounts), month)
        return [ReviewItemOut.of(v) for v in views if reviewed or not v.item.reviewed]

    @app.get("/api/review/history")
    def get_review_history(
        accounts: Annotated[str | None, Query(max_length=2000)] = None,
        kind: Kind | None = None,
    ) -> list[ReviewItemOut]:
        """Pendiente y revisado de los últimos meses con datos, del más reciente al más viejo."""
        with connection() as conn:
            flow = load_flow(conn)
            ctx = context(conn, flow, accounts)
            options = summary.month_options(flow, ctx.accounts, ctx.selected)
            months = [o.month for o in options[: review_view.HISTORY_MONTHS]]
            views = review_view.history(ctx, months, kind)
        return [ReviewItemOut.of(v) for v in views]

    @app.put("/api/review/{kind}/{fingerprint}")
    def put_review(kind: Kind, fingerprint: str, body: ReviewBody) -> ReviewMarkOut:
        """Marca «Ya lo revisé» (o lo deshace). En un gasto único es «No es único»; en una regla
        posible, «Descartar» (para siempre: esa categoría no se vuelve a proponer para el
        comercio). Queda en la bitácora."""
        with connection() as conn:
            flow = load_flow(conn)
            target = next((m for m in flow if m.fingerprint == fingerprint), None)
            if target is None:
                raise HTTPException(404, "transacción desconocida")
            if kind == "regla_posible":
                discard_rule(conn, target, body.reviewed, flow)
                return ReviewMarkOut(kind=kind, fingerprint=fingerprint, reviewed=body.reviewed)
            with (
                conn,
                changelog.track(
                    conn,
                    "revisado",
                    "transaccion",
                    fingerprint,
                    edit_log.subject(target),
                    before="revisado" if not body.reviewed else "por revisar",
                    after="revisado" if body.reviewed else "por revisar",
                    merchant=target.merchant,
                    fingerprints=[fingerprint],
                ),
            ):
                if kind == "unico":
                    dismissals.set_dismissed(conn, fingerprint, body.reviewed)
                else:
                    review_marks.set_reviewed(conn, fingerprint, kind, body.reviewed)
        return ReviewMarkOut(kind=kind, fingerprint=fingerprint, reviewed=body.reviewed)

    def discard_rule(
        conn: sqlite3.Connection, target: Movement, reviewed: bool, flow: Sequence[Movement]
    ) -> None:
        """Descarta la regla que se propone para el comercio (o, con `reviewed=false`, vuelve a
        permitir proponerlas todas)."""
        merchant = target.merchant
        found = next(
            (s for s in log_routes.rule_suggestions(conn, flow) if s.merchant == merchant), None
        )
        if reviewed and found is None:
            raise HTTPException(404, "no hay una regla propuesta para ese comercio")
        with (
            conn,
            changelog.track(
                conn,
                "revisado",
                "comercio",
                merchant,
                merchant,
                before="regla propuesta" if reviewed else "descartada",
                after="descartada" if reviewed else "se puede proponer",
                merchant=merchant,
                fingerprints=() if found is None else found.fingerprints,
            ),
        ):
            if found is not None and reviewed:
                changelog.dismiss_rule(conn, merchant, found.category_id)
            elif not reviewed:
                conn.execute("DELETE FROM rule_dismissals WHERE merchant = ?", (merchant,))
