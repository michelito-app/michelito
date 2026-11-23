"""Recurring routes: the view, the marks, "Is recurring..." from a transaction and
"Join with..." / "Separate".

Every write is recorded in the change log (`changelog.track`) in the same SQLite transaction:
marks with kind `recurring` and unions with `recurring_union`. The logic lives in
`analysis.recurring` (pure) and `analysis.recurring_marks` (database).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from michelito.analysis import accounts as account_data
from michelito.analysis import categories, changelog, installment_store, rates
from michelito.analysis import recurring as rec
from michelito.analysis import recurring_marks as marks
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import installments as installments_view
from michelito.web import recurring as recurring_view
from michelito.web import transactions
from michelito.web.recurring_schemas import JoinBody, SeparateBody, TxRecurringBody, TxRecurringOut
from michelito.web.schemas import MarkBody, RecurringOut

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]

MARK_KIND = "recurring"
UNION_KIND = "recurring_union"
_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def _fingerprints(
    movements: Iterable[Movement], unions: dict[str, str], keys: set[str], currency: str = ""
) -> list[str]:
    return [
        m.fingerprint
        for m in movements
        if rec.series_key(m, unions) in keys and (not currency or m.currency == currency)
    ]


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    parse_accounts: ParseAccounts,
    today: Callable[[], date],
) -> None:
    def load_spending(conn: sqlite3.Connection) -> tuple[Movement, ...]:
        """Only expenses, with the same criteria as the Summary (holders included)."""
        return tuple(m for m in load_flow(conn) if m.kind == "expense")

    def overview(
        conn: sqlite3.Connection,
        month: str | None,
        movements: Sequence[Movement] | None = None,
        selected: frozenset[str] | None = None,
    ) -> recurring_view.Overview:
        if movements is None:
            movements = load_spending(conn)
        # Status (active or inactive) is measured against the latest data of all accounts.
        as_of = max((m.day for m in movements), default=None)
        # A plan's installments are forecast by the plan, never as a recurring series too.
        planned = installment_store.taken(conn)
        chosen = [
            m
            for m in movements
            if (selected is None or m.account in selected) and m.fingerprint not in planned
        ]
        by_month = rates.load(conn)
        found = recurring_view.build_overview(
            chosen,
            marks.load_for(conn, movements),
            by_month,
            month,
            as_of=as_of,
            unions=marks.load_unions(conn),
        )
        return recurring_view.with_plans(
            found, installments_view.forecast(conn, movements, by_month, selected, as_of)
        )

    def recurring_out(
        conn: sqlite3.Connection, movements: Sequence[Movement] | None = None
    ) -> RecurringOut:
        return RecurringOut.of(overview(conn, None, movements))

    @app.get("/api/recurring")
    def get_recurring(
        month: Annotated[str | None, Query(pattern=_MONTH_PATTERN)] = None,
        accounts: Annotated[str | None, Query(max_length=2000)] = None,
    ) -> RecurringOut:
        with connection() as conn:
            selected = parse_accounts(accounts, account_data.account_infos(conn))
            return RecurringOut.of(overview(conn, month, selected=selected))

    @app.put("/api/recurring/mark")
    def put_recurring_mark(body: MarkBody) -> RecurringOut:
        with connection() as conn:
            movements = load_spending(conn)
            unions = marks.load_unions(conn)
            # Installments count from the latest imported data, not from the day of the click.
            as_of = max((m.day for m in movements), default=today())
            try:
                with (
                    conn,
                    changelog.track(
                        conn,
                        MARK_KIND,
                        "recurring",
                        f"{body.merchant} · {body.currency}",
                        rec.display_name(body.merchant),
                        merchant=body.merchant,
                        fingerprints=_fingerprints(
                            movements, unions, {body.merchant}, body.currency
                        ),
                    ),
                ):
                    keep = prepare(conn, movements, unions, body.merchant, body.currency)
                    key, currency = body.merchant, body.currency
                    marks.set_status(conn, key, currency, body.status, today(), keep=keep)
                    if "installments_left" in body.model_fields_set:
                        marks.set_installments(
                            conn, key, currency, body.installments_left, as_of, keep=keep
                        )
                    if "group" in body.model_fields_set:
                        marks.set_group(conn, key, currency, body.group, today(), keep=keep)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return recurring_out(conn, movements)

    def prepare(
        conn: sqlite3.Connection,
        movements: Sequence[Movement],
        unions: dict[str, str],
        key: str,
        currency: str,
    ) -> bool:
        """Before writing to a series with other merchants: copies into its row what it inherits
        from them (if it has no row yet) and says its row is kept even when empty (an explicit
        "no mark" overrides the inherited one). Runs inside the change's `track`, so undoing it
        goes back to the inherited marks."""
        names = rec.members(movements, unions).get(key, frozenset())
        if not names - {key}:
            return False
        saved = marks.load_for(conn, movements)
        if (key, currency) not in saved:
            found = marks.inherited(saved, key, currency, names)
            if found is not None:
                marks.materialize(conn, key, currency, found)
        return True

    def tx_state(
        conn: sqlite3.Connection, movements: Sequence[Movement], target: Movement
    ) -> TxRecurringOut:
        """Only the transaction's series (`recurring_view.series_view`), not the whole view."""
        unions = marks.load_unions(conn)
        key = rec.series_key(target, unions) or target.merchant
        problem = rec.mark_problem(target)
        found = None
        if not problem and movements:
            view = recurring_view.series_view(
                movements,
                marks.load_for(conn, movements),
                rates.load(conn),
                key,
                target.currency,
                as_of=max(m.day for m in movements),
                unions=unions,
            )
            found = view if view is not None and view.mark != "dismissed" else None
        return TxRecurringOut(
            eligible=not problem,
            reason=problem,
            key=key,
            name=rec.display_name(key),
            currency=target.currency,
            recurring=found is not None,
            mark=None if found is None else found.mark,
            group="" if found is None else found.group,
            loan=target.ref == categories.LOANS,
        )

    def find(movements: Sequence[Movement], fingerprint: str) -> Movement:
        try:
            return transactions.find(movements, fingerprint)
        except LookupError:
            raise HTTPException(404, t("web.unknown_transaction")) from None

    @app.get("/api/transactions/{fingerprint}/recurring")
    def get_tx_recurring(fingerprint: str) -> TxRecurringOut:
        with connection() as conn:
            flow = load_flow(conn)
            target = find(flow, fingerprint)
            return tx_state(conn, [m for m in flow if m.kind == "expense"], target)

    @app.post("/api/transactions/{fingerprint}/recurring")
    def post_tx_recurring(fingerprint: str, body: TxRecurringBody) -> TxRecurringOut:
        """ "Is recurring...": marks the transaction's series (its merchant or its provider)."""
        with connection() as conn:
            flow = load_flow(conn)
            target = find(flow, fingerprint)
            problem = rec.mark_problem(target)
            if problem:
                raise HTTPException(422, problem)
            movements = [m for m in flow if m.kind == "expense"]
            unions = marks.load_unions(conn)
            key = rec.series_key(target, unions) or target.merchant
            currency = target.currency
            as_of = max((m.day for m in movements), default=today())
            try:
                with (
                    conn,
                    changelog.track(
                        conn,
                        MARK_KIND,
                        "recurring",
                        f"{key} · {currency}",
                        rec.display_name(key),
                        merchant=key,
                        fingerprints=_fingerprints(movements, unions, {key}, currency),
                    ),
                ):
                    keep = prepare(conn, movements, unions, key, currency)
                    marks.set_status(conn, key, currency, "confirmed", today(), keep=keep)
                    marks.set_cadence(conn, key, currency, body.cadence, today(), keep=keep)
                    # No group ("By its category") clears the one chosen before.
                    marks.set_group(conn, key, currency, body.group, today(), keep=keep)
                    if body.installments_left is not None:
                        marks.set_installments(
                            conn, key, currency, body.installments_left, as_of, keep=keep
                        )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return tx_state(conn, movements, target)

    def save_unions(
        conn: sqlite3.Connection,
        movements: Sequence[Movement],
        unions: dict[str, str],
        plan: dict[str, str | None],
        subject: str,
        keys: set[str],
    ) -> None:
        with (
            conn,
            changelog.track(
                conn,
                UNION_KIND,
                "recurring",
                ", ".join(sorted(plan)),
                subject,
                fingerprints=_fingerprints(movements, unions, keys),
            ),
        ):
            for merchant, target in plan.items():
                marks.set_union(conn, merchant, target)

    @app.post("/api/recurring/join")
    def post_recurring_join(body: JoinBody) -> RecurringOut:
        """ "Join with...": the merchants of series `merchant` go into series `target`."""
        with connection() as conn:
            movements = load_spending(conn)
            unions = marks.load_unions(conn)
            try:
                plan = rec.join_plan(
                    rec.members(movements, unions), body.merchant, body.target, unions
                )
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from None
            except rec.JoinError as exc:
                raise HTTPException(422, str(exc)) from None
            subject = f"{rec.display_name(body.merchant)} → {rec.display_name(body.target)}"
            save_unions(conn, movements, unions, dict(plan), subject, {body.merchant, body.target})
            return recurring_out(conn, movements)

    @app.post("/api/recurring/separate")
    def post_recurring_separate(body: SeparateBody) -> RecurringOut:
        """ "Separate": the merchant leaves its current series and goes back to its own."""
        with connection() as conn:
            movements = load_spending(conn)
            unions = marks.load_unions(conn)
            try:
                target = rec.separate_plan(movements, unions, body.merchant)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from None
            except rec.JoinError as exc:
                raise HTTPException(422, str(exc)) from None
            before = {
                key
                for m in movements
                if m.merchant == body.merchant and (key := rec.series_key(m, unions)) is not None
            }
            names = ", ".join(sorted(rec.display_name(k) for k in before))
            subject = t("web.recurring.separated", merchant=body.merchant, series=names)
            save_unions(
                conn, movements, unions, {body.merchant: target}, subject, before | {body.merchant}
            )
            return recurring_out(conn, movements)
