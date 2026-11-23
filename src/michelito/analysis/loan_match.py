"""Which charges are a loan's payments (pure logic): those whose description has the loan number
as a whole word, e.g. "AUT PAGO <number> <reference> <account>", from any account.

The number is kept with only its letters and digits, upper case (`clean_number`), and compared
without leading zeros, so "00-1234567" and "1234567" are the same loan. A word shorter than
`MIN_LENGTH` (counting its zeros) never matches: it would catch references and amounts.
"""

from __future__ import annotations

import re

MIN_LENGTH = 5
_NOT_ALNUM = re.compile(r"[^0-9A-Za-z]")


def clean_number(text: str) -> str:
    return _NOT_ALNUM.sub("", text).upper()


def same_number(first: str, second: str) -> bool:
    """Both (clean) numbers are the same loan: equal without their leading zeros."""
    return bool(first.lstrip("0")) and first.lstrip("0") == second.lstrip("0")


def mentions(description: str, number: str) -> bool:
    """The description has `number` (already clean) as one of its words."""
    if len(number) < MIN_LENGTH:
        return False
    for word in description.split():
        clean = clean_number(word)
        if len(clean) >= MIN_LENGTH and same_number(clean, number):
            return True
    return False
