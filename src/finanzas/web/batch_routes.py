"""`PATCH /api/transactions`: la categoría de varias transacciones a la vez (ver `batch_edit`).

Todo en una transacción SQLite: o se aplican todas las que se pueden o ninguna. Responde con las
huellas cambiadas, las omitidas (con su motivo) y la entrada de la bitácora.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from finanzas.analysis import catalog, changelog
from finanzas.analysis.spending import Movement
from finanzas.web import batch_edit
from finanzas.web import categories as categories_view

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
Fingerprint = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class BatchBody(BaseModel):
    fingerprints: list[Fingerprint] = Field(min_length=1, max_length=batch_edit.BATCH_MAX)
    category_id: int
    reason: str = Field(default="", max_length=changelog.REASON_MAX)


class SkippedOut(BaseModel):
    fingerprint: str
    reason: str  # "vinculo", "caja", "direccion", "sin_cambio" o "desconocida"
    message: str


class BatchOut(BaseModel):
    applied: list[str]
    skipped: list[SkippedOut]
    entry_id: int | None  # la entrada de la bitácora (None si nada cambió)


def _target(known: catalog.Catalog, category_id: int) -> catalog.Category:
    """La categoría pedida; `catalog.CategoryError` (422) si no existe o solo la pone su
    vínculo."""
    chosen = categories_view.edit_target(known, None, category_id)
    found = None if chosen is None else known.by_id(chosen)
    if found is None:  # no pasa: `edit_target` ya lo valida
        raise catalog.CategoryError("categoría desconocida")
    return found


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @app.patch("/api/transactions")
    def patch_transactions(body: BatchBody) -> BatchOut:
        """Cambia la categoría («solo esta») de hasta 500 transacciones con un motivo común.
        422 si la categoría no existe o solo la pone su vínculo; 503 si la base está ocupada."""
        with connection() as conn:
            # Leer (catálogo y movimientos), decidir y escribir en la misma transacción: otra
            # conexión no puede cambiar nada en medio.
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                raise HTTPException(503, changelog.BUSY) from None
            try:
                with conn:
                    known = catalog.load(conn)
                    target = _target(known, body.category_id)
                    found = batch_edit.plan(load_flow(conn), body.fingerprints, target)
                    entry = batch_edit.apply(conn, found.chosen, target, body.reason)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        return BatchOut(
            applied=[m.fingerprint for m in found.chosen],
            skipped=[
                SkippedOut(fingerprint=s.fingerprint, reason=s.reason, message=s.message)
                for s in found.skipped
            ],
            entry_id=entry,
        )
