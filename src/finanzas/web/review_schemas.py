"""Modelos JSON de «Para revisar» (dinero en centavos enteros, fechas ISO)."""

from __future__ import annotations

from pydantic import BaseModel, StrictBool

from finanzas.analysis.review import Kind
from finanzas.web.review import ReviewView
from finanzas.web.schemas import _cents, to_cents


class ReviewItemOut(BaseModel):
    kind: Kind
    fingerprint: str
    day: str
    month: str
    merchant: str
    description: str
    account_label: str
    amount_cents: int  # en la moneda original, positivo
    currency: str
    amount_dop_cents: int | None  # None: US$ sin tasa
    reason: str
    reviewed: bool
    investment_id: int | None = None  # aporte o cobro posible: la inversión que se propone
    category_id: int | None = None  # regla posible: la categoría que se propone
    reserve_id: int | None = None  # reserva posible: la reserva que se propone

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
        )


class ReviewBody(BaseModel):
    reviewed: StrictBool


class ReviewMarkOut(BaseModel):
    kind: Kind
    fingerprint: str
    reviewed: bool
