"""Routes of "To review": the month's items, the history and "I already reviewed it"."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from michelito.analysis import accounts as account_data
from michelito.analysis import catalog, changelog, links, rates, review_marks
from michelito.analysis import one_off_dismissals as dismissals
from michelito.analysis import recurring_marks as marks
from michelito.analysis.review import Kind
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import budget as budget_view
from michelito.web import edit_log, log_routes, summary
from michelito.web import review as review_view
from michelito.web.budget_routes import load_inputs
from michelito.web.review_schemas import ReviewBody, ReviewItemOut, ReviewMarkOut

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]


def register(
    app: FastAPI, connection: Connection, load_flow: LoadFlow, parse_accounts: ParseAccounts
) -> None:
    def context(
        conn: sqlite3.Connection, flow: Sequence[Movement], accounts: str | None
    ) -> review_view.Context:
        infos = account_data.account_infos(conn)
        known = catalog.load(conn)
        linked = links.load(conn)
        rules = [
            (s, found.name)
            for s in log_routes.rule_suggestions(conn, flow)
            if (found := known.by_id(s.category_id)) is not None
        ]
        return review_view.Context(
            flow=flow,
            accounts=infos,
            rates=rates.load(conn),
            marks=marks.load_for(conn, flow),
            unions=marks.load_unions(conn),
            reviewed=review_marks.load(conn),
            dismissed=dismissals.load(conn),
            selected=parse_accounts(accounts, infos),
            links=linked,
            rules=rules,
            # Link suggestions do not depend on today's date (only on the due dates).
            reserve_hints=budget_view.link_hints(
                load_inputs(conn, flow, date.today(), with_marks=True), linked.fingerprints
            ),
        )

    @app.get("/api/review")
    def get_review(
        month: Annotated[str, Query(pattern=_MONTH_PATTERN)],
        accounts: Annotated[str | None, Query(max_length=2000)] = None,
        reviewed: bool = False,
    ) -> list[ReviewItemOut]:
        """The month's items to review; with `reviewed=true` also the ones already reviewed."""
        with connection() as conn:
            flow = load_flow(conn)
            views = review_view.month_items(context(conn, flow, accounts), month)
        return [ReviewItemOut.of(v) for v in views if reviewed or not v.item.reviewed]

    @app.get("/api/review/history")
    def get_review_history(
        accounts: Annotated[str | None, Query(max_length=2000)] = None,
        kind: Kind | None = None,
    ) -> list[ReviewItemOut]:
        """Pending and reviewed items of the latest months with data, most recent first."""
        with connection() as conn:
            flow = load_flow(conn)
            ctx = context(conn, flow, accounts)
            options = summary.month_options(flow, ctx.accounts, ctx.selected)
            months = [o.month for o in options[: review_view.HISTORY_MONTHS]]
            views = review_view.history(ctx, months, kind)
        return [ReviewItemOut.of(v) for v in views]

    @app.put("/api/review/{kind}/{fingerprint}")
    def put_review(kind: Kind, fingerprint: str, body: ReviewBody) -> ReviewMarkOut:
        """Marks "I already reviewed it" (or undoes it). On a one-off it is "Not a one-off"; on a
        possible rule, "Dismiss" (forever: that category is not proposed for the merchant
        again). It goes into the change log."""
        with connection() as conn:
            flow = load_flow(conn)
            target = next((m for m in flow if m.fingerprint == fingerprint), None)
            if target is None:
                raise HTTPException(404, t("web.unknown_transaction"))
            if kind == "possible_rule":
                discard_rule(conn, target, body.reviewed, flow)
                return ReviewMarkOut(kind=kind, fingerprint=fingerprint, reviewed=body.reviewed)
            with (
                conn,
                changelog.track(
                    conn,
                    "reviewed",
                    "transaction",
                    fingerprint,
                    edit_log.subject(target),
                    before=t("web.review.reviewed") if not body.reviewed else t("web.to_review"),
                    after=t("web.review.reviewed") if body.reviewed else t("web.to_review"),
                    merchant=target.merchant,
                    fingerprints=[fingerprint],
                ),
            ):
                if kind == "one_off":
                    dismissals.set_dismissed(conn, fingerprint, body.reviewed)
                else:
                    review_marks.set_reviewed(conn, fingerprint, kind, body.reviewed)
        return ReviewMarkOut(kind=kind, fingerprint=fingerprint, reviewed=body.reviewed)

    def discard_rule(
        conn: sqlite3.Connection, target: Movement, reviewed: bool, flow: Sequence[Movement]
    ) -> None:
        """Dismisses the rule proposed for the merchant (or, with `reviewed=false`, allows
        proposing all of them again)."""
        merchant = target.merchant
        found = next(
            (s for s in log_routes.rule_suggestions(conn, flow) if s.merchant == merchant), None
        )
        if reviewed and found is None:
            raise HTTPException(404, t("web.review.no_rule"))
        with (
            conn,
            changelog.track(
                conn,
                "reviewed",
                "merchant",
                merchant,
                merchant,
                before=t("web.review.rule_proposed")
                if reviewed
                else t("web.review.rule_discarded"),
                after=t("web.review.rule_discarded") if reviewed else t("web.review.rule_allowed"),
                merchant=merchant,
                fingerprints=() if found is None else found.fingerprints,
            ),
        ):
            if found is not None and reviewed:
                changelog.dismiss_rule(conn, merchant, found.category_id)
            elif not reviewed:
                conn.execute("DELETE FROM rule_dismissals WHERE merchant = ?", (merchant,))
