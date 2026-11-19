"""Rutas de las reservas: la lista con sus sugerencias, crear, editar y borrar, vincular gastos
(uno desde el detalle o varios con la selección múltiple), quitar un vínculo y descartar una
sugerencia. Todo con `X-Finanzas` (lo revisa `web.app`), en la bitácora (`reserva`,
`reserva_gasto`, `reserva_descarte`) y deshacible.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Response

from finanzas.analysis import accounts as account_data
from finanzas.analysis import changelog, links, reserve_store, reserves
from finanzas.analysis.reserves import Reserve, month_name
from finanzas.analysis.spending import Movement
from finanzas.web import budget as budget_view
from finanzas.web import edit_log
from finanzas.web.budget_routes import load_inputs
from finanzas.web.budget_schemas import (
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
    "vinculo": "ya está en un vínculo (otra reserva, un grupo, una inversión…)",
    "no_gasto": "no es un gasto",
    "desconocida": "no existe",
}


def plan_text(reserve: Reserve) -> str:
    """«RD$ 3,500 · cada año en enero», «… · cada 6 meses desde 2026-03» o «… · una vez, en
    2026-12» (con «· varios gastos» si junta varios)."""
    amount = f"RD$ {int(reserve.amount):,}"
    if reserve.every_months is None:
        when = f"una vez, en {reserve.due_month}"
    elif reserve.every_months == 12:
        when = f"cada año en {month_name(reserve.due_month)}"
    else:
        when = f"cada {reserve.every_months} meses desde {reserve.due_month}"
    return f"{amount} · {when}" + (" · varios gastos" if reserve.multiple else "")


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (links.AlreadyLinked, sqlite3.IntegrityError) as exc:
        detail = str(exc) if isinstance(exc, links.AlreadyLinked) else ""
        raise HTTPException(409, detail or "la transacción ya está en otro vínculo") from None
    except ValueError as exc:  # ReserveError, CategoryError
        raise HTTPException(422, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc) or "reserva desconocida") from None


def skip_reason(move: Movement | None, found: links.Links) -> str | None:
    if move is None:
        return "desconocida"
    if move.kind != "gasto" or move.amount <= 0:
        return "no_gasto"
    if found.is_linked(move.fingerprint):
        return "vinculo"
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
            "vinculo",
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
        """Las reservas (próximo vencimiento, aporte mensual, este año) y las sugerencias."""
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
        """Solo el id y el nombre de cada reserva (el selector de la selección múltiple)."""
        with connection() as conn:
            found = reserve_store.load(conn)
        return [ReserveOptionOut(id=r.id, name=r.name) for r in found]

    @app.post("/api/reserves", status_code=201)
    def post_reserve(body: ReserveBody) -> CreatedOut:
        """Una reserva nueva (a mano o desde una sugerencia: `source`, su clave)."""
        with (
            connection() as conn,
            _errors(),
            conn,
            changelog.track(conn, "reserva", "vinculo", "0", body.name, before="—") as draft,
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
            with conn, track(conn, "reserva", current, before=plan_text(current)) as draft:
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
        """Borra la reserva; sus gastos vuelven al tope de su categoría."""
        with connection() as conn, _errors():
            current = reserve_store.get(conn, reserve_id)
            with conn, track(conn, "reserva", current, before=plan_text(current), after="borrada"):
                reserve_store.delete(conn, reserve_id)
        return Response(status_code=204)

    @app.post("/api/reserves/{reserve_id}/members")
    def post_members(reserve_id: int, body: MembersBody) -> MembersOut:
        """Vincula uno o varios gastos (se omiten, con su motivo, los que no son gastos o ya
        están en un vínculo). Una sola entrada en la bitácora."""
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
                    "reserva_gasto",
                    "transaccion",
                    single.fingerprint,
                    edit_log.subject(single),
                    before="—",
                    after=f"cubierto por «{current.name}»",
                    merchant=single.merchant,
                    fingerprints=prints,
                )
            else:
                tracker = track(
                    conn,
                    "reserva_gasto",
                    current,
                    f"{len(applied)} gastos sin reserva",
                    f"{len(applied)} gastos cubiertos por «{current.name}»",
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
        """Quita el vínculo: el gasto vuelve al tope de su categoría."""
        with connection() as conn, _errors():
            current = reserve_store.get(conn, reserve_id)
            move = next((m for m in load_flow(conn) if m.fingerprint == fingerprint), None)
            with (
                conn,
                changelog.track(
                    conn,
                    "reserva_gasto",
                    "transaccion",
                    fingerprint,
                    fingerprint if move is None else edit_log.subject(move),
                    before=f"cubierto por «{current.name}»",
                    after="vuelve al tope",
                    merchant=None if move is None else move.merchant,
                    fingerprints=[fingerprint],
                ) as draft,
            ):
                reserve_store.remove_member(conn, reserve_id, fingerprint)
        return EntryOut(entry_id=draft.entry_id)

    @app.post("/api/reserve-suggestions/dismiss")
    def post_dismiss(body: DismissBody) -> EntryOut:
        """Descarta una sugerencia para siempre (por su clave)."""
        with connection() as conn, _errors():
            key, name = body.key.strip(), (body.name or "").strip() or body.key.strip()
            with (
                conn,
                changelog.track(
                    conn,
                    "reserva_descarte",
                    "vinculo",
                    key,
                    name,
                    before="sugerida",
                    after="descartada",
                ) as draft,
            ):
                reserve_store.dismiss(conn, key)
        return EntryOut(entry_id=draft.entry_id)

    @app.get("/api/transactions/{fingerprint}/reserve")
    def get_tx_reserve(fingerprint: str) -> TxReserveOut:
        """La sección «Reserva» del detalle: la que lo cubre o a cuáles se puede vincular."""
        with connection() as conn:
            flow = load_flow(conn)
            move = next((m for m in flow if m.fingerprint == fingerprint), None)
            if move is None:
                raise HTTPException(404, "transacción desconocida")
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
