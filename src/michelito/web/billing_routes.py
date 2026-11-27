"""Billing route: what a credit card billed, by whole statements (`analysis.billing`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from michelito.analysis import billing, rates
from michelito.i18n import t
from michelito.web.review_routes import Connection

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
DEFAULT_MONTHS = 12


class StatementBillingOut(BaseModel):
    period_end: str
    currency: str
    groups: dict[str, int]  # cents by group, see analysis.billing.GROUPS
    previous_balance_cents: int | None
    closing_balance_cents: int | None
    dop_per_usd: str | None  # the rate used (US$ only)
    rate_month: str | None  # the month that rate comes from
    converted_dop_cents: dict[str, int] | None  # the groups in RD$; None for US$ with no rate

    @classmethod
    def of(cls, line: billing.StatementBilling) -> StatementBillingOut:
        return cls(
            period_end=line.period_end.isoformat(),
            currency=line.currency,
            groups=dict(line.groups),
            previous_balance_cents=line.previous_balance_cents,
            closing_balance_cents=line.closing_balance_cents,
            dop_per_usd=str(line.rate.value) if line.rate else None,
            rate_month=line.rate.month_used if line.rate else None,
            converted_dop_cents=_plain(line.converted_dop),
        )


class BillingOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account: str
    first: str = Field(serialization_alias="from")
    last: str = Field(serialization_alias="to")
    statements: list[StatementBillingOut]
    totals: dict[str, dict[str, int]]  # currency -> cents by group
    converted_dop_cents: dict[str, int] | None  # every statement in RD$; None if a rate is missing
    missing: list[str]  # months of the range without a statement
    complete: bool

    @classmethod
    def of(cls, result: billing.Billing) -> BillingOut:
        return cls(
            account=result.account_key,
            first=result.from_month,
            last=result.to_month,
            statements=[StatementBillingOut.of(s) for s in result.statements],
            totals={c: dict(g) for c, g in result.totals.items()},
            converted_dop_cents=_plain(result.converted_dop),
            missing=list(result.missing),
            complete=result.complete,
        )


def _plain(groups: Mapping[str, int] | None) -> dict[str, int] | None:
    return None if groups is None else dict(groups)


def register(app: FastAPI, connection: Connection) -> None:
    @app.get("/api/billing", response_model_by_alias=True)
    def get_billing(
        account: Annotated[str, Query(min_length=1, max_length=100)],
        first: Annotated[str | None, Query(alias="from", pattern=_MONTH_PATTERN)] = None,
        last: Annotated[str | None, Query(alias="to", pattern=_MONTH_PATTERN)] = None,
    ) -> BillingOut:
        """By default, the 12 months up to the card's newest statement."""
        with connection() as conn:
            try:
                billing.require_card(conn, account)
            except billing.AccountNotFound:
                raise HTTPException(404, t("web.billing.unknown_account")) from None
            except billing.NotACard:
                raise HTTPException(422, t("web.billing.not_a_card")) from None
            # No `to`: the newest statement's month, but never before `from`.
            newest = billing.latest_month(conn, account)
            last = last or max((m for m in (newest, first) if m), default=None)
            if last is None:
                raise HTTPException(404, t("web.billing.no_statements"))
            first = first or billing.months_back(last, DEFAULT_MONTHS - 1)
            if first > last:
                raise HTTPException(422, t("web.billing.range"))
            if billing.span(first, last) > billing.MAX_RANGE_MONTHS:
                raise HTTPException(422, t("web.range_too_long", months=billing.MAX_RANGE_MONTHS))
            result = billing.account_billing(conn, account, first, last, rates.load(conn))
        return BillingOut.of(result)
