"""A new group from a credit (`analysis.ledger_credit`): who paid, the expense it pays back, the
other credits around it and "their share is what they paid". Made-up names and amounts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from michelito.analysis import categories as cat
from michelito.analysis import ledger_credit
from michelito.analysis.ledger import Contact
from michelito.analysis.links import LinkError, Links
from michelito.analysis.spending import Movement

D = Decimal
ME, ANA, LUIS = 1, 2, 3
CONTACTS = (
    Contact(ME, "me", True),
    Contact(ANA, "Ana", aliases=("ANA FICTICIA",)),
    Contact(LUIS, "Luis Inventado"),
)
CREDIT_DAY = "2026-03-10"


def _move(
    day: str,
    amount: str,
    description: str,
    category: str = cat.RESTAURANTS,
    currency: str = "DOP",
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=description,
        description=description,
        category=category,
        amount=D(amount),
        currency=currency,
        institution="x",
        fingerprint=description,
        account="checking",
    )


def _credit(description: str, amount: str = "-500", day: str = CREDIT_DAY) -> Movement:
    return _move(day, amount, description, cat.OTHER_INCOME)


class TestGuessPerson:
    def test_a_known_alias_is_that_contact(self) -> None:
        found = ledger_credit.guess_person("TRANSFERENCIA DE ANA FICTICIA", CONTACTS)
        assert found == ledger_credit.PersonGuess(ANA, "Ana", None)

    def test_a_contact_named_in_the_text_is_that_contact(self) -> None:
        found = ledger_credit.guess_person("TOKE DE LUIS INVENTADO", CONTACTS)
        assert found == ledger_credit.PersonGuess(LUIS, "Luis Inventado", None)

    def test_an_unknown_name_is_a_new_person_with_the_bank_text_as_alias(self) -> None:
        found = ledger_credit.guess_person("TOKE DE ROSA FICTICIA", CONTACTS)
        assert found == ledger_credit.PersonGuess(None, "Rosa Ficticia", "ROSA FICTICIA")

    def test_no_name_no_guess(self) -> None:
        assert ledger_credit.guess_person("DEPOSITO EN EFECTIVO", CONTACTS) is None


@pytest.mark.parametrize(
    ("value", "gross", "fits"),
    [
        ("1000", "2000", True),  # half
        ("666.67", "2000", True),  # a third
        ("1010", "2000", True),  # half within the tolerance
        ("1100", "2000", False),
        ("2000", "2000", False),  # all of it is not a share
        ("150", "2000", False),  # less than a tenth
    ],
)
def test_fits_share(value: str, gross: str, fits: bool) -> None:
    assert ledger_credit.fits_share(D(value), D(gross)) is fits


class TestExpenseOptions:
    def test_fitting_ones_first_then_by_closeness_within_the_window(self) -> None:
        credit = _credit("TOKE DE ANA FICTICIA", "-500")
        flow = [
            credit,
            _move("2026-03-08", "300", "CAFE CERCANO"),
            _move("2026-02-01", "1000", "CENA LEJANA"),  # half: fits
            _move("2026-03-09", "1500", "CENA CERCANA"),  # a third: fits
            _move("2026-03-11", "1000", "DESPUES DEL PAGO"),  # after the credit
            _move("2025-10-01", "1000", "MUY VIEJO"),  # out of the window
            _move("2026-03-01", "-100", "DEVOLUCION"),  # not an expense
        ]
        found = ledger_credit.expense_options(flow, Links(), credit)
        assert [(o.move.description, o.fits) for o in found] == [
            ("CENA CERCANA", True),
            ("CENA LEJANA", True),
            ("CAFE CERCANO", False),
        ]

    def test_another_currency_never_fits(self) -> None:
        credit = _credit("TOKE DE ANA FICTICIA", "-500")
        flow = [_move("2026-03-01", "1000", "TIENDA EN DOLARES", currency="USD")]
        found = ledger_credit.expense_options(flow, Links(), credit)
        assert [o.fits for o in found] == [False]


def test_credit_options_put_the_same_person_first_and_skip_far_ones() -> None:
    credit = _credit("TOKE DE ANA FICTICIA")
    flow = [
        credit,
        _credit("TOKE DE LUIS INVENTADO", day="2026-03-11"),
        _credit("TRANSFERENCIA DE ANA FICTICIA", day="2026-03-30"),
        _credit("TOKE DE ROSA FICTICIA", day="2026-05-01"),  # too far
        _credit("PAGO INTERESES CA", day="2026-03-10"),  # interest is never a payment
    ]
    found = ledger_credit.credit_options(flow, Links(), credit, CONTACTS)
    assert [(o.move.description, o.person and o.person.contact_id) for o in found] == [
        ("TRANSFERENCIA DE ANA FICTICIA", ANA),
        ("TOKE DE LUIS INVENTADO", LUIS),
    ]


class TestPaidSplits:
    def test_their_share_is_what_they_paid_and_the_rest_is_mine(self) -> None:
        assert ledger_credit.paid_splits([D(2000)], {ANA: D(850)}, ME) == [
            {ME: D(1150), ANA: D(850)}
        ]

    def test_several_expenses_are_filled_in_order(self) -> None:
        found = ledger_credit.paid_splits([D(300), D(1000)], {ANA: D(500), LUIS: D(200)}, ME)
        assert found == [{ANA: D(300)}, {ME: D(600), ANA: D(200), LUIS: D(200)}]
        assert sum((sum(s.values(), D(0)) for s in found), D(0)) == D(1300)

    def test_paying_more_than_the_expenses_is_refused(self) -> None:
        with pytest.raises(LinkError):
            ledger_credit.paid_splits([D(500)], {ANA: D(600)}, ME)
