"""Budget and reserves for the web: builds the views from what is already loaded (pure functions).

The logic lives in `analysis.budget` (caps) and `analysis.reserves` (reserves and suggestions).
Here movements are converted to RD$ (their month's rate, `rate_for`; without a rate, kept apart),
given their category id and narrowed to the chosen accounts: spending, what reserves cover and
the suggestions come from the chosen accounts; the usual amount (and with it the initial caps and
the warnings) from all of them, because caps are for the whole household.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from michelito.analysis import budget, catalog, categories, reserves
from michelito.analysis import recurring as rec
from michelito.analysis import reserve_suggestions as suggest
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.recurring_marks import Mark
from michelito.analysis.reserves import Reserve
from michelito.analysis.spending import Movement
from michelito.web import recurring as recurring_view
from michelito.web import summary

_ZERO = Decimal(0)


@dataclass(frozen=True)
class Inputs:
    """What the views need (already read from the database)."""

    flow: Sequence[Movement]  # every movement, every account
    accounts: Sequence[AccountInfo]
    rates: Mapping[str, Rate]
    known: catalog.Catalog
    caps: Mapping[int, budget.Cap]
    reserves: Sequence[Reserve]
    today: date
    selected: frozenset[str] | None = None
    marks: Mapping[tuple[str, str], Mark] = field(default_factory=dict)
    unions: Mapping[str, str] = field(default_factory=dict)
    dismissed: Collection[str] = ()

    @property
    def current(self) -> str:
        return self.today.strftime("%Y-%m")

    @property
    def reserved(self) -> dict[str, int]:
        return {fp: r.id for r in self.reserves for fp in r.members}

    def mine(self) -> list[Movement]:
        return [m for m in self.flow if self.selected is None or m.account in self.selected]


def expense_categories(known: catalog.Catalog) -> list[catalog.Category]:
    """The expense categories that accept a cap or a reserve (not the ones only a link sets)."""
    return [
        c
        for c in known.items
        if c.kind == "expense" and c.ref not in categories.LINK_ONLY and not c.hidden
    ]


def category_id(known: catalog.Catalog, move: Movement) -> int | None:
    found = known.by_ref(move.ref) or known.by_name(move.category)
    return None if found is None else found.id


def items(inputs: Inputs, movements: Sequence[Movement]) -> list[budget.Item]:
    """Expenses in RD$ with their category (those of a deleted category are left out)."""
    reserved = inputs.reserved
    found = []
    for move in movements:
        if move.kind != "expense":
            continue
        category = category_id(inputs.known, move)
        if category is None:
            continue
        found.append(
            budget.Item(
                fingerprint=move.fingerprint,
                month=move.month,
                category_id=category,
                dop=to_dop(move.amount, move.currency, rate_for(inputs.rates, move.month)),
                one_off=move.one_off,
                reserved=move.fingerprint in reserved,
            )
        )
    return found


def complete_months(inputs: Inputs) -> list[str]:
    """The complete months across all accounts (like the unfiltered Summary)."""
    return [o.month for o in summary.month_options(inputs.flow, inputs.accounts) if not o.partial]


def usual_amounts(inputs: Inputs) -> dict[int, Decimal]:
    months = budget.reference_months(complete_months(inputs))
    return budget.habitual(items(inputs, inputs.flow), months)


@dataclass(frozen=True)
class BudgetView:
    active: bool
    month: str
    lines: list[budget.Line]
    names: dict[int, str]
    totals: budget.Totals
    reference_months: list[str]
    filtered: bool  # with an account filter: caps of all, spending of the chosen ones
    missing: list[str]  # accounts that don't have the month's complete statement yet


def missing_statements(inputs: Inputs, month: str) -> list[str]:
    """The accounts (among the chosen ones) missing the month's complete statement."""
    found = summary.coverage_for(inputs.accounts, inputs.selected, month)
    return [c.label for c in found if not c.complete]


