"""One-off expense suggestions: the month's large, rare purchases, with local rules.

Pure functions over already loaded transactions; nothing leaves the machine. A purchase of the
month is a candidate only if it meets all of these:
- it is an expense with a positive amount, not marked as one-off nor dismissed, and not a loan
  payment (large and fixed by nature: not an extraordinary expense);
- it is not a recurring charge (`recurring.detect` corrected by the user's marks) nor an
  installment ("CUOTA", "3/12");
- it is worth at least MIN_AMOUNT_DOP in RD$ (US$ at the month's rate);
- against the purchases in its category over the last year (without one-offs): with at least
  MIN_CATEGORY_HISTORY of them, it is worth CATEGORY_FACTOR times their median; with fewer, the
  category itself is rare and the condition counts as met;
- and the merchant barely appears in that year (once at most) or the purchase is worth
  MERCHANT_FACTOR times the merchant's median.

The order is by rarity: times the category's median or, without a median, times MIN_AMOUNT_DOP.

Confirming a suggestion marks the one-off expense; dismissing it is stored apart
(`one_off_dismissals`) and the purchase keeps counting as normal history.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from michelito.analysis import categories, recurring
from michelito.analysis.rates import Rate, to_dop
from michelito.analysis.recurring_marks import Mark, for_series
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.parsers.common import normalize

MIN_AMOUNT_DOP = Decimal(10_000)
CATEGORY_FACTOR = Decimal(3)
MERCHANT_FACTOR = Decimal(3)
MIN_CATEGORY_HISTORY = 3
MAX_MERCHANT_SEEN = 1  # times seen in the year that still count as a new merchant
HISTORY_DAYS = 365
MAX_PER_MONTH = 5

_INSTALLMENT_WORD = re.compile(r"\bCUOTAS?\b")
# "3/12": installment a of b. Counts only if 1 <= a <= b and b is a credible term (2 to 60
# months), so "24/7" or a date "12/05" don't pass for installments.
_INSTALLMENT_FRACTION = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b")
_MAX_INSTALLMENTS = 60
# Recurring marks that confirm the merchant charges by itself (see `recurring_marks`).
_RECURRING_STATUSES = frozenset({"confirmed", "cancelled"})
_RATIO = Decimal("0.1")
# Expense categories never suggested as one-off.
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
    """ "CUOTA 3", "03/12": part of a financed purchase, not a new purchase."""
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
    """(merchant, currency) pairs that charge by themselves: the detected ones plus those the
    user marked.

    "It's recurring", "I cancelled it" or noted installments add it; "Not recurring" removes it
    even if `recurring.detect` finds it. A series (a provider or a union) counts for all its
    merchants.
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
    """Up to `limit` purchases of `month` that look like one-off expenses, the rarest first.

    `marks`: the user's recurring marks (`recurring_marks.load`), by merchant (or series) and
    currency; `unions`: the merchant unions in Recurring.
    `limit`: None means all (the "To review" history must not lose the dismissed ones).
    """
    expenses = [m for m in movements if m.kind == "expense"]
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
    """To RD$ at each month's rate; US$ without a rate are left out."""
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
        reasons.append(
            t("analysis.one_offs.category_times", times=_times(score), category=move.category)
        )
    else:
        score = item.dop / MIN_AMOUNT_DOP  # in "times", like the ratio to the median
        reasons.append(t("analysis.one_offs.rare_category"))
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
        return t("analysis.one_offs.new_merchant")
    if len(seen) <= MAX_MERCHANT_SEEN:
        return t("analysis.one_offs.infrequent_merchant")
    typical = median(seen)
    if item.dop < MERCHANT_FACTOR * typical:
        return None
    return t(
        "analysis.one_offs.merchant_times",
        times=_times(item.dop / typical),
        merchant=item.move.merchant,
    )


def _times(ratio: Decimal) -> str:
    return str(ratio.quantize(_RATIO))
