"""Detection of recurring charges (monthly and yearly) over card movements.

Pure functions: they take movements already loaded and never touch the database.
Only charges count (positive amount); refunds are ignored.

A *series* is what is measured together: by default, one merchant in one currency. There are
three exceptions (`series_key`):
- in Utilities, the merchants of one provider from the list (`providers`) form a single series,
  and each month's charge is the sum of what was paid that month (`_utility`);
- a merchant joined by hand to another (or to a provider) goes in that one's series (`unions`);
- Utilities prepaid top-ups go in none.
In Loans only the installment counts (the amount that repeats); the other payments are extra
payments (`_loan`).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Literal

from michelito.analysis import categories, providers
from michelito.analysis import recurring_loans as loans
from michelito.analysis.spending import Movement
from michelito.i18n import t

Cadence = Literal["monthly", "yearly"]
# How each cadence reads in the change log (display text).
CADENCE_LABELS: dict[str, str] = {
    "monthly": t("analysis.recurring.cadence.monthly"),
    "yearly": t("analysis.recurring.cadence.yearly"),
}

MONTHLY_MIN = 3
MONTHLY_GAP = (20, 40)  # days between consecutive charges
MONTHLY_SKIP_GAP = (41, 80)  # one skipped month between two charges
YEARLY_MIN = 2
YEARLY_GAP = (330, 400)
FIXED_TOLERANCE = Decimal("0.10")
VARIABLE_TOLERANCE = Decimal("0.50")
INACTIVE_FACTOR = Decimal("1.5")

_TYPICAL_CHARGES = 3  # the typical amount is the median of the latest charges

# Utilities: months between two payments that still count as monthly (one month unpaid and the
# next one double is normal); such a skip is tolerated in up to half of the gaps.
UTILITY_MAX_GAP = 2
# "Price up" in Utilities only when sustained: the average of the last `RISE_MONTHS` months
# exceeds the previous `RISE_MONTHS` months' average by more than `UTILITY_RISE` and none of
# those last months falls below the previous average (a single expensive month doesn't trigger it).
UTILITY_RISE = Decimal("0.25")
RISE_MONTHS = 3
_CENT = Decimal("0.01")
installment_amount = loans.installment_amount  # a loan installment (`recurring_loans`)
_YEARLY_GAP_DAYS = 300  # median gap from which a marked series is taken as yearly

# Screen groups: stable key -> name, in order (the installments group is assigned by whoever
# knows the installments). Assignment goes by the category's reference, never by its name.
GROUPS: dict[str, str] = {
    key: t(f"analysis.recurring.group.{key}")
    for key in ("housing", "loans", "utilities", "insurance", "subscriptions", "fees", "other")
}
_GROUP_BY_REF = {
    categories.HOUSING: "housing",
    categories.LOANS: "loans",
    categories.UTILITIES: "utilities",
    categories.INSURANCE: "insurance",
    categories.SUBSCRIPTIONS: "subscriptions",
    categories.BANK_FEES: "fees",
}
_OTHER_GROUP = "other"
_USER_REF = "user:"  # `catalog.Category.ref` of a user category


@dataclass(frozen=True)
class Charge:
    day: date
    amount: Decimal
    fingerprint: str


@dataclass(frozen=True)
class PriceChange:
    before: Decimal
    after: Decimal
    day: date


@dataclass(frozen=True)
class Recurring:
    merchant: str
    currency: str
    category: str
    cadence: Cadence
    charges: tuple[Charge, ...]
    typical: Decimal
    variable: bool
    price_change: PriceChange | None
    category_key: str = ""  # stable reference (`Movement.ref`); empty: `category` is it
    name: str = ""  # display name (the provider's); empty: `merchant`
    members: tuple[str, ...] = ()  # the series' merchants; empty: only `merchant`
    extras: tuple[Charge, ...] = ()  # loans: the extra payments (not the installment)

    @property
    def category_ref(self) -> str:
        return self.category_key or self.category

    @property
    def display(self) -> str:
        return self.name or self.merchant

    @property
    def utility_monthly(self) -> bool:
        return self.category_ref == categories.UTILITIES and self.cadence == "monthly"

    @property
    def first_day(self) -> date:
        return self.charges[0].day

    @property
    def last_day(self) -> date:
        return self.charges[-1].day

    @property
    def monthly(self) -> Decimal:
        return self.typical / 12 if self.cadence == "yearly" else self.typical


# User categories suggested in Housing by their name (the first time and without forcing
# anything: a group chosen by hand wins). System categories always go by their reference.
# The pattern matches Spanish category names the user types (rent, maintenance, condo fees).
_USER_HOUSING = re.compile(r"^(ALQUILER(ES)?|RENTA|MANTENIMIENTO|CONDOMINIO)\b")  # spanish-data


def group_key_of(category: str, name: str = "") -> str:
    """Screen group key from the category's reference; a user category whose name (`name`)
    matches `_USER_HOUSING` (rent, maintenance, condo fees) is suggested in Housing."""
    if category.startswith(_USER_REF) and _USER_HOUSING.search(categories.clean(name)):
        return "housing"
    return _GROUP_BY_REF.get(category, _OTHER_GROUP)


def group_of(category: str) -> str:
    """Screen group name for the category (installments are assigned by whoever knows them)."""
    return GROUPS[group_key_of(category)]


def natural_key(movement: Movement) -> str:
    """A movement's series without manual unions: its provider (in Utilities) or its merchant."""
    if movement.ref == categories.UTILITIES:
        found = providers.provider_of(movement.merchant)
        if found is not None:
            return found.key
    return movement.merchant


