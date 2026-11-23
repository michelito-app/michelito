"""Net worth's holdings, built from what Michelito stores (see `analysis.net_worth`).

- **Accounts**: each statement account and currency; its value is the closing balance of the
  latest statement on or before the day (portal printouts have no closing balance and do not
  count). Cards are debts, bank accounts assets. Unknown before the first statement.
- **Loans**: the balance of the schedule and real balances (`loan_schedule.balance_at`); zero
  before the loan starts.
- **Cash** («Efectivo»): its balance per currency on the day (`cash_box.balance_on`).
- **Investments** not written off: the capital still invested on the day.
- **Shared**: what others owe the user (asset) and what the user owes (debt), known today only.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from michelito.analysis import accounts as account_data
from michelito.analysis import cash_box, investments, links, loan_schedule, loan_store
from michelito.analysis.investments import InvestmentState
from michelito.analysis.loan_store import Loan
from michelito.analysis.net_worth import Holding, Side, ValueOn
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from michelito.db import PRINTOUT_PARSERS

_ZERO = Decimal(0)
CARDS, LOANS, BANKS, CASH, INVESTMENTS, OWED, OWING = (
    "cards",
    "loans",
    "banks",
    "cash",
    "investments",
    "owed",
    "owing",
)
_BALANCES = f"""
SELECT a.key AS account_key, a.kind AS kind, s.currency, s.period_end, s.closing_balance_cents
FROM statements s JOIN accounts a ON a.id = s.account_id
WHERE s.closing_balance_cents IS NOT NULL
  AND s.parser NOT IN ({", ".join("?" for _ in PRINTOUT_PARSERS)})
ORDER BY s.period_end, s.id
"""


def _steps(points: Sequence[tuple[date, Decimal]]) -> ValueOn:
    """The value of the latest point on or before the day (`points` by day); None before."""
    days = [when for when, _value in points]

    def value_on(day: date) -> Decimal | None:
        at = bisect_right(days, day)
        return points[at - 1][1] if at else None

    return value_on


def _cached(value_on: ValueOn) -> ValueOn:
    """The same values, each day computed once per request."""
    seen: dict[date, Decimal | None] = {}

    def cached(day: date) -> Decimal | None:
        if day not in seen:
            seen[day] = value_on(day)
        return seen[day]

    return cached


def account_holdings(conn: sqlite3.Connection) -> list[Holding]:
    labels = {info.key: info.label for info in account_data.account_infos(conn)}
    series: dict[tuple[str, str, str], list[tuple[date, Decimal]]] = defaultdict(list)
    for row in conn.execute(_BALANCES, PRINTOUT_PARSERS):
        if row["kind"] == account_data.CASH_KIND:
            continue
        key = (row["account_key"], row["kind"], row["currency"])
        series[key].append(
            (date.fromisoformat(row["period_end"]), Decimal(row["closing_balance_cents"]) / 100)
        )
    return [
        Holding(
            key=key,
            group=CARDS if kind == "credit_card" else BANKS,
            currency=currency,
            side="debt" if kind == "credit_card" else "asset",
            value_on=_steps(points),
            label=labels.get(key, key),
            known_from=points[0][0],
        )
        for (key, kind, currency), points in series.items()
    ]


def _loan_value(loan: Loan) -> ValueOn:
    rows = loan_schedule.schedule(
        loan.contract, loan.rates, loan.anchors, loan.statement_lines, loan.installments
    )

    def value_on(day: date) -> Decimal:
        if day < loan.contract.start:
            return _ZERO
        return loan_schedule.balance_at(loan.contract, rows, loan.anchors, day)

    return value_on


def loan_holdings(conn: sqlite3.Connection) -> list[Holding]:
    return [
        Holding(
            f"loan-{loan.id}",
            LOANS,
            loan.currency,
            "debt",
            _cached(_loan_value(loan)),
            label=loan.name,
        )
        for loan in loan_store.load(conn)
    ]


def cash_holdings(state: cash_box.BoxState) -> list[Holding]:
    def value(currency: str) -> ValueOn:
        return lambda day: cash_box.balance_on(state, currency, day)

    return [
        Holding(
            account_data.CASH_BOX_KEY,
            CASH,
            currency,
            "asset",
            _cached(value(currency)),
            label=account_data.CASH_BOX_NAME,
        )
        for currency in sorted({currency for currency, _amount in state.balances})
    ]


def _invested_on(state: InvestmentState) -> ValueOn:
    def value_on(day: date) -> Decimal:
        entries = tuple(e for e in state.entries if e.day <= day)
        return dataclasses.replace(state, entries=entries).pending

    return value_on


def investment_holdings(
    flow: Sequence[Movement], found: links.Links, rates: Mapping[str, Rate]
) -> list[Holding]:
    states = investments.states(tuple(flow), found, rates)
    return [
        Holding(
            f"investment-{state.id}",
            INVESTMENTS,
            state.currency,
            "asset",
            _cached(_invested_on(state)),
            label=state.title,
        )
        for state in states.values()
        if not state.link.written_off
    ]


def shared_holdings(totals: Sequence[tuple[str, Decimal, Decimal]]) -> list[Holding]:
    """`totals`: (currency, owed to the user, the user owes), known today only."""
    found = []
    for currency, owed, owing in totals:
        if owed:
            found.append(_constant(OWED, currency, "asset", owed))
        if owing:
            found.append(_constant(OWING, currency, "debt", owing))
    return found


def _constant(group: str, currency: str, side: Side, amount: Decimal) -> Holding:
    return Holding(group, group, currency, side, lambda _day: amount, historic=False)
