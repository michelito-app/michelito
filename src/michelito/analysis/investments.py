"""Investment accounting: what was contributed, what came back, the yield, and suggestions.

An investment (`links.Investment`) gathers contributions (debits), returns, capital repayments
and mixed credits (part capital, the rest return). No agreed terms are stored (rate or
frequency): everything comes from what happened.

- **Currency**: that of the first present contribution (by date). A movement in another currency
  is shown in its own and adds up converted at its month's rate (or the nearest previous
  month's, `rates.rate_for`); without any, it does not add up and goes apart (`unconverted`),
  without inventing one.
- **Contributed** A = sum of contributions. **Capital returned** K = sum of repayments + sum of
  the capital parts of mixed credits, each capped at the capital invested that day
  (`effective_capitals`: in date order, a day's contributions before its credits): anything
  returned in excess is a gain and counts as **return** (also in the Summary and reports, see
  `spending.with_links`). **Capital outstanding** = A - K (never negative). **Returns** R = sum
  of returns + sum of (credit - capital) of mixed credits + the excess returned (`excess`).
  **Last credit**: the most recent credit.
- **Status**: "closed" as soon as the outstanding capital reaches 0, by itself; otherwise
  "written_off" if it was marked as written off; otherwise "active".
- **Approximate annual %** (`annual_rate`): R / average invested capital x 365 / days. The
  capital invested on each day is C(t) = contributed up to t - capital returned (capped) up to
  t, which never drops below 0 at any step (each movement counts from its day). From the first
  contribution (d0) to the end (E: today if active; otherwise the day of the last movement), the
  capital-days are the sum of C(t) over each day of [d0, E). Average capital = capital-days /
  days, so annual % = R x 365 / capital-days (a fraction: 0.12 = 12 %). Without capital-days
  (everything on one day) there is no % (None); without returns it is 0.

Suggestions (`suggestions`; nothing is ever linked automatically, confirming is one tap):
- **The name** in "With whom" matches if the description carries all its significant words
  (`shared.name_words`: 4 letters or more) or, if it has more than two, at least two: with
  "Juan Perez", neither "JUAN GARCIA" nor "PAGO JUAN SUPERMERCADO" matches.
- **Another contribution?** (`possible_contribution`): an unlinked debit of at least
  LARGE_CONTRIBUTION_DOP in RD$ (= `review.LARGE_THIRD_PARTY_DOP`; with a rate, otherwise not)
  going to the same destination as a contribution of an investment not written off: the same
  exact merchant (at a bank, the destination account: "MB A 0000000066") or the name. So small
  transfers to the same person (not part of the investment) are not proposed.
- **A return?** (`possible_return`): an unlinked credit, since the first contribution, of an
  active investment, whose description carries the name, the exact merchant of an already
  linked credit or, as a whole word, a contribution's destination account (the digits after
  "A" in "MB A 0000..."; no other references); and worth at least
  max(RETURN_MIN_DOP, RETURN_MIN_SHARE x contributed) in RD$: the same person also sends small
  amounts that are not part of the investment.
If a movement fits several, the one with the most recent activity wins.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from michelito.analysis import categories, shared
from michelito.analysis.links import Investment, InvestmentMember, InvestmentRole, Links
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.i18n import t

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

# "Another contribution?" from this amount in RD$: the same as `review.LARGE_THIRD_PARTY_DOP`
# (not imported: `spending` uses this module and `review` uses `spending`; a test compares them).
LARGE_CONTRIBUTION_DOP = Decimal(25_000)
RETURN_MIN_DOP = Decimal(1_000)
RETURN_MIN_SHARE = Decimal("0.01")
DAYS_PER_YEAR = 365
_ZERO = Decimal(0)
# A transfer's destination account: "MB a 0000000066 ...", "TOKE A 0000..." (not a reference).
_DESTINATION = re.compile(r"\bA\s+(\d{6,})\b", re.IGNORECASE)
_NAME_MATCHES = 2  # with more words in "With whom", this many are enough
# What is never an investment contribution or return.
NOT_INVESTMENT = frozenset(
    {
        categories.CARD_PAYMENT,
        categories.OWN_TRANSFER,
        categories.CURRENCY_EXCHANGE,
        categories.REIMBURSEMENT,
        categories.SALARY,
    }
)

Status = Literal["active", "closed", "written_off"]
SuggestionKind = Literal["possible_contribution", "possible_return"]


@dataclass(frozen=True)
class Entry:
    """A present movement of the investment, in its currency and in the investment's."""

    move: Movement
    role: InvestmentRole
    amount: Decimal  # the statement's, positive, in the movement's currency
    capital: Decimal  # capital part that counts (contribution: 0), in the movement's currency
    value: Decimal | None  # `amount` in the investment's currency; None: no rate
    capital_value: Decimal | None
    return_value: Decimal | None  # the return, in the investment's currency
    excess: Decimal = _ZERO  # capital returned in excess (counts as return), in its currency
    excess_value: Decimal | None = None

    @property
    def fingerprint(self) -> str:
        return self.move.fingerprint

    @property
    def day(self) -> date:
        return self.move.day

    @property
    def currency(self) -> str:
        return self.move.currency

    @property
    def is_credit(self) -> bool:
        return self.role != "contribution"

    @property
    def counted(self) -> bool:
        return self.value is not None

    @property
    def returned(self) -> Decimal:
        """The return, in the movement's currency."""
        return _ZERO if self.role == "contribution" else self.amount - self.capital


