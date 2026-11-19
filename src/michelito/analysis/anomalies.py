"""Unusual months and what explains them ("What happened"). Pure functions, all in RD$.

Rule (deterministic): a month is unusual in spending or income when it departs from the usual
by more than max(ANOMALY_SHARE of the usual, ANOMALY_FLOOR). The usual is the median of the
same BASELINE previous complete months the Summary uses (`web.summary`); with fewer than
MIN_BASELINE months nothing is flagged. Months in progress (partial) are not flagged, nor is
income when a bank account's statement closes before the end of the month. Spending is compared
with the median without one-off expenses, like the Summary's "Expenses" indicator.

"What happened" groups by merchant: the month's amount minus the merchant's median over the
reference months (zero where it didn't appear). In a high month the ones that rose the most
show up; in a low one, the ones that dropped the most (or didn't appear). Each links its
largest transaction of the month, if any.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from michelito.analysis.spending import Movement

ANOMALY_SHARE = Decimal("0.30")
ANOMALY_FLOOR = Decimal(10_000)
MIN_BASELINE = 3
TOP_CONTRIBUTIONS = 3

Direction = Literal["up", "down"]
Side = Literal["expense", "income"]

_ZERO = Decimal(0)


@dataclass(frozen=True)
class Entry:
    """A transaction with its RD$ amount on the measured side (positive = more of that side)."""

    move: Movement
    dop: Decimal


@dataclass(frozen=True)
class Contribution:
    side: Side
    merchant: str
    category: str
    amount: Decimal  # the merchant's amount in the month
    habitual: Decimal  # the merchant's median over the reference months
    diff: Decimal  # amount − habitual
    count: int  # the merchant's transactions in the month
    fingerprint: str  # its largest transaction of the month; "" if it didn't appear
    day: date | None
    description: str


def deviation(
    value: Decimal,
    habitual: Decimal,
    *,
    share: Decimal = ANOMALY_SHARE,
    floor: Decimal = ANOMALY_FLOOR,
) -> Direction | None:
    """ "up" or "down" when `value` departs from `habitual` by more than max(share, floor)."""
    diff = value - habitual
    if abs(diff) <= max(floor, abs(habitual) * share):
        return None
    return "up" if diff > 0 else "down"


def habitual(values: Sequence[Decimal]) -> Decimal | None:
    """Median of the reference months; None with fewer than MIN_BASELINE."""
    if len(values) < MIN_BASELINE:
        return None
    return statistics.median(values)


def contributions(
    current: Sequence[Entry],
    baseline: Mapping[str, Sequence[Entry]],
    direction: Direction,
    side: Side,
    limit: int = TOP_CONTRIBUTIONS,
) -> list[Contribution]:
    """The merchants that best explain the month's deviation, in the given direction.

    `baseline`: entries of each reference month (without one-off expenses, like the usual).
    """
    now = _by_merchant(current)
    before = {month: _totals(entries) for month, entries in baseline.items()}
    merchants = set(now) | {m for totals in before.values() for m in totals}
    found = []
    for merchant in merchants:
        items = now.get(merchant, [])
        amount = sum((e.dop for e in items), _ZERO)
        usual = (
            statistics.median(totals.get(merchant, _ZERO) for totals in before.values())
            if before
            else _ZERO
        )
        diff = amount - usual
        if (diff > 0) if direction == "up" else (diff < 0):
            found.append(_contribution(side, merchant, items, amount, usual, diff, baseline))
    found.sort(key=lambda c: (-abs(c.diff), c.merchant))
    return found[:limit]


def _by_merchant(entries: Sequence[Entry]) -> dict[str, list[Entry]]:
    groups: defaultdict[str, list[Entry]] = defaultdict(list)
    for item in entries:
        groups[item.move.merchant].append(item)
    return groups


def _totals(entries: Sequence[Entry]) -> dict[str, Decimal]:
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    for item in entries:
        totals[item.move.merchant] += item.dop
    return totals


def _contribution(
    side: Side,
    merchant: str,
    items: Sequence[Entry],
    amount: Decimal,
    usual: Decimal,
    diff: Decimal,
    baseline: Mapping[str, Sequence[Entry]],
) -> Contribution:
    biggest = max(items, key=lambda e: (e.dop, e.move.day), default=None)
    sample = biggest or _last_seen(merchant, baseline)
    return Contribution(
        side=side,
        merchant=merchant,
        category=sample.move.category if sample else "",
        amount=amount,
        habitual=usual,
        diff=diff,
        count=len(items),
        fingerprint=biggest.move.fingerprint if biggest else "",
        day=biggest.move.day if biggest else None,
        description=biggest.move.description if biggest else "",
    )


def _last_seen(merchant: str, baseline: Mapping[str, Sequence[Entry]]) -> Entry | None:
    seen = [e for entries in baseline.values() for e in entries if e.move.merchant == merchant]
    return max(seen, key=lambda e: e.move.day, default=None)
