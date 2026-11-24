"""AI proposals (schema 28): what an AI connector asks to change, kept until the person answers.

- `propose`: checks a batch of category changes against the database (each transaction must
  exist, appear once and be one whose category can change; each category must exist and be
  one a person can choose) and saves it as one open proposal, with a snapshot of each
  transaction. Nothing in the ledger changes.
- `load_all` / `load`: the proposals as Review shows them.
- `finish`: after applying (`web.proposal_routes`), each item's outcome and the batch's status.

Every text in a proposal (title, explanation, reasons) comes from the AI: it is plain text,
cut to its maximum, and the interface shows it as data.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from michelito.analysis import catalog, changelog
from michelito.analysis.spending import Movement
from michelito.migrations_v28 import EXPLANATION_MAX, REASON_MAX, TITLE_MAX
from michelito.web import batch_edit
from michelito.web import categories as categories_view

ITEMS_MAX = 200
OPEN_MAX = 50  # open proposals an account may have at once
SOURCE_MAX = 80
Scope = Literal["transaction", "merchant"]
Status = Literal["open", "applying", "applied", "dismissed"]
ItemStatus = Literal["open", "applied", "skipped", "failed"]


class ProposalError(ValueError):
    """A batch that cannot be saved; `code` says why, `detail` where (no values)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Change:
    fingerprint: str
    category_id: int
    scope: Scope
    reason: str = ""


@dataclass(frozen=True)
class Item:
    id: int
    fingerprint: str
    category_id: int
    scope: Scope
    reason: str
    day: str
    merchant: str
    description: str
    amount_cents: int
    currency: str
    from_category: str
    status: ItemStatus
    message: str


@dataclass(frozen=True)
class Proposal:
    id: int
    created_at: str
    source: str
    title: str
    explanation: str
    status: Status
    decided_at: str | None
    items: tuple[Item, ...]


def plain(text: str, limit: int) -> str:
    """Visible text only (no control or format characters), single spaces, cut to `limit`."""
    kept = "".join(
        " " if unicodedata.category(c) == "Cc" else c
        for c in text
        if unicodedata.category(c) not in ("Cf", "Co", "Cs")
    )
    return " ".join(kept.split())[:limit]


def _cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def _check(
    changes: Sequence[Change], flow: Sequence[Movement], known: catalog.Catalog
) -> list[tuple[Change, Movement]]:
    if not 1 <= len(changes) <= ITEMS_MAX:
        raise ProposalError("items", f"between 1 and {ITEMS_MAX}")
    by_fingerprint: Mapping[str, Movement] = {m.fingerprint: m for m in flow if m.fingerprint}
    seen: set[str] = set()
    checked = []
    for index, change in enumerate(changes):
        movement = by_fingerprint.get(change.fingerprint)
        if movement is None:
            raise ProposalError("unknown_transaction", f"changes[{index}]")
        if change.fingerprint in seen:
            raise ProposalError("repeated_transaction", f"changes[{index}]")
        seen.add(change.fingerprint)
        if movement.link in batch_edit.FIXED_BY_LINK:
            raise ProposalError("linked_transaction", f"changes[{index}]")
        try:
            categories_view.edit_target(known, None, change.category_id)
        except catalog.CategoryError:
            raise ProposalError("unknown_category", f"changes[{index}]") from None
        checked.append((change, movement))
    return checked


def propose(
    conn: sqlite3.Connection,
    flow: Sequence[Movement],
    source: str,
    title: str,
    explanation: str,
    changes: Sequence[Change],
) -> int:
    """Save one open proposal (in its own transaction); its id. `ProposalError` if anything in
    it does not hold, or the account already has `OPEN_MAX` open proposals."""
    shown_title = plain(title, TITLE_MAX)
    if not shown_title:
        raise ProposalError("title")
    known = catalog.load(conn)
    checked = _check(changes, flow, known)
    with conn:
        count = conn.execute("SELECT COUNT(*) FROM ai_proposals WHERE status = 'open'").fetchone()
        if int(count[0]) >= OPEN_MAX:
            raise ProposalError("too_many_open")
        cursor = conn.execute(
            "INSERT INTO ai_proposals (created_at, source, title, explanation) VALUES (?, ?, ?, ?)",
            (
                changelog.now().isoformat(timespec="seconds"),
                plain(source, SOURCE_MAX) or "MCP",
                shown_title,
                plain(explanation, EXPLANATION_MAX),
            ),
        )
        proposal_id = int(cursor.lastrowid or 0)
        conn.executemany(
            "INSERT INTO ai_proposal_items (proposal_id, kind, fingerprint, category_id, scope, "
            "reason, day, merchant, description, amount_cents, currency, from_category) "
            "VALUES (?, 'category', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    proposal_id,
                    change.fingerprint,
                    change.category_id,
                    change.scope,
                    plain(change.reason, REASON_MAX),
                    movement.day.isoformat(),
                    movement.merchant,
                    movement.description,
                    _cents(movement.amount),
                    movement.currency,
                    known.name_of(movement.ref),
                )
                for change, movement in checked
            ],
        )
    return proposal_id