def budget_view(inputs: Inputs, month: str) -> BudgetView:
    usual = usual_amounts(inputs)
    wanted = {c.id for c in expense_categories(inputs.known)} | set(inputs.caps)
    found = budget.lines(items(inputs, inputs.mine()), month, inputs.caps, usual, wanted)
    return BudgetView(
        active=bool(inputs.caps),
        month=month,
        lines=found,
        names={c.id: c.name for c in inputs.known.items},
        totals=budget.totals(found),
        reference_months=budget.reference_months(complete_months(inputs)),
        filtered=summary.selection(inputs.accounts, inputs.selected) is not None,
        missing=missing_statements(inputs, month),
    )


def initial_caps(inputs: Inputs) -> list[budget.Cap]:
    usual = usual_amounts(inputs)
    return budget.initial_caps((c.id for c in expense_categories(inputs.known)), usual)


# --- Reserves --------------------------------------------------------------------------------


@dataclass(frozen=True)
class MemberView:
    move: Movement
    dop: Decimal | None


@dataclass(frozen=True)
class ReserveView:
    reserve: Reserve
    category: str
    next_due: str | None
    monthly: Decimal
    year: reserves.YearStatus
    members: list[MemberView]
    paid: bool  # the next due date already has its expense linked


def spent_map(
    inputs: Inputs, movements: Sequence[Movement], recurring: Collection[str] = ()
) -> dict[str, reserves.Spent]:
    """Expenses in RD$ by fingerprint; `recurring`: the recurring merchants."""
    found = {}
    for move in movements:
        if move.kind != "expense":
            continue
        found[move.fingerprint] = reserves.Spent(
            move.fingerprint,
            move.day,
            category_id(inputs.known, move),
            to_dop(move.amount, move.currency, rate_for(inputs.rates, move.month)),
            move.merchant in recurring,
        )
    return found


def paid(inputs: Inputs) -> set[tuple[int, str]]:
    """(reserve, due month) pairs that already have their expense (across all accounts)."""
    return reserves.paid_dues(inputs.reserves, spent_map(inputs, inputs.flow))


def reserve_views(inputs: Inputs) -> list[ReserveView]:
    mine = inputs.mine()
    spent = spent_map(inputs, mine)
    done = paid(inputs)
    by_fp = {m.fingerprint: m for m in mine}
    found = []
    for reserve in inputs.reserves:
        category = inputs.known.by_id(reserve.category_id)
        members = [
            MemberView(by_fp[fp], spent[fp].dop if fp in spent else None)
            for fp in reserve.members
            if fp in by_fp
        ]
        members.sort(key=lambda m: (m.move.day, m.move.fingerprint), reverse=True)
        due = reserves.next_due(reserve, inputs.current)
        settled = (reserve.id, due) in done
        found.append(
            ReserveView(
                reserve=reserve,
                category="" if category is None else category.name,
                next_due=due,
                monthly=_ZERO
                if settled
                else reserves.monthly_contribution(reserve, inputs.current),
                year=reserves.year_status(reserve, inputs.today.year, spent),
                members=members,
                paid=settled,
            )
        )
    return sorted(found, key=lambda v: (v.next_due or "9999-99", v.reserve.name, v.reserve.id))


def monthly_total(inputs: Inputs) -> Decimal:
    return reserves.monthly_total(inputs.reserves, inputs.current, paid(inputs))


def _regular(inputs: Inputs, movements: Sequence[Movement]) -> dict[int, dict[str, Decimal]]:
    """Spending by category and month, without one-off expenses (in RD$; no rate, not counted)."""
    found: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for item in items(inputs, movements):
        if item.dop is not None and not item.one_off:
            found[item.category_id][item.month] += item.dop
    return found


def suggestions(inputs: Inputs) -> list[suggest.Suggestion]:
    """The reserve suggestions still standing (see `analysis.reserve_suggestions`)."""
    mine = inputs.mine()
    usable = [suggest.Category(c.id, c.name, c.ref) for c in expense_categories(inputs.known)]
    regular = _regular(inputs, mine)
    complete = complete_months(inputs)
    excluded = suggest.excluded_categories(
        usable, regular, _monthly_recurring(inputs, mine), complete, _groups(inputs)
    )
    history = suggest.from_history(regular, complete, usable, inputs.current, excluded)
    found = [*_recurring(inputs, mine), *history]
    return suggest.pending_suggestions(found, inputs.reserves, inputs.dismissed)


