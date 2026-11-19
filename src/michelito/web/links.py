"""Links for the web: what each Transactions row shows about shared groups, reimbursements,
currency exchanges and investments, and the checks on the requests that change them."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from functools import cached_property

from michelito.analysis import cash_box, exchanges, investments, shared
from michelito.analysis.accounts import BANK_KINDS, AccountInfo
from michelito.analysis.exchanges import ExchangeState
from michelito.analysis.investments import InvestmentState, Suggestion
from michelito.analysis.links import AlreadyLinked, LinkError, Links
from michelito.analysis.rates import Rate, rate_for
from michelito.analysis.shared import ExpenseState, SharedState
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
class GroupView:
    """A shared group with its expenses and credits ready to show."""

    state: SharedState
    expenses: tuple[tuple[ExpenseState, LinkedTx], ...]  # oldest first
    credits: tuple[LinkedTx, ...]  # linked credits present, by date


@dataclass(frozen=True)
class RowLinks:
    # The row's stored link, even when dormant (its expense no longer appears or stopped being an
    # expense; the exchange is missing a leg): "shared", "reimbursement", "exchange",
    # "investment" or "".
    kind: str = ""
    link_id: int | None = None
    # What can be done with the row (the same rules the server checks).
    can_share: bool = False
    can_reimburse: bool = False
    can_exchange: bool = False
    group: GroupView | None = None  # the row's active group (as expense or as reimbursement)
    expense: ExpenseState | None = None  # the row as an expense of a group
    reimbursement_of: LinkedTx | None = None  # the first expense of the group it reimburses
    suggested_group: SharedState | None = None  # "Reimbursement of <group>?"
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
    groups: Mapping[int, SharedState] = field(default_factory=dict)
    exchange_states: Mapping[int, ExchangeState] = field(default_factory=dict)
    reimbursement_suggestions: Mapping[str, int] = field(default_factory=dict)
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
    def expense_states(self) -> dict[str, ExpenseState]:
        """The state of each shared expense present, by fingerprint."""
        return shared.by_expense(self.groups)

    def group_view(self, link_id: int) -> GroupView | None:
        state = self.groups.get(link_id)
        if state is None:
            return None
        currency = state.first.currency
        credits = sorted(
            (move for fp in state.link.reimbursements if (move := self.movement(fp)) is not None),
            key=lambda m: (m.day, m.fingerprint),
        )
        return GroupView(
            state=state,
            expenses=tuple((e, linked_tx(e.move, self.labels)) for e in state.expenses),
            credits=tuple(self.credit_for(m, currency) for m in credits),
        )

    @cached_property
    def _by_fp(self) -> dict[str, Movement]:
        return {m.fingerprint: m for m in self.movements}


def linked_tx(move: Movement, labels: Mapping[str, str]) -> LinkedTx:
    return LinkedTx(
        fingerprint=move.fingerprint,
        day=move.day,
        merchant=move.merchant,
        account_label=labels.get(move.account, move.account),
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
) -> Context:
    """`suggest=False` skips the suggestions (the Summary does not need them). `reviewed`: what
    was marked in "To review" (fingerprint, kind): an investment proposal already reviewed ("It
    is not") is not suggested on the row again."""
    banks = frozenset(a.key for a in accounts if a.kind in BANK_KINDS)
    labels = {a.key: a.label for a in accounts}
    moves = tuple(movements)
    groups = shared.states(moves, found, rates)
    invested = investments.states(moves, found, rates)
    if not suggest:
        return Context(
            found,
            moves,
            labels,
            banks,
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
        groups=groups,
        exchange_states=exchanges.states(moves, found),
        reimbursement_suggestions=shared.suggestions(moves, found, groups, rates),
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
    expense = ctx.expense_states.get(fp)
    kind, link_id = _stored(ctx.links, fp)
    group = None
    if link_id is not None and (expense is not None or kind == "reimbursement"):
        group = ctx.group_view(link_id)
    owner = ctx.links.reimbursed(fp)
    of = None
    if owner is not None:
        first = ctx.groups[owner.id].first.fingerprint if owner.id in ctx.groups else None
        of = ctx.linked(first or owner.expenses[0].fingerprint)
    suggested = ctx.reimbursement_suggestions.get(fp)
    counterpart = ctx.exchange_suggestions.get(fp)
    stored = ctx.links.investment_for(fp)
    member = None if stored is None else stored.member(fp)
    box = ctx.links.cash_box_for(fp)
    boxed = None if box is None else box.member(fp)
    return RowLinks(
        kind=kind,
        link_id=link_id,
        can_share=kind in ("", "shared") and is_shareable(move),
        can_reimburse=shared.is_eligible_credit(move, ctx.links),
        can_exchange=exchanges.is_eligible(move, ctx.links, ctx.banks),
        group=group,
        expense=expense,
        reimbursement_of=of,
        suggested_group=None if suggested is None else ctx.groups.get(suggested),
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
    if (owner := found.shared_for(fingerprint)) is not None:
        return "shared", owner.id
    if (owner := found.reimbursed(fingerprint)) is not None:
        return "reimbursement", owner.id
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
    if found.is_linked(move.fingerprint) and found.shared_for(move.fingerprint) is None:
        raise AlreadyLinked(t("web.already_linked"))
    if not is_shareable(move):
        raise LinkError(t("web.link.only_expense_shared"))


def check_reimbursement(ctx: Context, link_id: int, credit: Movement) -> None:
    """The credit can reimburse the group: it is not linked, it is an eligible credit and there
    is a rate to convert it to the currency of each expense of the group."""
    if ctx.links.is_linked(credit.fingerprint):
        raise AlreadyLinked(t("web.link.credit_already_linked"))
    state = ctx.groups.get(link_id)
    if state is None:
        raise LinkError(t("web.link.not_shared"))
    if credit.amount >= 0:
        raise LinkError(t("web.link.only_credit_reimburses"))
    currencies = {e.currency for e in state.expenses}
    if any(shared.converted(credit, c, ctx.rates) is None for c in currencies):
        raise LinkError(t("web.link.missing_rate"))
    if not shared.is_eligible_credit(credit, ctx.links):
        raise LinkError(t("web.link.credit_not_eligible"))


def check_joinable(ctx: Context, link_id: int, move: Movement) -> None:
    """The expense can join the group: it is an unlinked expense and the group exists."""
    if ctx.links.group(link_id) is None:
        raise LookupError(t("web.link.unknown_group", link_id=link_id))
    if ctx.links.is_linked(move.fingerprint):
        raise AlreadyLinked(t("web.already_linked"))
    if not is_shareable(move):
        raise LinkError(t("web.link.only_expense_shared"))


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
