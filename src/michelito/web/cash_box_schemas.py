"""JSON models of the cash box (`/api/cash-box`): money in whole cents, ISO dates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt

from michelito.analysis import corrections
from michelito.analysis.accounts import CASH_BOX_NAME
from michelito.analysis.cash_box import BoxState, EntryKind, Line, LineKind
from michelito.web.schemas import _cents, to_cents

Currency = Literal["DOP", "USD"]
Cents = Annotated[StrictInt, Field(gt=0, le=100_000_000_000)]
Note = Annotated[str | None, Field(max_length=corrections.NOTE_MAX)]


class CurrencyAmountOut(BaseModel):
    currency: str
    amount_cents: int


def _amounts(pairs: tuple[tuple[str, Decimal], ...]) -> list[CurrencyAmountOut]:
    return [CurrencyAmountOut(currency=c, amount_cents=to_cents(a)) for c, a in pairs]


class CashLineOut(BaseModel):
    """An inflow or outflow of the box. `amount_cents` is signed, in the box currency (+ in,
    - out; null: a deposit in another currency with no rate, which does not lower the balance)."""

    kind: LineKind
    day: str
    fingerprint: str
    entry_id: int | None  # manual entries (edited and deleted here)
    currency: str
    amount_cents: int | None
    dop_cents: int | None  # ≈ RD$ at its month's rate; null with no rate
    source_amount_cents: int  # the movement as it appears, positive
    source_currency: str
    merchant: str
    account_label: str
    category: str
    category_id: int | None
    note: str
    in_flow: bool  # shown in Transactions (everything but the opening balance)
    group: (
        str | None
    )  # the shared group it belongs to (its title); deleting it removes it from the group

    @classmethod
    def of(
        cls,
        line: Line,
        labels: Mapping[str, str],
        category_ids: Mapping[str, int],
        groups: Mapping[str, str],
    ) -> CashLineOut:
        move = line.move
        return cls(
            kind=line.kind,
            day=line.day.isoformat(),
            fingerprint=line.fingerprint,
            entry_id=None if line.entry is None else line.entry.id,
            currency=line.currency,
            amount_cents=_cents(line.amount),
            dop_cents=_cents(line.dop),
            source_amount_cents=to_cents(line.source_amount),
            source_currency=line.source_currency,
            merchant=CASH_BOX_NAME if move is None else move.merchant,
            account_label=CASH_BOX_NAME if move is None else labels.get(move.account, move.account),
            category="" if move is None else move.category,
            category_id=None if move is None else category_ids.get(move.ref),
            note="" if move is None else move.note,
            in_flow=move is not None,
            group=groups.get(line.fingerprint),
        )


class CashBoxOut(BaseModel):
    """The cash box: balance per currency and ≈ RD$, warnings, and its inflows and outflows."""

    account_key: str
    label: str
    exists: bool  # already used (its account shows in the account filter)
    balances: list[CurrencyAmountOut]  # RD$ first
    total_dop_cents: int  # each movement at its month's rate
    unconverted: list[CurrencyAmountOut]  # no rate: not in total_dop_cents
    negative: list[CurrencyAmountOut]  # currencies below zero (warned about, not blocked)
    uncounted: list[str]  # deposits in another currency with no rate: they do not lower the balance
    lines: list[CashLineOut]  # newest first

    @classmethod
    def of(
        cls,
        state: BoxState,
        exists: bool,
        labels: Mapping[str, str],
        category_ids: Mapping[str, int],
        groups: Mapping[str, str],
    ) -> CashBoxOut:
        return cls(
            account_key=state.account_key,
            label=CASH_BOX_NAME,
            exists=exists,
            balances=_amounts(state.balances),
            total_dop_cents=to_cents(state.total_dop),
            unconverted=_amounts(state.unconverted),
            negative=_amounts(state.negative),
            uncounted=list(state.uncounted),
            lines=[CashLineOut.of(line, labels, category_ids, groups) for line in state.lines],
        )


class EntryBody(BaseModel):
    """A manual entry: opening balance, inflow (income) or outflow (expense)."""

    kind: EntryKind
    day: date
    amount_cents: Cents
    currency: Currency
    category_id: int | None = None  # inflow: an income category; outflow: an expense one
    note: Note = None


class EntryPatch(BaseModel):
    """Changes day, amount and currency; category and note when given (the kind does not change).
    A present and empty (or null) note clears it; an absent one leaves it as is."""

    day: date
    amount_cents: Cents
    currency: Currency
    category_id: int | None = None
    note: Note = None


class DepositBody(BaseModel):
    """`currency`: the currency it left the box in (absent: the credit's); `amount_cents`: how
    much left in it (absent: the credit at its month's rate)."""

    currency: Currency | None = None
    amount_cents: Cents | None = None
