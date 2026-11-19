"""Budget routes: `GET /api/budget`, activation, a category's cap, the "the usual amount
changed" warning and the Summary card (`GET /api/budget/overview`).

Every write requires `X-Michelito` (checked by `web.app`) and is recorded in the change log
(`budget`, `budget_warning`) in the same SQLite transaction as the change, so it can be undone.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from michelito.analysis import accounts as account_data
from michelito.analysis import budget, budget_store, catalog, changelog, rates, reserve_store
from michelito.analysis import recurring_marks as marks
from michelito.analysis.changelog_rules import cap_text
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import budget as budget_view
from michelito.web import summary
from michelito.web.budget_schemas import BudgetOut, CapBody, EntryOut, OverviewOut, WarningBody

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
OptionalMonth = Annotated[str | None, Query(pattern=_MONTH_PATTERN)]
AccountKeys = Annotated[str | None, Query(max_length=2000)]

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]


def load_inputs(
    conn: sqlite3.Connection,
    flow: Sequence[Movement],
    today: date,
    selected: frozenset[str] | None = None,
    *,
    with_marks: bool = False,
) -> budget_view.Inputs:
    """What the budget and reserve views need, read from the database."""
    return budget_view.Inputs(
        flow=flow,
        accounts=account_data.account_infos(conn),
        rates=rates.load(conn),
        known=catalog.load(conn),
        caps=budget_store.load(conn),
        reserves=reserve_store.load(conn),
        today=today,
        selected=selected,
        marks=marks.load_for(conn, flow) if with_marks else {},
        unions=marks.load_unions(conn) if with_marks else {},
        dismissed=reserve_store.dismissed(conn) if with_marks else frozenset(),
    )


def _cents_text(cents: int | None) -> str:
    return cap_text(cents)


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    parse_accounts: ParseAccounts,
    today: Callable[[], date],
) -> None:
    def month_or_default(inputs: budget_view.Inputs, month: str | None) -> str:
        if month is not None:
            return month
        options = summary.month_options(inputs.flow, inputs.accounts, inputs.selected)
        if not options:
            raise HTTPException(404, t("web.no_data"))
        return next((o.month for o in options if not o.partial), options[0].month)

    @app.get("/api/budget")
    def get_budget(month: OptionalMonth = None, accounts: AccountKeys = None) -> BudgetOut:
        """The month's caps and spending by category (with the chosen accounts)."""
        with connection() as conn:
            infos = account_data.account_infos(conn)
            inputs = load_inputs(conn, load_flow(conn), today(), parse_accounts(accounts, infos))
        return BudgetOut.of(budget_view.budget_view(inputs, month_or_default(inputs, month)))

    @app.get("/api/budget/overview")
    def get_overview(month: OptionalMonth = None, accounts: AccountKeys = None) -> OverviewOut:
        """The Summary card: the month's categories over their cap, what is set aside per month for
        reserves and the reserves due in the next 60 days."""
        with connection() as conn:
            infos = account_data.account_infos(conn)
            inputs = load_inputs(conn, load_flow(conn), today(), parse_accounts(accounts, infos))
        return OverviewOut.of(budget_view.overview(inputs, month_or_default(inputs, month)))

    @app.post("/api/budget/activate", status_code=201)
    def post_activate() -> EntryOut:
        """Activates the budget: each expense category starts at its rounded usual amount (or "no
        budget"). 409 if it is already active."""
        with connection() as conn:
            inputs = load_inputs(conn, load_flow(conn), today())
            caps = budget_view.initial_caps(inputs)
            with_cap = sum(1 for c in caps if c.cap is not None)
            try:
                with (
                    conn,
                    changelog.track(
                        conn,
                        "budget",
                        "category",
                        "budget",
                        t("web.budget.subject"),
                        before=t("web.budget.inactive"),
                        after=t("web.budget.activated", count=len(caps), with_cap=with_cap),
                    ) as draft,
                ):
                    budget_store.activate(conn, caps)
            except budget_store.BudgetError as exc:
                raise HTTPException(409, str(exc)) from None
        return EntryOut(entry_id=draft.entry_id)

    def category(conn: sqlite3.Connection, category_id: int) -> catalog.Category:
        found = catalog.load(conn).by_id(category_id)
        if found is None:
            raise HTTPException(404, t("web.unknown_category"))
        if found.kind != "expense":
            raise HTTPException(422, t("web.budget.expense_only"))
        return found

    @app.put("/api/budget/caps/{category_id}")
    def put_cap(category_id: int, body: CapBody) -> EntryOut:
        """A manual cap (`cap_cents` null: "no budget"). It stays fixed: no update is offered when
        the usual amount changes."""
        with connection() as conn:
            found = category(conn, category_id)
            row = conn.execute(
                "SELECT cap_cents, manual FROM budget_caps WHERE category_id = ?", (category_id,)
            ).fetchone()
            if not budget_store.is_active(conn):
                raise HTTPException(409, t("web.budget.not_active"))
            before = "—" if row is None else _cents_text(row[0])
            try:
                with (
                    conn,
                    changelog.track(
                        conn,
                        "budget",
                        "category",
                        str(category_id),
                        found.name,
                        before=before,
                        after=_cents_text(body.cap_cents),
                    ) as draft,
                ):
                    budget_store.set_cap(conn, category_id, body.cap)
            except budget_store.BudgetError as exc:
                raise HTTPException(422, str(exc)) from None
        return EntryOut(entry_id=draft.entry_id)

    @app.post("/api/budget/caps/{category_id}/usual")
    def post_warning(category_id: int, body: WarningBody) -> EntryOut:
        """The "the usual amount changed" warning: accepting sets the cap to today's rounded usual
        amount; ignoring marks it as seen. 404 if that category has no warning."""
        with connection() as conn:
            found = category(conn, category_id)
            inputs = load_inputs(conn, load_flow(conn), today())
            cap = inputs.caps.get(category_id)
            usual = budget_view.usual_amounts(inputs).get(category_id)
            notice = None if cap is None else budget.warning(cap, usual)
            if cap is None or notice is None:
                raise HTTPException(404, t("web.budget.no_warning"))
            new = int(notice.habitual * 100)
            after = (
                _cents_text(new or None)
                if body.accept
                else t(
                    "web.budget.kept",
                    cap=_cents_text(None if cap.cap is None else int(cap.cap * 100)),
                )
            )
            with (
                conn,
                changelog.track(
                    conn,
                    "budget_warning",
                    "category",
                    str(category_id),
                    found.name,
                    before=t(
                        "web.budget.usual_changed",
                        basis=int(notice.basis),
                        usual=int(notice.habitual),
                    ),
                    after=after,
                ) as draft,
            ):
                budget_store.resolve_warning(conn, category_id, notice.habitual, body.accept)
        return EntryOut(entry_id=draft.entry_id)
