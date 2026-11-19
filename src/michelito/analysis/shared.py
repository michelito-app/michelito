"""A shared group's accounting: your share, what was reimbursed and what you are owed, per
expense.

A group has one or more expenses, each with its split. For an expense of amount A, your share S
comes from its split:
- "We were N": S = A / N, rounded to the cent (half to even);
- "My share: X": S = X (0 < X <= A);
- "I paid it for someone else": S = 0.
What you are owed for that expense is A - S, in its currency.

Reimbursements (linked credits and those entered by hand, together) are applied **from the
oldest expense to the newest** (FIFO): in (date, fingerprint) order, each one first settles
what is left of the oldest expense ((date, fingerprint) order) and the rest goes to the next. A
reimbursement in a currency other than the expense it is settling is converted at the rate of
the reimbursement's month (the one `converted` uses); the rest goes back to its currency at
that same rate and moves on to the next expense. Without a rate to convert, the rest of that
reimbursement doesn't count (`unconverted`: the interface warns).
- An expense's pending P = A - S - what was applied; the group's, P by currency.
- Excess: what is left of the reimbursements after settling every expense, in each
  reimbursement's currency; it doesn't count nor lower your share (the interface warns: it is
  usually a repeated reimbursement).
- What counts as expense: S while P is pending; with "They won't pay me" (for the whole group)
  S + P on each expense: the pending amount goes back to its expense (in its month), which by
  FIFO are the most recent ones.

Linked credits stop being income or transfers: they are "reimbursement" (see `spending`),
except one that counted nothing for lack of a rate (otherwise that money would vanish from the
totals).

A group's possible reimbursements (`pick_credits`): credits from any account and currency (with
a rate to convert them to each expense's currency), from the oldest expense up to
PICK_WINDOW_DAYS days after the newest (sometimes people pay months later), that don't exceed
what was spent in the group (one equal to a single expense in its currency is usually its
refund), and that are not salary, card payments, transfers between my accounts, interest or
another link. First the ones that fit in the pending amount (with a PENDING_MARGIN margin). A
credit is *suggested* for linking, without asking (`suggestions`), if it is in the group's
currency, arrives at most SUGGEST_WINDOW_DAYS days after one of the group's expenses and fits
in its pending amount; or if its description has a word (4 letters or more, without accents or
capitals) from the "With whom" of a group with something pending, in any currency (with a
rate) and up to PICK_WINDOW_DAYS days after the oldest pending expense. Nothing is ever linked
automatically.

The conversion is redone on every read with the stored rates: if you change a month's rate by
hand, or the BCRD rate arrives for a month that used the previous one, the reimbursed amount
changes with it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from michelito.analysis import categories
from michelito.analysis.links import Candidate, Links, Shared, SharedExpense
from michelito.analysis.rates import Rate, rate_for

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

PICK_WINDOW_DAYS = 120  # what "They paid part back" / "It's a reimbursement of…" lists
SUGGEST_WINDOW_DAYS = 14  # what is suggested by amount alone ("Reimbursement?")
PENDING_MARGIN = Decimal("0.05")  # in the pickers: "fits in the pending amount" with this margin
NAME_MIN_LETTERS = 4  # words of "With whom" that count for suggesting by name
_CENT = Decimal("0.01")
_NO_RATES: Mapping[str, Rate] = {}
_ZERO = Decimal(0)
_MANUAL = "manual:"
# Below this, what was returned in excess is conversion rounding: neither excess nor warning.
_MIN_EXCESS = {"DOP": Decimal(1), "USD": Decimal("0.05")}
# Credits that are never the reimbursement of a shared expense.
NOT_REIMBURSEMENT = frozenset(
    {
        categories.SALARY,
        categories.OWN_TRANSFER,
        categories.CARD_PAYMENT,
        categories.CURRENCY_EXCHANGE,
        categories.REIMBURSEMENT,
    }
)
# Transactions that are never a shared expense ("Add another expense"): cash withdrawals, loan
# payments (the "AUT PAGO" ones), card payments, transfers between my accounts and currency
# exchanges.
NOT_SHARED_EXPENSE = frozenset(
    {
        categories.CASH,
        categories.LOANS,
        categories.CARD_PAYMENT,
        categories.OWN_TRANSFER,
        categories.CURRENCY_EXCHANGE,
    }
)
# Interest paid by the bank: it lands in "other income" like a transfer, but is never a
# reimbursement.
_INTEREST = re.compile(r"\bINTERES(ES)?\b")
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ExpenseState:
    """One of the group's expenses after applying the reimbursements (in its currency)."""

    move: Movement
    split: SharedExpense
    amount: Decimal  # the whole expense
    share: Decimal  # your share by its split
    reimbursed: Decimal  # what was applied to this expense
    pending: Decimal  # what you are owed for this expense (0 with "They won't pay me")
    written_off: Decimal  # the pending amount that went back to your expense

    @property
    def fingerprint(self) -> str:
        return self.move.fingerprint

    @property
    def currency(self) -> str:
        return self.move.currency

    @property
    def day(self) -> date:
        return self.move.day

    @property
    def owed(self) -> Decimal:
        return self.amount - self.share

    @property
    def counted(self) -> Decimal:
        """What counts as your expense."""
        return self.share + self.written_off


