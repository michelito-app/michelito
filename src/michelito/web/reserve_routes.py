"""Reserve routes: the list with its suggestions, create, edit and delete, link expenses (one
from the detail view or several with multi-select), remove a link and dismiss a suggestion.
Everything requires `X-Michelito` (checked by `web.app`), is recorded in the change log
(`reserve`, `reserve_expense`, `reserve_dismissal`) and can be undone.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Response

from michelito.analysis import accounts as account_data
from michelito.analysis import changelog, links, reserve_store, reserves
from michelito.analysis.reserves import Reserve, month_name
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import budget as budget_view
from michelito.web import edit_log
from michelito.web.budget_routes import load_inputs
from michelito.web.budget_schemas import (
    CreatedOut,
    DismissBody,
    EntryOut,
    MembersBody,
    MembersOut,
    ReserveBody,
    ReserveOptionOut,
    ReserveOut,
    ReservePatch,
    ReserveRefOut,
    ReservesOut,
    SkippedOut,
    SuggestionOut,
    TxReserveOut,
)

AccountKeys = Annotated[str | None, Query(max_length=2000)]
Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]

SKIP_MESSAGES = {
    "linked": t("web.reserve.skip.linked"),
    "not_expense": t("web.reserve.skip.not_expense"),
    "unknown": t("web.reserve.skip.unknown"),
}


def plan_text(reserve: Reserve) -> str:
    """The reserve's plan as the change log shows it: amount, then once / every year in a month /
    every 6 months from a month, plus a "several expenses" suffix when it groups several."""
    amount = t("web.reserve.plan.amount", amount=int(reserve.amount))
    if reserve.every_months is None:
        when = t("web.reserve.plan.once", month=reserve.due_month)
    elif reserve.every_months == 12:
        when = t("web.reserve.plan.yearly", month=month_name(reserve.due_month))
    else:
        when = t("web.reserve.plan.every", months=reserve.every_months, month=reserve.due_month)
    plan = t("web.reserve.plan.text", amount=amount, when=when)
    return plan + (t("web.reserve.plan.multiple") if reserve.multiple else "")


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (links.AlreadyLinked, sqlite3.IntegrityError) as exc:
        detail = str(exc) if isinstance(exc, links.AlreadyLinked) else ""
        raise HTTPException(409, detail or t("web.already_linked")) from None
    except ValueError as exc:  # ReserveError, CategoryError
        raise HTTPException(422, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc) or t("web.reserve.unknown")) from None


def skip_reason(move: Movement | None, found: links.Links) -> str | None:
    if move is None:
        return "unknown"
    if move.kind != "expense" or move.amount <= 0:
        return "not_expense"
    if found.is_linked(move.fingerprint):
        return "linked"
    return None


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    parse_accounts: ParseAccounts,
    today: Callable[[], date],
) -> None:
    def track(
        conn: sqlite3.Connection,
        kind: str,
        reserve: Reserve,
        before: str,
        after: str | None = None,
        fingerprints: Sequence[str] = (),
    ) -> AbstractContextManager[changelog.Draft]:
        return changelog.track(
            conn,
            kind,
            "link",
            str(reserve.id),
            reserve.name,
            before=before,
            after=after,
            fingerprints=fingerprints,
        )

    def view_of(conn: sqlite3.Connection, reserve_id: int) -> ReserveOut:
        inputs = load_inputs(conn, load_flow(conn), today())
        found = next(v for v in budget_view.reserve_views(inputs) if v.reserve.id == reserve_id)
        return ReserveOut.of(found)

    @app.get("/api/reserves")
    def get_reserves(accounts: AccountKeys = None) -> ReservesOut:
        """The reserves (next due month, monthly contribution, this year) and the suggestions."""
        with connection() as conn:
            flow = load_flow(conn)
            infos = account_data.account_infos(conn)
            inputs = load_inputs(
                conn, flow, today(), parse_accounts(accounts, infos), with_marks=True
            )
        names = {c.id: c.name for c in inputs.known.items}
        return ReservesOut(
            items=[ReserveOut.of(v) for v in budget_view.reserve_views(inputs)],
            suggestions=[
                SuggestionOut.of(s, names.get(s.category_id, ""))
                for s in budget_view.suggestions(inputs)
            ],
            monthly_cents=int(budget_view.monthly_total(inputs) * 100),
        )

    @app.get("/api/reserves/options")
    def get_reserve_options() -> list[ReserveOptionOut]:
        """Only each reserve's id and name (the multi-select picker)."""
        with connection() as conn:
            found = reserve_store.load(conn)
        return [ReserveOptionOut(id=r.id, name=r.name) for r in found]

    @app.post("/api/reserves", status_code=201)
    def post_reserve(body: ReserveBody) -> CreatedOut:
        """A new reserve (by hand or from a suggestion: `source`, its key)."""
        with (
            connection() as conn,
            _errors(),
            conn,
            changelog.track(conn, "reserve", "link", "0", body.name, before="—") as draft,
        ):
            found = reserve_store.create(
                conn,
                name=body.name,
                amount=Decimal(body.amount_cents) / 100,
                category_id=body.category_id,
                due_month=body.due_month,
                every_months=body.every_months,
                multiple=body.multiple,
                source=body.source,
                start_month=today().strftime("%Y-%m"),
            )
            created = reserve_store.get(conn, found)
            draft.target, draft.subject = str(found), created.name
            draft.after = plan_text(created)
        return CreatedOut(id=found, entry_id=draft.entry_id)

    @app.patch("/api/reserves/{reserve_id}")
    def patch_reserve(reserve_id: int, body: ReservePatch) -> ReserveOut:
        with connection() as conn, _errors():
            current = reserve_store.get(conn, reserve_id)
            every: object = reserve_store._UNSET  # noqa: SLF001
            if body.once:
                every = None
            elif body.every_months is not None:
                every = body.every_months
            with conn, track(conn, "reserve", current, before=plan_text(current)) as draft:
                reserve_store.update(
                    conn,
                    reserve_id,
                    name=body.name,
                    amount=None if body.amount_cents is None else Decimal(body.amount_cents) / 100,
                    category_id=body.category_id,
                    due_month=body.due_month,
                    every_months=every,
                    multiple=body.multiple,
                )
                after = reserve_store.get(conn, reserve_id)
                draft.subject, draft.after = after.name, plan_text(after)
            return view_of(conn, reserve_id)

    @app.delete("/api/reserves/{reserve_id}", status_code=204)
    def delete_reserve(reserve_id: int) -> Response:
        """Deletes the reserve; its expenses go back to their category's cap."""
        with connection() as conn, _errors():
            current = reserve_store.get(conn, reserve_id)
            with (
                conn,
                track(
                    conn,
                    "reserve",
                    current,
                    before=plan_text(current),
                    after=t("web.deleted"),
                ),
            ):
                reserve_store.delete(conn, reserve_id)
        return Response(status_code=204)

    @app.post("/api/reserves/{reserve_id}/members")
    def post_members(reserve_id: int, body: MembersBody) -> MembersOut:
        """Links one or several expenses (those that are not expenses or are already in a link are
        skipped, with their reason). A single change-log entry."""
        with connection() as conn, _errors():
            current = reserve_store.get(conn, reserve_id)
            flow = {m.fingerprint: m for m in load_flow(conn)}
            found = links.load(conn)
            applied: list[Movement] = []
            skipped: list[SkippedOut] = []
            for fp in dict.fromkeys(body.fingerprints):
                reason = skip_reason(flow.get(fp), found)
                if reason is None:
                    applied.append(flow[fp])
                else:
                    message = SKIP_MESSAGES[reason]
                    skipped.append(SkippedOut(fingerprint=fp, reason=reason, message=message))
            single = applied[0] if len(applied) == 1 else None
            prints = [m.fingerprint for m in applied]
            tracker: AbstractContextManager[changelog.Draft]
            if single is not None:
                tracker = changelog.track(
                    conn,
                    "reserve_expense",
                    "transaction",
                    single.fingerprint,
                    edit_log.subject(single),
                    before="—",
                    after=t("web.reserve.covered_by", name=current.name),
                    merchant=single.merchant,
                    fingerprints=prints,
                )
            else:
                tracker = track(
                    conn,
                    "reserve_expense",
                    current,
                    t("web.reserve.batch_before", count=len(applied)),
                    t("web.reserve.batch_after", count=len(applied), name=current.name),
                    prints,
                )
            with conn, tracker as draft:
                for move in applied:
                    reserve_store.add_member(conn, reserve_id, move.fingerprint)
        return MembersOut(
            applied=[m.fingerprint for m in applied], skipped=skipped, entry_id=draft.entry_id
        )

    @app.delete("/api/reserves/{reserve_id}/members/{fingerprint}")
    def delete_member(reserve_id: int, fingerprint: str) -> EntryOut:
        """Removes the link: the expense goes back to its category's cap."""
        with connection() as conn, _errors():
            current = reserve_store.get(conn, reserve_id)
            move = next((m for m in load_flow(conn) if m.fingerprint == fingerprint), None)
            with (
                conn,
                changelog.track(
                    conn,
                    "reserve_expense",
                    "transaction",
                    fingerprint,
                    fingerprint if move is None else edit_log.subject(move),
                    before=t("web.reserve.covered_by", name=current.name),
                    after=t("web.reserve.back_to_cap"),
                    merchant=None if move is None else move.merchant,
                    fingerprints=[fingerprint],
                ) as draft,
            ):
                reserve_store.remove_member(conn, reserve_id, fingerprint)
        return EntryOut(entry_id=draft.entry_id)

    @app.post("/api/reserve-suggestions/dismiss")
    def post_dismiss(body: DismissBody) -> EntryOut:
        """Dismisses a suggestion for good (by its key)."""
        with connection() as conn, _errors():
            key, name = body.key.strip(), (body.name or "").strip() or body.key.strip()
            with (
                conn,
                changelog.track(
                    conn,
                    "reserve_dismissal",
                    "link",
                    key,
                    name,
                    before=t("web.reserve.suggested"),
                    after=t("web.reserve.dismissed"),
                ) as draft,
            ):
                reserve_store.dismiss(conn, key)
        return EntryOut(entry_id=draft.entry_id)

    @app.get("/api/transactions/{fingerprint}/reserve")
    def get_tx_reserve(fingerprint: str) -> TxReserveOut:
        """The detail view's Reserve section: the reserve covering it or the ones it can link to."""
        with connection() as conn:
            flow = load_flow(conn)
            move = next((m for m in flow if m.fingerprint == fingerprint), None)
            if move is None:
                raise HTTPException(404, t("web.unknown_transaction"))
            inputs = load_inputs(conn, flow, today(), with_marks=True)
            found = links.load(conn)
        return tx_reserve(inputs, found, move)

    def tx_reserve(inputs: budget_view.Inputs, found: links.Links, move: Movement) -> TxReserveOut:
        names = {c.id: c.name for c in inputs.known.items}

        def ref(r: Reserve, suggested: bool = False) -> ReserveRefOut:
            return ReserveRefOut(
                id=r.id,
                name=r.name,
                category=names.get(r.category_id, ""),
                next_due=reserves.next_due(r, inputs.current),
                suggested=suggested,
            )

        owner = found.reserve_for(move.fingerprint)
        if owner is not None:
            current = next((r for r in inputs.reserves if r.id == owner), None)
            return TxReserveOut(
                reserve=None if current is None else ref(current),
                options=[],
                can_link=False,
                reason="",
            )
        reason = skip_reason(move, found)
        hints = budget_view.link_hints(inputs, found.fingerprints)
        hinted = hints.get(move.fingerprint)
        category = budget_view.category_id(inputs.known, move)
        options = sorted(
            inputs.reserves,
            key=lambda r: (
                hinted is None or r.id != hinted.id,
                r.category_id != category,
                r.name,
            ),
        )
        return TxReserveOut(
            reserve=None,
            options=[ref(r, hinted is not None and r.id == hinted.id) for r in options],
            can_link=reason is None and bool(options),
            reason="" if reason is None else SKIP_MESSAGES[reason],
        )
