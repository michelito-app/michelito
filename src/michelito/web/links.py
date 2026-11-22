"""Links for the web: what each Transactions row shows about shared groups (the ledger),
currency exchanges and investments, and the checks on the requests that change them."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from functools import cached_property

from michelito.analysis import cash_box, exchanges, investments, ledger, ledger_suggest, shared
from michelito.analysis.accounts import BANK_KINDS, AccountInfo, account_label
from michelito.analysis.exchanges import ExchangeState
from michelito.analysis.investments import InvestmentState, Suggestion
from michelito.analysis.links import AlreadyLinked, LinkError, Links
from michelito.analysis.rates import Rate, rate_for
from michelito.analysis.spending import Movement
from michelito.i18n import t


@dataclass(frozen=True)
class LinkedTx:
    """Another transaction mentioned in the detail (a reimbursement, a leg, a suggestion)."""

    fingerprint: str
    day: date
    merchant: str
    account_label: str
    amount: Decimal  # as on the statement (a credit is negative)
    currency: str
    # A credit in a currency other than the expense's: its value in the expense currency (at the
    # month's rate).
    converted: Decimal | None = None
    converted_currency: str | None = None
    description: str = ""  # as on the statement (the pickers' search looks at it)


@dataclass(frozen=True)
class LedgerRow:
    """The row's place in the shared ledger: an entry it comes from, a payment it reconciles or
    (a group movement) the user's share of an expense someone else paid."""

    group_id: int
    group_name: str
    role: str  # "entry", "payment" or "group"
    entry: ledger.EntryState | None = None
    payment: ledger.Payment | None = None
    paid_by: str = ""  # who paid the entry (empty: the user)


@dataclass(frozen=True)
class RowLinks:
    # The row's stored link, even when dormant (its expense no longer appears or stopped being an
    # expense; the exchange is missing a leg): "shared" (a group entry), "reimbursement" (a group
    # payment), "group" (a group movement), "exchange", "investment" or "".
    kind: str = ""
    link_id: int | None = None
    # What can be done with the row (the same rules the server checks).
    can_share: bool = False
    can_reimburse: bool = False
    can_pay: bool = False  # a bank debit that can be a payment the user made in a group
    can_exchange: bool = False
    ledger: LedgerRow | None = None
    exchange: ExchangeState | None = None
    exchange_legs: tuple[LinkedTx, ...] = ()  # every leg of the exchange
    suggested_exchange_with: LinkedTx | None = None
    can_invest: bool = False  # a debit that can be a contribution ("It is an investment…")
    can_invest_credit: bool = False  # a credit that can come from one ("It is from an investment…")
    investment: InvestmentState | None = None  # the row's investment (active)
    investment_role: str = ""  # its role in it ("contribution", "return", "capital", "mixed")
    investment_capital: Decimal | None = None  # in a mixed credit, the capital part
    suggested_investment: Suggestion | None = None  # "Another contribution to…?" / "Return from…?"
    can_store: bool = False  # a withdrawal that can be marked "I put it in the cash box"
    can_deposit: bool = False  # a bank credit that can be "It came from the cash box"
    cash_box_role: str = ""  # "stored" (withdrawal kept), "deposit" (deposit from the box) or ""
    # On a deposit: the currency it left the box in and how much (None: no rate, not counted).
    cash_box_currency: str | None = None
    cash_box_amount: Decimal | None = None


@dataclass(frozen=True)
class Context:
    """Everything about links, computed once per request."""

    links: Links
    movements: tuple[Movement, ...]
    labels: Mapping[str, str]
    banks: frozenset[str]
    book: ledger.Ledger = ledger.EMPTY
    groups: Mapping[int, ledger.GroupState] = field(default_factory=dict)
    exchange_states: Mapping[int, ExchangeState] = field(default_factory=dict)
    exchange_suggestions: Mapping[str, str] = field(default_factory=dict)
    rates: Mapping[str, Rate] = field(default_factory=dict)
    investment_states: Mapping[int, InvestmentState] = field(default_factory=dict)
    investment_suggestions: Mapping[str, Suggestion] = field(default_factory=dict)

    def movement(self, fingerprint: str) -> Movement | None:
        return self._by_fp.get(fingerprint)

    def linked(self, fingerprint: str) -> LinkedTx | None:
        move = self._by_fp.get(fingerprint)
        return None if move is None else linked_tx(move, self.labels)

    def credit_for(self, credit: Movement, currency: str) -> LinkedTx:
        """A credit mentioned next to an expense in `currency`: in the other currency, with its
        equivalent (or without it when the rate is missing)."""
        found = linked_tx(credit, self.labels)
        if credit.currency == currency:
            return found
        value = shared.converted(credit, currency, self.rates)
        return replace(found, converted=value, converted_currency=currency)

    @cached_property
    def _by_fp(self) -> dict[str, Movement]:
        return {m.fingerprint: m for m in self.movements}


