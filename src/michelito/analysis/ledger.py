"""Shared ledger (schema 19): groups of people, expenses with per-person splits and payments.

The ledger lives apart from the transactions (`ledger_store`): a group has members (global
contacts; the user is the contact with `is_me`), entries (an expense: who paid, amount,
currency, day, description, category and each person's share, in integer cents) and payments
(from whom to whom, what the receiver got and, optionally, what was sent). The personal
database only links transactions to an entry or a payment (`ledger_links`).

Everything here is from the user's point of view: what each person owes the user and what the
user owes each person. Debts between two other people are not tracked (no "simplify debts").

Splits (`equal_split`, `parts_split`, `exact_shortfall`): an equal split divides the cents among
the checked people and the leftover cent(s) go to the payer (or, when the payer is not among
them, to the first person); a split by parts gives each person amount x parts / total parts,
rounded down to the cent, with the leftover cent(s) by the same rule; an exact split must add up
to the amount. `resplit_without` takes one person out of an entry keeping its mode (see there).

Balances (`group_state`), per group:
1. Claims: for each entry the user paid, each other person owes their share; for each entry
   another person paid, the user owes that person their own share.
2. Attributed payments (in (day, id) order) settle, for each person they are for
   (`Payment.parts_for`: one payment can be "on behalf of others"), the claims of that pair
   **from the oldest entry to the newest** (FIFO); a payment in another currency is converted
   at the rate of the payment's month (`convert`) and what is left goes back to its currency at
   that same rate and moves on. Without a rate, the rest does not count (`unconverted`). What
   is left after settling everything is not lost: see below.
   What an attributed payment brings beyond what that pair owed (a payment against the
   balance, or more than the balance) is not lost: it becomes a claim the other way (the
   receiver now owes the payer that rest, in the payment's currency).
3. Unattributed payments to the user ("unassigned") then settle, FIFO, what is left of the
   group's claims as a whole: they lower what the group owes the user, not any person's
   balance (what is left of them is excess).
4. "They won't pay me" is per person in a group (`Member.written_off`): what that person
   still owes goes back to the user's expense (in each entry's month). Unattributed payments
   cover first what the people not written off owe.
5. Exchange leftovers (`PersonBalance.leftover`, schema 22): what is left with a person in one
   currency, below `LEFTOVER` (RD$ 50 or US$ 1), when **every** claim of that currency still
   open with them (both ways) was touched by a payment in the other currency (or is the rest
   of one), is conversion rounding: those claims count as settled right after the attributed
   payments (`_settle_leftover`), so neither `PersonBalance.net`, the entries' pending, the
   totals, `has_pending`, Pending, "To review" nor `approx_total` count it; it shows as
   "settled (exchange difference)" and the raw figure is `raw_net`. An untouched claim in that
   currency (a new expense, say) is a real debt: then nothing of that currency is a leftover.
   It can be turned off per person in a group (`Member.leftover_settled`). A written-off
   person already owes nothing (rule 4), so for them it only applies to what the user owes
   them.

Allocations proposed for a payment on behalf of several people
(`ledger_cover.propose_allocations`): first everything the payer owed the receiver as of the
payment's (day, id) position, then each other person in the order given (the order they were
checked), each up to what they owe at that point, converted at the payment month's rate; what
is left stays on the payer (rule 2 turns it into a claim the other way).
`ledger_cover.cover_suggestion` proposes covering someone with a payment whose excess is still
open (see there).

The total line (`ledger_cover.approx_total`): balances in two currencies stay apart; one line
"in total ≈" converts them at the current month's rate (the closest previous month's when
missing; no line without a rate) into the currency of the larger side.

What counts as the user's spending for an entry (`EntryState.counted`): their share plus what
was written off when they paid; their share when someone else paid (an accrual: it counts in
the entry's month even before they pay that person back).

The amount a payment settles (`Payment.settles`) is what the receiver got; if what was sent is
known and differs, the difference stays pending on the sender until someone accepts it
(`accepted`: then it settles what was sent).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from functools import cached_property
from typing import Literal

from michelito.analysis.rates import Rate, rate_for

SplitMode = Literal["equal", "exact", "parts"]
SPLIT_MODES: tuple[SplitMode, ...] = ("equal", "exact", "parts")
CURRENCIES = ("DOP", "USD")
_CENT = Decimal("0.01")
_ZERO = Decimal(0)
_NO_RATES: Mapping[str, Rate] = {}
# Below this, what was paid in excess is conversion rounding: neither excess nor warning.
MIN_EXCESS = {"DOP": Decimal(1), "USD": Decimal("0.05")}
# Below this, what is left with a person after a converted payment is an exchange leftover.
LEFTOVER = {"DOP": Decimal(50), "USD": Decimal(1)}


@dataclass(frozen=True)
class Contact:
    id: int
    name: str
    is_me: bool = False
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Split:
    contact_id: int
    share: Decimal  # in the entry's currency
    parts: int | None = None  # a split by parts: this person's number of parts


@dataclass(frozen=True)
class Entry:
    id: int
    group_id: int
    paid_by: int
    amount: Decimal
    currency: str
    day: date
    description: str
    splits: tuple[Split, ...]
    split_mode: SplitMode = "exact"
    category_id: int | None = None
    fingerprint: str | None = None  # the linked transaction (only when the user paid)

    def share_of(self, contact_id: int) -> Decimal:
        return sum((s.share for s in self.splits if s.contact_id == contact_id), _ZERO)

    @property
    def people(self) -> tuple[int, ...]:
        return tuple(s.contact_id for s in self.splits)


@dataclass(frozen=True)
class Allocation:
    """Who a payment is for: the person whose balance with the user it settles, and how much."""

    contact_id: int
    amount: Decimal  # in the payment's currency


def fit_allocations(
    given: Sequence[tuple[int, Decimal]], principal: int, total: Decimal
) -> tuple[tuple[int, Decimal], ...]:
    """Allocations (person, amount) made to add up to `total`, the one rule for every mismatch
    (the bank's amount linked later or at once, a difference accepted): what is more goes to
    the principal's own allocation (the sender's: who sent it, and on whom a difference stays
    pending); what is less comes off the principal first and then off the others in order,
    never below zero. Zero amounts are left out; none given: all of it is the principal's."""
    found = [(c, v) for c, v in given if v > 0]
    if not found:
        return ((principal, total),) if total > 0 else ()
    if principal not in (c for c, _ in found):
        found.insert(0, (principal, _ZERO))
    else:
        found.sort(key=lambda item: item[0] != principal)
    delta = total - sum((v for _, v in found), _ZERO)
    fitted: list[tuple[int, Decimal]] = []
    for contact, value in found:
        if delta >= 0:
            value, delta = value + delta, _ZERO
        else:
            taken = min(value, -delta)
            value, delta = value - taken, delta + taken
        fitted.append((contact, value))
    return tuple((c, v) for c, v in fitted if v > 0)