@dataclass(frozen=True)
class Refund:
    """A group reimbursement: a linked credit (its fingerprint) or one by hand (`manual:<id>`)."""

    key: str
    day: date
    amount: Decimal  # positive, in `currency`
    currency: str

    @property
    def is_manual(self) -> bool:
        return self.key.startswith(_MANUAL)


@dataclass(frozen=True)
class CurrencyTotals:
    currency: str
    share: Decimal
    reimbursed: Decimal
    pending: Decimal
    written_off: Decimal


@dataclass(frozen=True)
class SharedState:
    link: Shared
    expenses: tuple[ExpenseState, ...]  # oldest to newest
    refunds: tuple[Refund, ...]  # in the order they are applied
    excess_by: tuple[
        tuple[str, Decimal], ...
    ] = ()  # left over after settling everything, by currency
    unconverted: tuple[str, ...] = ()  # reimbursements (or their rest) that didn't count: no rate
    uncounted: frozenset[str] = frozenset()  # credits that counted nothing (no rate)

    @property
    def id(self) -> int:
        return self.link.id

    @property
    def first(self) -> ExpenseState:
        return self.expenses[0]

    @property
    def title(self) -> str:
        """The name, else "With whom", else the first expense's merchant."""
        move = self.first.move
        return self.link.name or self.link.with_whom or move.merchant or move.description

    @property
    def pending(self) -> dict[str, Decimal]:
        """What you are owed, by currency (only those with something)."""
        return {t.currency: t.pending for t in self.totals if t.pending > 0}

    @property
    def excess(self) -> dict[str, Decimal]:
        return dict(self.excess_by)

    @property
    def has_pending(self) -> bool:
        return any(e.pending > 0 for e in self.expenses)

    @property
    def oldest_pending(self) -> ExpenseState | None:
        return next((e for e in self.expenses if e.pending > 0), None)

    @property
    def last_day(self) -> date:
        return max(e.day for e in self.expenses)

    @property
    def totals(self) -> tuple[CurrencyTotals, ...]:
        """Your share, what was returned, what is pending and what was written off, for each
        currency's expenses (RD$ before US$)."""
        found = []
        for currency in sorted({e.currency for e in self.expenses}):
            mine = [e for e in self.expenses if e.currency == currency]
            found.append(
                CurrencyTotals(
                    currency,
                    sum((e.share for e in mine), _ZERO),
                    sum((e.reimbursed for e in mine), _ZERO),
                    sum((e.pending for e in mine), _ZERO),
                    sum((e.written_off for e in mine), _ZERO),
                )
            )
        return tuple(found)

    def expense(self, fingerprint: str) -> ExpenseState | None:
        return next((e for e in self.expenses if e.fingerprint == fingerprint), None)


def nominal_share(split: SharedExpense, amount: Decimal) -> Decimal:
    if split.for_other:
        return _ZERO
    if split.people is not None:
        return (amount / split.people).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    return min(split.my_share if split.my_share is not None else amount, amount)


def convert(
    amount: Decimal, source: str, target: str, day: date, rates: Mapping[str, Rate]
) -> Decimal | None:
    """`amount` in `source` converted to `target` at the rate of `day`'s month (or the closest
    previous month's), to the cent. Unchanged for the same currency; `None` without a rate."""
    if source == target:
        return amount
    rate = rate_for(rates, day.strftime("%Y-%m"))
    if rate is None or rate.value <= 0:
        return None
    if source == "DOP" and target == "USD":
        return (amount / rate.value).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    if source == "USD" and target == "DOP":
        return (amount * rate.value).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    return None


def converted(credit: Movement, currency: str, rates: Mapping[str, Rate]) -> Decimal | None:
    """What came in with the credit (positive), in `currency` (see `convert`)."""
    return convert(-credit.amount, credit.currency, currency, credit.day, rates)


def gross(move: Movement) -> Decimal:
    """The transaction's amount before splitting (the statement's)."""
    return move.amount if move.gross is None else move.gross


