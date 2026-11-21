"""Routes of live sync: what the user decides about a provisional transaction (from a bank
alert) that did not show up in its statement.

`PUT /api/provisional/{fingerprint}` with `{"decision": "discard" | "keep" | null}`: "Discard"
hides it (it stops counting; the alert stays, never deleted), "Keep" leaves it counted and marks
the review item as reviewed, `null` forgets the decision. Each one is a change-log entry, so it
can be undone from the log. A provisional in a link (a shared group's entry, an exchange, an
investment...) cannot be discarded: 409 until it is taken out of it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from michelito.analysis import changelog, live_store
from michelito.analysis.spending import Movement
from michelito.i18n import t

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]


class DecisionBody(BaseModel):
    decision: Literal["discard", "keep"] | None


class DecisionOut(BaseModel):
    fingerprint: str
    decision: Literal["discard", "keep"] | None


def _label(decision: str | None) -> str:
    if decision == "discard":
        return t("web.provisional.discarded")
    if decision == "keep":
        return t("web.provisional.kept")
    return t("web.provisional.pending")


def _merchant(conn: sqlite3.Connection, fingerprint: str) -> str | None:
    """The alert's merchant, if the fingerprint is an alert that became a transaction."""
    alert_id = live_store.alert_id(fingerprint)
    if alert_id is None:
        return None
    row = conn.execute(
        "SELECT merchant FROM alerts WHERE id = ? AND status = 'provisional'", (alert_id,)
    ).fetchone()
    return None if row is None else str(row[0])


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @app.put("/api/provisional/{fingerprint}")
    def put_provisional(fingerprint: str, body: DecisionBody) -> DecisionOut:
        with connection() as conn:
            merchant = _merchant(conn, fingerprint)
            if merchant is None:
                raise HTTPException(404, t("web.provisional.unknown"))
            if body.decision == "discard" and live_store.is_linked(conn, fingerprint):
                # A group entry or a link would be left pointing at nothing.
                if live_store.in_cash(conn, fingerprint):
                    raise HTTPException(409, t("web.provisional.in_cash"))
                raise HTTPException(409, t("web.provisional.linked"))
            before = live_store.decisions(conn).get(fingerprint)
            with (
                conn,
                changelog.track(
                    conn,
                    "provisional",
                    "transaction",
                    fingerprint,
                    merchant,
                    before=_label(before),
                    after=_label(body.decision),
                    merchant=merchant,
                    fingerprints=[fingerprint],
                ),
            ):
                live_store.decide(conn, fingerprint, body.decision, changelog.now().isoformat())
        return DecisionOut(fingerprint=fingerprint, decision=body.decision)
