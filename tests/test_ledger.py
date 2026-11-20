"""The shared ledger's math (`analysis.ledger`), without a database: splits and the cent rule,
balances in both directions, currencies, payments with a difference, unattributed payments and
"They won't pay me" per person. Made-up people and amounts."""

from datetime import date
from decimal import Decimal

import pytest

from michelito.analysis import ledger
from michelito.analysis.ledger import Contact, Entry, Group, Ledger, Member, Payment, Split
from michelito.analysis.rates import Rate

D = Decimal
ME, ANA, LUIS, ROSA = 1, 2, 3, 4
CONTACTS = {
    ME: Contact(ME, "me", is_me=True),
    ANA: Contact(ANA, "Ana Ficticia"),
    LUIS: Contact(LUIS, "Luis Inventado"),
    ROSA: Contact(ROSA, "Rosa Ficticia"),
}
RATES = {"2026-01": Rate(D("60"), "2026-01", "bcrd"), "2026-02": Rate(D("62"), "2026-02", "bcrd")}


def _entry(
    entry_id: int,
    amount: str,
    paid_by: int = ME,
    people: tuple[int, ...] = (ME, ANA, LUIS),
    day: str = "2026-01-10",
    currency: str = "DOP",
    shares: dict[int, str] | None = None,
) -> Entry:
    total = D(amount)
    splits = (
        tuple(Split(c, D(v)) for c, v in shares.items())
        if shares is not None
        else ledger.equal_split(total, people, paid_by)
    )
    return Entry(
        entry_id, 1, paid_by, total, currency, date.fromisoformat(day), "x", splits, "equal"
    )


def _pay(
    payment_id: int,
    amount: str,
    from_contact: int | None = ANA,
    to_contact: int = ME,
    day: str = "2026-01-20",
    currency: str = "DOP",
    sent: str | None = None,
    accepted: bool = False,
) -> Payment:
    return Payment(
        payment_id,
        1,
        from_contact,
        to_contact,
        D(amount),
        currency,
        date.fromisoformat(day),
        None if sent is None else D(sent),
        accepted,
    )


def _state(
    entries: tuple[Entry, ...],
    payments: tuple[Payment, ...] = (),
    written_off: tuple[int, ...] = (),
    people: tuple[int, ...] = (ANA, LUIS),
    rates: dict[str, Rate] | None = None,
) -> ledger.GroupState:
    members = (Member(ME), *(Member(p, p in written_off) for p in people))
    group = Group(1, "Trip", members, entries, payments)
    return ledger.group_state(group, ME, RATES if rates is None else rates)


def _net(state: ledger.GroupState, person: int) -> dict[str, Decimal]:
    found = state.person(person)
    assert found is not None
    return found.net


class TestSplits:
    def test_equal_split_gives_the_leftover_cents_to_the_payer(self) -> None:
        shares = ledger.equal_split(D("100.00"), [ANA, ME, LUIS], ME)
        assert [(s.contact_id, s.share) for s in shares] == [
            (ANA, D("33.33")),
            (ME, D("33.34")),
            (LUIS, D("33.33")),
        ]
        assert sum(s.share for s in shares) == D("100.00")

    def test_two_leftover_cents_both_go_to_the_payer(self) -> None:
        shares = ledger.equal_split(D("0.11"), [ME, ANA, LUIS], ANA)
        assert {s.contact_id: s.share for s in shares} == {
            ME: D("0.03"),
            ANA: D("0.05"),
            LUIS: D("0.03"),
        }

    def test_when_the_payer_is_not_in_the_split_the_first_takes_them(self) -> None:
        shares = ledger.equal_split(D("10.00"), [ANA, LUIS, ROSA], ME)
        assert [s.share for s in shares] == [D("3.34"), D("3.33"), D("3.33")]

    def test_repeated_people_count_once_and_nobody_is_an_error(self) -> None:
        assert len(ledger.equal_split(D(10), [ANA, ANA, ME], ME)) == 2
        with pytest.raises(ValueError):
            ledger.equal_split(D(10), [], ME)

    def test_exact_shortfall_says_what_is_missing_or_over(self) -> None:
        assert ledger.exact_shortfall(D(1000), [D(300), D(500)]) == D(200)
        assert ledger.exact_shortfall(D(1000), [D(700), D(500)]) == D(-200)
        assert ledger.exact_shortfall(D(1000), [D(500), D(500)]) == 0


