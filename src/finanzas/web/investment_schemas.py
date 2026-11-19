"""Modelos JSON de Inversiones (`/api/investments`): dinero en centavos enteros, fechas ISO."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool, model_validator

from finanzas.analysis import links
from finanzas.analysis.investments import Entry
from finanzas.analysis.links import InvestmentRole
from finanzas.web import investment_list
from finanzas.web.schemas import InvestmentRefOut, RateOut, _cents, to_cents

Text = Annotated[str | None, Field(max_length=links.PERSON_MAX)]
Fingerprint = Annotated[str, Field(min_length=1, max_length=200)]
CreditRole = Literal["return", "capital", "mixed"]


class InvestmentEntryOut(BaseModel):
    """Un movimiento de la inversión, en su moneda (y si suma en la de la inversión)."""

    fingerprint: str
    day: str
    merchant: str
    description: str
    account_label: str
    role: InvestmentRole
    amount_cents: int  # positivo: lo que salió (aporte) o entró (crédito)
    currency: str
    capital_cents: int  # la parte de capital de un crédito (aporte: 0)
    return_cents: int  # la parte de rendimiento de un crédito (aporte: 0)
    excess_cents: int  # capital devuelto de más que lo aportado: está en `return_cents`
    counted: bool  # false: en otra moneda sin ninguna tasa, no suma

    @classmethod
    def of(cls, e: Entry, labels: Mapping[str, str]) -> InvestmentEntryOut:
        return cls(
            fingerprint=e.fingerprint,
            day=e.day.isoformat(),
            merchant=e.move.merchant or e.move.description,
            description=e.move.description,
            account_label=labels.get(e.move.account, e.move.account),
            role=e.role,
            amount_cents=to_cents(e.amount),
            currency=e.currency,
            capital_cents=to_cents(e.capital),
            return_cents=to_cents(e.returned),
            excess_cents=to_cents(e.excess),
            counted=e.counted,
        )


class InvestmentOut(InvestmentRefOut):
    """Una inversión con sus cifras (en su moneda) y sus movimientos."""

    written_off: bool
    first_day: str  # el primer aporte
    last_activity: str  # el movimiento más reciente
    last_credit: str | None  # el último cobro (rendimiento o capital)
    contributed_cents: int
    capital_returned_cents: int
    returns_cents: int  # incluye lo devuelto de más (`excess_cents`)
    excess_cents: int  # capital devuelto de más que lo aportado: cuenta como rendimiento
    annual_rate: float | None  # fracción (0.12 = 12 %); null sin capital-días
    pending_dop_cents: int | None  # capital por volver ≈ RD$; null: US$ sin tasa
    unconverted_count: int  # movimientos en otra moneda sin tasa: no suman
    entries: list[InvestmentEntryOut]  # por fecha

    @classmethod
    def of(cls, row: investment_list.InvestmentRow, labels: Mapping[str, str]) -> InvestmentOut:
        st = row.state
        return cls(
            **InvestmentRefOut.ref(st).model_dump(),
            written_off=st.link.written_off,
            first_day=st.first.day.isoformat(),
            last_activity=st.last_activity.isoformat(),
            last_credit=None if st.last_credit is None else st.last_credit.isoformat(),
            contributed_cents=to_cents(st.contributed),
            capital_returned_cents=to_cents(st.capital_returned),
            returns_cents=to_cents(st.returns),
            excess_cents=to_cents(st.excess),
            annual_rate=None if row.annual_rate is None else round(float(row.annual_rate), 6),
            pending_dop_cents=_cents(row.pending_dop),
            unconverted_count=len(st.unconverted),
            entries=[InvestmentEntryOut.of(e, labels) for e in st.entries],
        )


class InvestmentUnconvertedOut(BaseModel):
    """US$ sin ninguna tasa: aparte de las cifras en RD$."""

    pending_usd_cents: int
    returns_usd_cents: int


class InvestmentListOut(BaseModel):
    pending_dop_cents: int  # capital por volver de las activas ≈ RD$
    returns_year_dop_cents: int  # rendimientos cobrados en el año en curso ≈ RD$
    year: int
    active_count: int
    unconverted: InvestmentUnconvertedOut
    rate: RateOut | None  # la más reciente: la del capital por volver en US$
    investments: list[InvestmentOut]  # la última actividad primero

    @classmethod
    def of(
        cls, found: investment_list.InvestmentList, labels: Mapping[str, str], year: int
    ) -> InvestmentListOut:
        rows = [InvestmentOut.of(r, labels) for r in found.rows]
        return cls(
            pending_dop_cents=to_cents(found.pending_dop),
            returns_year_dop_cents=to_cents(found.returns_year_dop),
            year=year,
            active_count=found.active_count,
            unconverted=InvestmentUnconvertedOut(
                pending_usd_cents=to_cents(found.unconverted_pending_usd),
                returns_usd_cents=to_cents(found.unconverted_returns_usd),
            ),
            rate=None if found.rate is None else RateOut.of(found.rate),
            investments=rows,
        )


class InvestmentBody(BaseModel):
    """Una inversión nueva con este débito como primer aporte."""

    fingerprint: Fingerprint
    with_whom: Text = None
    name: Text = None


class InvestmentPatch(BaseModel):
    """Lo ausente no cambia; un texto vacío o null lo borra."""

    name: Text = None
    with_whom: Text = None
    written_off: StrictBool | None = None


class RoleBody(BaseModel):
    """El tipo de un crédito; `capital_cents` solo en un mixto (0 < capital < crédito)."""

    role: CreditRole
    capital_cents: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _capital_only_if_mixed(self) -> RoleBody:
        if (self.role == "mixed") != (self.capital_cents is not None):
            raise ValueError("un crédito mixto lleva la parte de capital; los demás, no")
        return self

    @property
    def capital(self) -> Decimal | None:
        return None if self.capital_cents is None else Decimal(self.capital_cents) / 100


class MemberBody(BaseModel):
    """Suma un movimiento: un débito como aporte (`role` ausente o "contribution") o un crédito
    con su tipo."""

    fingerprint: Fingerprint
    role: InvestmentRole = "contribution"
    capital_cents: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _capital_only_if_mixed(self) -> MemberBody:
        if (self.role == "mixed") != (self.capital_cents is not None):
            raise ValueError("un crédito mixto lleva la parte de capital; los demás, no")
        return self

    @property
    def capital(self) -> Decimal | None:
        return None if self.capital_cents is None else Decimal(self.capital_cents) / 100