@dataclass(frozen=True)
class InvestmentState:
    link: Investment
    currency: str
    entries: tuple[Entry, ...]  # by (date, fingerprint)

    @property
    def id(self) -> int:
        return self.link.id

    @property
    def counted(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.counted)

    @property
    def unconverted(self) -> tuple[Entry, ...]:
        """Movements in another currency without any rate: they do not add up."""
        return tuple(e for e in self.entries if not e.counted)

    @property
    def contributions(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.role == "contribution")

    @property
    def credits(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.is_credit)

    @property
    def first(self) -> Entry:
        """The first contribution (by date): sets the currency and opens the investment screen."""
        return self.contributions[0]

    @property
    def contributed(self) -> Decimal:
        return sum((e.value or _ZERO for e in self.contributions), _ZERO)

    @property
    def capital_returned(self) -> Decimal:
        return sum((e.capital_value or _ZERO for e in self.credits), _ZERO)

    @property
    def returns(self) -> Decimal:
        return sum((e.return_value or _ZERO for e in self.credits), _ZERO)

    @property
    def excess(self) -> Decimal:
        """What came back beyond what was contributed (already in `returns`)."""
        return sum((e.excess_value or _ZERO for e in self.credits), _ZERO)

    @property
    def pending(self) -> Decimal:
        """Outstanding capital (never negative)."""
        return max(self.contributed - self.capital_returned, _ZERO)

    @property
    def status(self) -> Status:
        if self.pending == 0:
            return "closed"
        return "written_off" if self.link.written_off else "active"

    @property
    def title(self) -> str:
        """Name, else "With whom", else the first contribution's merchant."""
        move = self.first.move
        return self.link.name or self.link.with_whom or move.merchant or move.description

    @property
    def last_activity(self) -> date:
        return max(e.day for e in self.entries)

    @property
    def last_credit(self) -> date | None:
        """Date of the last credit (return or capital)."""
        return max((e.day for e in self.credits), default=None)

    def end(self, today: date) -> date:
        """Until when the annual % is measured: today if active; otherwise its last movement."""
        last = self.last_activity
        return max(today, last) if self.status == "active" else last

    def annual_rate(self, today: date) -> Decimal | None:
        return annual_rate(self.counted, self.returns, self.end(today))


def annual_rate(entries: Iterable[Entry], returns: Decimal, end: date) -> Decimal | None:
    """R x 365 / capital-days (see the module docstring); None without capital-days."""
    days = capital_days(entries, end)
    if days <= 0:
        return None
    return returns * DAYS_PER_YEAR / days


def capital_days(entries: Iterable[Entry], end: date) -> Decimal:
    """Sum of each day's invested capital, from the first contribution up to `end` (excluded)."""
    changes: dict[date, Decimal] = {}
    for e in entries:
        delta = (e.value or _ZERO) if e.role == "contribution" else -(e.capital_value or _ZERO)
        if delta:
            changes[e.day] = changes.get(e.day, _ZERO) + delta
    total, capital, previous = _ZERO, _ZERO, None
    for day in sorted(d for d in changes if d < end):
        if previous is not None:
            total += capital * (day - previous).days
        capital = max(capital + changes[day], _ZERO)  # never negative, at any step
        previous = day
    if previous is not None:
        total += capital * (end - previous).days
    return total


