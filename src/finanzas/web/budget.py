"""Presupuesto y reservas para la web: arma las vistas a partir de lo ya cargado (funciones puras).

La lógica está en `analysis.budget` (topes) y `analysis.reserves` (reservas y sugerencias). Aquí
se pasan los movimientos a RD$ (la tasa de su mes, `rate_for`; sin tasa, aparte), se les pone el
id de su categoría y se recortan a las cuentas elegidas: lo gastado, lo cubierto por reservas y
las sugerencias salen de las elegidas; lo habitual (y con él los topes iniciales y los avisos),
de todas, porque los topes son de toda la casa.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from finanzas.analysis import budget, catalog, categories, reserves
from finanzas.analysis import recurring as rec
from finanzas.analysis import reserve_suggestions as suggest
from finanzas.analysis.accounts import AccountInfo
from finanzas.analysis.rates import Rate, rate_for, to_dop
from finanzas.analysis.recurring_marks import Mark
from finanzas.analysis.reserves import Reserve
from finanzas.analysis.spending import Movement
from finanzas.web import recurring as recurring_view
from finanzas.web import summary

_ZERO = Decimal(0)


@dataclass(frozen=True)
class Inputs:
    """Lo que hace falta para las vistas (ya leído de la base)."""

    flow: Sequence[Movement]  # todos los movimientos, todas las cuentas
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
    """Las categorías de gasto que admiten tope o reserva (sin las que solo pone un vínculo)."""
    return [
        c
        for c in known.items
        if c.kind == "gasto" and c.ref not in categories.LINK_ONLY and not c.hidden
    ]


def category_id(known: catalog.Catalog, move: Movement) -> int | None:
    found = known.by_ref(move.ref) or known.by_name(move.category)
    return None if found is None else found.id


def items(inputs: Inputs, movements: Sequence[Movement]) -> list[budget.Item]:
    """Los gastos en RD$ con su categoría (los de una categoría que ya no existe, fuera)."""
    reserved = inputs.reserved
    found = []
    for move in movements:
        if move.kind != "gasto":
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
    """Los meses completos con todas las cuentas (como el Resumen sin filtro)."""
    return [o.month for o in summary.month_options(inputs.flow, inputs.accounts) if not o.partial]


def habitual(inputs: Inputs) -> dict[int, Decimal]:
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
    filtered: bool  # con un filtro de cuentas: topes de todas, lo gastado de las elegidas
    missing: list[str]  # cuentas que todavía no tienen el estado completo del mes


def missing_statements(inputs: Inputs, month: str) -> list[str]:
    """Las cuentas (de las elegidas) a las que les falta el estado completo del mes."""
    found = summary.coverage_for(inputs.accounts, inputs.selected, month)
    return [c.label for c in found if not c.complete]


def budget_view(inputs: Inputs, month: str) -> BudgetView:
    usual = habitual(inputs)
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
    usual = habitual(inputs)
    return budget.initial_caps((c.id for c in expense_categories(inputs.known)), usual)


# --- Reservas --------------------------------------------------------------------------------


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
    paid: bool  # el próximo vencimiento ya tiene su gasto vinculado


def spent_map(
    inputs: Inputs, movements: Sequence[Movement], recurring: Collection[str] = ()
) -> dict[str, reserves.Spent]:
    """Los gastos en RD$ por huella; `recurring`: los comercios recurrentes."""
    found = {}
    for move in movements:
        if move.kind != "gasto":
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
    """(reserva, vencimiento) que ya tienen su gasto (con todas las cuentas)."""
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
    """Lo gastado por categoría y mes, sin gastos únicos (en RD$; sin tasa no suma)."""
    found: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for item in items(inputs, movements):
        if item.dop is not None and not item.one_off:
            found[item.category_id][item.month] += item.dop
    return found


def suggestions(inputs: Inputs) -> list[suggest.Suggestion]:
    """Las sugerencias de reservas que siguen en pie (ver `analysis.reserve_suggestions`)."""
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
    """La clave del grupo de Recurrentes de cada categoría de gasto (por su referencia)."""
    return {c.id: rec.group_key_of(c.ref, c.name) for c in expense_categories(inputs.known)}


def _monthly_recurring(inputs: Inputs, mine: Sequence[Movement]) -> dict[int, dict[str, Decimal]]:
    """Lo gastado (sin gastos únicos) en series recurrentes mensuales, por categoría y mes."""
    overview = _overview_of(inputs, mine)
    if overview is None:
        return {}
    merchants: set[str] = set()
    for view in overview.items:
        if view.cadence == "mensual":
            merchants.update(view.members or (view.merchant,))
    chosen = [m for m in mine if m.merchant in merchants]
    return _regular(inputs, chosen)


def _overview_of(inputs: Inputs, movements: Sequence[Movement]) -> recurring_view.Overview | None:
    expenses = [m for m in movements if m.kind == "gasto"]
    if not expenses:
        return None
    as_of = max(m.day for m in inputs.flow if m.kind == "gasto")
    return recurring_view.build_overview(
        expenses, inputs.marks, inputs.rates, None, as_of=as_of, unions=inputs.unions
    )


def _recurring(inputs: Inputs, mine: Sequence[Movement]) -> list[suggest.Suggestion]:
    overview = _overview_of(inputs, mine)
    if overview is None:
        return []
    sources = []
    for view in overview.items:
        if view.cadence != "anual" or view.status != "activo" or view.yearly_dop is None:
            continue
        category = inputs.known.by_name(view.category)
        if category is None or category.kind != "gasto":
            continue
        sources.append(
            suggest.RecurringSource(
                key=f"recurrente:{view.merchant}:{view.currency}",
                name=view.name or view.merchant,
                category_id=category.id,
                yearly_dop=view.yearly_dop,
                last_day=view.last_day,
            )
        )
    return suggest.from_recurring(sources, inputs.current)


def recurring_merchants(inputs: Inputs) -> set[str]:
    """Los comercios de los recurrentes activos (con todas las cuentas)."""
    overview = _overview_of(inputs, inputs.flow)
    if overview is None:
        return set()
    found: set[str] = set()
    for view in overview.items:
        if view.status == "activo":
            found.update(view.members or (view.merchant,))
    return found


def link_hints(inputs: Inputs, linked: Collection[str]) -> dict[str, Reserve]:
    """Huella -> la reserva a la que «Para revisar» propone vincular el gasto (con todas las
    cuentas: la reserva es de toda la casa). `linked`: huellas que ya están en un vínculo. Para
    las de varios gastos hacen falta las marcas de Recurrentes (`Inputs.marks`)."""
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
    """La tarjeta del Resumen."""

    active: bool
    over_count: int | None  # None con un filtro de cuentas (los topes son de todas)
    over: Decimal
    monthly: Decimal  # lo que se aparta al mes para todas las reservas
    upcoming: list[tuple[Reserve, str]]
    reserves: int
    missing: list[str]  # cuentas sin el estado completo del mes


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
