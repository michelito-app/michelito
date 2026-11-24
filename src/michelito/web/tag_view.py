"""Tags as the board shows them: where derived members come from (`sources`), the chips on each
transaction row (`chips`) and a tag's page (`detail`). The math is `analysis.tags`."""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from michelito.analysis import installment_store, ledger_store, loan_store, rates, tag_store
from michelito.analysis import tags as tag_math
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement, group_fingerprint
from michelito.web import loans as loans_view

_CENTS = Decimal(100)


@dataclass(frozen=True)
class TagChip:
    id: int
    name: str
    color: str | None
    derived: bool


@dataclass(frozen=True)
class Context:
    tags: tuple[tag_store.Tag, ...]
    manual: Mapping[int, set[str]]
    targets: Mapping[int, set[tuple[str, int]]]
    sources: tag_math.Sources
    by_month: Mapping[str, Rate]


@dataclass(frozen=True)
class Detail:
    tag: tag_store.Tag
    members: tuple[tag_math.Member, ...]
    total: tag_math.TagTotal


def _today_dop(
    amount: Decimal, currency: str, by_month: Mapping[str, Rate], today: date
) -> Decimal:
    found = rates.to_dop(amount, currency, rates.rate_for(by_month, today.isoformat()[:7]))
    return Decimal(0) if found is None else found


def sources(
    conn: sqlite3.Connection,
    flow: Sequence[Movement],
    by_month: Mapping[str, Rate],
    today: date,
    tagged: Collection[tuple[str, int]] = (),
) -> tag_math.Sources:
    """Where derived members come from; what is still to pay only for the loans and plans some
    tag holds (`tagged`: building a loan's view walks its schedule)."""
    groups: dict[str, int] = {}
    for group in ledger_store.load(conn).groups:
        for entry in group.entries:
            groups[group_fingerprint(entry.id)] = group.id
            if entry.fingerprint:
                groups[entry.fingerprint] = group.id
    loans = loan_store.load(conn)
    plans = installment_store.load(conn)
    remaining: dict[tuple[str, int], Decimal] = {}
    for loan in loans:
        if ("loan", loan.id) not in tagged:
            continue
        balance = loans_view.view(loan, flow, (), today).summary.balance
        remaining[("loan", loan.id)] = _today_dop(balance, loan.currency, by_month, today)
    for plan in plans:
        if ("installment", plan.id) not in tagged:
            continue
        left = installment_store.amount_of(installment_store.remaining_cents(plan))
        remaining[("installment", plan.id)] = _today_dop(left, plan.currency, by_month, today)
    return tag_math.Sources(
        groups=groups,
        loans={fp: loan.id for loan in loans for fp in loan.links},
        plans={fp: plan.id for plan in plans for fp in plan.links.values()},
        loans_with_payout=frozenset(loan.id for loan in loans if loan.has_payout),
        remaining=remaining,
    )


def context(conn: sqlite3.Connection, flow: Sequence[Movement], today: date) -> Context:
    by_month = rates.load(conn)
    targets = tag_store.targets(conn)
    tagged = {target for wanted in targets.values() for target in wanted}
    return Context(
        tags=tuple(tag_store.load(conn)),
        manual=tag_store.manual(conn),
        targets=targets,
        sources=sources(conn, flow, by_month, today, tagged),
        by_month=by_month,
    )


def to_dop(by_month: Mapping[str, Rate]):  # noqa: ANN201 (a small closure)
    def convert(move: Movement) -> Decimal | None:
        return rates.to_dop(move.amount, move.currency, rates.rate_for(by_month, move.month))

    return convert


def detail(ctx: Context, tag: tag_store.Tag, flow: Sequence[Movement]) -> Detail:
    targets = ctx.targets.get(tag.id, set())
    found = tag_math.members(tag, flow, ctx.manual.get(tag.id, set()), targets, ctx.sources)
    left = tag_math.still_to_pay(targets, ctx.sources)
    return Detail(tag, tuple(found), tag_math.total(found, to_dop(ctx.by_month), left))


def details(ctx: Context, flow: Sequence[Movement]) -> list[Detail]:
    return [detail(ctx, tag, flow) for tag in ctx.tags]


def row_chips(ctx: Context, flow: Sequence[Movement]) -> dict[str, tuple[TagChip, ...]]:
    """The chips on every row, in one pass over the flow (`analysis.tags.memberships`)."""
    if not ctx.tags:
        return {}
    found = tag_math.memberships(ctx.tags, flow, ctx.manual, ctx.targets, ctx.sources)
    return {
        fp: tuple(TagChip(tag.id, tag.name, tag.color, member.derived) for tag, member in items)
        for fp, items in found.items()
    }


def chips(found: Sequence[Detail]) -> dict[str, tuple[TagChip, ...]]:
    by_fp: dict[str, list[TagChip]] = {}
    for item in found:
        for member in item.members:
            chip = TagChip(item.tag.id, item.tag.name, item.tag.color, member.derived)
            by_fp.setdefault(member.move.fingerprint, []).append(chip)
    return {fp: tuple(found) for fp, found in by_fp.items()}


def cents(amount: Decimal) -> int:
    return int((amount * _CENTS).to_integral_value())


@dataclass(frozen=True)
class TargetView:
    """A loan or installment plan a tag holds as a whole."""

    kind: str  # "loan" | "installment"
    id: int
    name: str
    has_payout: bool  # its money reached the account: it adds nothing (the purchase counts)
    still_to_pay: Decimal


def names(conn: sqlite3.Connection) -> dict[tuple[str, int], tuple[str, bool]]:
    """("loan" | "installment", id) -> (name, has payout) of every loan and plan."""
    found: dict[tuple[str, int], tuple[str, bool]] = {
        ("loan", loan.id): (loan.name, loan.has_payout) for loan in loan_store.load(conn)
    }
    found.update({("installment", p.id): (p.name, False) for p in installment_store.load(conn)})
    return found


def targets_of(conn: sqlite3.Connection, ctx: Context, tag: tag_store.Tag) -> list[TargetView]:
    known = names(conn)
    shown = []
    for kind, target_id in sorted(ctx.targets.get(tag.id, set())):
        name, payout = known.get((kind, target_id), ("", False))
        left = Decimal(0) if payout else ctx.sources.remaining.get((kind, target_id), Decimal(0))
        shown.append(TargetView(kind, target_id, name, payout, left))
    return shown