def _nominal_capital(member: InvestmentMember, amount: Decimal) -> Decimal:
    if member.role == "capital":
        return amount
    if member.role == "mixed":
        return min(member.capital or amount, amount)
    return _ZERO


Present = Sequence[tuple["Movement", InvestmentMember]]


def _order(pair: tuple[Movement, InvestmentMember]) -> tuple[date, bool, str]:
    move, member = pair
    return (move.day, member.role != "contribution", move.fingerprint)


def investment_currency(present: Present) -> str | None:
    """That of the first present contribution (debit), by date; None without any."""
    debits = sorted(
        (move for move, m in present if m.role == "contribution" and shared.gross(move) > 0),
        key=lambda move: (move.day, move.fingerprint),
    )
    return debits[0].currency if debits else None


def effective_capitals(present: Present, rates: Mapping[str, Rate]) -> dict[str, Decimal]:
    """Credit -> the capital part that counts, in its currency: the nominal one (all of it in a
    repayment, the capital part in a mixed credit) capped at the capital invested up to that
    day. The rest is a gain (return). A credit without a rate keeps the nominal one."""
    currency = investment_currency(present)
    if currency is None:
        return {}
    running, found = _ZERO, {}
    for move, member in sorted(present, key=_order):
        gross = shared.gross(move)
        amount, day = abs(gross), move.day
        if member.role == "contribution":
            value = shared.convert(amount, move.currency, currency, day, rates)
            if gross > 0 and value is not None:
                running += value
            continue
        if gross >= 0:
            continue
        nominal = _nominal_capital(member, amount)
        value = shared.convert(nominal, move.currency, currency, day, rates)
        if nominal == 0 or value is None:
            found[move.fingerprint] = nominal
            continue
        applied = min(value, running)
        running -= applied
        if applied == value:
            found[move.fingerprint] = nominal
        elif applied <= 0:
            found[move.fingerprint] = _ZERO
        else:
            back = shared.convert(applied, currency, move.currency, day, rates)
            found[move.fingerprint] = min(back or _ZERO, nominal)
    return found


def _entry(
    move: Movement,
    member: InvestmentMember,
    currency: str,
    rates: Mapping[str, Rate],
    capitals: Mapping[str, Decimal],
) -> Entry:
    amount = abs(shared.gross(move))
    nominal = _nominal_capital(member, amount)
    capital = capitals.get(move.fingerprint, nominal)

    def value(of: Decimal) -> Decimal | None:
        return shared.convert(of, move.currency, currency, move.day, rates)

    whole = value(amount)
    return Entry(
        move=move,
        role=member.role,
        amount=amount,
        capital=capital,
        value=whole,
        capital_value=None if whole is None else value(capital),
        return_value=None if whole is None else value(amount - capital),
        excess=nominal - capital,
        excess_value=None if whole is None else value(nominal - capital),
    )


def state_of(
    link: Investment, by_fp: Mapping[str, Movement], rates: Mapping[str, Rate]
) -> InvestmentState | None:
    """The investment's accounting with its present movements (those still linked as an
    investment); None if no present contribution is left."""
    present = [
        (move, m)
        for m in link.members
        if (move := by_fp.get(m.fingerprint)) is not None and move.link == "investment"
    ]
    contributions = sorted(
        (move for move, m in present if m.role == "contribution"),
        key=lambda move: (move.day, move.fingerprint),
    )
    if not contributions:
        return None
    currency = contributions[0].currency
    capitals = effective_capitals(present, rates)
    entries = sorted(
        (_entry(move, m, currency, rates, capitals) for move, m in present),
        key=lambda e: (e.day, e.fingerprint),
    )
    return InvestmentState(link=link, currency=currency, entries=tuple(entries))


def states(
    movements: Sequence[Movement], links: Links, rates: Mapping[str, Rate]
) -> dict[int, InvestmentState]:
    """Accounting of each investment with some present contribution, by id."""
    by_fp = {m.fingerprint: m for m in movements}
    found = {}
    for link in links.investments:
        state = state_of(link, by_fp, rates)
        if state is not None:
            found[link.id] = state
    return found


