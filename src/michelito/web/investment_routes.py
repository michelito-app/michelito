"""Investments routes (`/api/investments`): the list with its totals, creating one, adding or
removing movements, changing a credit's role, renaming and "write off".

The math lives in `analysis.investments` and `web.investment_list`; here the request is
validated and written in one transaction (`links`). `/api/investments/open` is registered before
`/api/investments/{investment_id}` (the id is an integer).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from michelito.analysis import accounts as account_data
from michelito.analysis import changelog, links, rates, review_marks, shared
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import edit_log, investment_list
from michelito.web import links as links_view
from michelito.web.investment_schemas import (
    InvestmentBody,
    InvestmentListOut,
    InvestmentOut,
    InvestmentPatch,
    MemberBody,
    RoleBody,
)
from michelito.web.schemas import CandidateOut, InvestmentRefOut

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]
AccountKeys = Annotated[str | None, Query(max_length=2000)]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (links.AlreadyLinked, sqlite3.IntegrityError) as exc:  # another tab linked it
        detail = str(exc) if isinstance(exc, links.AlreadyLinked) else ""
        raise HTTPException(409, detail or t("web.already_linked")) from None
    except links.LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc) or t("web.investment.unknown")) from None


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
            raise HTTPException(404, t("web.investment.unknown"))
        found = investment_list.build_list({state.id: state}, ctx.rates, today())
        return InvestmentOut.of(found.rows[0], ctx.labels)

    def track(
        conn: sqlite3.Connection, investment_id: int
    ) -> AbstractContextManager[changelog.Draft]:
        """The "investment" log entry (create, add, remove, change the role, rename, write
        off)."""
        return changelog.track(
            conn,
            "investment",
            "link",
            str(investment_id),
            edit_log.link_subject(conn, investment_id),
        )

    def movement(ctx: links_view.Context, fingerprint: str) -> Movement:
        found = ctx.movement(fingerprint)
        if found is None:
            raise HTTPException(404, t("web.unknown_transaction"))
        return found

    def check_member(ctx: links_view.Context, move: Movement, body: MemberBody) -> None:
        if ctx.links.is_linked(move.fingerprint):
            raise links.AlreadyLinked(t("web.already_linked"))
        if body.role == "contribution" and not links_view.can_invest(ctx, move):
            raise links.LinkError(t("web.investment.only_bank_debit"))
        if body.role != "contribution" and not links_view.can_invest_credit(ctx, move):
            raise links.LinkError(t("web.investment.only_bank_credit"))

    @app.get("/api/investments")
    def get_investments(accounts: AccountKeys = None) -> InvestmentListOut:
        """Every investment and its totals (see `web.investment_list`)."""
        with connection() as conn:
            ctx = context(conn)
            selected = parse_accounts(accounts, account_data.account_infos(conn))
        now = today()
        found = investment_list.build_list(ctx.investment_states, ctx.rates, now, selected)
        return InvestmentListOut.of(found, ctx.labels, now.year)

    @app.get("/api/investments/open")
    def get_open_investments(include_lost: bool = False) -> list[InvestmentRefOut]:
        """The investments something can be added to, newest first; with `include_lost=true` (for
        a credit), also the written-off ones."""
        with connection() as conn:
            ctx = context(conn)
        found = investment_list.open_investments(ctx.investment_states, include_lost)
        return [InvestmentRefOut.ref(s) for s in found]

    @app.post("/api/investments", status_code=201)
    def post_investment(body: InvestmentBody) -> InvestmentOut:
        """A new investment with this debit as its first contribution."""
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
        """Name, "with whom" and "written off" (or undoing it)."""
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
        """Adds a contribution (a debit) or a credit with its role."""
        with connection() as conn:
            ctx = context(conn)
            target = movement(ctx, body.fingerprint)
            with _errors(), conn, track(conn, investment_id):
                if ctx.links.investment(investment_id) is None:
                    raise LookupError(t("web.investment.unknown_id", investment_id=investment_id))
                check_member(ctx, target, body)
                state = ctx.investment_states.get(investment_id)
                if (
                    body.role != "contribution"
                    and state is not None
                    and target.day < state.first.day
                ):
                    first = state.first.day.isoformat()
                    raise links.LinkError(t("web.investment.return_before_first", first=first))
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
        """Changes a credit's role (return, capital, or mixed with its capital part)."""
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
        """Removes the movement. Removing the last contribution deletes the investment (its credits
        are freed): 204. Otherwise, the up-to-date investment."""
        with connection() as conn:
            with _errors(), conn, track(conn, investment_id):
                deleted = links.remove_investment_member(conn, investment_id, fingerprint)
            if deleted:
                return Response(status_code=204)
            return JSONResponse(one(conn, investment_id).model_dump())

    @app.get("/api/investments/{investment_id}/candidates")
    def get_candidates(investment_id: int, kind: str = "credit") -> list[CandidateOut]:
        """What can be added: `kind=contribution` (debits) or `credit` (credits); the ones
        suggested for this investment first, and primary."""
        if kind not in ("contribution", "credit"):
            raise HTTPException(422, t("web.investment.kind_values"))
        with connection() as conn:
            ctx = context(conn, suggest=True)
        state = ctx.investment_states.get(investment_id)
        if state is None:
            raise HTTPException(404, t("web.investment.unknown"))
        pick = (
            investment_list.contribution_candidates
            if kind == "contribution"
            else investment_list.credit_candidates
        )
        found = pick(state, ctx.movements, ctx.links, ctx.investment_suggestions, ctx.banks)
        return [
            CandidateOut.ranked(links_view.linked_tx(c.move, ctx.labels), c.primary) for c in found
        ]
