"""A new shared group started from a credit ("It is a payment…" → "+ New group"): the credit is
what someone paid the user back for an expense that is in no group yet. Deterministic
suggestions only; nothing is linked or recorded without a tap.

- **Who paid** (`guess_person`): the counterpart printed in the transfer when it is a contact
  or an alias already; else that name as a new person, the bank's text kept as the alias; else
  a contact whose alias or name the description holds; else nobody (picked by hand).
- **The expense it pays back** (`expense_options`): the user's shareable expenses not in a
  group, from the PICK_WINDOW_DAYS days up to the credit; first those the credit is a fair
  share of (`fits_share`: half, a third… up to MAX_PEOPLE people, within FIT_TOLERANCE), then
  the rest; the closest in date first in each block. At most EXPENSE_LIMIT.
- **The other transactions** (`credit_options`): other eligible credits within
  OTHER_CREDIT_DAYS of this one, with their own guessed person; those naming the same person
  first, then the closest in date. At most CREDIT_LIMIT. None is preselected.
- **"Their share is what they paid"** (`paid_splits`): each person's share across the expenses
  is exactly what they paid, the rest is the user's, filling the expenses in order. It needs
  one currency and what they paid not over the expenses.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from michelito.analysis import ledger, ledger_suggest, shared
from michelito.analysis.links import LinkError, Links
from michelito.analysis.spending import Movement
from michelito.i18n import t

PICK_WINDOW_DAYS = shared.PICK_WINDOW_DAYS
MAX_PEOPLE = 10
FIT_TOLERANCE = Decimal("0.02")
OTHER_CREDIT_DAYS = 30
EXPENSE_LIMIT = 60
CREDIT_LIMIT = 20
_ZERO = Decimal(0)


@dataclass(frozen=True)
class PersonGuess:
    contact_id: int | None  # an existing contact
    name: str  # as it reads
    alias: str | None  # the bank's text, kept as an alias of a new person


@dataclass(frozen=True)
class ExpenseOption:
    move: Movement
    fits: bool  # the credit is a fair share of it


@dataclass(frozen=True)
class CreditOption:
    move: Movement
    person: PersonGuess | None


def guess_person(description: str, contacts: Iterable[ledger.Contact]) -> PersonGuess | None:
    others = [c for c in contacts if not c.is_me]
    raw = ledger_suggest.transfer_name(description)
    if raw is not None:
        folded = shared.fold(raw)
        for contact in others:
            names = {shared.fold(contact.name), *(shared.fold(a) for a in contact.aliases)}
            if folded in names:
                return PersonGuess(contact.id, contact.name, None)
    for contact in others:
        if ledger_suggest.matches_contact(contact, description):
            return PersonGuess(contact.id, contact.name, None)
    if raw is not None:
        return PersonGuess(None, ledger_suggest.nice_name(raw), raw)
    return None


def fits_share(value: Decimal, gross: Decimal) -> bool:
    """`value` is the expense split among 2 to MAX_PEOPLE people (one of their shares)."""
    if value <= 0 or gross <= value:
        return False
    return any(
        abs(gross / people - value) <= value * FIT_TOLERANCE for people in range(2, MAX_PEOPLE + 1)
    )


def expense_options(
    movements: Iterable[Movement], links: Links, credit: Movement
) -> list[ExpenseOption]:
    value = -credit.amount
    found = [
        ExpenseOption(m, m.currency == credit.currency and fits_share(value, shared.gross(m)))
        for m in movements
        if shared.is_shareable(m)
        and not m.link
        and not links.is_linked(m.fingerprint)
        and m.ref not in shared.NOT_SHARED_EXPENSE
        and 0 <= (credit.day - m.day).days <= PICK_WINDOW_DAYS
    ]
    found.sort(key=lambda o: (not o.fits, (credit.day - o.move.day).days, o.move.fingerprint))
    return found[:EXPENSE_LIMIT]


def credit_options(
    movements: Iterable[Movement],
    links: Links,
    credit: Movement,
    contacts: Sequence[ledger.Contact],
) -> list[CreditOption]:
    own = guess_person(credit.description, contacts)
    found = []
    for move in movements:
        if move.fingerprint == credit.fingerprint or not shared.is_eligible_credit(move, links):
            continue
        distance = abs((move.day - credit.day).days)
        if distance > OTHER_CREDIT_DAYS:
            continue
        person = guess_person(move.description, contacts)
        same = own is not None and person is not None and _same(own, person)
        found.append(((not same, distance, move.fingerprint), CreditOption(move, person)))
    found.sort(key=lambda item: item[0])
    return [option for _, option in found[:CREDIT_LIMIT]]


def _same(a: PersonGuess, b: PersonGuess) -> bool:
    if a.contact_id is not None or b.contact_id is not None:
        return a.contact_id == b.contact_id
    return shared.fold(a.name) == shared.fold(b.name)


def paid_splits(
    expenses: Sequence[Decimal], paid: Mapping[int, Decimal], me: int
) -> list[dict[int, Decimal]]:
    """Each expense's shares (person -> amount, the user's included) so that every person's
    shares add up to what they paid; the rest of each expense is the user's."""
    total = sum(expenses, _ZERO)
    if sum(paid.values(), _ZERO) > total:
        raise LinkError(t("analysis.ledger_credit.paid_over"))
    left = {person: value for person, value in paid.items() if value > 0}
    result = []
    for amount in expenses:
        room = amount
        shares: dict[int, Decimal] = {}
        for person in list(left):
            take = min(left[person], room)
            if take > 0:
                shares[person] = take
                room -= take
                left = {**left, person: left[person] - take}
        result.append({me: room, **shares} if room > 0 else shares)
    return result
