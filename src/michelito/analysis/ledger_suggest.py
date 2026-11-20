"""Deterministic suggestions around the shared ledger. They only propose: nothing is linked or
recorded without a tap.

- **Names seen in the bank** (`bank_names`): the counterpart of incoming transfers
  («TRANSFERENCIA DE <NAME>…», «TOKE DE <NAME>»…) that is not a contact or alias yet: offered
  when adding people ("seen in your bank"; picking one creates the alias).
- **Matching a contact** (`matches_contact`): a description holds one of the contact's aliases,
  or every word of its name (NAME_MIN_LETTERS letters or more; a name with none such matches
  only by alias).
- **"I paid it"** (`expense_candidates`): unlinked expenses that can be shared, from the last
  PICK_WINDOW_DAYS days; likely ones first (a category that is usually shared, or a round amount
  of at least LIKELY_MIN_DOP), then the rest; the most recent first in each block.
- **Payment candidates** (`payment_candidates`): for a payment received, eligible credits; for one
  paid, bank debits that are not expenses nor linked. Same currency, within PAYMENT_TOLERANCE of
  the amount and PAYMENT_DAYS of the day; those that name the person first, then the closest in
  amount and date. At most CANDIDATES.
- **Reverse flow** (`reverse_suggestions`, for "To review"): an eligible credit that names a
  contact who owes the user in some group ("Did Ana pay you RD$1,250?"): the group with the oldest
  pending entry, the credit no earlier than it and not over what they owe (with
  PAYMENT_TOLERANCE). Also an unlinked payment received (`Payment.fingerprint` None) whose
  matching credit arrives later: proposed for linking.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from michelito.analysis import categories, ledger, shared
from michelito.analysis.links import Links
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.spending import Movement

PICK_WINDOW_DAYS = shared.PICK_WINDOW_DAYS
PAYMENT_TOLERANCE = Decimal("0.05")
PAYMENT_DAYS = 7
CANDIDATES = 3
LIKELY_MIN_DOP = Decimal(1000)
ROUND_DOP = Decimal(100)
_ZERO = Decimal(0)
# Categories whose expenses are usually shared.
LIKELY_CATEGORIES = frozenset(
    {
        categories.RESTAURANTS,
        categories.DELIVERY,
        categories.GROCERIES,
        categories.ENTERTAINMENT,
        categories.TRAVEL,
        categories.HOME,
    }
)
# The counterpart of an incoming transfer, as the banks print it.
_TRANSFER_NAME = re.compile(
    r"\b(?:TRANSFERENCIA|TRANSF\.?|TOKE|LBTR|DEPOSITO|PAGO MOVIL|ENVIO)"  # spanish-data
    r"(?:\s+RECIBIDA)?\s+DE\s+([A-Z][A-Z'.]*(?:\s+[A-Z][A-Z'.]*){0,3})"  # spanish-data
)
_NOT_NAME = frozenset({"CTA", "CUENTA", "BANCO", "REF", "NO"})  # spanish-data


@dataclass(frozen=True)
class BankName:
    name: str  # as it reads ("Ana Ficticia")
    raw: str  # as the bank printed it ("ANA FICTICIA")
    count: int
    last_day: date


def transfer_name(description: str) -> str | None:
    """The counterpart printed in an incoming transfer, in capitals (None: none)."""
    found = _TRANSFER_NAME.search(description.upper())
    if found is None:
        return None
    words = []
    for word in found.group(1).split():
        if word in _NOT_NAME or any(ch.isdigit() for ch in word):
            break
        words.append(word.strip("."))
    return " ".join(w for w in words if w) or None


def nice_name(raw: str) -> str:
    return " ".join(part.capitalize() for part in raw.split())


def _known(book: ledger.Ledger) -> set[str]:
    found: set[str] = set()
    for contact in book.contacts.values():
        if contact.is_me:
            continue
        found.add(shared.fold(contact.name))
        found.update(shared.fold(a) for a in contact.aliases)
    return found


def bank_names(movements: Iterable[Movement], book: ledger.Ledger) -> list[BankName]:
    """Counterparts of incoming transfers that are not contacts yet, the most recent first."""
    known = _known(book)
    seen: dict[str, BankName] = {}
    for move in movements:
        if move.amount >= 0:
            continue
        raw = transfer_name(move.description)
        if raw is None or shared.fold(raw) in known:
            continue
        key = shared.fold(raw)
        prior = seen.get(key)
        if prior is None:
            seen[key] = BankName(nice_name(raw), raw, 1, move.day)
        else:
            seen[key] = BankName(
                prior.name, prior.raw, prior.count + 1, max(prior.last_day, move.day)
            )
    return sorted(seen.values(), key=lambda b: (b.last_day, b.count), reverse=True)


def matches_contact(contact: ledger.Contact, description: str) -> bool:
    text = shared.fold(" ".join(description.split()))
    padded = f" {' '.join(shared.words(text))} "
    for alias in contact.aliases:
        words = shared.words(alias)
        if words and f" {' '.join(words)} " in padded:
            return True
    names = shared.name_words(contact.name)
    return bool(names) and names <= set(shared.words(text))


# --- "I paid it" --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpenseCandidate:
    move: Movement
    likely: bool


def is_likely(move: Movement, rates: Mapping[str, Rate]) -> bool:
    """At least LIKELY_MIN_DOP and either a category that is usually shared or a round amount in
    RD$ (a multiple of ROUND_DOP as printed: a converted US$ amount does not count)."""
    value = to_dop(shared.gross(move), move.currency, rate_for(rates, move.month))
    if value is None or value < LIKELY_MIN_DOP:
        return False
    round_ = move.currency == "DOP" and shared.gross(move) % ROUND_DOP == 0
    return move.ref in LIKELY_CATEGORIES or round_


def expense_candidates(
    movements: Iterable[Movement],
    links: Links,
    today: date,
    rates: Mapping[str, Rate],
    chosen: Collection[str] | None = None,
) -> list[ExpenseCandidate]:
    found = [
        ExpenseCandidate(m, is_likely(m, rates))
        for m in movements
        if shared.is_shareable(m)
        and not m.link
        and not links.is_linked(m.fingerprint)
        and m.ref not in shared.NOT_SHARED_EXPENSE
        and 0 <= (today - m.day).days <= PICK_WINDOW_DAYS
        and (chosen is None or m.account in chosen)
    ]
    return sorted(found, key=lambda c: (c.likely, c.move.day, c.move.fingerprint), reverse=True)


# --- Payments -------------------------------------------------------------------------------


def _fits(value: Decimal, amount: Decimal) -> bool:
    return abs(value - amount) <= amount * PAYMENT_TOLERANCE


def is_payment_debit(move: Movement, links: Links, banks: Collection[str]) -> bool:
    """A bank debit that can be a payment the user made: any category (a transfer to a person
    may have been categorized as an expense) but card payments, own transfers and currency
    exchanges; not linked. The same rule checks a debit picked by hand (`web.links`)."""
    return (
        move.amount > 0
        and move.account in banks
        and not move.link
        and not links.is_linked(move.fingerprint)
        and move.ref
        not in (categories.CARD_PAYMENT, categories.OWN_TRANSFER, categories.CURRENCY_EXCHANGE)
    )


def payment_candidates(
    movements: Iterable[Movement],
    links: Links,
    banks: Collection[str],
    *,
    received: bool,
    amount: Decimal,
    currency: str,
    day: date,
    contact: ledger.Contact | None = None,
) -> list[Movement]:
    found = []
    for move in movements:
        eligible = (
            shared.is_eligible_credit(move, links)
            if received
            else is_payment_debit(move, links, banks)
        )
        if not eligible or move.currency != currency:
            continue
        if abs((move.day - day).days) > PAYMENT_DAYS or not _fits(abs(move.amount), amount):
            continue
        named = contact is not None and matches_contact(contact, move.description)
        key = (not named, abs(abs(move.amount) - amount), abs((move.day - day).days))
        found.append((key, move.fingerprint, move))
    found.sort(key=lambda item: (item[0], item[1]))
    return [move for _, _, move in found[:CANDIDATES]]


@dataclass(frozen=True)
class ReverseSuggestion:
    move: Movement  # the credit
    group_id: int
    contact_id: int | None  # None: an unattributed payment to link
    amount: Decimal  # what the credit brings (positive)
    payment_id: int | None = None  # an unlinked payment it would reconcile


def _owed_by(
    contact_id: int, states: Mapping[int, ledger.GroupState]
) -> list[tuple[date, int, dict[str, Decimal]]]:
    """(oldest pending day, group id, what they owe by currency) for each group where they do."""
    found = []
    for state in states.values():
        if state.group.archived:
            continue
        person = state.person(contact_id)
        if person is None:
            continue
        owes = {c: v for c, v in person.net.items() if v > 0}
        if not owes:
            continue
        days = [e.day for e in state.entries if e.paid_by_me and contact_id in e.entry.people]
        found.append((min(days) if days else date.min, state.id, owes))
    return sorted(found)


def reverse_suggestions(
    movements: Sequence[Movement],
    links: Links,
    book: ledger.Ledger,
    states: Mapping[int, ledger.GroupState],
) -> dict[str, ReverseSuggestion]:
    """Credit fingerprint -> what it seems to be (see the module docstring)."""
    found: dict[str, ReverseSuggestion] = {}
    loose = [
        (g.id, p)
        for g in book.groups
        for p in g.payments
        if p.fingerprint is None and p.to_contact == book.me
    ]
    owing = {c.id: _owed_by(c.id, states) for c in book.contacts.values() if not c.is_me}
    for move in movements:
        if not shared.is_eligible_credit(move, links):
            continue
        value = -move.amount
        pending = _loose_match(move, value, loose)
        if pending is not None:
            group_id, payment = pending
            found[move.fingerprint] = ReverseSuggestion(
                move, group_id, payment.from_contact, value, payment.id
            )
            continue
        for contact_id, groups in owing.items():
            contact = book.contacts[contact_id]
            if not groups or not matches_contact(contact, move.description):
                continue
            chosen = _group_for(move, value, groups)
            if chosen is not None:
                found[move.fingerprint] = ReverseSuggestion(move, chosen, contact_id, value)
                break
    return found


def _loose_match(
    move: Movement, value: Decimal, loose: Sequence[tuple[int, ledger.Payment]]
) -> tuple[int, ledger.Payment] | None:
    options = [
        (abs((move.day - p.day).days), p.id, g, p)
        for g, p in loose
        if p.currency == move.currency
        and abs((move.day - p.day).days) <= PAYMENT_DAYS
        and _fits(value, p.amount)
    ]
    if not options:
        return None
    _, _, group_id, payment = min(options, key=lambda o: (o[0], o[1]))
    return group_id, payment


def _group_for(
    move: Movement, value: Decimal, groups: Sequence[tuple[date, int, dict[str, Decimal]]]
) -> int | None:
    for oldest, group_id, owes in groups:
        owed = owes.get(move.currency)
        if owed is None or move.day < oldest:
            continue
        if value <= owed * (1 + PAYMENT_TOLERANCE):
            return group_id
    return None


def empty_suggestions(
    movements: Iterable[Movement], links: Links, today: date, rates: Mapping[str, Rate]
) -> list[Movement]:
    """ "these dinners look shared": up to CANDIDATES likely expenses to split."""
    found = [c.move for c in expense_candidates(movements, links, today, rates) if c.likely]
    return found[:CANDIDATES]
