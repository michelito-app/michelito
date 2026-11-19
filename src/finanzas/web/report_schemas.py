"""Modelos JSON de Reportes (dinero en centavos enteros)."""

from __future__ import annotations

from pydantic import BaseModel

from finanzas.analysis.anomalies import Direction
from finanzas.web import reports
from finanzas.web.schemas import MonthOptionOut, _cents, to_cents


class CellOut(BaseModel):
    amount_cents: int
    habitual_cents: int | None  # None: el mes no se compara
    flag: Direction | None
    level: int  # 1 a 3 en una subida; 0 si no

    @classmethod
    def of(cls, cell: reports.Cell) -> CellOut:
        return cls(
            amount_cents=to_cents(cell.amount),
            habitual_cents=_cents(cell.habitual),
            flag=cell.flag,
            level=cell.level,
        )


class RowOut(BaseModel):
    key: str
    label: str
    cells: list[CellOut]

    @classmethod
    def of(cls, row: reports.Row) -> RowOut:
        return cls(key=row.key, label=row.label, cells=[CellOut.of(c) for c in row.cells])


class ComparisonOut(BaseModel):
    months: list[MonthOptionOut]  # del más viejo al más nuevo
    totals: list[RowOut]  # ingresos, gastos, terceros, neto
    categories: list[RowOut]  # categorías de gasto, por total del rango
    incomes: list[RowOut]  # ingresos por categoría (clave `ingreso:<nombre>`), por total

    @classmethod
    def of(cls, result: reports.Comparison) -> ComparisonOut:
        return cls(
            months=[MonthOptionOut.of(m) for m in result.months],
            totals=[RowOut.of(r) for r in result.totals],
            categories=[RowOut.of(r) for r in result.categories],
            incomes=[RowOut.of(r) for r in result.incomes],
        )
