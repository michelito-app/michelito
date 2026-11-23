"""What the installment plan screens choose from.

- `GET /api/installments/people`: the people in the user's groups (the owner field: mine
  / a person / a new one).
- `GET /api/installments/charges`: the recent charges a new plan can start from (credit card
  charges not in a plan yet), newest first. With `plan_id`, the ones that can be linked to that plan
  (same card and currency) with the installment number each would be.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from michelito.analysis import accounts as account_data
from michelito.analysis import installment_match, installment_owner, installment_store
from michelito.analysis.spending import Movement
from michelito.i18n import t

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
CHARGES_MAX = 250  # about three months of card charges
CREDIT_CARD = "credit_card"  # the account kind installments are charged on


class PersonOut(BaseModel):
    id: int
    name: str


class ChargeOut(BaseModel):
    fingerprint: str
    day: str
    description: str
    merchant: str
    account_label: str
    amount_cents: int
    currency: str
    number: int | None  # for a plan: which installment it would be


def _startable(move: Movement, taken: set[str], cards: set[str]) -> bool:
    return (
        move.account in cards
        and installment_store.can_be_installment(move)
        and move.fingerprint not in taken
        and bool(installment_match.matcher_of(move.description))
    )


def _for_plan(
    moves: Sequence[Movement], plan: installment_store.Plan
) -> list[tuple[Movement, int]]:
    found = []
    for move in moves:
        if (move.account, move.currency) != (plan.account, plan.currency):
            continue
        number = installment_match.number_for(plan.first_month, move.month)
        if 1 <= number <= plan.count and number not in plan.links:
            found.append((move, number))
    return found


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @app.get("/api/installments/people")
    def get_people() -> list[PersonOut]:
        with connection() as conn:
            return [PersonOut(id=p.id, name=p.name) for p in installment_owner.people(conn)]

    @app.get("/api/installments/charges")
    def get_charges(plan_id: int | None = None) -> list[ChargeOut]:
        with connection() as conn:
            flow = load_flow(conn)
            taken = set(installment_store.taken(conn))
            infos = account_data.account_infos(conn)
            plans = {p.id: p for p in installment_store.load(conn)}
        labels = {i.key: i.label for i in infos}
        cards = {i.key for i in infos if i.kind == CREDIT_CARD}
        moves = sorted(
            (m for m in flow if _startable(m, taken, cards)),
            key=lambda m: (m.day, m.fingerprint),
            reverse=True,
        )
        if plan_id is None:
            numbered: list[tuple[Movement, int | None]] = [(m, None) for m in moves]
        elif plan_id in plans:
            numbered = list(_for_plan(moves, plans[plan_id]))
        else:
            raise HTTPException(404, t("web.installments.unknown"))
        return [
            ChargeOut(
                fingerprint=m.fingerprint,
                day=m.day.isoformat(),
                description=m.description,
                merchant=m.merchant or m.description,
                account_label=labels.get(m.account, m.account),
                amount_cents=abs(installment_store.charge_of(m).cents),
                currency=m.currency,
                number=number,
            )
            for m, number in numbered[:CHARGES_MAX]
        ]
