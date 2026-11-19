"""Reservas para gastos que no son de cada mes (YNAB: «embrace your true expenses»). Lógica pura.

Una reserva es un plan virtual, sin mover dinero: un nombre, un monto estimado en RD$, una
categoría de gasto y sus vencimientos. **Modelo de vencimientos** (el mínimo que cubre «anual»,
«semestral» y «una vez en un mes concreto»): el primer vencimiento (`due_month`, AAAA-MM) y cada
cuántos meses se repite (`every_months`: 12 anual o 6 semestral; None: una sola vez, en ese mes).
Una que se repite vence cada N meses también hacia atrás: el primer vencimiento solo fija la fase
(«cada año en enero»), así un gasto del enero pasado es de ella.

**Aporte mensual** (`monthly_contribution`): monto / meses entre vencimientos. Si se repite, esos
meses son `every_months` (anual: monto / 12). Una sola vez: los meses desde el mes en que se creó
la reserva (`start_month`) hasta su vencimiento, **los dos incluidos** (`due - start + 1`): creada
el mismo mes en que vence, el aporte es el monto entero; ya vencida, 0. Se redondea **hacia arriba
a RD$ 100** (`CONTRIBUTION_STEP`), para que apartar eso cada mes nunca se quede corto. Una reserva
cuyo próximo vencimiento ya tiene su gasto vinculado (`paid_dues`) no suma al aporte del mes ni
sale en «Próximos gastos grandes».

Los gastos vinculados a una reserva (`links`, rol `'reserved'`) no cuentan contra el tope de su
categoría (`analysis.budget`) y se muestran «cubiertos por la reserva». Una reserva puede juntar
varios gastos (`multiple`, p. ej. Navidad). Las sugerencias de reservas están en
`reserve_suggestions`.

**Vínculo sugerido** («Para revisar», `reserva_posible`; `link_suggestions`). Nunca para un
vencimiento anterior al mes en que se creó la reserva.
- Una de un solo gasto: un gasto sin vínculo de la misma categoría, en un mes a ±`LINK_WINDOW`
  de un vencimiento, a ±`LINK_TOLERANCE` del estimado, si ese vencimiento no tiene ya uno.
- Una de varios gastos: solo gastos **del mes del vencimiento**, de la misma categoría, que no
  sean de un comercio recurrente, y solo **lo que excede lo habitual** de la categoría en ese mes
  (la mediana de los 6 meses completos anteriores, `habitual_before`): de mayor a menor, mientras
  lo ya vinculado más el gasto no pase de ese exceso ni del 150 % del estimado; los de menos del
  `MULTIPLE_MIN_SHARE` del estimado no se proponen. Sin habitual para ese mes, no se propone.
- Si un gasto cabe en dos reservas, se propone la de estimado más cercano a su monto.

Queda abierto (sin construir) comparar lo apartado con el saldo de una cuenta de reservas.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal

CONTRIBUTION_STEP = Decimal(100)
UPCOMING_DAYS = 60
LINK_WINDOW = 1  # meses antes o después de un vencimiento
LINK_TOLERANCE = Decimal("0.50")
MULTIPLE_MIN_SHARE = Decimal("0.05")
HABITUAL_MONTHS = 6
EVERY_CHOICES = (6, 12)  # cada 6 meses o cada año (None: una sola vez)
NAME_MAX = 80
AMOUNT_MAX = Decimal(100_000_000)

MONTH_NAMES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_ZERO = Decimal(0)

HabitualFor = Callable[[int, str], Decimal | None]


class ReserveError(ValueError):
    """Pedido inválido sobre una reserva (422)."""


@dataclass(frozen=True)
class Reserve:
    id: int
    name: str
    amount: Decimal  # RD$ estimados por vencimiento
    category_id: int
    due_month: str  # primer vencimiento, AAAA-MM
    every_months: int | None  # None: una sola vez
    multiple: bool = False
    members: tuple[str, ...] = ()  # huellas de los gastos vinculados
    created_month: str = ""  # el mes desde el que se aparta (`start_month`)
    source: str | None = None  # la clave de la sugerencia de la que salió


@dataclass(frozen=True)
class Spent:
    """Un gasto ya en RD$ (`dop` None: US$ sin tasa) con su categoría (id del catálogo)."""

    fingerprint: str
    day: date
    category_id: int | None
    dop: Decimal | None
    recurring: bool = False  # de un comercio recurrente (no se propone para varios gastos)

    @property
    def month(self) -> str:
        return self.day.strftime("%Y-%m")


# --- Meses ----------------------------------------------------------------------------------


def month_index(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def month_at(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_name(month: str) -> str:
    return MONTH_NAMES[int(month[5:7]) - 1]


def check_month(month: str) -> str:
    if len(month) != 7 or month[4] != "-" or not (month[:4] + month[5:]).isdigit():
        raise ReserveError("el vencimiento va como AAAA-MM")
    if not 1 <= int(month[5:]) <= 12:
        raise ReserveError("el mes del vencimiento va de 01 a 12")
    return month


def due_months(reserve: Reserve, start: str, end: str) -> list[str]:
    """Los vencimientos entre `start` y `end` (incluidos)."""
    first, low, high = month_index(reserve.due_month), month_index(start), month_index(end)
    if reserve.every_months is None:
        return [reserve.due_month] if low <= first <= high else []
    # Una que se repite vence cada `step` meses hacia adelante y hacia atrás: el primer
    # vencimiento solo fija la fase («cada año en enero»).
    step = reserve.every_months
    index = first + -(-(low - first) // step) * step
    found = []
    while index <= high:
        found.append(month_at(index))
        index += step
    return found


def next_due(reserve: Reserve, current: str) -> str | None:
    """El primer vencimiento desde `current` (incluido); None si fue de una vez y ya pasó."""
    found = due_months(reserve, current, month_at(month_index(current) + 12 * 50))
    return found[0] if found else None


def near_due(reserve: Reserve, month: str, window: int = LINK_WINDOW) -> str | None:
    """El vencimiento a ±`window` meses de `month` (el más cercano), o None."""
    index = month_index(month)
    found = due_months(reserve, month_at(index - window), month_at(index + window))
    return min(found, key=lambda d: (abs(month_index(d) - index), d), default=None)


def ceil_to(value: Decimal, step: Decimal) -> Decimal:
    """`value` redondeado hacia arriba a un múltiplo de `step`."""
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def next_of_month(number: int, current: str) -> str:
    """El próximo mes `number` (1-12) desde `current` (incluido)."""
    year = int(current[:4])
    if number < int(current[5:]):
        year += 1
    return f"{year:04d}-{number:02d}"


def monthly_contribution(reserve: Reserve, current: str) -> Decimal:
    """Cuánto apartar al mes (ver el docstring del módulo), redondeado hacia arriba a RD$ 100."""
    if reserve.every_months is not None:
        return ceil_to(reserve.amount / reserve.every_months, CONTRIBUTION_STEP)
    due = month_index(reserve.due_month)
    if due < month_index(current):
        return _ZERO
    start = month_index(reserve.created_month or current)
    return ceil_to(reserve.amount / max(1, due - start + 1), CONTRIBUTION_STEP)


def paid_dues(reserves: Iterable[Reserve], spent: Mapping[str, Spent]) -> set[tuple[int, str]]:
    """(reserva, vencimiento) que ya tienen un gasto vinculado (a ±`LINK_WINDOW` meses)."""
    found = set()
    for reserve in reserves:
        for fp in reserve.members:
            item = spent.get(fp)
            due = None if item is None else near_due(reserve, item.month)
            if due is not None:
                found.add((reserve.id, due))
    return found


def monthly_total(
    reserves: Iterable[Reserve], current: str, paid: Collection[tuple[int, str]] = ()
) -> Decimal:
    """Lo que se aparta al mes para todas, sin las que ya pagaron su próximo vencimiento."""
    return sum(
        (
            monthly_contribution(r, current)
            for r in reserves
            if (r.id, next_due(r, current)) not in paid
        ),
        _ZERO,
    )


@dataclass(frozen=True)
class YearStatus:
    spent: Decimal  # lo vinculado con fecha en el año, en RD$
    estimated: Decimal  # el monto por cada vencimiento del año
    without_rate: int  # gastos vinculados en US$ sin tasa (no suman)


def year_status(reserve: Reserve, year: int, spent: Mapping[str, Spent]) -> YearStatus:
    total, missing = _ZERO, 0
    for fp in reserve.members:
        item = spent.get(fp)
        if item is None or item.day.year != year:
            continue
        if item.dop is None:
            missing += 1
        else:
            total += item.dop
    dues = due_months(reserve, f"{year:04d}-01", f"{year:04d}-12")
    return YearStatus(total, reserve.amount * len(dues), missing)


def upcoming(
    reserves: Iterable[Reserve],
    today: date,
    days: int = UPCOMING_DAYS,
    paid: Collection[tuple[int, str]] = (),
) -> list[tuple[Reserve, str]]:
    """Las reservas que vencen desde este mes hasta `days` días después de hoy (el primer día del
    mes del vencimiento cae en ese plazo), la más próxima primero; sin las que ya tienen el gasto
    de ese vencimiento vinculado (`paid`)."""
    current = today.strftime("%Y-%m")
    limit = today + timedelta(days=days)
    found = []
    for reserve in reserves:
        due = next_due(reserve, current)
        if due is None or (reserve.id, due) in paid:
            continue
        if date(int(due[:4]), int(due[5:]), 1) <= limit:
            found.append((reserve, due))
    return sorted(found, key=lambda pair: (pair[1], pair[0].name, pair[0].id))


# --- Vínculos sugeridos -----------------------------------------------------------------------


def habitual_before(
    regular: Mapping[int, Mapping[str, Decimal]], complete: Sequence[str], category: int, month: str
) -> Decimal | None:
    """Lo habitual de la categoría en `month`: la mediana de lo gastado (sin gastos únicos) en los
    `HABITUAL_MONTHS` meses completos anteriores; None sin ninguno."""
    before = [m for m in sorted(set(complete)) if m < month][-HABITUAL_MONTHS:]
    if not before:
        return None
    usual = regular.get(category, {})
    return statistics.median(usual.get(m, _ZERO) for m in before)


def link_suggestions(
    expenses: Sequence[Spent],
    reserves: Sequence[Reserve],
    linked: Collection[str],
    habitual: HabitualFor | None = None,
) -> dict[str, int]:
    """Huella del gasto -> la reserva que se propone (ver el docstring del módulo). `linked`:
    las huellas que ya están en algún vínculo; `habitual(categoría, mes)`: lo habitual de la
    categoría en ese mes (para las de varios gastos; sin él no se proponen)."""
    by_fp = {e.fingerprint: e for e in expenses}
    choices: dict[str, list[tuple[Decimal, int, int]]] = defaultdict(list)
    for reserve in reserves:
        found = (
            _multiple(reserve, expenses, by_fp, linked, habitual)
            if reserve.multiple
            else _single(reserve, expenses, by_fp, linked)
        )
        for item, distance in found:
            score = abs(reserve.amount - (item.dop or _ZERO))
            choices[item.fingerprint].append((score, distance, reserve.id))
    return {fp: min(options)[2] for fp, options in choices.items()}


def _usable(item: Spent, linked: Collection[str]) -> bool:
    return item.fingerprint not in linked and item.dop is not None and item.dop > 0


def _started(reserve: Reserve, due: str) -> bool:
    return not reserve.created_month or due >= reserve.created_month


def _cycle(reserve: Reserve, due: str, by_fp: Mapping[str, Spent]) -> list[Spent]:
    return [
        by_fp[fp]
        for fp in reserve.members
        if fp in by_fp and near_due(reserve, by_fp[fp].month) == due
    ]


def _single(
    reserve: Reserve, expenses: Sequence[Spent], by_fp: Mapping[str, Spent], linked: Collection[str]
) -> list[tuple[Spent, int]]:
    low = reserve.amount * (1 - LINK_TOLERANCE)
    high = reserve.amount * (1 + LINK_TOLERANCE)
    found = []
    for item in expenses:
        if item.category_id != reserve.category_id or not _usable(item, linked):
            continue
        due = near_due(reserve, item.month)
        if due is None or not _started(reserve, due) or _cycle(reserve, due, by_fp):
            continue
        if low <= (item.dop or _ZERO) <= high:
            found.append((item, abs(month_index(due) - month_index(item.month))))
    return found


def _multiple(
    reserve: Reserve,
    expenses: Sequence[Spent],
    by_fp: Mapping[str, Spent],
    linked: Collection[str],
    habitual: HabitualFor | None,
) -> list[tuple[Spent, int]]:
    if habitual is None:
        return []
    by_month: dict[str, list[Spent]] = defaultdict(list)
    for item in expenses:
        if item.category_id == reserve.category_id:
            by_month[item.month].append(item)
    found = []
    for month, items in sorted(by_month.items()):
        if not due_months(reserve, month, month) or not _started(reserve, month):
            continue
        usual = habitual(reserve.category_id, month)
        if usual is None:
            continue
        total = sum((i.dop for i in items if i.dop is not None), _ZERO)
        already = sum((c.dop for c in _cycle(reserve, month, by_fp) if c.dop is not None), _ZERO)
        room = min(total - usual, reserve.amount * (1 + LINK_TOLERANCE)) - already
        floor = reserve.amount * MULTIPLE_MIN_SHARE
        for item in sorted(items, key=lambda i: (-(i.dop or _ZERO), i.fingerprint)):
            if not _usable(item, linked) or item.recurring:
                continue
            amount = item.dop or _ZERO
            if floor <= amount <= room:
                found.append((item, 0))
                room -= amount
    return found
