"""Matching merchant receipts to transactions (see `receipts` and `receipt_store`).

A receipt (an order confirmation, a shipment notice) adds detail to a transaction that already
exists; it never creates one. `match` is pure: a transaction is a candidate for a receipt when
its description is the merchant's, the currency is the same, the cents are exactly the
receipt's and it is dated from `DAYS_BEFORE` before to `DAYS_AFTER` after the email.

- One candidate: linked, if the receipt is `trusted`.
- Several: proposed (the person chooses in To review). Never guessed.
- A transaction already linked to a receipt of another order is not a candidate; receipts that
  all want one free transaction are linked only if one order number is common to all of them
  (a shipment across two orders does not make the two orders one); otherwise they are proposed.
- A pair the person removed (`dismissed`) is not offered again.

What a merchant's email says is weaker than a bank alert: it does not name the card and its
amount is not always what is charged (an order may be charged in parts). So nothing here is
ever inferred beyond an exact, single candidate. And a receipt that came by email forwarding
is never linked on its own: anyone who knows an account's forwarding address can send it a
genuine email about an order of their own, so it is only proposed (`Pending.trusted`).

`reconcile` applies it to the stored receipts and the loaded flow, in the caller's
transaction, and is idempotent:

1. A link or a refusal made on a provisional follows it to the statement row that confirmed it
   under another fingerprint (`moved`, from `moved_provisionals`).
2. A link to a transaction that is no longer in the flow is dropped, and its receipt is looked
   for again.
3. What `match` links is linked (origin `'automatic'`); what it proposes is returned.

Automatic links are not change-log entries of their own, like an alert's confirmation; what
the person does about a link (`web.receipt_routes`) is, and the automatic links that follow
from it are part of that same entry.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from michelito.analysis import receipt_store
from michelito.analysis.receipt_store import Stored

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

_PROVISIONAL = "alert-"  # `live_store.FINGERPRINT_PREFIX`

DAYS_BEFORE = 1
DAYS_AFTER = 5
FORWARDED = "forwarding"  # `hosted.inbox.SOURCE`: the one source whose sender is not the owner's
_CENTS = 100

# How a bank prints each merchant (the receipt's display name -> its descriptions).
DESCRIPTIONS: dict[str, re.Pattern[str]] = {
    "Amazon": re.compile(r"(?<![A-Z0-9])(AMAZON|AMZN)(?![A-Z0-9])", re.IGNORECASE),
}


@dataclass(frozen=True)
class Pending:
    """A receipt not linked to any transaction yet."""

    id: int
    merchant: str
    orders: tuple[str, ...]
    amount_cents: int
    currency: str
    day: date  # when the email arrived
    trusted: bool = True  # False: it may not be the owner's (forwarded): proposed, never linked


@dataclass(frozen=True)
class Charge:
    """A transaction a receipt may be about."""

    fingerprint: str
    day: date
    amount_cents: int
    currency: str
    description: str


@dataclass(frozen=True)
class Matches:
    links: dict[int, str] = field(default_factory=dict)  # receipt id -> fingerprint
    proposals: dict[int, tuple[str, ...]] = field(default_factory=dict)  # -> its candidates


def is_merchant(merchant: str, description: str) -> bool:
    pattern = DESCRIPTIONS.get(merchant)
    return pattern is not None and pattern.search(description) is not None


def _fits(receipt: Pending, row: Charge) -> bool:
    """Same amount and currency already (the caller looks rows up by them): the date window and
    the merchant."""
    offset = (row.day - receipt.day).days
    return -DAYS_BEFORE <= offset <= DAYS_AFTER and is_merchant(receipt.merchant, row.description)


def match(
    receipts: Iterable[Pending],
    charges: Iterable[Charge],
    *,
    dismissed: Collection[tuple[int, str]] = (),
    taken: Mapping[str, frozenset[str]] | None = None,
) -> Matches:
    """Receipt id -> the transaction it is linked to, or the ones proposed for it.

    `dismissed`: (receipt id, fingerprint) pairs the person removed. `taken`: for a transaction
    that already has receipts, the order numbers of those receipts."""
    owners = taken or {}
    by_amount: dict[tuple[str, int], list[Charge]] = {}
    for row in sorted(charges, key=lambda row: (row.day, row.fingerprint)):
        by_amount.setdefault((row.currency, row.amount_cents), []).append(row)
    waiting = sorted(receipts, key=lambda item: item.id)
    candidates: dict[int, tuple[str, ...]] = {}
    wanted: dict[str, list[Pending]] = {}
    for receipt in waiting:
        own = frozenset(receipt.orders)
        found = tuple(
            row.fingerprint
            for row in by_amount.get((receipt.currency, receipt.amount_cents), ())
            if _fits(receipt, row)
            and (receipt.id, row.fingerprint) not in dismissed
            and (row.fingerprint not in owners or owners[row.fingerprint] & own)
        )
        if found:
            candidates[receipt.id] = found
            for fingerprint in found:
                wanted.setdefault(fingerprint, []).append(receipt)
    trusted = {receipt.id for receipt in waiting if receipt.trusted}
    links: dict[int, str] = {}
    proposals: dict[int, tuple[str, ...]] = {}
    for receipt_id, found in candidates.items():
        if len(found) == 1 and receipt_id in trusted and _one_order(wanted[found[0]]):
            links[receipt_id] = found[0]
        else:
            proposals[receipt_id] = found
    return Matches(links, proposals)


def _one_order(receipts: list[Pending]) -> bool:
    """Whether one order number is common to every receipt that wants a transaction."""
    return bool(frozenset.intersection(*(frozenset(receipt.orders) for receipt in receipts)))


def charges(
    movements: Iterable[Movement], amounts: Collection[tuple[str, int]] | None = None
) -> list[Charge]:
    """The transactions a receipt may be about: every one with a positive statement amount
    (`gross` when a link changed what counts as the person's expense). `amounts`: only the ones
    of these (currency, cents)."""
    found = []
    for movement in movements:
        amount: Decimal = movement.amount if movement.gross is None else movement.gross
        cents = int(amount * _CENTS)
        if cents <= 0 or not movement.fingerprint:
            continue
        if amounts is not None and (movement.currency, cents) not in amounts:
            continue
        found.append(
            Charge(
                movement.fingerprint, movement.day, cents, movement.currency, movement.description
            )
        )
    return found


def moved_provisionals(conn: sqlite3.Connection) -> dict[str, str]:
    """A provisional's fingerprint -> the statement row that confirmed it under a fingerprint
    of its own (`live_match`: the row did not take the provisional's identity)."""
    known = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alerts'"
    ).fetchone()
    if known is None:
        return {}
    rows = conn.execute(
        "SELECT id, statement_fingerprint FROM alerts "
        "WHERE status = 'confirmed' AND keeps_identity = 0 AND statement_fingerprint IS NOT NULL"
    )
    return {f"alert-{alert_id}": str(mark) for alert_id, mark in rows}


def _matches(
    conn: sqlite3.Connection,
    movements: Sequence[Movement],
    stored: Sequence[Stored],
    moved: Mapping[str, str],
) -> Matches:
    """What `match` says for the receipts with no transaction in the flow (read-only)."""
    present = {movement.fingerprint for movement in movements}

    def alive(fingerprint: str) -> bool:
        return fingerprint in present or moved.get(fingerprint) in present

    waiting = [
        Pending(
            r.id, r.merchant, r.orders, r.amount_cents, r.currency, r.day, r.source != FORWARDED
        )
        for r in stored
        if not any(alive(fingerprint) for fingerprint in r.links)
    ]
    if not waiting:
        return Matches()
    taken: dict[str, frozenset[str]] = {}
    for receipt in stored:
        for fingerprint in receipt.links:
            target = fingerprint if fingerprint in present else moved.get(fingerprint, "")
            if target in present:
                taken[target] = taken.get(target, frozenset()) | frozenset(receipt.orders)
    refused = receipt_store.dismissed(conn)
    dismissed = refused | {(rid, moved[mark]) for rid, mark in refused if mark in moved}
    amounts = {(receipt.currency, receipt.amount_cents) for receipt in waiting}
    return match(waiting, charges(movements, amounts), dismissed=dismissed, taken=taken)


def _carry(
    conn: sqlite3.Connection,
    stored: Sequence[Stored],
    present: Collection[str],
    moved: Mapping[str, str],
) -> bool:
    """Steps 1 and 2: move or drop the links to transactions that left the flow. True if
    anything changed."""
    changed = False
    for receipt in stored:
        for fingerprint in receipt.links:
            if fingerprint in present:
                continue
            target = moved.get(fingerprint)
            if target in present and target is not None:
                receipt_store.move_link(conn, receipt.id, fingerprint, target)
            else:
                receipt_store.drop_link(conn, receipt.id, fingerprint)
            changed = True
    return changed


def reconcile(
    conn: sqlite3.Connection,
    movements: Iterable[Movement],
    now: str,
    *,
    moved: Mapping[str, str] | None = None,
) -> Matches:
    """Steps 1 to 3 (see the module), in the caller's transaction; returns what was linked and
    what is proposed. `moved`: by default, `moved_provisionals`."""
    flow = tuple(movements)
    stored = receipt_store.load(conn)
    if not stored:
        return Matches()
    renamed = moved_provisionals(conn) if moved is None else moved
    present = {movement.fingerprint for movement in flow}
    if _carry(conn, stored, present, renamed):
        stored = receipt_store.load(conn)
    found = _matches(conn, flow, stored, renamed)
    for receipt_id, fingerprint in found.links.items():
        receipt_store.link(conn, receipt_id, fingerprint, "automatic", now)
    return found


def proposals(
    conn: sqlite3.Connection, movements: Iterable[Movement]
) -> dict[int, tuple[str, ...]]:
    """Receipt id -> the transactions proposed for it (nothing is written)."""
    stored = receipt_store.load(conn)
    if not _may_wait(stored):
        return {}
    return _matches(conn, tuple(movements), stored, moved_provisionals(conn)).proposals


def _may_wait(stored: Sequence[Stored]) -> bool:
    """Whether any receipt may be without its transaction: one with no link, or one linked to
    a provisional (the only fingerprints that are replaced). Cheap: it does not need the flow."""
    return any(
        not receipt.links or any(mark.startswith(_PROVISIONAL) for mark in receipt.links)
        for receipt in stored
    )


def reconcile_stored(conn: sqlite3.Connection, now: str) -> Matches:
    """`reconcile` against the whole flow as stored, loaded only if a receipt may be waiting.
    For the places that store receipts or statements outside a board request (the sync, the
    forwarding inbox); in the caller's transaction."""
    from michelito.analysis import spending  # noqa: PLC0415 (it loads every analysis module)

    if not _may_wait(receipt_store.load(conn)):
        return Matches()
    return reconcile(conn, spending.load_all(conn), now)
