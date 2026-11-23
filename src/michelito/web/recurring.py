"""Recurring charges view: detection + the user's marks + exchange rates.

Pure function: takes movements, marks and rates already loaded; never touches the database.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from michelito.analysis import categories, providers
from michelito.analysis import recurring as rec
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.recurring import PriceChange, Recurring
from michelito.analysis.recurring_marks import Mark, MarkStatus, for_series
from michelito.analysis.report import money
from michelito.analysis.spending import Movement
from michelito.i18n import t

Status = Literal["active", "inactive", "cancelled", "ended"]
AlertKind = Literal["new", "price_up", "charged_after_cancel"]

INSTALLMENTS_GROUP = t("web.recurring.installments_group")
_NAMES = list(rec.GROUPS.values())
# Housing · Loans · Utilities · Insurance · Subscriptions · Bank fees · Installments · Other.
GROUP_ORDER = (*_NAMES[:-1], INSTALLMENTS_GROUP, _NAMES[-1])
_PERIOD_DAYS = {"monthly": 30, "yearly": 365}
_MONTHS_PER_YEAR = 12
_ONE_UNIT = Decimal(1)


@dataclass(frozen=True)
class RecurringView:
    merchant: str  # the series key (marks use it)
    currency: str
    category: str
    group: str
    cadence: rec.Cadence
    status: Status
    typical: Decimal
    variable: bool
    monthly_dop: Decimal | None
    yearly_dop: Decimal | None
    first_day: date
    last_day: date
    charges: int
    price_change: PriceChange | None
    installments_left: int | None
    mark: MarkStatus | None
    charged_after_cancel: bool
    name: str = ""  # the display name (the provider's); empty: `merchant`
    members: tuple[str, ...] = ()  # the series' merchants
    provider: bool = False  # a provider from the list
    extras_year: Decimal = Decimal(0)  # loans: extra payments in the year of `as_of` (own currency)
    group_key: str = ""  # the `recurring.GROUPS` key (empty for Installments)


@dataclass(frozen=True)
class GroupTotal:
    group: str
    monthly_dop: Decimal
    yearly_dop: Decimal
    count: int


@dataclass(frozen=True)
class Alert:
    kind: AlertKind
    merchant: str
    currency: str
    detail: str
    fingerprint: str = ""  # the charge behind it, when known (price up, charged after cancel)
    name: str = ""  # the series' display name; empty: `merchant`


@dataclass(frozen=True)
class Overview:
    as_of: date | None  # None when there are no movements
    first_month: str | None  # month of the first movement ("YYYY-MM")
    items: list[RecurringView]
    groups: list[GroupTotal]
    dismissed: list[RecurringView]
    monthly_dop: Decimal
    alerts: list[Alert]


def build_overview(
    movements: Sequence[Movement],
    marks: Mapping[tuple[str, str], Mark],
    rates: Mapping[str, Rate],
    month: str | None,
    *,
    as_of: date | None = None,
    unions: Mapping[str, str] | None = None,
) -> Overview:
    """`as_of`: the day against which a charge counts as still active; by default the latest
    movement received (with a subset of accounts, better pass the one of all accounts).
    `marks`: by merchant or by series (read by series); `unions`: the manual unions."""
    if not movements:
        return Overview(None, None, [], [], [], Decimal(0), [])
    as_of = as_of or max(m.day for m in movements)
    first_month = min(m.month for m in movements)
    rate = rate_for(rates, as_of.strftime("%Y-%m"))

    views: list[RecurringView] = []
    dismissed: list[RecurringView] = []
    alerts: list[Alert] = []
    by_series = series_marks(movements, marks, unions)
    for found in _candidates(movements, by_series, unions):
        mark = by_series.get((found.merchant, found.currency))
        view = _view(found, mark, as_of, rate)
        if view.mark == "dismissed":
            dismissed.append(view)
            continue
        views.append(view)
        if month is not None:
            alerts.extend(_alerts(found, view, mark, month, first_month))

    views.sort(key=_order)
    dismissed.sort(key=lambda v: (v.merchant, v.currency))
    active = [v for v in views if v.status == "active"]
    return Overview(
        as_of=as_of,
        first_month=first_month,
        items=views,
        groups=_group_totals(active),
        dismissed=dismissed,
        monthly_dop=sum((v.monthly_dop for v in active if v.monthly_dop is not None), Decimal(0)),
        alerts=alerts,
    )


def series_marks(
    movements: Sequence[Movement],
    marks: Mapping[tuple[str, str], Mark],
    unions: Mapping[str, str] | None = None,
) -> dict[tuple[str, str], Mark]:
    """Marks by series (`recurring_marks.for_series`): those of a provider's or a union's
    merchants apply to the series as long as it has none of its own."""
    return for_series(marks, rec.members(movements, unions))


def _with_chosen_cadence(
    found: Recurring, groups: Mapping[tuple[str, str], list[Movement]], mark: Mark | None
) -> Recurring:
    chosen = mark.cadence if mark is not None else None
    if chosen is None or chosen == found.cadence:
        return found
    items = groups.get((found.merchant, found.currency), [])
    return rec.marked_items(found.merchant, found.currency, items, chosen) or found


def _candidates(
    movements: Sequence[Movement],
    marks: Mapping[tuple[str, str], Mark],
    unions: Mapping[str, str] | None,
) -> list[Recurring]:
    """The detected series (with the manually chosen cadence, if a different one was chosen)
    plus the marked ones the rule does not detect. Groups the movements only once."""
    groups = rec.group_movements(movements, unions)
    found = [
        _with_chosen_cadence(r, groups, marks.get((r.merchant, r.currency)))
        for r in rec.detect_grouped(groups)
    ]
    seen = {(r.merchant, r.currency) for r in found}
    for key, mark in sorted(marks.items()):
        if key in seen or mark.status not in ("confirmed", "cancelled"):
            continue
        fallback = rec.marked_items(*key, groups.get(key, []), mark.cadence)
        if fallback is not None:
            found.append(fallback)
    return found


def series_view(
    movements: Sequence[Movement],
    marks: Mapping[tuple[str, str], Mark],
    rates: Mapping[str, Rate],
    key: str,
    currency: str,
    *,
    as_of: date,
    unions: Mapping[str, str] | None = None,
) -> RecurringView | None:
    """The view of a single series (as in `build_overview`) without computing the others; None
    if it is not in Recurring (neither detected nor marked)."""
    items = [
        m
        for m in movements
        if m.amount > 0 and m.currency == currency and rec.series_key(m, unions) == key
    ]
    names = {m.merchant for m in items}
    mark = for_series(marks, {key: names}).get((key, currency)) if names else None
    found = rec.detect_series(key, currency, items)
    if found is not None:
        found = _with_chosen_cadence(found, {(key, currency): items}, mark)
    elif mark is not None and mark.status in ("confirmed", "cancelled"):
        found = rec.marked_items(key, currency, items, mark.cadence)
    if found is None:
        return None
    return _view(found, mark, as_of, rate_for(rates, as_of.strftime("%Y-%m")))


def _round_whole(value: Decimal) -> Decimal:
    return value.quantize(_ONE_UNIT, rounding=ROUND_HALF_EVEN)


def _costs(found: Recurring, rate: Rate | None) -> tuple[Decimal | None, Decimal | None]:
    """(monthly, yearly) in whole RD$: the charge's own period is rounded from the typical
    amount and the other derives from it, so monthly x 12 and yearly match on screen."""
    typical = to_dop(found.typical, found.currency, rate)
    if typical is None:
        return None, None
    if found.cadence == "yearly":
        yearly = _round_whole(typical)
        return _round_whole(yearly / _MONTHS_PER_YEAR), yearly
    monthly = _round_whole(typical)
    return monthly, monthly * _MONTHS_PER_YEAR


def _view(found: Recurring, mark: Mark | None, as_of: date, rate: Rate | None) -> RecurringView:
    left = _installments_left(found, mark)
    status = _status(found, mark, left, as_of)
    monthly, yearly = _costs(found, rate)
    group_key = _group_key(found, mark, left)
    return RecurringView(
        merchant=found.merchant,
        currency=found.currency,
        category=found.category,
        group=rec.GROUPS[group_key] if group_key else INSTALLMENTS_GROUP,
        cadence=found.cadence,
        status=status,
        typical=found.typical,
        variable=found.variable,
        monthly_dop=monthly,
        yearly_dop=yearly,
        first_day=found.first_day,
        last_day=found.last_day,
        charges=len(found.charges),
        price_change=found.price_change,
        installments_left=left,
        mark=mark.status if mark else None,
        charged_after_cancel=_charged_after_cancel(found, mark),
        name=found.display,
        members=found.members or (found.merchant,),
        provider=providers.is_provider_key(found.merchant),
        extras_year=sum((c.amount for c in found.extras if c.day.year == as_of.year), Decimal(0)),
        group_key=group_key,
    )


def _group_key(found: Recurring, mark: Mark | None, left: int | None) -> str:
    """The manually chosen group; otherwise Installments (empty key) for anything with recorded
    installments except a loan (which stays in Loans); otherwise its category's group."""
    if mark is not None and mark.group in rec.GROUPS:
        return mark.group
    if left is not None and found.category_ref != categories.LOANS:
        return ""
    return rec.group_key_of(found.category_ref, found.category)


