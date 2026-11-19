"""Modelos JSON de «Es recurrente…» (desde una transacción) y de «Unir con…» / «Separar»."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from finanzas.analysis.recurring import Cadence
from finanzas.analysis.recurring_marks import KEY_MAX, MarkStatus

GroupKey = Literal[
    "vivienda", "prestamos", "servicios", "seguros", "suscripciones", "cargos", "otros"
]


class TxRecurringBody(BaseModel):
    """«Es recurrente…»: cadencia (mensual por defecto), grupo opcional y, en un préstamo, las
    cuotas que quedan (ausente o null: no se anotan)."""

    cadence: Cadence = "mensual"
    group: GroupKey | None = None
    installments_left: int | None = Field(default=None, ge=0, le=600)


class TxRecurringOut(BaseModel):
    """Qué es la transacción para Recurrentes: si se puede marcar y, si ya es, dónde está."""

    eligible: bool  # un débito de gasto que no es una recarga
    reason: str  # por qué no se puede marcar (vacío si se puede)
    key: str  # la serie (comercio o proveedor) con que se marca
    name: str
    currency: str
    recurring: bool  # aparece en Recurrentes (detectado o marcado, sin «No es recurrente»)
    mark: MarkStatus | None
    group: str  # el grupo en que aparece (vacío si no aparece)
    loan: bool  # su categoría es Préstamos (se ofrecen las cuotas)


class JoinBody(BaseModel):
    """«Unir con…»: los comercios de la serie `merchant` pasan a la serie `target`."""

    merchant: str = Field(min_length=1, max_length=KEY_MAX)
    target: str = Field(min_length=1, max_length=KEY_MAX)


class SeparateBody(BaseModel):
    """«Separar»: el comercio vuelve a ir solo."""

    merchant: str = Field(min_length=1, max_length=KEY_MAX)
