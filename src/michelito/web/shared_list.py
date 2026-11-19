"""Shared: every shared group on one screen, across all months.

- **One row per group** with expenses present (`shared.states`), with its status: "pending" if
  some expense has something pending; "written_off" if it was marked "They won't pay me back"
  and something went back to your expenses; otherwise "settled" (also a written-off one that was
  already settled).
- **Paid**: sum of the expense amounts (before splitting), by currency. **Paid back**: sum of
  the reimbursements (linked and manual), by the currency of each: the money that came in,
  including what was left over (the group's excess is shown separately).
- **Order**: latest activity (the most recent expense or reimbursement) first; on a tie, the
  newest group (higher id).
- **Accounts**: with chosen accounts, a group counts if any of its expenses is from them (as in
  Pending).
- **Totals**: "Owed to you" is the same computation as Pending for the groups
  (`pending.build_pending`: what is pending in US$ at the most recent rate; with none, shown
  apart); "Paid back this year", the reimbursements dated in the year of `today`, each in RD$ at
  its month's rate (or the closest earlier month's) and, with no rate, apart; and how many groups
  have something pending.
- **New group** (`new_candidates`): unlinked expenses from the last NEW_WINDOW_DAYS days
  (relative to `today`), without the categories that are never shared (`NOT_SHARED_EXPENSE`),
  from the chosen accounts. *Suggested* ones first (`is_suggested`: category in
  SHAREABLE_CATEGORIES, by its reference, and an amount of at least SUGGEST_MIN_DOP in RD$, US$
  converted at its month's rate or the closest earlier one; with none, not suggested); then the
  rest. Within each block, the most recent first.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from michelito.analysis import categories, shared
from michelito.analysis.links import Links
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.shared import ExpenseState, Refund, SharedState
from michelito.analysis.spending import Movement
from michelito.web import pending as pending_view

NEW_WINDOW_DAYS = shared.PICK_WINDOW_DAYS  # "New group…": expenses from the last 120 days
# "New group…" suggests (on top) the expenses of these categories that make sense to share…
SHAREABLE_CATEGORIES = frozenset(
    {
        categories.RESTAURANTS,
        categories.DELIVERY,
        categories.GROCERIES,
        categories.ENTERTAINMENT,
        categories.TRAVEL,
        categories.SHOPPING,
        categories.ONLINE,
        categories.HOME,
        categories.OTHER,
    }
)
SUGGEST_MIN_DOP = Decimal(2000)  # …of at least this amount in RD$
_ZERO = Decimal(0)
_USD = "USD"

Status = Literal["pending", "settled", "written_off"]


@dataclass(frozen=True)
class RefundRow:
    """A reimbursement of the group as listed: a linked credit or a manual one."""

    key: str  # the credit's fingerprint or "manual:<id>"
    day: date
    description: str  # the credit's merchant or description; manual: the person (or "")
    account_label: str  # the credit's account; manual: "" (cash) or the "where"
    amount: Decimal  # positive, in `currency`
    currency: str
    manual: bool


@dataclass(frozen=True)
class GroupRow:
    state: SharedState
    status: Status
    last_activity: date
    refunds: tuple[RefundRow, ...]  # in the order they are applied
    paid: tuple[tuple[str, Decimal], ...]  # sum of the expense amounts, by currency
    reimbursed: tuple[tuple[str, Decimal], ...]  # sum of reimbursements, by their currency
    pending: tuple[tuple[str, Decimal], ...]  # owed to you, by currency (only those with something)
    pending_dop: Decimal | None  # ≈ RD$ of what is pending (None: nothing pending or no rate)
    unconverted_usd: Decimal  # pending US$ with no rate at all

    @property
    def expenses(self) -> tuple[ExpenseState, ...]:
        return self.state.expenses

    @property
    def first_day(self) -> date:
        return self.state.first.day

    @property
    def last_day(self) -> date:
        return self.state.last_day


@dataclass(frozen=True)
class SharedList:
    rows: tuple[GroupRow, ...]  # latest activity first
    owed_dop: Decimal  # owed to you, in RD$ (without the US$ with no rate)
    unconverted_owed_usd: Decimal
    reimbursed_year_dop: Decimal  # paid back in the year of `today`, in RD$
    unconverted_reimbursed_usd: Decimal
    rate: Rate | None  # the most recent: the one for what is pending in US$

    @property
    def open_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "pending")


def status_of(state: SharedState) -> Status:
    if state.has_pending:
        return "pending"
    if state.link.written_off and any(e.written_off > 0 for e in state.expenses):
        return "written_off"
    return "settled"


def last_activity(state: SharedState) -> date:
    """The group's most recent expense or reimbursement."""
    return max([state.last_day, *(r.day for r in state.refunds)])


def picked(state: SharedState, chosen: Collection[str] | None) -> bool:
    """The group counts with these accounts: one of its expenses is from them (None: all)."""
    return chosen is None or any(e.move.account in chosen for e in state.expenses)


def newest_first(states: Iterable[SharedState]) -> list[SharedState]:
    return sorted(states, key=lambda s: (last_activity(s), s.id), reverse=True)


def _by_currency(values: Iterable[tuple[str, Decimal]]) -> tuple[tuple[str, Decimal], ...]:
    found: dict[str, Decimal] = {}
    for currency, value in values:
        found[currency] = found.get(currency, _ZERO) + value
    return tuple(sorted(found.items()))


