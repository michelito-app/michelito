"""A loan's estimated payments (pure logic): what was surely paid but is not in Michelito.

Derived every time, never stored, so they go away on their own as the real data arrives:

- **installment**: an installment already due with no linked payment near its due date (within
  `MATCH_DAYS`, each payment covering one installment) and no loan statement line in its month.
  Its amount is that installment of the schedule (the bank's installment if there is one,
  otherwise the contract's).
- Up to the latest real balance, the balance decides: what it says was paid by then (principal
  paid off plus the interest and charges due) minus the linked payments is the gap. It explains
  the missing installments oldest first (a month the bank still has in the balance was not
  paid, so it is not estimated), and what is left of it is
- **extra**: principal paid that nothing records, on the real balance's day. Only from half an
  installment up: a smaller gap is the interest estimate's own error, not a payment.

They count only inside the loan (paid, progress); never as spending, in accounts or transactions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from michelito.analysis.loan_review import Payment
from michelito.analysis.loan_schedule import Anchor, Contract, Row, StatementLine

Kind = Literal["installment", "extra"]
MATCH_DAYS = 15  # a payment this close to a due date pays that installment
EXTRA_SHARE = Decimal("0.5")  # of an installment: a smaller gap is no extra payment


@dataclass(frozen=True)
class Estimate:
    kind: Kind
    day: date  # the due date, or the real balance's day
    amount: Decimal


def _month(day: date) -> str:
    return day.strftime("%Y-%m")


def _missing(
    rows: Sequence[Row],
    statements: Sequence[StatementLine],
    payments: Sequence[Payment],
    today: date,
) -> list[Estimate]:
    with_lines = {_month(line.day) for line in statements}
    free = sorted(payments, key=lambda p: (p.day, p.fingerprint))
    found = []
    for row in rows:
        if row.due > today:
            break
        if row.source == "statement" or row.month in with_lines:
            continue
        near = [p for p in free if abs((p.day - row.due).days) <= MATCH_DAYS]
        if near:
            free.remove(min(near, key=lambda p: abs((p.day - row.due).days)))
            continue
        found.append(Estimate("installment", row.due, row.payment))
    return found


def _gap(
    contract: Contract, rows: Sequence[Row], anchor: Anchor, payments: Sequence[Payment]
) -> tuple[Decimal, Decimal] | None:
    """What the real balance says was paid by its day minus the linked payments, and the
    installment then (None: no installment due by that day)."""
    due = [r for r in rows if r.due <= anchor.day]
    if not due:
        return None
    charged = sum((r.interest + r.other for r in due), Decimal(0))
    needed = contract.principal - anchor.balance + charged
    linked = sum((p.amount for p in payments if p.day <= anchor.day), Decimal(0))
    return needed - linked, due[-1].payment


def _explained(
    missing: Sequence[Estimate], gap: Decimal, installment: Decimal, anchor: Anchor
) -> list[Estimate]:
    """The installments the gap explains (oldest first, each at least half covered), then what
    is left of it as extra principal (from half an installment up)."""
    kept = []
    left = gap
    for estimate in missing:
        if left < estimate.amount * EXTRA_SHARE:
            break
        kept.append(estimate)
        left -= estimate.amount
    if left >= installment * EXTRA_SHARE:
        kept.append(Estimate("extra", anchor.day, left))
    return kept


def estimates(
    contract: Contract,
    rows: Sequence[Row],
    anchors: Sequence[Anchor],
    statements: Sequence[StatementLine],
    payments: Sequence[Payment],
    today: date,
) -> tuple[Estimate, ...]:
    """The estimated payments by day (the extra principal last on its day). Up to the latest
    real balance, only as many installments as it explains: a month the bank still has in the
    balance was not paid."""
    missing = _missing(rows, statements, payments, today)
    known = [a for a in anchors if a.day <= today]
    if not known:
        return tuple(missing)
    anchor = max(known, key=lambda a: a.day)
    found = _gap(contract, rows, anchor, payments)
    if found is None:
        return tuple(missing)
    gap, installment = found
    before = [e for e in missing if e.day <= anchor.day]
    after = [e for e in missing if e.day > anchor.day]
    return (*_explained(before, gap, installment, anchor), *after)