_PROPOSAL = "id, created_at, source, title, explanation, status, decided_at"
_ITEM = (
    "id, proposal_id, fingerprint, category_id, scope, reason, day, merchant, description, "
    "amount_cents, currency, from_category, status, message"
)


def _item(row: sqlite3.Row) -> Item:
    return Item(
        row["id"],
        row["fingerprint"],
        row["category_id"],
        row["scope"],
        row["reason"],
        row["day"],
        row["merchant"],
        row["description"],
        row["amount_cents"],
        row["currency"],
        row["from_category"],
        row["status"],
        row["message"],
    )


def _proposal(row: sqlite3.Row, items: Sequence[Item]) -> Proposal:
    return Proposal(
        row["id"],
        row["created_at"],
        row["source"],
        row["title"],
        row["explanation"],
        row["status"],
        row["decided_at"],
        tuple(items),
    )


def load_all(conn: sqlite3.Connection, decided: int = 10) -> list[Proposal]:
    """The open proposals (newest first), then the last `decided` answered ones."""
    previous = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT {_PROPOSAL} FROM ai_proposals WHERE status = 'open' ORDER BY id DESC"
        ).fetchall()
        rows += conn.execute(
            f"SELECT {_PROPOSAL} FROM ai_proposals WHERE status != 'open' "
            "ORDER BY decided_at DESC, id DESC LIMIT ?",
            (decided,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        items: dict[int, list[Item]] = {i: [] for i in ids}
        if ids:
            marks = ",".join("?" * len(ids))
            for row in conn.execute(
                f"SELECT {_ITEM} FROM ai_proposal_items WHERE proposal_id IN ({marks}) ORDER BY id",
                ids,
            ):
                items[row["proposal_id"]].append(_item(row))
        return [_proposal(r, items[r["id"]]) for r in rows]
    finally:
        conn.row_factory = previous


def load(conn: sqlite3.Connection, proposal_id: int) -> Proposal | None:
    previous = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"SELECT {_PROPOSAL} FROM ai_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            return None
        found = conn.execute(
            f"SELECT {_ITEM} FROM ai_proposal_items WHERE proposal_id = ? ORDER BY id",
            (proposal_id,),
        ).fetchall()
        return _proposal(row, [_item(r) for r in found])
    finally:
        conn.row_factory = previous


def claim(conn: sqlite3.Connection, proposal_id: int) -> bool:
    """Mark an open proposal as being applied; False if it was not open (already answered, or
    another request is applying it)."""
    with conn:
        return (
            conn.execute(
                "UPDATE ai_proposals SET status = 'applying' WHERE id = ? AND status = 'open'",
                (proposal_id,),
            ).rowcount
            == 1
        )


def release(conn: sqlite3.Connection, proposal_id: int) -> None:
    """Back to open after applying failed half way (what was applied stays in the log)."""
    with conn:
        conn.execute(
            "UPDATE ai_proposals SET status = 'open' WHERE id = ? AND status = 'applying'",
            (proposal_id,),
        )


def finish(
    conn: sqlite3.Connection,
    proposal_id: int,
    status: Status,
    outcomes: Mapping[int, tuple[ItemStatus, str]],
) -> None:
    """Record the answer: the batch's status and each item's outcome (the rest are skipped)."""
    with conn:
        conn.execute(
            "UPDATE ai_proposals SET status = ?, decided_at = ? WHERE id = ? "
            "AND status IN ('open', 'applying')",
            (status, changelog.now().isoformat(timespec="seconds"), proposal_id),
        )
        conn.execute(
            "UPDATE ai_proposal_items SET status = 'skipped' WHERE proposal_id = ? "
            "AND status = 'open'",
            (proposal_id,),
        )
        conn.executemany(
            "UPDATE ai_proposal_items SET status = ?, message = ? WHERE id = ? AND proposal_id = ?",
            [(state, message, item, proposal_id) for item, (state, message) in outcomes.items()],
        )
