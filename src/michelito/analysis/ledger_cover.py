"""Paying for others and payments in another currency (pure, over `ledger`'s balances).

- `propose_allocations`: the default allocations of a payment on behalf of several people (rule
  in `ledger`'s module docstring: payer first, then the others in the order checked, converted at
  the payment month's rate; what is left stays on the payer).
- `cover_suggestion`: "A paid RD$ 74,340 too much and B owes US$ 1,244.20. Was that payment for B
  too?" (the exact condition is in its docstring).
- `approx_total`: the "in total ≈" line for balances in two currencies.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from michelito.analysis.ledger import (
    LEFTOVER,
    Allocation,
    Group,
    GroupState,
    Payment,
    _apply_attributed,
    _Book,
    _open_book,
    _ordered_payments,
    apply_fifo,
    convert,
    group_state,
)
from michelito.analysis.rates import Rate, rate_for

_ZERO = Decimal(0)


@dataclass(frozen=True)
class Proposal:
    """The allocations proposed for a payment to the user (`propose_allocations`)."""

    # (person, amount in the payment's currency), the payer first.
    parts: tuple[tuple[int, Decimal], ...]
    owed: Mapping[int, Decimal]  # what each one owed at that point, in the payment's currency
    rate: Rate | None  # the payment month's rate, when some claim is in the other currency


def propose_allocations(
    group: Group,
    me: int,
    rates: Mapping[str, Rate],
    *,
    payer: int,
    amount: Decimal,
    currency: str,
    day: date,
    covers: Sequence[int] = (),
    payment_id: int | None = None,
) -> Proposal:
    """The default allocations of a payment from `payer` to the user that also covers `covers`
    (in the order they were checked): first everything the payer owed the user as of the
    payment's (day, id) position (`payment_id` None: a new one, after every payment of that
    day; the payment itself never counts), then each other person up to what they owe at that
    point, every claim converted to the payment's currency at its month's rate (`convert`; a
    claim without a rate is not counted). What is left stays on the payer. A written-off person
    still owes what they owe here: checking them says they did pay after all.

    Unattributed payments before that position lowered what the group owes as a whole, not any
    person's balance: the others together get at most what the group still owes after them,
    less the payer's own part (so the proposal never covers what was already paid)."""
    book = _open_book(group, me)
    position = (day, payment_id if payment_id is not None else float("inf"))
    earlier = [
        p for p in _ordered_payments(group) if p.id != payment_id and (p.day, p.id) < position
    ]
    for payment in earlier:
        _apply_attributed(payment, me, book.to_me, book.from_me, rates)
    still = _owed_after_unattributed(book, me, earlier, currency, day, rates)
    people = [payer, *(c for c in dict.fromkeys(covers) if c not in (payer, me))]
    owed: dict[int, Decimal] = {}
    foreign = False
    for person in people:
        claims = book.to_me.get(person)
        total = _ZERO
        for slot, value in (
            [] if claims is None else zip(claims.currencies, claims.remaining, strict=True)
        ):
            if value <= 0:
                continue
            foreign = foreign or slot != currency
            converted = convert(value, slot, currency, day, rates)
            total += converted or _ZERO
        owed[person] = total
    left = amount
    cap = max(_ZERO, still - owed[payer])
    parts: list[tuple[int, Decimal]] = []
    for person in people:
        part = min(left, owed[person]) if person == payer else min(left, owed[person], cap)
        left -= part
        if person != payer:
            cap -= part
        parts.append((person, part))
    parts[0] = (payer, parts[0][1] + left)
    rate = rate_for(rates, day.strftime("%Y-%m")) if foreign else None
    return Proposal(parts=tuple(parts), owed=owed, rate=rate)


def _owed_after_unattributed(
    book: _Book,
    me: int,
    earlier: Sequence[Payment],
    currency: str,
    day: date,
    rates: Mapping[str, Rate],
) -> Decimal:
    """What the group still owes the user (every person's open claims together) after the
    unattributed payments among `earlier`, in `currency` at `day`'s month's rate."""
    currencies = [e.currency for e in book.entries]
    aggregate = [
        sum((book.to_me[p].remaining[i] for p in book.others), _ZERO)
        for i in range(len(currencies))
    ]
    covered = [_ZERO] * len(currencies)
    for payment in earlier:
        if payment.from_contact is None and payment.to_contact == me:
            apply_fifo(
                payment.settles,
                payment.currency,
                payment.day,
                currencies,
                aggregate,
                covered,
                rates,
            )
    total = _ZERO
    for slot, value in zip(currencies, aggregate, strict=True):
        if value > 0:
            total += convert(value, slot, currency, day, rates) or _ZERO
    return total


@dataclass(frozen=True)
class CoverSuggestion:
    """ "Ana paid RD$ 74,340 too much in 3 payments and Beto owes US$ 1,244.20. Were those
    payments for Beto too?" """

    payments: tuple[Payment, ...]  # every payment of the payer with an open excess, oldest first
    payer: int
    excess: Decimal  # what the user owes the payer for them, in their currency
    covers: tuple[int, ...]  # who still owes the user
    owed: Mapping[str, Decimal]  # what they owe, by currency

    @property
    def payment(self) -> Payment:
        """The oldest one."""
        return self.payments[0]


def _qualifies(state: GroupState, me: int, payment: Payment, open_: Mapping[int, Decimal]) -> bool:
    """A payment another person made to the user, not answered "No", whose excess is still open
    (at least `LEFTOVER`)."""
    floor = LEFTOVER.get(payment.currency, _ZERO)
    return (
        payment.from_contact not in (None, me)
        and payment.to_contact == me
        and payment.id not in state.group.dismissed
        and open_.get(payment.id, _ZERO) >= floor
    )


