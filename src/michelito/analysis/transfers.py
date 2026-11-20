"""Detection of transfers between the user's accounts.

A transfer moves money between the user's own accounts: it is neither expense nor income.
It is detected, in this order, by:
1. A payment received by a card (already the card-payment category).
2. A bank debit with the same currency and amount as that payment, a few days apart.
3. A bank debit whose text talks about paying a card ("PAGO ... TC"); useful when the
   amount does not match, like a US$ card paid from a RD$ account.
4. A bank transaction that names a holder (the bank truncates names: see `_names`), the
   full number of another own account (registered or written in holders.txt; with or
   without leading zeros), the last 4 digits of another own account, or says "CUENTA
   PROPIA". On a reversal ("DEV ...") only the holder or "CUENTA PROPIA": its digits are
   the reference.

It only proposes the default category; the user's corrections always win.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from michelito.analysis import categories
from michelito.analysis.accounts import BANK_KINDS, AccountInfo

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

# Days apart tolerated between the card payment and the bank debit.
PAYMENT_MATCH_DAYS = 5

_CREDIT_CARD = "credit_card"
_NUMBER_DIGITS = 4  # an account's last 4 digits, as a whole word
_FULL_NUMBER_DIGITS = 6  # a full number has at least 6 digits
_PREFIX_WORDS = 2  # holder words that suffice when the bank truncates the name
_MIN_CUT = 3  # minimum letters of a truncated word following a single whole word
_MIN_MID_CUT = 2  # minimum letters of a truncation that is not at the end of the text
# Short name words that, in the middle of the text, are not taken for a truncation.
_PARTICLES = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "Y"})  # spanish-data
# A holders.txt line with only digits and separators is an own account number.
_NUMBER_LINE = re.compile(r"[\d\s.\-/]+")
# Bank wording for an own-account transfer and for a card payment.
# spanish-data: begin
_OWN_ACCOUNT_WORDING = re.compile(r"\b(CUENTA|CTA) PROPIA\b")
_CARD_PAYMENT_WORDING = re.compile(r"\bPAGO\b.*\b(TC|TDC|TARJETA)\b")
# spanish-data: end

_CARD_LAST4 = """
SELECT a.key, c.last4 FROM cards c JOIN accounts a ON a.id = c.account_id
"""


@dataclass(frozen=True)
class Holders:
    """What holders.txt says: (normalized) names and own account numbers."""

    names: tuple[str, ...] = ()
    numbers: tuple[int, ...] = ()  # no leading zeros: compared as integers


def as_holders(holders: Iterable[str] | Holders) -> Holders:
    """Also accepts a bare list of names (as before numbers existed)."""
    if isinstance(holders, Holders):
        return holders
    return Holders(names=tuple(holders))


def load_holders(path: Path) -> Holders:
    """Holders from the file, one per line; with no file (or an unreadable one), none.

    A line with only digits and separators ("000-123456-7") is the number of an own account
    if it has at least 6 digits; with fewer it is ignored. The other lines are names.
    """
    if not path.is_file():
        return Holders()
    try:
        return parse_holders(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return Holders()


def parse_holders(text: str) -> Holders:
    """Holders from the text of a holders file (see `load_holders`)."""
    lines = text.splitlines()
    names: list[str] = []
    numbers: list[int] = []
    for line in lines:
        stripped = line.strip()
        if stripped and _NUMBER_LINE.fullmatch(stripped):
            digits = re.sub(r"\D", "", line)
            if len(digits) >= _FULL_NUMBER_DIGITS:
                numbers.append(int(digits))
        elif name := categories.clean(line):
            names.append(name)
    return Holders(tuple(dict.fromkeys(names)), tuple(dict.fromkeys(numbers)))


def last4_by_card_account(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    """Last 4 digits of each stored card, by account key."""
    found: dict[str, list[str]] = {}
    for key, last4 in conn.execute(_CARD_LAST4):
        found.setdefault(key, []).append(last4)
    return {key: tuple(values) for key, values in found.items()}


def detect_transfers(
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    holders: Iterable[str] | Holders,
    *,
    card_last4: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, str]:
    """Fingerprint -> transfer category of the transactions that look like one.

    `holders`: holder names or `Holders` (names and numbers from holders.txt).
    `card_last4` provides the card digits (card keys do not carry them).
    """
    listed = as_holders(holders)
    kinds = {info.key: info.kind for info in accounts}
    found: dict[str, str] = {}
    payments = [m for m in movements if _is_card_payment(m, kinds)]
    found.update((m.fingerprint, categories.CARD_PAYMENT) for m in payments)
    for debit in _paired_debits(movements, payments, kinds):
        found[debit.fingerprint] = categories.CARD_PAYMENT
    numbers = _numbers_by_account(accounts, card_last4 or {})
    full = _full_numbers(accounts)
    names = [name for name in (categories.clean(h) for h in listed.names) if name]
    for item in movements:
        if item.fingerprint not in found:
            category = _by_wording(item, kinds)
            if category is None and _is_bank_row(item, kinds):
                category = _by_ownership(item, names, numbers, full, listed.numbers)
            if category:
                found[item.fingerprint] = category
    return found


def _is_card_payment(item: Movement, kinds: Mapping[str, str]) -> bool:
    return (
        kinds.get(item.account) == _CREDIT_CARD
        and item.amount < 0
        and item.original_ref == categories.CARD_PAYMENT
    )


def _is_bank_row(item: Movement, kinds: Mapping[str, str]) -> bool:
    """Transaction of a bank account (not a card): holder rules apply only there."""
    return kinds.get(item.account, "") in BANK_KINDS


def _is_bank_debit(item: Movement, kinds: Mapping[str, str]) -> bool:
    return item.amount > 0 and _is_bank_row(item, kinds)


def _paired_debits(
    movements: Sequence[Movement], payments: Sequence[Movement], kinds: Mapping[str, str]
) -> list[Movement]:
    """Bank debits with their card payment: one to one, the closest in date first."""
    free = list(payments)
    window = timedelta(days=PAYMENT_MATCH_DAYS)
    paired = []
    for debit in sorted((m for m in movements if _is_bank_debit(m, kinds)), key=_by_day):
        near = [
            p
            for p in free
            if p.currency == debit.currency
            and -p.amount == debit.amount
            and abs(p.day - debit.day) <= window
        ]
        if near:
            free.remove(min(near, key=lambda p: (abs(p.day - debit.day), p.day)))
            paired.append(debit)
    return paired


def _by_day(item: Movement) -> tuple[object, str]:
    return (item.day, item.fingerprint)


def _by_wording(item: Movement, kinds: Mapping[str, str]) -> str | None:
    if _is_bank_debit(item, kinds) and _CARD_PAYMENT_WORDING.search(
        categories.clean(item.description)
    ):
        return categories.CARD_PAYMENT
    return None


def _by_ownership(
    item: Movement,
    holders: Sequence[str],
    numbers: Mapping[str, frozenset[str]],
    full: Mapping[str, int],
    listed: Sequence[int] = (),
) -> str | None:
    text = categories.clean(item.description)
    words = text.split()
    if _OWN_ACCOUNT_WORDING.search(text) or any(_names(words, h.split()) for h in holders):
        return categories.OWN_TRANSFER
    if item.amount < 0 and categories.is_reversal(text):
        return None  # a reversal's digits are its reference, not an account
    tokens = set(words)
    for key, digits in numbers.items():
        if key != item.account and tokens & digits:
            return categories.OWN_TRANSFER
    long_tokens = {
        int(t) for t in re.findall(r"\d+", item.description) if len(t) >= _FULL_NUMBER_DIGITS
    }
    if any(key != item.account and value in long_tokens for key, value in full.items()):
        return categories.OWN_TRANSFER
    # A holders.txt number that is the transaction's own account does not count.
    mine = full.get(item.account)
    if any(value != mine and value in long_tokens for value in listed):
        return categories.OWN_TRANSFER
    return None


def _names(words: Sequence[str], holder: Sequence[str]) -> bool:
    """The description names the holder, whole or truncated by the bank, anywhere.

    The bank truncates the name where the field ends, and sometimes another field follows
    ("... FULANO DE TA BANCO BHD ..."). From any word, the holder's words that appear whole
    and in a row are counted (`m`); it matches if:
    - all of them appear;
    - `m >= 2` and the text ends there ("... FULANO DE");
    - `m >= 2` and the next word is the start of the holder's next word
      ("MARIA PEREZ LO BANCO" for MARIA PEREZ LOPEZ), even if more text follows;
    - `m == 1` and the next word is the start of the second, at least 3 letters long
      ("MARIA PER BANCO").
    In the middle of the text, the truncation cannot be a particle or a single letter
    (`_is_cut`). A different whole word breaks the match: "MARIA PEREZ INVENTADAS" is not
    MARIA PEREZ INVENTADA, and "MARIA PEREZ GOMEZ" (another person with the same first and
    last name) is not MARIA PEREZ LOPEZ. A one-word holder has to appear whole.
    """
    size = len(holder)
    for start in range(len(words)):
        matched = 0
        while (
            matched < size
            and start + matched < len(words)
            and words[start + matched] == holder[matched]
        ):
            matched += 1
        if matched == size:
            return True
        if matched == 0:
            continue
        following = words[start + matched] if start + matched < len(words) else None
        if following is None:
            if matched >= _PREFIX_WORDS:
                return True
            continue
        last = start + matched == len(words) - 1
        if holder[matched].startswith(following) and _is_cut(following, matched, last):
            return True
    return False


def _is_cut(word: str, matched: int, last: bool) -> bool:
    """`word` may be the truncation of the holder's next word after `matched` whole ones.

    At the end of the text any prefix will do (after 2 whole words). In the middle of the
    text, a particle ("DE", "LA"...) or a single letter is more likely another word than a
    truncation: "JUAN PEREZ DE LA CRUZ" is not JUAN PEREZ DELGADO.
    """
    if not last and (word in _PARTICLES or len(word) < _MIN_MID_CUT):
        return False
    return matched >= _PREFIX_WORDS or len(word) >= _MIN_CUT


def _numbers_by_account(
    accounts: Sequence[AccountInfo], card_last4: Mapping[str, Sequence[str]]
) -> dict[str, frozenset[str]]:
    """Last 4 digits of each account, from its key and its cards.

    The last group of 4 digits is compared as a whole word: a number fragment ("001234567")
    does not match on purpose, because of false positives; the account's full number is
    compared separately (`_full_numbers`).
    """
    numbers: dict[str, frozenset[str]] = {}
    for info in accounts:
        groups = [*re.findall(r"\d+", info.key), *card_last4.get(info.key, ())]
        digits = {g[-_NUMBER_DIGITS:] for g in groups if len(g) >= _NUMBER_DIGITS}
        if digits:
            numbers[info.key] = frozenset(digits)
    return numbers


def _full_numbers(accounts: Sequence[AccountInfo]) -> dict[str, int]:
    """Full number of each bank account (the digits of its key, without leading zeros).

    Cards have no number in their key; an account with fewer than 6 digits does not count
    either, because such a short number shows up in any reference.
    """
    found: dict[str, int] = {}
    for info in accounts:
        digits = "".join(re.findall(r"\d", info.key.partition(":")[2].partition(":")[2]))
        if info.kind in BANK_KINDS and len(digits) >= _FULL_NUMBER_DIGITS:
            found[info.key] = int(digits)
    return found
