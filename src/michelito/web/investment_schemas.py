"""JSON models of Investments (`/api/investments`): money in whole cents, ISO dates."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool, model_validator

from michelito.analysis import links
from michelito.analysis.investments import Entry
from michelito.analysis.links import InvestmentRole
from michelito.i18n import t
from michelito.web import investment_list
from michelito.web.schemas import InvestmentRefOut, RateOut, _cents, to_cents

Text = Annotated[str | None, Field(max_length=links.PERSON_MAX)]
Fingerprint = Annotated[str, Field(min_length=1, max_length=200)]
CreditRole = Literal["return", "capital", "mixed"]


class InvestmentEntryOut(BaseModel):
    """A movement of the investment, in its own currency (and whether it counts in the
    investment's)."""

    fingerprint: str
    day: str
    merchant: str
    description: str
    account_label: str
    role: InvestmentRole
    amount_cents: int  # positive: what went out (contribution) or came in (credit)
    currency: str
    capital_cents: int  # the capital part of a credit (contribution: 0)
    return_cents: int  # the return part of a credit (contribution: 0)
    excess_cents: int  # capital returned beyond what was contributed: included in `return_cents`
    counted: bool  # false: in another currency with no rate at all, not counted

    @classmethod
    def of(cls, e: Entry, labels: Mapping[str, str]) -> InvestmentEntryOut:
        return cls(
            fingerprint=e.fingerprint,
            day=e.day.isoformat(),
            merchant=e.move.merchant or e.move.description,
            description=e.move.description,
            account_label=labels.get(e.move.account, e.move.account),
            role=e.role,
            amount_cents=to_cents(e.amount),
            currency=e.currency,
            capital_cents=to_cents(e.capital),
            return_cents=to_cents(e.returned),
            excess_cents=to_cents(e.excess),
            counted=e.counted,
        )


class InvestmentOut(InvestmentRefOut):
    """An investment with its figures (in its currency) and its movements."""

    written_off: bool
    first_day: str  # the first contribution
    last_activity: str  # the newest movement
    last_credit: str | None  # the last return (yield or capital)
    contributed_cents: int
    capital_returned_cents: int
    returns_cents: int  # includes the excess returned (`excess_cents`)
    excess_cents: int  # capital returned beyond what was contributed: counts as return
    annual_rate: float | None  # fraction (0.12 = 12 %); null with no capital-days
    pending_dop_cents: int | None  # capital still to come back ≈ RD$; null: US$ with no rate
    unconverted_count: int  # movements in another currency with no rate: not counted
    entries: list[InvestmentEntryOut]  # by date

    @classmethod
    def of(cls, row: investment_list.InvestmentRow, labels: Mapping[str, str]) -> InvestmentOut:
        st = row.state
        return cls(
            **InvestmentRefOut.ref(st).model_dump(),
            written_off=st.link.written_off,
            first_day=st.first.day.isoformat(),
            last_activity=st.last_activity.isoformat(),
            last_credit=None if st.last_credit is None else st.last_credit.isoformat(),
            contributed_cents=to_cents(st.contributed),
            capital_returned_cents=to_cents(st.capital_returned),
            returns_cents=to_cents(st.returns),
            excess_cents=to_cents(st.excess),
            annual_rate=None if row.annual_rate is None else round(float(row.annual_rate), 6),
            pending_dop_cents=_cents(row.pending_dop),
            unconverted_count=len(st.unconverted),
            entries=[InvestmentEntryOut.of(e, labels) for e in st.entries],
        )


class InvestmentUnconvertedOut(BaseModel):
    """US$ with no rate at all: kept apart from the RD$ figures."""

    pending_usd_cents: int
    returns_usd_cents: int


class InvestmentListOut(BaseModel):
    pending_dop_cents: int  # capital still to come back from the active ones ≈ RD$
    returns_year_dop_cents: int  # returns received in the current year ≈ RD$
    year: int
    active_count: int
    unconverted: InvestmentUnconvertedOut
    rate: RateOut | None  # the latest one: used for the US$ capital still to come back
    investments: list[InvestmentOut]  # latest activity first

    @classmethod
    def of(
        cls, found: investment_list.InvestmentList, labels: Mapping[str, str], year: int
    ) -> InvestmentListOut:
        rows = [InvestmentOut.of(r, labels) for r in found.rows]
        return cls(
            pending_dop_cents=to_cents(found.pending_dop),
            returns_year_dop_cents=to_cents(found.returns_year_dop),
            year=year,
            active_count=found.active_count,
            unconverted=InvestmentUnconvertedOut(
                pending_usd_cents=to_cents(found.unconverted_pending_usd),
                returns_usd_cents=to_cents(found.unconverted_returns_usd),
            ),
            rate=None if found.rate is None else RateOut.of(found.rate),
            investments=rows,
        )


class InvestmentBody(BaseModel):
    """A new investment with this debit as its first contribution."""

    fingerprint: Fingerprint
    with_whom: Text = None
    name: Text = None


class InvestmentPatch(BaseModel):
    """Absent fields do not change; an empty text or null clears it."""

    name: Text = None
    with_whom: Text = None
    written_off: StrictBool | None = None


class RoleBody(BaseModel):
    """A credit's role; `capital_cents` only for a mixed one (0 < capital < credit)."""

    role: CreditRole
    capital_cents: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _capital_only_if_mixed(self) -> RoleBody:
        if (self.role == "mixed") != (self.capital_cents is not None):
            raise ValueError(t("web.investment.capital_only_if_mixed"))
        return self

    @property
    def capital(self) -> Decimal | None:
        return None if self.capital_cents is None else Decimal(self.capital_cents) / 100


class MemberBody(BaseModel):
    """Adds a movement: a debit as a contribution (`role` absent or "contribution") or a credit
    with its role."""

    fingerprint: Fingerprint
    role: InvestmentRole = "contribution"
    capital_cents: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _capital_only_if_mixed(self) -> MemberBody:
        if (self.role == "mixed") != (self.capital_cents is not None):
            raise ValueError(t("web.investment.capital_only_if_mixed"))
        return self

    @property
    def capital(self) -> Decimal | None:
        return None if self.capital_cents is None else Decimal(self.capital_cents) / 100
