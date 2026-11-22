"""Routes of merchant receipts: what the person decides about a receipt and a transaction.

- `PUT /api/receipts/{id}/transactions/{fingerprint}`: "it is this one": link a receipt to one
  of the transactions proposed for it (409 for any other transaction).
- `DELETE /api/receipts/{id}/transactions/{fingerprint}`: "it is not this one": remove the link
  (or refuse the proposal). The pair is not linked or proposed again. 409 for a pair that was
  neither linked nor proposed.

Each one is a change-log entry on the transaction, so it can be undone from its history.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from michelito.analysis import changelog, receipt_match, receipt_store
from michelito.analysis.receipt_store import Stored
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import edit_log

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
LOG_KIND = "receipt"


class ReceiptLinkOut(BaseModel):
    receipt_id: int
    fingerprint: str
    linked: bool


def label(receipt: Stored) -> str:
    """How the log names a receipt: its merchant and order number (data, not interface text)."""
    return " ".join((receipt.merchant, *receipt.orders[:1]))


def _found(
    conn: sqlite3.Connection, flow: Sequence[Movement], receipt_id: int, fingerprint: str
) -> tuple[Stored, Movement]:
    receipt = next((r for r in receipt_store.load(conn) if r.id == receipt_id), None)
    if receipt is None:
        raise HTTPException(404, t("web.receipt.unknown"))
    target = next((m for m in flow if m.fingerprint == fingerprint), None)
    if target is None:
        raise HTTPException(404, t("web.unknown_transaction"))
    return receipt, target


def decide(
    conn: sqlite3.Connection,
    receipt: Stored,
    target: Movement,
    linked: bool,
    flow: Sequence[Movement],
) -> None:
    """Link the pair or refuse it, as one change-log entry (the caller holds no transaction).
    What then becomes a single exact candidate is linked on its own inside the same entry, so
    undoing it undoes that too and no receipt is left on two transactions."""
    now = changelog.now().isoformat()
    nothing, shown = t("web.receipt.none"), label(receipt)
    with (
        conn,
        changelog.track(
            conn,
            LOG_KIND,
            "transaction",
            target.fingerprint,
            edit_log.subject(target),
            before=nothing if linked else shown,
            after=shown if linked else nothing,
            merchant=target.merchant,
            fingerprints=[target.fingerprint],
        ),
    ):
        if linked:
            receipt_store.link(conn, receipt.id, target.fingerprint, "confirmed", now)
        else:
            receipt_store.unlink(conn, receipt.id, target.fingerprint, now)
        receipt_match.reconcile(conn, flow, now)


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @app.put("/api/receipts/{receipt_id}/transactions/{fingerprint}")
    def put_link(receipt_id: int, fingerprint: str) -> ReceiptLinkOut:
        with connection() as conn:
            flow = load_flow(conn)
            receipt, target = _found(conn, flow, receipt_id, fingerprint)
            if fingerprint not in receipt.links:
                proposed = receipt_match.proposals(conn, flow).get(receipt_id, ())
                if fingerprint not in proposed:
                    raise HTTPException(409, t("web.receipt.not_proposed"))
                decide(conn, receipt, target, True, flow)
        return ReceiptLinkOut(receipt_id=receipt_id, fingerprint=fingerprint, linked=True)

    @app.delete("/api/receipts/{receipt_id}/transactions/{fingerprint}")
    def delete_link(receipt_id: int, fingerprint: str) -> ReceiptLinkOut:
        with connection() as conn:
            flow = load_flow(conn)
            receipt, target = _found(conn, flow, receipt_id, fingerprint)
            if fingerprint not in receipt.links:
                proposed = receipt_match.proposals(conn, flow).get(receipt_id, ())
                if fingerprint not in proposed:
                    raise HTTPException(409, t("web.receipt.not_proposed"))
            decide(conn, receipt, target, False, flow)
        return ReceiptLinkOut(receipt_id=receipt_id, fingerprint=fingerprint, linked=False)
