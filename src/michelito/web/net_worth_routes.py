"""`GET /api/net-worth`: net worth today, per group and per holding (with the month's change),
and its monthly history (see `analysis.net_worth` and `web.net_worth`). Amounts in RD$ cents."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from pydantic import BaseModel

from michelito.analysis import links, net_worth, rates
from michelito.analysis.net_worth import Holding
from michelito.analysis.spending import Movement
from michelito.web import cash_box_routes, ledger_routes, ledger_view
from michelito.web import net_worth as sources
from michelito.web.ledger_schemas import TotalOut

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
Today = Callable[[], date]


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value())


def _optional(value: Decimal | None) -> int | None:
    return None if value is None else _cents(value)


class GroupOut(BaseModel):
    group: str
    side: str
    total_cents: int


class HoldingOut(BaseModel):
    key: str
    label: str
    group: str
    currency: str
    value_cents: int | None  # in its own currency
    value_dop_cents: int | None
    change_dop_cents: int | None  # since the end of last month


class PointOut(BaseModel):
    month: str
    day: str
    net_cents: int
    assets_cents: int
    debts_cents: int


class NetWorthOut(BaseModel):
    net_cents: int
    assets_cents: int
    debts_cents: int
    unconverted: bool  # some US$ value has no rate and does not add up
    groups: list[GroupOut]
    holdings: list[HoldingOut]
    history: list[PointOut]


def _holding_out(holding: Holding, today: date, by_month: dict[str, rates.Rate]) -> HoldingOut:
    return HoldingOut(
        key=holding.key,
        label=holding.label,
        group=holding.group,
        currency=holding.currency,
        value_cents=_optional(holding.value_on(today)),
        value_dop_cents=_optional(net_worth.value_dop(holding, today, by_month)),
        change_dop_cents=_optional(net_worth.month_change(holding, today, by_month))
        if holding.historic
        else None,
    )


def build(holdings: Sequence[Holding], today: date, by_month: dict[str, rates.Rate]) -> NetWorthOut:
    found = net_worth.totals(holdings, today, by_month)
    sides = {h.group: h.side for h in holdings}
    return NetWorthOut(
        net_cents=_cents(found.net),
        assets_cents=_cents(found.assets),
        debts_cents=_cents(found.debts),
        unconverted=found.unconverted,
        groups=[
            GroupOut(group=group, side=sides[group], total_cents=_cents(total))
            for group, total in found.groups.items()
        ],
        holdings=[_holding_out(h, today, by_month) for h in holdings],
        history=[
            PointOut(
                month=p.month,
                day=p.day.isoformat(),
                net_cents=_cents(p.net),
                assets_cents=_cents(p.assets),
                debts_cents=_cents(p.debts),
            )
            for p in net_worth.history(holdings, by_month, today)
        ],
    )


def _shared(total: TotalOut) -> tuple[str, Decimal, Decimal]:
    return (
        total.currency,
        Decimal(total.owed_to_me_cents) / 100,
        Decimal(total.i_owe_cents) / 100,
    )


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow, today: Today) -> None:
    @app.get("/api/net-worth")
    def get_net_worth() -> NetWorthOut:
        now = today()
        with connection() as conn:
            flow = load_flow(conn)
            by_month = rates.load(conn)
            box, _exists = cash_box_routes.box_state(conn, flow, now)
            home = ledger_view.home(ledger_routes.load_book(conn, flow, now), now)
            holdings = [
                *sources.account_holdings(conn),
                *sources.loan_holdings(conn),
                *sources.cash_holdings(box),
                *sources.investment_holdings(flow, links.load(conn), by_month),
                *sources.shared_holdings([_shared(t) for t in home.totals]),
            ]
        return build(holdings, now, by_month)
