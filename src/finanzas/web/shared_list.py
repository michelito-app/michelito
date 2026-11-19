"""Compartidos: todos los grupos compartidos en una pantalla, de todos los meses.

- **Una fila por grupo** con gastos presentes (`shared.states`), con su estado: "pending" si
  algún gasto tiene pendiente; "written_off" si se marcó "No me lo van a pagar" y algo volvió a
  tus gastos; si no, "settled" (también uno dado por perdido que ya estaba saldado).
- **Pagado**: Σ montos de los gastos (antes de repartir), por moneda. **Te devolvieron**: Σ los
  reembolsos (enlazados y a mano), por la moneda de cada uno: el dinero que entró, con lo que
  sobró (el exceso del grupo se muestra aparte).
- **Orden**: la última actividad (el gasto o el reembolso más reciente) primero; a igualdad, el
  grupo más nuevo (id mayor).
- **Cuentas**: con cuentas elegidas, un grupo cuenta si alguno de sus gastos es de ellas (como
  Pendientes).
- **Totales**: «Te deben» es el mismo cálculo que Pendientes para los grupos
  (`pending.build_pending`: lo pendiente en US$ a la tasa más reciente; sin ninguna, aparte);
  «Te devolvieron este año», los reembolsos con fecha en el año de `today`, cada uno en RD$ a la
  tasa de su mes (o la del mes anterior más cercano) y, sin tasa, aparte; y cuántos grupos tienen
  pendiente.
- **Nuevo grupo** (`new_candidates`): gastos sin vínculo de los últimos NEW_WINDOW_DAYS días
  (respecto de `today`), sin las categorías que nunca se comparten (`NOT_SHARED_EXPENSE`), de
  las cuentas elegidas. Primero los *sugeridos* (`is_suggested`: categoría en
  SHAREABLE_CATEGORIES, por su referencia, y monto de al menos SUGGEST_MIN_DOP en RD$, lo que
  está en US$ a la tasa de su mes o la del anterior más cercano; sin ninguna, no se sugiere);
  luego los demás. En cada
  bloque, el más reciente primero.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from finanzas.analysis import categories, shared
from finanzas.analysis.links import Links
from finanzas.analysis.rates import Rate, rate_for, to_dop
from finanzas.analysis.shared import ExpenseState, Refund, SharedState
from finanzas.analysis.spending import Movement
from finanzas.web import pending as pending_view

NEW_WINDOW_DAYS = shared.PICK_WINDOW_DAYS  # «Nuevo grupo…»: gastos de los últimos 120 días
# «Nuevo grupo…» sugiere (arriba) los gastos de estas categorías que tiene sentido compartir…
SHAREABLE_CATEGORIES = frozenset(
    {
        categories.RESTAURANTS,
        categories.DELIVERY,
        categories.GROCERIES,
        categories.ENTERTAINMENT,
        categories.TRAVEL,
        categories.SHOPPING,
        categories.ONLINE,
        categories.HOME,
        categories.OTHER,
    }
)
SUGGEST_MIN_DOP = Decimal(2000)  # …de al menos este monto en RD$
_ZERO = Decimal(0)
_USD = "USD"

Status = Literal["pending", "settled", "written_off"]


@dataclass(frozen=True)
class RefundRow:
    """Un reembolso del grupo como se lista: un crédito enlazado o uno a mano."""

    key: str  # la huella del crédito o "manual:<id>"
    day: date
    description: str  # el comercio o la descripción del crédito; a mano, la persona (o "")
    account_label: str  # la cuenta del crédito; a mano, "" (efectivo) o el "dónde"
    amount: Decimal  # positivo, en `currency`
    currency: str
    manual: bool


@dataclass(frozen=True)
class GroupRow:
    state: SharedState
    status: Status
    last_activity: date
    refunds: tuple[RefundRow, ...]  # en el orden en que se imputan
    paid: tuple[tuple[str, Decimal], ...]  # Σ montos de los gastos, por moneda
    reimbursed: tuple[tuple[str, Decimal], ...]  # Σ reembolsos, por su moneda
    pending: tuple[tuple[str, Decimal], ...]  # te deben, por moneda (solo las que tienen algo)
    pending_dop: Decimal | None  # ≈ RD$ de lo pendiente (None: sin pendiente o sin tasa)
    unconverted_usd: Decimal  # US$ pendientes sin ninguna tasa

    @property
    def expenses(self) -> tuple[ExpenseState, ...]:
        return self.state.expenses

    @property
    def first_day(self) -> date:
        return self.state.first.day

    @property
    def last_day(self) -> date:
        return self.state.last_day


@dataclass(frozen=True)
class SharedList:
    rows: tuple[GroupRow, ...]  # la última actividad primero
    owed_dop: Decimal  # te deben, en RD$ (sin los US$ sin tasa)
    unconverted_owed_usd: Decimal
    reimbursed_year_dop: Decimal  # te devolvieron en el año de `today`, en RD$
    unconverted_reimbursed_usd: Decimal
    rate: Rate | None  # la más reciente: la de lo pendiente en US$

    @property
    def open_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "pending")


def status_of(state: SharedState) -> Status:
    if state.has_pending:
        return "pending"
    if state.link.written_off and any(e.written_off > 0 for e in state.expenses):
        return "written_off"
    return "settled"


def last_activity(state: SharedState) -> date:
    """El gasto o el reembolso más reciente del grupo."""
    return max([state.last_day, *(r.day for r in state.refunds)])


def picked(state: SharedState, chosen: Collection[str] | None) -> bool:
    """El grupo cuenta con estas cuentas: alguno de sus gastos es de ellas (None: todas)."""
    return chosen is None or any(e.move.account in chosen for e in state.expenses)


def newest_first(states: Iterable[SharedState]) -> list[SharedState]:
    return sorted(states, key=lambda s: (last_activity(s), s.id), reverse=True)


def _by_currency(values: Iterable[tuple[str, Decimal]]) -> tuple[tuple[str, Decimal], ...]:
    found: dict[str, Decimal] = {}
    for currency, value in values:
        found[currency] = found.get(currency, _ZERO) + value
    return tuple(sorted(found.items()))


def refund_rows(
    state: SharedState, by_fingerprint: Mapping[str, Movement], labels: Mapping[str, str]
) -> tuple[RefundRow, ...]:
    manual = {f"manual:{m.id}": m for m in state.link.manual}
    rows = []
    for refund in state.refunds:
        entry = manual.get(refund.key)
        if entry is not None:
            rows.append(_row(refund, entry.person, entry.place, manual=True))
            continue
        move = by_fingerprint[refund.key]
        label = labels.get(move.account, move.account)
        rows.append(_row(refund, move.merchant or move.description, label, manual=False))
    return tuple(rows)


def _row(refund: Refund, description: str, account: str, *, manual: bool) -> RefundRow:
    return RefundRow(
        refund.key, refund.day, description, account, refund.amount, refund.currency, manual
    )


def reimbursed_in_year(
    refunds: Iterable[Refund], year: int, rates: Mapping[str, Rate]
) -> tuple[Decimal, Decimal]:
    """Los reembolsos con fecha en `year`, en RD$ a la tasa de su mes; y los US$ sin tasa."""
    dop, unconverted = _ZERO, _ZERO
    for refund in refunds:
        if refund.day.year != year:
            continue
        value = to_dop(
            refund.amount, refund.currency, rate_for(rates, refund.day.strftime("%Y-%m"))
        )
        if value is None:
            unconverted += refund.amount
        else:
            dop += value
    return dop, unconverted


def build_shared_list(
    movements: Sequence[Movement],
    groups: Mapping[int, SharedState],
    labels: Mapping[str, str],
    rates: Mapping[str, Rate],
    today: date,
    chosen: Collection[str] | None = None,
) -> SharedList:
    """Las filas y los totales de Compartidos. `chosen`: claves de las cuentas (None: todas)."""
    by_fp = {m.fingerprint: m for m in movements}
    shown = newest_first(s for s in groups.values() if picked(s, chosen))
    owed = pending_view.build_pending(movements, groups, {}, labels, rates, today, chosen)
    items = {i.link_id: i for i in owed.owed_to_me}
    rows = tuple(_group_row(s, by_fp, labels, items.get(s.id)) for s in shown)
    year_dop, year_unconverted = reimbursed_in_year(
        (r for s in shown for r in s.refunds), today.year, rates
    )
    return SharedList(
        rows=rows,
        owed_dop=sum((r.pending_dop for r in rows if r.pending_dop is not None), _ZERO),
        unconverted_owed_usd=owed.unconverted_owed_to_me,
        reimbursed_year_dop=year_dop,
        unconverted_reimbursed_usd=year_unconverted,
        rate=owed.rate,
    )


def _group_row(
    state: SharedState,
    by_fp: Mapping[str, Movement],
    labels: Mapping[str, str],
    item: pending_view.PendingItem | None,
) -> GroupRow:
    pending = tuple(sorted(state.pending.items()))
    return GroupRow(
        state=state,
        status=status_of(state),
        last_activity=last_activity(state),
        refunds=refund_rows(state, by_fp, labels),
        paid=_by_currency((e.currency, e.amount) for e in state.expenses),
        reimbursed=_by_currency((r.currency, r.amount) for r in state.refunds),
        pending=pending,
        pending_dop=None if item is None else item.pending_dop,
        unconverted_usd=_unconverted(item),
    )


def _unconverted(item: pending_view.PendingItem | None) -> Decimal:
    """Los US$ pendientes de la fila que no pasaron a RD$ (como los cuenta Pendientes)."""
    if item is None:
        return _ZERO
    if item.pending_dop is None:
        return sum((v for c, v in item.parts if c == _USD), _ZERO)
    return item.unconverted_usd


@dataclass(frozen=True)
class NewCandidate:
    """Una opción de «Nuevo grupo…»: el gasto y si se sugiere (va arriba)."""

    move: Movement
    suggested: bool


def is_suggested(move: Movement, rates: Mapping[str, Rate]) -> bool:
    """Un gasto que tiene sentido compartir: de SHAREABLE_CATEGORIES (por su referencia, así que
    renombrar la categoría no cambia nada) y de al menos SUGGEST_MIN_DOP en RD$. Lo que no está
    en pesos se convierte a la tasa de su mes; sin tasa (ni de un mes anterior), no se sugiere."""
    if move.ref not in SHAREABLE_CATEGORIES:
        return False
    value = to_dop(shared.gross(move), move.currency, rate_for(rates, move.month))
    return value is not None and value >= SUGGEST_MIN_DOP


def new_candidates(
    movements: Iterable[Movement],
    links: Links,
    today: date,
    rates: Mapping[str, Rate],
    chosen: Collection[str] | None = None,
) -> list[NewCandidate]:
    """«Nuevo grupo…»: gastos sin vínculo de los últimos NEW_WINDOW_DAYS días que se pueden
    compartir, de las cuentas elegidas; primero los sugeridos y luego los demás, en cada bloque
    el más reciente primero."""
    found = [
        NewCandidate(m, is_suggested(m, rates))
        for m in movements
        if shared.is_shareable(m)
        and not m.link
        and not links.is_linked(m.fingerprint)
        and m.ref not in shared.NOT_SHARED_EXPENSE
        and 0 <= (today - m.day).days <= NEW_WINDOW_DAYS
        and (chosen is None or m.account in chosen)
    ]
    return sorted(found, key=lambda c: (c.suggested, c.move.day, c.move.fingerprint), reverse=True)
