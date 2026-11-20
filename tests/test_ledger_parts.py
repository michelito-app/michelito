"""The ledger's newer math (`analysis.ledger`, schema 21), without a database: splits by parts and
their cent rule, taking a person out of an entry keeping its mode, and payments on behalf of
others (allocations). Made-up people and amounts."""

from datetime import date
from decimal import Decimal

import pytest

from michelito.analysis import ledger
from michelito.analysis.ledger import Allocation, Entry, Group, Member, Payment, Split

D = Decimal
ME, ANA, LUIS, ROSA = 1, 2, 3, 4


def _entry(splits: tuple[Split, ...], mode: ledger.SplitMode, paid_by: int = ME) -> Entry:
    total = sum((s.share for s in splits), D(0))
    return Entry(1, 1, paid_by, total, "DOP", date(2026, 1, 10), "x", splits, mode)


def _shares(splits: tuple[Split, ...]) -> dict[int, Decimal]:
    return {s.contact_id: s.share for s in splits}


class TestParts:
    def test_amounts_follow_the_parts_and_add_up(self) -> None:
        splits = ledger.parts_split(D("4896.00"), [(ME, 1), (ANA, 2), (LUIS, 3)], ME)
        assert [(s.contact_id, s.share, s.parts) for s in splits] == [
            (ME, D("816.00"), 1),
            (ANA, D("1632.00"), 2),
            (LUIS, D("2448.00"), 3),
        ]

    def test_the_leftover_cents_go_to_the_payer(self) -> None:
        # 100.00 in 3 parts: 33.33 a part; 2 parts are 66.66, the leftover cent is the payer's.
        splits = ledger.parts_split(D("100.00"), [(ANA, 2), (LUIS, 1)], LUIS)
        assert _shares(splits) == {ANA: D("66.66"), LUIS: D("33.34")}
        splits = ledger.parts_split(D("0.10"), [(ME, 1), (ANA, 1), (LUIS, 1)], ANA)
        assert _shares(splits) == {ME: D("0.03"), ANA: D("0.04"), LUIS: D("0.03")}

    def test_without_the_payer_the_first_person_takes_them(self) -> None:
        splits = ledger.parts_split(D("10.00"), [(ANA, 1), (LUIS, 2)], ROSA)
        assert _shares(splits) == {ANA: D("3.34"), LUIS: D("6.66")}

    def test_every_rounding_adds_up(self) -> None:
        for cents in range(1, 400, 7):
            amount = D(cents).scaleb(-2)
            splits = ledger.parts_split(amount, [(ME, 3), (ANA, 5), (LUIS, 7)], ANA)
            assert sum(s.share for s in splits) == amount

    def test_at_least_one_part_and_one_person(self) -> None:
        with pytest.raises(ValueError):
            ledger.parts_split(D(10), [(ME, 0)], ME)
        with pytest.raises(ValueError):
            ledger.parts_split(D(10), [], ME)


class TestResplit:
    def test_equal_is_split_equally_among_the_rest(self) -> None:
        entry = _entry(ledger.equal_split(D("100.00"), [ME, ANA, LUIS], ME), "equal")
        assert _shares(ledger.resplit_without(entry, LUIS)) == {ME: D("50.00"), ANA: D("50.00")}
        odd = _entry(ledger.equal_split(D("100.01"), [ME, ANA, LUIS], ANA), "equal", ANA)
        assert _shares(ledger.resplit_without(odd, LUIS)) == {ME: D("50.00"), ANA: D("50.01")}

    def test_parts_keep_the_others_parts(self) -> None:
        splits = ledger.parts_split(D("4000.00"), [(ME, 1), (ANA, 2), (LUIS, 1)], ME)
        found = ledger.resplit_without(_entry(splits, "parts"), LUIS)
        assert [(s.contact_id, s.share, s.parts) for s in found] == [
            (ME, D("1333.34"), 1),
            (ANA, D("2666.66"), 2),
        ]

    def test_exact_goes_to_the_rest_in_proportion(self) -> None:
        # Luis's 300 goes 2:1 to Ana (600) and me (300): 200 and 100.
        splits = (Split(ME, D("300.00")), Split(ANA, D("600.00")), Split(LUIS, D("300.00")))
        found = ledger.resplit_without(_entry(splits, "exact"), LUIS)
        assert _shares(found) == {ME: D("400.00"), ANA: D("800.00")}

    def test_exact_rounding_leaves_the_cents_to_the_payer(self) -> None:
        splits = (Split(ME, D("1.00")), Split(ANA, D("1.00")), Split(LUIS, D("1.00")),
                  Split(ROSA, D("0.01")))  # fmt: skip
        found = ledger.resplit_without(_entry(splits, "exact", ANA), ROSA)
        assert _shares(found) == {ME: D("1.00"), ANA: D("1.01"), LUIS: D("1.00")}
        assert sum(found_.share for found_ in found) == D("3.01")

    def test_nobody_left_means_it_is_all_the_payers(self) -> None:
        entry = _entry((Split(ANA, D("50.00")),), "exact", ME)
        assert _shares(ledger.resplit_without(entry, ANA)) == {ME: D("50.00")}
        equal = _entry(ledger.equal_split(D("50.00"), [ANA], ME), "equal")
        assert _shares(ledger.resplit_without(equal, ANA)) == {ME: D("50.00")}


