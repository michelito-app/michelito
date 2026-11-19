"""Sugerencias de gastos únicos: compras grandes y raras del mes, con reglas locales.

Funciones puras sobre movimientos ya cargados; nada sale de la máquina. Una compra del mes
es candidata solo si cumple todo:
- es un gasto con monto positivo, no está marcada como única ni descartada, y no es un
  pago de préstamo (grande y fijo por naturaleza: no es un gasto extraordinario);
- no es un cargo recurrente (`recurring.detect` corregido por las marcas del usuario) ni una
  cuota ("CUOTA", "3/12");
- vale al menos MIN_AMOUNT_DOP en pesos (los dólares, con la tasa del mes);
- frente a las compras de su categoría del último año (sin gastos únicos): con al menos
  MIN_CATEGORY_HISTORY de ellas, vale CATEGORY_FACTOR veces su mediana; con menos, la
  categoría misma es rara y la condición se da por cumplida;
- y el comercio casi no aparece en ese año (a lo sumo una vez) o la compra vale
  MERCHANT_FACTOR veces la mediana del comercio.

El orden es por rareza: veces la mediana de la categoría o, sin mediana, veces MIN_AMOUNT_DOP.

Confirmar una sugerencia es marcar el gasto único; descartarla se guarda aparte
(`one_off_dismissals`) y la compra sigue contando como historia normal.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from finanzas.analysis import categories, recurring
from finanzas.analysis.rates import Rate, to_dop
from finanzas.analysis.recurring_marks import Mark, for_series
from finanzas.analysis.spending import Movement
from finanzas.parsers.common import normalize

MIN_AMOUNT_DOP = Decimal(10_000)
CATEGORY_FACTOR = Decimal(3)
MERCHANT_FACTOR = Decimal(3)
MIN_CATEGORY_HISTORY = 3
MAX_MERCHANT_SEEN = 1  # veces vistas en el año que aún cuentan como comercio nuevo
HISTORY_DAYS = 365
MAX_PER_MONTH = 5

_INSTALLMENT_WORD = re.compile(r"\bCUOTAS?\b")
# "3/12": cuota a de b. Solo cuenta si 1 <= a <= b y b es un plazo creíble (2 a 60 meses);
# así "24/7" o una fecha "12/05" no pasan por cuotas.
_INSTALLMENT_FRACTION = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b")
_MAX_INSTALLMENTS = 60
# Marcas de recurrentes que confirman que el comercio cobra solo (ver `recurring_marks`).
_RECURRING_STATUSES = frozenset({"confirmed", "cancelled"})
_RATIO = Decimal("0.1")
# Categorías de gasto que nunca se sugieren como gasto único.
_NEVER_ONE_OFF = frozenset({categories.LOANS})

RateForMonth = Callable[[str], Rate | None]


@dataclass(frozen=True)
class Suggestion:
    fingerprint: str
    day: date
    merchant: str
    description: str
    account: str
    amount: Decimal
    currency: str
    amount_dop: Decimal
    reasons: tuple[str, ...]
    score: Decimal


@dataclass(frozen=True)
class _Peso:
    move: Movement
    dop: Decimal


def is_installment(description: str) -> bool:
    """ "CUOTA 3", "03/12": la parte de una compra financiada, no una compra nueva."""
    text = normalize(description).upper()
    if _INSTALLMENT_WORD.search(text):
        return True
    return any(
        1 <= int(a) <= int(b) and 2 <= int(b) <= _MAX_INSTALLMENTS
        for a, b in _INSTALLMENT_FRACTION.findall(text)
    )


def recurring_keys(
    expenses: Sequence[Movement],
    marks: Mapping[tuple[str, str], Mark],
    unions: Mapping[str, str] | None = None,
) -> set[tuple[str, str]]:
    """(comercio, moneda) que cobran solos: lo detectado más lo marcado por el usuario.

    "Es recurrente", "La cancelé" o cuotas anotadas lo agregan; "No es recurrente" lo quita
    aunque `recurring.detect` lo encuentre. Una serie (un proveedor o una unión) cuenta por
    todos sus comercios.
    """
    groups = recurring.members(expenses, unions)
    found = {
        (name, r.currency)
        for r in recurring.detect(expenses, unions)
        for name in (r.members or (r.merchant,))
    }
    for (key, currency), mark in for_series(marks, groups).items():
        pairs = {(name, currency) for name in groups.get(key, {key})}
        if mark.status in _RECURRING_STATUSES or mark.installments_left is not None:
            found |= pairs
        elif mark.status == "dismissed":
            found -= pairs
    return found


def suggest(
    movements: Sequence[Movement],
    month: str,
    *,
    rate_for_month: RateForMonth,
    dismissed: Collection[str],
    marks: Mapping[tuple[str, str], Mark] | None = None,
    limit: int | None = MAX_PER_MONTH,
    unions: Mapping[str, str] | None = None,
) -> list[Suggestion]:
    """Hasta `limit` compras de `month` que parecen gastos únicos, la más rara primero.

    `marks`: marcas de recurrentes del usuario (`recurring_marks.load`), por comercio (o
    serie) y moneda; `unions`: las uniones de comercios en Recurrentes.
    `limit`: None, todas (el historial de «Para revisar» no debe perder las descartadas).
    """
    expenses = [m for m in movements if m.kind == "gasto"]
    recurrent = recurring_keys(expenses, marks or {}, unions)
    history = _convert((m for m in expenses if m.amount > 0 and not m.one_off), rate_for_month)
    found = []
    for item in _convert((m for m in expenses if m.month == month), rate_for_month):
        move = item.move
        if (
            move.amount <= 0
            or move.ref in _NEVER_ONE_OFF
            or move.one_off
            or move.fingerprint in dismissed
            or (move.merchant, move.currency) in recurrent
            or is_installment(move.description)
            or item.dop < MIN_AMOUNT_DOP
        ):
            continue
        suggestion = _judge(item, _before(history, move.day))
        if suggestion is not None:
            found.append(suggestion)
    found.sort(key=lambda s: (-s.score, s.day, s.fingerprint))
    return found if limit is None else found[:limit]


def _convert(movements: Iterable[Movement], rate_for_month: RateForMonth) -> list[_Peso]:
    """A RD$ con la tasa de cada mes; los US$ sin tasa quedan fuera."""
    converted = []
    for move in movements:
        dop = to_dop(move.amount, move.currency, rate_for_month(move.month))
        if dop is not None:
            converted.append(_Peso(move, dop))
    return converted


def _before(history: Sequence[_Peso], day: date) -> list[_Peso]:
    start = day - timedelta(days=HISTORY_DAYS)
    return [p for p in history if start <= p.move.day < day]


def _judge(item: _Peso, past: Sequence[_Peso]) -> Suggestion | None:
    move = item.move
    same_category = [p.dop for p in past if p.move.ref == move.ref]
    reasons: list[str] = []
    if len(same_category) >= MIN_CATEGORY_HISTORY:
        typical = median(same_category)
        if item.dop < CATEGORY_FACTOR * typical:
            return None
        score = item.dop / typical
        reasons.append(f"{_times(score)} veces tu compra típica en {move.category}")
    else:
        score = item.dop / MIN_AMOUNT_DOP  # en "veces", como el cociente con la mediana
        reasons.append("categoría poco usada")
    same_merchant = [p.dop for p in past if p.move.merchant == move.merchant]
    merchant_reason = _merchant_reason(item, same_merchant)
    if merchant_reason is None:
        return None
    reasons.append(merchant_reason)
    return Suggestion(
        fingerprint=move.fingerprint,
        day=move.day,
        merchant=move.merchant,
        description=move.description,
        account=move.account,
        amount=move.amount,
        currency=move.currency,
        amount_dop=item.dop,
        reasons=tuple(reasons),
        score=score,
    )


def _merchant_reason(item: _Peso, seen: Sequence[Decimal]) -> str | None:
    if not seen:
        return "comercio nuevo"
    if len(seen) <= MAX_MERCHANT_SEEN:
        return "comercio poco frecuente"
    typical = median(seen)
    if item.dop < MERCHANT_FACTOR * typical:
        return None
    return f"{_times(item.dop / typical)} veces lo usual en {item.move.merchant}"


def _times(ratio: Decimal) -> str:
    return str(ratio.quantize(_RATIO))
