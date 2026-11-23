"""The "To review" list for the web: the rules of `analysis.review` with the Recurring warnings,
the chosen accounts and each account's label. Pure functions."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property

from michelito.analysis import investments, ledger, ledger_cover, ledger_suggest, reserves, review
from michelito.analysis import links as link_data
from michelito.analysis.accounts import BANK_KINDS, AccountInfo
from michelito.analysis.changelog_rules import RuleSuggestion
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.recurring_marks import Mark
from michelito.analysis.reserves import Reserve
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import ledger_view
from michelito.web import recurring as recurring_view

HISTORY_MONTHS = 12


@dataclass(frozen=True)
class ReviewView:
    item: review.Item
    account_label: str


# What a linked installment never is.
_INSTALLMENT_HIDES = frozenset({"one_off", "duplicate", "price_up"})


@dataclass(frozen=True)
class Context:
    """What does not change from one month to the next."""

    flow: Sequence[Movement]  # every movement (every account)
    accounts: Sequence[AccountInfo]
    rates: Mapping[str, Rate]
    marks: Mapping[tuple[str, str], Mark]
    reviewed: Collection[tuple[str, str]]
    dismissed: Collection[str]
    selected: frozenset[str] | None = None
    links: link_data.Links = link_data.NONE  # to propose investment contributions and returns
    # Proposed merchant rules (from the change log), with their category name.
    rules: Sequence[tuple[RuleSuggestion, str]] = ()
    unions: Mapping[str, str] = field(default_factory=dict)  # Recurring unions
    # Expenses that look like a reserve's (`web.budget.link_hints`): fingerprint -> the reserve.
    reserve_hints: Mapping[str, Reserve] = field(default_factory=dict)
    book: ledger.Ledger = ledger.EMPTY  # the shared ledger, for possible payments

    @cached_property
    def payments(self) -> dict[str, ledger_suggest.ReverseSuggestion]:
        """Credits that look like a payment from someone who owes the user (computed once)."""
        if not self.book.groups:
            return {}
        states = ledger.states(self.book, self.rates)
        return ledger_suggest.reverse_suggestions(self.flow, self.links, self.book, states)

    @cached_property
    def covers(self) -> list[tuple[ledger.Group, ledger_cover.CoverSuggestion]]:
        """ "Was that payment for someone else too?", one per group at most (computed once)."""
        found = []
        for state in ledger.states(self.book, self.rates).values():
            suggestion = ledger_cover.cover_suggestion(state, self.book.me)
            if suggestion is not None:
                found.append((state.group, suggestion))
        return found

    # Provisionals missing from their statement (`live_store.unmatched`): fingerprint -> the
    # closing date of the statement they should have been in; and the user's decisions.
    unmatched: Mapping[str, date] = field(default_factory=dict)
    decisions: Mapping[str, str] = field(default_factory=dict)
    # Purchases a reversal alert named that still count (`live_store.reversals`).
    reversals: Mapping[str, str] = field(default_factory=dict)
    # Merchant receipts with more than one possible transaction (`receipt_match.proposals`):
    # fingerprint -> the receipt proposed for it and what the item says.
    receipts: Mapping[str, tuple[int, str]] = field(default_factory=dict)
    # Installment plans: the charges linked as installments (never one-offs, duplicates or
    # price rises) and the off-script ones (fingerprint -> the plan and what the item says).
    installments: Collection[str] = frozenset()
    off_script: Mapping[str, tuple[int, int | None, str]] = field(default_factory=dict)
    # Loans: their linked payments (hidden like installments) and the months whose loan
    # statement disagrees (fingerprint of the month's first payment -> the loan and the reason).
    loans: Collection[str] = frozenset()
    loan_differences: Mapping[str, tuple[int, str]] = field(default_factory=dict)

    @cached_property
    def hints(self) -> dict[str, review.Hint]:
        """Possible investment contributions and returns, with every account (as in Shared):
        computed once per request, not once per history month."""
        if not self.links.investments:
            return {}
        found = investments.states(self.flow, self.links, self.rates)
        banks = {a.key for a in self.accounts if a.kind in BANK_KINDS}
        proposed = investments.suggestions(self.flow, self.links, found, self.rates, banks)
        return {fp: review.Hint(s.kind, s.reason, s.state.id) for fp, s in proposed.items()}


def month_items(ctx: Context, month: str) -> list[ReviewView]:
    """The month's items, pending and reviewed, with the history of the chosen accounts.

    Like the one-off card: an unusual purchase on the chosen card is judged against what is
    bought with it. The price warnings come from Recurring with the same accounts, measured
    against the latest data of all of them.
    """
    mine = [m for m in ctx.flow if ctx.selected is None or m.account in ctx.selected]
    labels = {info.key: info.label for info in ctx.accounts}
    found = review.detect(
        mine,
        month,
        rate_for_month=lambda m: rate_for(ctx.rates, m),
        marks=ctx.marks,
        price_ups=_price_ups(ctx, mine, month),
        reviewed=ctx.reviewed,
        dismissed=ctx.dismissed,
        hints=ctx.hints,
        unions=ctx.unions,
    )
    proposed = _payment_items(ctx, mine, month)
    shown = {i.fingerprint for i in proposed}
    found = [
        i
        for i in found
        if i.fingerprint not in shown
        and not (
            i.kind in _INSTALLMENT_HIDES
            and (i.fingerprint in ctx.installments or i.fingerprint in ctx.loans)
        )
    ]
    found = [
        *proposed,
        *_cover_items(ctx, month),
        *_unconfirmed_items(ctx, mine, month),
        *_reversal_items(ctx, mine, month),
        *_receipt_items(ctx, mine, month),
        *_installment_items(ctx, mine, month),
        *_loan_items(ctx, mine, month),
        *_rule_items(ctx, mine, month),
        *_reserve_items(ctx, mine, month),
        *found,
    ]
    return [ReviewView(item, labels.get(item.account, item.account)) for item in found]


def _rule_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """The "UBER EATS: you put it in Delivery 2 times. Always?" items, in the month of the most
    recent of those transactions (if it is from the chosen accounts)."""
    by_fp = {m.fingerprint: m for m in mine}
    items = []
    for found, name in ctx.rules:
        latest = next((by_fp[fp] for fp in found.fingerprints if fp in by_fp), None)
        if latest is None or latest.month != month:
            continue
        amount = abs(latest.gross if latest.gross is not None else latest.amount)
        items.append(
            review.Item(
                kind="possible_rule",
                fingerprint=latest.fingerprint,
                day=latest.day,
                merchant=latest.merchant,
                description=latest.description,
                account=latest.account,
                amount=amount,
                currency=latest.currency,
                amount_dop=to_dop(amount, latest.currency, rate_for(ctx.rates, month)),
                reason=t(
                    "web.review.rule_reason",
                    merchant=found.merchant,
                    count=found.count,
                    category=name,
                ),
                category_id=found.category_id,
            )
        )
    return items


def _reserve_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """The "Is it from the reserve 'Marbete'? (due in January)" item for each expense of the
    month that looks like it; one already marked "No" comes out as reviewed."""
    items = []
    for move in mine:
        reserve = ctx.reserve_hints.get(move.fingerprint)
        if reserve is None or move.month != month:
            continue
        due = reserves.near_due(reserve, month) or reserve.due_month
        items.append(
            review.Item(
                kind="possible_reserve",
                fingerprint=move.fingerprint,
                day=move.day,
                merchant=move.merchant,
                description=move.description,
                account=move.account,
                amount=abs(move.amount),
                currency=move.currency,
                amount_dop=to_dop(abs(move.amount), move.currency, rate_for(ctx.rates, month)),
                reason=t(
                    "web.review.reserve_reason",
                    name=reserve.name,
                    month=reserves.month_name(due),
                    year=due[:4],
                ),
                reviewed=(move.fingerprint, "possible_reserve") in ctx.reviewed,
                reserve_id=reserve.id,
            )
        )
    return items


def _unconfirmed_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """ "It did not show up in your <month> statement. Was it reversed?" for each provisional of
    the month missing from its statement; one already kept comes out as reviewed."""
    items = []
    for move in mine:
        closing = ctx.unmatched.get(move.fingerprint)
        if closing is None or move.month != month:
            continue
        amount = abs(move.amount)
        items.append(
            review.Item(
                kind="unconfirmed",
                fingerprint=move.fingerprint,
                day=move.day,
                merchant=move.merchant,
                description=move.description,
                account=move.account,
                amount=amount,
                currency=move.currency,
                amount_dop=to_dop(amount, move.currency, rate_for(ctx.rates, month)),
                reason=t(
                    "web.review.unconfirmed_reason",
                    month=reserves.month_name(closing.strftime("%Y-%m")),
                ),
                reviewed=ctx.decisions.get(move.fingerprint) == "keep",
                provisional=True,
            )
        )
    return items


def _receipt_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """ "Is this the charge of your Amazon order …?" for each transaction of the month a
    merchant receipt may be about, when the receipt has more than one candidate."""
    items = []
    for move in mine:
        proposed = ctx.receipts.get(move.fingerprint)
        if proposed is None or move.month != month:
            continue
        receipt_id, reason = proposed
        amount = abs(move.gross if move.gross is not None else move.amount)
        items.append(
            review.Item(
                kind="possible_receipt",
                fingerprint=move.fingerprint,
                day=move.day,
                merchant=move.merchant,
                description=move.description,
                account=move.account,
                amount=amount,
                currency=move.currency,
                amount_dop=to_dop(amount, move.currency, rate_for(ctx.rates, month)),
                reason=reason,
                provisional=move.provisional,
                receipt_id=receipt_id,
            )
        )
    return items


def _installment_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """A charge that looks like an installment plan's but is off its script (another amount,
    two in a month, after the last one, a refund), for the person to decide."""
    items = []
    for move in mine:
        found = ctx.off_script.get(move.fingerprint)
        if found is None or move.month != month:
            continue
        plan_id, number, reason = found
        amount = abs(move.gross if move.gross is not None else move.amount)
        items.append(
            review.Item(
                kind="installment_off_script",
                installment_number=number,
                fingerprint=move.fingerprint,
                day=move.day,
                merchant=move.merchant,
                description=move.description,
                account=move.account,
                amount=amount,
                currency=move.currency,
                amount_dop=to_dop(amount, move.currency, rate_for(ctx.rates, month)),
                reason=reason,
                plan_id=plan_id,
            )
        )
    return items


def _loan_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """A month whose loan statement disagrees with its payments or with the contract, on the
    month's first linked payment."""
    items = []
    for move in mine:
        found = ctx.loan_differences.get(move.fingerprint)
        if found is None or move.month != month:
            continue
        loan_id, reason = found
        amount = abs(move.gross if move.gross is not None else move.amount)
        items.append(
            review.Item(
                kind="loan_difference",
                fingerprint=move.fingerprint,
                day=move.day,
                merchant=move.merchant,
                description=move.description,
                account=move.account,
                amount=amount,
                currency=move.currency,
                amount_dop=to_dop(amount, move.currency, rate_for(ctx.rates, month)),
                reason=reason,
                loan_id=loan_id,
            )
        )
    return items