def _payment(
    amount: str,
    allocations: tuple[tuple[int, str], ...] = (),
    sent: str | None = None,
    accepted: bool = False,
    from_contact: int = ANA,
    payment_id: int = 1,
) -> Payment:
    return Payment(
        payment_id,
        1,
        from_contact,
        ME,
        D(amount),
        "DOP",
        date(2026, 1, 20),
        None if sent is None else D(sent),
        accepted,
        allocations=tuple(Allocation(c, D(v)) for c, v in allocations),
    )


class TestAllocations:
    def test_without_allocations_it_is_all_for_the_payer(self) -> None:
        assert _payment("100").parts_for(ME) == ((ANA, D(100)),)

    def test_allocations_split_what_settles(self) -> None:
        payment = _payment("100", ((ANA, "40"), (LUIS, "60")))
        assert payment.parts_for(ME) == ((ANA, D(40)), (LUIS, D(60)))

    def test_an_accepted_difference_is_the_payers(self) -> None:
        payment = _payment("100", ((ANA, "40"), (LUIS, "60")), sent="105", accepted=True)
        assert payment.parts_for(ME) == ((ANA, D(45)), (LUIS, D(60)))
        # A payer who paid only for others still gets the difference.
        others = _payment("100", ((LUIS, "100"),), sent="103", accepted=True)
        assert others.parts_for(ME) == ((ANA, D(3)), (LUIS, D(100)))

    def test_less_received_comes_off_the_payer_first_then_the_others(self) -> None:
        # Recorded as 100 (40 + 60); the bank brought 30: 40 off Ana... and 30 off Luis.
        payment = _payment("30", ((ANA, "40"), (LUIS, "60")))
        assert payment.parts_for(ME) == ((LUIS, D(30)),)

    def test_unattributed_has_no_parts(self) -> None:
        payment = Payment(1, 1, None, ME, D(10), "DOP", date(2026, 1, 20))
        assert payment.parts_for(ME) == ()

    def test_balances_use_the_allocations(self) -> None:
        # Ana paid 3,000 among the three of us: I owe her 1,000. Luis paid 1,500 among us: I owe
        # him 500. I paid 4,896 among the three: each owes me 1,632.
        entries = (
            Entry(
                1,
                1,
                ME,
                D(4896),
                "DOP",
                date(2026, 1, 3),
                "x",
                ledger.equal_split(D(4896), [ME, ANA, LUIS], ME),
                "equal",
            ),  # fmt: skip
        )
        payment = _payment("3264", ((ANA, "1632"), (LUIS, "1632")))
        members = (Member(ME), Member(ANA), Member(LUIS))
        state = ledger.group_state(Group(1, "Trip", members, entries, (payment,)), ME)
        assert state.person(ANA).net == {} and state.person(LUIS).net == {}  # type: ignore[union-attr]
        assert state.owed_to_me == {}
        # The same payment all for Ana would leave Luis owing and Ana owed back.
        alone = _payment("3264")
        state = ledger.group_state(Group(1, "Trip", members, entries, (alone,)), ME)
        assert state.person(ANA).net == {"DOP": D(-1632)}  # type: ignore[union-attr]
        assert state.person(LUIS).net == {"DOP": D(1632)}  # type: ignore[union-attr]

    def test_an_allocation_beyond_the_balance_turns_the_other_way_for_that_person(self) -> None:
        entries = (
            Entry(
                1,
                1,
                ME,
                D(300),
                "DOP",
                date(2026, 1, 3),
                "x",
                ledger.equal_split(D(300), [ME, ANA, LUIS], ME),
                "equal",
            ),  # fmt: skip
        )
        payment = _payment("250", ((ANA, "100"), (LUIS, "150")))
        members = (Member(ME), Member(ANA), Member(LUIS))
        state = ledger.group_state(Group(1, "Trip", members, entries, (payment,)), ME)
        assert state.person(ANA).net == {}  # type: ignore[union-attr]
        assert state.person(LUIS).net == {"DOP": D(-50)}  # type: ignore[union-attr]
        assert state.payments[0].turned == D(50)


def test_fit_allocations_is_the_one_rule_for_every_mismatch() -> None:
    # More: the principal's own part. Less: off the principal first (here at 0), then the rest.
    assert ledger.fit_allocations([(LUIS, D(100))], ANA, D(103)) == ((ANA, D(3)), (LUIS, D(100)))
    assert ledger.fit_allocations([(LUIS, D(155))], ANA, D(150)) == ((LUIS, D(150)),)
    assert ledger.fit_allocations([], ANA, D(10)) == ((ANA, D(10)),)
