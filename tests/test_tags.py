"""What a tag holds and what it adds up to (`analysis.tags`), made-up movements: each
fingerprint once, the user's own share for shared expenses, refunds subtracting, transfers
listed but not added, financed loans with what is still to pay and dollars without a rate."""

from datetime import date
from decimal import Decimal

from michelito.analysis import categories
from michelito.analysis.spending import Movement, group_fingerprint
from michelito.analysis.tag_store import Tag
from michelito.analysis.tags import Sources, counts, members, memberships, total

MANUAL = Tag(1, "Furnish", None, None, "2026-04-01")
GROUP = Tag(2, "Trip", 9, None, "2026-04-01")
NONE = Sources(groups={}, loans={}, plans={}, loans_with_payout=frozenset(), remaining={})


def move(
    fingerprint: str,
    day: date,
    amount: str,
    category: str = categories.HOME,
    currency: str = "DOP",
    **extra: object,
) -> Movement:
    fields: dict = {
        "day": day,
        "merchant": f"SHOP {fingerprint}",
        "description": f"SHOP {fingerprint}",
        "category": category,
        "amount": Decimal(amount),
        "currency": currency,
        "institution": "bank",
        "fingerprint": fingerprint,
    }
    fields.update(extra)
    return Movement(**fields)


def dop(m: Movement) -> Decimal | None:
    return m.amount if m.currency == "DOP" else None


def spent(found: list, still: str = "0") -> Decimal:
    return total(found, dop, Decimal(still)).spent


def test_manual_members_are_listed_newest_first() -> None:
    flow = [move("a", date(2026, 4, 18), "70000"), move("b", date(2026, 5, 16), "40000")]

    found = members(MANUAL, flow, {"a", "b"}, set(), NONE)

    assert [m.move.fingerprint for m in found] == ["b", "a"]
    assert all(m.via == "manual" and not m.derived for m in found)


def test_group_tag_includes_linked_and_others_paid_entries() -> None:
    linked = move(
        "hotel", date(2026, 3, 2), "4000", link="shared", gross=Decimal("12000"), category="Viajes"
    )
    others = move(group_fingerprint(7), date(2026, 3, 3), "3000", link="group")
    sources = Sources(
        groups={"hotel": 9, group_fingerprint(7): 9},
        loans={},
        plans={},
        loans_with_payout=frozenset(),
        remaining={},
    )

    found = members(GROUP, [linked, others], set(), set(), sources)

    assert {m.via for m in found} == {"group"}
    assert all(m.derived for m in found)
    assert spent(found) == Decimal("7000")


def test_manual_row_on_a_derived_member_counts_once() -> None:
    linked = move("hotel", date(2026, 3, 2), "4000", link="shared", gross=Decimal("12000"))
    sources = Sources({"hotel": 9}, {}, {}, frozenset(), {})

    found = members(GROUP, [linked], {"hotel"}, set(), sources)

    assert [(m.move.fingerprint, m.via) for m in found] == [("hotel", "group")]
    assert spent(found) == Decimal("4000")


def test_a_refund_subtracts() -> None:
    flow = [move("a", date(2026, 5, 1), "10000"), move("r", date(2026, 5, 9), "-2500")]

    assert spent(members(MANUAL, flow, {"a", "r"}, set(), NONE)) == Decimal("7500")


def test_transfers_and_income_are_listed_not_added() -> None:
    card = move("p", date(2026, 5, 27), "24000", category=categories.CARD_PAYMENT)
    pay_back = move("back", date(2026, 5, 28), "-1000", link="reimbursement")
    flow = [move("a", date(2026, 5, 1), "10000"), card, pay_back]

    found = members(MANUAL, flow, {"a", "p", "back"}, set(), NONE)

    assert {m.move.fingerprint: m.counted for m in found} == {"a": True, "p": False, "back": False}
    assert spent(found) == Decimal("10000")
    assert not counts(card)


