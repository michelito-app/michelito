"""Rutas de los análisis guardados (ver `analysis.insights` y `finanzas.dossier`)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import BaseModel, Field

from finanzas import dossier
from finanzas.analysis import accounts as account_data
from finanzas.analysis import insights, transfers
from finanzas.analysis.spending import Movement
from finanzas.web.dossier_routes import HASH_PATTERN, AccountKey
from finanzas.web.review_routes import Connection, LoadFlow
from finanzas.web.summary import month_label

Month = Annotated[str, PathParam(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
Holders = Callable[[], transfers.Holders]


class InsightOut(BaseModel):
    month: str
    label: str
    text: str  # Markdown
    accounts: list[str] | None  # cuentas analizadas; None: todas
    created_at: str
    updated_at: str
    stale: bool  # los datos cambiaron desde este análisis


class InsightBody(BaseModel):
    text: str
    # «Copiar para Claude»: la respuesta pegada es un análisis nuevo (reemplaza al guardado), con
    # las cuentas del dossier copiado (None: todas; si no viene, las de su encabezado) y la huella
    # de ese dossier (`X-Finanzas-Huella`; sin ella, la de hoy). Sin `fresh`, como siempre.
    fresh: bool = False
    accounts: list[AccountKey] | None = Field(default=None, max_length=200)
    huella: str | None = Field(default=None, pattern=HASH_PATTERN)


def _pasted(body: InsightBody, month: str) -> tuple[str, list[str] | None]:
    """El texto sin el encabezado del dossier y las cuentas analizadas. ValueError si el
    encabezado es de otro mes o sus cuentas no son las de `accounts`."""
    pasted = dossier.split_header(body.text, month)
    if "accounts" not in body.model_fields_set:
        return pasted.text, pasted.accounts
    given = sorted(set(body.accounts)) if body.accounts else None
    if pasted.has_header and given != pasted.accounts:
        raise ValueError("las cuentas no son las del dossier que se copió; vuelve a copiarlo")
    return pasted.text, given


def _check_accounts(conn: sqlite3.Connection, keys: list[str] | None) -> None:
    """ValueError si alguna cuenta no existe (con huella no se arma el dossier)."""
    known = {info.key for info in account_data.account_infos(conn)}
    unknown = sorted(set(keys or ()) - known)
    if unknown:
        raise ValueError(f"cuentas desconocidas: {', '.join(unknown)}")


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow, holders: Holders) -> None:
    def current_hash(
        conn: sqlite3.Connection, flow: Sequence[Movement], found: insights.Insight
    ) -> str | None:
        accounts = list(found.accounts) if found.accounts else None
        try:
            built = dossier.build(conn, found.month, accounts=accounts, flow=flow)
        except (ValueError, LookupError):
            return None  # ya no hay datos del mes o una cuenta dejó de existir
        return built.data_hash

    def out(
        conn: sqlite3.Connection, flow: Sequence[Movement], found: insights.Insight
    ) -> InsightOut:
        return InsightOut(
            month=found.month,
            label=month_label(found.month),
            text=found.text,
            accounts=None if found.accounts is None else list(found.accounts),
            created_at=found.created_at,
            updated_at=found.updated_at,
            stale=current_hash(conn, flow, found) != found.data_hash,
        )

    @app.get("/api/insights")
    def get_insights() -> list[InsightOut]:
        """Del mes más reciente al más viejo."""
        with connection() as conn:
            flow = load_flow(conn)
            return [out(conn, flow, found) for found in insights.list_all(conn)]

    @app.get("/api/insights/{month}")
    def get_insight(month: Month) -> InsightOut:
        with connection() as conn:
            found = insights.get(conn, month)
            if found is None:
                raise HTTPException(404, "no hay análisis de ese mes")
            return out(conn, load_flow(conn), found)

    @app.put("/api/insights/{month}")
    def put_insight(month: Month, body: InsightBody) -> InsightOut:
        """Edita el texto (la huella sigue siendo la del análisis) o crea uno con la huella de
        los datos de hoy (todas las cuentas). Con `fresh`, lo guarda (o reemplaza) como análisis
        nuevo de `accounts` con `huella` (la del dossier copiado) o, sin ella, la de hoy."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with connection() as conn:
            flow = load_flow(conn)
            try:
                with conn:
                    if body.fresh:
                        raw, keys = _pasted(body, month)
                        text = insights.clean_text(raw)
                        if body.huella is not None:
                            _check_accounts(conn, keys)
                            data_hash = body.huella
                        else:
                            built = dossier.build(conn, month, accounts=keys, flow=flow)
                            data_hash = built.data_hash
                        insights.save(conn, month, text, data_hash, keys, now)
                    elif insights.get(conn, month) is not None:
                        insights.edit_text(conn, month, body.text, now)
                    else:
                        insights.clean_text(body.text)
                        built = dossier.build(conn, month, holders=holders(), flow=flow)
                        insights.save(conn, month, body.text, built.data_hash, None, now)
            except LookupError:
                raise HTTPException(404, "mes sin datos") from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            found = insights.get(conn, month)
            assert found is not None
            return out(conn, flow, found)

    @app.delete("/api/insights/{month}", status_code=204)
    def delete_insight(month: Month) -> Response:
        with connection() as conn, conn:
            removed = insights.delete(conn, month)
        if not removed:
            raise HTTPException(404, "no hay análisis de ese mes")
        return Response(status_code=204)
