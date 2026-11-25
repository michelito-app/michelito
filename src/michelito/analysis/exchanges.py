"""Currency exchanges with third parties: linked RD$ and US$ legs (see `links`).

An exchange groups one or more legs in each currency, from any of the user's bank accounts:
those of one currency in one direction (all going out or all coming in) and those of the
other in the opposite one. Linked legs are the currency-exchange category: neither expense,
nor income, nor third-party transfer, so they do not move the month's "what you kept".

Math:
- The **base** side is the one of the oldest leg (what you gave or received first); the
  other, what comes back.
- Rate (RD$ per US$): the agreed one if the user set it; otherwise the one implied by the
  first complete pair: the RD$ sum of the peso legs of the first day with peso legs, divided
  by the US$ sum of the dollar legs of the first day with dollar legs (4 decimals).
- Pending: the base side converted to the other currency at that rate, minus what came back
  in the other currency (never negative), in cents; also in RD$ (at the same rate).
- "Exchange complete" closes it: the pending amount becomes 0 even if it does not balance.

Suggestions: a bank transaction of at least SUGGEST_MIN_DOP (US$ at the month's rate) with a
counterpart in the other currency and opposite direction, from any bank account, at most
WINDOW_DAYS days before or after, whose implied rate is within ±RATE_TOLERANCE of the month's
official rate or that covers a good share (the smaller of the two in RD$ is at least
SHARE_MIN of the larger). Neither is salary, a card payment, a transfer between my accounts
or another link. Nothing is ever linked automatically.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from michelito.analysis import categories
from michelito.analysis.links import Candidate, Exchange, LinkError, Links
from michelito.analysis.rates import Rate, to_dop
from michelito.i18n import t

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

WINDOW_DAYS = 30
SUGGEST_MIN_DOP = Decimal(20_000)
RATE_TOLERANCE = Decimal("0.05")
SHARE_MIN = Decimal("0.5")
PENDING_MARGIN = Decimal("0.05")  # when adding legs: fits the pending amount / completes it
PICK_RATE_GAP = Decimal(
    "0.10"
)  # when starting an exchange: farther from the month's rate, behind "See more"
PESOS, DOLLARS = "DOP", "USD"
CURRENCIES = frozenset({PESOS, DOLLARS})
_RATE = Decimal("0.0001")
_CENT = Decimal("0.01")
_ZERO = Decimal(0)
# Transactions that are never a leg of an exchange.
NOT_A_LEG = frozenset(
    {
        categories.SALARY,
        categories.CARD_PAYMENT,
        categories.OWN_TRANSFER,
        categories.REIMBURSEMENT,
        categories.CURRENCY_EXCHANGE,
        categories.CRYPTO,
    }
)

RateForMonth = Callable[[str], Rate | None]


@dataclass(frozen=True)
class ExchangeState:
    exchange: Exchange
    legs: tuple[Movement, ...]  # the legs present, by date
    totals: Mapping[str, Decimal]  # absolute amount per currency
    base: str  # currency of the base side
    rate: Decimal  # RD$ per US$: the agreed or the implied one
    implied_rate: Decimal
    pending: Decimal  # in the `pending_currency` currency
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
        """Only the first pair (the legs of each currency's first day): with no agreed rate,
        the implied one comes from those same legs and the pending amount is 0 by definition."""
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
    """Error if the legs do not form an exchange: RD$ and US$, each currency in a single
    direction and the two in opposite directions."""
    by_currency = sides(legs)
    if set(by_currency) != CURRENCIES:
        raise LinkError(t("analysis.exchanges.needs_both_currencies"))
    signs = {currency: {m.amount > 0 for m in moves} for currency, moves in by_currency.items()}
    if any(len(s) != 1 for s in signs.values()) or signs[PESOS] == signs[DOLLARS]:
        raise LinkError(t("analysis.exchanges.opposite_directions"))
    if any(m.amount == 0 for m in legs):
        raise LinkError(t("analysis.exchanges.zero_leg"))


def implied_rate(legs: Sequence[Movement]) -> Decimal:
    by_currency = sides(legs)
    dop_total = _first_day_total(by_currency[PESOS])
    usd_total = _first_day_total(by_currency[DOLLARS])
    return (dop_total / usd_total).quantize(_RATE, rounding=ROUND_HALF_EVEN)


def _first_day_total(moves: Sequence[Movement]) -> Decimal:
    first = min(m.day for m in moves)
    return sum((abs(m.amount) for m in moves if m.day == first), _ZERO)


def state(exchange: Exchange, by_fingerprint: Mapping[str, Movement]) -> ExchangeState | None:
    """The exchange's math; None if the legs present no longer form an exchange."""
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
    """Can be a leg: from a bank account, in RD$ or US$, with no excluded category and no
    other link."""
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
    """Possible legs, already sorted and flagged (`primary`: they go in the visible part).

    - No exchange: those in the other currency and opposite direction to `target` within
      ±WINDOW_DAYS days, by how close the pair's implied rate is to the official one of
      `target`'s month; those farther than PICK_RATE_GAP (or with no rate) are not primary.
    - An exchange (`current`) with a pending amount: only the missing side (the pending
      currency, in the direction of the side that comes back) near some leg. Primary are
      those that fit the pending amount with a PENDING_MARGIN margin: first those that
      complete it, then by date proximity; those that exceed it (e.g. because of the bank's
      spread) come after, by date proximity, behind "See more".
    - An exchange with nothing pending: those that fit either of its two sides, none primary.
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
    """Transaction -> counterpart with which it looks like a currency exchange.

    Counterparts are looked up by currency and direction, sorted by date: only those inside
    the window are checked (not all against all).
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
    dop_leg, usd_leg = (move, other) if move.currency == PESOS else (other, move)
    implied = abs(dop_leg.amount) / abs(usd_leg.amount)
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
