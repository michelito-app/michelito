"""Rutas de Reportes: comparar meses."""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from finanzas.analysis import accounts as account_data
from finanzas.analysis import rates
from finanzas.web import reports
from finanzas.web.report_schemas import ComparisonOut
from finanzas.web.review_routes import Connection, LoadFlow, ParseAccounts

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def register(
    app: FastAPI, connection: Connection, load_flow: LoadFlow, parse_accounts: ParseAccounts
) -> None:
    @app.get("/api/reports/compare")
    def get_compare(
        first: Annotated[str | None, Query(alias="from", pattern=_MONTH_PATTERN)] = None,
        last: Annotated[str | None, Query(alias="to", pattern=_MONTH_PATTERN)] = None,
        accounts: Annotated[str | None, Query(max_length=2000)] = None,
    ) -> ComparisonOut:
        """Categorías × meses del rango (por defecto los 12 más recientes con datos)."""
        with connection() as conn:
            flow = load_flow(conn)
            infos = account_data.account_infos(conn)
            selected = parse_accounts(accounts, infos)
            try:
                result = reports.compare(
                    flow, infos, rates.load(conn), first=first, last=last, selected=selected
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        return ComparisonOut.of(result)
