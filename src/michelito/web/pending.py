"""Pending: who owes you and whom you owe, across all months.

- **Owed to you**: the shared groups with something pending, one row per group
  (`shared.states`: they already apply the reimbursements, converted, from the oldest expense to
  the newest) and the currency exchanges with something pending whose base side left your
  accounts (you gave first: the oldest leg is a debit).
- **You owe**: the exchanges with something pending whose base side came in (they gave first
  and the other currency is still to be returned).
- Left out: what was marked "They won't pay me back" and complete exchanges or ones with nothing
  pending (the states already leave them at 0).

In RD$: an exchange is valued at its own rate (the agreed or the implied one,
`ExchangeState.pending_dop`: it is the price at which the debt was agreed, so it never lacks a
rate); what a group has pending in US$, at the most recent saved rate (the one for the month of
`today` or the closest earlier month) and, with none, apart, without making one up. With chosen
accounts, a group counts if any of its expenses is from them (its row opens the group's first
expense and shows the account of the first one from those accounts); an exchange, if any of its
legs is, and its row is the first of those legs (the one that opens its screen and gives the
account). A group's date and age are those of its oldest pending expense; an exchange's, those
of its first leg. Each list goes from oldest to newest.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from michelito.analysis.exchanges import ExchangeState
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.shared import SharedState
from michelito.analysis.spending import Movement

WHO_CHARS = 40  # a longer note is trimmed for the row
_ZERO = Decimal(0)
_USD = "USD"

Kind = Literal["shared", "exchange"]


@dataclass(frozen=True)
class PendingItem:
    kind: Kind
    fingerprint: str  # the group's first expense, or the exchange's first leg
    day: date
    merchant: str  # the group title (name, "With whom" or merchant) or the exchange's
    account_label: str
    who: str  # the group's "With whom" or else the note (trimmed); may be empty
    pending: Decimal  # in `currency`
    currency: str
    pending_dop: Decimal | None  # None: in US$ with no rate at all
    age_days: int
    rate: Decimal | None = None  # RD$ per US$ used for `pending_dop` (None: not needed)
    # A group: how many expenses it has, its id and what is pending by currency (RD$ before US$).
    expense_count: int = 1
    link_id: int | None = None
    parts: tuple[tuple[str, Decimal], ...] = ()
    unconverted_usd: Decimal = Decimal(0)  # pending US$ with no rate at all


@dataclass(frozen=True)
class Pending:
    owed_to_me: tuple[PendingItem, ...]
    i_owe: tuple[PendingItem, ...]
    rate: Rate | None  # the most recent: the one for shared expenses in US$

    @property
    def owed_to_me_dop(self) -> Decimal:
        return _dop_total(self.owed_to_me)

    @property
    def i_owe_dop(self) -> Decimal:
        return _dop_total(self.i_owe)

    @property
    def net_dop(self) -> Decimal:
        return self.owed_to_me_dop - self.i_owe_dop

    @property
    def unconverted_owed_to_me(self) -> Decimal:
        return _unconverted(self.owed_to_me)

    @property
    def unconverted_i_owe(self) -> Decimal:
        return _unconverted(self.i_owe)


def build_pending(
    movements: Sequence[Movement],
    groups: Mapping[int, SharedState],
    exchange_states: Mapping[int, ExchangeState],
    labels: Mapping[str, str],
    rates: Mapping[str, Rate],
    today: date,
    chosen: Collection[str] | None = None,
) -> Pending:
    """Both lists and the rate used. `chosen`: account keys (None: all)."""
    rate = rate_for(rates, today.strftime("%Y-%m"))
    owed: list[PendingItem] = []
    owing: list[PendingItem] = []
    for state in groups.values():
        moves = [e.move for e in state.expenses]
        if not state.has_pending or not _picked(moves, chosen):
            continue
        first = next(m for m in moves if chosen is None or m.account in chosen)
        owed.append(_shared_item(state, first, labels, rate, today))
    for exchange in exchange_states.values():
        shown = _shown_leg(exchange, chosen)
        if exchange.pending <= 0 or shown is None:
            continue
        item = _exchange_item(exchange, shown, labels, today)
        # The base side left your accounts (you gave first): you are owed; if it came in, you owe.
        base = next(leg for leg in exchange.legs if leg.currency == exchange.base)
        (owed if base.amount > 0 else owing).append(item)
    return Pending(_oldest_first(owed), _oldest_first(owing), rate)


def _shared_item(
    state: SharedState, shown: Movement, labels: Mapping[str, str], rate: Rate | None, today: date
) -> PendingItem:
    parts = tuple(sorted(state.pending.items()))
    oldest = state.oldest_pending or state.first
    converted = [(to_dop(value, currency, rate), value, currency) for currency, value in parts]
    dop_parts = [dop for dop, _, _ in converted if dop is not None]
    unconverted = sum((v for dop, v, c in converted if dop is None and c == _USD), _ZERO)
    main_currency, main_value = parts[0]
    return PendingItem(
        kind="shared",
        fingerprint=state.first.fingerprint,
        day=oldest.day,
        merchant=state.title,
        account_label=labels.get(shown.account, shown.account),
        who=_trim(state.link.with_whom or state.first.move.note),
        pending=main_value,
        currency=main_currency,
        pending_dop=sum(dop_parts, _ZERO) if dop_parts else None,
        age_days=(today - oldest.day).days,
        rate=rate.value if rate is not None and any(c == _USD for c, _ in parts) else None,
        expense_count=len(state.expenses),
        link_id=state.id,
        parts=parts,
        unconverted_usd=unconverted if dop_parts else _ZERO,
    )


def _exchange_item(
    exchange: ExchangeState, shown: Movement, labels: Mapping[str, str], today: date
) -> PendingItem:
    return PendingItem(
        kind="exchange",
        fingerprint=shown.fingerprint,
        day=exchange.first_day,
        merchant=_name(shown),
        account_label=labels.get(shown.account, shown.account),
        who=_trim(next((leg.note for leg in exchange.legs if leg.note), "")),
        pending=exchange.pending,
        currency=exchange.pending_currency,
        pending_dop=exchange.pending_dop,
        age_days=(today - exchange.first_day).days,
        rate=exchange.rate,
    )


def _shown_leg(exchange: ExchangeState, chosen: Collection[str] | None) -> Movement | None:
    """The leg that stands for the exchange: the first one from the chosen accounts (None: none)."""
    return next((leg for leg in exchange.legs if chosen is None or leg.account in chosen), None)


def _name(move: Movement) -> str:
    return move.merchant or move.description


def _picked(moves: Iterable[Movement], chosen: Collection[str] | None) -> bool:
    return chosen is None or any(m.account in chosen for m in moves)


def _trim(text: str) -> str:
    clean = " ".join(text.split())
    if len(clean) <= WHO_CHARS:
        return clean
    return clean[: WHO_CHARS - 1].rstrip() + "…"


def _oldest_first(items: Iterable[PendingItem]) -> tuple[PendingItem, ...]:
    return tuple(sorted(items, key=lambda i: (i.day, i.fingerprint)))


def _dop_total(items: Iterable[PendingItem]) -> Decimal:
    return sum((i.pending_dop for i in items if i.pending_dop is not None), _ZERO)


def _unconverted(items: Iterable[PendingItem]) -> Decimal:
    whole = sum((i.pending for i in items if i.pending_dop is None and i.currency == _USD), _ZERO)
    return whole + sum((i.unconverted_usd for i in items), _ZERO)