class TestBalances:
    def test_what_others_owe_when_the_user_paid(self) -> None:
        state = _state((_entry(1, "3000"),))
        [item] = state.entries
        assert (item.my_share, item.owed_to_me, item.pending, item.counted) == (
            D(1000),
            D(2000),
            D(2000),
            D(1000),
        )
        assert _net(state, ANA) == {"DOP": D(1000)}
        assert _net(state, LUIS) == {"DOP": D(1000)}
        assert state.net == {"DOP": D(2000)}

    def test_what_the_user_owes_when_someone_else_paid(self) -> None:
        state = _state((_entry(1, "6000", paid_by=ANA),))
        [item] = state.entries
        assert (item.my_share, item.i_owe, item.counted, item.pending) == (
            D(2000),
            D(2000),
            D(2000),  # the user's share is spending (accrual)
            0,
        )
        assert _net(state, ANA) == {"DOP": D(-2000)}
        assert _net(state, LUIS) == {}  # Luis owes Ana: not the user's business
        assert state.net == {"DOP": D(-2000)}

    def test_both_directions_net_per_person(self) -> None:
        state = _state((_entry(1, "3000"), _entry(2, "1500", paid_by=ANA, day="2026-01-12")))
        assert _net(state, ANA) == {"DOP": D(500)}  # owes 1,000, is owed 500
        assert state.net == {"DOP": D(1500)}
        assert {t.currency: (t.pending, t.i_owe) for t in state.totals} == {
            "DOP": (D(2000), D(500))
        }

    def test_each_currency_apart(self) -> None:
        state = _state((_entry(1, "300", currency="USD"), _entry(2, "3000")))
        assert _net(state, ANA) == {"DOP": D(1000), "USD": D(100)}
        assert state.owed_to_me == {"DOP": D(2000), "USD": D(200)}

    def test_the_user_not_in_the_split_lends_everything(self) -> None:
        state = _state((_entry(1, "1000", people=(ANA,)),), people=(ANA,))
        [item] = state.entries
        assert (item.my_share, item.counted, item.pending) == (0, 0, D(1000))


class TestPayments:
    def test_a_payment_settles_the_oldest_entry_first(self) -> None:
        entries = (
            _entry(1, "300", people=(ME, ANA)),
            _entry(2, "600", people=(ME, ANA), day="2026-01-15"),
        )
        state = _state(entries, (_pay(1, "200"),), people=(ANA,))
        first, second = state.entries
        assert (first.reimbursed, first.pending) == (D(150), 0)
        assert (second.reimbursed, second.pending) == (D(50), D(250))
        assert _net(state, ANA) == {"DOP": D(250)}

    def test_a_partial_payment_leaves_the_rest_pending(self) -> None:
        state = _state((_entry(1, "3000"),), (_pay(1, "400"),))
        assert _net(state, ANA) == {"DOP": D(600)}
        assert _net(state, LUIS) == {"DOP": D(1000)}

    def test_paying_back_someone_who_paid(self) -> None:
        state = _state(
            (_entry(1, "6000", paid_by=ANA),), (_pay(1, "1500", from_contact=ME, to_contact=ANA),)
        )
        [item] = state.entries
        assert (item.paid_back, item.debt_pending) == (D(1500), D(500))
        assert _net(state, ANA) == {"DOP": D(-500)}

    def test_a_payment_in_another_currency_is_converted_at_its_month(self) -> None:
        # A US$ 100 hotel split in two; RD$ 1,240 back in February (at 62: US$ 20).
        state = _state(
            (_entry(1, "100", people=(ME, ANA), currency="USD"),),
            (_pay(1, "1240", day="2026-02-10"),),
            people=(ANA,),
        )
        assert _net(state, ANA) == {"USD": D(30)}

    def test_without_a_rate_the_payment_does_not_count(self) -> None:
        state = _state(
            (_entry(1, "100", people=(ME, ANA), currency="USD"),),
            (Payment(1, 1, ANA, ME, D(1240), "DOP", date(2026, 2, 10), fingerprint="credit"),),
            people=(ANA,),
            rates={},
        )
        assert _net(state, ANA) == {"USD": D(50)}
        [paid] = state.payments
        assert paid.unconverted and paid.uncounted
        assert state.uncounted == frozenset({"credit"})

    def test_paying_too_much_turns_the_rest_into_a_claim_the_other_way(self) -> None:
        state = _state((_entry(1, "200", people=(ME, ANA)),), (_pay(1, "150"),), people=(ANA,))
        assert _net(state, ANA) == {"DOP": D(-50)}  # now the user owes Ana 50
        assert (state.excess, state.payments[0].turned) == ({}, D(50))
        assert (state.owed_to_me, state.i_owe) == ({}, {"DOP": D(50)})
        # Paying her back settles it.
        back = _pay(2, "50", from_contact=ME, to_contact=ANA, day="2026-01-25")
        state = _state(state.group.entries, (*state.group.payments, back), people=(ANA,))
        assert _net(state, ANA) == {}

    def test_a_payment_against_the_balance_is_a_claim_the_other_way(self) -> None:
        # Ana paid the hotel and the user owes her; then she sends 300 more: the user owes 300
        # more, nothing is swallowed as a reimbursement.
        hotel = _entry(1, "600", paid_by=ANA, people=(ME, ANA))
        state = _state((hotel,), (_pay(1, "300"),), people=(ANA,))
        assert _net(state, ANA) == {"DOP": D(-600)}

    def test_unattributed_excess_stays_excess(self) -> None:
        state = _state(
            (_entry(1, "200", people=(ME, ANA)),),
            (_pay(1, "150", from_contact=None),),
            people=(ANA,),
        )
        assert state.excess == {"DOP": D(50)} and state.owed_to_me == {}

    def test_different_people_never_cancel_each_other(self) -> None:
        # Ana owes the user 100 and the user owes Luis 100: both show, nothing nets to zero.
        mine = _entry(1, "200", people=(ME, ANA))
        luis = _entry(2, "200", paid_by=LUIS, people=(ME, LUIS))
        state = _state((mine, luis))
        assert (state.owed_to_me, state.i_owe) == ({"DOP": D(100)}, {"DOP": D(100)})
        assert ledger.net_totals([state]) == {"DOP": (D(100), D(100))}

    def test_unattributed_payments_lower_only_the_owed_side(self) -> None:
        mine = _entry(1, "300", people=(ME, ANA, LUIS))
        rosa = _entry(2, "200", paid_by=ROSA, people=(ME, ROSA), day="2026-01-11")
        loose = _pay(1, "50", from_contact=None)
        state = _state((mine, rosa), (loose,), people=(ANA, LUIS, ROSA))
        assert (state.owed_to_me, state.i_owe) == ({"DOP": D(150)}, {"DOP": D(100)})

    def test_the_debt_goes_down_by_what_was_received(self) -> None:
        sent = _pay(1, "1200", sent="1250")
        state = _state((_entry(1, "3750"),), (sent,))
        assert sent.difference == D(50)
        assert _net(state, ANA) == {"DOP": D(50)}  # the difference is pending on the sender

    def test_accepting_the_difference_settles_what_was_sent(self) -> None:
        accepted = _pay(1, "1200", sent="1250", accepted=True)
        state = _state((_entry(1, "3750"),), (accepted,))
        assert accepted.settles == D(1250)
        assert _net(state, ANA) == {}

    def test_an_unattributed_payment_lowers_the_group_but_nobody_in_particular(self) -> None:
        state = _state((_entry(1, "3000"),), (_pay(1, "500", from_contact=None),))
        assert _net(state, ANA) == {"DOP": D(1000)}
        assert _net(state, LUIS) == {"DOP": D(1000)}
        assert state.net == {"DOP": D(1500)}
        [loose] = state.unattributed
        assert loose.payment.id == 1