def refund_rows(
    state: SharedState, by_fingerprint: Mapping[str, Movement], labels: Mapping[str, str]
) -> tuple[RefundRow, ...]:
    manual = {f"manual:{m.id}": m for m in state.link.manual}
    rows = []
    for refund in state.refunds:
        entry = manual.get(refund.key)
        if entry is not None:
            rows.append(_row(refund, entry.person, entry.place, manual=True))
            continue
        move = by_fingerprint[refund.key]
        label = labels.get(move.account, move.account)
        rows.append(_row(refund, move.merchant or move.description, label, manual=False))
    return tuple(rows)


def _row(refund: Refund, description: str, account: str, *, manual: bool) -> RefundRow:
    return RefundRow(
        refund.key, refund.day, description, account, refund.amount, refund.currency, manual
    )


def reimbursed_in_year(
    refunds: Iterable[Refund], year: int, rates: Mapping[str, Rate]
) -> tuple[Decimal, Decimal]:
    """The reimbursements dated in `year`, in RD$ at their month's rate; and the US$ with no
    rate."""
    dop, unconverted = _ZERO, _ZERO
    for refund in refunds:
        if refund.day.year != year:
            continue
        value = to_dop(
            refund.amount, refund.currency, rate_for(rates, refund.day.strftime("%Y-%m"))
        )
        if value is None:
            unconverted += refund.amount
        else:
            dop += value
    return dop, unconverted


def build_shared_list(
    movements: Sequence[Movement],
    groups: Mapping[int, SharedState],
    labels: Mapping[str, str],
    rates: Mapping[str, Rate],
    today: date,
    chosen: Collection[str] | None = None,
) -> SharedList:
    """The rows and totals of Shared. `chosen`: account keys (None: all)."""
    by_fp = {m.fingerprint: m for m in movements}
    shown = newest_first(s for s in groups.values() if picked(s, chosen))
    owed = pending_view.build_pending(movements, groups, {}, labels, rates, today, chosen)
    items = {i.link_id: i for i in owed.owed_to_me}
    rows = tuple(_group_row(s, by_fp, labels, items.get(s.id)) for s in shown)
    year_dop, year_unconverted = reimbursed_in_year(
        (r for s in shown for r in s.refunds), today.year, rates
    )
    return SharedList(
        rows=rows,
        owed_dop=sum((r.pending_dop for r in rows if r.pending_dop is not None), _ZERO),
        unconverted_owed_usd=owed.unconverted_owed_to_me,
        reimbursed_year_dop=year_dop,
        unconverted_reimbursed_usd=year_unconverted,
        rate=owed.rate,
    )


def _group_row(
    state: SharedState,
    by_fp: Mapping[str, Movement],
    labels: Mapping[str, str],
    item: pending_view.PendingItem | None,
) -> GroupRow:
    pending = tuple(sorted(state.pending.items()))
    return GroupRow(
        state=state,
        status=status_of(state),
        last_activity=last_activity(state),
        refunds=refund_rows(state, by_fp, labels),
        paid=_by_currency((e.currency, e.amount) for e in state.expenses),
        reimbursed=_by_currency((r.currency, r.amount) for r in state.refunds),
        pending=pending,
        pending_dop=None if item is None else item.pending_dop,
        unconverted_usd=_unconverted(item),
    )


def _unconverted(item: pending_view.PendingItem | None) -> Decimal:
    """The row's pending US$ that were not converted to RD$ (as Pending counts them)."""
    if item is None:
        return _ZERO
    if item.pending_dop is None:
        return sum((v for c, v in item.parts if c == _USD), _ZERO)
    return item.unconverted_usd


@dataclass(frozen=True)
class NewCandidate:
    """An option of "New group…": the expense and whether it is suggested (goes on top)."""

    move: Movement
    suggested: bool


def is_suggested(move: Movement, rates: Mapping[str, Rate]) -> bool:
    """An expense that makes sense to share: in SHAREABLE_CATEGORIES (by its reference, so
    renaming the category changes nothing) and of at least SUGGEST_MIN_DOP in RD$. What is not in
    DOP is converted at its month's rate; with no rate (not even an earlier month's), it is not
    suggested."""
    if move.ref not in SHAREABLE_CATEGORIES:
        return False
    value = to_dop(shared.gross(move), move.currency, rate_for(rates, move.month))
    return value is not None and value >= SUGGEST_MIN_DOP


def new_candidates(
    movements: Iterable[Movement],
    links: Links,
    today: date,
    rates: Mapping[str, Rate],
    chosen: Collection[str] | None = None,
) -> list[NewCandidate]:
    """The "New group…" options: unlinked expenses from the last NEW_WINDOW_DAYS days that can be
    shared, from the chosen accounts; suggested ones first and then the rest, the most recent
    first in each block."""
    found = [
        NewCandidate(m, is_suggested(m, rates))
        for m in movements
        if shared.is_shareable(m)
        and not m.link
        and not links.is_linked(m.fingerprint)
        and m.ref not in shared.NOT_SHARED_EXPENSE
        and 0 <= (today - m.day).days <= NEW_WINDOW_DAYS
        and (chosen is None or m.account in chosen)
    ]
    return sorted(found, key=lambda c: (c.suggested, c.move.day, c.move.fingerprint), reverse=True)
