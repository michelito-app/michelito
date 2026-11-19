"""Detección de cargos recurrentes (mensuales y anuales) sobre los movimientos de tarjeta.

Funciones puras: reciben movimientos ya cargados y no tocan la base de datos.
Solo cuentan los cobros (monto positivo); las devoluciones se ignoran.

Una *serie* es lo que se mide junto: por defecto, un comercio en una moneda. Hay tres
excepciones (`series_key`):
- en Servicios, los comercios de un mismo proveedor de la lista (`providers`) forman una sola
  serie, y el cobro de cada mes es la suma de lo pagado ese mes (`_utility`);
- un comercio unido a mano a otro (o a un proveedor) va en la serie de ese (`unions`);
- las recargas prepago de Servicios no van en ninguna.
En Préstamos solo cuenta la cuota (el monto que se repite); los demás pagos son abonos extra
(`_loan`).
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

from finanzas.analysis import categories, providers
from finanzas.analysis import recurring_loans as loans
from finanzas.analysis.spending import Movement

Cadence = Literal["mensual", "anual"]

MONTHLY_MIN = 3
MONTHLY_GAP = (20, 40)  # días entre cobros consecutivos
MONTHLY_SKIP_GAP = (41, 80)  # un mes saltado entre dos cobros
YEARLY_MIN = 2
YEARLY_GAP = (330, 400)
FIXED_TOLERANCE = Decimal("0.10")
VARIABLE_TOLERANCE = Decimal("0.50")
INACTIVE_FACTOR = Decimal("1.5")

_TYPICAL_CHARGES = 3  # el monto típico es la mediana de los últimos cobros

# Servicios: meses entre dos pagos que siguen siendo mensuales (uno sin pago y el siguiente
# doble es normal); se tolera un salto así en hasta la mitad de las brechas.
UTILITY_MAX_GAP = 2
# «Subió» en Servicios solo si es sostenido: el promedio de los últimos `RISE_MONTHS` meses
# supera en más de `UTILITY_RISE` al de los `RISE_MONTHS` anteriores y ninguno de esos últimos
# meses queda por debajo del promedio anterior (un mes caro suelto no lo dispara).
UTILITY_RISE = Decimal("0.25")
RISE_MONTHS = 3
_CENT = Decimal("0.01")
installment_amount = loans.installment_amount  # la cuota de un préstamo (`recurring_loans`)
_YEARLY_GAP_DAYS = 300  # mediana de brechas desde la cual una serie marcada se toma por anual

# Grupos de pantalla: clave estable -> nombre, en orden («Cuotas» lo asigna quien conoce las
# cuotas). La asignación es por la referencia de la categoría, nunca por su nombre.
GROUPS: dict[str, str] = {
    "vivienda": "Vivienda",
    "prestamos": "Préstamos",
    "servicios": "Servicios",
    "seguros": "Seguros",
    "suscripciones": "Suscripciones",
    "cargos": "Cargos del banco",
    "otros": "Otros recurrentes",
}
_GROUP_BY_REF = {
    categories.HOUSING: "vivienda",
    categories.LOANS: "prestamos",
    categories.UTILITIES: "servicios",
    categories.INSURANCE: "seguros",
    categories.SUBSCRIPTIONS: "suscripciones",
    categories.BANK_FEES: "cargos",
}
_OTHER_GROUP = "otros"
_USER_REF = "user:"  # `catalog.Category.ref` de una categoría del usuario


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
    category_key: str = ""  # referencia estable (`Movement.ref`); vacía: `category` lo es
    name: str = ""  # nombre visible (el del proveedor); vacío: `merchant`
    members: tuple[str, ...] = ()  # los comercios de la serie; vacío: solo `merchant`
    extras: tuple[Charge, ...] = ()  # préstamos: los abonos extra (no son la cuota)

    @property
    def category_ref(self) -> str:
        return self.category_key or self.category

    @property
    def display(self) -> str:
        return self.name or self.merchant

    @property
    def utility_monthly(self) -> bool:
        return self.category_ref == categories.UTILITIES and self.cadence == "mensual"

    @property
    def first_day(self) -> date:
        return self.charges[0].day

    @property
    def last_day(self) -> date:
        return self.charges[-1].day

    @property
    def monthly(self) -> Decimal:
        return self.typical / 12 if self.cadence == "anual" else self.typical


# Categorías del usuario que se sugieren en Vivienda por su nombre (la primera vez y sin forzar
# nada: el grupo elegido a mano manda). Las del sistema van siempre por su referencia.
_USER_HOUSING = re.compile(r"^(ALQUILER(ES)?|RENTA|MANTENIMIENTO|CONDOMINIO)\b")


def group_key_of(category: str, name: str = "") -> str:
    """Clave del grupo de pantalla según la referencia de la categoría; una del usuario cuyo
    nombre (`name`) es «Alquiler», «Renta», «Mantenimiento» o «Condominio» se sugiere en
    Vivienda."""
    if category.startswith(_USER_REF) and _USER_HOUSING.search(categories.clean(name)):
        return "vivienda"
    return _GROUP_BY_REF.get(category, _OTHER_GROUP)


def group_of(category: str) -> str:
    """Grupo de pantalla según la categoría ("Cuotas" lo asigna quien conoce las cuotas)."""
    return GROUPS[group_key_of(category)]


def natural_key(movement: Movement) -> str:
    """La serie de un movimiento sin uniones a mano: su proveedor (en Servicios) o su comercio."""
    if movement.ref == categories.UTILITIES:
        found = providers.provider_of(movement.merchant)
        if found is not None:
            return found.key
    return movement.merchant


def is_recharge(movement: Movement) -> bool:
    """Una recarga prepago de Servicios: sigue siendo gasto, pero ni factura ni recurrente."""
    return movement.ref == categories.UTILITIES and providers.is_recharge(
        movement.description, movement.merchant
    )


def is_store_charge(movement: Movement) -> bool:
    """Una compra en Servicios en una tienda o centro de un proveedor («CLARO AGORA»): no es la
    factura (`providers.store_of`)."""
    return (
        movement.ref == categories.UTILITIES and providers.store_of(movement.merchant) is not None
    )


def series_key(movement: Movement, unions: Mapping[str, str] | None = None) -> str | None:
    """La serie del movimiento: la unión a mano de su comercio, si hay; si no, la natural. None
    para una recarga o una compra en una tienda del proveedor (no van en ninguna, salvo que el
    comercio se una a mano)."""
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
    """Clave de serie -> sus comercios (en cualquier moneda)."""
    found: dict[str, set[str]] = defaultdict(set)
    for m in movements:
        key = series_key(m, unions)
        if key is not None:
            found[key].add(m.merchant)
    return {key: frozenset(names) for key, names in found.items()}


def display_name(key: str) -> str:
    """El nombre visible de una serie: el del proveedor o la clave del comercio."""
    return providers.display_name(key)


class JoinError(ValueError):
    """«Unir con…» o «Separar» no aplica (el mensaje dice por qué)."""


def join_plan(
    groups: Mapping[str, Collection[str]],
    key: str,
    target: str,
    unions: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """«Unir con…»: las uniones a guardar (comercio -> `target`) para que los comercios de la
    serie `key` vayan en la serie `target` (otra serie de `groups` o un proveedor de la lista).
    También reescribe las uniones guardadas que apuntan a `key` (de comercios sin cobros hoy),
    así ninguna queda apuntando a una serie que ya no existe. `groups`: clave -> comercios
    (`members`). `LookupError` si alguna no existe."""
    if key not in groups:
        raise LookupError(f"recurrente desconocido: {key}")
    if target not in groups and providers.by_key(target) is None:
        raise LookupError(f"recurrente desconocido: {target}")
    if key == target:
        raise JoinError("ya están juntos")
    names = set(groups[key]) | {m for m, t in (unions or {}).items() if t == key}
    return {name: target for name in sorted(names)}


def separate_plan(
    movements: Iterable[Movement], unions: Mapping[str, str], merchant: str
) -> str | None:
    """«Separar»: la unión a guardar para que el comercio vaya solo; None borra la que tiene
    (sin ella ya va solo). `JoinError` si ya va solo; `LookupError` si no tiene cobros."""
    natural = {natural_key(m) for m in movements if m.merchant == merchant and not is_recharge(m)}
    if not natural:
        raise LookupError(f"comercio desconocido: {merchant}")
    current = unions.get(merchant)
    alone_by_nature = natural == {merchant}
    if current is not None and current != merchant:
        return None if alone_by_nature else merchant
    if current is None and not alone_by_nature:
        return merchant
    raise JoinError("ya va por separado")


def mark_problem(movement: Movement) -> str:
    """Por qué la transacción no se puede marcar «Es recurrente…» (vacío si se puede)."""
    if movement.kind != "gasto":
        return "Solo un gasto puede ser recurrente."
    if movement.amount <= 0:
        return "Una devolución no es un cobro recurrente."
    if is_recharge(movement):
        return "Las recargas prepago no son recurrentes."
    if is_store_charge(movement):
        return "Parece una compra en una tienda del proveedor, no el pago de la factura."
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
    """Cobros positivos de una serie (un comercio, un proveedor o una unión) en una moneda."""
    return _charges(_grouped(movements, unions).get((merchant, currency), []))


def detect(
    movements: Sequence[Movement], unions: Mapping[str, str] | None = None
) -> list[Recurring]:
    """Series que cobran solas cada mes o cada año, ordenadas por clave."""
    return detect_grouped(_grouped(movements, unions))


def detect_series(key: str, currency: str, items: list[Movement]) -> Recurring | None:
    """Una sola serie (sus cobros de `group_movements`), si cobra sola."""
    found = _detect_series(key, currency, items) if items else None
    return None if found is None else _named(found, key, items)


def detect_grouped(groups: Mapping[tuple[str, str], list[Movement]]) -> list[Recurring]:
    """`detect` sobre los cobros ya agrupados (`group_movements`)."""
    found = []
    for (key, currency), items in groups.items():
        recurring = _detect_series(key, currency, items)
        if recurring is not None:
            found.append(_named(recurring, key, items))
    return sorted(found, key=lambda r: r.merchant)


def group_movements(
    movements: Iterable[Movement], unions: Mapping[str, str] | None = None
) -> dict[tuple[str, str], list[Movement]]:
    """Los cobros de cada serie (clave, moneda), por fecha: agrúpalos una vez y pásalos a
    `detect_grouped` y `marked_items`."""
    return _grouped(movements, unions)


def marked(
    movements: Sequence[Movement],
    key: str,
    currency: str,
    unions: Mapping[str, str] | None = None,
    cadence: Cadence | None = None,
) -> Recurring | None:
    """Una serie marcada a mano (ver `marked_items`)."""
    return marked_items(
        key, currency, _grouped(movements, unions).get((key, currency), []), cadence
    )


def marked_items(
    key: str, currency: str, items: Sequence[Movement], cadence: Cadence | None = None
) -> Recurring | None:
    """Una serie marcada a mano, aunque la regla no la detecte (o con la cadencia elegida): sus
    cobros (`items`, de `group_movements`) sin exigir cadencia. None si no tiene cobros."""
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
    variable = utility and chosen == "mensual"
    if variable:
        typical = _average(_per_month(charges)[-_TYPICAL_CHARGES:])
    else:
        recent = charges[-1:] if chosen == "anual" else charges[-_TYPICAL_CHARGES:]
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
    """Anual si la mediana de días entre cobros llega a _YEARLY_GAP_DAYS; si no, mensual."""
    gaps = [(b.day - a.day).days for a, b in zip(charges, charges[1:], strict=False)]
    return "anual" if gaps and median(gaps) >= _YEARLY_GAP_DAYS else "mensual"


def _charges(items: Iterable[Movement]) -> tuple[Charge, ...]:
    return tuple(Charge(m.day, m.amount, m.fingerprint) for m in items)


def _detect_series(key: str, currency: str, items: list[Movement]) -> Recurring | None:
    main = _main_category(items)
    if main.ref == categories.UTILITIES:
        monthly = _utility(key, currency, items, main)
        if monthly is not None:
            return monthly
        yearly = _classify(key, currency, items)
        return yearly if yearly is not None and yearly.cadence == "anual" else None
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
    """Un cobro por mes: la suma de lo pagado, con el día y la huella del último pago."""
    months = _by_month(items)
    found = []
    for index in sorted(months):
        paid = sorted(months[index], key=_by_day)
        total = sum((m.amount for m in paid), Decimal(0))
        found.append(Charge(paid[-1].day, total, paid[-1].fingerprint))
    return tuple(found)


def _per_month(charges: Sequence[Charge]) -> list[Decimal]:
    """Lo pagado repartido por mes: un pago tras meses sin pagar cubre también esos meses (el
    doble tras un mes vacío cuenta mitad y mitad)."""
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
    """Servicios: la suma de cada mes, con meses sin pago tolerados; monto siempre variable."""
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
        cadence="mensual",
        charges=run,
        typical=_average(spread[-_TYPICAL_CHARGES:]),
        variable=True,
        price_change=sustained_rise(spread, run[-1].day),
        category_key=main.ref,
    )


def sustained_rise(spread: Sequence[Decimal], day: date) -> PriceChange | None:
    """«Subió» de Servicios (ver `UTILITY_RISE`) sobre lo pagado por mes, o None."""
    if len(spread) < 2 * RISE_MONTHS:
        return None
    before = _average(spread[-2 * RISE_MONTHS : -RISE_MONTHS])
    recent = spread[-RISE_MONTHS:]
    after = _average(recent)
    if before <= 0 or after <= before * (1 + UTILITY_RISE) or min(recent) <= before:
        return None
    return PriceChange(before, after, day)


def _loan(key: str, currency: str, items: list[Movement], main: Movement) -> Recurring | None:
    """Préstamos: la serie es la cuota (`recurring_loans`); los abonos extra van aparte y nunca
    disparan «subió»."""
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
    """Un cobro con la categoría más común de la serie; en empate, la del más reciente."""
    counts = Counter(m.ref for m in items)
    top = max(counts.values())
    return next(m for m in reversed(items) if counts[m.ref] == top)


def _last_run(items: list[Movement]) -> list[Movement]:
    """Cobros desde la última pausa larga (más de MONTHLY_SKIP_GAP[1] días sin cobrar)."""
    start = len(items) - 1
    while start > 0 and (items[start].day - items[start - 1].day).days <= MONTHLY_SKIP_GAP[1]:
        start -= 1
    return items[start:]


def _cadence(items: list[Movement]) -> tuple[Cadence, list[Movement]] | None:
    """Cadencia y los cobros que la sustentan.

    Lo mensual se evalúa solo sobre la última racha (una pausa o una compra suelta antigua
    no esconde una suscripción vigente); lo anual, sobre toda la serie.
    """
    run = _last_run(items)
    run_months = {m.month for m in run}
    if len(run) >= MONTHLY_MIN and len(run_months) == len(run) and _monthly_gaps(_gaps(run)):
        return "mensual", run
    if len(items) >= YEARLY_MIN and all(YEARLY_GAP[0] <= g <= YEARLY_GAP[1] for g in _gaps(items)):
        return "anual", items
    return None


def _gaps(items: list[Movement]) -> list[int]:
    return [(b.day - a.day).days for a, b in zip(items, items[1:], strict=False)]


def _monthly_gaps(gaps: list[int]) -> bool:
    """Brechas normales, con algún mes saltado tolerado (a lo sumo 1 de cada 6 cobros)."""
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
    """Tramos de precio: abre tramo un cobro que difiere más de FIXED_TOLERANCE del primero."""
    segments: list[list[Charge]] = []
    for c in charges:
        if segments and _relative_gap(c.amount, segments[-1][0].amount) <= FIXED_TOLERANCE:
            segments[-1].append(c)
        else:
            segments.append([c])
    return [tuple(s) for s in segments]


def _amounts(charges: tuple[Charge, ...], category: str) -> tuple[bool, Decimal] | None:
    """(variable, monto típico), o None si los montos son dispares."""
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
        return None  # un cobro suelto en medio: monto al azar, no un cambio de precio
    last = segments[-1]
    if len(segments) > 1 and len(last) == 1:
        before = median(c.amount for c in segments[-2])
        if _relative_gap(last[0].amount, before) > VARIABLE_TOLERANCE:
            return None  # salto demasiado grande: se espera a que se repita
    return False, median(c.amount for c in last)


def _price_change(charges: tuple[Charge, ...]) -> PriceChange | None:
    """Último cambio de precio: del último cobro del tramo anterior al primero del último."""
    segments = _segments(charges)
    if len(segments) < 2:
        return None
    before, first_new = segments[-2][-1], segments[-1][0]
    return PriceChange(before.amount, first_new.amount, first_new.day)
