"""Installment plans for the board: each plan's card and the "installment n/N" of a row.

A plan's card: how many are paid, what is left, when it ends, and each installment's state:
"paid" (its charge is linked), "missing" (no charge although the card already has later data,
`installment_match.missing`) or "pending" (still to come). The pending and missing ones are what
the plan still expects (`upcoming`), the remaining installments of the forecast.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from michelito.analysis import installment_match, installment_store
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.installment_store import Plan
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.spending import Movement

State = Literal["paid", "missing", "pending"]


@dataclass(frozen=True)
class Tag:
    """What a transaction row shows: "installment 3/6 · Phone"."""

    plan_id: int
    name: str
    number: int
    count: int


@dataclass(frozen=True)
class Installment:
    number: int
    month: str
    state: State
    fingerprint: str | None


@dataclass(frozen=True)
class PlanView:
    plan: Plan
    account_label: str
    group_name: str | None
    contact_name: str | None
    installments: tuple[Installment, ...]

    @property
    def paid(self) -> int:
        return sum(1 for i in self.installments if i.state == "paid")

    @property
    def remaining_cents(self) -> int:
        return (self.plan.count - self.paid) * self.plan.amount_cents

    @property
    def missing(self) -> tuple[int, ...]:
        return tuple(i.number for i in self.installments if i.state == "missing")


def tags(conn: sqlite3.Connection) -> dict[str, Tag]:
    return {
        fingerprint: Tag(plan.id, plan.name, number, plan.count)
        for plan in installment_store.load(conn)
        for number, fingerprint in plan.links.items()
    }


def _installments(
    plan: Plan, flow_days: Mapping[str, Movement], last_day: date | None
) -> tuple[Installment, ...]:
    linked = {n: flow_days[fp].day for n, fp in plan.links.items() if fp in flow_days}
    absent = set(installment_match.missing(plan.terms, linked, last_day))
    found = []
    for number in range(1, plan.count + 1):
        fingerprint = plan.links.get(number)
        state: State = (
            "paid" if fingerprint is not None else "missing" if number in absent else "pending"
        )
        month = installment_match.month_of_number(plan.first_month, number)
        found.append(Installment(number, month, state, fingerprint))
    return tuple(found)


def views(
    conn: sqlite3.Connection,
    flow: Sequence[Movement],
    accounts: Sequence[AccountInfo],
) -> list[PlanView]:
    """Every plan's card. A card's data reaches its latest statement's cutoff (`through`)."""
    plans = installment_store.load(conn)
    if not plans:
        return []
    by_fp = {m.fingerprint: m for m in flow}
    labels = {info.key: info.label for info in accounts}
    last = {info.key: info.through for info in accounts}
    groups = {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, name FROM ledger_groups")}
    contacts = {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, name FROM contacts")}
    return [
        PlanView(
            plan=plan,
            account_label=labels.get(plan.account, plan.account),
            group_name=None if plan.group_id is None else groups.get(plan.group_id),
            contact_name=None if plan.contact_id is None else contacts.get(plan.contact_id),
            installments=_installments(plan, by_fp, last.get(plan.account)),
        )
        for plan in plans
    ]


def forecast(
    conn: sqlite3.Connection,
    flow: Sequence[Movement],
    by_month: Mapping[str, Rate],
    selected: frozenset[str] | None,
    as_of: date | None,
) -> list[tuple[Decimal, int]]:
    """Each plan of the chosen accounts with installments left: its installment in RD$ (at the
    rate of `as_of`'s month; a US$ plan with no rate is left out) and how many are left."""
    plans = [
        p
        for p in installment_store.load(conn)
        if (selected is None or p.account in selected)
        and len(p.links) < p.count
        and not p.for_member  # a member's installments are not the user's spending
    ]
    if not plans:
        return []
    rate = rate_for(by_month, (as_of or date.today()).strftime("%Y-%m"))
    found = []
    for plan in plans:
        amount = to_dop(installment_store.amount_of(plan.amount_cents), plan.currency, rate)
        if amount is not None:
            found.append((amount, plan.count - len(plan.links)))
    return found
