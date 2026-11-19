"""Rutas de la caja fuerte (`/api/cash-box`): saldo y movimientos, anotar, editar y borrar uno a
mano, marcar o desmarcar un retiro guardado y vincular o desvincular un depósito.

Las cuentas están en `analysis.cash_box` y lo guardado en `analysis.cash_box_store`; aquí se valida
el pedido y se escribe en una transacción. Lo anotado y borrado devuelve la caja al día; marcar
un retiro o un depósito devuelve la transacción (como `PATCH /api/transactions/{huella}`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

from finanzas.analysis import accounts as account_data
from finanzas.analysis import cash_box, cash_box_store, catalog, changelog, links, rates, shared
from finanzas.analysis.accounts import BANK_KINDS, CASH_BOX_KEY
from finanzas.analysis.spending import Movement
from finanzas.web import edit_log
from finanzas.web.cash_box_schemas import CashBoxOut, DepositBody, EntryBody, EntryPatch
from finanzas.web.schemas import TxOut

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
TxOutFor = Callable[[sqlite3.Connection, str, str], TxOut]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (links.AlreadyLinked, sqlite3.IntegrityError) as exc:  # otra pestaña lo enlazó
        detail = str(exc) if isinstance(exc, links.AlreadyLinked) else ""
        raise HTTPException(409, detail or "la transacción ya está en otro vínculo") from None
    except ValueError as exc:  # CashBoxError, LinkError y una nota demasiado larga
        raise HTTPException(422, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc) or "movimiento desconocido") from None


def _money(cents: int | None) -> Decimal | None:
    return None if cents is None else Decimal(cents) / 100


def register(
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    tx_out: TxOutFor,
    today: Callable[[], date],
) -> None:
    def box_out(conn: sqlite3.Connection) -> CashBoxOut:
        flow = load_flow(conn)
        found = links.load(conn)
        box = next((b for b in found.cash_boxes if b.account_key == CASH_BOX_KEY), None)
        by_month = rates.load(conn)
        state = cash_box.state_of(box, cash_box_store.load_entries(conn), flow, by_month)
        labels = {a.key: a.label for a in account_data.account_infos(conn)}
        ids = {c.ref: c.id for c in catalog.load(conn).items}
        states = shared.states(flow, found, by_month)
        groups = {
            line.fingerprint: states[owner.id].title
            for line in state.lines
            if (owner := found.shared_for(line.fingerprint)) is not None and owner.id in states
        }
        return CashBoxOut.of(state, box is not None, labels, ids, groups)

    def movement(conn: sqlite3.Connection, fingerprint: str) -> tuple[Movement, links.Links]:
        found = next((m for m in load_flow(conn) if m.fingerprint == fingerprint), None)
        if found is None:
            raise HTTPException(404, "transacción desconocida")
        return found, links.load(conn)

    def track_tx(
        conn: sqlite3.Connection, fingerprint: str, target: Movement | None
    ) -> AbstractContextManager[changelog.Draft]:
        """La entrada «caja fuerte» de un retiro guardado o un depósito."""
        return changelog.track(
            conn,
            "caja_fuerte",
            "transaccion",
            fingerprint,
            fingerprint if target is None else edit_log.subject(target),
            merchant=None if target is None else target.merchant,
            fingerprints=[fingerprint],
        )

    def track_entry(
        conn: sqlite3.Connection, entry_id: int | None
    ) -> AbstractContextManager[changelog.Draft]:
        """La entrada «movimiento de la caja» (anotar, cambiar o borrar uno a mano)."""
        code = "" if entry_id is None else cash_box.entry_fingerprint(entry_id)
        return changelog.track(conn, "caja_movimiento", "caja", code, "Caja fuerte")

    def unmark(fingerprint: str, role: str) -> Response:
        """Quita la marca aunque el movimiento ya no esté en el flujo (un estado que cambió): la
        transacción al día si sigue, 204 si no."""
        with connection() as conn:
            before = next((m for m in load_flow(conn) if m.fingerprint == fingerprint), None)
            with _errors(), conn, track_tx(conn, fingerprint, before):
                cash_box_store.remove(conn, fingerprint, role)
            target = next((m for m in load_flow(conn) if m.fingerprint == fingerprint), None)
            if target is None:
                return Response(status_code=204)
            return JSONResponse(tx_out(conn, fingerprint, target.month).model_dump())

    @app.get("/api/cash-box")
    def get_cash_box() -> CashBoxOut:
        with connection() as conn:
            return box_out(conn)

    @app.post("/api/cash-box/entries", status_code=201)
    def post_entry(body: EntryBody) -> CashBoxOut:
        """Anota un saldo inicial, una entrada o una salida (un saldo negativo se permite: la
        respuesta lo trae en `negative`)."""
        with connection() as conn:
            with _errors(), conn, track_entry(conn, None) as draft:
                made = cash_box_store.add_entry(
                    conn,
                    body.kind,
                    body.day,
                    Decimal(body.amount_cents) / 100,
                    body.currency,
                    category=body.category_id,
                    note=body.note,
                    today=today(),
                )
                draft.target = cash_box.entry_fingerprint(made)
            return box_out(conn)

    @app.put("/api/cash-box/entries/{entry_id}")
    def put_entry(entry_id: int, body: EntryPatch) -> CashBoxOut:
        with connection() as conn:
            with _errors(), conn, track_entry(conn, entry_id):
                cash_box_store.update_entry(
                    conn,
                    entry_id,
                    body.day,
                    Decimal(body.amount_cents) / 100,
                    body.currency,
                    category=body.category_id,
                    # Presente y vacía (o null): se borra; ausente: no se toca.
                    note=(body.note or "") if "note" in body.model_fields_set else None,
                    today=today(),
                )
            return box_out(conn)

    @app.delete("/api/cash-box/entries/{entry_id}")
    def delete_entry(entry_id: int) -> CashBoxOut:
        with connection() as conn:
            with _errors(), conn, track_entry(conn, entry_id):
                cash_box_store.delete_entry(conn, entry_id)
            return box_out(conn)

    @app.put("/api/cash-box/stored/{fingerprint}")
    def put_stored(fingerprint: str) -> TxOut:
        """«Lo guardé en la caja fuerte»: el retiro deja de ser gasto y suma al saldo."""
        with connection() as conn:
            target, found = movement(conn, fingerprint)
            with _errors(), conn, track_tx(conn, fingerprint, target) as draft:
                draft.before, draft.after = target.category, "Caja fuerte"
                if found.is_linked(fingerprint):
                    raise links.AlreadyLinked("la transacción ya está en otro vínculo")
                if not cash_box.can_store(target, found):
                    raise cash_box.CashBoxError(
                        "solo un retiro (un débito de «Efectivo») se puede guardar en la caja"
                    )
                cash_box_store.store(conn, fingerprint)
            return tx_out(conn, fingerprint, target.month)

    @app.delete("/api/cash-box/stored/{fingerprint}")
    def delete_stored(fingerprint: str) -> Response:
        """Deshace «Lo guardé»: el retiro vuelve a ser gasto en su categoría."""
        return unmark(fingerprint, "stored")

    @app.put("/api/cash-box/deposits/{fingerprint}")
    def put_deposit(fingerprint: str, body: DepositBody) -> TxOut:
        """«Vino de la caja fuerte»: el crédito no es ingreso y baja el saldo (en otra moneda, lo
        dicho o a la tasa del mes del depósito)."""
        with connection() as conn:
            target, found = movement(conn, fingerprint)
            infos = account_data.account_infos(conn)
            banks = [a.key for a in infos if a.kind in BANK_KINDS]
            with _errors(), conn, track_tx(conn, fingerprint, target) as draft:
                draft.before, draft.after = target.category, "Vino de la caja fuerte"
                if found.is_linked(fingerprint):
                    raise links.AlreadyLinked("la transacción ya está en otro vínculo")
                if not cash_box.can_deposit(target, found, banks):
                    raise cash_box.CashBoxError(
                        "solo un crédito de una cuenta bancaria (que no sea salario, pago de "
                        "tarjeta ni envío entre tus cuentas) puede venir de la caja"
                    )
                other = body.currency if body.currency != target.currency else None
                if other is None and body.amount_cents is not None:
                    raise cash_box.CashBoxError(
                        "en la misma moneda sale de la caja lo mismo que el depósito"
                    )
                cash_box_store.deposit(conn, fingerprint, other, _money(body.amount_cents))
            return tx_out(conn, fingerprint, target.month)

    @app.delete("/api/cash-box/deposits/{fingerprint}")
    def delete_deposit(fingerprint: str) -> Response:
        """Desvincula el depósito: vuelve a su categoría (un ingreso, por lo general)."""
        return unmark(fingerprint, "deposit")
