"""Cash routes (`/api/cash-box`, the cash account): balance and entries, add, edit and delete a
manual entry (a new inflow or outflow needs its concept; "Repeat" makes it the first occurrence
of a schedule), mark or unmark a withdrawal moved into cash ("I spent it directly" after the
activation is remembered), and link or unlink a deposit. Schedules, occurrences and the
reconcile live in `cash_routes`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

from michelito.analysis import accounts as account_data
from michelito.analysis import (
    cash_activation,
    cash_box,
    cash_box_store,
    cash_schedule_store,
    catalog,
    changelog,
    ledger_store,
    links,
    rates,
)
from michelito.analysis.accounts import BANK_KINDS, CASH_BOX_KEY
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import cash_view, edit_log
from michelito.web.cash_box_schemas import CashBoxOut, DepositBody, EntryBody, EntryPatch
from michelito.web.schemas import TxOut

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
TxOutFor = Callable[[sqlite3.Connection, str, str], TxOut]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (links.AlreadyLinked, sqlite3.IntegrityError) as exc:  # another tab linked it
        detail = str(exc) if isinstance(exc, links.AlreadyLinked) else ""
        raise HTTPException(409, detail or t("web.already_linked")) from None
    except ValueError as exc:  # CashBoxError, LinkError and a note that is too long
        raise HTTPException(422, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc) or t("web.cash.unknown_entry")) from None


def _money(cents: int | None) -> Decimal | None:
    return None if cents is None else Decimal(cents) / 100


def box_state(
    conn: sqlite3.Connection, flow: Sequence[Movement], day: date
) -> tuple[cash_box.BoxState, bool]:
    """The account's state on `day` and whether it exists yet."""
    found = links.load(conn)
    box = next((b for b in found.cash_boxes if b.account_key == CASH_BOX_KEY), None)
    entries = cash_box_store.load_entries(conn)
    state = cash_box.state_of(box, entries, flow, rates.load(conn), today=day)
    return state, box is not None


def box_out(conn: sqlite3.Connection, load_flow: LoadFlow, day: date) -> CashBoxOut:
    """The whole "Efectivo" (cash) screen, as it stands after a change."""
    state, exists = box_state(conn, load_flow(conn), day)
    labels = {a.key: a.label for a in account_data.account_infos(conn)}
    ids = {c.ref: c.id for c in catalog.load(conn).items}
    book = ledger_store.load(conn)
    groups = {
        line.fingerprint: held[0].name
        for line in state.lines
        if (held := book.entry_for(line.fingerprint)) is not None
    }
    extras = cash_view.extras(conn, cash_box_store.load_entries(conn), day)
    return CashBoxOut.of(state, exists, labels, ids, groups, extras, day)


def track_entry(
    conn: sqlite3.Connection, entry_id: int | None, kind: str = "cash_entry"
) -> AbstractContextManager[changelog.Draft]:
    """The "cash entry" log entry (adding, changing or deleting manual entries, schedules and
    reconciles)."""
    code = "" if entry_id is None else cash_box.entry_fingerprint(entry_id)
    return changelog.track(conn, kind, "cash_box", code, t("web.cash.box_name"))


