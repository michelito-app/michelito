"""Shared routes: every group and the expenses for "New group…".

They are registered before `/api/shared/{link_id}` (the id is an integer: `new-candidates` would
clash otherwise).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, Query

from michelito.analysis import accounts as account_data
from michelito.analysis import links, rates
from michelito.analysis.spending import Movement
from michelito.web import links as links_view
from michelito.web import shared_list
from michelito.web.schemas import CandidateOut
from michelito.web.shared_schemas import SharedListOut

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
        """Every shared group and its totals (see `web.shared_list`)."""
        with connection() as conn:
            ctx, selected = context(conn, accounts)
        now = today()
        found = shared_list.build_shared_list(
            ctx.movements, ctx.groups, ctx.labels, ctx.rates, now, selected
        )
        return SharedListOut.of(found, ctx.labels, now.year)

    @app.get("/api/shared/new-candidates")
    def get_new_candidates(accounts: AccountKeys = None) -> list[CandidateOut]:
        """The "New group…" options: unlinked expenses from the last 120 days; `primary` =
        suggested (see `shared_list.is_suggested`), suggested ones first and the most recent
        first in each block."""
        with connection() as conn:
            ctx, selected = context(conn, accounts)
        found = shared_list.new_candidates(ctx.movements, ctx.links, today(), ctx.rates, selected)
        return [
            CandidateOut.ranked(links_view.linked_tx(c.move, ctx.labels), c.suggested)
            for c in found
        ]