@dataclass(frozen=True)
class Payment:
    id: int
    group_id: int
    from_contact: int | None  # None: unattributed ("unassigned")
    to_contact: int
    amount: Decimal  # what the receiver got, in `currency`
    currency: str
    day: date
    sent: Decimal | None = None  # what was sent, when known (same currency)
    accepted: bool = False  # "Accept difference": it settles what was sent
    note: str = ""
    fingerprint: str | None = None  # the linked transaction
    # Who it is for (they add up to `amount` when recorded). Empty: all of it for the other end.
    allocations: tuple[Allocation, ...] = ()

    def principal(self, me: int) -> int | None:
        """The person (not the user) at the other end: who paid the user, or who the user paid
        (None: unattributed or between two other people)."""
        if self.from_contact is None:
            return None
        if self.to_contact == me:
            return self.from_contact
        return self.to_contact if self.from_contact == me else None

    def parts_for(self, me: int) -> tuple[tuple[int, Decimal], ...]:
        """(person, amount) this payment settles with each person, adding up to `settles`
        (`fit_allocations`). Without allocations, all of it is for the principal."""
        principal = self.principal(me)
        if principal is None:
            return ()
        given = [(a.contact_id, a.amount) for a in self.allocations]
        return fit_allocations(given, principal, self.settles)

    @property
    def settles(self) -> Decimal:
        if self.accepted and self.sent is not None:
            return self.sent
        return self.amount

    @property
    def difference(self) -> Decimal | None:
        """What was sent minus what was received (None: unknown or equal)."""
        if self.sent is None or self.sent == self.amount:
            return None
        return self.sent - self.amount


@dataclass(frozen=True)
class Member:
    contact_id: int
    written_off: bool = False  # "They won't pay me"
    leftover_settled: bool = True  # exchange leftovers count as settled (schema 22)


@dataclass(frozen=True)
class Group:
    id: int
    name: str
    members: tuple[Member, ...]
    entries: tuple[Entry, ...] = ()
    payments: tuple[Payment, ...] = ()
    category_id: int | None = None
    archived: bool = False
    # Payments whose "Was it for someone else too?" was answered "No" (schema 22).
    dismissed: frozenset[int] = frozenset()

    def member(self, contact_id: int) -> Member | None:
        return next((m for m in self.members if m.contact_id == contact_id), None)

    def entry(self, entry_id: int) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def payment(self, payment_id: int) -> Payment | None:
        return next((p for p in self.payments if p.id == payment_id), None)