def newest_first(found: Iterable[InvestmentState]) -> list[InvestmentState]:
    return sorted(found, key=lambda s: (s.last_activity, s.id), reverse=True)


# --- Candidates and suggestions -------------------------------------------------------------


def _free(move: Movement, links: Links) -> bool:
    return (
        not move.link and not links.is_linked(move.fingerprint) and move.ref not in NOT_INVESTMENT
    )


def is_contribution_candidate(move: Movement, links: Links) -> bool:
    """A debit that may be a contribution: unlinked and not a card payment, own transfer, etc."""
    return move.amount > 0 and _free(move, links)


def is_credit_candidate(move: Movement, links: Links) -> bool:
    """A credit that may belong to an investment (return, capital or mixed)."""
    return move.amount < 0 and _free(move, links)


@dataclass(frozen=True)
class Suggestion:
    kind: SuggestionKind
    state: InvestmentState

    @property
    def reason(self) -> str:
        if self.kind == "possible_contribution":
            return t("analysis.investments.reason.contribution", title=self.state.title)
        return t("analysis.investments.reason.return", title=self.state.title)


def _dop(move: Movement, rates: Mapping[str, Rate]) -> Decimal | None:
    value = to_dop(abs(shared.gross(move)), move.currency, rate_for(rates, move.month))
    return None if value is None else abs(value)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", shared.fold(text)))


def names_match(with_whom: str, text: str) -> bool:
    """The description carries the name: all significant words of "With whom" or, if it has
    more than two, at least two (see the module docstring)."""
    names = shared.name_words(with_whom)
    if not names:
        return False
    found = len(names & _words(text))
    return found == len(names) or found >= _NAME_MATCHES


def destinations(descriptions: Iterable[str]) -> frozenset[str]:
    """The destination accounts of these transfers ("MB a 0000000066 ..." -> "0000000066")."""
    return frozenset(n for text in descriptions for n in _DESTINATION.findall(text))


def _same_destination(move: Movement, state: InvestmentState) -> bool:
    merchants = {e.move.merchant for e in state.contributions if e.move.merchant}
    return move.merchant in merchants or names_match(state.link.with_whom, move.description)


def _from_origin(move: Movement, state: InvestmentState) -> bool:
    credit_merchants = {e.move.merchant for e in state.credits if e.move.merchant}
    accounts = destinations(e.move.description for e in state.contributions)
    text = move.description
    return (
        names_match(state.link.with_whom, text)
        or move.merchant in credit_merchants
        or any(re.search(rf"\b{n}\b", text) for n in accounts)
    )


def _contributed_dop(state: InvestmentState, rates: Mapping[str, Rate]) -> Decimal:
    return sum((_dop(e.move, rates) or _ZERO for e in state.contributions), _ZERO)


def suggestions(
    movements: Iterable[Movement],
    links: Links,
    found: Mapping[int, InvestmentState],
    rates: Mapping[str, Rate],
    banks: Collection[str] | None = None,
) -> dict[str, Suggestion]:
    """Fingerprint -> the investment it looks like (see the module docstring). Only proposes.
    `banks`: the bank accounts (only their movements are proposed; None: all)."""
    ranked = newest_first(found.values())
    open_ = [s for s in ranked if s.status != "written_off"]
    active = [s for s in ranked if s.status == "active"]
    result: dict[str, Suggestion] = {}
    for move in movements:
        if banks is not None and move.account not in banks:
            continue
        if is_contribution_candidate(move, links):
            value = _dop(move, rates)
            if value is None or value < LARGE_CONTRIBUTION_DOP:
                continue
            hit = next((s for s in open_ if _same_destination(move, s)), None)
            if hit is not None:
                result[move.fingerprint] = Suggestion("possible_contribution", hit)
        elif is_credit_candidate(move, links):
            value = _dop(move, rates)
            if value is None:
                continue
            hit = next(
                (
                    s
                    for s in active
                    if move.day >= s.first.day
                    and value >= max(RETURN_MIN_DOP, RETURN_MIN_SHARE * _contributed_dop(s, rates))
                    and _from_origin(move, s)
                ),
                None,
            )
            if hit is not None:
                result[move.fingerprint] = Suggestion("possible_return", hit)
    return result
