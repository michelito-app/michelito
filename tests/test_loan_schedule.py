"""The amortization schedule of a loan (`analysis.loan_schedule`), made-up values."""

from datetime import date
from decimal import Decimal

from michelito.analysis.loan_schedule import (
    Anchor,
    Contract,
    Installment,
    Rate,
    StatementLine,
    balance_at,
    installment_for,
    schedule,
    summary,
)

CONTRACT = Contract(principal=Decimal("100000.00"), term=12, start=date(2026, 1, 15))
RATES = (Rate(date(2026, 1, 15), Decimal("12")),)


def test_the_fixed_installment_follows_the_annuity_formula() -> None:
    assert installment_for(Decimal("100000"), Decimal("12"), 12) == Decimal("8884.88")
    assert installment_for(Decimal("1200"), Decimal("0"), 12) == Decimal("100.00")


def test_the_schedule_pays_the_loan_off_in_its_term() -> None:
    rows = schedule(CONTRACT, RATES)

    assert len(rows) == 12
    first = rows[0]
    assert first.due == date(2026, 2, 15)
    assert first.interest == Decimal("1000.00")
    assert first.principal == Decimal("7884.88")
    assert first.balance == Decimal("92115.12")
    assert rows[-1].due == date(2027, 1, 15)
    assert rows[-1].balance == Decimal("0.00")
    assert all(r.source == "contract" for r in rows)


