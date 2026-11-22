"""A new shared group from a credit ("It is a payment…" → "+ New group").

`GET /api/shared/credit-plan` proposes (who paid, the expense it pays back, other credits);
`POST /api/shared/groups/from-credit` creates the group with its expenses and payments in ONE
change of the log (kind "group_new"), so a single undo takes all of it back.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException

from michelito.analysis import ledger, ledger_credit, ledger_store, links, shared
from michelito.analysis.links import LinkError
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import links as links_view
from michelito.web.ledger_credit_schemas import (
    CreditExpenseBody,
    CreditGroupBody,
    CreditPlanOut,
)
from michelito.web.ledger_schemas import GroupOut, NewPerson

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
Tracked = Callable[..., AbstractContextManager[None]]


@dataclass(frozen=True)
class Helpers:
    """Closures of `web.ledger_routes.register` this module reuses."""

    tracked: Tracked
    person_id: Callable[[sqlite3.Connection, NewPerson], int]
    payment_tx: Callable[[sqlite3.Connection, str, bool], Movement]
    group_response: Callable[[sqlite3.Connection, int], GroupOut]
    day: Callable[[str | None, date], date]
    load_book: Callable[..., Any]


@dataclass(frozen=True)
class _Expense:
    amount: Decimal
    currency: str
    day: date
    description: str
    fingerprint: str | None


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    today: Callable[[], date],
    helpers: Helpers,
) -> None:
    @app.get("/api/shared/credit-plan")
    def get_credit_plan(fingerprint: str) -> CreditPlanOut:
        with connection() as conn:
            flow = load_flow(conn)
            book = helpers.load_book(conn, flow, today())
        credit = next((m for m in flow if m.fingerprint == fingerprint), None)
        if credit is None:
            raise HTTPException(404, t("web.unknown_transaction"))
        if not shared.is_eligible_credit(credit, book.links):
            raise HTTPException(422, t("web.link.credit_not_eligible"))
        contacts = list(book.ledger.contacts.values())
        return CreditPlanOut.build(
            ledger_credit.guess_person(credit.description, contacts),
            ledger_credit.expense_options(flow, book.links, credit),
            ledger_credit.credit_options(flow, book.links, credit, contacts, book.banks),
            dict(book.labels),
        )

    def expense_of(
        conn: sqlite3.Connection, body: CreditExpenseBody, flow: Sequence[Movement]
    ) -> _Expense:
        if body.fingerprint is not None:
            move = next((m for m in flow if m.fingerprint == body.fingerprint), None)
            if move is None:
                raise LookupError(t("web.unknown_transaction"))
            links_view.check_shareable(links.load(conn), move)
            return _Expense(
                shared.gross(move),
                move.currency,
                move.day,
                move.merchant or move.description,
                move.fingerprint,
            )
        if body.amount_cents is None:
            raise LinkError(t("analysis.links.amount_positive"))
        if not body.description or not body.description.strip():
            raise LinkError(t("web.ledger.description_required"))
        return _Expense(
            Decimal(body.amount_cents) / 100,
            body.currency,
            helpers.day(body.day, today()),
            body.description,
            None,
        )

    @app.post("/api/shared/groups/from-credit", status_code=201)
    def post_group_from_credit(body: CreditGroupBody) -> GroupOut:
        fingerprints = _fingerprints(body)
        with connection() as conn:
            with helpers.tracked(conn, "group_new", "group-new", body.name, fingerprints):
                found = _create(conn, body, expense_of, helpers, load_flow)
            return helpers.group_response(conn, found)


def _fingerprints(body: CreditGroupBody) -> list[str]:
    given = [p.fingerprint for p in body.payments] + [
        e.fingerprint for e in body.expenses if e.fingerprint is not None
    ]
    if len(set(given)) != len(given):
        raise HTTPException(422, t("web.ledger_credit.repeated"))
    return given


def _create(
    conn: sqlite3.Connection,
    body: CreditGroupBody,
    expense_of: Callable[[sqlite3.Connection, CreditExpenseBody, Sequence[Movement]], _Expense],
    helpers: Helpers,
    load_flow: LoadFlow,
) -> int:
    me = ledger_store.ensure_me(conn)
    payers = [helpers.person_id(conn, p.person) for p in body.payments]
    if me in payers:
        raise LinkError(t("web.ledger_credit.needs_person"))
    received = [helpers.payment_tx(conn, p.fingerprint, True) for p in body.payments]
    flow = load_flow(conn)
    expenses = [expense_of(conn, e, flow) for e in body.expenses]
    group = ledger_store.create_group(conn, body.name, payers, body.category_id)
    for expense, splits in zip(
        expenses, _splits(body, expenses, payers, received, me), strict=True
    ):
        ledger_store.add_entry(
            conn,
            group,
            paid_by=me,
            amount=expense.amount,
            currency=expense.currency,
            day=expense.day,
            description=expense.description,
            splits=splits,
            mode="exact" if body.split == "paid" else "equal",
            category_id=body.category_id,
            fingerprint=expense.fingerprint,
        )
    for payer, move in zip(payers, received, strict=True):
        ledger_store.add_payment(
            conn,
            group,
            from_contact=payer,
            to_contact=me,
            amount=-move.amount,
            currency=move.currency,
            day=move.day,
            fingerprint=move.fingerprint,
        )
    return group


def _splits(
    body: CreditGroupBody,
    expenses: Sequence[_Expense],
    payers: Sequence[int],
    received: Sequence[Movement],
    me: int,
) -> Iterator[tuple[ledger.Split, ...]]:
    people = [me, *dict.fromkeys(payers)]
    if body.split == "equal":
        for expense in expenses:
            yield ledger_store.build_splits(expense.amount, me, "equal", people)
        return
    currencies = {e.currency for e in expenses} | {m.currency for m in received}
    if len(currencies) != 1:
        raise LinkError(t("web.ledger_credit.one_currency"))
    paid: dict[int, Decimal] = {}
    for payer, move in zip(payers, received, strict=True):
        paid = {**paid, payer: paid.get(payer, Decimal(0)) + (-move.amount)}
    for shares in ledger_credit.paid_splits([e.amount for e in expenses], paid, me):
        yield tuple(ledger.Split(c, v) for c, v in shares.items() if v > 0)
