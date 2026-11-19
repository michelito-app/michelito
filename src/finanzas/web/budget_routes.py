"""Rutas del presupuesto: `GET /api/budget`, activar, el tope de una categoría, el aviso de «lo
habitual cambió» y la tarjeta del Resumen (`GET /api/budget/overview`).

Cada escritura exige `X-Finanzas` (lo revisa `web.app`) y queda en la bitácora (`presupuesto`,
`presupuesto_aviso`), en la misma transacción SQLite que el cambio, y se puede deshacer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from finanzas.analysis import accounts as account_data
from finanzas.analysis import budget, budget_store, catalog, changelog, rates, reserve_store
from finanzas.analysis import recurring_marks as marks
from finanzas.analysis.changelog_rules import cap_text
from finanzas.analysis.spending import Movement
from finanzas.web import budget as budget_view
from finanzas.web import summary
from finanzas.web.budget_schemas import BudgetOut, CapBody, EntryOut, OverviewOut, WarningBody

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
    """Lo que necesitan las vistas del presupuesto y las reservas, leído de la base."""
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
            raise HTTPException(404, "mes sin datos")
        return next((o.month for o in options if not o.partial), options[0].month)

    @app.get("/api/budget")
    def get_budget(month: OptionalMonth = None, accounts: AccountKeys = None) -> BudgetOut:
        """Topes y lo gastado del mes por categoría (con las cuentas elegidas)."""
        with connection() as conn:
            infos = account_data.account_infos(conn)
            inputs = load_inputs(conn, load_flow(conn), today(), parse_accounts(accounts, infos))
        return BudgetOut.of(budget_view.budget_view(inputs, month_or_default(inputs, month)))

    @app.get("/api/budget/overview")
    def get_overview(month: OptionalMonth = None, accounts: AccountKeys = None) -> OverviewOut:
        """La tarjeta del Resumen: categorías pasadas del mes, lo que se aparta al mes para las
        reservas y las que vencen en los próximos 60 días."""
        with connection() as conn:
            infos = account_data.account_infos(conn)
            inputs = load_inputs(conn, load_flow(conn), today(), parse_accounts(accounts, infos))
        return OverviewOut.of(budget_view.overview(inputs, month_or_default(inputs, month)))

    @app.post("/api/budget/activate", status_code=201)
    def post_activate() -> EntryOut:
        """Activa el presupuesto: cada categoría de gasto arranca con lo habitual redondeado (o
        «Sin presupuesto»). 409 si ya está activo."""
        with connection() as conn:
            inputs = load_inputs(conn, load_flow(conn), today())
            caps = budget_view.initial_caps(inputs)
            with_cap = sum(1 for c in caps if c.cap is not None)
            try:
                with (
                    conn,
                    changelog.track(
                        conn,
                        "presupuesto",
                        "categoria",
                        "presupuesto",
                        "Presupuesto",
                        before="sin activar",
                        after=f"{len(caps)} categorías, {with_cap} con tope",
                    ) as draft,
                ):
                    budget_store.activate(conn, caps)
            except budget_store.BudgetError as exc:
                raise HTTPException(409, str(exc)) from None
        return EntryOut(entry_id=draft.entry_id)

    def category(conn: sqlite3.Connection, category_id: int) -> catalog.Category:
        found = catalog.load(conn).by_id(category_id)
        if found is None:
            raise HTTPException(404, "categoría desconocida")
        if found.kind != "gasto":
            raise HTTPException(422, "solo una categoría de gasto lleva tope")
        return found

    @app.put("/api/budget/caps/{category_id}")
    def put_cap(category_id: int, body: CapBody) -> EntryOut:
        """El tope a mano (`cap_cents` null: «Sin presupuesto»). Queda fijo: no se ofrece
        actualizarlo cuando cambie lo habitual."""
        with connection() as conn:
            found = category(conn, category_id)
            row = conn.execute(
                "SELECT cap_cents, manual FROM budget_caps WHERE category_id = ?", (category_id,)
            ).fetchone()
            if not budget_store.is_active(conn):
                raise HTTPException(409, "el presupuesto no está activo: actívalo primero")
            before = "—" if row is None else _cents_text(row[0])
            try:
                with (
                    conn,
                    changelog.track(
                        conn,
                        "presupuesto",
                        "categoria",
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

    @app.post("/api/budget/caps/{category_id}/habitual")
    def post_warning(category_id: int, body: WarningBody) -> EntryOut:
        """Aviso de «lo habitual cambió»: aceptar pone el tope en lo habitual redondeado de hoy;
        ignorar lo da por visto. 404 si no hay aviso para esa categoría."""
        with connection() as conn:
            found = category(conn, category_id)
            inputs = load_inputs(conn, load_flow(conn), today())
            cap = inputs.caps.get(category_id)
            usual = budget_view.habitual(inputs).get(category_id)
            notice = None if cap is None else budget.warning(cap, usual)
            if cap is None or notice is None:
                raise HTTPException(404, "no hay aviso de lo habitual para esa categoría")
            new = int(notice.habitual * 100)
            after = (
                _cents_text(new or None)
                if body.accept
                else f"se queda {_cents_text(None if cap.cap is None else int(cap.cap * 100))}"
            )
            with (
                conn,
                changelog.track(
                    conn,
                    "presupuesto_aviso",
                    "categoria",
                    str(category_id),
                    found.name,
                    before=f"lo habitual pasó de RD$ {int(notice.basis):,} a "
                    f"RD$ {int(notice.habitual):,}",
                    after=after,
                ) as draft,
            ):
                budget_store.resolve_warning(conn, category_id, notice.habitual, body.accept)
        return EntryOut(entry_id=draft.entry_id)
