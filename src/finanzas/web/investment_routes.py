"""Rutas de Inversiones (`/api/investments`): la lista con sus totales, crear una, sumar o quitar
movimientos, cambiar el tipo de un crédito, renombrar y «Dar por perdida».

Las cuentas están en `analysis.investments` y `web.investment_list`; aquí se valida el pedido y
se escribe en una transacción (`links`). `/api/investments/open` va antes que
`/api/investments/{investment_id}` (el id es un entero).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from finanzas.analysis import accounts as account_data
from finanzas.analysis import changelog, links, rates, review_marks, shared
from finanzas.analysis.spending import Movement
from finanzas.web import edit_log, investment_list
from finanzas.web import links as links_view
from finanzas.web.investment_schemas import (
    InvestmentBody,
    InvestmentListOut,
    InvestmentOut,
    InvestmentPatch,
    MemberBody,
    RoleBody,
)
from finanzas.web.schemas import CandidateOut, InvestmentRefOut

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]
AccountKeys = Annotated[str | None, Query(max_length=2000)]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (links.AlreadyLinked, sqlite3.IntegrityError) as exc:  # otra pestaña lo enlazó
        detail = str(exc) if isinstance(exc, links.AlreadyLinked) else ""
        raise HTTPException(409, detail or "la transacción ya está en otro vínculo") from None
    except links.LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc) or "inversión desconocida") from None


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    parse_accounts: ParseAccounts,
    today: Callable[[], date],
) -> None:
    def context(conn: sqlite3.Connection, suggest: bool = False) -> links_view.Context:
        return links_view.context(
            load_flow(conn),
            links.load(conn),
            account_data.account_infos(conn),
            rates.load(conn),
            suggest=suggest,
            reviewed=review_marks.load(conn) if suggest else (),
        )

    def one(conn: sqlite3.Connection, investment_id: int) -> InvestmentOut:
        ctx = context(conn)
        state = ctx.investment_states.get(investment_id)
        if state is None:
            raise HTTPException(404, "inversión desconocida")
        found = investment_list.build_list({state.id: state}, ctx.rates, today())
        return InvestmentOut.of(found.rows[0], ctx.labels)

    def track(
        conn: sqlite3.Connection, investment_id: int
    ) -> AbstractContextManager[changelog.Draft]:
        """La entrada «inversión» de la bitácora (crear, sumar, quitar, cambiar el tipo,
        renombrar, dar por perdida)."""
        return changelog.track(
            conn,
            "inversion",
            "vinculo",
            str(investment_id),
            edit_log.link_subject(conn, investment_id),
        )

    def movement(ctx: links_view.Context, fingerprint: str) -> Movement:
        found = ctx.movement(fingerprint)
        if found is None:
            raise HTTPException(404, "transacción desconocida")
        return found

    def check_member(ctx: links_view.Context, move: Movement, body: MemberBody) -> None:
        if ctx.links.is_linked(move.fingerprint):
            raise links.AlreadyLinked("la transacción ya está en otro vínculo")
        if body.role == "contribution" and not links_view.can_invest(ctx, move):
            raise links.LinkError("solo un débito de una cuenta bancaria puede ser un aporte")
        if body.role != "contribution" and not links_view.can_invest_credit(ctx, move):
            raise links.LinkError("solo un crédito de una cuenta bancaria puede ser un cobro")

    @app.get("/api/investments")
    def get_investments(accounts: AccountKeys = None) -> InvestmentListOut:
        """Todas las inversiones y sus totales (ver `web.investment_list`)."""
        with connection() as conn:
            ctx = context(conn)
            selected = parse_accounts(accounts, account_data.account_infos(conn))
        now = today()
        found = investment_list.build_list(ctx.investment_states, ctx.rates, now, selected)
        return InvestmentListOut.of(found, ctx.labels, now.year)

    @app.get("/api/investments/open")
    def get_open_investments(include_lost: bool = False) -> list[InvestmentRefOut]:
        """Las inversiones a las que se puede sumar algo, la más reciente primero; con
        `include_lost=true` (para un crédito), también las dadas por perdidas."""
        with connection() as conn:
            ctx = context(conn)
        found = investment_list.open_investments(ctx.investment_states, include_lost)
        return [InvestmentRefOut.ref(s) for s in found]

    @app.post("/api/investments", status_code=201)
    def post_investment(body: InvestmentBody) -> InvestmentOut:
        """Nueva inversión con este débito como primer aporte."""
        with connection() as conn:
            ctx = context(conn)
            target = movement(ctx, body.fingerprint)
            with _errors(), conn, track(conn, 0) as draft:
                check_member(ctx, target, MemberBody(fingerprint=body.fingerprint))
                found = links.create_investment(
                    conn, target.fingerprint, with_whom=body.with_whom, name=body.name
                )
                draft.target, draft.subject = str(found), edit_log.link_subject(conn, found)
            return one(conn, found)

    @app.get("/api/investments/{investment_id}")
    def get_investment(investment_id: int) -> InvestmentOut:
        with connection() as conn:
            return one(conn, investment_id)

    @app.patch("/api/investments/{investment_id}")
    def patch_investment(investment_id: int, body: InvestmentPatch) -> InvestmentOut:
        """Nombre, «Con quién» y «Dada por perdida» (o deshacerlo)."""
        given = body.model_fields_set
        with connection() as conn:
            with _errors(), conn, track(conn, investment_id):
                links.set_investment(
                    conn,
                    investment_id,
                    name=body.name if "name" in given else ...,
                    with_whom=body.with_whom if "with_whom" in given else ...,
                    written_off=body.written_off,
                )
            return one(conn, investment_id)

    @app.post("/api/investments/{investment_id}/members")
    def post_member(investment_id: int, body: MemberBody) -> InvestmentOut:
        """Suma un aporte (un débito) o un crédito con su tipo."""
        with connection() as conn:
            ctx = context(conn)
            target = movement(ctx, body.fingerprint)
            with _errors(), conn, track(conn, investment_id):
                if ctx.links.investment(investment_id) is None:
                    raise LookupError(f"inversión desconocida: {investment_id}")
                check_member(ctx, target, body)
                state = ctx.investment_states.get(investment_id)
                if (
                    body.role != "contribution"
                    and state is not None
                    and target.day < state.first.day
                ):
                    first = state.first.day.isoformat()
                    raise links.LinkError(
                        f"un cobro no puede ser anterior al primer aporte ({first})"
                    )
                links.add_investment_member(
                    conn,
                    investment_id,
                    target.fingerprint,
                    body.role,
                    abs(shared.gross(target)),
                    body.capital,
                )
            return one(conn, investment_id)

    @app.put("/api/investments/{investment_id}/members/{fingerprint}")
    def put_member(investment_id: int, fingerprint: str, body: RoleBody) -> InvestmentOut:
        """Cambia el tipo de un crédito (rendimiento, capital o mixto con su capital)."""
        with connection() as conn:
            ctx = context(conn)
            target = movement(ctx, fingerprint)
            with _errors(), conn, track(conn, investment_id):
                links.set_investment_role(
                    conn,
                    investment_id,
                    fingerprint,
                    body.role,
                    abs(shared.gross(target)),
                    body.capital,
                )
            return one(conn, investment_id)

    @app.delete("/api/investments/{investment_id}/members/{fingerprint}")
    def delete_member(investment_id: int, fingerprint: str) -> Response:
        """Quita el movimiento. Con el último aporte se borra la inversión (sus créditos quedan
        libres): 204. Si no, la inversión al día."""
        with connection() as conn:
            with _errors(), conn, track(conn, investment_id):
                deleted = links.remove_investment_member(conn, investment_id, fingerprint)
            if deleted:
                return Response(status_code=204)
            return JSONResponse(one(conn, investment_id).model_dump())

    @app.get("/api/investments/{investment_id}/candidates")
    def get_candidates(investment_id: int, kind: str = "credit") -> list[CandidateOut]:
        """Lo que se puede sumar: `kind=contribution` (débitos) o `credit` (créditos); los
        propuestos para esta inversión primero y primarios."""
        if kind not in ("contribution", "credit"):
            raise HTTPException(422, "kind es «contribution» o «credit»")
        with connection() as conn:
            ctx = context(conn, suggest=True)
        state = ctx.investment_states.get(investment_id)
        if state is None:
            raise HTTPException(404, "inversión desconocida")
        pick = (
            investment_list.contribution_candidates
            if kind == "contribution"
            else investment_list.credit_candidates
        )
        found = pick(state, ctx.movements, ctx.links, ctx.investment_suggestions, ctx.banks)
        return [
            CandidateOut.ranked(links_view.linked_tx(c.move, ctx.labels), c.primary) for c in found
        ]
