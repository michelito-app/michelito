""" "Efectivo" (cash) routes beyond the entries (schema 23): scheduled payments and collections, the
answers to their occurrences, the reconcile and the concepts written before.

Each write is one change in the change log (one undo): creating a schedule materializes, in the
same change, the occurrences already due; a reconcile writes its entries and its mark together.
Every write returns the up-to-date account (`cash_box_routes.box_out`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal

from fastapi import FastAPI

from michelito.analysis import cash_activation, cash_box, cash_box_store, cash_schedule_store
from michelito.analysis.accounts import CASH_BOX_KEY
from michelito.web import cash_view
from michelito.web.cash_box_routes import (
    Connection,
    LoadFlow,
    _errors,
    box_out,
    box_state,
    track_entry,
)
from michelito.web.cash_box_schemas import (
    AnswerBody,
    CashBoxOut,
    ConceptOut,
    PauseBody,
    ReconcileBody,
    ScheduleBody,
)


def _draft(body: ScheduleBody) -> cash_schedule_store.ScheduleDraft:
    return cash_schedule_store.ScheduleDraft(
        kind=body.kind,
        concept=body.concept,
        amount=Decimal(body.amount_cents) / 100,
        currency=body.currency,
        category_id=body.category_id,
        frequency=body.frequency,
        start=body.start_day,
        end=body.end_day,
        max_count=body.max_count,
    )


def reconcile(
    conn: sqlite3.Connection,
    load_flow: LoadFlow,
    counts: Mapping[str, Decimal],
    day: date,
) -> list[int]:
    """Writes the reconcile of `day` (inside the caller's change): one entry per currency whose
    count differs (`cash_box.reconcile_plan`) and the month's mark. Returns the entries made."""
    state, _ = box_state(conn, load_flow(conn), day)
    made = [
        cash_box_store.add_entry(
            conn,
            item.kind,
            day,
            item.amount,
            item.currency,
            today=day,
            concept=None if item.kind == "initial" else item.concept,
        )
        for item in cash_box.reconcile_plan(state, counts, day)
    ]
    cash_box_store.ensure_box(conn)
    conn.execute(
        "INSERT INTO cash_reconciliations (account_key, month, day, created_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (CASH_BOX_KEY, day.strftime("%Y-%m"), day.isoformat()),
    )
    cash_activation.activate(conn, day)
    return made


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    today: Callable[[], date],
) -> None:
    def out(conn: sqlite3.Connection) -> CashBoxOut:
        return box_out(conn, load_flow, today())

    @app.get("/api/cash-box/concepts")
    def get_concepts() -> list[ConceptOut]:
        """The concepts written before, most recent first (autocomplete)."""
        with connection() as conn:
            found = cash_view.concepts(conn, cash_box_store.load_entries(conn))
        return [ConceptOut.of(item) for item in found]

    @app.post("/api/cash-box/schedules", status_code=201)
    def post_schedule(body: ScheduleBody) -> CashBoxOut:
        """A new scheduled payment or collection; its occurrences already due appear at once
        (pending), in the same change."""
        now = today()
        with connection() as conn:
            cash_box_store.ensure_system_box(conn)  # outside the change: see there
            with _errors(), conn, track_entry(conn, None, "cash_schedule") as draft:
                made = cash_schedule_store.add(conn, _draft(body), now)
                cash_schedule_store.materialize(conn, now)
                cash_activation.activate(conn, now)
                draft.target = f"schedule-{made}"
            return out(conn)

    @app.put("/api/cash-box/schedules/{schedule_id}")
    def put_schedule(schedule_id: int, body: ScheduleBody) -> CashBoxOut:
        """Changes a schedule: a new amount applies from the next occurrence (those already
        there keep theirs)."""
        now = today()
        with connection() as conn:
            with _errors(), conn, track_entry(conn, None, "cash_schedule") as draft:
                draft.target = f"schedule-{schedule_id}"
                cash_schedule_store.update(conn, schedule_id, _draft(body), now)
                cash_schedule_store.materialize(conn, now)
            return out(conn)

    @app.put("/api/cash-box/schedules/{schedule_id}/paused")
    def put_paused(schedule_id: int, body: PauseBody) -> CashBoxOut:
        """Pause or resume (from today: the dates missed while paused are not created)."""
        now = today()
        with connection() as conn:
            with _errors(), conn, track_entry(conn, None, "cash_schedule") as draft:
                draft.target = f"schedule-{schedule_id}"
                cash_schedule_store.set_paused(conn, schedule_id, body.paused, now)
                cash_schedule_store.materialize(conn, now)
            return out(conn)

    @app.delete("/api/cash-box/schedules/{schedule_id}")
    def delete_schedule(schedule_id: int) -> CashBoxOut:
        """Deletes the schedule; its past occurrences stay."""
        with connection() as conn:
            with _errors(), conn, track_entry(conn, None, "cash_schedule") as draft:
                draft.target = f"schedule-{schedule_id}"
                cash_schedule_store.delete(conn, schedule_id)
            return out(conn)

    @app.post("/api/cash-box/occurrences/{entry_id}")
    def post_answer(entry_id: int, body: AnswerBody) -> CashBoxOut:
        """The answer on an occurrence: paid / received, another amount, or it did not happen."""
        now = today()
        with connection() as conn:
            with _errors(), conn, track_entry(conn, entry_id, "cash_occurrence"):
                amount = None if body.amount_cents is None else Decimal(body.amount_cents) / 100
                cash_schedule_store.answer(conn, entry_id, body.action, amount, now)
            return out(conn)

    @app.post("/api/cash-box/reconcile")
    def post_reconcile(body: ReconcileBody) -> CashBoxOut:
        """ "Reconcile cash": how much cash there is per currency; the difference becomes one
        entry per currency (see `cash_box.reconcile_plan`), all in one change."""
        now = today()
        counts: dict[str, Decimal] = {
            item.currency: Decimal(item.amount_cents) / 100 for item in body.counts
        }
        with connection() as conn:
            cash_box_store.ensure_system_box(conn)  # outside the change: see there
            with _errors(), conn, track_entry(conn, None, "cash_reconcile") as draft:
                made = reconcile(conn, load_flow, counts, now)
                draft.target = "" if not made else cash_box.entry_fingerprint(made[0])
            return out(conn)