class TestWrittenOff:
    def test_one_person_written_off_goes_back_to_the_users_expense(self) -> None:
        state = _state((_entry(1, "3000"),), written_off=(LUIS,))
        [item] = state.entries
        assert (item.written_off, item.pending, item.counted) == (D(1000), D(1000), D(2000))
        assert _net(state, LUIS) == {}
        assert _net(state, ANA) == {"DOP": D(1000)}

    def test_everyone_written_off(self) -> None:
        state = _state((_entry(1, "3000"),), (_pay(1, "400"),), written_off=(ANA, LUIS))
        [item] = state.entries
        assert (item.reimbursed, item.written_off, item.pending) == (D(400), D(1600), 0)
        assert state.net == {}

    def test_an_unattributed_payment_covers_first_who_was_not_written_off(self) -> None:
        state = _state(
            (_entry(1, "3000"),), (_pay(1, "500", from_contact=None),), written_off=(LUIS,)
        )
        [item] = state.entries
        # Ana owed 1,000 (500 covered by the loose payment), Luis's 1,000 is written off.
        assert (item.pending, item.written_off) == (D(500), D(1000))


class TestAcrossGroups:
    def test_people_and_totals(self) -> None:
        one = Group(1, "One", (Member(ME), Member(ANA)), (_entry(1, "1000", people=(ME, ANA)),))
        hotel = Entry(
            2,
            2,
            ANA,
            D(900),
            "DOP",
            date(2026, 1, 3),
            "Hotel",
            ledger.equal_split(D(900), [ME, ANA, LUIS], ANA),
        )
        two = Group(2, "Two", (Member(ME), Member(ANA), Member(LUIS)), (hotel,))
        book = Ledger(ME, CONTACTS, (one, two))
        states = ledger.states(book, RATES)
        people = {p.contact.id: p for p in ledger.people(book, states)}
        assert people[ANA].net == {"DOP": D(200)}  # 500 - 300
        assert people[ANA].groups == (1, 2)
        assert people[LUIS].settled and people[ROSA].groups == ()
        assert ledger.net_totals(states.values()) == {"DOP": (D(500), D(300))}

    def test_links_by_fingerprint(self) -> None:
        entry = Entry(1, 1, ME, D(10), "DOP", date(2026, 1, 1), "x", (), fingerprint="fp1")
        paid = Payment(1, 1, ANA, ME, D(5), "DOP", date(2026, 1, 2), fingerprint="fp2")
        book = Ledger(ME, CONTACTS, (Group(1, "G", (Member(ME),), (entry,), (paid,)),))
        assert book.entry_for("fp1") == (book.groups[0], entry)
        assert book.payment_for("fp2") == (book.groups[0], paid)
        assert book.entry_for("fp2") is None and book.payment_for("nope") is None
