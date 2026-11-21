"""JSON models of the cash box (`/api/cash-box`): money in whole cents, ISO dates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StrictInt, field_validator

from michelito.analysis import corrections
from michelito.analysis.accounts import CASH_BOX_NAME
from michelito.analysis.cash_box import (
    CONCEPT_MAX,
    BoxState,
    EntryKind,
    Line,
    LineKind,
    balance_on,
)
from michelito.analysis.cash_schedule import MAX_COUNT, Frequency, ScheduleKind
from michelito.web.cash_view import CashExtras, Concept, OccurrenceView, ScheduleView
from michelito.web.schemas import _cents, _iso, to_cents

Currency = Literal["DOP", "USD"]
Cents = Annotated[StrictInt, Field(gt=0, le=100_000_000_000)]
Note = Annotated[str | None, Field(max_length=corrections.NOTE_MAX)]
# The length is checked again after collapsing spaces (`cash_box.check_concept`).
ConceptText = Annotated[str, Field(min_length=1, max_length=CONCEPT_MAX * 2)]


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
    concept: str | None  # what a hand-made income or expense was (null before schema 23)
    schedule_id: int | None  # the schedule that materialized it
    # An unanswered occurrence: "pending" (within a week) or "unconfirmed" (a payment kept as
    # paid); empty otherwise.
    state: str
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
            concept=None if line.entry is None else line.entry.concept,
            schedule_id=None if line.entry is None else line.entry.schedule_id,
            state="" if move is None else move.cash_state,
            group=groups.get(line.fingerprint),
        )


class CashBoxOut(BaseModel):
    """The cash box: balance per currency and ≈ RD$, warnings, and its inflows and outflows."""

    account_key: str
    label: str
    exists: bool  # already used (its account shows in the account filter)
    balances: list[CurrencyAmountOut]  # RD$ first
    # Counting only what is dated up to today (later entries wait): what a reconcile compares.
    balances_today: list[CurrencyAmountOut] = []
    total_dop_cents: int  # each movement at its month's rate
    unconverted: list[CurrencyAmountOut]  # no rate: not in total_dop_cents
    negative: list[CurrencyAmountOut]  # currencies below zero (warned about, not blocked)
    uncounted: list[str]  # deposits in another currency with no rate: they do not lower the balance
    lines: list[CashLineOut]  # newest first
    schedules: list[ScheduleOut] = []
    occurrences: list[OccurrenceOut] = []  # waiting for an answer ("To review"), oldest first
    upcoming: UpcomingOut | None = None  # the next one due within a week ("Next")
    activated_on: str | None = None  # since when withdrawals move into cash automatically
    reconcile_due: bool = False  # the monthly "Reconcile cash" prompt
    last_reconciled: str | None = None

    @classmethod
    def of(
        cls,
        state: BoxState,
        exists: bool,
        labels: Mapping[str, str],
        category_ids: Mapping[str, int],
        groups: Mapping[str, str],
        extras: CashExtras | None = None,
        today: date | None = None,
    ) -> CashBoxOut:
        more = {} if extras is None else _extras(extras)
        if today is not None:
            more["balances_today"] = _amounts(
                tuple((c, balance_on(state, c, today)) for c, _ in state.balances)
            )
        return cls(
            **more,
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


class ScheduleOut(BaseModel):
    id: int
    kind: ScheduleKind
    concept: str
    amount_cents: int
    currency: str
    category: str
    category_id: int | None
    frequency: Frequency
    start_day: str
    end_day: str | None
    max_count: int | None
    paused: bool
    next_due: str | None
    finished: bool

    @classmethod
    def of(cls, view: ScheduleView) -> ScheduleOut:
        item = view.schedule
        return cls(
            id=item.id,
            kind=item.kind,
            concept=item.concept,
            amount_cents=to_cents(item.amount),
            currency=item.currency,
            category=view.category,
            category_id=view.category_id,
            frequency=item.frequency,
            start_day=item.start.isoformat(),
            end_day=_iso(item.end),
            max_count=item.max_count,
            paused=item.paused,
            next_due=_iso(view.next_due),
            finished=view.finished,
        )


class OccurrenceOut(BaseModel):
    """A scheduled occurrence waiting for an answer. `state`: "pending" (it counts) or "lapsed"
    (a collection unanswered for over a week: it does not count until confirmed)."""

    entry_id: int
    fingerprint: str
    schedule_id: int | None
    kind: EntryKind
    concept: str
    day: str
    amount_cents: int
    currency: str
    category: str
    category_id: int | None
    state: str

    @classmethod
    def of(cls, view: OccurrenceView) -> OccurrenceOut:
        entry = view.entry
        return cls(
            entry_id=entry.id,
            fingerprint=entry.fingerprint,
            schedule_id=entry.schedule_id,
            kind=entry.kind,
            concept=entry.concept or "",
            day=entry.day.isoformat(),
            amount_cents=to_cents(entry.amount),
            currency=entry.currency,
            category=view.category,
            category_id=view.category_id,
            state=view.state,
        )


class UpcomingOut(BaseModel):
    schedule_id: int
    kind: ScheduleKind
    concept: str
    day: str
    amount_cents: int
    currency: str


def _extras(extras: CashExtras) -> dict[str, Any]:
    upcoming = extras.upcoming
    return {
        "schedules": [ScheduleOut.of(view) for view in extras.schedules],
        "occurrences": [OccurrenceOut.of(view) for view in extras.occurrences],
        "upcoming": None
        if upcoming is None
        else UpcomingOut(
            schedule_id=upcoming.schedule.id,
            kind=upcoming.schedule.kind,
            concept=upcoming.schedule.concept,
            day=upcoming.day.isoformat(),
            amount_cents=to_cents(upcoming.schedule.amount),
            currency=upcoming.schedule.currency,
        ),
        "activated_on": _iso(extras.activated_on),
        "reconcile_due": extras.reconcile_due,
        "last_reconciled": _iso(extras.last_reconciled),
    }


class ConceptOut(BaseModel):
    concept: str
    kind: EntryKind
    currency: str
    category_id: int | None
    last_day: str

    @classmethod
    def of(cls, item: Concept) -> ConceptOut:
        return cls(
            concept=item.concept,
            kind=item.kind,  # type: ignore[arg-type]
            currency=item.currency,
            category_id=item.category_id,
            last_day=item.last_day.isoformat(),
        )


class RepeatBody(BaseModel):
    """ "Repeat": the entry becomes the first occurrence of a schedule from its date."""

    frequency: Frequency
    end_day: date | None = None
    max_count: Annotated[int | None, Field(ge=1, le=MAX_COUNT)] = None


class ScheduleBody(BaseModel):
    kind: ScheduleKind
    concept: ConceptText
    amount_cents: Cents
    currency: Currency
    category_id: int | None = None
    frequency: Frequency
    start_day: date
    end_day: date | None = None
    max_count: Annotated[int | None, Field(ge=1, le=MAX_COUNT)] = None


class PauseBody(BaseModel):
    paused: bool


class AnswerBody(BaseModel):
    """An answer: "Paid" / "Received" (`confirm`), another amount (`amount`, with
    `amount_cents`) or "Not paid" / "It did not come" (`skip`)."""

    action: Literal["confirm", "amount", "skip"]
    amount_cents: Cents | None = None


class CountOut(BaseModel):
    currency: Currency
    amount_cents: Annotated[StrictInt, Field(ge=0, le=100_000_000_000)]


class ReconcileBody(BaseModel):
    """How much cash there is now, per currency (at least one)."""

    counts: Annotated[list[CountOut], Field(min_length=1, max_length=2)]

    @field_validator("counts")
    @classmethod
    def _one_per_currency(cls, counts: list[CountOut]) -> list[CountOut]:
        if len({item.currency for item in counts}) != len(counts):
            raise ValueError("one count per currency")
        return counts


class EntryBody(BaseModel):
    """A manual entry: opening balance, inflow (income) or outflow (expense)."""

    kind: EntryKind
    day: date
    amount_cents: Cents
    currency: Currency
    category_id: int | None = None  # inflow: an income category; outflow: an expense one
    note: Note = None
    # Required for a new inflow or outflow (the route says so); not for the initial balance.
    concept: ConceptText | None = None
    repeat: RepeatBody | None = None


class EntryPatch(BaseModel):
    """Changes day, amount and currency; category and note when given (the kind does not change).
    A present and empty (or null) note clears it; an absent one leaves it as is."""

    day: date
    amount_cents: Cents
    currency: Currency
    category_id: int | None = None
    note: Note = None
    concept: ConceptText | None = None


class DepositBody(BaseModel):
    """`currency`: the currency it left the box in (absent: the credit's); `amount_cents`: how
    much left in it (absent: the credit at its month's rate)."""

    currency: Currency | None = None
    amount_cents: Cents | None = None


CashBoxOut.model_rebuild()