@dataclass(frozen=True)
class LinkRef:
    """A transaction linked to the ledger: to an entry or to a payment of a group."""

    group_id: int
    entry_id: int | None = None
    payment_id: int | None = None


@dataclass(frozen=True)
class Ledger:
    me: int
    contacts: Mapping[int, Contact] = field(default_factory=dict)
    groups: tuple[Group, ...] = ()
    review_people: bool = False  # "Review your people" after the migration

    def group(self, group_id: int) -> Group | None:
        return next((g for g in self.groups if g.id == group_id), None)

    @cached_property
    def links(self) -> dict[str, LinkRef]:
        found: dict[str, LinkRef] = {}
        for group in self.groups:
            for entry in group.entries:
                if entry.fingerprint:
                    found[entry.fingerprint] = LinkRef(group.id, entry_id=entry.id)
            for payment in group.payments:
                if payment.fingerprint:
                    found[payment.fingerprint] = LinkRef(group.id, payment_id=payment.id)
        return found

    def name(self, contact_id: int | None) -> str:
        found = None if contact_id is None else self.contacts.get(contact_id)
        return "" if found is None else found.name

    def entry_for(self, fingerprint: str) -> tuple[Group, Entry] | None:
        ref = self.links.get(fingerprint)
        if ref is None or ref.entry_id is None:
            return None
        group = self.group(ref.group_id)
        entry = None if group is None else group.entry(ref.entry_id)
        return None if group is None or entry is None else (group, entry)

    def payment_for(self, fingerprint: str) -> tuple[Group, Payment] | None:
        ref = self.links.get(fingerprint)
        if ref is None or ref.payment_id is None:
            return None
        group = self.group(ref.group_id)
        payment = None if group is None else group.payment(ref.payment_id)
        return None if group is None or payment is None else (group, payment)


EMPTY = Ledger(me=0)


# --- Splits ---------------------------------------------------------------------------------


def to_cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def equal_split(amount: Decimal, people: Sequence[int], paid_by: int) -> tuple[Split, ...]:
    """`amount` divided in cents among `people` (in that order); the leftover cent(s) go to the
    payer, or to the first person when the payer is not among them."""
    if not people:
        raise ValueError("an equal split needs at least one person")
    chosen = list(dict.fromkeys(people))
    cents = to_cents(amount)
    base, left = divmod(cents, len(chosen))
    taker = paid_by if paid_by in chosen else chosen[0]
    return tuple(
        Split(person, Decimal(base + (left if person == taker else 0)).scaleb(-2))
        for person in chosen
    )


def exact_shortfall(amount: Decimal, shares: Iterable[Decimal]) -> Decimal:
    """What is missing (positive) or over (negative) for the exact shares to add up."""
    return amount - sum(shares, _ZERO)