def cover_suggestion(state: GroupState, me: int) -> CoverSuggestion | None:
    """A person X paid the user more than they owed (attributed payments whose excess is still
    open as a claim the other way, at least `LEFTOVER` each) while other members still owe the
    user. One suggestion per group: the payer of the oldest such payment, with **all** their
    payments that qualify (oldest first, in that payments' currency). Not suggested when:
    - the group is archived, or what the people owe is covered by unattributed payments (the
      group's `owed_to_me`, which already subtracts them, is empty; the amounts are capped by
      it too);
    - the payments were answered "No" (`Group.dismissed`, per payment), or the user does not
      still owe X at least `LEFTOVER` in that currency (`net`, without exchange leftovers);
    - the only people who owe are written off ("They won't pay me") or owe only an exchange
      leftover.
    Its excess is X's open excess over those payments, at most what the user owes X."""
    group = state.group
    if group.archived or not state.owed_to_me:
        return None
    open_ = dict(state.open_excess)
    written = {m.contact_id for m in group.members if m.written_off}
    candidates = [p for p in _ordered_payments(group) if _qualifies(state, me, p, open_)]
    for first in candidates:
        payer = first.from_contact
        assert payer is not None  # `_qualifies`
        currency = first.currency
        floor = LEFTOVER.get(currency, _ZERO)
        balance = state.person(payer)
        owing = _ZERO if balance is None else -balance.net.get(currency, _ZERO)
        if owing < floor:
            continue
        owed: dict[str, Decimal] = {}
        people = []
        for member in group.members:
            person = state.person(member.contact_id)
            if member.contact_id in (me, payer, *written) or person is None:
                continue
            positive = {c: v for c, v in person.net.items() if v > 0}
            if positive:
                people.append(member.contact_id)
                for code, value in positive.items():
                    owed[code] = owed.get(code, _ZERO) + value
        # What unattributed payments covered is not owed any more (`owed_to_me` subtracts it).
        owed = {
            c: min(v, state.owed_to_me.get(c, _ZERO))
            for c, v in owed.items()
            if state.owed_to_me.get(c, _ZERO) > 0
        }
        if not people or not owed:
            continue
        payments = tuple(
            p for p in candidates if p.from_contact == payer and p.currency == currency
        )
        total = sum((open_[p.id] for p in payments), _ZERO)
        return CoverSuggestion(
            payments, payer, min(total, owing), tuple(people), dict(sorted(owed.items()))
        )
    return None


@dataclass(frozen=True)
class PlannedPayment:
    payment: Payment
    proposal: Proposal


@dataclass(frozen=True)
class CoverPlan:
    """What "Yes" proposes for a suggestion: each payment's allocations, in order, and the
    group's balances once they are all applied."""

    payments: tuple[PlannedPayment, ...]
    after: GroupState


def with_allocations(group: Group, payment_id: int, parts: Sequence[tuple[int, Decimal]]) -> Group:
    """The group with one payment's allocations replaced (zero parts left out)."""
    allocations = tuple(Allocation(c, v) for c, v in parts if v > 0)
    return replace(
        group,
        payments=tuple(
            replace(p, allocations=allocations) if p.id == payment_id else p for p in group.payments
        ),
    )


def propose_cover(
    group: Group, me: int, rates: Mapping[str, Rate], found: CoverSuggestion
) -> CoverPlan:
    """Each payment of the suggestion proposed in order (`propose_allocations` at its own
    position, over what it settles), the people it already covers first and then the
    suggested ones; each proposal is applied before the next one is made, so a later payment
    covers only what the earlier ones left."""
    current = group
    planned = []
    for payment in found.payments:
        already = [
            a.contact_id for a in payment.allocations if a.contact_id != payment.from_contact
        ]
        proposal = propose_allocations(
            current,
            me,
            rates,
            payer=found.payer,
            amount=payment.settles,
            currency=payment.currency,
            day=payment.day,
            covers=list(dict.fromkeys([*already, *found.covers])),
            payment_id=payment.id,
        )
        current = with_allocations(current, payment.id, proposal.parts)
        planned.append(PlannedPayment(payment, proposal))
    return CoverPlan(tuple(planned), group_state(current, me, rates))


def approx_total(
    owed: Mapping[str, Decimal],
    owing: Mapping[str, Decimal],
    rates: Mapping[str, Rate],
    today: date,
) -> tuple[str, Decimal] | None:
    """ "In total ≈": what is owed to the user minus what the user owes, in one currency, when
    they come in more than one. Converted at `today`'s month's rate (the closest previous one);
    into the currency whose side is larger once converted (RD$ on a tie). None: one currency
    only, or no rate. Positive: owed to the user."""
    values: dict[str, Decimal] = {}
    for currency, value in owed.items():
        values[currency] = values.get(currency, _ZERO) + value
    for currency, value in owing.items():
        values[currency] = values.get(currency, _ZERO) - value
    present = {c for c, v in (*owed.items(), *owing.items()) if v != 0}
    if len(present) < 2:
        return None
    in_dop: dict[str, Decimal] = {}
    for currency in present:
        sides = abs(owed.get(currency, _ZERO)) + abs(owing.get(currency, _ZERO))
        converted = convert(sides, currency, "DOP", today, rates)
        if converted is None:
            return None
        in_dop[currency] = converted
    target = max(sorted(present), key=lambda c: (in_dop[c], c == "DOP"))
    total = _ZERO
    for currency in present:
        converted = convert(values.get(currency, _ZERO), currency, target, today, rates)
        if converted is None:
            return None
        total += converted
    return target, total
