"""One person paying for several and payments in another currency (`analysis.ledger`, pure):
the default allocations (payer first, then the others in order, converted, with a shortfall),
the "Was that payment for B too?" suggestion, exchange leftovers and the "in total ≈" line.
Made-up people and amounts (`tests.ledger_cover_case`)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from michelito.analysis import ledger, ledger_cover
from michelito.analysis.ledger import Allocation, Entry, Member, Payment, equal_split
from michelito.analysis.rates import Rate
from tests import ledger_cover_case as case
from tests.ledger_cover_case import ANA, BETO, ME, RATES

D = Decimal
FEB_10 = date(2026, 2, 10)


def _state(group: ledger.Group) -> ledger.GroupState:
    return ledger.group_state(group, ME, RATES)


def _covered(*parts: tuple[int, str]) -> ledger.Group:
    """The case with Ana's last payment split as given."""
    payments = list(case.base_payments())
    last = payments[-1]
    payments[-1] = replace(last, allocations=tuple(Allocation(c, D(v)) for c, v in parts))
    return case.group(*payments)


class TestProposal:
    def test_payer_first_then_the_others_converted_at_the_payment_month(self) -> None:
        found = ledger_cover.propose_allocations(
            case.group(),
            ME,
            RATES,
            payer=ANA,
            amount=D("40820.00"),
            currency="DOP",
            day=FEB_10,
            covers=[BETO],
            payment_id=case.LAST,
        )
        # Ana still owed US$ 11.18 before that payment (RD$ 712.17 at 63.70); Beto US$ 629.31.
        assert found.owed == {ANA: D("712.17"), BETO: D("40087.05")}
        assert found.parts == ((ANA, D("732.95")), (BETO, D("40087.05")))
        assert sum(v for _, v in found.parts) == D("40820.00")
        assert found.rate is not None and found.rate.month_used == "2026-02"

    def test_not_enough_for_everyone_covers_in_the_order_checked(self) -> None:
        group = case.group()
        luis = 4
        members = (*group.members, Member(luis))
        entries = (
            *group.entries,
            Entry(3, 1, ME, D("3000"), "DOP", date(2025, 12, 12), "x",
                  equal_split(D("3000"), (ME, luis), ME), "equal"),
        )  # fmt: skip
        group = replace(group, members=members, entries=entries)
        found = ledger_cover.propose_allocations(
            group,
            ME,
            RATES,
            payer=ANA,
            amount=D("20000.00"),
            currency="DOP",
            day=FEB_10,
            covers=[luis, BETO],
            payment_id=case.LAST,
        )
        # Ana's own RD$ 712.17 first, then Luis' RD$ 1,500, then Beto gets what is left.
        assert found.parts == ((ANA, D("712.17")), (luis, D("1500.00")), (BETO, D("17787.83")))

    def test_a_new_payment_counts_every_payment_of_that_day_and_the_payer_keeps_the_rest(
        self,
    ) -> None:
        found = ledger_cover.propose_allocations(
            case.group(),
            ME,
            RATES,
            payer=BETO,
            amount=D("100.00"),
            currency="USD",
            day=FEB_10,
        )
        # After Ana's last payment (same day, earlier id) Beto still owes his US$ 629.31: a
        # payment of US$ 100 is all his.
        assert found.parts == ((BETO, D("100.00")),)
        assert found.rate is None  # same currency: nothing converted
        over = ledger_cover.propose_allocations(
            case.group(), ME, RATES, payer=BETO, amount=D("700"), currency="USD", day=FEB_10
        )
        assert over.parts == ((BETO, D("700")),)  # the rest stays on the payer (rule 2)

    def test_a_claim_without_a_rate_owes_nothing_here(self) -> None:
        found = ledger_cover.propose_allocations(
            case.group(),
            ME,
            {},
            payer=ANA,
            amount=D("1000"),
            currency="DOP",
            day=FEB_10,
            covers=[BETO],
        )
        assert found.parts == ((ANA, D("1000")), (BETO, D("0")))
        assert found.rate is None


