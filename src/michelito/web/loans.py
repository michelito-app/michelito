"""Loans for the board: each loan's card and the "loan · name" of a transaction row.

A loan's card: its linked payments and what they add up to, the balance today, the interest
paid (from the loan statements where they exist, estimated from the contract otherwise), the
installments left and the expected end, the bank's installment, the rate history and the
differences for review (`loan_review`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from michelito.analysis import loan_review, loan_schedule, loan_store
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.loan_review import Difference, Payment
from michelito.analysis.loan_schedule import Summary
from michelito.analysis.loan_store import Loan
from michelito.analysis.spending import Movement


@dataclass(frozen=True)
class Tag:
    """What a transaction row shows: "loan · Car"."""

    loan_id: int
    name: str


@dataclass(frozen=True)
class PaymentView:
    fingerprint: str
    day: date
    description: str
    account_label: str
    amount: Decimal
    origin: str


@dataclass(frozen=True)
class LoanView:
    loan: Loan
    summary: Summary
    payments: tuple[PaymentView, ...]  # newest first
    differences: tuple[Difference, ...]
    rate: Decimal  # in force today
    installment: Decimal | None  # the bank's, in force today

    @property
    def paid(self) -> Decimal:
        return sum((p.amount for p in self.payments), Decimal(0))


def tags(conn: sqlite3.Connection) -> dict[str, Tag]:
    return {
        fingerprint: Tag(loan.id, loan.name)
        for loan in loan_store.load(conn)
        for fingerprint in loan.links
    }


def view(
    loan: Loan, flow: Sequence[Movement], accounts: Sequence[AccountInfo], today: date
) -> LoanView:
    labels = {info.key: info.label for info in accounts}
    by_fp = {m.fingerprint: m for m in flow}
    linked = [by_fp[fp] for fp in loan.links if fp in by_fp]
    payments = tuple(
        PaymentView(
            m.fingerprint,
            m.day,
            m.description,
            labels.get(m.account, m.account),
            loan_store.payment_amount(m),
            loan.links[m.fingerprint],
        )
        for m in sorted(linked, key=lambda m: (m.day, m.fingerprint), reverse=True)
    )
    found = loan_review.differences(
        loan.contract,
        loan.rates,
        loan.anchors,
        loan.statement_lines,
        [Payment(p.fingerprint, p.day, p.amount) for p in payments],
        loan.installments,
    )
    return LoanView(
        loan=loan,
        summary=loan_schedule.summary(
            loan.contract,
            loan.rates,
            loan.anchors,
            loan.statement_lines,
            today,
            loan.installments,
        ),
        payments=payments,
        differences=tuple(found),
        rate=loan_schedule.rate_on(loan.rates, today),
        installment=loan_schedule.installment_on(loan.installments, today),
    )


def views(
    conn: sqlite3.Connection,
    flow: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    today: date,
) -> list[LoanView]:
    return [view(loan, flow, accounts, today) for loan in loan_store.load(conn)]
