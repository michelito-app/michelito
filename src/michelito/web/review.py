"""The "To review" list for the web: the rules of `analysis.review` with the Recurring warnings,
the chosen accounts and each account's label. Pure functions."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property

from michelito.analysis import investments, reserves, review
from michelito.analysis import links as link_data
from michelito.analysis.accounts import BANK_KINDS, AccountInfo
from michelito.analysis.changelog_rules import RuleSuggestion
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.recurring_marks import Mark
from michelito.analysis.reserves import Reserve
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import recurring as recurring_view

HISTORY_MONTHS = 12


@dataclass(frozen=True)
class ReviewView:
    item: review.Item
    account_label: str


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
    found = [*_rule_items(ctx, mine, month), *_reserve_items(ctx, mine, month), *found]
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