def linked_tx(move: Movement, labels: Mapping[str, str]) -> LinkedTx:
    return LinkedTx(
        fingerprint=move.fingerprint,
        day=move.day,
        merchant=move.merchant,
        account_label=account_label(labels, move.account),
        amount=shared.gross(move),
        currency=move.currency,
        description=move.description,
    )


def context(
    movements: Sequence[Movement],
    found: Links,
    accounts: Sequence[AccountInfo],
    rates: Mapping[str, Rate],
    suggest: bool = True,
    reviewed: Collection[tuple[str, str]] = (),
    book: ledger.Ledger = ledger.EMPTY,
) -> Context:
    """`suggest=False` skips the suggestions (the Summary does not need them). `reviewed`: what
    was marked in "To review" (fingerprint, kind): an investment proposal already reviewed ("It
    is not") is not suggested on the row again."""
    banks = frozenset(a.key for a in accounts if a.kind in BANK_KINDS)
    labels = {a.key: a.label for a in accounts}
    moves = tuple(movements)
    groups = ledger.states(book, rates)
    invested = investments.states(moves, found, rates)
    if not suggest:
        return Context(
            found,
            moves,
            labels,
            banks,
            book,
            groups,
            exchanges.states(moves, found),
            rates=rates,
            investment_states=invested,
        )
    return Context(
        links=found,
        movements=moves,
        labels=labels,
        banks=banks,
        book=book,
        groups=groups,
        exchange_states=exchanges.states(moves, found),
        exchange_suggestions=exchanges.suggestions(
            moves, found, banks, lambda month: rate_for(rates, month)
        ),
        rates=rates,
        investment_states=invested,
        investment_suggestions={
            fp: hint
            for fp, hint in investments.suggestions(moves, found, invested, rates, banks).items()
            if (fp, hint.kind) not in reviewed
        },
    )


def row_links(ctx: Context, fingerprints: Collection[str]) -> dict[str, RowLinks]:
    """What each of these rows shows (and what can be done with them)."""
    by_fp = {m.fingerprint: m for m in ctx.movements}
    exchange_of = {
        leg.fingerprint: state for state in ctx.exchange_states.values() for leg in state.legs
    }
    found: dict[str, RowLinks] = {}
    for fp in fingerprints:
        move = by_fp.get(fp)
        if move is None:
            continue
        found[fp] = _row(ctx, move, exchange_of.get(fp))
    return found


def _row(ctx: Context, move: Movement, exchange: ExchangeState | None) -> RowLinks:
    fp = move.fingerprint
    kind, link_id = _stored(ctx.links, fp)
    row = ledger_row(ctx, move)
    if row is not None and row.role == "group":
        kind, link_id = "group", row.group_id
    counterpart = ctx.exchange_suggestions.get(fp)
    stored = ctx.links.investment_for(fp)
    member = None if stored is None else stored.member(fp)
    box = ctx.links.cash_box_for(fp)
    boxed = None if box is None else box.member(fp)
    return RowLinks(
        kind=kind,
        link_id=link_id,
        can_share=kind == "" and is_shareable(move),
        can_reimburse=shared.is_eligible_credit(move, ctx.links),
        # Not an expense: an expense offers "Share" (an ATM withdrawal or a loan payment is one).
        can_pay=row is None
        and not is_shareable(move)
        and ledger_suggest.is_payment_debit(move, ctx.links, ctx.banks),
        can_exchange=exchanges.is_eligible(move, ctx.links, ctx.banks),
        ledger=row,
        exchange=exchange,
        exchange_legs=()
        if exchange is None
        else tuple(linked_tx(leg, ctx.labels) for leg in exchange.legs),
        suggested_exchange_with=None if counterpart is None else ctx.linked(counterpart),
        can_invest=can_invest(ctx, move),
        can_invest_credit=can_invest_credit(ctx, move),
        investment=None if stored is None else ctx.investment_states.get(stored.id),
        investment_role="" if member is None else member.role,
        investment_capital=None if member is None else member.capital,
        suggested_investment=ctx.investment_suggestions.get(fp),
        can_store=cash_box.can_store(move, ctx.links),
        can_deposit=cash_box.can_deposit(move, ctx.links, ctx.banks),
        **_boxed(ctx, move, boxed),
    )