def refunds_of(link: Shared, by_fingerprint: Mapping[str, Movement]) -> tuple[Refund, ...]:
    """The group's present reimbursements, in the order they are applied (date, fingerprint)."""
    found = [
        Refund(fp, move.day, -move.amount, move.currency)
        for fp in link.reimbursements
        if (move := by_fingerprint.get(fp)) is not None and move.amount < 0
    ]
    found.extend(Refund(f"{_MANUAL}{m.id}", m.day, m.amount, m.currency) for m in link.manual)
    return tuple(sorted(found, key=lambda r: (r.day, r.key)))


def group_state(
    link: Shared,
    expenses: Sequence[Movement],
    by_fingerprint: Mapping[str, Movement],
    rates: Mapping[str, Rate] = _NO_RATES,
) -> SharedState:
    """The group's accounting with these present expenses (at least one; its amount is `gross`)."""
    ordered = sorted(expenses, key=lambda m: (m.day, m.fingerprint))
    splits = [link.split(m.fingerprint) or SharedExpense(m.fingerprint) for m in ordered]
    amounts = [gross(m) for m in ordered]
    shares = [nominal_share(s, a) for s, a in zip(splits, amounts, strict=True)]
    remaining = [a - s for a, s in zip(amounts, shares, strict=True)]
    applied = [_ZERO] * len(ordered)
    refunds = refunds_of(link, by_fingerprint)
    excess: dict[str, Decimal] = {}
    unconverted: list[str] = []
    uncounted: set[str] = set()
    for refund in refunds:
        left, counted, blocked = _impute(refund, ordered, remaining, applied, rates)
        if left <= 0:
            continue
        if not blocked:
            excess[refund.currency] = excess.get(refund.currency, _ZERO) + left
            continue
        # What is left belonged to an expense without a rate to convert it: it doesn't count.
        unconverted.append(refund.key)
        if not counted and not refund.is_manual:
            uncounted.add(refund.key)
    states = tuple(
        ExpenseState(
            move=move,
            split=split,
            amount=amount,
            share=share,
            reimbursed=applied[index],
            pending=_ZERO if link.written_off else remaining[index],
            written_off=remaining[index] if link.written_off else _ZERO,
        )
        for index, (move, split, amount, share) in enumerate(
            zip(ordered, splits, amounts, shares, strict=True)
        )
    )
    return SharedState(
        link=link,
        expenses=states,
        refunds=refunds,
        excess_by=tuple(sorted((c, v) for c, v in excess.items() if v >= _MIN_EXCESS[c])),
        unconverted=tuple(unconverted),
        uncounted=frozenset(uncounted),
    )


def _impute(
    refund: Refund,
    ordered: Sequence[Movement],
    remaining: list[Decimal],
    applied: list[Decimal],
    rates: Mapping[str, Rate],
) -> tuple[Decimal, bool, bool]:
    """Applies a reimbursement from the oldest expense to the newest (updates `remaining` and
    `applied`). An expense without a rate to convert the reimbursement is skipped: it goes on
    with the next ones. Returns what is left (in the reimbursement's currency), whether anything
    counted and whether an expense with something pending was skipped for lack of a rate."""
    left, counted, blocked = refund.amount, False, False
    for index, move in enumerate(ordered):
        if left <= 0:
            break
        if remaining[index] <= 0:
            continue
        value = convert(left, refund.currency, move.currency, refund.day, rates)
        if value is None:
            blocked = True
            continue
        used = min(value, remaining[index])
        applied[index] += used
        remaining[index] -= used
        counted = counted or used > 0
        if used == value:
            return _ZERO, counted, blocked
        back = convert(used, move.currency, refund.currency, refund.day, rates) or _ZERO
        left = max(_ZERO, left - back)
    return left, counted, blocked


def states(
    movements: Sequence[Movement], links: Links, rates: Mapping[str, Rate] = _NO_RATES
) -> dict[int, SharedState]:
    """The accounting of each group with some present expense (still an expense), by id."""
    by_fp = {m.fingerprint: m for m in movements}
    found: dict[int, SharedState] = {}
    for link in links.shared:
        present = [
            move
            for e in link.expenses
            if (move := by_fp.get(e.fingerprint)) is not None and move.link == "shared"
        ]
        if present:
            found[link.id] = group_state(link, present, by_fp, rates)
    return found


def by_expense(groups: Mapping[int, SharedState]) -> dict[str, ExpenseState]:
    """The state of each present shared expense, by its fingerprint."""
    return {e.fingerprint: e for g in groups.values() for e in g.expenses}


def is_shareable(move: Movement) -> bool:
    return move.kind == "expense" and gross(move) > 0


