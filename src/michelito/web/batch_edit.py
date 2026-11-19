"""Change the category of several transactions at once (Transactions multi-select).

- `plan` (pure logic): which fingerprints change and which are skipped, with the reason. Skipped:
  a transaction whose link sets its category (cash box, investment, reimbursement, currency
  exchange: what `spending.with_links` sets), a manual cash-box entry that does not fit (money
  in only goes to an income category and money out to an expense one, as when it is recorded),
  a debit that would go to an income category (a debit is not income), one already in that
  category, and a fingerprint that does not exist.
  "Already there" looks at the category shown, wherever it comes from (merchant rule, keyword,
  automatic): it gets no correction of its own, so if the merchant rule changes later, that
  transaction follows it (decided: the batch does not "freeze" what was already there).
- `apply`: saves "only this one" on each (never a merchant rule) inside the caller's SQLite
  transaction, as ONE change-log entry (`category_batch`) with the fingerprints that changed and
  the shared reason. "Undo" returns each one to its exact previous correction (also "no
  correction"), without touching its note or "one-off".
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from michelito.analysis import cash_box, catalog, changelog, changelog_rules, corrections
from michelito.analysis.spending import Movement
from michelito.i18n import t

BATCH_KIND = changelog_rules.BATCH_KIND
BATCH_MAX = 500
# Links that set the category of their transactions (a shared expense does not change it).
FIXED_BY_LINK = frozenset({"cash_box", "investment", "reimbursement", "exchange"})
# How many previous categories the change-log line names; more than that, "several categories".
_BEFORE_NAMES = 3

SkipReason = Literal["linked", "cash_box", "direction", "unchanged", "unknown"]
SKIP_MESSAGES: dict[str, str] = {
    "linked": t("web.batch.skip.linked"),
    "cash_box": t("web.batch.skip.cash_box"),
    "direction": t("web.batch.skip.direction"),
    "unchanged": t("web.batch.skip.unchanged"),
    "unknown": t("web.batch.skip.unknown"),
}


@dataclass(frozen=True)
class Skipped:
    fingerprint: str
    reason: SkipReason

    @property
    def message(self) -> str:
        return SKIP_MESSAGES[self.reason]


@dataclass(frozen=True)
class Plan:
    chosen: tuple[Movement, ...]  # the ones that change, in the requested order
    skipped: tuple[Skipped, ...]


def fits(move: Movement, kind: str) -> bool:
    """Whether a category of that kind fits the transaction. A debit (positive amount) cannot be
    income; a credit can go to an expense (a refund subtracts from its category)."""
    return not (kind == "income" and move.amount > 0)


def plan(
    movements: Sequence[Movement], fingerprints: Iterable[str], target: catalog.Category
) -> Plan:
    """What changes and what does not (without repeating fingerprints)."""
    by_fp = {m.fingerprint: m for m in movements}
    chosen: list[Movement] = []
    skipped: list[Skipped] = []
    for fp in dict.fromkeys(fingerprints):
        move = by_fp.get(fp)
        reason = _skip_reason(move, target)
        if reason is not None:
            skipped.append(Skipped(fp, reason))
        elif move is not None:
            chosen.append(move)
    return Plan(tuple(chosen), tuple(skipped))


def _skip_reason(move: Movement | None, target: catalog.Category) -> SkipReason | None:
    if move is None:
        return "unknown"
    if move.link in FIXED_BY_LINK:
        return "linked"
    if cash_box.manual_category_error(move.fingerprint, move.amount, target.kind) is not None:
        return "cash_box"
    if not fits(move, target.kind):
        return "direction"
    if move.ref == target.ref:
        return "unchanged"
    return None


def count_text(count: int) -> str:
    return (
        t("web.batch.one_transaction") if count == 1 else t("web.batch.transactions", count=count)
    )


def before_text(moves: Sequence[Movement]) -> str:
    """The change-log "before": the category (or the categories from most to least frequent, up
    to three)."""
    names = [name for name, _ in Counter(m.category for m in moves).most_common()]
    if len(names) > _BEFORE_NAMES:
        return t("web.batch.several_categories")
    return ", ".join(names)


def apply(
    conn: sqlite3.Connection, chosen: Sequence[Movement], target: catalog.Category, reason: str
) -> int | None:
    """Sets `target` on each one (in the caller's transaction) and returns the change-log entry
    (None if there was nothing to change). An error leaves everything as it was."""
    if not chosen:
        return None
    fingerprints = [m.fingerprint for m in chosen]
    with changelog.track(
        conn,
        BATCH_KIND,
        "category",  # the target is the category they move to (no `change_log` migration)
        str(target.id),
        count_text(len(chosen)),
        before=before_text(chosen),
        after=target.name,
        fingerprints=fingerprints,
    ) as draft:
        for fp in fingerprints:
            corrections.set_transaction_category(conn, fp, target.id)
    if draft.entry_id is not None and reason.strip():
        changelog.set_reason(conn, draft.entry_id, reason)
    return draft.entry_id
