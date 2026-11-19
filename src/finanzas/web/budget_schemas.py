"""Modelos JSON del presupuesto y las reservas (dinero en centavos enteros de RD$)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool, StringConstraints

from finanzas.analysis import budget
from finanzas.analysis import reserve_suggestions as suggest
from finanzas.web.budget import BudgetView, Overview, ReserveView
from finanzas.web.schemas import _cents, to_cents

Fingerprint = Annotated[str, StringConstraints(min_length=1, max_length=64)]
MonthText = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class WarningOut(BaseModel):
    habitual_cents: int
    basis_cents: int
    up: bool


class LineOut(BaseModel):
    category_id: int
    category: str
    cap_cents: int | None  # None: «Sin presupuesto»
    manual: bool
    spent_cents: int  # contra el tope
    one_offs_cents: int
    covered_cents: int  # cubierto por reservas
    without_rate: int  # gastos en US$ sin tasa (no suman)
    over_cents: int  # lo que pasa del tope, exacto
    passed: bool  # pasó por más del margen (max(5 %, RD$ 500)): cuenta como pasada
    refunds_cents: int  # devuelto de más en el mes (lo gastado queda en 0)
    habitual_cents: int | None
    warning: WarningOut | None
    active: bool  # arriba (tope, algo del mes o un aviso) o en «Otras categorías»

    @classmethod
    def of(cls, line: budget.Line, name: str) -> LineOut:
        found = line.warning
        return cls(
            category_id=line.category_id,
            category=name,
            cap_cents=_cents(line.cap),
            manual=line.manual,
            spent_cents=to_cents(line.spent),
            one_offs_cents=to_cents(line.one_offs),
            covered_cents=to_cents(line.covered),
            without_rate=line.without_rate,
            over_cents=to_cents(line.over),
            passed=line.passed,
            refunds_cents=to_cents(line.refunds),
            habitual_cents=_cents(line.habitual),
            warning=None
            if found is None
            else WarningOut(
                habitual_cents=to_cents(found.habitual),
                basis_cents=to_cents(found.basis),
                up=found.up,
            ),
            active=line.active,
        )


class BudgetOut(BaseModel):
    active: bool
    month: str
    lines: list[LineOut]
    cap_cents: int
    spent_cents: int
    over_count: int
    over_cents: int
    reference_months: list[str]
    filtered: bool  # con filtro de cuentas: topes de todas, lo gastado de las elegidas
    missing: list[str]  # cuentas sin el estado completo del mes (datos parciales)

    @classmethod
    def of(cls, view: BudgetView) -> BudgetOut:
        return cls(
            active=view.active,
            month=view.month,
            lines=[LineOut.of(line, view.names.get(line.category_id, "")) for line in view.lines],
            cap_cents=to_cents(view.totals.cap),
            spent_cents=to_cents(view.totals.spent),
            over_count=view.totals.over_count,
            over_cents=to_cents(view.totals.over),
            reference_months=view.reference_months,
            filtered=view.filtered,
            missing=view.missing,
        )


class CapBody(BaseModel):
    cap_cents: int | None = Field(ge=0, le=10_000_000_000)  # None: «Sin presupuesto»

    @property
    def cap(self) -> Decimal | None:
        return None if self.cap_cents is None else Decimal(self.cap_cents) / 100


class WarningBody(BaseModel):
    accept: StrictBool


class EntryOut(BaseModel):
    entry_id: int | None  # la entrada de la bitácora (None si nada cambió)


class MemberOut(BaseModel):
    fingerprint: str
    day: str
    month: str
    merchant: str
    amount_cents: int
    currency: str
    amount_dop_cents: int | None


class ReserveOut(BaseModel):
    id: int
    name: str
    amount_cents: int
    category_id: int
    category: str
    due_month: str
    every_months: int | None  # None: una sola vez
    multiple: bool
    next_due: str | None  # None: de una vez y ya pasó
    monthly_cents: int
    year_spent_cents: int
    year_estimated_cents: int
    year_without_rate: int
    paid: bool  # el próximo vencimiento ya tiene su gasto vinculado
    members: list[MemberOut]

    @classmethod
    def of(cls, view: ReserveView) -> ReserveOut:
        r = view.reserve
        return cls(
            id=r.id,
            name=r.name,
            amount_cents=to_cents(r.amount),
            category_id=r.category_id,
            category=view.category,
            due_month=r.due_month,
            every_months=r.every_months,
            multiple=r.multiple,
            next_due=view.next_due,
            monthly_cents=to_cents(view.monthly),
            year_spent_cents=to_cents(view.year.spent),
            year_estimated_cents=to_cents(view.year.estimated),
            year_without_rate=view.year.without_rate,
            paid=view.paid,
            members=[
                MemberOut(
                    fingerprint=m.move.fingerprint,
                    day=m.move.day.isoformat(),
                    month=m.move.month,
                    merchant=m.move.merchant or m.move.description,
                    amount_cents=to_cents(m.move.amount),
                    currency=m.move.currency,
                    amount_dop_cents=_cents(m.dop),
                )
                for m in view.members
            ],
        )


class SuggestionOut(BaseModel):
    key: str
    name: str
    amount_cents: int
    category_id: int
    category: str
    due_month: str
    every_months: int
    multiple: bool
    reason: str

    @classmethod
    def of(cls, item: suggest.Suggestion, category: str) -> SuggestionOut:
        return cls(
            key=item.key,
            name=item.name,
            amount_cents=to_cents(item.amount),
            category_id=item.category_id,
            category=category,
            due_month=item.due_month,
            every_months=item.every_months,
            multiple=item.multiple,
            reason=item.reason,
        )


class ReservesOut(BaseModel):
    items: list[ReserveOut]
    suggestions: list[SuggestionOut]
    monthly_cents: int  # lo que se aparta al mes para todas


class ReserveBody(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    amount_cents: int = Field(gt=0, le=10_000_000_000)
    category_id: int
    due_month: MonthText
    every_months: Literal[6, 12] | None = None  # cada 6 meses o cada año; None: una sola vez
    multiple: StrictBool = False
    source: Annotated[str, StringConstraints(max_length=200)] | None = None  # una sugerencia


class ReservePatch(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None
    amount_cents: int | None = Field(default=None, gt=0, le=10_000_000_000)
    category_id: int | None = None
    due_month: MonthText | None = None
    every_months: Literal[6, 12] | None = None
    once: StrictBool | None = None  # true: pasa a «una sola vez» (`every_months` se ignora)
    multiple: StrictBool | None = None


class CreatedOut(BaseModel):
    id: int
    entry_id: int | None


class MembersBody(BaseModel):
    fingerprints: list[Fingerprint] = Field(min_length=1, max_length=500)


class SkippedOut(BaseModel):
    fingerprint: str
    reason: str  # "vinculo", "no_gasto" o "desconocida"
    message: str


class MembersOut(BaseModel):
    applied: list[str]
    skipped: list[SkippedOut]
    entry_id: int | None


class DismissBody(BaseModel):
    # «recurrente:…», «irregular:…» o «pico:…» (solo se valida la forma: con un filtro de
    # cuentas la sugerencia puede no estar entre las de todas).
    key: Annotated[
        str, StringConstraints(pattern=r"^(recurrente|irregular|pico):.+$", max_length=200)
    ]
    name: Annotated[str, StringConstraints(max_length=80)] | None = None  # para la bitácora


class ReserveOptionOut(BaseModel):
    id: int
    name: str


class ReserveRefOut(BaseModel):
    id: int
    name: str
    category: str
    next_due: str | None
    suggested: bool  # la que «Para revisar» propone para este gasto


class TxReserveOut(BaseModel):
    """La sección «Reserva» del detalle de una transacción."""

    reserve: ReserveRefOut | None  # la que la cubre
    options: list[ReserveRefOut]  # a las que se puede vincular (la sugerida primero)
    can_link: bool
    reason: str  # por qué no se puede, si no


class UpcomingOut(BaseModel):
    id: int
    name: str
    due_month: str
    amount_cents: int


class OverviewOut(BaseModel):
    active: bool
    over_count: int | None  # None con filtro de cuentas: no se cuentan las pasadas
    over_cents: int
    missing: list[str]  # cuentas sin el estado completo del mes
    monthly_cents: int
    reserves: int
    upcoming: list[UpcomingOut]

    @classmethod
    def of(cls, found: Overview) -> OverviewOut:
        return cls(
            active=found.active,
            over_count=found.over_count,
            over_cents=to_cents(found.over),
            monthly_cents=to_cents(found.monthly),
            reserves=found.reserves,
            missing=found.missing,
            upcoming=[
                UpcomingOut(id=r.id, name=r.name, due_month=due, amount_cents=to_cents(r.amount))
                for r, due in found.upcoming
            ],
        )
