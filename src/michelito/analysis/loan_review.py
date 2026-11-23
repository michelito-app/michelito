"""What a loan sends to review (pure logic): where its statements disagree.

Only months with a loan statement are judged (without one, the contract is all there is):

- **payments**: the payments linked in the statement's month do not add up to what the
  statement says was paid (principal + interest + other charges);
- **contract**: the statement's balance is far from what the contract (and the real balances
  the user entered) expected for that installment, e.g. a rate change nobody entered.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from michelito.analysis.loan_schedule import Anchor, Contract, Rate, StatementLine, schedule

Kind = Literal["payments", "contract"]
PAYMENT_TOLERANCE = Decimal("1.00")
BALANCE_TOLERANCE = Decimal("0.005")  # of the expected balance (and at least a peso)


@dataclass(frozen=True)
class Payment:
    fingerprint: str
    day: date
    amount: Decimal


@dataclass(frozen=True)
class Difference:
    kind: Kind
    month: str
    expected: Decimal  # payments: the statement's; contract: the contract's balance
    found: Decimal  # payments: the linked ones; contract: the statement's balance
    fingerprints: tuple[str, ...]  # the month's linked payments


def _month(day: date) -> str:
    return day.strftime("%Y-%m")


def differences(
    contract: Contract,
    rates: Sequence[Rate],
    anchors: Sequence[Anchor],
    statements: Sequence[StatementLine],
    payments: Sequence[Payment],
) -> list[Difference]:
    if not statements:
        return []
    expected = {row.month: row for row in schedule(contract, rates, anchors)}
    actual = {row.month: row for row in schedule(contract, rates, anchors, statements)}
    months = sorted({_month(line.day) for line in statements})
    found = []
    for month in months:
        paid = sorted((p for p in payments if _month(p.day) == month), key=lambda p: p.day)
        fingerprints = tuple(p.fingerprint for p in paid)
        row = actual.get(month)
        if row is None:
            continue
        total = sum((p.amount for p in paid), Decimal(0))
        if abs(total - row.payment) > PAYMENT_TOLERANCE:
            found.append(Difference("payments", month, row.payment, total, fingerprints))
        plan = expected.get(month)
        if plan is not None:
            limit = max(PAYMENT_TOLERANCE, plan.balance * BALANCE_TOLERANCE)
            if abs(plan.balance - row.balance) > limit:
                found.append(Difference("contract", month, plan.balance, row.balance, fingerprints))
    return found
