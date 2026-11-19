"""Sugerencias de gasto único para la web: las de `analysis.one_offs` con etiqueta de cuenta."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from finanzas.analysis import one_offs
from finanzas.analysis.accounts import AccountInfo
from finanzas.analysis.rates import Rate, rate_for
from finanzas.analysis.recurring_marks import Mark
from finanzas.analysis.spending import Movement


@dataclass(frozen=True)
class SuggestionView:
    suggestion: one_offs.Suggestion
    account_label: str


def suggestions(
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    rates: Mapping[str, Rate],
    month: str,
    dismissed: Collection[str],
    marks: Mapping[tuple[str, str], Mark],
    unions: Mapping[str, str] | None = None,
) -> list[SuggestionView]:
    labels = {info.key: info.label for info in accounts}
    found = one_offs.suggest(
        movements,
        month,
        rate_for_month=lambda m: rate_for(rates, m),
        dismissed=dismissed,
        marks=marks,
        unions=unions,
    )
    return [SuggestionView(s, labels.get(s.account, s.account)) for s in found]


def reasons_by_fingerprint(
    movements: Sequence[Movement],
    rates: Mapping[str, Rate],
    months: Iterable[str],
    dismissed: Collection[str],
    marks: Mapping[tuple[str, str], Mark],
    unions: Mapping[str, str] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Razones de cada fila sugerida en los meses dados (para marcar la lista)."""
    found: dict[str, tuple[str, ...]] = {}
    for month in sorted(set(months)):
        for item in one_offs.suggest(
            movements,
            month,
            rate_for_month=lambda m: rate_for(rates, m),
            dismissed=dismissed,
            marks=marks,
            unions=unions,
        ):
            found[item.fingerprint] = item.reasons
    return found
