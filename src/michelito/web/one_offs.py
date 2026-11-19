"""One-off expense suggestions for the web: those of `analysis.one_offs`, with account labels."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from michelito.analysis import one_offs
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.rates import Rate, rate_for
from michelito.analysis.recurring_marks import Mark
from michelito.analysis.spending import Movement


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
    """Reasons of each suggested row in the given months (to mark the list)."""
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