def _reversal_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """ "The bank reported a reversal…" for each purchase of the month a reversal alert named
    that still counts (linked, so not voided; or charged by the statement anyway)."""
    items = []
    for move in mine:
        state = ctx.reversals.get(move.fingerprint)
        if state is None or move.month != month:
            continue
        amount = abs(move.gross if move.gross is not None else move.amount)
        key = "web.review.reversal_charged" if state == "charged" else "web.review.reversal_linked"
        items.append(
            review.Item(
                kind="reversal",
                fingerprint=move.fingerprint,
                day=move.day,
                merchant=move.merchant,
                description=move.description,
                account=move.account,
                amount=amount,
                currency=move.currency,
                amount_dop=to_dop(amount, move.currency, rate_for(ctx.rates, month)),
                reason=t(key),
                reviewed=ctx.decisions.get(move.fingerprint) == "keep",
                provisional=move.provisional,
            )
        )
    return items


def _payment_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """ "Did Ana pay you RD$1,250?": each credit of the month that looks like a group payment; one
    marked "No" comes out as reviewed."""
    items = []
    names = {g.id: g.name for g in ctx.book.groups}
    for move in mine:
        found = ctx.payments.get(move.fingerprint)
        if found is None or move.month != month:
            continue
        who = ctx.book.name(found.contact_id) or t("web.review.payment_someone")
        key = "web.review.payment_link_reason" if found.payment_id else "web.review.payment_reason"
        items.append(
            review.Item(
                kind="possible_payment",
                fingerprint=move.fingerprint,
                day=move.day,
                merchant=move.merchant,
                description=move.description,
                account=move.account,
                amount=found.amount,
                currency=move.currency,
                amount_dop=to_dop(found.amount, move.currency, rate_for(ctx.rates, month)),
                reason=t(key, name=who, group=names.get(found.group_id, "")),
                reviewed=(move.fingerprint, "possible_payment") in ctx.reviewed,
                group_id=found.group_id,
                contact_id=found.contact_id,
                payment_id=found.payment_id,
            )
        )
    return items