def add_entry(conn: sqlite3.Connection, body: EntryBody, now: date) -> int:
    """Writes a new entry (and its schedule with "Repeat") inside the caller's change; returns
    the entry id."""
    if body.kind != "initial" and body.concept is None:
        raise cash_box.CashBoxError(t("analysis.cash_box.concept_required"))
    if body.kind == "initial" and body.repeat is not None:
        raise cash_box.CashBoxError(t("web.cash.initial_no_repeat"))
    amount = Decimal(body.amount_cents) / 100
    schedule_id = None
    if body.repeat is not None:
        schedule_id = cash_schedule_store.add(
            conn,
            cash_schedule_store.ScheduleDraft(
                kind="payment" if body.kind == "expense" else "collection",
                concept=body.concept or "",
                amount=amount,
                currency=body.currency,
                category_id=body.category_id,
                frequency=body.repeat.frequency,
                start=body.day,
                end=body.repeat.end_day,
                max_count=body.repeat.max_count,
            ),
            now,
        )
    made = cash_box_store.add_entry(
        conn,
        body.kind,
        body.day,
        amount,
        body.currency,
        category=body.category_id,
        note=body.note,
        today=now,
        concept=body.concept,
        schedule_id=schedule_id,
        status=None if schedule_id is None else "confirmed",
    )
    if schedule_id is not None:
        cash_schedule_store.materialize(conn, now)
    cash_activation.activate(conn, now)
    return made


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    tx_out: TxOutFor,
    today: Callable[[], date],
) -> None:
    def box_out_now(conn: sqlite3.Connection) -> CashBoxOut:
        return box_out(conn, load_flow, today())

    def movement(conn: sqlite3.Connection, fingerprint: str) -> tuple[Movement, links.Links]:
        found = next((m for m in load_flow(conn) if m.fingerprint == fingerprint), None)
        if found is None:
            raise HTTPException(404, t("web.unknown_transaction"))
        return found, links.load(conn)

    def track_tx(
        conn: sqlite3.Connection, fingerprint: str, target: Movement | None
    ) -> AbstractContextManager[changelog.Draft]:
        """The "cash box" log entry of a stored withdrawal or a deposit."""
        return changelog.track(
            conn,
            "cash_box",
            "transaction",
            fingerprint,
            fingerprint if target is None else edit_log.subject(target),
            merchant=None if target is None else target.merchant,
            fingerprints=[fingerprint],
        )

    def unmark(fingerprint: str, role: str) -> Response:
        """Removes the mark even when the movement is no longer in the flow (a statement that
        changed): the up-to-date transaction if it is still there, 204 if not. A withdrawal
        dated on or after the activation is remembered as "I spent it directly", so the automatic
        pass does not move it into cash again."""
        with connection() as conn:
            before = next((m for m in load_flow(conn) if m.fingerprint == fingerprint), None)
            since = cash_activation.activated_on(conn)
            with _errors(), conn, track_tx(conn, fingerprint, before):
                cash_box_store.remove(conn, fingerprint, role)
                after_activation = since is not None and (before is None or before.day >= since)
                if role == "stored" and after_activation:
                    cash_activation.set_spent_direct(conn, fingerprint, True)
                if role == "stored":
                    cash_activation.forget_auto(conn, fingerprint)
            target = next((m for m in load_flow(conn) if m.fingerprint == fingerprint), None)
            if target is None:
                return Response(status_code=204)
            return JSONResponse(tx_out(conn, fingerprint, target.month).model_dump())

    @app.get("/api/cash-box")
    def get_cash_box() -> CashBoxOut:
        with connection() as conn:
            return box_out_now(conn)

    @app.post("/api/cash-box/entries", status_code=201)
    def post_entry(body: EntryBody) -> CashBoxOut:
        """Adds an opening balance, an inflow or an outflow (a negative balance is allowed: the
        response reports it in `negative`). An inflow or outflow needs its concept; with
        `repeat` it is also the first occurrence of a new schedule from its date (one change).
        The first write activates "Efectivo" (cash) (`cash_activation`)."""
        now = today()
        with connection() as conn:
            if body.kind == "initial" or body.concept is not None:
                cash_box_store.ensure_system_box(conn)  # outside the change: see there
            with _errors(), conn, track_entry(conn, None) as draft:
                made = add_entry(conn, body, now)
                draft.target = cash_box.entry_fingerprint(made)
            return box_out_now(conn)

    @app.put("/api/cash-box/entries/{entry_id}")
    def put_entry(entry_id: int, body: EntryPatch) -> CashBoxOut:
        with connection() as conn:
            with _errors(), conn, track_entry(conn, entry_id):
                cash_box_store.update_entry(
                    conn,
                    entry_id,
                    body.day,
                    Decimal(body.amount_cents) / 100,
                    body.currency,
                    category=body.category_id,
                    # Present and empty (or null): cleared; absent: left as is.
                    note=(body.note or "") if "note" in body.model_fields_set else None,
                    today=today(),
                    concept=body.concept,
                )
            return box_out_now(conn)

    @app.delete("/api/cash-box/entries/{entry_id}")
    def delete_entry(entry_id: int) -> CashBoxOut:
        with connection() as conn:
            with _errors(), conn, track_entry(conn, entry_id):
                cash_box_store.delete_entry(conn, entry_id)
            return box_out_now(conn)

    @app.put("/api/cash-box/stored/{fingerprint}")
    def put_stored(fingerprint: str) -> TxOut:
        """Marks "I moved it to my cash": the withdrawal stops being an expense and adds to the
        balance."""
        with connection() as conn:
            target, found = movement(conn, fingerprint)
            if not found.is_linked(fingerprint) and cash_box.can_store(target, found):
                cash_box_store.ensure_system_box(conn)  # outside the change: see there
            with _errors(), conn, track_tx(conn, fingerprint, target) as draft:
                draft.before, draft.after = target.category, t("web.cash.box_name")
                if found.is_linked(fingerprint):
                    raise links.AlreadyLinked(t("web.already_linked"))
                if not cash_box.can_store(target, found):
                    raise cash_box.CashBoxError(t("web.cash.only_withdrawal"))
                cash_box_store.store(conn, fingerprint)
                cash_activation.set_spent_direct(conn, fingerprint, False)
            return tx_out(conn, fingerprint, target.month)

    @app.delete("/api/cash-box/stored/{fingerprint}")
    def delete_stored(fingerprint: str) -> Response:
        """ "I spent it directly": the withdrawal is an expense in its category again."""
        return unmark(fingerprint, "stored")

    @app.put("/api/cash-box/deposits/{fingerprint}")
    def put_deposit(fingerprint: str, body: DepositBody) -> TxOut:
        """Marks "it came from the cash box": the credit is not income and lowers the balance
        (in another currency, by the given amount or at the rate of the deposit's month)."""
        with connection() as conn:
            target, found = movement(conn, fingerprint)
            infos = account_data.account_infos(conn)
            banks = [a.key for a in infos if a.kind in BANK_KINDS]
            if not found.is_linked(fingerprint) and cash_box.can_deposit(target, found, banks):
                cash_box_store.ensure_system_box(conn)  # outside the change: see there
            with _errors(), conn, track_tx(conn, fingerprint, target) as draft:
                draft.before, draft.after = target.category, t("web.cash.from_box")
                if found.is_linked(fingerprint):
                    raise links.AlreadyLinked(t("web.already_linked"))
                if not cash_box.can_deposit(target, found, banks):
                    raise cash_box.CashBoxError(t("web.cash.only_bank_credit"))
                other = body.currency if body.currency != target.currency else None
                if other is None and body.amount_cents is not None:
                    raise cash_box.CashBoxError(t("web.cash.same_currency_amount"))
                cash_box_store.deposit(conn, fingerprint, other, _money(body.amount_cents))
            return tx_out(conn, fingerprint, target.month)

    @app.delete("/api/cash-box/deposits/{fingerprint}")
    def delete_deposit(fingerprint: str) -> Response:
        """Unlinks the deposit: it goes back to its category (usually income)."""
        return unmark(fingerprint, "deposit")
