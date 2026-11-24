"""What a tag holds and what it adds up to (pure: no SQLite).

Members (`members`): the transactions tagged by hand, plus, for a group tag, every movement of
its group (transactions linked to its entries and the `group-<entry>` movements of entries
someone else paid), plus the payments of the loans and the charges of the installment plans
tagged as a whole. Each fingerprint is listed once; when it arrives by several routes the
first of group > loan / installment > manual names it (`via`). A fingerprint no longer in the
flow (a statement read again) is skipped, and comes back when it reappears.

A loan whose money reached the user's account (`has_payout`) is debt, not spending: tagging it
brings neither its payments nor what is still to pay; the purchase it paid for is the expense.

Total (`total`): the flow already carries the user's share of a shared expense (`link ==
"shared"`: `amount` is what counts), so the total is the sum, in RD$, of the members that
count (`counts`: expense kinds, refunds subtracting; never transfers, income or payments
received for a group). Dollars without the month's rate are listed and counted in
`unconverted`, not added.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from michelito.analysis.spending import Movement
from michelito.analysis.tag_store import Tag

_ZERO = Decimal("0")
_NOT_SPENDING_LINKS = frozenset({"reimbursement", "exchange", "investment"})


@dataclass(frozen=True)
class Sources:
    """Where derived members come from, by movement fingerprint."""

    groups: Mapping[str, int]  # -> group id (linked transactions and `group-<entry>` movements)
    loans: Mapping[str, int]  # -> loan id (its payments)
    plans: Mapping[str, int]  # -> installment plan id (its charges)
    loans_with_payout: frozenset[int]
    remaining: Mapping[tuple[str, int], Decimal]  # ("loan" | "installment", id) -> RD$ left


@dataclass(frozen=True)
class Member:
    move: Movement
    derived: bool
    via: str  # "manual" | "group" | "loan" | "installment"
    counted: bool


@dataclass(frozen=True)
class TagTotal:
    spent: Decimal
    still_to_pay: Decimal
    unconverted: int
    count: int
    first: date | None
    last: date | None
    by_category: tuple[tuple[str, Decimal], ...]


def counts(move: Movement) -> bool:
    """Whether the movement adds to a tag's total: an expense (or its refund), never a
    transfer, income, or a payment received for a group."""
    if move.link in _NOT_SPENDING_LINKS:
        return False
    return move.link in ("shared", "group") or move.kind == "expense"


def _route(
    tag: Tag,
    move: Movement,
    manual: Collection[str],
    targets: Collection[tuple[str, int]],
    sources: Sources,
) -> str | None:
    fingerprint = move.fingerprint
    if tag.group_id is not None and sources.groups.get(fingerprint) == tag.group_id:
        return "group"
    loan = sources.loans.get(fingerprint)
    if loan is not None and ("loan", loan) in targets and loan not in sources.loans_with_payout:
        return "loan"
    plan = sources.plans.get(fingerprint)
    if plan is not None and ("installment", plan) in targets:
        return "installment"
    if fingerprint in manual:
        return "manual"
    return None


def members(
    tag: Tag,
    flow: Sequence[Movement],
    manual: Collection[str],
    targets: Collection[tuple[str, int]],
    sources: Sources,
) -> list[Member]:
    found: dict[str, Member] = {}
    for move in flow:
        if not move.fingerprint or move.fingerprint in found:
            continue
        via = _route(tag, move, manual, targets, sources)
        if via is not None:
            found[move.fingerprint] = Member(move, via != "manual", via, counts(move))
    return sorted(found.values(), key=lambda m: (m.move.day, m.move.fingerprint), reverse=True)


def still_to_pay(targets: Collection[tuple[str, int]], sources: Sources) -> Decimal:
    """What the tagged loans (without payout) and installment plans still owe, in RD$."""
    left = _ZERO
    for kind, target_id in targets:
        if kind == "loan" and target_id in sources.loans_with_payout:
            continue
        left += sources.remaining.get((kind, target_id), _ZERO)
    return left


def total(
    found: Sequence[Member],
    to_dop: Callable[[Movement], Decimal | None],
    left: Decimal,
) -> TagTotal:
    spent, unconverted = _ZERO, 0
    by_category: dict[str, Decimal] = {}
    for member in found:
        if not member.counted:
            continue
        amount = to_dop(member.move)
        if amount is None:
            unconverted += 1
            continue
        spent += amount
        by_category[member.move.category] = by_category.get(member.move.category, _ZERO) + amount
    days = [m.move.day for m in found]
    return TagTotal(
        spent=spent,
        still_to_pay=left,
        unconverted=unconverted,
        count=len(found),
        first=min(days, default=None),
        last=max(days, default=None),
        by_category=tuple(sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))),
    )


def memberships(
    all_tags: Sequence[Tag],
    flow: Sequence[Movement],
    manual: Mapping[int, Collection[str]],
    targets: Mapping[int, Collection[tuple[str, int]]],
    sources: Sources,
) -> dict[str, list[tuple[Tag, Member]]]:
    """Every tag each movement is in, in one pass over the flow (for the chips on the rows):
    the same membership as `members`, tag by tag, without walking the flow once per tag."""
    by_group = {tag.group_id: tag for tag in all_tags if tag.group_id is not None}
    by_id = {tag.id: tag for tag in all_tags}
    by_manual: dict[str, list[Tag]] = {}
    for tag_id, fingerprints in manual.items():
        if tag_id in by_id:
            for fp in fingerprints:
                by_manual.setdefault(fp, []).append(by_id[tag_id])
    by_target: dict[tuple[str, int], list[Tag]] = {}
    for tag_id, wanted in targets.items():
        if tag_id in by_id:
            for target in wanted:
                by_target.setdefault(target, []).append(by_id[tag_id])
    found: dict[str, list[tuple[Tag, Member]]] = {}
    for move in flow:
        fp = move.fingerprint
        candidates: dict[int, Tag] = {t.id: t for t in by_manual.get(fp, ())}
        group = sources.groups.get(fp)
        if group is not None and group in by_group:
            candidates[by_group[group].id] = by_group[group]
        for kind, index in (("loan", sources.loans), ("installment", sources.plans)):
            target_id = index.get(fp)
            if target_id is not None:
                candidates.update({t.id: t for t in by_target.get((kind, target_id), ())})
        for tag in candidates.values():
            via = _route(tag, move, manual.get(tag.id, ()), targets.get(tag.id, ()), sources)
            if via is not None:
                found.setdefault(fp, []).append(
                    (tag, Member(move, via != "manual", via, counts(move)))
                )
    return found
