"""Matching installment charges to plans (`analysis.installment_match`): pure, made-up values."""

from datetime import date

import pytest

from michelito.analysis import installment_match as im
from michelito.analysis.installment_match import Charge, Terms

CARD = "bank:credit_card"
OTHER_CARD = "other:credit_card"


def terms(
    plan_id: int = 1,
    *,
    account: str = CARD,
    matcher: str = "store.com*",
    cents: int = 15000,
    count: int = 4,
    first_month: str = "2026-03",
) -> Terms:
    return Terms(plan_id, account, matcher, cents, "USD", count, first_month)


def charge(
    fingerprint: str,
    day: date,
    *,
    cents: int = 15000,
    account: str = CARD,
    description: str = "Store.com*XY12AB STORE.COM/BILL",
    currency: str = "USD",
) -> Charge:
    return Charge(fingerprint, day, account, description, cents, currency)


def test_the_matcher_is_the_description_up_to_the_star() -> None:
    assert im.matcher_of("Store.com*XY12AB STORE.COM/BILL") == "store.com*"


def test_without_a_star_the_matcher_is_the_first_two_words() -> None:
    assert im.matcher_of("CUOTA  Phone Shop 03") == "cuota phone"


def test_months_between_counts_whole_calendar_months() -> None:
    assert im.number_for("2026-11", "2027-02") == 4
    assert im.month_of_number("2026-11", 3) == "2027-01"


def test_each_charge_links_as_the_installment_of_its_month() -> None:
    found = im.match(
        [terms()],
        [charge("a", date(2026, 3, 10)), charge("b", date(2026, 4, 9))],
    )

    assert found.links == {"a": (1, 1), "b": (1, 2)}
    assert found.off_script == {}


def test_a_charge_on_another_card_or_merchant_is_ignored() -> None:
    found = im.match(
        [terms()],
        [
            charge("a", date(2026, 3, 10), account=OTHER_CARD),
            charge("b", date(2026, 3, 10), description="STORE MARK*ZZ99 STORE.COM"),
            charge("c", date(2026, 3, 10), currency="DOP"),
        ],
    )

    assert found.links == {} and found.off_script == {}


def test_two_plans_on_different_cards_never_compete() -> None:
    found = im.match(
        [terms(1), terms(2, account=OTHER_CARD)],
        [charge("a", date(2026, 3, 10)), charge("b", date(2026, 3, 10), account=OTHER_CARD)],
    )

    assert found.links == {"a": (1, 1), "b": (2, 1)}


def test_a_different_amount_is_off_script_not_linked() -> None:
    found = im.match([terms()], [charge("a", date(2026, 3, 10), cents=16000)])

    assert found.links == {}
    assert found.off_script == {"a": im.OffScript(1, "amount", 1)}


def test_a_charge_after_the_last_installment_is_off_script() -> None:
    found = im.match([terms(count=2)], [charge("a", date(2026, 5, 10))])

    assert found.off_script == {"a": im.OffScript(1, "after_end", 3)}


def test_a_charge_before_the_plan_is_ignored() -> None:
    found = im.match([terms()], [charge("a", date(2026, 2, 10))])

    assert found.links == {} and found.off_script == {}


def test_a_refund_from_the_merchant_on_the_card_is_off_script() -> None:
    found = im.match([terms()], [charge("a", date(2026, 4, 2), cents=-15000)])

    assert found.off_script == {"a": im.OffScript(1, "refund", None)}


def test_two_exact_charges_in_one_month_are_both_off_script() -> None:
    found = im.match([terms()], [charge("a", date(2026, 3, 2)), charge("b", date(2026, 3, 20))])

    assert found.links == {}
    assert found.off_script == {
        "a": im.OffScript(1, "repeated", 1),
        "b": im.OffScript(1, "repeated", 1),
    }


def test_a_taken_number_is_not_linked_again() -> None:
    found = im.match(
        [terms()],
        [charge("a", date(2026, 3, 10)), charge("b", date(2026, 3, 25))],
        taken={"a": (1, 1)},
    )

    assert found.links == {}
    assert found.off_script == {"b": im.OffScript(1, "repeated", 1)}


def test_a_linked_charge_stays_linked_and_is_not_off_script() -> None:
    found = im.match([terms()], [charge("a", date(2026, 3, 10))], taken={"a": (1, 1)})

    assert found.links == {} and found.off_script == {}


def test_a_dismissed_pair_is_neither_linked_nor_shown() -> None:
    found = im.match([terms()], [charge("a", date(2026, 3, 10))], dismissed={(1, "a")})

    assert found.links == {} and found.off_script == {}


@pytest.mark.parametrize(
    ("last_day", "missing"),
    [
        (date(2026, 4, 15), []),  # within the grace days of April 9
        (date(2026, 4, 20), [2]),
        (date(2026, 6, 30), [2, 3, 4]),
    ],
)
def test_a_month_without_its_charge_is_missing_once_the_card_has_later_data(
    last_day: date, missing: list[int]
) -> None:
    found = im.missing(terms(), {1: date(2026, 3, 9)}, last_day)

    assert found == missing


def test_without_any_linked_charge_nothing_is_missing() -> None:
    assert im.missing(terms(), {}, date(2026, 12, 31)) == []


def test_backfill_finds_the_earlier_charges_in_consecutive_months() -> None:
    rows = [
        charge("x", date(2026, 1, 12)),
        charge("a", date(2026, 3, 10)),
        charge("b", date(2026, 4, 9)),
        charge("c", date(2026, 5, 11)),
    ]

    assert im.earlier_in_a_row(rows, rows[3]) == ["a", "b", "c"]


def test_a_charge_two_plans_could_take_goes_to_the_first_and_never_twice() -> None:
    found = im.match(
        [terms(1, first_month="2026-01"), terms(2, first_month="2026-02")],
        [charge("a", date(2026, 2, 5))],
    )

    assert found.links == {"a": (1, 2)}
    assert "a" not in found.off_script


def test_a_charge_long_after_the_end_is_not_flagged() -> None:
    found = im.match(
        [terms(count=2)],
        [charge("a", date(2026, 5, 10)), charge("b", date(2026, 9, 10))],
    )

    assert set(found.off_script) == {"a"}


def test_an_empty_description_has_no_matcher() -> None:
    assert im.matcher_of("  ") == ""
    assert im.matcher_of("*AB12") == ""
