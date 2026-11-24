"""`/api/tags`: tags that group transactions by purpose (spec `.superpowers/sdd/tags.md`).

Every write is one change-log entry (target type "link", target `tag-<id>`, like groups'
`group-<id>`), so it shows in the log with its author and can be undone. A group's tag is
renamed and deleted with its group, and its derived members are untagged from the group.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date, timedelta
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Response

from michelito.analysis import catalog, changelog, corrections, rates, tag_store
from michelito.analysis.catalog import fold
from michelito.analysis.spending import Movement
from michelito.analysis.tags import counts
from michelito.i18n import t
from michelito.web import tag_view
from michelito.web.tag_schemas import (
    AddedOut,
    CandidateOut,
    CandidatesOut,
    CategoryAmountOut,
    ChangedOut,
    FingerprintsBody,
    MemberOut,
    OneOffBody,
    RemovedOut,
    TagBody,
    TagOut,
    TagPatch,
    TagSummaryOut,
    TargetOut,
    row_fields,
)
from michelito.web.tag_view import cents

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
Today = Callable[[], date]

LIKELY_LARGEST = 10
DEFAULT_MONTHS_BACK = 92  # days: an empty tag's candidates start about three months back
_GROUP_MARK = "group-"


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow, today: Today) -> None:
    @contextmanager
    def tracked(
        conn: sqlite3.Connection,
        kind: str,
        tag_id: int | str,
        subject: str,
        fingerprints: Sequence[str] = (),
    ) -> Iterator[changelog.Draft]:
        try:
            with (
                conn,
                changelog.track(
                    conn, kind, "link", f"tag-{tag_id}", subject, fingerprints=fingerprints
                ) as draft,
            ):
                yield draft
        except tag_store.DuplicateTag as error:
            raise HTTPException(409, str(error)) from None
        except tag_store.TagError as error:
            raise HTTPException(400, str(error)) from None
        except KeyError:
            raise HTTPException(404, t("web.tags.unknown")) from None

    def tag_of(conn: sqlite3.Connection, tag_id: int) -> tag_store.Tag:
        try:
            return tag_store.get(conn, tag_id)
        except KeyError:
            raise HTTPException(404, t("web.tags.unknown")) from None

    def detail_of(conn: sqlite3.Connection, tag_id: int) -> tag_view.Detail:
        tag = tag_of(conn, tag_id)
        flow = load_flow(conn)
        return tag_view.detail(tag_view.context(conn, flow, today()), tag, flow)

    def tag_out(conn: sqlite3.Connection, tag_id: int) -> TagOut:
        tag = tag_of(conn, tag_id)
        flow = load_flow(conn)
        ctx = tag_view.context(conn, flow, today())
        found = tag_view.detail(ctx, tag, flow)
        shown = [
            TargetOut(
                kind=v.kind,
                id=v.id,
                name=v.name,
                has_payout=v.has_payout,
                still_to_pay_cents=cents(v.still_to_pay),
            )
            for v in tag_view.targets_of(conn, ctx, tag)
        ]
        convert = tag_view.to_dop(rates.load(conn))
        members = []
        for member in found.members:
            dop = convert(member.move)
            members.append(MemberOut.of(member, None if dop is None else cents(dop)))
        return TagOut(
            **TagSummaryOut.of(found).model_dump(),
            members=members,
            targets=shown,
            by_category=[
                CategoryAmountOut(category=name, amount_cents=cents(amount))
                for name, amount in found.total.by_category
            ],
        )

    @app.get("/api/tags")
    def get_tags() -> list[TagSummaryOut]:
        with connection() as conn:
            flow = load_flow(conn)
            ctx = tag_view.context(conn, flow, today())
            return [TagSummaryOut.of(d) for d in tag_view.details(ctx, flow)]

    @app.post("/api/tags", status_code=201)
    def post_tag(body: TagBody) -> TagSummaryOut:
        with connection() as conn:
            now = changelog.now().isoformat()
            with tracked(conn, "tag_create", "new", body.name.strip()):
                made = tag_store.create(conn, body.name, body.color, now)
            return TagSummaryOut.of(detail_of(conn, made.id))

    @app.get("/api/tags/{tag_id}")
    def get_tag(tag_id: int) -> TagOut:
        with connection() as conn:
            return tag_out(conn, tag_id)

    @app.patch("/api/tags/{tag_id}")
    def patch_tag(tag_id: int, body: TagPatch) -> TagOut:
        with connection() as conn:
            tag = tag_of(conn, tag_id)
            with tracked(conn, "tag_rename", tag_id, tag.name):
                if body.name is not None:
                    tag_store.rename(conn, tag_id, body.name)
                if "color" in body.model_fields_set:
                    tag_store.set_color(conn, tag_id, body.color)
            return tag_out(conn, tag_id)

    @app.delete("/api/tags/{tag_id}", status_code=204)
    def delete_tag(tag_id: int) -> Response:
        with connection() as conn:
            tag = tag_of(conn, tag_id)
            with tracked(conn, "tag_delete", tag_id, tag.name):
                tag_store.delete(conn, tag_id)
        return Response(status_code=204)

    @app.post("/api/tags/{tag_id}/transactions")
    def post_tag_transactions(tag_id: int, body: FingerprintsBody) -> AddedOut:
        with connection() as conn:
            tag = tag_of(conn, tag_id)
            known = {m.fingerprint for m in load_flow(conn)}
            missing = [fp for fp in body.fingerprints if fp not in known]
            if missing:
                raise HTTPException(404, t("web.unknown_transaction"))
            now = changelog.now().isoformat()
            with tracked(conn, "tag_add", tag_id, tag.name, body.fingerprints) as draft:
                added = tag_store.add(conn, tag_id, body.fingerprints, now)
            return AddedOut(added=added, entry_id=draft.entry_id)

    @app.delete("/api/tags/{tag_id}/transactions")
    def delete_tag_transactions(tag_id: int, body: FingerprintsBody) -> RemovedOut:
        with connection() as conn:
            found = detail_of(conn, tag_id)
            derived = {m.move.fingerprint for m in found.members if m.derived}
            if derived & set(body.fingerprints):
                raise HTTPException(400, t("web.tags.derived"))
            with tracked(conn, "tag_remove", tag_id, found.tag.name, body.fingerprints) as draft:
                removed = tag_store.remove(conn, tag_id, body.fingerprints)
            return RemovedOut(removed=removed, entry_id=draft.entry_id)

    def target_route(kind: str, tag_id: int, target_id: int, on: bool) -> TagOut:
        with connection() as conn:
            tag = tag_of(conn, tag_id)
            if on and (kind, target_id) not in tag_view.names(conn):
                raise HTTPException(404, t("web.tags.unknown_target"))
            now = changelog.now().isoformat()
            with tracked(conn, "tag_target", tag_id, tag.name):
                if on:
                    tag_store.add_target(conn, tag_id, kind, target_id, now)
                else:
                    tag_store.remove_target(conn, tag_id, kind, target_id)
            return tag_out(conn, tag_id)

    @app.put("/api/tags/{tag_id}/loans/{loan_id}")
    def put_tag_loan(tag_id: int, loan_id: int) -> TagOut:
        return target_route("loan", tag_id, loan_id, True)

    @app.delete("/api/tags/{tag_id}/loans/{loan_id}")
    def delete_tag_loan(tag_id: int, loan_id: int) -> TagOut:
        return target_route("loan", tag_id, loan_id, False)

    @app.put("/api/tags/{tag_id}/installments/{plan_id}")
    def put_tag_plan(tag_id: int, plan_id: int) -> TagOut:
        return target_route("installment", tag_id, plan_id, True)

    @app.delete("/api/tags/{tag_id}/installments/{plan_id}")
    def delete_tag_plan(tag_id: int, plan_id: int) -> TagOut:
        return target_route("installment", tag_id, plan_id, False)

    @app.post("/api/tags/{tag_id}/one-off")
    def post_tag_one_off(tag_id: int, body: OneOffBody) -> ChangedOut:
        """Mark (or unmark) every counted transaction of the tag as a one-off, in one entry."""
        with connection() as conn:
            found = detail_of(conn, tag_id)
            chosen = [
                m.move
                for m in found.members
                if m.counted
                and not m.move.fingerprint.startswith(_GROUP_MARK)
                and m.move.one_off != body.one_off
            ]
            fps = [m.fingerprint for m in chosen]
            with tracked(conn, "tag_one_off", tag_id, found.tag.name, fps) as draft:
                for fp in fps:
                    corrections.set_one_off(conn, fp, body.one_off)
            return ChangedOut(changed=len(fps), entry_id=draft.entry_id)

    @app.get("/api/tags/{tag_id}/candidates")
    def get_tag_candidates(
        tag_id: int,
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        category_id: int | None = None,
        merchant: str | None = None,
        account: str | None = None,
    ) -> CandidatesOut:
        with connection() as conn:
            found = detail_of(conn, tag_id)
            flow = load_flow(conn)
            known = catalog.load(conn)
            convert = tag_view.to_dop(rates.load(conn))
            first, last = found.total.first, found.total.last
            if start is None:
                start = first or today() - timedelta(days=DEFAULT_MONTHS_BACK)
            if end is None:
                end = last or today()
            wanted = None if category_id is None else known.by_id(category_id)
            needle = None if not merchant else fold(merchant)
            tagged = {m.move.fingerprint for m in found.members}
            rows = [
                m
                for m in flow
                if m.fingerprint
                and start <= m.day <= end
                and (wanted is None or m.ref == wanted.ref)
                and (needle is None or needle in fold(m.merchant))
                and (account is None or m.account == account)
            ]
            in_tag = {m.move.category for m in found.members if m.counted}
            pool = [m for m in rows if counts(m) and (not in_tag or m.category in in_tag)]
            dops = {m.fingerprint: convert(m) for m in rows}
            largest = sorted(pool, key=lambda m: dops[m.fingerprint] or 0, reverse=True)
            likely = {m.fingerprint for m in largest[:LIKELY_LARGEST]}
            likely |= {m.fingerprint for m in rows if m.one_off and counts(m)}
            items = [
                CandidateOut(
                    **row_fields(
                        m,
                        None if dops[m.fingerprint] is None else cents(dops[m.fingerprint]),
                        counts(m),
                    ),
                    likely=m.fingerprint in likely,
                    tagged=m.fingerprint in tagged,
                )
                for m in rows
            ]
            items.sort(key=lambda c: (not c.likely, c.day), reverse=False)
            return CandidatesOut(from_=start.isoformat(), to=end.isoformat(), items=items)
