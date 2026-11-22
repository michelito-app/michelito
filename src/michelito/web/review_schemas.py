"""JSON models of "To review" (money in whole cents, ISO dates)."""

from __future__ import annotations

from pydantic import BaseModel, Field, StrictBool

from michelito.analysis.review import Kind
from michelito.web.review import ReviewView
from michelito.web.schemas import _cents, to_cents


class ReviewItemOut(BaseModel):
    kind: Kind
    fingerprint: str
    day: str
    month: str
    merchant: str
    description: str
    account_label: str
    amount_cents: int  # in the original currency, positive
    currency: str
    amount_dop_cents: int | None  # None: US$ with no rate
    reason: str
    reviewed: bool
    investment_id: int | None = None  # possible contribution or return: the proposed investment
    category_id: int | None = None  # possible rule: the proposed category
    reserve_id: int | None = None  # possible reserve: the proposed reserve
    group_id: int | None = None  # possible payment: the group
    contact_id: int | None = None  # possible payment: who pays (null: unattributed)
    payment_id: int | None = None  # possible payment: the unlinked payment it reconciles
    payment_ids: list[int] = Field(default_factory=list)  # possible cover: all its payments
    provisional: bool = False  # still provisional (from a bank alert): it can be discarded
    receipt_id: int | None = None  # possible receipt: the merchant receipt proposed for it

    @classmethod
    def of(cls, view: ReviewView) -> ReviewItemOut:
        item = view.item
        return cls(
            kind=item.kind,
            fingerprint=item.fingerprint,
            day=item.day.isoformat(),
            month=item.day.strftime("%Y-%m"),
            merchant=item.merchant,
            description=item.description,
            account_label=view.account_label,
            amount_cents=to_cents(item.amount),
            currency=item.currency,
            amount_dop_cents=_cents(item.amount_dop),
            reason=item.reason,
            reviewed=item.reviewed,
            investment_id=item.investment_id,
            category_id=item.category_id,
            reserve_id=item.reserve_id,
            group_id=item.group_id,
            contact_id=item.contact_id,
            payment_id=item.payment_id,
            payment_ids=list(item.payment_ids),
            provisional=item.provisional,
            receipt_id=item.receipt_id,
        )


class ReviewBody(BaseModel):
    reviewed: StrictBool


class ReviewMarkOut(BaseModel):
    kind: Kind
    fingerprint: str
    reviewed: bool
