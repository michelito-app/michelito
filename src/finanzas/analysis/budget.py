"""Presupuesto por categoría (estilo Monarch, no base cero). Lógica pura, todo en RD$.

- Cada categoría de gasto puede tener un **tope** mensual (`Cap`). No hay asignación de ingresos
  ni **arrastre**: cada mes se compara solo lo de ese mes contra el tope.
- Lo gastado contra el tope es lo del mes en esa categoría (un compartido, solo tu parte, como en
  el resto: ya viene así en `Movement.amount`; una devolución resta), **sin** los gastos únicos
  (van aparte, «+ RD$ X en gastos únicos», y siguen en el total del mes) y **sin** los gastos
  vinculados a una reserva («cubiertos por la reserva»). Lo que está en US$ pasa a RD$ con la tasa
  de su mes; sin tasa no suma y se cuenta aparte.
- **Lo habitual** de una categoría (`habitual`): la mediana de lo gastado (sin gastos únicos ni lo
  cubierto por reservas) en los últimos `BASELINE_MONTHS` meses completos (hace falta al menos
  uno; los meses sin gasto en ella cuentan como 0), con todas las cuentas: los topes son de toda
  la casa aunque se mire un filtro de cuentas.
- **Valor inicial** al activar: lo habitual redondeado (`round_cap`: al múltiplo de `CAP_STEP`
  más cercano, con un mínimo de `CAP_STEP` si hubo algo; sin habitual, «Sin presupuesto»).
- **Aviso de «lo habitual cambió»** (`warning`): solo en un tope que no se tocó a mano, cuando lo
  habitual redondeado de hoy difiere de lo ya visto (`basis`) por al menos
  max(`CAP_STEP`, `WARN_SHARE` de lo ya visto). Nunca cambia solo: aceptar pone el tope nuevo;
  ignorar solo da por visto el valor nuevo (no vuelve a avisar hasta que cambie otra vez).
- **Pasada**: una categoría cuenta como pasada (`passed`, en los totales y en el Resumen) solo si
  excede su tope en más de max(`PASS_SHARE` del tope, `PASS_FLOOR`): un alquiler en US$ que sube
  un poco por la tasa no lo es. La diferencia exacta (`over`) se muestra igual.
- **Gasto neto negativo**: si las devoluciones del mes superan lo gastado, lo gastado contra el
  tope queda en 0 y lo devuelto de más va aparte («devoluciones: RD$ X», `refunds`); no resta del
  total gastado del presupuesto.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

BASELINE_MONTHS = 6
CAP_STEP = Decimal(500)
WARN_SHARE = Decimal("0.10")
CAP_MAX = Decimal(100_000_000)
PASS_SHARE = Decimal("0.05")
PASS_FLOOR = Decimal(500)
_ZERO = Decimal(0)


@dataclass(frozen=True)
class Cap:
    category_id: int
    cap: Decimal | None  # None: «Sin presupuesto»
    manual: bool = False  # editado a mano: queda fijo
    basis: Decimal | None = None  # lo habitual redondeado ya visto


@dataclass(frozen=True)
class Item:
    """Un gasto del mes ya en RD$ (`dop` None: US$ sin tasa)."""

    fingerprint: str
    month: str
    category_id: int
    dop: Decimal | None
    one_off: bool = False
    reserved: bool = False  # vinculado a una reserva


@dataclass(frozen=True)
class Warning:
    habitual: Decimal  # lo habitual redondeado de hoy
    basis: Decimal  # lo ya visto

    @property
    def up(self) -> bool:
        return self.habitual > self.basis


@dataclass(frozen=True)
class Line:
    category_id: int
    cap: Decimal | None
    manual: bool
    spent: Decimal  # contra el tope
    one_offs: Decimal  # gastos únicos del mes (aparte)
    covered: Decimal  # cubierto por reservas (aparte)
    without_rate: int  # gastos en US$ sin tasa (no suman)
    habitual: Decimal | None  # lo habitual redondeado de hoy (None: sin meses de referencia)
    warning: Warning | None
    refunds: Decimal = _ZERO  # devuelto de más en el mes (lo gastado queda en 0)

    @property
    def over(self) -> Decimal:
        """Lo que pasa del tope, exacto (0 si no lo pasa o no hay tope)."""
        if self.cap is None:
            return _ZERO
        return max(self.spent - self.cap, _ZERO)

    @property
    def passed(self) -> bool:
        """Pasó el tope por más del margen (ver el docstring del módulo)."""
        if self.cap is None:
            return False
        return self.over > max(self.cap * PASS_SHARE, PASS_FLOOR)

    @property
    def ratio(self) -> float:
        if self.cap is None or self.cap <= 0:
            return float("inf") if self.spent > 0 and self.cap is not None else 0.0
        return float(self.spent / self.cap)

    @property
    def active(self) -> bool:
        """Se muestra arriba: tiene tope, algo del mes o un aviso."""
        return bool(
            self.cap is not None
            or self.spent
            or self.one_offs
            or self.covered
            or self.refunds
            or self.without_rate
            or self.warning
        )


def round_cap(value: Decimal | None) -> Decimal | None:
    """Lo habitual redondeado al múltiplo de `CAP_STEP` más cercano (mitad hacia arriba), con un
    mínimo de `CAP_STEP` si hubo gasto; None sin habitual o sin gasto."""
    if value is None or value <= 0:
        return None
    steps = (value / CAP_STEP).to_integral_value(rounding=ROUND_HALF_UP)
    return max(steps, Decimal(1)) * CAP_STEP


def reference_months(complete: Iterable[str], count: int = BASELINE_MONTHS) -> list[str]:
    """Los últimos `count` meses completos (de más viejo a más nuevo)."""
    return sorted(set(complete))[-count:]


def habitual(items: Iterable[Item], months: Sequence[str]) -> dict[int, Decimal]:
    """Lo habitual por categoría: la mediana de lo gastado en `months` sin gastos únicos ni lo
    cubierto por reservas (los meses sin gasto, 0). Vacío sin meses."""
    if not months:
        return {}
    wanted = set(months)
    totals: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for item in items:
        if item.month in wanted and not item.one_off and not item.reserved and item.dop is not None:
            totals[item.category_id][item.month] += item.dop
    return {
        category: statistics.median(by_month.get(m, _ZERO) for m in months)
        for category, by_month in totals.items()
    }


def initial_caps(categories: Iterable[int], usual: Mapping[int, Decimal]) -> list[Cap]:
    """Los topes al activar: lo habitual redondeado de cada categoría (o «Sin presupuesto»)."""
    found = []
    for category in categories:
        rounded = round_cap(usual.get(category))
        found.append(Cap(category, rounded, False, rounded or _ZERO))
    return found


def warning(cap: Cap, usual: Decimal | None) -> Warning | None:
    """El aviso de «lo habitual cambió» (ver el docstring del módulo)."""
    if cap.manual or cap.basis is None:
        return None
    now = round_cap(usual) or _ZERO
    if abs(now - cap.basis) < max(CAP_STEP, cap.basis * WARN_SHARE):
        return None
    return Warning(now, cap.basis)


def lines(
    items: Iterable[Item],
    month: str,
    caps: Mapping[int, Cap],
    usual: Mapping[int, Decimal],
    categories: Collection[int],
) -> list[Line]:
    """Una línea por categoría de gasto (`categories`, más las que tuvieron algo en el mes),
    ordenadas por exceso (la que más pasa primero), luego por cuánto de su tope llevan."""
    spent: dict[int, Decimal] = defaultdict(Decimal)
    one_offs: dict[int, Decimal] = defaultdict(Decimal)
    covered: dict[int, Decimal] = defaultdict(Decimal)
    missing: dict[int, int] = defaultdict(int)
    seen = set(categories)
    for item in items:
        if item.month != month:
            continue
        seen.add(item.category_id)
        if item.dop is None:
            missing[item.category_id] += 1
        elif item.reserved:
            covered[item.category_id] += item.dop
        elif item.one_off:
            one_offs[item.category_id] += item.dop
        else:
            spent[item.category_id] += item.dop
    found = []
    for category in seen:
        cap = caps.get(category)
        rounded = round_cap(usual.get(category)) if usual else None
        found.append(
            Line(
                category_id=category,
                cap=None if cap is None else cap.cap,
                manual=bool(cap and cap.manual),
                spent=max(spent[category], _ZERO),
                one_offs=one_offs[category],
                covered=covered[category],
                without_rate=missing[category],
                habitual=rounded,
                warning=None if cap is None else warning(cap, usual.get(category, _ZERO)),
                refunds=max(-spent[category], _ZERO),
            )
        )
    return sorted(
        found,
        key=lambda line: (not line.passed, -line.over, -line.ratio, -line.spent, line.category_id),
    )


@dataclass(frozen=True)
class Totals:
    cap: Decimal  # suma de los topes
    spent: Decimal  # lo gastado contra un tope (en las categorías con tope)
    over_count: int
    over: Decimal


def totals(found: Iterable[Line]) -> Totals:
    capped = [line for line in found if line.cap is not None]
    passed = [line for line in capped if line.passed]
    return Totals(
        cap=sum((line.cap or _ZERO for line in capped), _ZERO),
        spent=sum((line.spent for line in capped), _ZERO),
        over_count=len(passed),
        over=sum((line.over for line in passed), _ZERO),
    )