COVER_KEY = "ledger-payment-{id}"  # the item's key when the payment is not linked to the bank


def _cover_items(ctx: Context, month: str) -> list[review.Item]:
    """ "Ana paid RD$ 38,440 too much and Beto owes US$ 629.31. Was that payment for Beto too?"
    in the month of that payment (not tied to the chosen accounts: it is the group's). "No"
    dismisses it in the ledger (`ledger_store.set_cover_dismissed`), so it never comes back
    as reviewed here."""
    items = []
    for group, found in ctx.covers if ctx.book.groups else ():
        payment = found.payment
        if payment.day.strftime("%Y-%m") != month:
            continue
        text = ledger_view.cover_text(ctx.book, found)
        items.append(
            review.Item(
                kind="possible_cover",
                fingerprint=payment.fingerprint or COVER_KEY.format(id=payment.id),
                day=payment.day,
                merchant=group.name,
                description=text,
                account="",
                amount=found.excess,
                currency=payment.currency,
                amount_dop=to_dop(found.excess, payment.currency, rate_for(ctx.rates, month)),
                reason=text,
                group_id=group.id,
                contact_id=found.payer,
                payment_id=payment.id,
                payment_ids=tuple(p.id for p in found.payments),
            )
        )
    return items


def history(ctx: Context, months: Sequence[str], kind: str | None = None) -> list[ReviewView]:
    """The items of the given months (most recent first), pending and reviewed."""
    found = [
        view for month in sorted(set(months), reverse=True) for view in month_items(ctx, month)
    ]
    return [view for view in found if kind is None or view.item.kind == kind]


def _price_ups(ctx: Context, mine: Sequence[Movement], month: str) -> dict[str, str]:
    expenses = [m for m in mine if m.kind == "expense"]
    if not expenses:
        return {}
    as_of = max(m.day for m in ctx.flow if m.kind == "expense")
    overview = recurring_view.build_overview(
        expenses, ctx.marks, ctx.rates, month, as_of=as_of, unions=ctx.unions
    )
    return {
        a.fingerprint: a.detail for a in overview.alerts if a.kind == "price_up" and a.fingerprint
    }
