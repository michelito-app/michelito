"""Resumen de gastos en texto para la terminal.

Para explorar por mes y categoría, y corregir, está el board (`finanzas board`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from finanzas.analysis import categories, spending
from finanzas.analysis.spending import CategoryChange, MerchantTotal, Movement

CURRENCY_ORDER = ("DOP", "USD")
SYMBOLS = {"DOP": "RD$", "USD": "US$"}
BASELINE_MONTHS = 6
TOP_CATEGORIES = 8
TOP_MERCHANTS = 8
TOP_CHANGES = 5
MONTH_NAMES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
NO_DATA = "No hay estados de tarjeta guardados todavía. Corre `finanzas sync`."
NO_FULL_MONTH = "Todavía no hay un mes cubierto entero por los estados de todas las tarjetas."


@dataclass(frozen=True)
class CurrencySection:
    currency: str
    monthly: dict[str, Decimal]
    categories: list[tuple[str, Decimal]]
    merchants: list[MerchantTotal]
    changes: list[CategoryChange]
    bank_fees: Decimal = Decimal(0)

    @property
    def total(self) -> Decimal:
        return sum(self.monthly.values(), Decimal(0))

    @property
    def monthly_average(self) -> Decimal:
        return self.total / len(self.monthly)


@dataclass(frozen=True)
class SpendingReport:
    through: date | None
    months: tuple[str, ...]
    sections: tuple[CurrencySection, ...]


def currencies(movements: Sequence[Movement], months: Sequence[str]) -> list[str]:
    """Monedas con movimientos en `months`: pesos y dólares primero, luego el resto."""
    wanted = set(months)
    found = {m.currency for m in movements if m.month in wanted}
    return [c for c in CURRENCY_ORDER if c in found] + sorted(found - set(CURRENCY_ORDER))


def build(
    movements: Sequence[Movement],
    through: date | None,
    months: int,
    first_full_month: str | None = None,
) -> SpendingReport:
    """Agrega los últimos `months` meses completos.

    Los meses anteriores a `first_full_month` (el primer estado de una tarjeta cubre
    solo parte del mes anterior) se excluyen del total, del promedio y de la comparación.
    """
    if through is None:
        return SpendingReport(None, (), ())
    last = spending.last_full_month(through)
    earliest = first_full_month or "0000-00"
    window = tuple(m for m in spending.months_back(last, months) if m >= earliest)
    if not window:
        return SpendingReport(through, (), ())
    previous = spending.months_back(last, BASELINE_MONTHS + 1)[:-1]
    baseline = tuple(m for m in previous if m >= earliest)
    sections = tuple(
        CurrencySection(
            currency=currency,
            monthly=spending.monthly_totals(movements, currency, window),
            categories=spending.by_category(movements, currency, window),
            merchants=spending.top_merchants(movements, currency, window, TOP_MERCHANTS),
            changes=(
                spending.compare_month(movements, currency, last, baseline) if baseline else []
            ),
            bank_fees=_bank_fees(movements, currency, window),
        )
        for currency in currencies(movements, window)
    )
    return SpendingReport(through, window, sections)


def _bank_fees(movements: Sequence[Movement], currency: str, months: Sequence[str]) -> Decimal:
    """Cargos del banco por su referencia estable (el nombre puede estar cambiado)."""
    wanted = set(months)
    return sum(
        (
            m.amount
            for m in movements
            if m.ref == categories.BANK_FEES and m.currency == currency and m.month in wanted
        ),
        Decimal(0),
    )


def money(value: Decimal, currency: str) -> str:
    places = Decimal("1") if currency == "DOP" else Decimal("0.01")
    rounded = value.quantize(places, rounding=ROUND_HALF_UP) + 0  # sin "-0"
    return f"{SYMBOLS.get(currency, currency)} {rounded:,}"


def month_label(month: str) -> str:
    year, number = month.split("-")
    return f"{MONTH_NAMES[int(number) - 1]} {year[2:]}"


def share(part: Decimal, whole: Decimal) -> str:
    return f"{(part / whole * 100):.0f}%" if whole else "-"


def to_text(built: SpendingReport) -> str:
    if not built.sections:
        return NO_DATA if built.through is None else NO_FULL_MONTH
    title = (
        f"Gasto con tarjetas, {month_label(built.months[0])} a {month_label(built.months[-1])} "
        f"(datos completos hasta {built.through})"
    )
    lines = [title, ""]
    for section in built.sections:
        lines.extend(_text_section(section, built.months[-1]))
    lines.append("Para explorar por mes y corregir categorías: finanzas board")
    return "\n".join(lines)


def _purchases(count: int) -> str:
    return "1 compra" if count == 1 else f"{count} compras"


def _text_section(section: CurrencySection, last: str) -> list[str]:
    cur = section.currency
    lines = [
        f"{SYMBOLS.get(cur, cur)} ({cur})",
        f"  Total: {money(section.total, cur)} · promedio mensual "
        f"{money(section.monthly_average, cur)}",
        f"  Cargos del banco: {money(section.bank_fees, cur)}",
        "  Por categoría:",
    ]
    lines += [
        f"    {name:<28} {money(total, cur):>14}  {share(total, section.total):>4}"
        for name, total in section.categories[:TOP_CATEGORIES]
    ]
    lines.append("  Comercios principales:")
    lines += [
        f"    {m.name:<28} {money(m.total, cur):>14}  {_purchases(m.purchases)}"
        for m in section.merchants
    ]
    lines.append(
        f"  {month_label(last)} frente al promedio de los {BASELINE_MONTHS} meses previos:"
    )
    lines += [
        f"    {c.category:<28} {money(c.current, cur):>14}  (promedio {money(c.average, cur)})"
        for c in section.changes[:TOP_CHANGES]
        if c.current > max(c.average, Decimal(0))
    ]
    return [*lines, ""]
