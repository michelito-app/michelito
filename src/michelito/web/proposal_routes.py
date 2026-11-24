"""The AI proposals in Review (see `web.proposals`).

- `GET /api/proposals`: the open proposals and the last answered ones, each with its items.
- `POST /api/proposals/{id}/apply` (`{"item_ids": [...]}`): apply the chosen items; the rest of
  the batch is skipped and the proposal is answered. Changes go through the app's own routes
  (`web.internal`) as `claude`, so each one is in the change log and can be undone there:
  "only this one" changes, one `PATCH /api/transactions` per target category (one change-log
  entry each); merchant rules, one `PATCH /api/transactions/{fingerprint}` each.
  A statement (`web.imports`) is stored whole, like a document (if it no longer squares or is
  already stored, 409 and the proposal stays open); provisional charges become provisionals of
  their account (`alerts`, confirmed by their statement); cash rows go through
  `POST /api/cash-box/entries` as `claude`, one entry each.
- `POST /api/proposals/{id}/dismiss`: answer it without changing anything.

409 if the proposal was already answered or is being applied (it is claimed first, so two
clicks cannot apply it twice); 404 if it does not exist.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import Any

import anyio
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from michelito.analysis import accounts as account_data
from michelito.analysis import cash_box, catalog, changelog
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import imports, internal, proposals
from michelito.web.workspace import CURRENT

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
AUTHOR = "claude"


class ItemOut(BaseModel):
    id: int
    fingerprint: str
    scope: str
    reason: str
    day: str
    merchant: str
    description: str
    amount_cents: int
    currency: str
    from_category: str
    to_category_id: int
    to_category: str  # its current name ("" if it no longer exists)
    status: str
    message: str


class RowOut(BaseModel):
    id: int
    day: str
    description: str
    amount_cents: int
    currency: str
    direction: str
    category: str  # the suggested category's name ("" if none)
    duplicate_of: str
    status: str
    message: str


class SectionOut(BaseModel):
    currency: str
    transactions: int
    debits_cents: int | None
    credits_cents: int | None
    closing_cents: int | None
    continues: bool | None  # its previous balance is the last stored closing (None: unknown)


class StatementOut(BaseModel):
    period_start: str | None
    period_end: str
    currencies: list[str]
    transactions: int
    document_status: str
    sections: list[SectionOut] = []


class ProposalOut(BaseModel):
    id: int
    created_at: str
    source: str
    title: str
    explanation: str
    status: str
    decided_at: str | None
    kind: str
    account_label: str  # the account of a statement or provisional charges ("" otherwise)
    items: list[ItemOut]
    rows: list[RowOut]
    statement: StatementOut | None

    @classmethod
    def of(
        cls, found: proposals.Proposal, known: catalog.Catalog, labels: dict[str, str]
    ) -> ProposalOut:
        def name(category_id: int | None) -> str:
            category = None if category_id is None else known.by_id(category_id)
            return "" if category is None else category.name

        summary = found.statement

        return cls(
            id=found.id,
            created_at=found.created_at,
            source=found.source,
            title=found.title,
            explanation=found.explanation,
            status=found.status,
            decided_at=found.decided_at,
            kind=found.kind,
            account_label=labels.get(found.account_key, found.account_key),
            rows=[
                RowOut(
                    id=r.id,
                    day=r.day,
                    description=r.description,
                    amount_cents=r.amount_cents,
                    currency=r.currency,
                    direction=r.direction,
                    category=name(r.category_id),
                    duplicate_of=r.duplicate_of,
                    status=r.status,
                    message=r.message,
                )
                for r in found.rows
            ],
            statement=None
            if summary is None
            else StatementOut(
                period_start=summary.period_start,
                period_end=summary.period_end,
                currencies=list(summary.currencies),
                transactions=summary.transactions,
                document_status=summary.document_status,
            ),
            items=[
                ItemOut(
                    id=i.id,
                    fingerprint=i.fingerprint,
                    scope=i.scope,
                    reason=i.reason,
                    day=i.day,
                    merchant=i.merchant,
                    description=i.description,
                    amount_cents=i.amount_cents,
                    currency=i.currency,
                    from_category=i.from_category,
                    to_category_id=i.category_id,
                    to_category=name(i.category_id),
                    status=i.status,
                    message=i.message,
                )
                for i in found.items
            ],
        )


class ApplyBody(BaseModel):
    item_ids: list[int] = Field(max_length=proposals.ITEMS_MAX)


Outcomes = dict[int, tuple[proposals.ItemStatus, str]]


class _Refused(Exception):
    """A statement that could not be stored after all: the proposal stays open."""


def _detail(answer: internal.Answer) -> str:
    """The route's own reason (a text, or a validation list's messages), cut short."""
    body = answer.body
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list):
        detail = "; ".join(str(d.get("msg", "")) for d in detail if isinstance(d, dict))
    if isinstance(detail, str) and detail:
        return detail[:200]
    return t("web.proposals.failed")


async def _apply_items(
    app: Any, request: Request, found: proposals.Proposal, chosen: Sequence[proposals.Item]
) -> Outcomes:
    workspace = CURRENT.get()
    if workspace is None:
        raise HTTPException(401, t("web.no_session"))
    host = request.headers.get("host", "localhost")
    reason = f"{found.source}: {found.title}"[: changelog.REASON_MAX]
    outcomes: Outcomes = {}
    by_category: dict[int, list[proposals.Item]] = defaultdict(list)
    for item in chosen:
        if item.scope == "transaction":
            by_category[item.category_id].append(item)
            continue
        answer = await internal.call(
            app,
            workspace,
            host,
            "PATCH",
            f"/api/transactions/{item.fingerprint}",
            body={"category_id": item.category_id, "scope": "merchant"},
            author=AUTHOR,
        )
        ok = answer.status == 200
        outcomes[item.id] = ("applied", "") if ok else ("failed", _detail(answer))
    for category_id, items in by_category.items():
        answer = await internal.call(
            app,
            workspace,
            host,
            "PATCH",
            "/api/transactions",
            body={
                "fingerprints": [i.fingerprint for i in items],
                "category_id": category_id,
                "reason": reason,
            },
            author=AUTHOR,
        )
        if answer.status != 200 or not isinstance(answer.body, dict):
            for item in items:
                outcomes[item.id] = ("failed", _detail(answer))
            continue
        skipped = {s["fingerprint"]: s.get("message", "") for s in answer.body.get("skipped", [])}
        for item in items:
            if item.fingerprint in skipped:
                outcomes[item.id] = ("skipped", str(skipped[item.fingerprint])[:200])
            else:
                outcomes[item.id] = ("applied", "")
    return outcomes


async def _apply_cash(
    app: Any, request: Request, chosen: Sequence[proposals.ImportRow]
) -> Outcomes:
    """Each chosen row as a cash entry, through the cash route (logged, undoable)."""
    workspace = CURRENT.get()
    if workspace is None:
        raise HTTPException(401, t("web.no_session"))
    host = request.headers.get("host", "localhost")
    outcomes: Outcomes = {}
    for row in chosen:
        try:
            answer = await _post_cash(app, workspace, host, row)
        except Exception as exc:  # noqa: BLE001 - the rest are answered; never applied twice
            outcomes[row.id] = ("failed", type(exc).__name__)
            continue
        ok = answer.status in (200, 201)
        outcomes[row.id] = ("applied", "") if ok else ("failed", _detail(answer))
    return outcomes


async def _post_cash(
    app: Any, workspace: Any, host: str, row: proposals.ImportRow
) -> internal.Answer:
    return await internal.call(
        app,
        workspace,
        host,
        "POST",
        "/api/cash-box/entries",
        body={
            "kind": "expense" if row.direction == "out" else "income",
            "day": row.day,
            "amount_cents": row.amount_cents,
            "currency": row.currency,
            "category_id": row.category_id,
            "concept": row.description[: cash_box.CONCEPT_MAX],
        },
        author=AUTHOR,
    )


def _document_outcome(status: str) -> tuple[proposals.ItemStatus, str]:
    if status == "parsed":
        return "applied", ""
    if status == "duplicate":
        return "skipped", t("web.proposals.duplicate_statement")
    return "failed", t("web.proposals.failed")


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:  # noqa: ARG001
    def labels(conn: sqlite3.Connection) -> dict[str, str]:
        return {info.key: info.label for info in account_data.account_infos(conn)}

    def out(conn: sqlite3.Connection, found: proposals.Proposal) -> ProposalOut:
        shown = ProposalOut.of(found, catalog.load(conn), labels(conn))
        if shown.statement is None:
            return shown
        summaries = imports.section_summaries(
            conn, found.account_key, imports.payload_of(conn, found.id)
        )
        sections = [SectionOut(**vars(summary)) for summary in summaries]
        return shown.model_copy(
            update={"statement": shown.statement.model_copy(update={"sections": sections})}
        )

    def read_all() -> list[ProposalOut]:
        with connection() as conn:
            return [out(conn, p) for p in proposals.load_all(conn)]

    def read_open(proposal_id: int) -> proposals.Proposal:
        with connection() as conn:
            found = proposals.load(conn, proposal_id)
        if found is None:
            raise HTTPException(404, t("web.proposals.unknown"))
        if found.status != "open":
            raise HTTPException(409, t("web.proposals.answered"))
        return found

    def claim(proposal_id: int) -> bool:
        with connection() as conn:
            return proposals.claim(conn, proposal_id)

    def release(proposal_id: int) -> None:
        with connection() as conn:
            proposals.release(conn, proposal_id)

    def answer(
        proposal_id: int,
        status: proposals.Status,
        outcomes: Outcomes,
        made: dict[int, str] | None = None,
    ) -> ProposalOut:
        with connection() as conn:
            proposals.finish(conn, proposal_id, status, outcomes, made)
            done = proposals.load(conn, proposal_id)
            assert done is not None
            return out(conn, done)

    def store_statement(found: proposals.Proposal) -> str:
        with connection() as conn:
            try:
                return imports.store_statement(conn, found.id, found.account_key)
            except proposals.ProposalError as error:  # the account changed since: not stored
                raise _Refused(str(error)) from None

    def add_provisionals(found: proposals.Proposal, row_ids: list[int]) -> dict[int, str]:
        with connection() as conn:
            return imports.add_provisionals(conn, found.id, found.account_key, row_ids)

    async def apply_kind(
        request: Request, found: proposals.Proposal, wanted: set[int]
    ) -> tuple[Outcomes, dict[int, str]]:
        """What applying does for each kind: (outcomes by item or row id, fingerprints made)."""
        if found.kind == "category":
            chosen = [i for i in found.items if i.id in wanted]
            return await _apply_items(app, request, found, chosen), {}
        if found.kind == "statement":
            status = await anyio.to_thread.run_sync(store_statement, found)
            state, message = _document_outcome(status)
            if state == "failed":  # it no longer squares: stays open, to dismiss
                raise _Refused(message)
            return {}, {}  # stored, or already stored: answered either way
        rows = [r for r in found.rows if r.id in wanted]
        if found.kind == "cash":
            return await _apply_cash(app, request, rows), {}
        made = await anyio.to_thread.run_sync(add_provisionals, found, [r.id for r in rows])
        return {r.id: ("applied", "") for r in rows if r.id in made}, made

    @app.get("/api/proposals")
    def get_proposals() -> list[ProposalOut]:
        return read_all()

    @app.post("/api/proposals/{proposal_id}/apply")
    async def post_apply(proposal_id: int, body: ApplyBody, request: Request) -> ProposalOut:
        found = await anyio.to_thread.run_sync(read_open, proposal_id)
        wanted = set(body.item_ids)
        known_ids = {i.id for i in found.items} | {r.id for r in found.rows}
        if not wanted <= known_ids:
            raise HTTPException(422, t("web.proposals.unknown_item"))
        if not await anyio.to_thread.run_sync(claim, proposal_id):
            raise HTTPException(409, t("web.proposals.answered"))
        try:
            outcomes, made = await apply_kind(request, found, wanted)
        except _Refused as refused:
            await anyio.to_thread.run_sync(release, proposal_id)
            raise HTTPException(409, str(refused)) from None
        except Exception:
            await anyio.to_thread.run_sync(release, proposal_id)
            raise
        return await anyio.to_thread.run_sync(answer, proposal_id, "applied", outcomes, made)

    @app.post("/api/proposals/{proposal_id}/dismiss")
    def post_dismiss(proposal_id: int) -> ProposalOut:
        read_open(proposal_id)
        return answer(proposal_id, "dismissed", {})
