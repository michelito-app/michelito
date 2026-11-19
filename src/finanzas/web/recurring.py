"""Vista de cargos recurrentes: detección + marcas del usuario + tasas de cambio.

Función pura: recibe movimientos, marcas y tasas ya cargados, no toca la base de datos.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from finanzas.analysis import categories, providers
from finanzas.analysis import recurring as rec
from finanzas.analysis.rates import Rate, rate_for, to_dop
from finanzas.analysis.recurring import PriceChange, Recurring
from finanzas.analysis.recurring_marks import Mark, MarkStatus, for_series
from finanzas.analysis.report import money
from finanzas.analysis.spending import Movement

Status = Literal["activo", "inactivo", "cancelado", "terminado"]
AlertKind = Literal["nuevo", "subio", "cobro_tras_cancelar"]

INSTALLMENTS_GROUP = "Cuotas"
_NAMES = list(rec.GROUPS.values())
# Vivienda · Préstamos · Servicios · Seguros · Suscripciones · Cargos del banco · Cuotas · Otros.
GROUP_ORDER = (*_NAMES[:-1], INSTALLMENTS_GROUP, _NAMES[-1])
_PERIOD_DAYS = {"mensual": 30, "anual": 365}
_MONTHS_PER_YEAR = 12
_PESO = Decimal(1)


@dataclass(frozen=True)
class RecurringView:
    merchant: str  # la clave de la serie (con ella se marca)
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
    name: str = ""  # el nombre visible (el del proveedor); vacío: `merchant`
    members: tuple[str, ...] = ()  # los comercios de la serie
    provider: bool = False  # un proveedor de la lista
    extras_year: Decimal = Decimal(0)  # préstamos: abonos extra del año de `as_of` (su moneda)
    group_key: str = ""  # la clave de `recurring.GROUPS` (vacía en Cuotas)


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
    fingerprint: str = ""  # el cobro que lo causó, cuando se sabe (subió, cobro tras cancelar)
    name: str = ""  # nombre visible de la serie; vacío: `merchant`


@dataclass(frozen=True)
class Overview:
    as_of: date | None  # None cuando no hay movimientos
    first_month: str | None  # mes del primer movimiento ("YYYY-MM")
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
    """`as_of`: día contra el que se mide si un cargo sigue activo; por defecto, el último
    movimiento recibido (con un subconjunto de cuentas, conviene pasar el de todas).
    `marks`: por comercio o por serie (se leen por serie); `unions`: las uniones a mano."""
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
    active = [v for v in views if v.status == "activo"]
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
    """Las marcas por serie (`recurring_marks.for_series`): las de los comercios de un
    proveedor o de una unión valen para la serie mientras ella no tenga una propia."""
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
    """Los detectados (con la cadencia elegida a mano, si se eligió otra) y, aparte, los
    marcados que la regla no detecta. Agrupa los movimientos una sola vez."""
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
    """La vista de una sola serie (como en `build_overview`), sin calcular las demás; None si
    no aparece en Recurrentes (ni detectada ni marcada)."""
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


def _round_pesos(value: Decimal) -> Decimal:
    return value.quantize(_PESO, rounding=ROUND_HALF_EVEN)


def _costs(found: Recurring, rate: Rate | None) -> tuple[Decimal | None, Decimal | None]:
    """(mensual, anual) en RD$ a pesos enteros: del monto típico se redondea el periodo propio
    del cargo y el otro sale de ahí, para que mensual × 12 y el anual cuadren en pantalla."""
    typical = to_dop(found.typical, found.currency, rate)
    if typical is None:
        return None, None
    if found.cadence == "anual":
        yearly = _round_pesos(typical)
        return _round_pesos(yearly / _MONTHS_PER_YEAR), yearly
    monthly = _round_pesos(typical)
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
    """El grupo elegido a mano; si no, «Cuotas» (clave vacía) para lo que lleva cuotas anotadas
    salvo un préstamo (que se queda en Préstamos); si no, el de su categoría."""
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
        return "terminado"
    if mark is not None and mark.status == "cancelled":
        return "cancelado"
    return "inactivo" if (as_of - found.last_day).days > inactive_after(found) else "activo"


def inactive_after(found: Recurring) -> Decimal:
    """Días sin cobro tras los que un cargo está inactivo: 1,5 periodos; en Servicios mensual,
    1,5 veces los meses que puede haber entre dos pagos (`UTILITY_MAX_GAP`: 90 días), porque un
    mes sin pago seguido de uno doble es normal."""
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
    active = view.status == "activo"
    # En el primer mes con datos todo "empieza" ahí: no es un cargo nuevo.
    first_seen = found.first_day.strftime("%Y-%m")
    if active and first_seen == month and month != first_month:
        if view.monthly_dop is not None:
            cost = money(view.monthly_dop, "DOP")
        else:
            cost = money(found.monthly, currency)
        alerts.append(
            Alert("nuevo", merchant, currency, f"Nuevo: {cost} al mes", name=found.display)
        )
    change = found.price_change
    if (
        active
        and change is not None
        and change.after > change.before
        and change.day.strftime("%Y-%m") == month
    ):
        detail = f"Subió de {money(change.before, currency)} a {money(change.after, currency)}"
        charge = next((c for c in found.charges if c.day == change.day), None)
        alerts.append(
            Alert(
                "subio",
                merchant,
                currency,
                detail,
                charge.fingerprint if charge else "",
                found.display,
            )
        )
    late = [c for c in _after_cancel(found, mark) if c.day.strftime("%Y-%m") == month]
    if late:
        detail = f"Cobró {money(late[-1].amount, currency)} después de cancelarlo"
        alerts.append(
            Alert(
                "cobro_tras_cancelar",
                merchant,
                currency,
                detail,
                late[-1].fingerprint,
                found.display,
            )
        )
    return alerts