def test_tagged_loan_without_payout_counts_payments_and_remaining() -> None:
    flow = [
        move(f"q{i}", date(2026, 2 + i, 15), "1000", category=categories.LOANS) for i in range(3)
    ]
    sources = Sources(
        {}, {f"q{i}": 5 for i in range(3)}, {}, frozenset(), {("loan", 5): Decimal("9000")}
    )

    found = members(MANUAL, flow, set(), {("loan", 5)}, sources)
    result = total(found, dop, Decimal("9000"))

    assert all(m.via == "loan" and m.derived for m in found)
    assert (result.spent, result.still_to_pay) == (Decimal("3000"), Decimal("9000"))


def test_tagged_loan_with_payout_adds_nothing() -> None:
    flow = [
        move(f"q{i}", date(2026, 2 + i, 15), "1000", category=categories.LOANS) for i in range(3)
    ]
    sources = Sources(
        {}, {f"q{i}": 5 for i in range(3)}, {}, frozenset({5}), {("loan", 5): Decimal("9000")}
    )

    found = members(MANUAL, flow, set(), {("loan", 5)}, sources)

    assert found == []


def test_a_tagged_installment_plan_brings_its_charges() -> None:
    flow = [move("c1", date(2026, 6, 3), "2000"), move("c2", date(2026, 7, 3), "2000")]
    sources = Sources(
        {}, {}, {"c1": 4, "c2": 4}, frozenset(), {("installment", 4): Decimal("8000")}
    )

    found = members(MANUAL, flow, set(), {("installment", 4)}, sources)

    assert [m.via for m in found] == ["installment", "installment"]
    assert spent(found) == Decimal("4000")


def test_dollars_without_rate_are_flagged() -> None:
    flow = [
        move("a", date(2026, 5, 1), "10000"),
        move("u", date(2026, 5, 5), "113", currency="USD"),
    ]

    result = total(members(MANUAL, flow, {"a", "u"}, set(), NONE), dop, Decimal("0"))

    assert (result.spent, result.unconverted) == (Decimal("10000"), 1)


def test_a_missing_fingerprint_is_skipped() -> None:
    flow = [move("a", date(2026, 5, 1), "10000")]

    found = members(MANUAL, flow, {"a", "gone"}, set(), NONE)

    assert [m.move.fingerprint for m in found] == ["a"]


def test_by_category_is_sorted_and_span_is_first_and_last_day() -> None:
    flow = [
        move("a", date(2026, 4, 18), "70000"),
        move("b", date(2026, 6, 6), "40000", category=categories.PROFESSIONAL),
        move("c", date(2026, 5, 16), "40500"),
    ]

    result = total(members(MANUAL, flow, {"a", "b", "c"}, set(), NONE), dop, Decimal("0"))

    assert result.by_category == (
        (categories.HOME, Decimal("110500")),
        (categories.PROFESSIONAL, Decimal("40000")),
    )
    assert (result.first, result.last, result.count) == (date(2026, 4, 18), date(2026, 6, 6), 3)


def test_memberships_in_one_pass_agree_with_each_tags_members() -> None:
    hotel = move("hotel", date(2026, 3, 2), "4000", link="shared", gross=Decimal("12000"))
    pay = move("q1", date(2026, 3, 15), "1000", category=categories.LOANS)
    sofa = move("sofa", date(2026, 4, 18), "70000")
    other = move("x", date(2026, 4, 19), "500")
    flow = [hotel, pay, sofa, other]
    sources = Sources({"hotel": 9}, {"q1": 5}, {}, frozenset(), {})
    furnish = Tag(1, "Furnish", None, None, "2026-04-01")
    manual = {1: {"sofa", "hotel"}}
    targets = {1: {("loan", 5)}}

    found = memberships([furnish, GROUP], flow, manual, targets, sources)

    expected = {
        tag.id: members(tag, flow, manual.get(tag.id, set()), targets.get(tag.id, set()), sources)
        for tag in (furnish, GROUP)
    }
    for tag_id, listed in expected.items():
        assert sorted(m.move.fingerprint for m in listed) == sorted(
            fp for fp, items in found.items() if any(tag.id == tag_id for tag, _ in items)
        )
    assert "x" not in found
