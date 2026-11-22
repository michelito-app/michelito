"""The "To review" list: the month's transactions worth a look, with local, deterministic
rules.

Pure functions over already loaded transactions. Kinds (`Kind`):
- "one_off": a possible one-off expense (`one_offs.suggest`, unchanged).
- "unusual_income": income of at least UNUSUAL_INCOME_DOP from a counterpart (merchant) that
  does not appear as income in the previous year. Only once there are NEW_COUNTERPART_DAYS of
  data before that day: at first everything would look new.
- "large_third_party": a transfer to third parties of at least LARGE_THIRD_PARTY_DOP.
- "duplicate": an expense with the same account, merchant, amount and currency as another one
  the same day or the day before (the second one is flagged). On the next day, only from
  NEXT_DAY_MIN_DOP; and not when that same charge already repeats (RECURRING_CHARGES or more in
  the previous RECURRING_DAYS, like a toll or parking).
- "price_up": a recurring charge whose price went up in the month (the Recurring alerts; the
  caller passes them already computed, by fingerprint).
- "possible_contribution" and "possible_return": a debit that looks like another contribution
  to an investment, or a credit that looks like a return from one (`investments.suggestions`;
  the caller passes them already computed, by fingerprint, as `Hint`). They only propose: the
  user confirms.
- "possible_rule": a merchant that was given the same category by hand ("only this one")
  several times (`changelog_rules.rule_suggestions`; the caller adds it, in the month of the
  most recent one).
- "possible_reserve": an expense that looks like it belongs to a reserve
  (`reserves.link_suggestions`; the caller adds it). "Yes" links it; "No" marks it reviewed and
  it doesn't come back.
- "possible_payment": a credit that looks like a payment from someone who owes you in a shared
  group, or the bank side of a payment written down unlinked
  (`ledger_suggest.reverse_suggestions`; the caller adds it). "Yes" records (or links) the
  payment; "No" marks it reviewed.
- "possible_cover": someone paid more than they owed in a shared group while another member
  still owes ("Was that payment for B too?"; `ledger_cover.cover_suggestion`, the caller adds it, in
  the payment's month). "Yes" opens that payment's "Also paid for…" in the group; "No"
  dismisses it in the ledger (`ledger_dismissals`), not here.
- "unconfirmed": a provisional transaction (from a bank alert) that did not show up in the
  statement covering its date (`live_store.unmatched`; the caller adds it). "Discard" hides it,
  "Keep" leaves it counted and marks it reviewed; both go in `provisional_decisions`.
- "reversal": the bank sent a reversal alert for a purchase that still counts: a provisional it
  could not void because it is linked (Discard once it is out of the link, or Keep), or one the
  statement charged anyway (Keep). `live_store.reversals`; the caller adds it.

What already belongs to an investment doesn't show up as "large_third_party" (a contribution is
"Investments", not "Transfers to third parties") nor as "unusual_income" (neither the yield nor
the capital coming back). A transaction proposed as a contribution or return shows up only with
that proposal, unless it was already reviewed ("It's not"): then the proposal is reviewed (only
in the history) and whatever else it is shows up again.

What was reviewed is stored apart by fingerprint and kind (`review_marks`; one-off expenses use
their usual dismissals, `one_off_dismissals`), so it survives `parse --retry`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, get_args

from michelito.analysis import categories, one_offs
from michelito.analysis.rates import Rate, to_dop
from michelito.analysis.recurring_marks import Mark
from michelito.analysis.report import money
from michelito.analysis.spending import Movement
from michelito.i18n import t

Kind = Literal[
    "one_off",
    "unusual_income",
    "large_third_party",
    "duplicate",
    "price_up",
    "possible_contribution",
    "possible_return",
    "possible_rule",
    "possible_reserve",
    "possible_payment",
    "possible_cover",
    "unconfirmed",
    "reversal",
    "possible_receipt",
]
KINDS: tuple[Kind, ...] = get_args(Kind)

UNUSUAL_INCOME_DOP = Decimal(10_000)
LARGE_THIRD_PARTY_DOP = Decimal(25_000)
NEW_COUNTERPART_DAYS = 60
HISTORY_DAYS = 365
DUPLICATE_DAYS = 1
NEXT_DAY_MIN_DOP = Decimal(500)  # on the next day, a duplicate is flagged from this amount
RECURRING_DAYS = 60  # the same charge repeated this many times in these days is not a duplicate
RECURRING_CHARGES = 3

RateForMonth = Callable[[str], Rate | None]


@dataclass(frozen=True)
class Item:
    kind: Kind
    fingerprint: str
    day: date
    merchant: str
    description: str
    account: str
    amount: Decimal  # in the original currency, positive (what came in or went out)
    currency: str
    amount_dop: Decimal | None  # None: US$ without a rate
    reason: str
    reviewed: bool = False
    investment_id: int | None = None  # possible contribution or return: the proposed investment
    category_id: int | None = None  # possible rule: the proposed category
    reserve_id: int | None = None  # possible reserve: the proposed reserve
    # Possible payment: the group, who seems to pay (None: unattributed) and, if it reconciles
    # one already written down, that payment.
    group_id: int | None = None
    contact_id: int | None = None
    payment_id: int | None = None
    payment_ids: tuple[int, ...] = ()  # possible cover: every payment of the suggestion
    provisional: bool = False  # the movement is still provisional (it can be discarded)
    receipt_id: int | None = None  # possible receipt: the merchant receipt proposed for it


@dataclass(frozen=True)
class Hint:
    """An investment proposal for a transaction (see `investments.suggestions`)."""

    kind: Kind  # "possible_contribution" or "possible_return"
    reason: str
    investment_id: int


def detect(
    movements: Sequence[Movement],
    month: str,
    *,
    rate_for_month: RateForMonth,
    marks: Mapping[tuple[str, str], Mark] | None = None,
    price_ups: Mapping[str, str] | None = None,
    reviewed: Collection[tuple[str, str]] = (),
    dismissed: Collection[str] = (),
    hints: Mapping[str, Hint] | None = None,
    unions: Mapping[str, str] | None = None,
) -> list[Item]:
    """Everything in `month` to review, pending and reviewed (`Item.reviewed`).

    `reviewed`: (fingerprint, kind) pairs marked "Already reviewed"; `dismissed`: dismissed
    one-off expenses ("Not a one-off"), which count as reviewed. `price_ups`: fingerprint of the
    charge that went up -> the Recurring alert's sentence. `hints`: fingerprint -> possible
    contribution or return.
    """
    done = set(reviewed)
    # A proposal already reviewed ("It's not") doesn't hide what that transaction is by itself.
    proposed = {fp: hint for fp, hint in (hints or {}).items() if (fp, hint.kind) not in done}
    found = [
        *_one_offs(movements, month, rate_for_month, marks or {}, dismissed, unions),
        *(
            i
            for i in _unusual_incomes(movements, month, rate_for_month)
            if i.fingerprint not in proposed
        ),
        *(
            i
            for i in _large_third_party(movements, month, rate_for_month)
            if i.fingerprint not in proposed
        ),
        *_duplicates(movements, month, rate_for_month),
        *_price_ups(movements, month, rate_for_month, price_ups or {}),
        *_investment_hints(movements, month, rate_for_month, hints or {}),
    ]
    marked = [
        _with_reviewed(
            item,
            (item.fingerprint, item.kind) in done
            or (item.kind == "one_off" and item.fingerprint in dismissed),
        )
        for item in found
    ]
    return sorted(marked, key=lambda i: (-i.day.toordinal(), KINDS.index(i.kind), i.fingerprint))


def _with_reviewed(item: Item, reviewed: bool) -> Item:
    return item if item.reviewed == reviewed else replace(item, reviewed=reviewed)


def _item(kind: Kind, move: Movement, dop: Decimal | None, reason: str) -> Item:
    return Item(
        kind=kind,
        fingerprint=move.fingerprint,
        day=move.day,
        merchant=move.merchant,
        description=move.description,
        account=move.account,
        amount=abs(move.amount),
        currency=move.currency,
        amount_dop=None if dop is None else abs(dop),
        reason=reason,
    )


def _dop(move: Movement, rate_for_month: RateForMonth) -> Decimal | None:
    return to_dop(move.amount, move.currency, rate_for_month(move.month))


def _one_offs(
    movements: Sequence[Movement],
    month: str,
    rate_for_month: RateForMonth,
    marks: Mapping[tuple[str, str], Mark],
    dismissed: Collection[str],
    unions: Mapping[str, str] | None = None,
) -> list[Item]:
    """The pending suggestions and, apart, the already dismissed ones (for the history)."""

    def suggest(skip: Collection[str], limit: int | None) -> list[one_offs.Suggestion]:
        return one_offs.suggest(
            movements,
            month,
            rate_for_month=rate_for_month,
            dismissed=skip,
            marks=marks,
            limit=limit,
            unions=unions,
        )

    pending = suggest(dismissed, one_offs.MAX_PER_MONTH)
    seen = {s.fingerprint for s in pending}
    # No cap: a dismissed one must not drop out of the history because 5 larger ones exist.
    everything = suggest((), None)
    done = [s for s in everything if s.fingerprint in dismissed and s.fingerprint not in seen]
    by_fp = {m.fingerprint: m for m in movements}
    return [
        _item("one_off", by_fp[s.fingerprint], s.amount_dop, " · ".join(s.reasons))
        for s in (*pending, *done)
        if s.fingerprint in by_fp
    ]


def _unusual_incomes(
    movements: Sequence[Movement], month: str, rate_for_month: RateForMonth
) -> list[Item]:
    if not movements:
        return []
    first = min(m.day for m in movements)
    incomes = [m for m in movements if m.kind == "income" and m.amount < 0]
    found = []
    for move in incomes:
        if move.link == "investment":
            continue  # a yield already linked: its origin is known
        if move.month != month or move.day - first < timedelta(days=NEW_COUNTERPART_DAYS):
            continue
        dop = _dop(move, rate_for_month)
        if dop is None or -dop < UNUSUAL_INCOME_DOP:
            continue
        start = move.day - timedelta(days=HISTORY_DAYS)
        seen = any(
            other.merchant == move.merchant and start <= other.day < move.day for other in incomes
        )
        if not seen:
            known = min(HISTORY_DAYS, (move.day - first).days)
            since = (
                t("analysis.review.since_last_year")
                if known >= HISTORY_DAYS
                else t("analysis.review.since_last_days", days=known)
            )
            reason = t("analysis.review.unusual_income", amount=money(-dop, "DOP"), since=since)
            found.append(_item("unusual_income", move, dop, reason))
    return found


def _large_third_party(
    movements: Sequence[Movement], month: str, rate_for_month: RateForMonth
) -> list[Item]:
    found = []
    for move in movements:
        if move.month != month or move.ref != categories.THIRD_PARTY or move.amount <= 0:
            continue
        dop = _dop(move, rate_for_month)
        if dop is not None and dop >= LARGE_THIRD_PARTY_DOP:
            reason = t(
                "analysis.review.large_third_party",
                amount=money(dop, "DOP"),
                threshold=money(LARGE_THIRD_PARTY_DOP, "DOP"),
            )
            found.append(_item("large_third_party", move, dop, reason))
    return found


def _investment_hints(
    movements: Iterable[Movement],
    month: str,
    rate_for_month: RateForMonth,
    hints: Mapping[str, Hint],
) -> list[Item]:
    found = []
    for move in movements:
        hint = hints.get(move.fingerprint)
        if hint is None or move.month != month:
            continue
        item = _item(hint.kind, move, _dop(move, rate_for_month), hint.reason)
        found.append(replace(item, investment_id=hint.investment_id))
    return found


def _duplicates(
    movements: Sequence[Movement], month: str, rate_for_month: RateForMonth
) -> list[Item]:
    groups: defaultdict[tuple[str, str, Decimal, str], list[Movement]] = defaultdict(list)
    for move in movements:
        if move.kind == "expense" and move.amount > 0:
            groups[(move.account, move.merchant, move.amount, move.currency)].append(move)
    found = []
    for charges in groups.values():
        charges.sort(key=lambda m: (m.day, m.fingerprint))
        for index, (before, after) in enumerate(zip(charges, charges[1:], strict=False)):
            if after.month != month or (after.day - before.day).days > DUPLICATE_DAYS:
                continue
            dop = _dop(after, rate_for_month)
            same_day = after.day == before.day
            if not same_day and (dop if dop is not None else after.amount) < NEXT_DAY_MIN_DOP:
                continue  # a small charge on the next day (a toll, a coffee) is normal
            if _recurs(charges[:index], before.day):
                continue
            when = t("analysis.review.same_day" if same_day else "analysis.review.previous_day")
            reason = t("analysis.review.duplicate", when=when)
            found.append(_item("duplicate", after, dop, reason))
    return found


def _recurs(earlier: Sequence[Movement], day: date) -> bool:
    """The same charge already repeats: RECURRING_CHARGES or more in the previous RECURRING_DAYS."""
    start = day - timedelta(days=RECURRING_DAYS)
    return sum(1 for m in earlier if start <= m.day < day) >= RECURRING_CHARGES


def _price_ups(
    movements: Iterable[Movement],
    month: str,
    rate_for_month: RateForMonth,
    price_ups: Mapping[str, str],
) -> list[Item]:
    return [
        _item("price_up", move, _dop(move, rate_for_month), price_ups[move.fingerprint])
        for move in movements
        if move.fingerprint in price_ups and move.month == month
    ]