def is_eligible_credit(move: Movement, links: Links) -> bool:
    """A credit that can be a reimbursement: not salary, a payment, an own transfer, interest or
    another link."""
    return (
        move.amount < 0
        and move.ref not in NOT_REIMBURSEMENT
        and not move.link
        and not links.is_linked(move.fingerprint)
        and not _INTEREST.search(move.description.upper())
    )


# --- Pickers and suggestions ---------------------------------------------------------------


def _in_currency(
    values: Iterable[tuple[Decimal, str]], currency: str, day: date, rates: Mapping[str, Rate]
) -> Decimal | None:
    """The sum of these amounts converted to `currency` at `day`'s month rate (None without one)."""
    total = _ZERO
    for amount, source in values:
        value = convert(amount, source, currency, day, rates)
        if value is None:
            return None
        total += value
    return total


def _fits(state: SharedState, credit: Movement, rates: Mapping[str, Rate]) -> bool:
    """The credit can reimburse the group: in range, with a rate and not over what was spent."""
    if credit.day < state.first.day:
        return False
    if (credit.day - state.last_day).days > PICK_WINDOW_DAYS:
        return False
    value = -credit.amount
    spent = _in_currency(
        ((e.amount, e.currency) for e in state.expenses), credit.currency, credit.day, rates
    )
    if spent is None:
        return False
    # One equal to the only expense, in its currency, is usually its refund, not a reimbursement.
    only = state.expenses[0] if len(state.expenses) == 1 else None
    if only is not None and only.currency == credit.currency:
        return value < spent
    return value <= spent


def _pending_in(state: SharedState, currency: str, day: date, rates: Mapping[str, Rate]) -> Decimal:
    found = _in_currency(((v, c) for c, v in state.pending.items()), currency, day, rates)
    return found or _ZERO


def _fits_pending(value: Decimal, pending: Decimal) -> bool:
    return pending > 0 and value <= pending * (1 + PENDING_MARGIN)


def candidates(
    state: SharedState,
    movements: Iterable[Movement],
    links: Links,
    rates: Mapping[str, Rate] = _NO_RATES,
) -> list[Movement]:
    """Credits that can reimburse the group, from the closest to the oldest expense to the
    farthest."""
    found = [m for m in movements if is_eligible_credit(m, links) and _fits(state, m, rates)]
    return sorted(found, key=lambda m: ((m.day - state.first.day).days, m.amount))


def pick_credits(
    state: SharedState,
    movements: Iterable[Movement],
    links: Links,
    rates: Mapping[str, Rate] = _NO_RATES,
) -> list[Candidate]:
    """A group's reimbursement picker: the `candidates` that fit in the pending amount (with
    PENDING_MARGIN) first and primary, by date; then the rest, by date."""
    marked = [
        Candidate(m, _fits_pending(-m.amount, _pending_in(state, m.currency, m.day, rates)))
        for m in candidates(state, movements, links, rates)
    ]
    return sorted(marked, key=lambda c: not c.primary)  # stable: keeps the date order


@dataclass(frozen=True)
class GroupCandidate:
    state: SharedState
    primary: bool


def groups_for(
    credit: Movement, groups: Mapping[int, SharedState], rates: Mapping[str, Rate] = _NO_RATES
) -> list[SharedState]:
    """Groups with something pending this credit could reimburse, the one whose expense is
    closest before the credit first."""
    options = [g for g in groups.values() if g.has_pending and _fits(g, credit, rates)]
    return sorted(options, key=lambda g: (_distance(g, credit), g.id))


def _distance(state: SharedState, credit: Movement) -> int:
    return min((credit.day - e.day).days for e in state.expenses if e.day <= credit.day)


def pick_groups(
    credit: Movement, groups: Mapping[int, SharedState], rates: Mapping[str, Rate] = _NO_RATES
) -> list[GroupCandidate]:
    """The picker from a credit: the groups with something pending it can reimburse; first (and
    primary) those whose pending amount covers it."""
    marked = [
        GroupCandidate(
            g, _fits_pending(-credit.amount, _pending_in(g, credit.currency, credit.day, rates))
        )
        for g in groups_for(credit, groups, rates)
    ]
    return sorted(marked, key=lambda c: not c.primary)


