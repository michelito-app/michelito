"""One person who paid for several in more than one payment (`analysis.ledger_cover`, pure): the
suggestion groups all of that payer's payments with an open excess, and the plan proposes each
one in order, payer first, each counting what the previous ones already covered. Made-up
figures, one payer for two in three payments (`tests.ledger_cover_case.spread_group`)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from michelito.analysis import ledger, ledger_cover
from michelito.analysis.ledger import Allocation
from tests import ledger_cover_case as case
from tests.ledger_cover_case import ANA, BETO, ME, SPREAD_RATES

D = Decimal


def _state(group: ledger.Group) -> ledger.GroupState:
    return ledger.group_state(group, ME, SPREAD_RATES)


def test_before_ana_is_owed_her_three_excesses_and_beto_still_owes() -> None:
    state = _state(case.spread_group())
    assert state.owed_to_me == {"USD": D("990.76")}
    assert set(state.i_owe) == {"DOP"}
    assert D("54600") < state.i_owe["DOP"] < D("54700")


def test_one_suggestion_for_all_her_payments_oldest_first() -> None:
    state = _state(case.spread_group())
    found = ledger_cover.cover_suggestion(state, ME)
    assert found is not None and found.payer == ANA and found.covers == (BETO,)
    assert [p.id for p in found.payments] == [11, 13, 14]
    assert found.excess == state.i_owe["DOP"]  # her total open excess
    assert found.owed == {"USD": D("990.76")}


def test_the_plan_proposes_each_payment_counting_the_previous_ones() -> None:
    group = case.spread_group()
    found = ledger_cover.cover_suggestion(_state(group), ME)
    assert found is not None
    plan = ledger_cover.propose_cover(group, ME, SPREAD_RATES, found)
    parts = [dict(p.proposal.parts) for p in plan.payments]
    # The first payment: Ana's own US$ 1,500.10 first, the rest of it for Beto.
    assert parts[0][ANA] + parts[0][BETO] == D("98000.00")
    assert D("88300") < parts[0][ANA] < D("88400")
    # The other two are all Beto's (he still owes more than all of it).
    assert parts[1] == {ANA: D("0"), BETO: D("20000.00")}
    assert parts[2] == {ANA: D("0"), BETO: D("25000.00")}
    after = plan.after
    assert after.i_owe == {}
    ana, beto = after.person(ANA), after.person(BETO)
    assert ana is not None and ana.net == {}
    assert beto is not None and set(beto.net) == {"USD"}
    assert D("62") < beto.net["USD"] < D("64")  # what is left of Beto's debt


def test_applying_the_plan_gives_its_balances() -> None:
    group = case.spread_group()
    found = ledger_cover.cover_suggestion(_state(group), ME)
    assert found is not None
    plan = ledger_cover.propose_cover(group, ME, SPREAD_RATES, found)
    chosen = {p.payment.id: p.proposal.parts for p in plan.payments}
    applied = replace(
        group,
        payments=tuple(
            replace(p, allocations=tuple(Allocation(c, v) for c, v in chosen[p.id] if v > 0))
            if p.id in chosen
            else p
            for p in group.payments
        ),
    )
    state = _state(applied)
    assert state.owed_to_me == plan.after.owed_to_me and state.i_owe == {}
    assert ledger_cover.cover_suggestion(state, ME) is None


def test_no_is_for_every_payment_of_the_suggestion() -> None:
    dismissed = case.spread_group(dismissed=frozenset({11, 13, 14}))
    assert ledger_cover.cover_suggestion(_state(dismissed), ME) is None
    # One of them dismissed alone: the other two are still proposed.
    partly = case.spread_group(dismissed=frozenset({11}))
    found = ledger_cover.cover_suggestion(_state(partly), ME)
    assert found is not None and [p.id for p in found.payments] == [13, 14]
