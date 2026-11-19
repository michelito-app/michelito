"""JSON models of the budget and the reserves (money in whole RD$ cents)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool, StringConstraints

from michelito.analysis import budget
from michelito.analysis import reserve_suggestions as suggest
from michelito.web.budget import BudgetView, Overview, ReserveView
from michelito.web.schemas import _cents, to_cents

Fingerprint = Annotated[str, StringConstraints(min_length=1, max_length=64)]
MonthText = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class WarningOut(BaseModel):
    habitual_cents: int
    basis_cents: int
    up: bool


class LineOut(BaseModel):
    category_id: int
    category: str
    cap_cents: int | None  # None: "no budget"
    manual: bool
    spent_cents: int  # counted against the cap
    one_offs_cents: int
    covered_cents: int  # covered by reserves
    without_rate: int  # US$ expenses without a rate (not counted)
    over_cents: int  # the exact amount over the cap
    passed: bool  # over by more than the margin (max(5 %, RD$ 500)): counts as over
    refunds_cents: int  # refunded beyond spending in the month (spending stays at 0)
    habitual_cents: int | None
    warning: WarningOut | None
    active: bool  # on top (cap, something this month or a warning) or in "Other categories"

    @classmethod
    def of(cls, line: budget.Line, name: str) -> LineOut:
        found = line.warning
        return cls(
            category_id=line.category_id,
            category=name,
            cap_cents=_cents(line.cap),
            manual=line.manual,
            spent_cents=to_cents(line.spent),
            one_offs_cents=to_cents(line.one_offs),
            covered_cents=to_cents(line.covered),
            without_rate=line.without_rate,
            over_cents=to_cents(line.over),
            passed=line.passed,
            refunds_cents=to_cents(line.refunds),
            habitual_cents=_cents(line.habitual),
            warning=None
            if found is None
            else WarningOut(
                habitual_cents=to_cents(found.habitual),
                basis_cents=to_cents(found.basis),
                up=found.up,
            ),
            active=line.active,
        )


class BudgetOut(BaseModel):
    active: bool
    month: str
    lines: list[LineOut]
    cap_cents: int
    spent_cents: int
    over_count: int
    over_cents: int
    reference_months: list[str]
    filtered: bool  # with an account filter: caps of all, spending of the chosen ones
    missing: list[str]  # accounts without the month's complete statement (partial data)

    @classmethod
    def of(cls, view: BudgetView) -> BudgetOut:
        return cls(
            active=view.active,
            month=view.month,
            lines=[LineOut.of(line, view.names.get(line.category_id, "")) for line in view.lines],
            cap_cents=to_cents(view.totals.cap),
            spent_cents=to_cents(view.totals.spent),
            over_count=view.totals.over_count,
            over_cents=to_cents(view.totals.over),
            reference_months=view.reference_months,
            filtered=view.filtered,
            missing=view.missing,
        )


class CapBody(BaseModel):
    cap_cents: int | None = Field(ge=0, le=10_000_000_000)  # None: "no budget"

    @property
    def cap(self) -> Decimal | None:
        return None if self.cap_cents is None else Decimal(self.cap_cents) / 100


class WarningBody(BaseModel):
    accept: StrictBool


class EntryOut(BaseModel):
    entry_id: int | None  # the change-log entry (None if nothing changed)


class MemberOut(BaseModel):
    fingerprint: str
    day: str
    month: str
    merchant: str
    amount_cents: int
    currency: str
    amount_dop_cents: int | None


class ReserveOut(BaseModel):
    id: int
    name: str
    amount_cents: int
    category_id: int
    category: str
    due_month: str
    every_months: int | None  # None: only once
    multiple: bool
    next_due: str | None  # None: one-time and already past
    monthly_cents: int
    year_spent_cents: int
    year_estimated_cents: int
    year_without_rate: int
    paid: bool  # the next due month already has its expense linked
    members: list[MemberOut]

    @classmethod
    def of(cls, view: ReserveView) -> ReserveOut:
        r = view.reserve
        return cls(
            id=r.id,
            name=r.name,
            amount_cents=to_cents(r.amount),
            category_id=r.category_id,
            category=view.category,
            due_month=r.due_month,
            every_months=r.every_months,
            multiple=r.multiple,
            next_due=view.next_due,
            monthly_cents=to_cents(view.monthly),
            year_spent_cents=to_cents(view.year.spent),
            year_estimated_cents=to_cents(view.year.estimated),
            year_without_rate=view.year.without_rate,
            paid=view.paid,
            members=[
                MemberOut(
                    fingerprint=m.move.fingerprint,
                    day=m.move.day.isoformat(),
                    month=m.move.month,
                    merchant=m.move.merchant or m.move.description,
                    amount_cents=to_cents(m.move.amount),
                    currency=m.move.currency,
                    amount_dop_cents=_cents(m.dop),
                )
                for m in view.members
            ],
        )


class SuggestionOut(BaseModel):
    key: str
    name: str
    amount_cents: int
    category_id: int
    category: str
    due_month: str
    every_months: int
    multiple: bool
    reason: str

    @classmethod
    def of(cls, item: suggest.Suggestion, category: str) -> SuggestionOut:
        return cls(
            key=item.key,
            name=item.name,
            amount_cents=to_cents(item.amount),
            category_id=item.category_id,
            category=category,
            due_month=item.due_month,
            every_months=item.every_months,
            multiple=item.multiple,
            reason=item.reason,
        )


class ReservesOut(BaseModel):
    items: list[ReserveOut]
    suggestions: list[SuggestionOut]
    monthly_cents: int  # what is set aside per month for all of them


class ReserveBody(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    amount_cents: int = Field(gt=0, le=10_000_000_000)
    category_id: int
    due_month: MonthText
    every_months: Literal[6, 12] | None = None  # every 6 months or every year; None: only once
    multiple: StrictBool = False
    source: Annotated[str, StringConstraints(max_length=200)] | None = None  # a suggestion


class ReservePatch(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None
    amount_cents: int | None = Field(default=None, gt=0, le=10_000_000_000)
    category_id: int | None = None
    due_month: MonthText | None = None
    every_months: Literal[6, 12] | None = None
    once: StrictBool | None = None  # true: becomes "only once" (`every_months` is ignored)
    multiple: StrictBool | None = None


class CreatedOut(BaseModel):
    id: int
    entry_id: int | None


class MembersBody(BaseModel):
    fingerprints: list[Fingerprint] = Field(min_length=1, max_length=500)


class SkippedOut(BaseModel):
    fingerprint: str
    reason: str  # "linked", "not_expense" or "unknown"
    message: str


class MembersOut(BaseModel):
    applied: list[str]
    skipped: list[SkippedOut]
    entry_id: int | None


class DismissBody(BaseModel):
    # "recurring:…", "irregular:…" or "peak:…" (only the shape is validated: with an account
    # filter the suggestion may not be among those of all accounts).
    key: Annotated[
        str, StringConstraints(pattern=r"^(recurring|irregular|peak):.+$", max_length=200)
    ]
    name: Annotated[str, StringConstraints(max_length=80)] | None = None  # for the change log


class ReserveOptionOut(BaseModel):
    id: int
    name: str


class ReserveRefOut(BaseModel):
    id: int
    name: str
    category: str
    next_due: str | None
    suggested: bool  # the one "To review" proposes for this expense


class TxReserveOut(BaseModel):
    """The Reserve section of a transaction's detail view."""

    reserve: ReserveRefOut | None  # the reserve covering it
    options: list[ReserveRefOut]  # those it can link to (the suggested one first)
    can_link: bool
    reason: str  # why it cannot, otherwise


class UpcomingOut(BaseModel):
    id: int
    name: str
    due_month: str
    amount_cents: int


class OverviewOut(BaseModel):
    active: bool
    over_count: int | None  # None with an account filter: categories over their cap are not counted
    over_cents: int
    missing: list[str]  # accounts without the month's complete statement
    monthly_cents: int
    reserves: int
    upcoming: list[UpcomingOut]

    @classmethod
    def of(cls, found: Overview) -> OverviewOut:
        return cls(
            active=found.active,
            over_count=found.over_count,
            over_cents=to_cents(found.over),
            monthly_cents=to_cents(found.monthly),
            reserves=found.reserves,
            missing=found.missing,
            upcoming=[
                UpcomingOut(id=r.id, name=r.name, due_month=due, amount_cents=to_cents(r.amount))
                for r, due in found.upcoming
            ],
        )
