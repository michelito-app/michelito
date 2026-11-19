"""Modelos JSON de Compartidos (`GET /api/shared`): dinero en centavos enteros, fechas ISO."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from finanzas.analysis.shared import ExpenseState
from finanzas.web import shared_list
from finanzas.web.schemas import (
    CurrencyCentsOut,
    RateOut,
    _cents,
    _currency_cents,
    to_cents,
)


class SharedListExpenseOut(BaseModel):
    """Un gasto del grupo: su reparto y si ya está saldado (en su moneda)."""

    fingerprint: str
    day: str
    merchant: str
    account_label: str
    amount_cents: int  # el gasto completo (antes de repartir)
    currency: str
    people: int | None  # "Éramos N"
    my_share_cents: int | None  # "Mi parte: X"
    for_other: bool  # "Lo pagué por otra persona"
    share_cents: int
    reimbursed_cents: int
    pending_cents: int
    written_off_cents: int

    @classmethod
    def of(cls, e: ExpenseState, labels: Mapping[str, str]) -> SharedListExpenseOut:
        split = e.split
        return cls(
            fingerprint=e.fingerprint,
            day=e.day.isoformat(),
            merchant=e.move.merchant or e.move.description,
            account_label=labels.get(e.move.account, e.move.account),
            amount_cents=to_cents(e.amount),
            currency=e.currency,
            people=split.people,
            my_share_cents=_cents(split.my_share),
            for_other=split.for_other,
            share_cents=to_cents(e.share),
            reimbursed_cents=to_cents(e.reimbursed),
            pending_cents=to_cents(e.pending),
            written_off_cents=to_cents(e.written_off),
        )


class SharedListRefundOut(BaseModel):
    """Un reembolso: un crédito enlazado (`key` es su huella) o uno a mano (`manual:<id>`)."""

    key: str
    manual: bool
    day: str
    description: str  # del crédito: comercio o descripción; a mano: la persona (puede ir vacío)
    account_label: str  # del crédito: su cuenta; a mano: el "dónde" ("" = efectivo)
    amount_cents: int  # positivo
    currency: str

    @classmethod
    def of(cls, r: shared_list.RefundRow) -> SharedListRefundOut:
        return cls(
            key=r.key,
            manual=r.manual,
            day=r.day.isoformat(),
            description=r.description,
            account_label=r.account_label,
            amount_cents=to_cents(r.amount),
            currency=r.currency,
        )


class SharedListGroupOut(BaseModel):
    id: int
    title: str  # nombre, si no «Con quién», si no el comercio del primer gasto
    name: str
    with_whom: str
    status: shared_list.Status
    first_fingerprint: str  # el primer gasto: abre la pantalla del grupo
    first_day: str  # el gasto más viejo
    last_day: str  # el gasto más nuevo
    last_activity: str  # el gasto o el reembolso más reciente
    expenses: list[SharedListExpenseOut]  # del más viejo al más nuevo
    refunds: list[SharedListRefundOut]  # en el orden en que se imputan
    paid: list[CurrencyCentsOut]  # Σ montos de los gastos, por moneda
    reimbursed: list[CurrencyCentsOut]  # Σ reembolsos, por su moneda
    pending: list[CurrencyCentsOut]  # te deben, por moneda (vacío si nada)
    pending_dop_cents: int | None  # ≈ RD$ de lo pendiente; null sin pendiente o sin tasa
    unconverted_usd_cents: int  # US$ pendientes sin ninguna tasa
    excess: list[CurrencyCentsOut]  # te devolvieron de más tras saldar todo

    @classmethod
    def of(cls, row: shared_list.GroupRow, labels: Mapping[str, str]) -> SharedListGroupOut:
        st = row.state
        return cls(
            id=st.id,
            title=st.title,
            name=st.link.name,
            with_whom=st.link.with_whom,
            status=row.status,
            first_fingerprint=st.first.fingerprint,
            first_day=row.first_day.isoformat(),
            last_day=row.last_day.isoformat(),
            last_activity=row.last_activity.isoformat(),
            expenses=[SharedListExpenseOut.of(e, labels) for e in row.expenses],
            refunds=[SharedListRefundOut.of(r) for r in row.refunds],
            paid=_currency_cents(list(row.paid)),
            reimbursed=_currency_cents(list(row.reimbursed)),
            pending=_currency_cents(list(row.pending)),
            pending_dop_cents=_cents(row.pending_dop),
            unconverted_usd_cents=to_cents(row.unconverted_usd),
            excess=_currency_cents(list(st.excess_by)),
        )


class SharedUnconvertedOut(BaseModel):
    """US$ sin ninguna tasa: aparte de las cifras en RD$."""

    owed_usd_cents: int
    reimbursed_usd_cents: int


class SharedListOut(BaseModel):
    owed_dop_cents: int  # te deben (suma de las filas, como Pendientes)
    reimbursed_year_dop_cents: int  # reembolsos con fecha en el año en curso
    year: int
    open_count: int  # grupos con pendiente
    unconverted: SharedUnconvertedOut
    rate: RateOut | None  # la más reciente: la de lo pendiente en US$
    groups: list[SharedListGroupOut]  # la última actividad primero

    @classmethod
    def of(
        cls, found: shared_list.SharedList, labels: Mapping[str, str], year: int
    ) -> SharedListOut:
        groups = [SharedListGroupOut.of(r, labels) for r in found.rows]
        return cls(
            # Suma los centavos de las filas: cuadra con lo que se ve (como Pendientes).
            owed_dop_cents=sum(g.pending_dop_cents or 0 for g in groups),
            reimbursed_year_dop_cents=to_cents(found.reimbursed_year_dop),
            year=year,
            open_count=found.open_count,
            unconverted=SharedUnconvertedOut(
                owed_usd_cents=to_cents(found.unconverted_owed_usd),
                reimbursed_usd_cents=to_cents(found.unconverted_reimbursed_usd),
            ),
            rate=None if found.rate is None else RateOut.of(found.rate),
            groups=groups,
        )
