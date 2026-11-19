"""Cambios de divisas con terceros: patas en RD$ y en US$ enlazadas (ver `links`).

Un cambio agrupa una o más patas en cada moneda, de cualquier cuenta bancaria del usuario: las de
una moneda en una dirección (todas salen o todas entran) y las de la otra en la contraria. Las
patas enlazadas son "Cambio de divisas": ni gasto, ni ingreso, ni transferencia a terceros, así
que no mueven "Te quedó".

Cuentas:
- El lado **base** es el de la pata más antigua (lo que diste o recibiste primero); el otro, lo
  que vuelve.
- Tasa (RD$ por US$): la acordada si el usuario la puso; si no, la implícita del primer par
  completo: la suma en RD$ de las patas en pesos del primer día con patas en pesos, dividida
  entre la suma en US$ de las patas en dólares del primer día con patas en dólares (4 decimales).
- Pendiente: lo del lado base convertido a la otra moneda a esa tasa, menos lo que volvió en la
  otra moneda (nunca negativo), en centavos; también en RD$ (a la misma tasa).
- "Cambio completo" lo cierra: el pendiente queda en 0 aunque no cuadre.

Sugerencias: un movimiento bancario de al menos SUGGEST_MIN_DOP (US$ a la tasa del mes) con una
contraparte en la otra moneda y dirección contraria, de cualquier cuenta bancaria, a lo sumo
WINDOW_DAYS días antes o después, cuya tasa implícita está a ±RATE_TOLERANCE de la oficial del
mes o que cubre una buena parte (la menor de las dos en RD$ es al menos SHARE_MIN de la mayor).
Ninguna de las dos es salario, pago de tarjeta, envío entre mis cuentas ni otro vínculo. Nunca
se enlaza solo.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from finanzas.analysis import categories
from finanzas.analysis.links import Candidate, Exchange, LinkError, Links
from finanzas.analysis.rates import Rate, to_dop

if TYPE_CHECKING:
    from finanzas.analysis.spending import Movement

WINDOW_DAYS = 30
SUGGEST_MIN_DOP = Decimal(20_000)
RATE_TOLERANCE = Decimal("0.05")
SHARE_MIN = Decimal("0.5")
PENDING_MARGIN = Decimal("0.05")  # al agregar patas: cabe en el pendiente / lo completa
PICK_RATE_GAP = Decimal("0.10")  # al empezar un cambio: más lejos de la tasa del mes, «Ver más»
PESOS, DOLLARS = "DOP", "USD"
CURRENCIES = frozenset({PESOS, DOLLARS})
_RATE = Decimal("0.0001")
_CENT = Decimal("0.01")
_ZERO = Decimal(0)
# Movimientos que nunca son una pata de un cambio.
NOT_A_LEG = frozenset(
    {
        categories.SALARY,
        categories.CARD_PAYMENT,
        categories.OWN_TRANSFER,
        categories.REIMBURSEMENT,
        categories.CURRENCY_EXCHANGE,
    }
)

RateForMonth = Callable[[str], Rate | None]


@dataclass(frozen=True)
class ExchangeState:
    exchange: Exchange
    legs: tuple[Movement, ...]  # las patas presentes, por fecha
    totals: Mapping[str, Decimal]  # monto absoluto por moneda
    base: str  # moneda del lado base
    rate: Decimal  # RD$ por US$: la acordada o la implícita
    implied_rate: Decimal
    pending: Decimal  # en la moneda `pending_currency`
    pending_currency: str
    pending_dop: Decimal

    @property
    def first_day(self) -> date:
        return self.legs[0].day

    @property
    def month(self) -> str:
        return self.legs[0].month

    @property
    def first_pair_only(self) -> bool:
        """Solo el primer par (las patas del primer día de cada moneda): sin tasa acordada, la
        implícita sale de ellas mismas y el pendiente es 0 por definición."""
        firsts = {c: min(m.day for m in self.legs if m.currency == c) for c in self.totals}
        return all(m.day == firsts[m.currency] for m in self.legs)

    @property
    def other(self) -> str:
        return DOLLARS if self.base == PESOS else PESOS


def sides(legs: Iterable[Movement]) -> dict[str, list[Movement]]:
    found: dict[str, list[Movement]] = {}
    for leg in legs:
        found.setdefault(leg.currency, []).append(leg)
    return found


def check_legs(legs: Sequence[Movement]) -> None:
    """Error si las patas no forman un cambio: RD$ y US$, cada moneda en una sola dirección y
    las dos en direcciones contrarias."""
    by_currency = sides(legs)
    if set(by_currency) != CURRENCIES:
        raise LinkError("un cambio necesita patas en RD$ y en US$")
    signs = {currency: {m.amount > 0 for m in moves} for currency, moves in by_currency.items()}
    if any(len(s) != 1 for s in signs.values()) or signs[PESOS] == signs[DOLLARS]:
        raise LinkError("las patas de una moneda van en una dirección y las de la otra al revés")
    if any(m.amount == 0 for m in legs):
        raise LinkError("una pata sin monto no sirve")


def implied_rate(legs: Sequence[Movement]) -> Decimal:
    by_currency = sides(legs)
    pesos = _first_day_total(by_currency[PESOS])
    dollars = _first_day_total(by_currency[DOLLARS])
    return (pesos / dollars).quantize(_RATE, rounding=ROUND_HALF_EVEN)


def _first_day_total(moves: Sequence[Movement]) -> Decimal:
    first = min(m.day for m in moves)
    return sum((abs(m.amount) for m in moves if m.day == first), _ZERO)


def state(exchange: Exchange, by_fingerprint: Mapping[str, Movement]) -> ExchangeState | None:
    """Cuentas del cambio; None si las patas presentes ya no forman un cambio."""
    present = [by_fingerprint[leg] for leg in exchange.legs if leg in by_fingerprint]
    order = {fp: index for index, fp in enumerate(exchange.legs)}
    legs = tuple(sorted(present, key=lambda m: (m.day, order[m.fingerprint])))
    try:
        check_legs(legs)
    except LinkError:
        return None
    totals = {c: sum((abs(m.amount) for m in moves), _ZERO) for c, moves in sides(legs).items()}
    implied = implied_rate(legs)
    rate = exchange.agreed_rate or implied
    base = legs[0].currency
    if base == PESOS:
        owed, currency = totals[PESOS] / rate - totals[DOLLARS], DOLLARS
    else:
        owed, currency = totals[DOLLARS] * rate - totals[PESOS], PESOS
    pending = _ZERO if exchange.closed else max(_ZERO, owed).quantize(_CENT, ROUND_HALF_EVEN)
    pending_dop = pending if currency == PESOS else (pending * rate).quantize(_CENT)
    return ExchangeState(
        exchange=exchange,
        legs=legs,
        totals=totals,
        base=base,
        rate=rate,
        implied_rate=implied,
        pending=pending,
        pending_currency=currency,
        pending_dop=pending_dop,
    )


def states(movements: Sequence[Movement], links: Links) -> dict[int, ExchangeState]:
    by_fp = {m.fingerprint: m for m in movements}
    found: dict[int, ExchangeState] = {}
    for exchange in links.exchanges:
        current = state(exchange, by_fp)
        if current is not None:
            found[exchange.id] = current
    return found


def is_eligible(move: Movement, links: Links, banks: Collection[str]) -> bool:
    """Puede ser una pata: de una cuenta bancaria, en RD$ o US$, sin categoría excluida ni
    otro vínculo."""
    return (
        move.account in banks
        and move.currency in CURRENCIES
        and move.amount != 0
        and move.ref not in NOT_A_LEG
        and not move.link
        and not links.is_linked(move.fingerprint)
    )


def _near(a: Movement, b: Movement) -> bool:
    return abs((a.day - b.day).days) <= WINDOW_DAYS


def _opposite(a: Movement, b: Movement) -> bool:
    return a.currency != b.currency and (a.amount > 0) != (b.amount > 0)


def candidates(
    target: Movement,
    movements: Iterable[Movement],
    links: Links,
    banks: Collection[str],
    current: ExchangeState | None = None,
    rate_for_month: RateForMonth | None = None,
) -> list[Candidate]:
    """Patas posibles, ya ordenadas y marcadas (`primary`: van en la parte visible).

    - Sin cambio: las de la otra moneda y dirección contraria a `target` a ±WINDOW_DAYS días,
      por cercanía de la tasa implícita del par a la oficial del mes de `target`; las que se
      alejan más de PICK_RATE_GAP (o sin tasa) no son primarias.
    - Con un cambio (`current`) con pendiente: solo el lado que falta (la moneda del pendiente,
      en la dirección del lado que vuelve) cerca de alguna pata. Son primarias las que caben en
      el pendiente con PENDING_MARGIN de margen: primero las que lo completan, luego por
      cercanía de fecha; las que pasan de ahí (p. ej. por el diferencial del banco) van
      después, por cercanía de fecha, tras «Ver más».
    - Con un cambio sin pendiente: las que encajan en cualquiera de sus dos lados, ninguna
      primaria.
    """
    pool = [m for m in movements if is_eligible(m, links, banks)]
    if current is None:
        return _starting(target, pool, rate_for_month)
    if current.pending > 0:
        return _missing_side(current, pool)
    shape = {(leg.currency, leg.amount > 0) for leg in current.legs}
    found = [
        m
        for m in pool
        if (m.currency, m.amount > 0) in shape and any(_near(leg, m) for leg in current.legs)
    ]
    return [Candidate(m, False) for m in sorted(found, key=lambda m: (m.day, m.fingerprint))]


def _starting(
    target: Movement, pool: Iterable[Movement], rate_for_month: RateForMonth | None
) -> list[Candidate]:
    def gap(other: Movement) -> Decimal | None:
        return None if rate_for_month is None else _rate_gap(target, other, rate_for_month)

    found = [(m, gap(m)) for m in pool if _opposite(target, m) and _near(target, m)]
    ranked = sorted(
        found,
        key=lambda pair: (
            pair[1] is None,
            pair[1] or _ZERO,
            abs((pair[0].day - target.day).days),
            pair[0].fingerprint,
        ),
    )
    return [Candidate(m, g is not None and g <= PICK_RATE_GAP) for m, g in ranked]


def _missing_side(current: ExchangeState, pool: Iterable[Movement]) -> list[Candidate]:
    currency = current.pending_currency
    incoming = next(leg.amount > 0 for leg in current.legs if leg.currency == currency)
    limit = current.pending * (1 + PENDING_MARGIN)
    found = [
        m
        for m in pool
        if m.currency == currency
        and (m.amount > 0) == incoming
        and any(_near(leg, m) for leg in current.legs)
    ]

    def distance(m: Movement) -> int:
        return min(abs((m.day - leg.day).days) for leg in current.legs)

    def completes(m: Movement) -> bool:
        return abs(abs(m.amount) - current.pending) <= current.pending * PENDING_MARGIN

    def fits(m: Movement) -> bool:
        return abs(m.amount) <= limit

    ranked = sorted(
        found,
        key=lambda m: (not fits(m), not completes(m), distance(m), m.day, m.fingerprint),
    )
    return [Candidate(m, fits(m)) for m in ranked]


def suggestions(
    movements: Sequence[Movement],
    links: Links,
    banks: Collection[str],
    rate_for_month: RateForMonth,
) -> dict[str, str]:
    """Movimiento -> contraparte con la que parece un cambio de divisas.

    Las contrapartes se buscan por moneda y dirección, ordenadas por fecha: solo se miran las
    de la ventana (no todos contra todos).
    """
    pool = [m for m in movements if is_eligible(m, links, banks)]
    dop = {m.fingerprint: _dop(m, rate_for_month) for m in pool}
    buckets: dict[tuple[str, bool], list[Movement]] = {}
    for move in sorted(pool, key=lambda m: m.day):
        buckets.setdefault((move.currency, move.amount > 0), []).append(move)
    days = {key: [m.day.toordinal() for m in moves] for key, moves in buckets.items()}
    found: dict[str, str] = {}
    for move in pool:
        size = dop[move.fingerprint]
        if size is None or size < SUGGEST_MIN_DOP:
            continue
        key = (DOLLARS if move.currency == PESOS else PESOS, move.amount <= 0)
        bucket, ordinals = buckets.get(key, []), days.get(key, [])
        day = move.day.toordinal()
        start = bisect_left(ordinals, day - WINDOW_DAYS)
        end = bisect_right(ordinals, day + WINDOW_DAYS)
        options = [
            other
            for other in bucket[start:end]
            if _looks_like_exchange(move, other, dop, rate_for_month)
        ]
        if options:
            best = min(options, key=lambda o: _rank(move, o, dop, rate_for_month))
            found[move.fingerprint] = best.fingerprint
    return found


def _dop(move: Movement, rate_for_month: RateForMonth) -> Decimal | None:
    value = to_dop(abs(move.amount), move.currency, rate_for_month(move.month))
    return None if value is None else value


def _rate_gap(move: Movement, other: Movement, rate_for_month: RateForMonth) -> Decimal | None:
    official = rate_for_month(move.month)
    if official is None or official.value <= 0:
        return None
    pesos, dollars = (move, other) if move.currency == PESOS else (other, move)
    implied = abs(pesos.amount) / abs(dollars.amount)
    return abs(implied / official.value - 1)


def _looks_like_exchange(
    move: Movement,
    other: Movement,
    dop: Mapping[str, Decimal | None],
    rate_for_month: RateForMonth,
) -> bool:
    gap = _rate_gap(move, other, rate_for_month)
    if gap is not None and gap <= RATE_TOLERANCE:
        return True
    a, b = dop[move.fingerprint], dop[other.fingerprint]
    if a is None or b is None or max(a, b) == 0:
        return False
    return min(a, b) / max(a, b) >= SHARE_MIN


def _rank(
    move: Movement,
    other: Movement,
    dop: Mapping[str, Decimal | None],
    rate_for_month: RateForMonth,
) -> tuple[int, int, Decimal, str]:
    gap = _rate_gap(move, other, rate_for_month)
    close_rate = 0 if gap is not None and gap <= RATE_TOLERANCE else 1
    a, b = dop[move.fingerprint] or _ZERO, dop[other.fingerprint] or _ZERO
    return (close_rate, abs((move.day - other.day).days), abs(a - b), other.fingerprint)
