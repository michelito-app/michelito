"""A loan's amortization schedule (pure logic): fixed monthly installments from the contract,
corrected by the real balances the user enters and replaced by the loan statements where they
exist.

- Installment n is due n months after the start date (on the same day, or the month's last day).
  Its interest is the balance before it times the annual rate / 12, at the rate in force when
  its period starts (the previous due date).
- **A new rate** recomputes the installment over the months left, keeping the expected end.
- **A real balance** (`Anchor`, from the user or a statement) replaces the balance from that day
  on; the installment stays and the end moves (an extra payment shortens the loan). If the
  installment no longer covers the interest, it is recomputed over the months left instead.
  A real balance of zero ends the loan.
- **The last installment** pays whatever is left, so the cents the rounding leaves never make
  an extra month.
- **Statement lines** are the truth for the installment of their month (principal, interest,
  other charges and the balance after them); the contract only projects the months without one.

Amounts are `Decimal`, rounded to cents at each installment.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Literal

CENT = Decimal("0.01")
MONTHS_PER_YEAR = 12
PERCENT = Decimal(100)
MAX_INSTALLMENTS = 600  # a safety cap: no loan here runs for more than 50 years
# The last installment takes whatever the rounding of the others left (less than this).
LAST_ROUNDING = Decimal(1)

Source = Literal["contract", "statement"]


@dataclass(frozen=True)
class Contract:
    principal: Decimal
    term: int  # number of monthly installments
    start: date  # the disbursement: installment 1 is due a month later


@dataclass(frozen=True)
class Rate:
    effective: date
    annual: Decimal  # percent per year, e.g. 12.5


@dataclass(frozen=True)
class Anchor:
    """The real balance on a day (from the bank)."""

    day: date
    balance: Decimal


@dataclass(frozen=True)
class StatementLine:
    """One payment as the loan statement prints it."""

    day: date
    principal: Decimal
    interest: Decimal
    balance: Decimal  # after the payment
    other: Decimal = Decimal(0)  # insurance, fees, late charges


@dataclass(frozen=True)
class Row:
    number: int
    due: date
    payment: Decimal
    interest: Decimal
    principal: Decimal
    balance: Decimal  # after the installment
    rate: Decimal
    source: Source
    other: Decimal = Decimal(0)

    @property
    def month(self) -> str:
        return self.due.strftime("%Y-%m")


@dataclass(frozen=True)
class Summary:
    rows: tuple[Row, ...]
    balance: Decimal
    interest_from_statements: Decimal  # in installments already due
    interest_estimated: Decimal
    installments_left: int
    next_payment: Row | None
    end: date | None


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(day: date, months: int) -> date:
    index = day.year * MONTHS_PER_YEAR + day.month - 1 + months
    year, month = divmod(index, MONTHS_PER_YEAR)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last))


def _monthly(annual: Decimal) -> Decimal:
    return annual / PERCENT / MONTHS_PER_YEAR


def installment_for(balance: Decimal, annual: Decimal, months: int) -> Decimal:
    """The fixed installment that pays `balance` off in `months` at `annual` percent."""
    months = max(months, 1)
    r = _monthly(annual)
    if r == 0:
        return _cents(balance / months)
    return _cents(balance * r / (1 - (1 + r) ** -months))


def _months_to_pay(balance: Decimal, annual: Decimal, installment: Decimal) -> int | None:
    """How many installments pay `balance` off; None if the installment never does."""
    r = _monthly(annual)
    if r == 0:
        if installment <= 0:
            return None
        return int((balance / installment).to_integral_value(rounding=ROUND_CEILING))
    if installment <= balance * r:
        return None
    left = balance
    for count in range(1, MAX_INSTALLMENTS + 1):
        left = left + _cents(left * r) - installment
        if left < LAST_ROUNDING:  # what is left goes into this installment
            return count
    return None


def rate_on(rates: Sequence[Rate], day: date) -> Decimal:
    """The rate in force on `day` (the earliest one before the first change)."""
    ordered = sorted(rates, key=lambda r: r.effective)
    if not ordered:
        return Decimal(0)
    found = ordered[0].annual
    for rate in ordered:
        if rate.effective <= day:
            found = rate.annual
    return found


def _statement_row(number: int, due: date, lines: Sequence[StatementLine], rate: Decimal) -> Row:
    principal = sum((line.principal for line in lines), Decimal(0))
    interest = sum((line.interest for line in lines), Decimal(0))
    other = sum((line.other for line in lines), Decimal(0))
    last = max(lines, key=lambda line: line.day)
    return Row(
        number,
        due,
        principal + interest + other,
        interest,
        principal,
        last.balance,
        rate,
        "statement",
        other,
    )


def schedule(
    contract: Contract,
    rates: Sequence[Rate],
    anchors: Sequence[Anchor] = (),
    statements: Sequence[StatementLine] = (),
) -> tuple[Row, ...]:
    """Every installment from the first to the one that pays the loan off."""
    by_month: dict[str, list[StatementLine]] = {}
    for line in statements:
        by_month.setdefault(line.day.strftime("%Y-%m"), []).append(line)
    last_statement = max(by_month, default="")
    balance = contract.principal
    rate = rate_on(rates, contract.start)
    installment = installment_for(balance, rate, contract.term)
    end = contract.term  # the number of the installment expected to be the last
    rows: list[Row] = []
    number = 0
    while number < MAX_INSTALLMENTS:
        number += 1
        opens, due = add_months(contract.start, number - 1), add_months(contract.start, number)
        lines = by_month.get(due.strftime("%Y-%m"))
        if lines:
            row = _statement_row(number, due, lines, rate_on(rates, opens))
            rows.append(row)
            balance = row.balance
            if balance <= 0:
                break
            end = _replan(balance, rate, installment, number, end)
            continue
        if balance <= 0 and due.strftime("%Y-%m") >= last_statement:
            break
        new_rate = rate_on(rates, opens)
        if new_rate != rate:
            rate = new_rate
            installment = installment_for(balance, rate, end - number + 1)
        anchor = _anchor_in(anchors, opens, due)
        if anchor is not None:
            balance = anchor.balance
            if balance <= 0:
                break  # paid off by then: no installment is due any more
            end = _replan(balance, rate, installment, number - 1, end)
            if _months_to_pay(balance, rate, installment) is None:
                installment = installment_for(balance, rate, end - number + 1)
        interest = _cents(balance * _monthly(rate))
        principal = min(installment - interest, balance)
        if number >= end:
            principal = balance  # the last one clears what the rounding left
        if principal < 0:
            principal = Decimal(0)
        balance = _cents(balance - principal)
        rows.append(
            Row(number, due, interest + principal, interest, principal, balance, rate, "contract")
        )
        if balance <= 0:
            break
    return tuple(rows)


def _anchor_in(anchors: Sequence[Anchor], opens: date, due: date) -> Anchor | None:
    """The latest real balance from the period's start (included) to its due date."""
    inside = [a for a in anchors if opens <= a.day < due]
    return max(inside, key=lambda a: a.day) if inside else None


