"""«Copiar para Claude»: el dossier del mes y la instrucción fija, de solo lectura.

`GET /api/dossier?mes=AAAA-MM&cuentas=k1,k2` devuelve el Markdown de `finanzas.dossier` tal
cual (con `DATA_NOTICE`, los bloques ```text y los recortes) sobre la base de la petición (en la
demo, la copia del visitante). En la URL solo van el mes y las cuentas. La interfaz junta la
instrucción (`analysis.claude_prompt`) y el dossier en el portapapeles; nada se manda afuera.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, StringConstraints

from finanzas import dossier
from finanzas.analysis import claude_prompt
from finanzas.web.review_routes import Connection, LoadFlow

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
HASH_HEADER = "X-Finanzas-Huella"
HASH_PATTERN = rf"^[0-9a-f]{{{dossier.HASH_LENGTH}}}$"
ACCOUNT_KEY_MAX = 100  # largo máximo de una clave de cuenta pedida (las reales son cortas)
AccountKey = Annotated[str, StringConstraints(min_length=1, max_length=ACCOUNT_KEY_MAX)]
_NO_STORE = {"Cache-Control": "no-store"}


class InstructionOut(BaseModel):
    texto: str


def account_keys(raw: str | None) -> list[str] | None:
    """Las claves pedidas, sin repetir y ordenadas; None si no se pidió ninguna (todas). 422 si
    alguna pasa de `ACCOUNT_KEY_MAX`."""
    keys = sorted({key.strip() for key in (raw or "").split(",") if key.strip()})
    if any(len(key) > ACCOUNT_KEY_MAX for key in keys):
        raise HTTPException(422, f"clave de cuenta de más de {ACCOUNT_KEY_MAX} caracteres")
    return keys or None


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @app.get("/api/dossier/instruccion")
    def get_instruction() -> InstructionOut:
        """La instrucción por defecto que acompaña al dossier (no abre la base)."""
        return InstructionOut(texto=claude_prompt.INSTRUCTION)

    @app.get("/api/dossier")
    def get_dossier(
        mes: Annotated[str, Query(pattern=_MONTH_PATTERN)],
        cuentas: Annotated[str | None, Query(max_length=2000)] = None,
    ) -> Response:
        """El dossier del mes en Markdown; 422 si alguna cuenta no existe, 404 sin datos."""
        with connection() as conn:
            try:
                built = dossier.build(
                    conn, mes, accounts=account_keys(cuentas), flow=load_flow(conn)
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            except LookupError:
                raise HTTPException(404, "mes sin datos") from None
        return Response(
            built.markdown,
            media_type="text/markdown; charset=utf-8",
            headers={**_NO_STORE, HASH_HEADER: built.data_hash},
        )