def is_recharge(movement: Movement) -> bool:
    """A Utilities prepaid top-up: still an expense, but neither a bill nor recurring."""
    return movement.ref == categories.UTILITIES and providers.is_recharge(
        movement.description, movement.merchant
    )


def is_store_charge(movement: Movement) -> bool:
    """A Utilities purchase at a provider's store or center ("CLARO AGORA"): not the bill
    (`providers.store_of`)."""
    return (
        movement.ref == categories.UTILITIES and providers.store_of(movement.merchant) is not None
    )


def series_key(movement: Movement, unions: Mapping[str, str] | None = None) -> str | None:
    """The movement's series: its merchant's manual union, if any; otherwise the natural one.
    None for a top-up or a purchase at a provider's store (they go in none, unless the merchant
    is joined by hand)."""
    if is_recharge(movement):
        return None
    target = (unions or {}).get(movement.merchant)
    if target is not None:
        return target
    if is_store_charge(movement):
        return None
    return natural_key(movement)


def members(
    movements: Iterable[Movement], unions: Mapping[str, str] | None = None
) -> dict[str, frozenset[str]]:
    """Series key -> its merchants (in any currency)."""
    found: dict[str, set[str]] = defaultdict(set)
    for m in movements:
        key = series_key(m, unions)
        if key is not None:
            found[key].add(m.merchant)
    return {key: frozenset(names) for key, names in found.items()}


def display_name(key: str) -> str:
    """A series' display name: the provider's, or the merchant key."""
    return providers.display_name(key)


class JoinError(ValueError):
    """ "Join with..." or "Separate" does not apply (the message says why)."""