def _installments_left(found: Recurring, mark: Mark | None) -> int | None:
    if mark is None or mark.installments_left is None:
        return None
    since = mark.installments_on
    paid = sum(1 for c in found.charges if since is None or c.day > since)
    return max(0, mark.installments_left - paid)


def _status(found: Recurring, mark: Mark | None, left: int | None, as_of: date) -> Status:
    if left == 0:
        return "ended"
    if mark is not None and mark.status == "cancelled":
        return "cancelled"
    return "inactive" if (as_of - found.last_day).days > inactive_after(found) else "active"


def inactive_after(found: Recurring) -> Decimal:
    """Days without a charge after which a charge is inactive: 1.5 periods; for a monthly
    Utility, 1.5 times the months there can be between two payments (`UTILITY_MAX_GAP`: 90
    days), because a month without payment followed by a double one is normal."""
    months = rec.UTILITY_MAX_GAP if found.utility_monthly else 1
    return _PERIOD_DAYS[found.cadence] * months * rec.INACTIVE_FACTOR


def _after_cancel(found: Recurring, mark: Mark | None) -> list[rec.Charge]:
    if mark is None or mark.status != "cancelled" or mark.status_on is None:
        return []
    return [c for c in found.charges if c.day > mark.status_on]


def _charged_after_cancel(found: Recurring, mark: Mark | None) -> bool:
    return bool(_after_cancel(found, mark))