def pick_expenses(
    state: SharedState,
    movements: Iterable[Movement],
    links: Links,
    rates: Mapping[str, Rate] = _NO_RATES,
) -> list[Candidate]:
    """The "Add another expense" picker: unlinked expenses within +/-PICK_WINDOW_DAYS days of
    the group's.

    Left out: withdrawals, loans, card payments, own transfers and exchanges
    (NOT_SHARED_EXPENSE). Primary: if the group has an excess (you were paid back too much: an
    expense is missing), those within +/-PENDING_MARGIN of it (converted to its currency at
    their month's rate), from the closest to the excess to the farthest; then those with the
    same merchant as one in the group, or whose note or description shares a word with "With
    whom", by date proximity. After that, the rest.
    """
    merchants = {e.move.merchant for e in state.expenses if e.move.merchant}
    names = name_words(state.link.with_whom)
    found: list[tuple[tuple[int, Decimal, int, str], Candidate]] = []
    for move in movements:
        if move.link or links.is_linked(move.fingerprint) or not is_shareable(move):
            continue
        if move.ref in NOT_SHARED_EXPENSE:
            continue
        distance = min(abs((move.day - e.day).days) for e in state.expenses)
        if distance > PICK_WINDOW_DAYS:
            continue
        gap = _excess_gap(state, move, rates)
        words = set(_words(f"{move.note} {move.description}"))
        related = move.merchant in merchants or bool(names & words)
        rank = 0 if gap is not None else 1 if related else 2
        key = (rank, gap if gap is not None else _ZERO, distance, move.fingerprint)
        found.append((key, Candidate(move, rank < 2)))
    found.sort(key=lambda pair: pair[0])
    return [candidate for _, candidate in found]


def _excess_gap(state: SharedState, move: Movement, rates: Mapping[str, Rate]) -> Decimal | None:
    """How far the expense is from the group's excess, if within +/-PENDING_MARGIN of it."""
    gaps = []
    for currency, excess in state.excess_by:
        value = convert(gross(move), move.currency, currency, move.day, rates)
        if value is not None and abs(value - excess) <= excess * PENDING_MARGIN:
            gaps.append(abs(value - excess))
    return min(gaps) if gaps else None


def open_groups(groups: Mapping[int, SharedState]) -> list[SharedState]:
    """Groups with something pending (for "Add it to a group"), most recent first."""
    found = [g for g in groups.values() if g.has_pending]
    return sorted(found, key=lambda g: (g.last_day, g.id), reverse=True)


def fold(text: str) -> str:
    """Without accents and in lowercase."""
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).casefold()


def _words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def name_words(with_whom: str) -> frozenset[str]:
    """The words of "With whom" useful for suggesting: NAME_MIN_LETTERS letters or more."""
    return frozenset(w for w in _words(with_whom) if len(w) >= NAME_MIN_LETTERS and not w.isdigit())


def suggestions(
    movements: Sequence[Movement],
    links: Links,
    groups: Mapping[int, SharedState],
    rates: Mapping[str, Rate] = _NO_RATES,
) -> dict[str, int]:
    """Credit -> the group it seems to reimburse: by amount (same currency, shortly after an
    expense, fits in the pending amount) or, failing that, by name ("With whom" in the
    description)."""
    open_ = [g for g in groups.values() if g.has_pending]
    if not open_:
        return {}
    found: dict[str, int] = {}
    for credit in movements:
        if not is_eligible_credit(credit, links):
            continue
        chosen = _by_amount(credit, open_) or _by_name(credit, open_, rates)
        if chosen is not None:
            found[credit.fingerprint] = chosen.id
    return found


def _by_amount(credit: Movement, groups: Sequence[SharedState]) -> SharedState | None:
    options = []
    for group in groups:
        near = [
            (credit.day - e.day).days
            for e in group.expenses
            if e.currency == credit.currency
            and 0 <= (credit.day - e.day).days <= SUGGEST_WINDOW_DAYS
        ]
        if near and -credit.amount <= group.pending.get(credit.currency, _ZERO):
            options.append((min(near), group.id, group))
    return min(options, key=lambda o: (o[0], o[1]))[2] if options else None


def _by_name(
    credit: Movement, groups: Sequence[SharedState], rates: Mapping[str, Rate]
) -> SharedState | None:
    words = set(_words(credit.description))
    options = []
    for group in groups:
        oldest = group.oldest_pending
        if oldest is None or not name_words(group.link.with_whom) & words:
            continue
        if not 0 <= (credit.day - oldest.day).days <= PICK_WINDOW_DAYS:
            continue
        currencies = {e.currency for e in group.expenses}
        if any(converted(credit, c, rates) is None for c in currencies):
            continue
        # As in the picker: it must fit in the pending amount (with PENDING_MARGIN).
        pending = _pending_in(group, credit.currency, credit.day, rates)
        if not _fits_pending(-credit.amount, pending):
            continue
        options.append((oldest.day, oldest.fingerprint, group))
    return min(options, key=lambda o: (o[0], o[1]))[2] if options else None
