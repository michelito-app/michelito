"""Estimated payments of a loan (`analysis.loan_estimates`), made-up values: the installments
due with no linked payment nor statement line, and the extra principal that squares the paid
total with the latest real balance."""

from datetime import date, timedelta
from decimal import Decimal

from michelito.analysis.loan_estimates import estimates
from michelito.analysis.loan_review import Payment
from michelito.analysis.loan_schedule import (
    Anchor,
    Contract,
    Installment,
    Rate,
    StatementLine,
    schedule,
)

CONTRACT = Contract(principal=Decimal("100000.00"), term=12, start=date(2026, 1, 15))
RATES = (Rate(date(2026, 1, 15), Decimal("12")),)
TODAY = date(2026, 6, 20)  # five installments due: February to June
ROWS = schedule(CONTRACT, RATES)


def paid(*days: date, amount: str = "8884.88") -> list[Payment]:
    return [Payment(f"p{i}", day, Decimal(amount)) for i, day in enumerate(days)]


def test_every_installment_due_without_a_payment_is_estimated() -> None:
    found = estimates(CONTRACT, ROWS, (), (), (), TODAY)

    assert [(e.kind, e.day, e.amount) for e in found] == [
        ("installment", date(2026, month, 15), Decimal("8884.88")) for month in range(2, 7)
    ]


def test_a_linked_payment_near_the_due_date_covers_its_installment() -> None:
    payments = paid(date(2026, 2, 15), date(2026, 3, 20), date(2026, 5, 2))

    found = estimates(CONTRACT, ROWS, (), (), payments, TODAY)

    # March is paid 5 days late, May 13 days early; April and June have none.
    assert [e.day for e in found] == [date(2026, 4, 15), date(2026, 6, 15)]


def test_one_payment_covers_one_installment_only() -> None:
    payments = paid(date(2026, 3, 14), date(2026, 3, 16))  # two payments around March 15

    found = estimates(CONTRACT, ROWS, (), (), payments, TODAY)

    assert date(2026, 3, 15) not in [e.day for e in found]
    assert date(2026, 2, 15) in [e.day for e in found]  # 27 days earlier: too far
    assert len(found) == 4


def test_a_statement_line_covers_its_month() -> None:
    line = StatementLine(date(2026, 4, 15), Decimal("7000"), Decimal("900"), Decimal("80000"))
    rows = schedule(CONTRACT, RATES, statements=(line,))

    found = estimates(CONTRACT, rows, (), (line,), (), TODAY)

    assert date(2026, 4, 15) not in [e.day for e in found]


def test_the_banks_installment_is_the_estimate() -> None:
    fixed = (Installment(date(2026, 1, 15), Decimal("9500.00")),)
    rows = schedule(CONTRACT, RATES, installments=fixed)

    found = estimates(CONTRACT, rows, (), (), (), TODAY)

    assert {e.amount for e in found} == {Decimal("9500.00")}


def test_the_extra_principal_squares_the_payments_with_the_real_balance() -> None:
    # Five installments paid, and the bank says 40,000 are owed: some 20,000 more were paid.
    anchor = Anchor(date(2026, 6, 20), Decimal("40000.00"))
    rows = schedule(CONTRACT, RATES, (anchor,))
    payments = paid(*(date(2026, month, 15) for month in range(2, 7)))

    found = estimates(CONTRACT, rows, (anchor,), (), payments, TODAY)

    (extra,) = found
    assert extra.kind == "extra"
    assert extra.day == anchor.day
    interest = sum((r.interest for r in rows if r.due <= anchor.day), Decimal(0))
    assert extra.amount == Decimal("60000.00") + interest - 5 * Decimal("8884.88")


def test_the_extra_counts_the_estimated_installments_too() -> None:
    anchor = Anchor(date(2026, 6, 20), Decimal("40000.00"))
    rows = schedule(CONTRACT, RATES, (anchor,))
    payments = paid(date(2026, 2, 15))  # four installments missing

    found = estimates(CONTRACT, rows, (anchor,), (), payments, TODAY)

    assert [e.kind for e in found] == ["installment"] * 4 + ["extra"]
    interest = sum((r.interest for r in rows if r.due <= anchor.day), Decimal(0))
    assert found[-1].amount == Decimal("60000.00") + interest - 5 * Decimal("8884.88")


def test_a_small_gap_with_the_real_balance_is_not_an_extra_payment() -> None:
    rows_without = schedule(CONTRACT, RATES)
    june = next(r for r in rows_without if r.due == date(2026, 6, 15))
    # The bank's own interest is a little lower than the estimate: a few hundred less owed.
    anchor = Anchor(date(2026, 6, 20), june.balance - Decimal("300"))
    rows = schedule(CONTRACT, RATES, (anchor,))
    payments = paid(*(date(2026, month, 15) for month in range(2, 7)))

    assert estimates(CONTRACT, rows, (anchor,), (), payments, TODAY) == ()


def test_paying_more_than_the_real_balance_needs_is_no_extra() -> None:
    anchor = Anchor(date(2026, 6, 20), Decimal("90000.00"))
    rows = schedule(CONTRACT, RATES, (anchor,))
    payments = paid(*(date(2026, month, 15) for month in range(2, 7)))

    assert estimates(CONTRACT, rows, (anchor,), (), payments, TODAY) == ()


def test_nothing_is_estimated_before_its_due_date() -> None:
    found = estimates(CONTRACT, ROWS, (), (), (), date(2026, 2, 14))

    assert found == ()
    assert estimates(CONTRACT, ROWS, (), (), (), date(2026, 2, 15) + timedelta(days=0))


def test_a_month_without_payment_is_not_estimated_when_the_real_balance_says_it_is_owed() -> None:
    # May was skipped and the bank still has it in the balance: nothing is missing.
    payments = paid(*(date(2026, month, 15) for month in (2, 3, 4, 6)))
    rows_without = schedule(CONTRACT, RATES)
    may = next(r for r in rows_without if r.due == date(2026, 5, 15))
    anchor = Anchor(date(2026, 6, 20), may.balance)  # four installments' principal paid off
    rows = schedule(CONTRACT, RATES, (anchor,))

    assert estimates(CONTRACT, rows, (anchor,), (), payments, TODAY) == ()


def test_the_real_balance_only_fills_as_many_months_as_it_explains() -> None:
    # Nothing linked, and the balance says two installments were paid: the oldest two.
    rows_without = schedule(CONTRACT, RATES)
    march = next(r for r in rows_without if r.due == date(2026, 3, 15))
    anchor = Anchor(date(2026, 6, 20), march.balance)
    rows = schedule(CONTRACT, RATES, (anchor,))

    found = estimates(CONTRACT, rows, (anchor,), (), (), TODAY)

    assert [(e.kind, e.day) for e in found] == [
        ("installment", date(2026, 2, 15)),
        ("installment", date(2026, 3, 15)),
    ]


def test_installments_due_after_the_real_balance_are_estimated_as_usual() -> None:
    anchor = Anchor(date(2026, 4, 20), Decimal("75000.00"))
    rows = schedule(CONTRACT, RATES, (anchor,))
    payments = paid(*(date(2026, month, 15) for month in (2, 3, 4)))

    found = estimates(CONTRACT, rows, (anchor,), (), payments, TODAY)

    assert [e.day for e in found if e.kind == "installment"] == [
        date(2026, 5, 15),
        date(2026, 6, 15),
    ]
