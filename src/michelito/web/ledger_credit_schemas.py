"""JSON models of "a new group from a credit" (`web.ledger_credit_routes`)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from michelito.analysis.ledger_credit import CreditOption, ExpenseOption, PersonGuess
from michelito.web import links as links_view
from michelito.web.ledger_schemas import Cents, Day, Name, NewPerson
from michelito.web.schemas import Currency, LinkedTxOut

Fingerprint = Annotated[str, Field(min_length=1, max_length=200)]
MAX_ITEMS = 20


class PersonGuessOut(BaseModel):
    contact_id: int | None
    name: str
    alias: str | None

    @classmethod
    def of(cls, guess: PersonGuess | None) -> PersonGuessOut | None:
        if guess is None:
            return None
        return cls(contact_id=guess.contact_id, name=guess.name, alias=guess.alias)


class ExpenseOptionOut(LinkedTxOut):
    fits: bool  # the credit is a fair share of it


class CreditOptionOut(BaseModel):
    tx: LinkedTxOut
    person: PersonGuessOut | None


class CreditPlanOut(BaseModel):
    """What the "new group" flow of a credit offers: who paid, the expense it pays back and the
    other credits around it (see `analysis.ledger_credit`)."""

    person: PersonGuessOut | None
    expenses: list[ExpenseOptionOut]
    credits: list[CreditOptionOut]

    @classmethod
    def build(
        cls,
        person: PersonGuess | None,
        expenses: list[ExpenseOption],
        credits: list[CreditOption],
        labels: dict[str, str],
    ) -> CreditPlanOut:
        return cls(
            person=PersonGuessOut.of(person),
            expenses=[
                ExpenseOptionOut(
                    **LinkedTxOut.of(links_view.linked_tx(o.move, labels)).model_dump(),
                    fits=o.fits,
                )
                for o in expenses
            ],
            credits=[
                CreditOptionOut(
                    tx=LinkedTxOut.of(links_view.linked_tx(o.move, labels)),
                    person=PersonGuessOut.of(o.person),
                )
                for o in credits
            ],
        )


class CreditPaymentBody(BaseModel):
    """A credit the user received and who paid it (a contact or a new person)."""

    fingerprint: Fingerprint
    person: NewPerson


class CreditExpenseBody(BaseModel):
    """An expense the user paid: a bank transaction (`fingerprint`) or one typed by hand (cash,
    or not in the bank yet)."""

    fingerprint: Fingerprint | None = None
    amount_cents: Cents | None = None
    currency: Currency = "DOP"
    day: Day | None = None
    description: Annotated[str, Field(max_length=120)] | None = None


class CreditGroupBody(BaseModel):
    """A new group from a credit: the first payment is the credit it starts from. `split`
    "paid": each person's share is what they paid (settled); "equal": every expense split
    equally among the user and the people who paid."""

    name: Name
    category_id: int | None = None
    split: Literal["paid", "equal"] = "paid"
    payments: list[CreditPaymentBody] = Field(min_length=1, max_length=MAX_ITEMS)
    expenses: list[CreditExpenseBody] = Field(min_length=1, max_length=MAX_ITEMS)
