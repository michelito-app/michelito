"""Loans in Recurring (pure logic): which payment of each month is the installment and which are
extra payments.

- **Installment in two parts**: if over the last months the month's sum is stable (within
  `TOLERANCE` of its median) and no single payment comes close to it, the installment is the
  month's sum (one payment per month with the sum, and the last one's day and fingerprint) and
  there are no extra payments.
- **Tiers**: otherwise, each exact amount repeated in two or more months is an installment tier
  running from its first to its last month. A month's installment is the tier covering it (if
  several, the most repeated and, on a tie, the most recent: an extra payment repeated twice
  does not beat the installment); a month outside every tier uses the nearest one. So an
  installment that changes (9 months of 10k and then 12k) is the whole series and the new one
  does not become extra payments. Without repeated amounts, the installment is the median of
  each month's smallest payment.
- The month's payment closest to its installment (within `TOLERANCE`) is the installment; the
  rest, extra payments.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from statistics import median

from michelito.analysis.spending import Movement

TOLERANCE = Decimal("0.10")
RECENT_MONTHS = 3  # the months checked for a stable sum


@dataclass(frozen=True)
class LoanParts:
    regular: list[Movement]  # each month's installment (one per month), by date
    extras: list[Movement]  # the extra payments, by date
    installment: Decimal  # the last month's installment


def _month(day: date) -> int:
    return day.year * 12 + day.month - 1


def _by_day(m: Movement) -> tuple[date, str]:
    return (m.day, m.fingerprint)


def _by_month(items: Iterable[Movement]) -> dict[int, list[Movement]]:
    found: dict[int, list[Movement]] = defaultdict(list)
    for m in items:
        found[_month(m.day)].append(m)
    return {index: sorted(paid, key=_by_day) for index, paid in found.items()}


def _gap(amount: Decimal, reference: Decimal) -> Decimal:
    return abs(amount - reference) / reference


def _split_in_parts(months: dict[int, list[Movement]]) -> list[Movement] | None:
    """Each month's sum as the installment, if the last months pay a stable sum in parts with
    no single payment close to it; None otherwise."""
    recent = sorted(months)[-RECENT_MONTHS:]
    if len(recent) < RECENT_MONTHS:
        return None
    sums = [sum((m.amount for m in months[i]), Decimal(0)) for i in recent]
    center = median(sums)
    if center <= 0 or any(_gap(s, center) > TOLERANCE for s in sums):
        return None
    if any(_gap(m.amount, center) <= TOLERANCE for i in recent for m in months[i]):
        return None
    return [
        replace(months[i][-1], amount=sum((m.amount for m in months[i]), Decimal(0)))
        for i in sorted(months)
    ]


def _tiers(months: dict[int, list[Movement]]) -> dict[int, Decimal]:
    """Each month's installment (see the module docstring)."""
    seen: dict[Decimal, set[int]] = defaultdict(set)
    for index, paid in months.items():
        for m in paid:
            seen[m.amount].add(index)
    repeated = {amount: sorted(found) for amount, found in seen.items() if len(found) >= 2}
    if not repeated:
        single = median(min(m.amount for m in paid) for paid in months.values())
        return dict.fromkeys(months, single)

    def rank(amount: Decimal) -> tuple[int, int]:
        return (len(repeated[amount]), repeated[amount][-1])

    found = {}
    for index in months:
        covering = [a for a, ms in repeated.items() if ms[0] <= index <= ms[-1]]
        if covering:
            found[index] = max(covering, key=rank)
            continue

        def distance(amount: Decimal, index: int = index) -> int:
            ms = repeated[amount]
            return min(abs(index - ms[0]), abs(index - ms[-1]))

        found[index] = min(repeated, key=lambda a: (distance(a), -rank(a)[0], -rank(a)[1]))
    return found


def split(items: Sequence[Movement]) -> LoanParts:
    """Each month's installment and the extra payments among a loan's (positive) payments."""
    months = _by_month(items)
    in_parts = _split_in_parts(months)
    if in_parts is not None:
        return LoanParts(in_parts, [], in_parts[-1].amount)
    tiers = _tiers(months)
    regular: list[Movement] = []
    extras: list[Movement] = []
    for index in sorted(months):
        installment = tiers[index]
        paid = sorted(months[index], key=lambda m: (abs(m.amount - installment), *_by_day(m)))
        if installment > 0 and _gap(paid[0].amount, installment) <= TOLERANCE:
            regular.append(paid[0])
            extras.extend(paid[1:])
        else:
            extras.extend(paid)
    return LoanParts(sorted(regular, key=_by_day), sorted(extras, key=_by_day), tiers[max(months)])


def installment_amount(items: Sequence[Movement]) -> Decimal:
    """The installment of the last month with payments."""
    return split(items).installment