def test_a_due_day_past_the_months_end_falls_on_its_last_day() -> None:
    contract = Contract(Decimal("1200"), 3, date(2026, 1, 31))

    rows = schedule(contract, (Rate(contract.start, Decimal("0")),))

    assert [r.due for r in rows] == [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_a_new_rate_recomputes_the_installment_and_keeps_the_end() -> None:
    rates = (*RATES, Rate(date(2026, 7, 1), Decimal("18")))

    rows = schedule(CONTRACT, rates)

    assert len(rows) == 12
    assert rows[6].payment > rows[5].payment  # from the 7th installment, more interest
    assert rows[6].rate == Decimal("18")
    assert rows[-1].balance == Decimal("0.00")


def test_a_real_balance_keeps_the_installment_and_moves_the_end() -> None:
    # The bank says the balance is lower than expected (an extra payment): it ends earlier.
    anchors = (Anchor(date(2026, 4, 20), Decimal("50000.00")),)

    rows = schedule(CONTRACT, RATES, anchors)

    assert rows[3].payment == Decimal("8884.88")
    assert rows[3].interest == Decimal("500.00")
    assert len(rows) < 12
    assert rows[-1].balance == Decimal("0.00")


def test_statement_lines_win_over_the_contract_for_their_months() -> None:
    lines = (
        StatementLine(
            date(2026, 2, 16), Decimal("7000.00"), Decimal("1100.00"), Decimal("93000.00")
        ),
    )

    rows = schedule(CONTRACT, RATES, statements=lines)

    assert rows[0].source == "statement"
    assert rows[0].principal == Decimal("7000.00")
    assert rows[0].interest == Decimal("1100.00")
    assert rows[0].balance == Decimal("93000.00")
    assert rows[1].source == "contract"
    assert rows[1].interest == Decimal("930.00")  # projected from the statement's balance


def test_several_statement_lines_in_one_period_add_up() -> None:
    lines = (
        StatementLine(date(2026, 2, 10), Decimal("4000"), Decimal("1000"), Decimal("96000")),
        StatementLine(
            date(2026, 2, 14), Decimal("3000"), Decimal("0"), Decimal("93000"), Decimal("50")
        ),
    )

    (first, *_) = schedule(CONTRACT, RATES, statements=lines)

    assert first.principal == Decimal("7000")
    assert first.interest == Decimal("1000")
    assert first.other == Decimal("50")
    assert first.payment == Decimal("8050")
    assert first.balance == Decimal("93000")


def test_the_balance_on_a_day_is_the_last_known_one() -> None:
    rows = schedule(CONTRACT, RATES)
    anchors = (Anchor(date(2026, 3, 20), Decimal("80000.00")),)

    assert balance_at(CONTRACT, rows, (), date(2026, 2, 1)) == Decimal("100000.00")
    assert balance_at(CONTRACT, rows, (), date(2026, 2, 15)) == Decimal("92115.12")
    assert balance_at(CONTRACT, rows, anchors, date(2026, 3, 25)) == Decimal("80000.00")


def test_the_summary_splits_interest_paid_by_its_source() -> None:
    lines = (StatementLine(date(2026, 2, 15), Decimal("7000"), Decimal("1100"), Decimal("93000")),)

    found = summary(CONTRACT, RATES, (), lines, date(2026, 3, 20))

    assert found.interest_from_statements == Decimal("1100")
    assert found.interest_estimated == Decimal("930.00")
    assert found.installments_left == len(found.rows) - 2
    assert len(found.rows) == 13  # a higher balance than the contract's: it ends later
    assert found.next_payment is not None
    assert found.end == found.rows[-1].due
    assert found.balance == found.rows[1].balance


def test_a_loan_that_would_never_end_stops_at_the_cap() -> None:
    # A real balance far above the contract with the same installment: the installment is
    # recomputed over the months left instead of looping forever.
    anchors = (Anchor(date(2026, 2, 20), Decimal("10000000")),)

    rows = schedule(CONTRACT, RATES, anchors)

    assert rows[-1].balance == Decimal("0.00")
    assert len(rows) == 12


def test_the_last_installment_clears_the_rounding_left_over() -> None:
    contract = Contract(Decimal("1000"), 12, date(2026, 1, 15))

    rows = schedule(contract, (Rate(contract.start, Decimal("0")),))

    assert len(rows) == 12
    assert rows[-1].balance == Decimal("0.00")
    assert rows[-1].payment == Decimal("83.37")


def test_many_contracts_end_in_their_term() -> None:
    for principal, term, rate in [("12345.67", 7, "5"), ("99999", 84, "28"), ("5000", 36, "17.5")]:
        contract = Contract(Decimal(principal), term, date(2026, 1, 31))

        rows = schedule(contract, (Rate(contract.start, Decimal(rate)),))

        assert len(rows) == term
        assert rows[-1].balance == Decimal("0.00")


def test_at_zero_rate_a_real_balance_rounds_the_months_up() -> None:
    contract = Contract(Decimal("1000"), 10, date(2025, 1, 1))
    anchors = (Anchor(date(2025, 3, 15), Decimal("550")),)

    rows = schedule(contract, (Rate(contract.start, Decimal("0")),), anchors)

    assert len(rows) == 2 + 6  # from the 3rd, 550 at 100 a month: six more, the last one of 50
    assert rows[-1].payment == Decimal("50.00")


def test_a_real_balance_of_zero_ends_the_loan() -> None:
    anchors = (Anchor(date(2026, 3, 20), Decimal("0")),)

    rows = schedule(CONTRACT, RATES, anchors)
    found = summary(CONTRACT, RATES, anchors, (), date(2026, 3, 25))

    assert len(rows) == 2
    assert found.installments_left == 0
    assert found.balance == Decimal("0")


def test_the_banks_installment_replaces_the_computed_one_and_ends_sooner() -> None:
    fixed = (Installment(date(2026, 1, 15), Decimal("10000.00")),)

    rows = schedule(CONTRACT, RATES, installments=fixed)

    assert len(rows) == 11
    assert all(r.payment == Decimal("10000.00") for r in rows[:-1])
    assert rows[-1].payment < Decimal("10000.00")  # the last one pays what is left
    assert rows[-1].balance == Decimal("0.00")
    assert rows[-1].due == date(2026, 12, 15)


def test_a_lower_bank_installment_moves_the_end_later() -> None:
    fixed = (Installment(date(2026, 1, 15), Decimal("8000.00")),)

    rows = schedule(CONTRACT, RATES, installments=fixed)

    assert len(rows) == 14
    assert rows[-1].balance == Decimal("0.00")
    assert Decimal(0) < rows[-1].payment <= Decimal("8000.00")


def test_a_bank_installment_applies_from_the_first_due_date_on_or_after_it() -> None:
    fixed = (Installment(date(2026, 4, 16), Decimal("10000.00")),)

    rows = schedule(CONTRACT, RATES, installments=fixed)

    assert [r.payment for r in rows[:3]] == [Decimal("8884.88")] * 3
    assert rows[3].due == date(2026, 5, 15)
    assert rows[3].payment == Decimal("10000.00")
    assert rows[-1].balance == Decimal("0.00")


def test_the_last_bank_installment_in_force_wins() -> None:
    fixed = (
        Installment(date(2026, 1, 15), Decimal("10000.00")),
        Installment(date(2026, 6, 16), Decimal("9000.00")),
    )

    rows = schedule(CONTRACT, RATES, installments=fixed)

    assert rows[4].payment == Decimal("10000.00")
    assert rows[5].due == date(2026, 7, 15)
    assert rows[5].payment == Decimal("9000.00")


def test_with_a_bank_installment_a_new_rate_keeps_it_and_moves_the_end() -> None:
    fixed = (Installment(date(2026, 1, 15), Decimal("8884.88")),)
    rates = (*RATES, Rate(date(2026, 7, 15), Decimal("24")))

    rows = schedule(CONTRACT, rates, installments=fixed)

    assert all(r.payment == Decimal("8884.88") for r in rows[:-1])
    assert len(rows) > 12
    assert rows[-1].balance == Decimal("0.00")


def test_a_real_balance_with_the_bank_installment_sets_the_end() -> None:
    fixed = (Installment(date(2026, 1, 15), Decimal("10000.00")),)
    anchors = (Anchor(date(2026, 10, 20), Decimal("15000.00")),)

    rows = schedule(CONTRACT, RATES, anchors, installments=fixed)

    assert rows[-1].due == date(2026, 12, 15)  # 10,000 in November, the rest in December
    assert rows[-2].balance == Decimal("5150.00")  # 15,000 + 150 of interest - 10,000
    assert rows[-1].payment == Decimal("5201.50")  # 5,150 + 51.50 of interest
    assert rows[-1].balance == Decimal("0.00")


def test_a_bank_installment_below_the_interest_is_ignored_while_it_is() -> None:
    fixed = (Installment(date(2026, 1, 15), Decimal("900.00")),)

    rows = schedule(CONTRACT, RATES, installments=fixed)

    assert [r.interest for r in rows[:3]] == [Decimal(v) for v in ("1000.00", "921.15", "841.51")]
    assert [r.payment for r in rows[:3]] == [Decimal(v) for v in ("8884.88", "8884.88", "900.00")]
    assert rows[-1].balance == Decimal("0.00")


def test_the_summary_follows_the_bank_installment() -> None:
    fixed = (Installment(date(2026, 1, 15), Decimal("10000.00")),)

    found = summary(CONTRACT, RATES, (), (), date(2026, 4, 30), installments=fixed)

    assert found.end == date(2026, 12, 15)
    assert found.installments_left == 8
    assert found.next_payment is not None
    assert found.next_payment.payment == Decimal("10000.00")