def ledger_row(ctx: Context, move: Movement) -> LedgerRow | None:
    """The row's place in the ledger, if any (a group movement: by its entry)."""
    fp = move.fingerprint
    if move.link == "group" and fp.startswith("group-"):
        entry_id = int(fp.removeprefix("group-"))
        group = next((g for g in ctx.book.groups if g.entry(entry_id) is not None), None)
        state = None if group is None else ctx.groups.get(group.id)
        item = None if state is None else state.entry(entry_id)
        if group is None or item is None:
            return None
        return LedgerRow(group.id, group.name, "group", entry=item, paid_by=_payer(ctx, item))
    found = ctx.book.entry_for(fp)
    if found is not None:
        group, entry = found
        state = ctx.groups.get(group.id)
        item = None if state is None else state.entry(entry.id)
        return LedgerRow(group.id, group.name, "entry", entry=item)
    paid = ctx.book.payment_for(fp)
    if paid is not None:
        group, payment = paid
        return LedgerRow(group.id, group.name, "payment", payment=payment)
    return None


def _payer(ctx: Context, item: ledger.EntryState) -> str:
    return "" if item.entry.paid_by == ctx.book.me else ctx.book.name(item.entry.paid_by)


def _boxed(ctx: Context, move: Movement, member: cash_box.CashBoxMember | None) -> dict:
    """The row's cash box part: its role and, on a deposit, what left the box."""
    if member is None:
        return {}
    if member.role == "stored":
        return {"cash_box_role": "stored"}
    gross = shared.gross(move)
    currency = member.box_currency or move.currency
    taken = (
        cash_box.deposit_amount(member, -gross, move.currency, move.month, ctx.rates)
        if gross < 0
        else None
    )
    return {"cash_box_role": "deposit", "cash_box_currency": currency, "cash_box_amount": taken}


def _stored(found: Links, fingerprint: str) -> tuple[str, int | None]:
    """The stored link of the fingerprint (role and id), active or dormant."""
    if (held := found.ledger_for(fingerprint)) is not None:
        group_id, role = held
        return ("shared" if role == "entry" else "reimbursement"), group_id
    if (exchange := found.exchange_for(fingerprint)) is not None:
        return "exchange", exchange.id
    if (investment := found.investment_for(fingerprint)) is not None:
        return "investment", investment.id
    if (box := found.cash_box_for(fingerprint)) is not None:
        return "cash_box", box.id
    if (reserve := found.reserve_for(fingerprint)) is not None:
        return "reserve", reserve
    return "", None


def can_invest(ctx: Context, move: Movement) -> bool:
    """A bank-account debit that can be a contribution (cards do not send money to another
    person: this way it is not offered on every purchase)."""
    return move.account in ctx.banks and investments.is_contribution_candidate(move, ctx.links)


def can_invest_credit(ctx: Context, move: Movement) -> bool:
    """A bank-account credit that can come from an investment."""
    return move.account in ctx.banks and investments.is_credit_candidate(move, ctx.links)


def is_shareable(move: Movement) -> bool:
    return shared.is_shareable(move)


# --- Request checks ---------------------------------------------------------------------------


def check_shareable(found: Links, move: Movement) -> None:
    if found.is_linked(move.fingerprint):
        raise AlreadyLinked(t("web.already_linked"))
    if not is_shareable(move):
        raise LinkError(t("web.link.only_expense_shared"))


def check_payment_tx(found: Links, move: Movement, received: bool, banks: Collection[str]) -> None:
    """A transaction can reconcile a payment: unlinked, a credit if received (an eligible one)
    or, if paid, a debit the candidates would offer (`ledger_suggest.is_payment_debit`)."""
    if found.is_linked(move.fingerprint):
        raise AlreadyLinked(t("web.link.credit_already_linked"))
    if received and not shared.is_eligible_credit(move, found):
        raise LinkError(t("web.link.credit_not_eligible"))
    if not received and not ledger_suggest.is_payment_debit(move, found, banks):
        raise LinkError(t("web.ledger.payment_needs_debit"))


def check_legs(ctx: Context, new: Sequence[Movement], current: Sequence[Movement] = ()) -> None:
    """The new legs can be legs and, with the ones the exchange already has, form one."""
    for leg in new:
        if ctx.links.is_linked(leg.fingerprint):
            raise AlreadyLinked(t("web.link.leg_already_linked"))
        if leg.account not in ctx.banks:
            raise LinkError(t("web.link.leg_not_bank"))
        if not exchanges.is_eligible(leg, ctx.links, ctx.banks):
            raise LinkError(t("web.link.leg_not_eligible"))
    exchanges.check_legs([*current, *new])