def join_plan(
    groups: Mapping[str, Collection[str]],
    key: str,
    target: str,
    unions: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """ "Join with...": the unions to save (merchant -> `target`) so the merchants of series
    `key` go in series `target` (another series of `groups` or a provider from the list).
    It also rewrites saved unions pointing at `key` (from merchants with no charges today), so
    none is left pointing at a series that no longer exists. `groups`: key -> merchants
    (`members`). `LookupError` if either does not exist."""
    if key not in groups:
        raise LookupError(t("analysis.recurring.unknown", series=key))
    if target not in groups and providers.by_key(target) is None:
        raise LookupError(t("analysis.recurring.unknown", series=target))
    if key == target:
        raise JoinError(t("analysis.recurring.already_joined"))
    names = set(groups[key]) | {m for m, t in (unions or {}).items() if t == key}
    return {name: target for name in sorted(names)}


def separate_plan(
    movements: Iterable[Movement], unions: Mapping[str, str], merchant: str
) -> str | None:
    """ "Separate": the union to save so the merchant goes alone; None deletes the one it has
    (without it, it already goes alone). `JoinError` if already alone; `LookupError` if it has
    no charges."""
    natural = {natural_key(m) for m in movements if m.merchant == merchant and not is_recharge(m)}
    if not natural:
        raise LookupError(t("analysis.recurring.unknown_merchant", merchant=merchant))
    current = unions.get(merchant)
    alone_by_nature = natural == {merchant}
    if current is not None and current != merchant:
        return None if alone_by_nature else merchant
    if current is None and not alone_by_nature:
        return merchant
    raise JoinError(t("analysis.recurring.already_separate"))


def mark_problem(movement: Movement) -> str:
    """Why the transaction cannot be marked "Is recurring..." (empty when it can)."""
    if movement.kind != "expense":
        return t("analysis.recurring.mark.not_expense")
    if movement.amount <= 0:
        return t("analysis.recurring.mark.refund")
    if is_recharge(movement):
        return t("analysis.recurring.mark.top_up")
    if is_store_charge(movement):
        return t("analysis.recurring.mark.store_purchase")
    return ""


def _grouped(
    movements: Iterable[Movement], unions: Mapping[str, str] | None
) -> dict[tuple[str, str], list[Movement]]:
    groups: dict[tuple[str, str], list[Movement]] = defaultdict(list)
    for m in movements:
        if m.amount <= 0:
            continue
        key = series_key(m, unions)
        if key is not None:
            groups[(key, m.currency)].append(m)
    for items in groups.values():
        items.sort(key=_by_day)
    return groups


def _by_day(m: Movement) -> tuple[date, str]:
    return (m.day, m.fingerprint)


def series(
    movements: Sequence[Movement],
    merchant: str,
    currency: str,
    unions: Mapping[str, str] | None = None,
) -> tuple[Charge, ...]:
    """Positive charges of a series (a merchant, a provider or a union) in one currency."""
    return _charges(_grouped(movements, unions).get((merchant, currency), []))


def detect(
    movements: Sequence[Movement], unions: Mapping[str, str] | None = None
) -> list[Recurring]:
    """Series that charge on their own every month or every year, sorted by key."""
    return detect_grouped(_grouped(movements, unions))


def detect_series(key: str, currency: str, items: list[Movement]) -> Recurring | None:
    """A single series (its charges from `group_movements`), if it charges on its own."""
    found = _detect_series(key, currency, items) if items else None
    return None if found is None else _named(found, key, items)


def detect_grouped(groups: Mapping[tuple[str, str], list[Movement]]) -> list[Recurring]:
    """`detect` over charges already grouped (`group_movements`)."""
    found = []
    for (key, currency), items in groups.items():
        recurring = _detect_series(key, currency, items)
        if recurring is not None:
            found.append(_named(recurring, key, items))
    return sorted(found, key=lambda r: r.merchant)


def group_movements(
    movements: Iterable[Movement], unions: Mapping[str, str] | None = None
) -> dict[tuple[str, str], list[Movement]]:
    """Each series' charges (key, currency), by date: group them once and pass them to
    `detect_grouped` and `marked_items`."""
    return _grouped(movements, unions)


def marked(
    movements: Sequence[Movement],
    key: str,
    currency: str,
    unions: Mapping[str, str] | None = None,
    cadence: Cadence | None = None,
) -> Recurring | None:
    """A series marked by hand (see `marked_items`)."""
    return marked_items(
        key, currency, _grouped(movements, unions).get((key, currency), []), cadence
    )


def marked_items(
    key: str, currency: str, items: Sequence[Movement], cadence: Cadence | None = None
) -> Recurring | None:
    """A series marked by hand, even if the rule does not detect it (or with the chosen
    cadence): its charges (`items`, from `group_movements`) without requiring a cadence. None if
    it has no charges."""
    if not items:
        return None
    main = _main_category(list(items))
    used: list[Movement] = list(items)
    extras: list[Movement] = []
    if main.ref == categories.LOANS:
        parts = loans.split(items)
        used, extras = parts.regular or list(items), parts.extras
    utility = main.ref == categories.UTILITIES
    charges = _month_charges(used) if utility else _charges(used)
    chosen = cadence or _fallback_cadence(charges)
    variable = utility and chosen == "monthly"
    if variable:
        typical = _average(_per_month(charges)[-_TYPICAL_CHARGES:])
    else:
        recent = charges[-1:] if chosen == "yearly" else charges[-_TYPICAL_CHARGES:]
        typical = median(c.amount for c in recent)
    found = Recurring(
        merchant=key,
        currency=currency,
        category=main.category,
        cadence=chosen,
        charges=charges,
        typical=typical,
        variable=variable,
        price_change=None,
        category_key=main.ref,
        extras=_charges(extras),
    )
    return _named(found, key, items)


def _named(found: Recurring, key: str, items: Sequence[Movement]) -> Recurring:
    names = tuple(sorted({m.merchant for m in items}))
    return replace(found, name=display_name(key), members=names)


def _fallback_cadence(charges: Sequence[Charge]) -> Cadence:
    """Yearly if the median days between charges reaches _YEARLY_GAP_DAYS; otherwise monthly."""
    gaps = [(b.day - a.day).days for a, b in zip(charges, charges[1:], strict=False)]
    return "yearly" if gaps and median(gaps) >= _YEARLY_GAP_DAYS else "monthly"


def _charges(items: Iterable[Movement]) -> tuple[Charge, ...]:
    return tuple(Charge(m.day, m.amount, m.fingerprint) for m in items)


def _detect_series(key: str, currency: str, items: list[Movement]) -> Recurring | None:
    main = _main_category(items)
    if main.ref == categories.UTILITIES:
        monthly = _utility(key, currency, items, main)
        if monthly is not None:
            return monthly
        yearly = _classify(key, currency, items)
        return yearly if yearly is not None and yearly.cadence == "yearly" else None
    if main.ref == categories.LOANS:
        return _loan(key, currency, items, main)
    return _classify(key, currency, items)


def _month_index(day: date) -> int:
    return day.year * 12 + day.month - 1


def _by_month(items: Iterable[Movement]) -> dict[int, list[Movement]]:
    found: dict[int, list[Movement]] = defaultdict(list)
    for m in items:
        found[_month_index(m.day)].append(m)
    return found


def _month_charges(items: Sequence[Movement]) -> tuple[Charge, ...]:
    """One charge per month: the sum paid, with the day and fingerprint of the last payment."""
    months = _by_month(items)
    found = []
    for index in sorted(months):
        paid = sorted(months[index], key=_by_day)
        total = sum((m.amount for m in paid), Decimal(0))
        found.append(Charge(paid[-1].day, total, paid[-1].fingerprint))
    return tuple(found)


def _per_month(charges: Sequence[Charge]) -> list[Decimal]:
    """What was paid spread per month: a payment after unpaid months also covers those months
    (a double payment after an empty month counts half and half)."""
    values: list[Decimal] = []
    previous: int | None = None
    for charge in charges:
        index = _month_index(charge.day)
        span = 1 if previous is None else max(1, index - previous)
        values.extend([charge.amount / span] * span)
        previous = index
    return values


def _average(values: Sequence[Decimal]) -> Decimal:
    return (sum(values, Decimal(0)) / len(values)).quantize(_CENT)


def _utility(key: str, currency: str, items: list[Movement], main: Movement) -> Recurring | None:
    """Utilities: each month's sum, tolerating unpaid months; the amount is always variable."""
    charges = _month_charges(items)
    months = [_month_index(c.day) for c in charges]
    start = len(months) - 1
    while start > 0 and months[start] - months[start - 1] <= UTILITY_MAX_GAP:
        start -= 1
    run = charges[start:]
    gaps = [b - a for a, b in zip(months[start:], months[start + 1 :], strict=False)]
    if len(run) < MONTHLY_MIN or sum(1 for g in gaps if g > 1) > len(gaps) // 2:
        return None
    spread = _per_month(run)
    return Recurring(
        merchant=key,
        currency=currency,
        category=main.category,
        cadence="monthly",
        charges=run,
        typical=_average(spread[-_TYPICAL_CHARGES:]),
        variable=True,
        price_change=sustained_rise(spread, run[-1].day),
        category_key=main.ref,
    )


def sustained_rise(spread: Sequence[Decimal], day: date) -> PriceChange | None:
    """Utilities "price up" (see `UTILITY_RISE`) over what was paid per month, or None."""
    if len(spread) < 2 * RISE_MONTHS:
        return None
    before = _average(spread[-2 * RISE_MONTHS : -RISE_MONTHS])
    recent = spread[-RISE_MONTHS:]
    after = _average(recent)
    if before <= 0 or after <= before * (1 + UTILITY_RISE) or min(recent) <= before:
        return None
    return PriceChange(before, after, day)


def _loan(key: str, currency: str, items: list[Movement], main: Movement) -> Recurring | None:
    """Loans: the series is the installment (`recurring_loans`); extra payments go apart and
    never trigger "price up"."""
    parts = loans.split(items)
    regular, extras = parts.regular, parts.extras
    found = _cadence(regular) if regular else None
    if found is None:
        return None
    cadence, used = found
    charges = _charges(used)
    first = charges[0].day
    return Recurring(
        merchant=key,
        currency=currency,
        category=main.category,
        cadence=cadence,
        charges=charges,
        typical=median(c.amount for c in charges[-_TYPICAL_CHARGES:]),
        variable=False,
        price_change=None,
        category_key=main.ref,
        extras=_charges(m for m in extras if m.day >= first),
    )


def _classify(merchant: str, currency: str, items: list[Movement]) -> Recurring | None:
    found = _cadence(items)
    if found is None:
        return None
    cadence, used = found

    charges = tuple(Charge(m.day, m.amount, m.fingerprint) for m in used)
    main = _main_category(used)
    amounts = _amounts(charges, main.ref)
    if amounts is None:
        return None
    variable, typical = amounts

    return Recurring(
        merchant=merchant,
        currency=currency,
        category=main.category,
        cadence=cadence,
        charges=charges,
        typical=typical,
        variable=variable,
        price_change=None if variable else _price_change(charges),
        category_key=main.ref,
    )


def _main_category(items: list[Movement]) -> Movement:
    """A charge with the series' most common category; on a tie, the most recent one's."""
    counts = Counter(m.ref for m in items)
    top = max(counts.values())
    return next(m for m in reversed(items) if counts[m.ref] == top)


def _last_run(items: list[Movement]) -> list[Movement]:
    """Charges since the last long pause (more than MONTHLY_SKIP_GAP[1] days without a charge)."""
    start = len(items) - 1
    while start > 0 and (items[start].day - items[start - 1].day).days <= MONTHLY_SKIP_GAP[1]:
        start -= 1
    return items[start:]


def _cadence(items: list[Movement]) -> tuple[Cadence, list[Movement]] | None:
    """Cadence and the charges that support it.

    Monthly is evaluated only over the last run (a pause or an old one-off purchase does not
    hide a current subscription); yearly, over the whole series.
    """
    run = _last_run(items)
    run_months = {m.month for m in run}
    if len(run) >= MONTHLY_MIN and len(run_months) == len(run) and _monthly_gaps(_gaps(run)):
        return "monthly", run
    if len(items) >= YEARLY_MIN and all(YEARLY_GAP[0] <= g <= YEARLY_GAP[1] for g in _gaps(items)):
        return "yearly", items
    return None


def _gaps(items: list[Movement]) -> list[int]:
    return [(b.day - a.day).days for a, b in zip(items, items[1:], strict=False)]


def _monthly_gaps(gaps: list[int]) -> bool:
    """Normal gaps, tolerating some skipped month (at most 1 in every 6 charges)."""
    skips = 0
    for gap in gaps:
        if MONTHLY_GAP[0] <= gap <= MONTHLY_GAP[1]:
            continue
        if MONTHLY_SKIP_GAP[0] <= gap <= MONTHLY_SKIP_GAP[1]:
            skips += 1
        else:
            return False
    return skips <= max(1, len(gaps) // 6)


def _relative_gap(amount: Decimal, reference: Decimal) -> Decimal:
    return abs(amount - reference) / reference


def _segments(charges: tuple[Charge, ...]) -> list[tuple[Charge, ...]]:
    """Price segments: a charge differing more than FIXED_TOLERANCE from the first opens one."""
    segments: list[list[Charge]] = []
    for c in charges:
        if segments and _relative_gap(c.amount, segments[-1][0].amount) <= FIXED_TOLERANCE:
            segments[-1].append(c)
        else:
            segments.append([c])
    return [tuple(s) for s in segments]


def _amounts(charges: tuple[Charge, ...], category: str) -> tuple[bool, Decimal] | None:
    """(variable, typical amount), or None if the amounts are scattered."""
    if category == categories.UTILITIES:
        center = median(c.amount for c in charges)
        spread = max(_relative_gap(c.amount, center) for c in charges)
        recent = [c.amount for c in charges[-_TYPICAL_CHARGES:]]
        if spread <= FIXED_TOLERANCE:
            return False, median(recent)
        if spread <= VARIABLE_TOLERANCE:
            return True, (sum(recent, Decimal(0)) / len(recent)).quantize(Decimal("0.01"))
        return None
    segments = _segments(charges)
    if any(len(s) < 2 for s in segments[1:-1]):
        return None  # a lone charge in the middle: a random amount, not a price change
    last = segments[-1]
    if len(segments) > 1 and len(last) == 1:
        before = median(c.amount for c in segments[-2])
        if _relative_gap(last[0].amount, before) > VARIABLE_TOLERANCE:
            return None  # jump too big: wait until it repeats
    return False, median(c.amount for c in last)


def _price_change(charges: tuple[Charge, ...]) -> PriceChange | None:
    """Last price change: from the previous segment's last charge to the last one's first."""
    segments = _segments(charges)
    if len(segments) < 2:
        return None
    before, first_new = segments[-2][-1], segments[-1][0]
    return PriceChange(before.amount, first_new.amount, first_new.day)
