"""Rutas de Compartidos: todos los grupos y los gastos para «Nuevo grupo…».

Se registran antes que `/api/shared/{link_id}` (el id es un entero: `new-candidates` chocaría).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, Query

from finanzas.analysis import accounts as account_data
from finanzas.analysis import links, rates
from finanzas.analysis.spending import Movement
from finanzas.web import links as links_view
from finanzas.web import shared_list
from finanzas.web.schemas import CandidateOut
from finanzas.web.shared_schemas import SharedListOut

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]
AccountKeys = Annotated[str | None, Query(max_length=2000)]


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    parse_accounts: ParseAccounts,
    today: Callable[[], date],
) -> None:
    def context(
        conn: sqlite3.Connection, accounts: str | None
    ) -> tuple[links_view.Context, frozenset[str] | None]:
        infos = account_data.account_infos(conn)
        selected = parse_accounts(accounts, infos)
        ctx = links_view.context(
            load_flow(conn), links.load(conn), infos, rates.load(conn), suggest=False
        )
        return ctx, selected

    @app.get("/api/shared")
    def get_shared(accounts: AccountKeys = None) -> SharedListOut:
        """Todos los grupos compartidos y sus totales (ver `web.shared_list`)."""
        with connection() as conn:
            ctx, selected = context(conn, accounts)
        now = today()
        found = shared_list.build_shared_list(
            ctx.movements, ctx.groups, ctx.labels, ctx.rates, now, selected
        )
        return SharedListOut.of(found, ctx.labels, now.year)

    @app.get("/api/shared/new-candidates")
    def get_new_candidates(accounts: AccountKeys = None) -> list[CandidateOut]:
        """«Nuevo grupo…»: gastos sin vínculo de los últimos 120 días; `primary` = sugerido (ver
        `shared_list.is_suggested`), los sugeridos primero y en cada bloque el más reciente."""
        with connection() as conn:
            ctx, selected = context(conn, accounts)
        found = shared_list.new_candidates(ctx.movements, ctx.links, today(), ctx.rates, selected)
        return [
            CandidateOut.ranked(links_view.linked_tx(c.move, ctx.labels), c.suggested)
            for c in found
        ]
