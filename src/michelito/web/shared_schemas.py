"""JSON models of Shared (`GET /api/shared`): money in whole cents, ISO dates."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from michelito.analysis.shared import ExpenseState
from michelito.web import shared_list
from michelito.web.schemas import (
    CurrencyCentsOut,
    RateOut,
    _cents,
    _currency_cents,
    to_cents,
)


class SharedListExpenseOut(BaseModel):
    """An expense of the group: its split and whether it is settled (in its currency)."""

    fingerprint: str
    day: str
    merchant: str
    account_label: str
    amount_cents: int  # the whole expense (before splitting)
    currency: str
    people: int | None  # "We were N"
    my_share_cents: int | None  # "My share: X"
    for_other: bool  # "I paid it for someone else"
    share_cents: int
    reimbursed_cents: int
    pending_cents: int
    written_off_cents: int

    @classmethod
    def of(cls, e: ExpenseState, labels: Mapping[str, str]) -> SharedListExpenseOut:
        split = e.split
        return cls(
            fingerprint=e.fingerprint,
            day=e.day.isoformat(),
            merchant=e.move.merchant or e.move.description,
            account_label=labels.get(e.move.account, e.move.account),
            amount_cents=to_cents(e.amount),
            currency=e.currency,
            people=split.people,
            my_share_cents=_cents(split.my_share),
            for_other=split.for_other,
            share_cents=to_cents(e.share),
            reimbursed_cents=to_cents(e.reimbursed),
            pending_cents=to_cents(e.pending),
            written_off_cents=to_cents(e.written_off),
        )


class SharedListRefundOut(BaseModel):
    """A reimbursement: a linked credit (`key` is its fingerprint) or a manual one
    (`manual:<id>`)."""

    key: str
    manual: bool
    day: str
    description: str  # credit: merchant or description; manual: the person (may be empty)
    account_label: str  # credit: its account; manual: the "where" ("" = cash)
    amount_cents: int  # positive
    currency: str

    @classmethod
    def of(cls, r: shared_list.RefundRow) -> SharedListRefundOut:
        return cls(
            key=r.key,
            manual=r.manual,
            day=r.day.isoformat(),
            description=r.description,
            account_label=r.account_label,
            amount_cents=to_cents(r.amount),
            currency=r.currency,
        )


class SharedListGroupOut(BaseModel):
    id: int
    title: str  # name, else "With whom", else the merchant of the first expense
    name: str
    with_whom: str
    status: shared_list.Status
    first_fingerprint: str  # the first expense: opens the group screen
    first_day: str  # the oldest expense
    last_day: str  # the newest expense
    last_activity: str  # the most recent expense or reimbursement
    expenses: list[SharedListExpenseOut]  # oldest first
    refunds: list[SharedListRefundOut]  # in the order they are applied
    paid: list[CurrencyCentsOut]  # sum of the expense amounts, by currency
    reimbursed: list[CurrencyCentsOut]  # sum of reimbursements, by their currency
    pending: list[CurrencyCentsOut]  # owed to you, by currency (empty if nothing)
    pending_dop_cents: (
        int | None
    )  # ≈ RD$ of what is pending; null when nothing is pending or no rate
    unconverted_usd_cents: int  # pending US$ with no rate at all
    excess: list[CurrencyCentsOut]  # paid back in excess after everything was settled

    @classmethod
    def of(cls, row: shared_list.GroupRow, labels: Mapping[str, str]) -> SharedListGroupOut:
        st = row.state
        return cls(
            id=st.id,
            title=st.title,
            name=st.link.name,
            with_whom=st.link.with_whom,
            status=row.status,
            first_fingerprint=st.first.fingerprint,
            first_day=row.first_day.isoformat(),
            last_day=row.last_day.isoformat(),
            last_activity=row.last_activity.isoformat(),
            expenses=[SharedListExpenseOut.of(e, labels) for e in row.expenses],
            refunds=[SharedListRefundOut.of(r) for r in row.refunds],
            paid=_currency_cents(list(row.paid)),
            reimbursed=_currency_cents(list(row.reimbursed)),
            pending=_currency_cents(list(row.pending)),
            pending_dop_cents=_cents(row.pending_dop),
            unconverted_usd_cents=to_cents(row.unconverted_usd),
            excess=_currency_cents(list(st.excess_by)),
        )


class SharedUnconvertedOut(BaseModel):
    """US$ with no rate at all: apart from the RD$ figures."""

    owed_usd_cents: int
    reimbursed_usd_cents: int


class SharedListOut(BaseModel):
    owed_dop_cents: int  # owed to you (sum of the rows, as in Pending)
    reimbursed_year_dop_cents: int  # reimbursements dated in the current year
    year: int
    open_count: int  # groups with something pending
    unconverted: SharedUnconvertedOut
    rate: RateOut | None  # the most recent: the one for what is pending in US$
    groups: list[SharedListGroupOut]  # latest activity first

    @classmethod
    def of(
        cls, found: shared_list.SharedList, labels: Mapping[str, str], year: int
    ) -> SharedListOut:
        groups = [SharedListGroupOut.of(r, labels) for r in found.rows]
        return cls(
            # Sums the rows' cents: it matches what is shown (as in Pending).
            owed_dop_cents=sum(g.pending_dop_cents or 0 for g in groups),
            reimbursed_year_dop_cents=to_cents(found.reimbursed_year_dop),
            year=year,
            open_count=found.open_count,
            unconverted=SharedUnconvertedOut(
                owed_usd_cents=to_cents(found.unconverted_owed_usd),
                reimbursed_usd_cents=to_cents(found.unconverted_reimbursed_usd),
            ),
            rate=None if found.rate is None else RateOut.of(found.rate),
            groups=groups,
        )