class TestLeftover:
    def test_covering_beto_settles_him_and_leaves_ana_an_exchange_leftover(self) -> None:
        state = _state(_covered((ANA, "732.95"), (BETO, "40087.05")))
        ana, beto = state.person(ANA), state.person(BETO)
        assert ana is not None and beto is not None
        assert ana.raw_net == {"DOP": D("-20.78")} and ana.net == {}
        assert ana.leftover == (("DOP", D("-20.78")),) and ana.settled
        assert beto.net == {} and beto.leftover == ()
        assert state.owed_to_me == {} and state.i_owe == {}

    def test_at_the_threshold_it_counts(self) -> None:
        # RD$ 50.00 left with Ana is not "below RD$ 50": it stays pending.
        state = _state(_covered((ANA, "762.17"), (BETO, "40057.83")))
        ana = state.person(ANA)
        assert ana is not None and ana.leftover == ()
        assert ana.net == {"DOP": D("-50.00")}
        # Beto's US$ 0.46 left is below US$ 1 on a claim a RD$ payment settled: a leftover.
        beto = state.person(BETO)
        assert beto is not None and beto.net == {} and beto.leftover == (("USD", D("0.46")),)

    def test_only_after_a_converted_payment(self) -> None:
        dop = Entry(1, 1, ME, D("60"), "DOP", date(2026, 1, 2), "x",
                    equal_split(D("60"), (ME, ANA), ME), "equal")  # fmt: skip
        group = ledger.Group(1, "g", (Member(ME), Member(ANA)), entries=(dop,))
        state = ledger.group_state(group, ME, RATES)
        assert state.person(ANA).net == {"DOP": D("30")}  # type: ignore[union-attr]

    def test_the_toggle_turns_it_off_for_that_person(self) -> None:
        group = _covered((ANA, "732.95"), (BETO, "40087.05"))
        group = replace(
            group, members=(Member(ME), Member(ANA, leftover_settled=False), Member(BETO))
        )
        ana = _state(group).person(ANA)
        assert ana is not None and ana.leftover == () and ana.net == {"DOP": D("-20.78")}

    def test_a_written_off_person_owes_nothing_and_keeps_what_the_user_owes_them(self) -> None:
        group = _covered((ANA, "732.95"), (BETO, "40087.05"))
        group = replace(group, members=(Member(ME), Member(ANA, written_off=True), Member(BETO)))
        ana = _state(group).person(ANA)
        assert ana is not None and ana.written_off and ana.leftover == (("DOP", D("-20.78")),)


class TestCoverSuggestion:
    def test_the_case_is_suggested_on_the_payment_with_the_open_excess(self) -> None:
        found = ledger_cover.cover_suggestion(_state(case.group()), ME)
        assert found is not None
        assert found.payment.id == case.LAST and found.payer == ANA
        assert found.excess == D("40107.83") and found.covers == (BETO,)
        assert found.owed == {"USD": D("629.31")}

    def test_not_after_no_nor_once_covered(self) -> None:
        dismissed = case.group(dismissed=frozenset({case.LAST}))
        assert ledger_cover.cover_suggestion(_state(dismissed), ME) is None
        covered = _covered((ANA, "732.95"), (BETO, "40087.05"))
        assert ledger_cover.cover_suggestion(_state(covered), ME) is None

    def test_not_when_written_off_or_unattributed_payments_explain_it(self) -> None:
        written = case.group(members=(Member(ME), Member(ANA), Member(BETO, written_off=True)))
        assert ledger_cover.cover_suggestion(_state(written), ME) is None
        loose = Payment(9, 1, None, ME, D("700"), "USD", date(2026, 2, 12))
        explained = case.group(*case.base_payments(), loose)
        assert _state(explained).owed_to_me == {}
        assert ledger_cover.cover_suggestion(_state(explained), ME) is None

    def test_not_in_an_archived_group_nor_for_an_exchange_leftover(self) -> None:
        archived = replace(case.group(), archived=True)
        assert ledger_cover.cover_suggestion(_state(archived), ME) is None
        # Ana paid RD$ 30 too much (an exchange leftover): nothing to suggest.
        payments = list(case.base_payments())
        payments[-1] = replace(payments[-1], amount=D("742.17"))
        small = _state(case.group(*payments))
        assert small.person(ANA).net == {}  # type: ignore[union-attr]
        assert ledger_cover.cover_suggestion(small, ME) is None

    def test_every_payment_with_an_open_excess_oldest_first(self) -> None:
        extra = Payment(5, 1, ANA, ME, D("5000"), "DOP", date(2026, 2, 15))
        found = ledger_cover.cover_suggestion(_state(case.group(*case.base_payments(), extra)), ME)
        assert found is not None and [p.id for p in found.payments] == [case.LAST, 5]
        assert found.payment.id == case.LAST
        # What the user owes Ana over both: RD$ 40,107.83 + RD$ 5,000.
        assert found.excess == D("45107.83")


