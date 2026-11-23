"""Matching card charges to installment plans (pure; the storage is `installment_store`).

A plan is the charges of one purchase paid in monthly installments on one card. A charge is
installment n of a plan when it is on the plan's card, in its currency, its description starts
with the plan's matcher (the merchant's prefix up to its `*`: the reference after it changes on
every charge) and it falls in the n-th calendar month from the plan's first month.

- `match` links the exact ones (the installment's amount, the only charge for that number);
  anything else that looks like the plan is `off_script`, for the person to decide in review:
  another amount, two charges for one month, a charge after the last installment or a refund.
- `missing` says which installments did not arrive although the card already has later data.
- `earlier_in_a_row` finds, when a plan is created from a charge, the earlier installments that
  were already paid (one per month, with no gap).

A charge two plans could take goes to the first one (the oldest), never to both.
"""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from michelito.analysis.shared import fold

Reason = Literal["amount", "repeated", "after_end", "refund"]
REASONS: tuple[Reason, ...] = ("amount", "repeated", "after_end", "refund")
# Days after an installment's usual day before its absence counts as missing (statements are
# not cut on the same day every month).
GRACE_DAYS = 7
# A charge at the plan's merchant this many months after its last installment is still asked
# about; later ones are other purchases.
AFTER_END_MONTHS = 2
_MATCHER_WORDS = 2
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Terms:
    """What a plan needs for matching."""

    plan_id: int
    account: str
    matcher: str  # folded prefix of the description
    amount_cents: int  # per installment, positive
    currency: str
    count: int
    first_month: str  # "YYYY-MM"


@dataclass(frozen=True)
class Charge:
    fingerprint: str
    day: date
    account: str
    description: str
    cents: int  # positive: a charge; negative: a refund
    currency: str

    @property
    def month(self) -> str:
        return self.day.strftime("%Y-%m")


@dataclass(frozen=True)
class OffScript:
    plan_id: int
    reason: Reason
    number: int | None  # the installment it would be (None for a refund)


@dataclass(frozen=True)
class Matches:
    links: dict[str, tuple[int, int]] = field(default_factory=dict)  # fp -> (plan, number)
    off_script: dict[str, OffScript] = field(default_factory=dict)


def matcher_of(description: str) -> str:
    """The stable part of a charge's description: up to its first `*` (included), or its first
    words when it has none."""
    text = _SPACES.sub(" ", fold(description).strip())
    if "*" in text:
        head = text[: text.index("*") + 1]
        return head if len(head) > 1 else ""
    return " ".join(text.split(" ")[:_MATCHER_WORDS])


def matches_text(matcher: str, description: str) -> bool:
    return bool(matcher) and _SPACES.sub(" ", fold(description).strip()).startswith(matcher)


def _month_index(month: str) -> int:
    year, number = (int(part) for part in month.split("-"))
    return year * 12 + number - 1


def number_for(first_month: str, month: str) -> int:
    """Which installment falls in `month` (1 for the first month; < 1 before the plan)."""
    return _month_index(month) - _month_index(first_month) + 1


def month_of_number(first_month: str, number: int) -> str:
    index = _month_index(first_month) + number - 1
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _belongs(plan: Terms, row: Charge) -> bool:
    return (
        row.account == plan.account
        and row.currency == plan.currency
        and matches_text(plan.matcher, row.description)
    )


def match(
    plans: Sequence[Terms],
    charges: Sequence[Charge],
    taken: Mapping[str, tuple[int, int]] | None = None,
    dismissed: Collection[tuple[int, str]] = (),
) -> Matches:
    """New links and the off-script charges. `taken`: the links already stored (fingerprint ->
    plan and number); `dismissed`: (plan, fingerprint) pairs the person refused."""
    stored = dict(taken or {})
    numbers_taken = {(plan, number) for plan, number in stored.values()}
    links: dict[str, tuple[int, int]] = {}
    off: dict[str, OffScript] = {}
    for plan in plans:
        exact: dict[int, list[Charge]] = defaultdict(list)
        for row in charges:
            if (
                row.fingerprint in stored
                or row.fingerprint in links
                or (plan.plan_id, row.fingerprint) in dismissed
            ):
                continue
            if not _belongs(plan, row):
                continue
            number = number_for(plan.first_month, row.month)
            if number < 1:
                continue
            if row.cents < 0:
                off[row.fingerprint] = OffScript(plan.plan_id, "refund", None)
            elif number > plan.count + AFTER_END_MONTHS:
                continue
            elif number > plan.count:
                off[row.fingerprint] = OffScript(plan.plan_id, "after_end", number)
            elif row.cents != plan.amount_cents:
                off[row.fingerprint] = OffScript(plan.plan_id, "amount", number)
            else:
                exact[number].append(row)
        for number, rows in exact.items():
            if len(rows) == 1 and (plan.plan_id, number) not in numbers_taken:
                links[rows[0].fingerprint] = (plan.plan_id, number)
                off.pop(rows[0].fingerprint, None)
                continue
            for row in rows:
                off[row.fingerprint] = OffScript(plan.plan_id, "repeated", number)
    return Matches(links, off)


def _day_in(month: str, day_of_month: int) -> date:
    year, number = (int(part) for part in month.split("-"))
    return date(year, number, min(day_of_month, calendar.monthrange(year, number)[1]))


def missing(plan: Terms, linked: Mapping[int, date], last_day: date | None) -> list[int]:
    """The installments with no charge whose usual day (that of the first linked one) plus
    `GRACE_DAYS` is already before the card's latest data. Nothing without any linked charge."""
    if not linked or last_day is None:
        return []
    usual = linked[min(linked)].day
    return [
        number
        for number in range(1, plan.count + 1)
        if number not in linked
        and _day_in(month_of_number(plan.first_month, number), usual) + timedelta(days=GRACE_DAYS)
        < last_day
    ]


def earlier_in_a_row(charges: Sequence[Charge], chosen: Charge) -> list[str]:
    """`chosen` and the charges like it (same card, currency, matcher and amount) in each month
    right before it, with no gap: the installments already paid, oldest first."""
    matcher = matcher_of(chosen.description)
    by_month: dict[str, Charge] = {}
    for row in charges:
        if (
            row.account == chosen.account
            and row.currency == chosen.currency
            and row.cents == chosen.cents
            and matches_text(matcher, row.description)
        ):
            by_month.setdefault(row.month, row)
    found = [chosen.fingerprint]
    month = chosen.month
    while True:
        month = month_of_number(month, 0)
        earlier = by_month.get(month)
        if earlier is None:
            return found[::-1]
        found.append(earlier.fingerprint)
