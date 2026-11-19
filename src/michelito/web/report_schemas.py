"""Reports JSON models (money in integer cents)."""

from __future__ import annotations

from pydantic import BaseModel

from michelito.analysis.anomalies import Direction
from michelito.web import reports
from michelito.web.schemas import MonthOptionOut, _cents, to_cents


class CellOut(BaseModel):
    amount_cents: int
    habitual_cents: int | None  # None: the month is not compared
    flag: Direction | None
    level: int  # 1 to 3 on a rise; 0 otherwise

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
    months: list[MonthOptionOut]  # oldest to newest
    totals: list[RowOut]  # income, expenses, third party, net
    categories: list[RowOut]  # expense categories, by range total
    incomes: list[RowOut]  # income by category (key `income:<name>`), by total

    @classmethod
    def of(cls, result: reports.Comparison) -> ComparisonOut:
        return cls(
            months=[MonthOptionOut.of(m) for m in result.months],
            totals=[RowOut.of(r) for r in result.totals],
            categories=[RowOut.of(r) for r in result.categories],
            incomes=[RowOut.of(r) for r in result.incomes],
        )
