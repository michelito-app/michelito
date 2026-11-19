"""Cash box accounting: stored cash that is not spending (pure functions).

By default nothing changes: an ATM withdrawal is spending in the cash category on the day of the
withdrawal. Only what the user marks by hand goes into the box (there are no suggestions):

- **Stored withdrawal** (`links`, role `'stored'`): a debit in the cash category from a bank or a
  card (`can_store`). It moves to the cash box category (a transfer: neither spending nor
  subtracted from what you had left) and adds to the balance in its currency. Removing the mark
  turns it back into spending.
- **Bank deposit** (role `'deposit'`): a credit on a bank account whose category is an income
  one, other than salary, investment return or interest paid by the bank ("PAGO INTERESES": its
  category is other income, so it is recognized by the word INTERES/INTERESES in the
  description) (`can_deposit`). A card payment, a transfer between your accounts, an exchange, a
  refund or a reversal are transfers and stay out. It moves to the cash box category (not
  income) and lowers the balance. By default it leaves the box in the credit's currency and for
  the same amount. If it left in the other currency (dollars from the box deposited as DOP),
  `box_currency` says so and `box_amount` how much left; without an amount it is converted at
  the deposit month's rate (`rates.rate_for`, the board's rate) and, with no rate at all, it does
  not lower the balance and a warning is raised (`uncounted`), without making anything up.
- **By hand** (`cash_box_store`, table `cash_entries`): *initial balance* (cash already there: not
  income of any month and not shown in Transactions), *income* (cash received: income in its
  month, by default other income) and *expense* (spending in its category and month, by
  default cash). Income and expense entries are movements of the cash box account
  (`spending`): they can be searched and corrected, and take a note, "one-off" and sharing like
  any other. Their fingerprint is `cash-<id>`: it does not clash with statement fingerprints (24
  hex digits) and does not change with `parse --retry`, which only rebuilds `transactions` rows.

**Balance**: per currency, inflows (initial balance, income entries, stored withdrawals) minus
outflows (expense entries and deposits), each movement in its own currency. A negative balance
is allowed and warned about (`negative`: the box would end at -US$ 200; adjust the initial
balance?). **~ RD$**: each movement at its month's rate; US$ without any rate is kept apart
(`unconverted`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Literal, get_args

from michelito.analysis import categories
from michelito.analysis.accounts import CASH_BOX_KEY
from michelito.analysis.links import CashBox, CashBoxMember, Links
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.i18n import t

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

EntryKind = Literal["initial", "income", "expense"]
ENTRY_KINDS: tuple[EntryKind, ...] = get_args(EntryKind)
LineKind = Literal["initial", "income", "expense", "stored", "deposit"]
CURRENCIES = ("DOP", "USD")
FINGERPRINT_PREFIX = "cash-"
MERCHANT = "CAJA FUERTE"  # spanish-data: the merchant shown for entries made by hand
# The description each kind of hand-made entry shows in Transactions.
DESCRIPTIONS: Mapping[str, str] = {
    "initial": t("analysis.cash_box.description_initial"),
    "income": t("analysis.cash_box.description_income"),
    "expense": t("analysis.cash_box.description_expense"),
}
# Default category of hand-made entries (the user changes it like any other).
DEFAULT_CATEGORY: Mapping[str, str] = {
    "income": categories.OTHER_INCOME,
    "expense": categories.CASH,
}
# The category kind each hand-made entry accepts when it is entered.
ENTRY_CATEGORY_KIND: Mapping[str, categories.Kind] = {"income": "income", "expense": "expense"}
# Dates accepted for hand-made entries: not before this and not more than a month after today.
FIRST_DAY = date(2000, 1, 1)
DAYS_AHEAD = 31
_CENT = Decimal("0.01")
# Income that never comes from the box: salary and investment returns.
_NOT_DEPOSIT = frozenset({categories.SALARY, categories.INVESTMENT_RETURN, *categories.LINK_ONLY})
# Interest paid by the bank ("PAGO INTERESES", "CR INTERESES GANADOS").
_INTEREST = re.compile(r"\bINTERES(ES)?\b")
_ZERO = Decimal(0)


class CashBoxError(ValueError):
    """Invalid request on the cash box (422)."""


@dataclass(frozen=True)
class ManualEntry:
    """A movement entered by hand in the box (`cash_entries`). `amount` is always positive."""

    id: int
    kind: EntryKind
    day: date
    amount: Decimal
    currency: str
    account_key: str = CASH_BOX_KEY

    @property
    def fingerprint(self) -> str:
        return entry_fingerprint(self.id)


def entry_fingerprint(entry_id: int) -> str:
    return f"{FINGERPRINT_PREFIX}{entry_id}"


def entry_id(fingerprint: str) -> int | None:
    """The id of a hand-made entry from its fingerprint; None if it is not one."""
    digits = fingerprint.removeprefix(FINGERPRINT_PREFIX)
    if digits == fingerprint or not digits.isdigit() or digits.startswith("0"):
        return None
    return int(digits)


def is_manual(fingerprint: str) -> bool:
    return entry_id(fingerprint) is not None


def manual_kind(amount: Decimal) -> categories.Kind:
    """The category kind of a hand-made box entry (as when it is entered,
    `cash_box_store._category`): an inflow (negative amount) is income; an outflow, expense."""
    return ENTRY_CATEGORY_KIND["income" if amount < 0 else "expense"]


def manual_category_error(fingerprint: str, amount: Decimal, kind: str) -> str | None:
    """Why that category does not fit a hand-made box entry (None if it fits or if it is not
    one)."""
    if not is_manual(fingerprint):
        return None
    wanted = manual_kind(amount)
    if kind == wanted:
        return None
    if wanted == "income":
        return t("analysis.cash_box.inflow_needs_income")
    return t("analysis.cash_box.outflow_needs_expense")


@dataclass(frozen=True)
class Line:
    """A box inflow or outflow, signed in the box currency (+ in, - out)."""

    kind: LineKind
    day: date
    fingerprint: str
    currency: str  # in the box
    amount: Decimal | None  # None: a deposit in another currency without a rate (balance unchanged)
    dop: Decimal | None  # ~ RD$ at its month's rate; None without a rate
    # The movement as it appears (the bank credit or debit, or the entry), positive.
    source_amount: Decimal
    source_currency: str
    move: Movement | None = None  # in the flow (all but the initial balance)
    entry: ManualEntry | None = None  # the hand-made entry

    @property
    def counted(self) -> bool:
        return self.amount is not None


@dataclass(frozen=True)
class BoxState:
    account_key: str
    lines: tuple[Line, ...]  # most recent first
    balances: tuple[tuple[str, Decimal], ...]  # per currency, RD$ first
    total_dop: Decimal  # ~ RD$, each movement at its month's rate
    unconverted: tuple[tuple[str, Decimal], ...]  # what has no rate, per currency
    uncounted: tuple[str, ...] = ()  # other-currency deposits, no rate: balance unchanged

    def balance(self, currency: str) -> Decimal:
        return dict(self.balances).get(currency, _ZERO)

    @property
    def negative(self) -> tuple[tuple[str, Decimal], ...]:
        """The currencies in which the box went negative (warned about, never blocked)."""
        return tuple((c, amount) for c, amount in self.balances if amount < 0)


def after(state: BoxState, currency: str, delta: Decimal) -> Decimal | None:
    """The `currency` balance after moving `delta` (negative: out); None if it does not go
    negative."""
    left = state.balance(currency) + delta
    return left if left < 0 else None


def state_of(
    box: CashBox | None,
    entries: Iterable[ManualEntry],
    movements: Sequence[Movement],
    rates: Mapping[str, Rate],
    account_key: str = CASH_BOX_KEY,
) -> BoxState:
    """The box with its lines and balances. `movements`: the flow (`spending.load_all`), holding
    the withdrawals, the deposits and the hand-made entries; one that no longer appears (or is no
    longer a debit or a credit) does not count."""
    by_fp = {m.fingerprint: m for m in movements}
    lines = [
        _entry_line(entry, by_fp.get(entry.fingerprint), rates)
        for entry in entries
        if entry.account_key == account_key
    ]
    for member in () if box is None else box.members:
        move = by_fp.get(member.fingerprint)
        if move is None:
            continue
        line = _member_line(member, move, rates)
        if line is not None:
            lines.append(line)
    lines.sort(key=lambda line: (line.day, line.fingerprint), reverse=True)
    return BoxState(
        account_key=account_key,
        lines=tuple(lines),
        balances=_by_currency((line.currency, line.amount) for line in lines),
        total_dop=sum((line.dop for line in lines if line.dop is not None), _ZERO),
        unconverted=_by_currency(
            (line.currency, line.amount) for line in lines if line.dop is None
        ),
        uncounted=tuple(line.fingerprint for line in lines if not line.counted),
    )


def _by_currency(
    pairs: Iterable[tuple[str, Decimal | None]],
) -> tuple[tuple[str, Decimal], ...]:
    totals: dict[str, Decimal] = {}
    for currency, amount in pairs:
        if amount is not None:
            totals[currency] = totals.get(currency, _ZERO) + amount
    return tuple(sorted(totals.items(), key=lambda item: (item[0] != "DOP", item[0])))


def _entry_line(entry: ManualEntry, move: Movement | None, rates: Mapping[str, Rate]) -> Line:
    signed = -entry.amount if entry.kind == "expense" else entry.amount
    return Line(
        kind=entry.kind,
        day=entry.day,
        fingerprint=entry.fingerprint,
        currency=entry.currency,
        amount=signed,
        dop=_dop(signed, entry.currency, entry.day, rates),
        source_amount=entry.amount,
        source_currency=entry.currency,
        move=move,
        entry=entry,
    )


def _member_line(member: CashBoxMember, move: Movement, rates: Mapping[str, Rate]) -> Line | None:
    gross = move.gross if move.gross is not None else move.amount
    if member.role == "stored":
        if gross <= 0:
            return None
        amount: Decimal | None = gross
        currency = move.currency
    else:
        if gross >= 0:
            return None
        currency = member.box_currency or move.currency
        taken = deposit_amount(member, -gross, move.currency, move.month, rates)
        amount = None if taken is None else -taken
    return Line(
        kind=member.role,
        day=move.day,
        fingerprint=move.fingerprint,
        currency=currency,
        amount=amount,
        dop=None if amount is None else _dop(amount, currency, move.day, rates),
        source_amount=abs(gross),
        source_currency=move.currency,
        move=move,
    )


def deposit_amount(
    member: CashBoxMember,
    credit: Decimal,
    currency: str,
    month: str,
    rates: Mapping[str, Rate],
) -> Decimal | None:
    """What left the box for a deposit of `credit` (positive, in `currency`): the same if it left
    in that currency; otherwise the amount given by hand or the credit at the month's rate; None
    without a rate."""
    target = member.box_currency or currency
    if target == currency:
        return credit
    if member.box_amount is not None:
        return member.box_amount
    rate = rate_for(rates, month)
    if rate is None or rate.value <= 0:
        return None
    converted = credit * rate.value if currency == "USD" else credit / rate.value
    return converted.quantize(_CENT, rounding=ROUND_HALF_UP)


def _dop(amount: Decimal, currency: str, day: date, rates: Mapping[str, Rate]) -> Decimal | None:
    return to_dop(amount, currency, rate_for(rates, day.strftime("%Y-%m")))


# --- What can be marked ---------------------------------------------------------------------------


def can_store(move: Movement, links: Links) -> bool:
    """A cash-category debit (an ATM withdrawal or a cash advance) from a bank or a card, with no
    other link. Hand-made box entries are not: they are already in it."""
    return (
        move.amount > 0
        and move.ref == categories.CASH
        and move.account != CASH_BOX_KEY
        and not is_manual(move.fingerprint)
        and not links.is_linked(move.fingerprint)
    )


def can_deposit(move: Movement, links: Links, banks: Iterable[str]) -> bool:
    """A credit on a bank account, with no other link, whose category is an income one other than
    salary or investment return, and that is not bank interest (see the module docstring)."""
    return (
        move.amount < 0
        and move.account in set(banks)
        and move.kind == "income"
        and move.ref not in _NOT_DEPOSIT
        and _INTEREST.search(move.description.upper()) is None
        and not links.is_linked(move.fingerprint)
    )


def stored_dop(movements: Iterable[Movement], rates: Mapping[str, Rate], month: str) -> Decimal:
    """The month's stored withdrawals in RD$ (US$ without a rate does not count): "of that, RD$ X
    went to the cash box". A deposit (credit) does not subtract from that line."""
    total = _ZERO
    for move in movements:
        if move.link != "cash_box" or move.amount <= 0 or move.month != month:
            continue
        total += to_dop(move.amount, move.currency, rate_for(rates, month)) or _ZERO
    return total


def last_day(today: date) -> date:
    return today + timedelta(days=DAYS_AHEAD)


def check_day(day: date, today: date) -> None:
    """The date of a hand-made entry: from FIRST_DAY to today + DAYS_AHEAD days."""
    if not FIRST_DAY <= day <= last_day(today):
        raise CashBoxError(
            t(
                "analysis.cash_box.date_range",
                first=FIRST_DAY.isoformat(),
                last=last_day(today).isoformat(),
            )
        )


def check_entry(kind: str, amount: Decimal, currency: str) -> None:
    if kind not in ENTRY_KINDS:
        raise CashBoxError(t("analysis.cash_box.unknown_kind", kind=kind))
    if not amount.is_finite() or amount <= 0:
        raise CashBoxError(t("analysis.cash_box.amount_positive"))
    if amount != amount.quantize(_CENT):
        raise CashBoxError(t("analysis.cash_box.amount_decimals"))
    if currency not in CURRENCIES:
        raise CashBoxError(t("analysis.cash_box.currency"))
