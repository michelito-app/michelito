"""Reserves (pure logic of `analysis.reserves`): due months, monthly contribution, what is already
paid and the suggested links. Reserve suggestions are in `test_reserve_suggestions`. Made-up
data."""

from datetime import date
from decimal import Decimal as D

import pytest

from michelito.analysis import reserves
from michelito.analysis.reserves import Reserve, Spent

FUN, TAX = 7, 8


def reserve(**changes: object) -> Reserve:
    base: dict[str, object] = {
        "id": 1,
        "name": "Marbete",
        "amount": D(3_500),
        "category_id": TAX,
        "due_month": "2027-01",
        "every_months": 12,
        "created_month": "2025-01",
    }
    return Reserve(**{**base, **changes})  # type: ignore[arg-type]


def spent(
    fp: str, day: str, dop: str | None, category: int = TAX, recurring: bool = False
) -> Spent:
    return Spent(fp, date.fromisoformat(day), category, None if dop is None else D(dop), recurring)


@pytest.mark.parametrize(
    ("changes", "monthly"),
    [
        ({"amount": D(3_500)}, D(300)),  # yearly: 3,500 / 12 = 291.67 -> 300
        ({"amount": D(30_000), "every_months": 6}, D(5_000)),  # half-yearly
        ({"amount": D(12_000), "every_months": 12}, D(1_000)),  # exact: no rounding
        # Once: from February (created) to December, both included, is 11 months ->
        # 5,500 / 11 = 500.
        ({"amount": D(5_500), "every_months": None, "due_month": "2026-12"}, D(500)),
        # Once, created in the month it is due: the whole amount.
        ({"amount": D(4_500), "every_months": None, "due_month": "2026-02"}, D(4_500)),
        # From February to March: 2 months.
        ({"amount": D(4_500), "every_months": None, "due_month": "2026-03"}, D(2_300)),
        # Once and already past due: nothing to set aside.
        ({"amount": D(4_500), "every_months": None, "due_month": "2026-01"}, D(0)),
    ],
)
def test_monthly_contribution(changes: dict[str, object], monthly: D) -> None:
    found = reserve(**{"created_month": "2026-02", **changes})
    assert reserves.monthly_contribution(found, "2026-02") == monthly


def test_due_months_cover_yearly_half_yearly_and_once() -> None:
    yearly = reserve(due_month="2025-12")
    assert reserves.due_months(yearly, "2026-01", "2027-12") == ["2026-12", "2027-12"]
    assert reserves.next_due(yearly, "2026-12") == "2026-12"
    half = reserve(due_month="2026-03", every_months=6)
    assert reserves.due_months(half, "2026-01", "2026-12") == ["2026-03", "2026-09"]
    once = reserve(due_month="2026-05", every_months=None)
    assert reserves.next_due(once, "2026-02") == "2026-05"
    assert reserves.next_due(once, "2026-06") is None
    assert reserves.near_due(yearly, "2027-01") == "2026-12"  # one month later
    assert reserves.near_due(yearly, "2026-10") is None
    # A repeating reserve is also due before its first due month (the phase is "every January").
    assert reserves.due_months(reserve(), "2025-01", "2026-12") == ["2025-01", "2026-01"]


def test_year_status_and_upcoming_within_60_days() -> None:
    found = reserve(members=("a", "b", "c"), due_month="2026-03")
    by_fp = {
        "a": spent("a", "2026-03-02", "2000"),
        "b": spent("b", "2026-03-20", None),  # US$ without a rate: counted apart
        "c": spent("c", "2025-03-01", "9999"),  # another year
    }
    status = reserves.year_status(found, 2026, by_fp)
    assert (status.spent, status.estimated, status.without_rate) == (D(2_000), D(3_500), 1)
    soon = reserve(id=2, name="Colegio", due_month="2026-04", every_months=None)
    late = reserve(id=3, name="Seguro", due_month="2026-06", every_months=None)
    gone = reserve(id=4, name="Old", due_month="2026-01", every_months=None)
    near = reserves.upcoming([late, soon, found, gone], date(2026, 2, 20))
    assert [(r.name, due) for r, due in near] == [("Marbete", "2026-03"), ("Colegio", "2026-04")]


