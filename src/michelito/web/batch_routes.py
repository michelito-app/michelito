"""`PATCH /api/transactions`: the category of several transactions at once (see `batch_edit`).

All in one SQLite transaction: either every one that can be applied is, or none. Responds with
the changed fingerprints, the skipped ones (with their reason) and the change-log entry.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from michelito.analysis import catalog, changelog
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import batch_edit
from michelito.web import categories as categories_view

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
Fingerprint = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class BatchBody(BaseModel):
    fingerprints: list[Fingerprint] = Field(min_length=1, max_length=batch_edit.BATCH_MAX)
    category_id: int
    reason: str = Field(default="", max_length=changelog.REASON_MAX)


class SkippedOut(BaseModel):
    fingerprint: str
    reason: str  # "linked", "cash_box", "direction", "unchanged" or "unknown"
    message: str


class BatchOut(BaseModel):
    applied: list[str]
    skipped: list[SkippedOut]
    entry_id: int | None  # the change-log entry (None if nothing changed)


def _target(known: catalog.Catalog, category_id: int) -> catalog.Category:
    """The requested category; `catalog.CategoryError` (422) if it does not exist or only its link
    can set it."""
    chosen = categories_view.edit_target(known, None, category_id)
    found = None if chosen is None else known.by_id(chosen)
    if found is None:  # does not happen: `edit_target` already checks it
        raise catalog.CategoryError(t("web.unknown_category"))
    return found


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @app.patch("/api/transactions")
    def patch_transactions(body: BatchBody) -> BatchOut:
        """Changes the category ("only this one") of up to 500 transactions with a shared reason.
        422 if the category does not exist or only its link can set it; 503 if the database is
        busy."""
        with connection() as conn:
            # Read (catalog and movements), decide and write in the same transaction: another
            # connection cannot change anything in between.
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
