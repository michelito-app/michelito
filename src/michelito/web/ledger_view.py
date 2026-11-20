"""Shared (the ledger) for the web: the home (people and groups), a group's page and a person,
built from `ledger.group_state` with the user's transactions next to what they reconcile."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from michelito.analysis import ledger, ledger_suggest
from michelito.analysis.ledger import GroupState, Ledger
from michelito.analysis.links import Links
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from michelito.web import links as links_view
from michelito.web.ledger_schemas import (
    AllocationOut,
    BankNameOut,
    ContactOut,
    ContactsOut,
    EffectOut,
    EntryOut,
    GroupOut,
    GroupRowOut,
    MemberOut,
    PaymentOut,
    PersonGroupOut,
    PersonOut,
    SharedHomeOut,
    SplitOut,
    SuggestionOut,
    TotalOut,
    money,
)
from michelito.web.schemas import LinkedTxOut, to_cents

_ZERO = Decimal(0)


@dataclass(frozen=True)
class Book:
    """Everything a Shared request needs, computed once."""

    ledger: Ledger
    states: Mapping[int, GroupState]
    movements: Sequence[Movement]
    links: Links
    labels: Mapping[str, str]
    rates: Mapping[str, Rate]
    banks: frozenset[str]

    def tx(self, fingerprint: str | None) -> LinkedTxOut | None:
        if fingerprint is None:
            return None
        move = next((m for m in self.movements if m.fingerprint == fingerprint), None)
        return None if move is None else LinkedTxOut.of(links_view.linked_tx(move, self.labels))

    def name(self, contact_id: int | None) -> str:
        return self.ledger.name(contact_id)


def _contact(contact: ledger.Contact) -> ContactOut:
    return ContactOut(
        id=contact.id, name=contact.name, is_me=contact.is_me, aliases=list(contact.aliases)
    )


def contacts(book: Book) -> ContactsOut:
    found = sorted(book.ledger.contacts.values(), key=lambda c: (not c.is_me, c.name.casefold()))
    payers: dict[int, date] = {}
    for group in book.ledger.groups:
        for entry in group.entries:
            if entry.paid_by != book.ledger.me:
                payers[entry.paid_by] = max(payers.get(entry.paid_by, date.min), entry.day)
    return ContactsOut(
        contacts=[_contact(c) for c in found],
        bank_names=[
            BankNameOut(name=b.name, raw=b.raw, count=b.count, last_day=b.last_day.isoformat())
            for b in ledger_suggest.bank_names(book.movements, book.ledger)
        ],
        recent_payers=sorted(payers, key=lambda c: payers[c], reverse=True),
    )


def person(book: Book, total: ledger.PersonTotal) -> PersonOut:
    groups = {g.id: g for g in book.ledger.groups}
    rows = []
    for group_id, values in total.by_group:
        group = groups[group_id]
        member = group.member(total.contact.id)
        rows.append(
            PersonGroupOut(
                group_id=group_id,
                group_name=group.name,
                archived=group.archived,
                balance=money(values),
                written_off=member is not None and member.written_off,
            )
        )
    return PersonOut(
        id=total.contact.id,
        name=total.contact.name,
        aliases=list(total.contact.aliases),
        balance=money(total.net),
        group_count=len(total.groups),
        groups=rows,
    )


def home(book: Book, today: date) -> SharedHomeOut:
    people = ledger.people(book.ledger, book.states)
    groups = sorted(
        book.ledger.groups,
        key=lambda g: (g.archived, -(_last(book, g) or date.min).toordinal(), -g.id),
    )
    rows = [
        GroupRowOut(
            id=g.id,
            name=g.name,
            archived=g.archived,
            balance=money(book.states[g.id].net),
            owed_to_me=money(book.states[g.id].owed_to_me),
            i_owe=money(book.states[g.id].i_owe),
            people=[book.name(m.contact_id) for m in g.members if m.contact_id != book.ledger.me],
            last_day=None if (last := _last(book, g)) is None else last.isoformat(),
            unattributed=len(book.states[g.id].unattributed),
        )
        for g in groups
    ]
    totals = ledger.net_totals(s for s in book.states.values() if not s.group.archived)
    suggestions: list[SuggestionOut] = []
    if not book.ledger.groups:
        suggestions = [
            SuggestionOut(**LinkedTxOut.of(links_view.linked_tx(m, book.labels)).model_dump())
            for m in ledger_suggest.empty_suggestions(book.movements, book.links, today, book.rates)
        ]
    return SharedHomeOut(
        totals=[
            TotalOut(currency=c, owed_to_me_cents=to_cents(owed), i_owe_cents=to_cents(owing))
            for c, (owed, owing) in totals.items()
            if to_cents(owed) or to_cents(owing)
        ],
        people=[person(book, p) for p in people],
        groups=rows,
        review_people=book.ledger.review_people,
        suggestions=suggestions,
    )


def _last(book: Book, group: ledger.Group) -> date | None:
    return book.states[group.id].last_activity


def _effect(item: ledger.EntryState) -> EffectOut:
    if item.paid_by_me:
        lent = item.owed_to_me
        return EffectOut(kind="lent" if lent > 0 else "none", cents=to_cents(lent))
    owe = item.i_owe
    return EffectOut(kind="owe" if owe > 0 else "none", cents=to_cents(owe))


def entry_out(book: Book, item: ledger.EntryState) -> EntryOut:
    entry = item.entry
    me = book.ledger.me
    return EntryOut(
        id=entry.id,
        day=entry.day.isoformat(),
        description=entry.description,
        amount_cents=to_cents(entry.amount),
        currency=entry.currency,
        paid_by=entry.paid_by,
        paid_by_name=book.name(entry.paid_by),
        paid_by_me=entry.paid_by == me,
        category_id=entry.category_id,
        split=entry.split_mode,
        splits=[
            SplitOut(
                contact_id=s.contact_id,
                name=book.name(s.contact_id),
                is_me=s.contact_id == me,
                cents=to_cents(s.share),
                parts=s.parts if entry.split_mode == "parts" else None,
            )
            for s in entry.splits
        ],
        effect=_effect(item),
        my_share_cents=to_cents(item.my_share),
        pending_cents=to_cents(item.pending),
        written_off_cents=to_cents(item.written_off),
        debt_pending_cents=to_cents(item.debt_pending),
        transaction=book.tx(entry.fingerprint),
    )


def payment_out(book: Book, state: ledger.PaymentState) -> PaymentOut:
    payment = state.payment
    me = book.ledger.me
    difference = payment.difference
    return PaymentOut(
        id=payment.id,
        day=payment.day.isoformat(),
        from_contact=payment.from_contact,
        from_name=book.name(payment.from_contact),
        to_contact=payment.to_contact,
        to_name=book.name(payment.to_contact),
        from_me=payment.from_contact == me,
        to_me=payment.to_contact == me,
        amount_cents=to_cents(payment.amount),
        currency=payment.currency,
        sent_cents=None if payment.sent is None else to_cents(payment.sent),
        difference_cents=None if difference is None else to_cents(difference),
        accepted=payment.accepted,
        note=payment.note,
        excess_cents=to_cents(state.excess),
        unconverted=state.unconverted,
        transaction=book.tx(payment.fingerprint),
        allocations=[
            AllocationOut(
                contact_id=contact,
                name=book.name(contact),
                is_me=contact == me,
                cents=to_cents(value),
            )
            for contact, value in payment.parts_for(me)
        ],
    )


def group_out(book: Book, group_id: int) -> GroupOut | None:
    group = book.ledger.group(group_id)
    state = book.states.get(group_id)
    if group is None or state is None:
        return None
    me = book.ledger.me
    members = sorted(group.members, key=lambda m: m.contact_id != me)
    timeline: list[tuple[date, int, int, EntryOut | PaymentOut]] = [
        (e.day, 0, e.entry.id, entry_out(book, e)) for e in state.entries
    ]
    timeline.extend((p.payment.day, 1, p.payment.id, payment_out(book, p)) for p in state.payments)
    timeline.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return GroupOut(
        id=group.id,
        name=group.name,
        archived=group.archived,
        category_id=group.category_id,
        members=[_member(book, state, m) for m in members],
        balance=money(state.net),
        owed_to_me=money(state.owed_to_me),
        i_owe=money(state.i_owe),
        excess=money(state.excess),
        unattributed=[payment_out(book, p) for p in state.unattributed],
        timeline=[item for _, _, _, item in timeline],
    )


def _member(book: Book, state: ledger.GroupState, member: ledger.Member) -> MemberOut:
    balance = state.person(member.contact_id)
    return MemberOut(
        id=member.contact_id,
        name=book.name(member.contact_id),
        is_me=member.contact_id == book.ledger.me,
        written_off=member.written_off,
        balance=[] if balance is None else money(balance.net),
    )


def person_out(book: Book, contact_id: int) -> PersonOut | None:
    total = next(
        (p for p in ledger.people(book.ledger, book.states) if p.contact.id == contact_id), None
    )
    return None if total is None else person(book, total)