def _order(view: RecurringView) -> tuple[int, bool, Decimal, str]:
    monthly = view.monthly_dop
    return (
        GROUP_ORDER.index(view.group),
        monthly is None,
        -monthly if monthly is not None else Decimal(0),
        view.name or view.merchant,
    )


def _group_totals(active: list[RecurringView]) -> list[GroupTotal]:
    totals = []
    for group in GROUP_ORDER:
        members = [v for v in active if v.group == group]
        if not members:
            continue
        monthly = sum((v.monthly_dop for v in members if v.monthly_dop is not None), Decimal(0))
        yearly = sum((v.yearly_dop for v in members if v.yearly_dop is not None), Decimal(0))
        totals.append(GroupTotal(group, monthly, yearly, len(members)))
    return totals


def _alerts(
    found: Recurring, view: RecurringView, mark: Mark | None, month: str, first_month: str
) -> list[Alert]:
    merchant, currency = found.merchant, found.currency
    alerts = []
    active = view.status == "active"
    # In the first month with data everything "starts" there: not a new charge.
    first_seen = found.first_day.strftime("%Y-%m")
    if active and first_seen == month and month != first_month:
        if view.monthly_dop is not None:
            cost = money(view.monthly_dop, "DOP")
        else:
            cost = money(found.monthly, currency)
        detail = t("web.recurring.alert_new", cost=cost)
        alerts.append(Alert("new", merchant, currency, detail, name=found.display))
    change = found.price_change
    if (
        active
        and change is not None
        and change.after > change.before
        and change.day.strftime("%Y-%m") == month
    ):
        detail = t(
            "web.recurring.alert_price_up",
            before=money(change.before, currency),
            after=money(change.after, currency),
        )
        charge = next((c for c in found.charges if c.day == change.day), None)
        alerts.append(
            Alert(
                "price_up",
                merchant,
                currency,
                detail,
                charge.fingerprint if charge else "",
                found.display,
            )
        )
    late = [c for c in _after_cancel(found, mark) if c.day.strftime("%Y-%m") == month]
    if late:
        detail = t(
            "web.recurring.alert_charged_after_cancel", amount=money(late[-1].amount, currency)
        )
        alerts.append(
            Alert(
                "charged_after_cancel",
                merchant,
                currency,
                detail,
                late[-1].fingerprint,
                found.display,
            )
        )
    return alerts


MONTHS_A_YEAR = 12


def with_plans(found: Overview, plans: Sequence[tuple[Decimal, int]]) -> Overview:
    """The overview with the installment plans' remaining installments in the Installments
    group: each plan with installments left adds its installment (RD$) to the monthly total
    and the installments of the next twelve months to the yearly one. `plans`: (installment in
    RD$, installments left)."""
    active = [(amount, left) for amount, left in plans if left > 0]
    if not active:
        return found
    monthly = sum((amount for amount, _ in active), Decimal(0))
    yearly = sum((amount * min(left, MONTHS_A_YEAR) for amount, left in active), Decimal(0))
    groups = list(found.groups)
    index = next((i for i, g in enumerate(groups) if g.group == INSTALLMENTS_GROUP), None)
    if index is None:
        groups.append(GroupTotal(INSTALLMENTS_GROUP, monthly, yearly, len(active)))
        groups.sort(key=lambda g: GROUP_ORDER.index(g.group))
    else:
        old = groups[index]
        groups[index] = GroupTotal(
            old.group, old.monthly_dop + monthly, old.yearly_dop + yearly, old.count + len(active)
        )
    return replace(found, groups=groups, monthly_dop=found.monthly_dop + monthly)
