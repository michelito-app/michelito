"""Spending summary as text for the terminal.

To explore by month and category, and to correct, there is the board (`michelito board`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from michelito.analysis import categories, spending
from michelito.analysis.spending import CategoryChange, MerchantTotal, Movement

CURRENCY_ORDER = ("DOP", "USD")
SYMBOLS = {"DOP": "RD$", "USD": "US$"}
BASELINE_MONTHS = 6
TOP_CATEGORIES = 8
TOP_MERCHANTS = 8
TOP_CHANGES = 5
MONTH_NAMES = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
NO_DATA = "No card statements saved yet. Run `michelito sync`."
NO_FULL_MONTH = "No month is fully covered by the statements of every card yet."


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
    """Currencies with transactions in `months`: RD$ and US$ first, then the rest."""
    wanted = set(months)
    found = {m.currency for m in movements if m.month in wanted}
    return [c for c in CURRENCY_ORDER if c in found] + sorted(found - set(CURRENCY_ORDER))


def build(
    movements: Sequence[Movement],
    through: date | None,
    months: int,
    first_full_month: str | None = None,
) -> SpendingReport:
    """Aggregate the last `months` complete months.

    Months before `first_full_month` (a card's first statement covers only part of the
    previous month) are left out of the total, the average and the comparison.
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
    """Bank fees, by their stable reference (the name may have been changed)."""
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
    rounded = value.quantize(places, rounding=ROUND_HALF_UP) + 0  # no "-0"
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
        f"Card spending, {month_label(built.months[0])} to {month_label(built.months[-1])} "
        f"(complete data through {built.through})"
    )
    lines = [title, ""]
    for section in built.sections:
        lines.extend(_text_section(section, built.months[-1]))
    lines.append("To explore by month and correct categories: michelito board")
    return "\n".join(lines)


def _purchases(count: int) -> str:
    return "1 purchase" if count == 1 else f"{count} purchases"


def _text_section(section: CurrencySection, last: str) -> list[str]:
    cur = section.currency
    lines = [
        f"{SYMBOLS.get(cur, cur)} ({cur})",
        f"  Total: {money(section.total, cur)} · monthly average "
        f"{money(section.monthly_average, cur)}",
        f"  Bank fees: {money(section.bank_fees, cur)}",
        "  By category:",
    ]
    lines += [
        f"    {name:<28} {money(total, cur):>14}  {share(total, section.total):>4}"
        for name, total in section.categories[:TOP_CATEGORIES]
    ]
    lines.append("  Top merchants:")
    lines += [
        f"    {m.name:<28} {money(m.total, cur):>14}  {_purchases(m.purchases)}"
        for m in section.merchants
    ]
    lines.append(
        f"  {month_label(last)} against the average of the previous {BASELINE_MONTHS} months:"
    )
    lines += [
        f"    {c.category:<28} {money(c.current, cur):>14}  (average {money(c.average, cur)})"
        for c in section.changes[:TOP_CHANGES]
        if c.current > max(c.average, Decimal(0))
    ]
    return [*lines, ""]
