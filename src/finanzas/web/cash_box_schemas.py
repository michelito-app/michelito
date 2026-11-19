"""Modelos JSON de la caja fuerte (`/api/cash-box`): dinero en centavos enteros, fechas ISO."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt

from finanzas.analysis import corrections
from finanzas.analysis.accounts import CASH_BOX_NAME
from finanzas.analysis.cash_box import BoxState, EntryKind, Line, LineKind
from finanzas.web.schemas import _cents, to_cents

Currency = Literal["DOP", "USD"]
Cents = Annotated[StrictInt, Field(gt=0, le=100_000_000_000)]
Note = Annotated[str | None, Field(max_length=corrections.NOTE_MAX)]


class CurrencyAmountOut(BaseModel):
    currency: str
    amount_cents: int


def _amounts(pairs: tuple[tuple[str, Decimal], ...]) -> list[CurrencyAmountOut]:
    return [CurrencyAmountOut(currency=c, amount_cents=to_cents(a)) for c, a in pairs]


class CashLineOut(BaseModel):
    """Una entrada o salida de la caja. `amount_cents`, con signo en la moneda de la caja (+ entra,
    − sale; null: un depósito en otra moneda sin tasa, que no baja el saldo)."""

    kind: LineKind
    day: str
    fingerprint: str
    entry_id: int | None  # lo anotado a mano (se edita y se borra aquí)
    currency: str
    amount_cents: int | None
    dop_cents: int | None  # ≈ RD$ a la tasa de su mes; null sin tasa
    source_amount_cents: int  # el movimiento como aparece, positivo
    source_currency: str
    merchant: str
    account_label: str
    category: str
    category_id: int | None
    note: str
    in_flow: bool  # sale en Transacciones (todo menos el saldo inicial)
    group: str | None  # el grupo compartido en que está (su título); borrarlo lo saca de él

    @classmethod
    def of(
        cls,
        line: Line,
        labels: Mapping[str, str],
        category_ids: Mapping[str, int],
        groups: Mapping[str, str],
    ) -> CashLineOut:
        move = line.move
        return cls(
            kind=line.kind,
            day=line.day.isoformat(),
            fingerprint=line.fingerprint,
            entry_id=None if line.entry is None else line.entry.id,
            currency=line.currency,
            amount_cents=_cents(line.amount),
            dop_cents=_cents(line.dop),
            source_amount_cents=to_cents(line.source_amount),
            source_currency=line.source_currency,
            merchant=CASH_BOX_NAME if move is None else move.merchant,
            account_label=CASH_BOX_NAME if move is None else labels.get(move.account, move.account),
            category="" if move is None else move.category,
            category_id=None if move is None else category_ids.get(move.ref),
            note="" if move is None else move.note,
            in_flow=move is not None,
            group=groups.get(line.fingerprint),
        )


class CashBoxOut(BaseModel):
    """La caja fuerte: saldo por moneda y ≈ RD$, avisos y sus entradas y salidas."""

    account_key: str
    label: str
    exists: bool  # ya se usó (su cuenta aparece en el filtro de cuentas)
    balances: list[CurrencyAmountOut]  # RD$ primero
    total_dop_cents: int  # cada movimiento a la tasa de su mes
    unconverted: list[CurrencyAmountOut]  # sin tasa: no entra en total_dop_cents
    negative: list[CurrencyAmountOut]  # las monedas en negativo (se avisa, no se bloquea)
    uncounted: list[str]  # depósitos en otra moneda sin tasa: no bajan el saldo
    lines: list[CashLineOut]  # la más reciente primero

    @classmethod
    def of(
        cls,
        state: BoxState,
        exists: bool,
        labels: Mapping[str, str],
        category_ids: Mapping[str, int],
        groups: Mapping[str, str],
    ) -> CashBoxOut:
        return cls(
            account_key=state.account_key,
            label=CASH_BOX_NAME,
            exists=exists,
            balances=_amounts(state.balances),
            total_dop_cents=to_cents(state.total_dop),
            unconverted=_amounts(state.unconverted),
            negative=_amounts(state.negative),
            uncounted=list(state.uncounted),
            lines=[CashLineOut.of(line, labels, category_ids, groups) for line in state.lines],
        )


class EntryBody(BaseModel):
    """Un movimiento anotado a mano: saldo inicial, entrada (ingreso) o salida (gasto)."""

    kind: EntryKind
    day: date
    amount_cents: Cents
    currency: Currency
    category_id: int | None = None  # entrada: una de ingreso; salida: una de gasto
    note: Note = None


class EntryPatch(BaseModel):
    """Cambia día, monto y moneda; categoría y nota si vienen (el tipo no cambia). Una nota
    presente y vacía (o null) la borra; ausente, no la toca."""

    day: date
    amount_cents: Cents
    currency: Currency
    category_id: int | None = None
    note: Note = None


class DepositBody(BaseModel):
    """`currency`: la moneda en que salió de la caja (ausente: la del crédito); `amount_cents`:
    cuánto salió en ella (ausente: el crédito a la tasa de su mes)."""

    currency: Currency | None = None
    amount_cents: Cents | None = None
