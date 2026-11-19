"""Inversiones: todas en una pantalla, de todos los meses (funciones puras).

- **Una fila por inversión** con algún aporte presente (`investments.states`), la de actividad
  más reciente primero (a igualdad, la más nueva).
- **Cuentas**: con cuentas elegidas, una inversión cuenta si alguno de sus aportes es de ellas
  (como Compartidos con los gastos).
- **Totales** (≈ RD$): «Capital por volver», el de las activas (las cerradas no tienen; las
  dadas por perdidas no cuentan), en RD$ a la tasa más reciente; «Rendimientos cobrados este
  año», el rendimiento de cada crédito con fecha en el año de `today`, en RD$ a la tasa de su mes
  (o la del mes anterior más cercano); los US$ sin tasa van aparte, sin inventar. Y cuántas
  están activas.
- **Selectores** de la pantalla de una inversión: débitos que pueden ser otro aporte (desde
  PICK_WINDOW_DAYS antes del primer aporte) y créditos que pueden ser un cobro (desde el primer
  aporte); primero (y primarios) los que se proponen para esta inversión
  (`investments.suggestions`), luego el resto, en cada bloque el más reciente primero.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from finanzas.analysis import investments
from finanzas.analysis.investments import InvestmentState, Suggestion
from finanzas.analysis.links import Candidate, Links
from finanzas.analysis.rates import Rate, rate_for, to_dop
from finanzas.analysis.spending import Movement

PICK_WINDOW_DAYS = 120
_ZERO = Decimal(0)


@dataclass(frozen=True)
class InvestmentRow:
    state: InvestmentState
    annual_rate: Decimal | None  # fracción: 0.12 = 12 % (ver `investments.annual_rate`)
    pending_dop: Decimal | None  # capital por volver ≈ RD$ (None: en US$ sin ninguna tasa)


@dataclass(frozen=True)
class InvestmentList:
    rows: tuple[InvestmentRow, ...]  # la última actividad primero
    pending_dop: Decimal  # capital por volver de las activas, ≈ RD$
    unconverted_pending_usd: Decimal  # el de las activas en US$ sin ninguna tasa
    returns_year_dop: Decimal  # rendimientos cobrados en el año de `today`, ≈ RD$
    unconverted_returns_usd: Decimal
    rate: Rate | None  # la más reciente: la del capital por volver en US$

    @property
    def active_count(self) -> int:
        return sum(1 for r in self.rows if r.state.status == "active")


def picked(state: InvestmentState, chosen: Collection[str] | None) -> bool:
    """La inversión cuenta con estas cuentas: alguno de sus aportes es de ellas (None: todas)."""
    return chosen is None or any(e.move.account in chosen for e in state.contributions)


def latest_rate(rates: Mapping[str, Rate], today: date) -> Rate | None:
    return rate_for(rates, today.strftime("%Y-%m"))


def pending_dop(state: InvestmentState, rate: Rate | None) -> Decimal | None:
    return to_dop(state.pending, state.currency, rate)


def returns_in_year(
    found: Iterable[InvestmentState], year: int, rates: Mapping[str, Rate]
) -> tuple[Decimal, Decimal]:
    """Rendimientos con fecha en `year`, en RD$ a la tasa de su mes; y los US$ sin tasa."""
    dop, unconverted = _ZERO, _ZERO
    for state in found:
        for entry in state.credits:
            if entry.day.year != year or entry.returned <= 0:
                continue
            value = to_dop(entry.returned, entry.currency, rate_for(rates, entry.move.month))
            if value is None:
                unconverted += entry.returned
            else:
                dop += value
    return dop, unconverted


def build_list(
    found: Mapping[int, InvestmentState],
    rates: Mapping[str, Rate],
    today: date,
    chosen: Collection[str] | None = None,
) -> InvestmentList:
    """Las filas y los totales de Inversiones. `chosen`: claves de las cuentas (None: todas)."""
    shown = investments.newest_first(s for s in found.values() if picked(s, chosen))
    rate = latest_rate(rates, today)
    rows = tuple(InvestmentRow(s, s.annual_rate(today), pending_dop(s, rate)) for s in shown)
    active = [r for r in rows if r.state.status == "active"]
    year_dop, year_unconverted = returns_in_year(shown, today.year, rates)
    return InvestmentList(
        rows=rows,
        pending_dop=sum((r.pending_dop for r in active if r.pending_dop is not None), _ZERO),
        unconverted_pending_usd=sum(
            (r.state.pending for r in active if r.pending_dop is None), _ZERO
        ),
        returns_year_dop=year_dop,
        unconverted_returns_usd=year_unconverted,
        rate=rate,
    )


def _ranked(moves: Iterable[Movement], suggested: Collection[str]) -> list[Candidate]:
    found = [Candidate(m, m.fingerprint in suggested) for m in moves]
    return sorted(found, key=lambda c: (c.primary, c.move.day, c.move.fingerprint), reverse=True)


def contribution_candidates(
    state: InvestmentState,
    movements: Iterable[Movement],
    links: Links,
    hints: Mapping[str, Suggestion],
    banks: Collection[str],
) -> list[Candidate]:
    """«Añadir un aporte»: débitos bancarios sin vínculo desde PICK_WINDOW_DAYS días antes del
    primer aporte; los propuestos para esta inversión, primero."""
    start = state.first.day - timedelta(days=PICK_WINDOW_DAYS)
    moves = [
        m
        for m in movements
        if m.account in banks and m.day >= start and investments.is_contribution_candidate(m, links)
    ]
    return _ranked(moves, _suggested(hints, state, "aporte_posible"))


def credit_candidates(
    state: InvestmentState,
    movements: Iterable[Movement],
    links: Links,
    hints: Mapping[str, Suggestion],
    banks: Collection[str],
) -> list[Candidate]:
    """«Añadir un cobro»: créditos bancarios sin vínculo desde el primer aporte; los propuestos
    para esta inversión, primero."""
    moves = [
        m
        for m in movements
        if m.account in banks
        and m.day >= state.first.day
        and investments.is_credit_candidate(m, links)
    ]
    return _ranked(moves, _suggested(hints, state, "cobro_posible"))


def _suggested(
    hints: Mapping[str, Suggestion], state: InvestmentState, kind: str
) -> frozenset[str]:
    return frozenset(fp for fp, s in hints.items() if s.kind == kind and s.state.id == state.id)


def open_investments(
    found: Mapping[int, InvestmentState], include_lost: bool = False
) -> list[InvestmentState]:
    """Las inversiones a las que se puede sumar algo, la de actividad más reciente primero: para
    un aporte («Añadir a una existente»), todas menos las dadas por perdidas; para un crédito
    (`include_lost`), también ellas: a veces pagan parte de una que se dio por perdida."""
    ranked = investments.newest_first(found.values())
    return [s for s in ranked if include_lost or s.status != "written_off"]