class TestApproxTotal:
    def test_two_currencies_in_the_larger_side(self) -> None:
        state = _state(case.group())
        found = ledger_cover.approx_total(state.owed_to_me, state.i_owe, RATES, date(2026, 2, 20))
        # US$ 629.31 x 63.70 = RD$ 40,087.05 owed; RD$ 40,107.83 owed by the user.
        assert found == ("DOP", D("-20.78"))
        usd = ledger_cover.approx_total(
            {"USD": D("100")}, {"DOP": D("637")}, RATES, date(2026, 2, 1)
        )
        assert usd == ("USD", D("90.00"))

    def test_one_currency_or_no_rate_gives_no_line(self) -> None:
        assert (
            ledger_cover.approx_total({"DOP": D("5")}, {"DOP": D("3")}, RATES, date(2026, 2, 1))
            is None
        )
        assert (
            ledger_cover.approx_total({"USD": D("1")}, {"DOP": D("3")}, {}, date(2026, 2, 1))
            is None
        )

    def test_the_closest_previous_month_when_the_current_one_is_missing(self) -> None:
        rates = {"2026-01": Rate(D("60"), "2026-01", "bcrd")}
        found = ledger_cover.approx_total(
            {"USD": D("10")}, {"DOP": D("100")}, rates, date(2026, 3, 5)
        )
        assert found == ("USD", D("8.33"))  # US$ 10 - RD$ 100 / 60 (January's rate)


def test_the_payment_detail_knows_it_was_converted() -> None:
    state = _state(case.group())
    assert all(p.converted for p in state.payments)
    same = Payment(7, 1, BETO, ME, D("10"), "USD", FEB_10)
    found = _state(case.group(*case.base_payments(), same))
    assert not next(p for p in found.payments if p.payment.id == 7).converted


def _probe(*extra: Entry) -> ledger.GroupState:
    """Ana owes US$ 100 and pays RD$ 6,345 at 63.70 (US$ 99.61): US$ 0.39 left on that claim."""
    hotel = Entry(1, 1, ME, D("200"), "USD", date(2026, 1, 5), "x",
                  equal_split(D("200"), (ME, ANA), ME), "equal")  # fmt: skip
    group = ledger.Group(
        1,
        "g",
        (Member(ME), Member(ANA)),
        entries=(hotel, *extra),
        payments=(Payment(1, 1, ANA, ME, D("6345"), "DOP", FEB_10),),
    )
    return ledger.group_state(group, ME, RATES)


class TestLeftoverEverywhere:
    def test_a_leftover_is_not_pending_in_entries_totals_or_has_pending(self) -> None:
        state = _probe()
        ana = state.person(ANA)
        assert ana is not None and ana.net == {} and ana.leftover == (("USD", D("0.39")),)
        assert ana.raw_net == {"USD": D("0.39")}
        assert state.entries[0].pending == 0
        assert state.entries[0].reimbursed == D("100")
        assert not state.has_pending
        assert [t.pending for t in state.totals] == [D("0")]
        assert state.owed_to_me == {}

    def test_an_untouched_claim_in_that_currency_is_a_real_debt(self) -> None:
        coffee = Entry(2, 1, ME, D("1.00"), "USD", date(2026, 2, 12), "x",
                       equal_split(D("1.00"), (ME, ANA), ME), "equal")  # fmt: skip
        state = _probe(coffee)
        ana = state.person(ANA)
        assert ana is not None and ana.leftover == ()
        assert ana.net == {"USD": D("0.89")}
        assert state.entries[1].pending == D("0.50") and state.has_pending


class TestUnattributed:
    """An unattributed US$ 300 on Feb 5 covers part of what the group owes (FIFO over its
    claims as a whole): proposals and the suggestion never count it as owed."""

    def _group(self) -> ledger.Group:
        loose = Payment(9, 1, None, ME, D("300"), "USD", date(2026, 2, 5))
        return case.group(*case.base_payments(), loose)

    def test_the_proposal_is_capped_by_what_is_still_owed(self) -> None:
        found = ledger_cover.propose_allocations(
            self._group(),
            ME,
            RATES,
            payer=ANA,
            amount=D("40820.00"),
            currency="DOP",
            day=FEB_10,
            covers=[BETO],
            payment_id=case.LAST,
        )
        # The group still owes US$ 340.49 after it (RD$ 21,689.21 at 63.70); RD$ 712.17 of that
        # is Ana's own, so the others get at most RD$ 20,977.04 (US$ 329.31, as the suggestion
        # says).
        assert dict(found.parts)[BETO] == D("20977.04")
        assert sum(v for _, v in found.parts) == D("40820.00")

    def test_the_suggestion_says_what_is_still_owed(self) -> None:
        state = _state(self._group())
        assert state.owed_to_me == {"USD": D("329.31")}
        found = ledger_cover.cover_suggestion(state, ME)
        assert found is not None and found.owed == {"USD": D("329.31")}
