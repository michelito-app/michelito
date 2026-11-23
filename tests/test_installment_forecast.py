"""The remaining installments of the plans in Recurring's forecast (`web.recurring.with_plans`)."""

from datetime import date
from decimal import Decimal

from michelito.web import recurring as recurring_view


def _empty() -> recurring_view.Overview:
    return recurring_view.Overview(date(2026, 4, 30), "2026-01", [], [], [], Decimal(0), [])


def test_an_active_plan_adds_its_installment_to_the_installments_group() -> None:
    found = recurring_view.with_plans(_empty(), [(Decimal(9000), 4), (Decimal(1000), 20)])

    (group,) = found.groups
    assert group.group == recurring_view.INSTALLMENTS_GROUP
    assert group.monthly_dop == Decimal(10000)
    assert group.yearly_dop == Decimal(9000 * 4 + 1000 * 12)
    assert group.count == 2
    assert found.monthly_dop == Decimal(10000)


def test_a_finished_plan_adds_nothing() -> None:
    found = recurring_view.with_plans(_empty(), [(Decimal(9000), 0)])

    assert found.groups == [] and found.monthly_dop == 0


def test_the_plans_join_an_existing_installments_group() -> None:
    base = _empty()
    existing = recurring_view.GroupTotal(
        recurring_view.INSTALLMENTS_GROUP, Decimal(500), Decimal(6000), 1
    )
    other = recurring_view.GroupTotal(recurring_view.GROUP_ORDER[0], Decimal(100), Decimal(1200), 1)
    start = recurring_view.Overview(
        base.as_of, base.first_month, [], [other, existing], [], Decimal(600), []
    )

    found = recurring_view.with_plans(start, [(Decimal(1000), 2)])

    assert [g.group for g in found.groups] == [other.group, existing.group]
    assert found.groups[1].monthly_dop == Decimal(1500)
    assert found.groups[1].count == 2
    assert found.monthly_dop == Decimal(1600)