def _replan(balance: Decimal, rate: Decimal, installment: Decimal, done: int, end: int) -> int:
    """The new last installment after a real balance: keep the installment, move the end (or
    keep the end if the installment never pays it off)."""
    months = _months_to_pay(balance, rate, installment)
    if months is None:
        return max(end, done + 1)
    return done + int(months)


def balance_at(
    contract: Contract, rows: Sequence[Row], anchors: Sequence[Anchor], day: date
) -> Decimal:
    """The balance on `day`: the latest of the installments due and the real balances (a real
    balance wins on the same day)."""
    found_day, found = contract.start, contract.principal
    for row in rows:
        if row.due <= day and row.due >= found_day:
            found_day, found = row.due, row.balance
    for anchor in sorted(anchors, key=lambda a: a.day):
        if anchor.day <= day and anchor.day >= found_day:
            found_day, found = anchor.day, anchor.balance
    return found


def summary(
    contract: Contract,
    rates: Sequence[Rate],
    anchors: Sequence[Anchor],
    statements: Sequence[StatementLine],
    today: date,
) -> Summary:
    rows = schedule(contract, rates, anchors, statements)
    due = [r for r in rows if r.due <= today]
    ahead = [r for r in rows if r.due > today]
    return Summary(
        rows=rows,
        balance=balance_at(contract, rows, anchors, today),
        interest_from_statements=sum(
            (r.interest for r in due if r.source == "statement"), Decimal(0)
        ),
        interest_estimated=sum((r.interest for r in due if r.source == "contract"), Decimal(0)),
        installments_left=len(ahead),
        next_payment=ahead[0] if ahead else None,
        end=rows[-1].due if rows else None,
    )