def _groups(inputs: Inputs) -> dict[int, str]:
    """The Recurring group key of each expense category (by its reference)."""
    return {c.id: rec.group_key_of(c.ref, c.name) for c in expense_categories(inputs.known)}


def _monthly_recurring(inputs: Inputs, mine: Sequence[Movement]) -> dict[int, dict[str, Decimal]]:
    """Spending (without one-offs) in monthly recurring series, by category and month."""
    overview = _overview_of(inputs, mine)
    if overview is None:
        return {}
    merchants: set[str] = set()
    for view in overview.items:
        if view.cadence == "monthly":
            merchants.update(view.members or (view.merchant,))
    chosen = [m for m in mine if m.merchant in merchants]
    return _regular(inputs, chosen)


def _overview_of(inputs: Inputs, movements: Sequence[Movement]) -> recurring_view.Overview | None:
    expenses = [m for m in movements if m.kind == "expense"]
    if not expenses:
        return None
    as_of = max(m.day for m in inputs.flow if m.kind == "expense")
    return recurring_view.build_overview(
        expenses, inputs.marks, inputs.rates, None, as_of=as_of, unions=inputs.unions
    )


def _recurring(inputs: Inputs, mine: Sequence[Movement]) -> list[suggest.Suggestion]:
    overview = _overview_of(inputs, mine)
    if overview is None:
        return []
    sources = []
    for view in overview.items:
        if view.cadence != "yearly" or view.status != "active" or view.yearly_dop is None:
            continue
        category = inputs.known.by_name(view.category)
        if category is None or category.kind != "expense":
            continue
        sources.append(
            suggest.RecurringSource(
                key=f"recurring:{view.merchant}:{view.currency}",
                name=view.name or view.merchant,
                category_id=category.id,
                yearly_dop=view.yearly_dop,
                last_day=view.last_day,
            )
        )
    return suggest.from_recurring(sources, inputs.current)


def recurring_merchants(inputs: Inputs) -> set[str]:
    """The merchants of the active recurring series (across all accounts)."""
    overview = _overview_of(inputs, inputs.flow)
    if overview is None:
        return set()
    found: set[str] = set()
    for view in overview.items:
        if view.status == "active":
            found.update(view.members or (view.merchant,))
    return found


def link_hints(inputs: Inputs, linked: Collection[str]) -> dict[str, Reserve]:
    """Fingerprint -> the reserve that "To review" proposes linking the expense to (across all
    accounts: the reserve is for the whole household). `linked`: fingerprints already in a link.
    Reserves with several expenses need the Recurring marks (`Inputs.marks`)."""
    if not inputs.reserves:
        return {}
    spent = list(spent_map(inputs, inputs.flow, recurring_merchants(inputs)).values())
    regular = _regular(inputs, inputs.flow)
    complete = complete_months(inputs)

    def usual(category: int, month: str) -> Decimal | None:
        return reserves.habitual_before(regular, complete, category, month)

    found = reserves.link_suggestions(spent, inputs.reserves, linked, usual)
    by_id = {r.id: r for r in inputs.reserves}
    return {fp: by_id[reserve_id] for fp, reserve_id in found.items()}


@dataclass(frozen=True)
class Overview:
    """The Summary card."""

    active: bool
    over_count: int | None  # None with an account filter (caps are for all accounts)
    over: Decimal
    monthly: Decimal  # what is set aside per month for all reserves
    upcoming: list[tuple[Reserve, str]]
    reserves: int
    missing: list[str]  # accounts without the month's complete statement


def overview(inputs: Inputs, month: str) -> Overview:
    view = budget_view(inputs, month) if inputs.caps else None
    done = paid(inputs)
    counted = view is not None and not view.filtered
    return Overview(
        active=view is not None,
        over_count=view.totals.over_count if counted and view else None,
        over=view.totals.over if counted and view else _ZERO,
        monthly=reserves.monthly_total(inputs.reserves, inputs.current, done),
        upcoming=reserves.upcoming(inputs.reserves, inputs.today, paid=done),
        reserves=len(inputs.reserves),
        missing=missing_statements(inputs, month),
    )