def _weighted(cents: int, weights: Sequence[tuple[int, int]], paid_by: int) -> list[int]:
    """`cents` divided in proportion to the weights (person, weight), each rounded down to the
    cent; the leftover cent(s) go to the payer, or to the first person when the payer is not
    among them (the equal split's rule)."""
    total = sum(w for _, w in weights)
    found = [cents * w // total for _, w in weights]
    people = [p for p, _ in weights]
    taker = people.index(paid_by) if paid_by in people else 0
    found[taker] += cents - sum(found)
    return found


def parts_split(
    amount: Decimal, parts: Sequence[tuple[int, int]], paid_by: int
) -> tuple[Split, ...]:
    """`amount` divided by parts: each person (in that order) gets amount x parts / total parts,
    rounded down to the cent; the leftover cent(s) go to the payer (or the first person)."""
    chosen = list(dict(parts).items())
    if not chosen:
        raise ValueError("a split by parts needs at least one person")
    if any(count < 1 for _, count in chosen):
        raise ValueError("every person has at least one part")
    shares = _weighted(to_cents(amount), chosen, paid_by)
    return tuple(
        Split(person, Decimal(cents).scaleb(-2), count)
        for (person, count), cents in zip(chosen, shares, strict=True)
    )


def resplit_without(entry: Entry, contact_id: int) -> tuple[Split, ...]:
    """The entry's splits without `contact_id`, keeping its mode:

    - equal: equal among the rest (the cent rule);
    - parts: the rest keep their parts and the amount is divided again by parts;
    - exact: the person's amount goes to the rest in proportion to their amounts (a person with
      RD$ 600 of the RD$ 900 left gets two thirds of it), rounded down to the cent, with the
      leftover cent(s) to the payer (or the first person). An exact split stores no zero
      amounts, so a share of 0 is no share: that person is not in the split and gets nothing.

    When nobody (or, for exact, nobody with an amount) is left, all of it is the payer's: the
    expense becomes theirs alone, and what the person owed for it is gone. `resplit_preview`
    shows that before it happens."""
    rest = [s for s in entry.splits if s.contact_id != contact_id]
    if entry.split_mode == "equal" and rest:
        return equal_split(entry.amount, [s.contact_id for s in rest], entry.paid_by)
    if entry.split_mode == "parts" and rest:
        return parts_split(
            entry.amount, [(s.contact_id, s.parts or 1) for s in rest], entry.paid_by
        )
    weights = [(s.contact_id, to_cents(s.share)) for s in rest if s.share > 0]
    if not weights:
        return (Split(entry.paid_by, entry.amount),)
    shares = _weighted(to_cents(entry.amount), weights, entry.paid_by)
    return tuple(
        Split(person, Decimal(cents).scaleb(-2))
        for (person, _), cents in zip(weights, shares, strict=True)
    )


# --- Currency -------------------------------------------------------------------------------


def convert(
    amount: Decimal, source: str, target: str, day: date, rates: Mapping[str, Rate]
) -> Decimal | None:
    """`amount` in `source` converted to `target` at the rate of `day`'s month (or the closest
    previous month's), to the cent. Unchanged for the same currency; `None` without a rate."""
    if source == target:
        return amount
    rate = rate_for(rates, day.strftime("%Y-%m"))
    if rate is None or rate.value <= 0:
        return None
    if source == "DOP" and target == "USD":
        return (amount / rate.value).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    if source == "USD" and target == "DOP":
        return (amount * rate.value).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    return None


@dataclass
class _Applied:
    """What a payment did: what was left (its currency), whether it counted, whether an entry
    with something pending was skipped for lack of a rate and whether it settled a claim in the
    other currency (`converted`)."""

    left: Decimal
    counted: bool
    blocked: bool
    converted: bool = False


def apply_fifo(
    amount: Decimal,
    currency: str,
    day: date,
    currencies: Sequence[str],
    remaining: list[Decimal],
    applied: list[Decimal],
    rates: Mapping[str, Rate],
    touched: list[bool] | None = None,
) -> _Applied:
    """Applies a payment from the oldest claim to the newest (updates `remaining` and
    `applied`, one slot per entry in `currencies`; `touched` marks the slots a payment in the
    other currency settled part of). A claim without a rate to convert the payment is skipped:
    it goes on with the next ones."""
    left, counted, blocked, converted = amount, False, False, False
    for index, target in enumerate(currencies):
        if left <= 0:
            break
        if remaining[index] <= 0:
            continue
        value = convert(left, currency, target, day, rates)
        if value is None:
            blocked = True
            continue
        used = min(value, remaining[index])
        applied[index] += used
        remaining[index] -= used
        counted = counted or used > 0
        if used > 0 and target != currency:
            converted = True
            if touched is not None:
                touched[index] = True
        if used == value:
            return _Applied(_ZERO, counted, blocked, converted)
        back = convert(used, target, currency, day, rates) or _ZERO
        left = max(_ZERO, left - back)
    return _Applied(left, counted, blocked, converted)


# --- Balances -------------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryState:
    entry: Entry
    my_share: Decimal
    owed_to_me: Decimal  # the other people's shares when the user paid
    reimbursed: Decimal  # what payments to the user settled of `owed_to_me`
    pending: Decimal  # what is still owed to the user for this entry
    written_off: Decimal  # what went back to the user's expense ("They won't pay me")
    i_owe: Decimal  # the user's share when someone else paid
    paid_back: Decimal  # what the user's payments settled of `i_owe`
    paid_by_me: bool

    @property
    def currency(self) -> str:
        return self.entry.currency

    @property
    def day(self) -> date:
        return self.entry.day

    @property
    def debt_pending(self) -> Decimal:
        return self.i_owe - self.paid_back

    @property
    def counted(self) -> Decimal:
        """What counts as the user's spending."""
        return self.my_share + self.written_off


@dataclass(frozen=True)
class PaymentState:
    payment: Payment
    excess: Decimal = _ZERO  # an unattributed payment: left after settling everything
    turned: Decimal = _ZERO  # an attributed one: what became a claim the other way
    unconverted: bool = False  # part did not count: no rate
    uncounted: bool = False  # nothing counted for lack of a rate
    converted: bool = False  # it settled claims in the other currency (at its month's rate)


@dataclass(frozen=True)
class CurrencyTotals:
    """The group's figures in one currency (over the entries in that currency)."""

    currency: str
    share: Decimal  # the user's share
    reimbursed: Decimal  # paid back to the user
    pending: Decimal  # still owed to the user
    written_off: Decimal
    i_owe: Decimal  # what the user still owes


@dataclass(frozen=True)
class PersonBalance:
    """What one person owes the user (`owes_me`) and the user owes them (`i_owe`), by currency."""

    contact_id: int
    owes_me: tuple[tuple[str, Decimal], ...] = ()
    i_owe: tuple[tuple[str, Decimal], ...] = ()
    written_off: bool = False
    # Exchange leftovers taken as settled, by currency, signed like `net` (rule 5).
    leftover: tuple[tuple[str, Decimal], ...] = ()

    @property
    def net(self) -> dict[str, Decimal]:
        """Positive: they owe the user; negative: the user owes them (only non-zero). The
        exchange leftovers are already out (`group_state` settled those claims)."""
        found: dict[str, Decimal] = {}
        for currency, value in self.owes_me:
            found[currency] = found.get(currency, _ZERO) + value
        for currency, value in self.i_owe:
            found[currency] = found.get(currency, _ZERO) - value
        return {c: v for c, v in sorted(found.items()) if v != 0}

    @property
    def raw_net(self) -> dict[str, Decimal]:
        """`net` with the exchange leftovers still in."""
        found = self.net
        for currency, value in self.leftover:
            found[currency] = found.get(currency, _ZERO) + value
        return {c: v for c, v in sorted(found.items()) if v != 0}

    @property
    def settled(self) -> bool:
        return not self.net


@dataclass(frozen=True)
class GroupState:
    group: Group
    entries: tuple[EntryState, ...]  # oldest to newest
    payments: tuple[PaymentState, ...]  # in the order they are applied
    people: tuple[PersonBalance, ...]  # every member but the user
    # By currency: how much of the people's balances the unattributed payments covered.
    loose: tuple[tuple[str, Decimal], ...] = ()
    # Attributed payments whose excess (a claim the other way) is still open: payment id ->
    # what is left of it, in the payment's currency.
    open_excess: tuple[tuple[int, Decimal], ...] = ()

    @property
    def id(self) -> int:
        return self.group.id

    @property
    def totals(self) -> tuple[CurrencyTotals, ...]:
        found = []
        for currency in sorted({e.currency for e in self.entries}):
            mine = [e for e in self.entries if e.currency == currency]
            found.append(
                CurrencyTotals(
                    currency,
                    sum((e.my_share for e in mine if e.paid_by_me), _ZERO),
                    sum((e.reimbursed for e in mine), _ZERO),
                    sum((e.pending for e in mine), _ZERO),
                    sum((e.written_off for e in mine), _ZERO),
                    sum((e.debt_pending for e in mine), _ZERO),
                )
            )
        return tuple(found)

    @property
    def owed_to_me(self) -> dict[str, Decimal]:
        """What the people who owe the user add up to, by currency (each person's balance is
        netted on its own, never against another person's), less what unattributed payments
        covered. Only positive values."""
        found: dict[str, Decimal] = {}
        for person in self.people:
            for currency, value in person.net.items():
                if value > 0:
                    found[currency] = found.get(currency, _ZERO) + value
        for currency, value in self.loose:
            found[currency] = found.get(currency, _ZERO) - value
        return {c: v for c, v in sorted(found.items()) if v > 0}

    @property
    def i_owe(self) -> dict[str, Decimal]:
        """What the user owes the people they owe, by currency (only positive values)."""
        found: dict[str, Decimal] = {}
        for person in self.people:
            for currency, value in person.net.items():
                if value < 0:
                    found[currency] = found.get(currency, _ZERO) - value
        return {c: v for c, v in sorted(found.items()) if v > 0}

    @property
    def net(self) -> dict[str, Decimal]:
        """Owed to the user minus what the user owes, by currency (only non-zero). For display
        use `owed_to_me` and `i_owe`: this cancels different people against each other."""
        found = dict(self.owed_to_me)
        for currency, value in self.i_owe.items():
            found[currency] = found.get(currency, _ZERO) - value
        return {c: v for c, v in found.items() if v != 0}

    @property
    def has_pending(self) -> bool:
        return any(e.pending > 0 or e.debt_pending > 0 for e in self.entries)

    @property
    def unattributed(self) -> tuple[PaymentState, ...]:
        return tuple(p for p in self.payments if p.payment.from_contact is None)

    @property
    def excess(self) -> dict[str, Decimal]:
        found: dict[str, Decimal] = {}
        for state in self.payments:
            if state.excess > 0:
                currency = state.payment.currency
                found[currency] = found.get(currency, _ZERO) + state.excess
        return {c: v for c, v in found.items() if v >= MIN_EXCESS.get(c, _ZERO)}

    @property
    def uncounted(self) -> frozenset[str]:
        return frozenset(
            p.payment.fingerprint for p in self.payments if p.uncounted and p.payment.fingerprint
        )

    @property
    def last_activity(self) -> date | None:
        days = [e.day for e in self.entries] + [p.payment.day for p in self.payments]
        return max(days) if days else None

    def person(self, contact_id: int) -> PersonBalance | None:
        return next((p for p in self.people if p.contact_id == contact_id), None)

    def entry(self, entry_id: int) -> EntryState | None:
        return next((e for e in self.entries if e.entry.id == entry_id), None)


def _ordered_entries(group: Group) -> list[Entry]:
    return sorted(group.entries, key=lambda e: (e.day, e.id))


def _ordered_payments(group: Group) -> list[Payment]:
    return sorted(group.payments, key=lambda p: (p.day, p.id))


@dataclass
class _Claims:
    """Running claims of one direction with one person: one slot per entry, then one per
    payment that turned into a claim this way (`sources`: that payment's id). `touched`: a
    payment in the other currency settled part of the slot, or the slot is the rest of one."""

    currencies: list[str]
    remaining: list[Decimal]
    applied: list[Decimal]
    touched: list[bool]
    sources: list[int | None]

    @classmethod
    def empty(cls, currencies: Sequence[str]) -> _Claims:
        size = len(currencies)
        return cls(list(currencies), [_ZERO] * size, [_ZERO] * size, [False] * size, [None] * size)

    def add(
        self, currency: str, value: Decimal, touched: bool = False, source: int | None = None
    ) -> None:
        self.currencies.append(currency)
        self.remaining.append(value)
        self.applied.append(_ZERO)
        self.touched.append(touched)
        self.sources.append(source)

    def open_in(self, currency: str) -> list[int]:
        """The slots of `currency` with something still open."""
        return [
            i for i, (c, r) in enumerate(zip(self.currencies, self.remaining, strict=True))
            if c == currency and r > 0
        ]  # fmt: skip

    def settle(self, slots: Iterable[int]) -> None:
        """What is left in these slots counts as settled (an exchange leftover)."""
        for index in slots:
            self.applied[index] += self.remaining[index]
            self.remaining[index] = _ZERO


@dataclass
class _Book:
    """The claims of a group before any payment: entries oldest first, the people (every
    member but the user, and anyone an entry or payment names) and both directions."""

    entries: list[Entry]
    others: list[int]
    to_me: dict[int, _Claims]
    from_me: dict[int, _Claims]


def _open_book(group: Group, me: int) -> _Book:
    entries = _ordered_entries(group)
    currencies = [e.currency for e in entries]
    others = [m.contact_id for m in group.members if m.contact_id != me]
    for entry in entries:
        others.extend(c for c in (entry.paid_by, *entry.people) if c != me and c not in others)
    for payment in group.payments:
        for contact, _ in payment.parts_for(me):
            if contact != me and contact not in others:
                others.append(contact)
    to_me = {p: _Claims.empty(currencies) for p in others}
    from_me = {p: _Claims.empty(currencies) for p in others}
    for index, entry in enumerate(entries):
        if entry.paid_by == me:
            for split in entry.splits:
                if split.contact_id != me:
                    to_me[split.contact_id].remaining[index] += split.share
        else:
            from_me[entry.paid_by].remaining[index] += entry.share_of(me)
    return _Book(entries, others, to_me, from_me)


def group_state(group: Group, me: int, rates: Mapping[str, Rate] = _NO_RATES) -> GroupState:
    """The group's balances for the user (see the module docstring)."""
    book = _open_book(group, me)
    entries, others, to_me, from_me = book.entries, book.others, book.to_me, book.from_me
    currencies = [e.currency for e in entries]
    size = len(entries)
    owed = {p: list(c.remaining) for p, c in to_me.items()}
    debts = {p: list(c.remaining) for p, c in from_me.items()}
    results: dict[int, PaymentState] = {}
    payments = _ordered_payments(group)
    for payment in payments:
        state = _apply_attributed(payment, me, to_me, from_me, rates)
        if state is not None:
            results[payment.id] = state
    written = {m.contact_id for m in group.members if m.written_off}
    kept = {m.contact_id for m in group.members if not m.leftover_settled}
    leftovers = {
        p: _settle_leftover(to_me[p], from_me[p], p in written) for p in others if p not in kept
    }
    # Unattributed payments: what is left of the group's claims to the user as a whole.
    aggregate = [sum((to_me[p].remaining[i] for p in others), _ZERO) for i in range(size)]
    loose = [_ZERO] * size
    for payment in payments:
        if payment.from_contact is not None or payment.to_contact != me:
            continue
        done = apply_fifo(
            payment.settles, payment.currency, payment.day, currencies, aggregate, loose, rates
        )
        results[payment.id] = _payment_state(payment, done)
    states = tuple(
        _entry_state(index, entry, me, to_me, from_me, owed, debts, loose[index], written)
        for index, entry in enumerate(entries)
    )
    people = tuple(
        _person(p, to_me[p], from_me[p], p in written, leftovers.get(p, ())) for p in others
    )
    covered: dict[str, Decimal] = {}
    for index, item in enumerate(states):
        open_ = sum((c.remaining[index] for p, c in to_me.items() if p not in written), _ZERO)
        if open_ > item.pending:
            covered[item.currency] = covered.get(item.currency, _ZERO) + open_ - item.pending
    return GroupState(
        group=group,
        entries=states,
        payments=tuple(results.get(p.id, PaymentState(p)) for p in payments),
        people=people,
        loose=tuple(sorted(covered.items())),
        open_excess=_open_excess(to_me, from_me),
    )


def _open_excess(
    to_me: Mapping[int, _Claims], from_me: Mapping[int, _Claims]
) -> tuple[tuple[int, Decimal], ...]:
    found: dict[int, Decimal] = {}
    for claims in (*to_me.values(), *from_me.values()):
        for source, value in zip(claims.sources, claims.remaining, strict=True):
            if source is not None and value > 0:
                found[source] = found.get(source, _ZERO) + value
    return tuple(sorted(found.items()))


def _apply_attributed(
    payment: Payment,
    me: int,
    to_me: Mapping[int, _Claims],
    from_me: Mapping[int, _Claims],
    rates: Mapping[str, Rate],
) -> PaymentState | None:
    """Applies an attributed payment, person by person (`Payment.parts_for`): each part settles
    the claims of that person with the user and what is left of it becomes a claim the other
    way. None: unattributed or between other people."""
    parts = payment.parts_for(me)
    if not parts:
        return None
    turned, unconverted, counted, converted = _ZERO, False, False, False
    for contact, value in parts:
        if contact not in to_me:
            continue
        if payment.to_contact == me:
            claims, opposite = to_me[contact], from_me[contact]
        else:
            claims, opposite = from_me[contact], to_me[contact]
        done = apply_fifo(
            value,
            payment.currency,
            payment.day,
            claims.currencies,
            claims.remaining,
            claims.applied,
            rates,
            claims.touched,
        )
        counted = counted or done.counted
        converted = converted or done.converted
        if done.left > 0 and not done.blocked:
            opposite.add(payment.currency, done.left, touched=done.converted, source=payment.id)
            turned += done.left
        elif done.left > 0:
            unconverted = True
    return PaymentState(
        payment,
        turned=turned,
        unconverted=unconverted,
        uncounted=unconverted and not counted,
        converted=converted,
    )


def _payment_state(payment: Payment, done: _Applied) -> PaymentState:
    if done.left <= 0:
        return PaymentState(payment, converted=done.converted)
    if not done.blocked:
        return PaymentState(payment, excess=done.left, converted=done.converted)
    return PaymentState(
        payment, unconverted=True, uncounted=not done.counted, converted=done.converted
    )


def _entry_state(
    index: int,
    entry: Entry,
    me: int,
    to_me: Mapping[int, _Claims],
    from_me: Mapping[int, _Claims],
    owed: Mapping[int, list[Decimal]],
    debts: Mapping[int, list[Decimal]],
    loose: Decimal,
    written: frozenset[int] | set[int],
) -> EntryState:
    mine = entry.paid_by == me
    left = {p: c.remaining[index] for p, c in to_me.items()}
    open_ = sum((v for p, v in left.items() if p not in written), _ZERO)
    forgiven = sum((v for p, v in left.items() if p in written), _ZERO)
    # Unattributed payments cover first what the people not written off owe.
    written_off = max(_ZERO, forgiven - max(_ZERO, loose - open_))
    total_left = open_ + forgiven - loose
    owed_total = sum((v[index] for v in owed.values()), _ZERO)
    debt = sum((v[index] for v in debts.values()), _ZERO)
    paid_back = sum((c.applied[index] for c in from_me.values()), _ZERO)
    return EntryState(
        entry=entry,
        my_share=entry.share_of(me),
        owed_to_me=owed_total,
        reimbursed=owed_total - total_left,
        pending=total_left - written_off,
        written_off=written_off,
        i_owe=debt,
        paid_back=paid_back,
        paid_by_me=mine,
    )


def _sum_by(values: Iterable[tuple[str, Decimal]]) -> tuple[tuple[str, Decimal], ...]:
    found: dict[str, Decimal] = {}
    for currency, value in values:
        found[currency] = found.get(currency, _ZERO) + value
    return tuple(sorted((c, v) for c, v in found.items() if v > 0))


def _settle_leftover(
    to_me: _Claims, from_me: _Claims, written_off: bool
) -> tuple[tuple[str, Decimal], ...]:
    """Rule 5 for one person: in each currency where every claim still open (both ways; for a
    written-off person, only what the user owes them) was touched by a payment in the other
    currency and what they add up to is below `LEFTOVER`, those claims count as settled (moved
    to `applied`, so entries, totals and Pending agree with `net`). Returns what was settled,
    signed like `net`. An untouched claim in that currency is a real debt: nothing is settled."""
    found = []
    for currency in sorted(set(to_me.currencies) | set(from_me.currencies)):
        owed = [] if written_off else to_me.open_in(currency)
        owing = from_me.open_in(currency)
        if not owed and not owing:
            continue
        if not all(to_me.touched[i] for i in owed) or not all(from_me.touched[i] for i in owing):
            continue
        value = sum((to_me.remaining[i] for i in owed), _ZERO) - sum(
            (from_me.remaining[i] for i in owing), _ZERO
        )
        if value == 0 or abs(value) >= LEFTOVER.get(currency, _ZERO):
            continue
        to_me.settle(owed)
        from_me.settle(owing)
        found.append((currency, value))
    return tuple(found)


def _person(
    contact_id: int,
    to_me: _Claims,
    from_me: _Claims,
    written_off: bool,
    leftover: tuple[tuple[str, Decimal], ...] = (),
) -> PersonBalance:
    owes = () if written_off else _sum_by(zip(to_me.currencies, to_me.remaining, strict=True))
    return PersonBalance(
        contact_id=contact_id,
        owes_me=owes,
        i_owe=_sum_by(zip(from_me.currencies, from_me.remaining, strict=True)),
        written_off=written_off,
        leftover=leftover,
    )


def states(ledger: Ledger, rates: Mapping[str, Rate] = _NO_RATES) -> dict[int, GroupState]:
    """Every group's balances, by id."""
    return {g.id: group_state(g, ledger.me, rates) for g in ledger.groups}


# --- People across groups -------------------------------------------------------------------


@dataclass(frozen=True)
class PersonTotal:
    """One contact across every group: net balance by currency and the groups it is in."""

    contact: Contact
    net: dict[str, Decimal]
    groups: tuple[int, ...]  # the groups they are a member of (not archived first)
    by_group: tuple[tuple[int, dict[str, Decimal]], ...]  # each group's net with them

    @property
    def settled(self) -> bool:
        return not self.net


def people(ledger: Ledger, groups: Mapping[int, GroupState]) -> list[PersonTotal]:
    """Every contact but the user, with their balance across groups."""
    found = []
    for contact in ledger.contacts.values():
        if contact.is_me:
            continue
        net: dict[str, Decimal] = {}
        member_of: list[int] = []
        by_group: list[tuple[int, dict[str, Decimal]]] = []
        for group in ledger.groups:
            state = groups.get(group.id)
            balance = None if state is None else state.person(contact.id)
            if group.member(contact.id) is None and balance is None:
                continue
            member_of.append(group.id)
            values = {} if balance is None else balance.net
            by_group.append((group.id, values))
            for currency, value in values.items():
                net[currency] = net.get(currency, _ZERO) + value
        found.append(
            PersonTotal(
                contact=contact,
                net={c: v for c, v in sorted(net.items()) if v != 0},
                groups=tuple(member_of),
                by_group=tuple(by_group),
            )
        )
    return sorted(found, key=lambda p: p.contact.name.casefold())


def net_totals(groups: Iterable[GroupState]) -> dict[str, tuple[Decimal, Decimal]]:
    """Across groups, by currency: (owed to the user, what the user owes), adding up the
    groups' `owed_to_me` and `i_owe` apart (people never cancel each other)."""
    found: dict[str, tuple[Decimal, Decimal]] = {}
    for state in groups:
        for currency, value in state.owed_to_me.items():
            owed, owing = found.get(currency, (_ZERO, _ZERO))
            found[currency] = (owed + value, owing)
        for currency, value in state.i_owe.items():
            owed, owing = found.get(currency, (_ZERO, _ZERO))
            found[currency] = (owed, owing + value)
    return dict(sorted(found.items()))
