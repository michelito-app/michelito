"""The AI proposals in Review (see `web.proposals`).

- `GET /api/proposals`: the open proposals and the last answered ones, each with its items.
- `POST /api/proposals/{id}/apply` (`{"item_ids": [...]}`): apply the chosen items; the rest of
  the batch is skipped and the proposal is answered. Changes go through the app's own routes
  (`web.internal`) as `claude`, so each one is in the change log and can be undone there:
  "only this one" changes, one `PATCH /api/transactions` per target category (one change-log
  entry each); merchant rules, one `PATCH /api/transactions/{fingerprint}` each.
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

from michelito.analysis import catalog, changelog
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import internal, proposals
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


class ProposalOut(BaseModel):
    id: int
    created_at: str
    source: str
    title: str
    explanation: str
    status: str
    decided_at: str | None
    items: list[ItemOut]

    @classmethod
    def of(cls, found: proposals.Proposal, known: catalog.Catalog) -> ProposalOut:
        def name(category_id: int) -> str:
            category = known.by_id(category_id)
            return "" if category is None else category.name

        return cls(
            id=found.id,
            created_at=found.created_at,
            source=found.source,
            title=found.title,
            explanation=found.explanation,
            status=found.status,
            decided_at=found.decided_at,
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


def _detail(answer: internal.Answer) -> str:
    body = answer.body
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return str(body["detail"])[:200]
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


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:  # noqa: ARG001
    def read_all() -> list[ProposalOut]:
        with connection() as conn:
            known = catalog.load(conn)
            return [ProposalOut.of(p, known) for p in proposals.load_all(conn)]

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

    def answer(proposal_id: int, status: proposals.Status, outcomes: Outcomes) -> ProposalOut:
        with connection() as conn:
            proposals.finish(conn, proposal_id, status, outcomes)
            known = catalog.load(conn)
            done = proposals.load(conn, proposal_id)
        assert done is not None
        return ProposalOut.of(done, known)

    @app.get("/api/proposals")
    def get_proposals() -> list[ProposalOut]:
        return read_all()

    @app.post("/api/proposals/{proposal_id}/apply")
    async def post_apply(proposal_id: int, body: ApplyBody, request: Request) -> ProposalOut:
        found = await anyio.to_thread.run_sync(read_open, proposal_id)
        wanted = set(body.item_ids)
        known_ids = {i.id for i in found.items}
        if not wanted <= known_ids:
            raise HTTPException(422, t("web.proposals.unknown_item"))
        chosen = [i for i in found.items if i.id in wanted]
        if not await anyio.to_thread.run_sync(claim, proposal_id):
            raise HTTPException(409, t("web.proposals.answered"))
        try:
            outcomes = await _apply_items(app, request, found, chosen)
        except Exception:
            await anyio.to_thread.run_sync(release, proposal_id)
            raise
        return await anyio.to_thread.run_sync(answer, proposal_id, "applied", outcomes)

    @app.post("/api/proposals/{proposal_id}/dismiss")
    def post_dismiss(proposal_id: int) -> ProposalOut:
        read_open(proposal_id)
        return answer(proposal_id, "dismissed", {})
