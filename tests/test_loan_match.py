"""Which charges are a loan's payments (`analysis.loan_match`), made-up values."""

import pytest

from michelito.analysis.loan_match import clean_number, mentions


@pytest.mark.parametrize(
    ("typed", "clean"),
    [
        ("1234567890", "1234567890"),
        (" 12-345 678 ", "12345678"),
        ("0012345", "0012345"),
        ("ab12x", "AB12X"),
    ],
)
def test_the_number_keeps_only_letters_and_digits(typed: str, clean: str) -> None:
    assert clean_number(typed) == clean


def test_a_description_mentions_the_number_as_a_whole_token() -> None:
    assert mentions("AUT PAGO 1234567890 101-00001 5555555555", "1234567890")
    assert mentions("AUT PAGO 0123456789 101-00001", "123456789")
    assert not mentions("AUT PAGO 12345678901 101-00001", "1234567890")
    assert not mentions("AUT PAGO 123456789 101-00001", "1234567890")
    assert not mentions("CLARO PAGO 1234567890", "")


def test_leading_zeros_do_not_make_another_loan() -> None:
    assert mentions("AUT PAGO 0000000088", "0000000088")
    assert mentions("AUT PAGO 0000000088", "00088")
    assert not mentions("AUT PAGO 88 0000000088X", "0000000088")  # "88" alone is too short


def test_short_numbers_never_match() -> None:
    # A number this short would match references and amounts.
    assert not mentions("AUT PAGO 1234 101-00001", "1234")
