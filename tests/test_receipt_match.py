"""Matching receipts to transactions (`analysis.receipt_match`): pure, with made-up values."""

from datetime import date

import pytest

from michelito.analysis import receipt_match
from michelito.analysis.receipt_match import Charge, Pending

DAY = date(2026, 2, 14)


def pending(
    receipt_id: int = 1,
    *,
    cents: int = 13056,
    day: date = DAY,
    orders: tuple[str, ...] = ("ORDER-A",),
    merchant: str = "Amazon",
    currency: str = "USD",
) -> Pending:
    return Pending(receipt_id, merchant, orders, cents, currency, day)


def charge(
    fingerprint: str = "tx-1",
    *,
    cents: int = 13056,
    day: date = DAY,
    description: str = "AMAZON MKTPL*AB1CD2EF3",
    currency: str = "USD",
) -> Charge:
    return Charge(fingerprint, day, cents, currency, description)


def test_a_single_exact_charge_is_linked() -> None:
    found = receipt_match.match([pending()], [charge()])

    assert found.links == {1: "tx-1"}
    assert found.proposals == {}


@pytest.mark.parametrize("offset", [-1, 0, 3, 5])
def test_the_charge_may_come_a_day_before_or_a_few_days_after(offset: int) -> None:
    row = charge(day=date.fromordinal(DAY.toordinal() + offset))

    assert receipt_match.match([pending()], [row]).links == {1: "tx-1"}


@pytest.mark.parametrize("offset", [-2, 6, 40])
def test_a_charge_outside_the_window_is_not_a_candidate(offset: int) -> None:
    row = charge(day=date.fromordinal(DAY.toordinal() + offset))

    found = receipt_match.match([pending()], [row])

    assert found.links == {} and found.proposals == {}


@pytest.mark.parametrize(
    "row",
    [
        charge(cents=13055),
        charge(currency="DOP"),
        charge(description="TIENDA FICTICIA SANTO DOMINGO"),
    ],
)
def test_another_amount_currency_or_merchant_is_not_a_candidate(row: Charge) -> None:
    found = receipt_match.match([pending()], [row])

    assert found.links == {} and found.proposals == {}


@pytest.mark.parametrize(
    "description",
    [
        "AMAZON.COM*AB1CD2EF3 SEATTLE",
        "AMZN Mktp US*AB1CD2EF3",
        "Amazon Prime*AB1CD",
        "AMAZON RETAIL",
    ],
)
def test_the_descriptions_a_bank_prints_for_the_merchant(description: str) -> None:
    assert receipt_match.match([pending()], [charge(description=description)]).links == {1: "tx-1"}


@pytest.mark.parametrize("description", ["AMAZONAS RESTAURANT", "CAMAZON STORE", "PAGO AMZNX"])
def test_a_name_that_only_contains_the_merchants_is_not_it(description: str) -> None:
    found = receipt_match.match([pending()], [charge(description=description)])

    assert found.links == {}


def test_two_exact_charges_are_proposed_not_guessed() -> None:
    rows = [charge("tx-1"), charge("tx-2", day=date(2026, 2, 15))]

    found = receipt_match.match([pending()], rows)

    assert found.links == {}
    assert found.proposals == {1: ("tx-1", "tx-2")}


def test_two_receipts_of_different_orders_for_one_charge_are_proposed() -> None:
    receipts = [pending(1, orders=("ORDER-A",)), pending(2, orders=("ORDER-B",))]

    found = receipt_match.match(receipts, [charge()])

    assert found.links == {}
    assert found.proposals == {1: ("tx-1",), 2: ("tx-1",)}


def test_two_receipts_of_the_same_order_share_the_charge() -> None:
    # The order confirmation and its only shipment say the same amount.
    receipts = [pending(1, orders=("ORDER-A",)), pending(2, orders=("ORDER-A", "ORDER-B"))]

    found = receipt_match.match(receipts, [charge()])

    assert found.links == {1: "tx-1", 2: "tx-1"}


def test_each_receipt_finds_its_own_charge() -> None:
    receipts = [pending(1, cents=11097), pending(2, cents=5539, orders=("ORDER-B",))]
    rows = [charge("tx-1", cents=5539), charge("tx-2", cents=11097)]

    assert receipt_match.match(receipts, rows).links == {1: "tx-2", 2: "tx-1"}


def test_a_dismissed_pair_is_never_offered_again() -> None:
    rows = [charge("tx-1"), charge("tx-2")]

    found = receipt_match.match([pending()], rows, dismissed={(1, "tx-1")})

    assert found.links == {1: "tx-2"}


def test_a_charge_taken_by_another_order_is_not_a_candidate() -> None:
    found = receipt_match.match([pending()], [charge()], taken={"tx-1": frozenset({"ORDER-Z"})})

    assert found.links == {} and found.proposals == {}


def test_a_charge_taken_by_the_same_order_still_links() -> None:
    found = receipt_match.match([pending()], [charge()], taken={"tx-1": frozenset({"ORDER-A"})})

    assert found.links == {1: "tx-1"}


def test_a_merchant_without_a_known_description_matches_nothing() -> None:
    found = receipt_match.match([pending(merchant="Tienda Ficticia")], [charge()])

    assert found.links == {} and found.proposals == {}


def test_the_result_does_not_depend_on_the_order_given() -> None:
    receipts = [pending(1), pending(2, cents=500, orders=("ORDER-B",))]
    rows = [charge("tx-1"), charge("tx-2", cents=500), charge("tx-3", cents=500)]

    forward = receipt_match.match(receipts, rows)
    backward = receipt_match.match(receipts[::-1], rows[::-1])

    assert forward == backward
    assert forward.proposals == {2: ("tx-2", "tx-3")}


def test_receipts_must_share_one_order_whatever_order_they_arrived_in() -> None:
    # A shipment across two orders does not make the two orders one.
    first = pending(1, orders=("ORDER-A",))
    across = pending(2, orders=("ORDER-A", "ORDER-B"))
    second = pending(3, orders=("ORDER-B",))

    for receipts in ([first, across, second], [across, first, second]):
        renumbered = [
            Pending(index, r.merchant, r.orders, r.amount_cents, r.currency, r.day)
            for index, r in enumerate(receipts, 1)
        ]
        found = receipt_match.match(renumbered, [charge()])
        assert found.links == {}
        assert set(found.proposals) == {1, 2, 3}


def test_many_waiting_receipts_do_not_scan_every_charge() -> None:
    receipts = [pending(index, cents=100 + index) for index in range(1, 301)]
    rows = [charge(f"tx-{index}", cents=50_000 + index) for index in range(5000)]
    rows.append(charge("tx-match", cents=101))

    found = receipt_match.match(receipts, rows)

    assert found.links == {1: "tx-match"}
