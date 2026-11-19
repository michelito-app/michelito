"""Rutas de Recurrentes: la vista, las marcas, «Es recurrente…» desde una transacción y
«Unir con…» / «Separar».

Toda escritura queda en la bitácora (`changelog.track`) en la misma transacción SQLite: las
marcas con el tipo `recurrente` y las uniones con `recurrente_union`. La lógica está en
`analysis.recurring` (pura) y `analysis.recurring_marks` (base).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from finanzas.analysis import accounts as account_data
from finanzas.analysis import categories, changelog, rates
from finanzas.analysis import recurring as rec
from finanzas.analysis import recurring_marks as marks
from finanzas.analysis.spending import Movement
from finanzas.web import recurring as recurring_view
from finanzas.web import transactions
from finanzas.web.recurring_schemas import JoinBody, SeparateBody, TxRecurringBody, TxRecurringOut
from finanzas.web.schemas import MarkBody, RecurringOut

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]

MARK_KIND = "recurrente"
UNION_KIND = "recurrente_union"
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
        """Solo los gastos, con el mismo criterio que el Resumen (titulares incluidos)."""
        return tuple(m for m in load_flow(conn) if m.kind == "gasto")

    def overview(
        conn: sqlite3.Connection,
        month: str | None,
        movements: Sequence[Movement] | None = None,
        selected: frozenset[str] | None = None,
    ) -> recurring_view.Overview:
        if movements is None:
            movements = load_spending(conn)
        # El estado (activo o inactivo) se mide contra el último dato de todas las cuentas.
        as_of = max((m.day for m in movements), default=None)
        chosen = [m for m in movements if selected is None or m.account in selected]
        return recurring_view.build_overview(
            chosen,
            marks.load_for(conn, movements),
            rates.load(conn),
            month,
            as_of=as_of,
            unions=marks.load_unions(conn),
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
            # Las cuotas se cuentan desde el último dato importado, no desde el día del clic.
            as_of = max((m.day for m in movements), default=today())
            try:
                with (
                    conn,
                    changelog.track(
                        conn,
                        MARK_KIND,
                        "recurrente",
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
        """Antes de escribir sobre una serie con otros comercios: copia a su fila lo que hereda
        de ellos (si aún no tiene fila) y dice que su fila se conserva aunque quede vacía (un
        «sin marca» explícito manda sobre lo heredado). Va dentro del `track` del cambio: así
        deshacerlo vuelve a lo heredado."""
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
        """Solo la serie de la transacción (`recurring_view.series_view`), no toda la vista."""
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
            raise HTTPException(404, "transacción desconocida") from None

    @app.get("/api/transactions/{fingerprint}/recurring")
    def get_tx_recurring(fingerprint: str) -> TxRecurringOut:
        with connection() as conn:
            flow = load_flow(conn)
            target = find(flow, fingerprint)
            return tx_state(conn, [m for m in flow if m.kind == "gasto"], target)

    @app.post("/api/transactions/{fingerprint}/recurring")
    def post_tx_recurring(fingerprint: str, body: TxRecurringBody) -> TxRecurringOut:
        """«Es recurrente…»: marca la serie de la transacción (su comercio o su proveedor)."""
        with connection() as conn:
            flow = load_flow(conn)
            target = find(flow, fingerprint)
            problem = rec.mark_problem(target)
            if problem:
                raise HTTPException(422, problem)
            movements = [m for m in flow if m.kind == "gasto"]
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
                        "recurrente",
                        f"{key} · {currency}",
                        rec.display_name(key),
                        merchant=key,
                        fingerprints=_fingerprints(movements, unions, {key}, currency),
                    ),
                ):
                    keep = prepare(conn, movements, unions, key, currency)
                    marks.set_status(conn, key, currency, "confirmed", today(), keep=keep)
                    marks.set_cadence(conn, key, currency, body.cadence, today(), keep=keep)
                    # Sin grupo («Según su categoría») borra el elegido antes.
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
                "recurrente",
                ", ".join(sorted(plan)),
                subject,
                fingerprints=_fingerprints(movements, unions, keys),
            ),
        ):
            for merchant, target in plan.items():
                marks.set_union(conn, merchant, target)

    @app.post("/api/recurring/join")
    def post_recurring_join(body: JoinBody) -> RecurringOut:
        """«Unir con…»: los comercios de la serie `merchant` van en la serie `target`."""
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
        """«Separar»: el comercio deja la serie en que va y vuelve a ir solo."""
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
            subject = f"{body.merchant} · fuera de {names}"
            save_unions(
                conn, movements, unions, {body.merchant: target}, subject, before | {body.merchant}
            )
            return recurring_out(conn, movements)