def test_a_paid_due_leaves_upcoming_and_the_monthly_total() -> None:
    vehicle_tax = reserve(due_month="2026-03", members=("tax",))
    school = reserve(id=2, name="Colegio", amount=D(1_200), due_month="2026-03")
    by_fp = {"tax": spent("tax", "2026-03-02", "3500")}
    paid = reserves.paid_dues([vehicle_tax, school], by_fp)
    assert paid == {(1, "2026-03")}
    near = reserves.upcoming([vehicle_tax, school], date(2026, 3, 5), paid=paid)
    assert [r.name for r, _ in near] == ["Colegio"]
    assert reserves.monthly_total([vehicle_tax, school], "2026-03", paid) == D(100)
    assert reserves.monthly_total([vehicle_tax, school], "2026-03") == D(400)


def test_link_suggestion_needs_category_window_and_amount() -> None:
    vehicle_tax = reserve(due_month="2026-01")
    expenses = [
        spent("ok", "2026-02-10", "3000"),  # one month later, within +-50 %
        spent("early", "2025-12-15", "3600"),  # one month earlier: also
        spent("far", "2026-03-01", "3500"),  # two months later: no
        spent("big", "2026-01-05", "6000"),  # over 150 %: no
        spent("small", "2026-01-05", "1000"),  # under 50 %: no
        spent("other", "2026-01-05", "3500", category=FUN),  # another category: no
        spent("linked", "2026-01-06", "3500"),  # already in a link: no
        spent("usd", "2026-01-07", None),  # no rate: no
    ]
    found = reserves.link_suggestions(expenses, [vehicle_tax], linked={"linked"})
    assert found == {"ok": 1, "early": 1}
    # It already has its expense for that due month: a single-expense reserve proposes no other.
    taken = reserve(due_month="2026-01", members=("ok",))
    assert reserves.link_suggestions(expenses, [taken], linked={"ok"}) == {}


def test_link_suggestion_never_before_the_reserve_was_created() -> None:
    # Created in February 2026: the January 2026 due month is from before.
    late = reserve(created_month="2026-02")
    expenses = [spent("jan", "2026-01-20", "3400"), spent("next", "2027-01-20", "3400")]
    assert reserves.link_suggestions(expenses, [late], linked=set()) == {"next": 1}


def test_a_spending_that_fits_two_reserves_goes_to_the_closest_amount() -> None:
    big = reserve(id=1, name="Seguro", amount=D(5_000), due_month="2026-01")
    close = reserve(id=2, name="Marbete", amount=D(3_400), due_month="2026-01")
    found = reserves.link_suggestions([spent("tax", "2026-01-20", "3500")], [big, close], set())
    assert found == {"tax": 2}


def _usual(value: str):  # noqa: ANN202
    return lambda category, month: D(value)


def test_several_expenses_only_in_the_due_month_and_above_the_usual() -> None:
    christmas = reserve(
        name="Navidad", category_id=FUN, amount=D(20_000), due_month="2025-12", multiple=True
    )
    expenses = [
        spent("gift1", "2025-12-05", "15000", FUN),
        spent("gift2", "2025-12-10", "9000", FUN),
        spent("cinema", "2025-12-12", "3000", FUN, recurring=True),  # recurring: no
        spent("tiny", "2025-12-11", "500", FUN),  # under 5 % of the estimate: no
        spent("november", "2025-11-12", "3000", FUN),  # not the due month
        spent("january", "2026-01-12", "3000", FUN),
    ]
    # The month adds up to 27,500 and the usual is 3,000: up to 24,500 is proposed, largest first.
    found = reserves.link_suggestions(expenses, [christmas], set(), _usual("3000"))
    assert found == {"gift1": 1, "gift2": 1}
    # With a high usual, only what exceeds it fits (27,500 - 12,000 = 15,500).
    assert reserves.link_suggestions(expenses, [christmas], set(), _usual("12000")) == {"gift1": 1}
    # Without a usual (no reference months) nothing is proposed.
    assert reserves.link_suggestions(expenses, [christmas], set()) == {}
    # With the first already linked, the rest of the excess (24,500 - 15,000) admits the second.
    with_one = reserve(**{**christmas.__dict__, "members": ("gift1",)})
    found = reserves.link_suggestions(expenses, [with_one], {"gift1"}, _usual("3000"))
    assert found == {"gift2": 1}


def test_habitual_before_is_the_median_of_the_previous_complete_months() -> None:
    regular = {FUN: {"2025-06": D(1000), "2025-07": D(3000), "2025-08": D(2000)}}
    complete = ["2025-06", "2025-07", "2025-08", "2025-09"]
    assert reserves.habitual_before(regular, complete, FUN, "2025-09") == D(2000)
    assert reserves.habitual_before(regular, complete, FUN, "2025-06") is None
