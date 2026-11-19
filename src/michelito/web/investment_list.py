"""Investments: all of them on one screen, across every month (pure functions).

- **One row per investment** with at least one contribution present (`investments.states`), the
  one with the most recent activity first (on a tie, the newest).
- **Accounts**: with chosen accounts, an investment counts if any of its contributions belongs
  to them (like Shared with its expenses).
- **Totals** (≈ RD$): "capital still to come back", that of the active ones (closed ones have
  none; written-off ones do not count), in RD$ at the latest rate; "returns received this
  year", the return of each credit dated in the year of `today`, in RD$ at its month's rate
  (or the closest earlier month's); US$ with no rate go apart, nothing is made up. And how many
  are active.
- **Pickers** on an investment's screen: debits that can be another contribution (from
  PICK_WINDOW_DAYS before the first contribution) and credits that can be a return (from the
  first contribution); first (and primary) the ones suggested for this investment
  (`investments.suggestions`), then the rest, newest first within each block.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from michelito.analysis import investments
from michelito.analysis.investments import InvestmentState, Suggestion
from michelito.analysis.links import Candidate, Links
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.spending import Movement

PICK_WINDOW_DAYS = 120
_ZERO = Decimal(0)


@dataclass(frozen=True)
class InvestmentRow:
    state: InvestmentState
    annual_rate: Decimal | None  # fraction: 0.12 = 12 % (see `investments.annual_rate`)
    pending_dop: (
        Decimal | None
    )  # capital still to come back ≈ RD$ (None: in US$ with no rate at all)


@dataclass(frozen=True)
class InvestmentList:
    rows: tuple[InvestmentRow, ...]  # latest activity first
    pending_dop: Decimal  # capital still to come back from the active ones, ≈ RD$
    unconverted_pending_usd: Decimal  # that of the active ones in US$ with no rate at all
    returns_year_dop: Decimal  # returns received in the year of `today`, ≈ RD$
    unconverted_returns_usd: Decimal
    rate: Rate | None  # the latest one: used for the US$ capital still to come back

    @property
    def active_count(self) -> int:
        return sum(1 for r in self.rows if r.state.status == "active")


def picked(state: InvestmentState, chosen: Collection[str] | None) -> bool:
    """The investment counts for these accounts: one of its contributions is theirs (None: all)."""
    return chosen is None or any(e.move.account in chosen for e in state.contributions)


def latest_rate(rates: Mapping[str, Rate], today: date) -> Rate | None:
    return rate_for(rates, today.strftime("%Y-%m"))


def pending_dop(state: InvestmentState, rate: Rate | None) -> Decimal | None:
    return to_dop(state.pending, state.currency, rate)


def returns_in_year(
    found: Iterable[InvestmentState], year: int, rates: Mapping[str, Rate]
) -> tuple[Decimal, Decimal]:
    """Returns dated in `year`, in RD$ at their month's rate; and the US$ with no rate."""
    dop, unconverted = _ZERO, _ZERO
    for state in found:
        for entry in state.credits:
            if entry.day.year != year or entry.returned <= 0:
                continue
            value = to_dop(entry.returned, entry.currency, rate_for(rates, entry.move.month))
            if value is None:
                unconverted += entry.returned
            else:
                dop += value
    return dop, unconverted


def build_list(
    found: Mapping[int, InvestmentState],
    rates: Mapping[str, Rate],
    today: date,
    chosen: Collection[str] | None = None,
) -> InvestmentList:
    """The rows and totals of Investments. `chosen`: account keys (None: all)."""
    shown = investments.newest_first(s for s in found.values() if picked(s, chosen))
    rate = latest_rate(rates, today)
    rows = tuple(InvestmentRow(s, s.annual_rate(today), pending_dop(s, rate)) for s in shown)
    active = [r for r in rows if r.state.status == "active"]
    year_dop, year_unconverted = returns_in_year(shown, today.year, rates)
    return InvestmentList(
        rows=rows,
        pending_dop=sum((r.pending_dop for r in active if r.pending_dop is not None), _ZERO),
        unconverted_pending_usd=sum(
            (r.state.pending for r in active if r.pending_dop is None), _ZERO
        ),
        returns_year_dop=year_dop,
        unconverted_returns_usd=year_unconverted,
        rate=rate,
    )


def _ranked(moves: Iterable[Movement], suggested: Collection[str]) -> list[Candidate]:
    found = [Candidate(m, m.fingerprint in suggested) for m in moves]
    return sorted(found, key=lambda c: (c.primary, c.move.day, c.move.fingerprint), reverse=True)


def contribution_candidates(
    state: InvestmentState,
    movements: Iterable[Movement],
    links: Links,
    hints: Mapping[str, Suggestion],
    banks: Collection[str],
) -> list[Candidate]:
    """For "add a contribution": unlinked bank debits from PICK_WINDOW_DAYS days before the first
    contribution; the ones suggested for this investment first."""
    start = state.first.day - timedelta(days=PICK_WINDOW_DAYS)
    moves = [
        m
        for m in movements
        if m.account in banks and m.day >= start and investments.is_contribution_candidate(m, links)
    ]
    return _ranked(moves, _suggested(hints, state, "possible_contribution"))


def credit_candidates(
    state: InvestmentState,
    movements: Iterable[Movement],
    links: Links,
    hints: Mapping[str, Suggestion],
    banks: Collection[str],
) -> list[Candidate]:
    """For "add a return": unlinked bank credits since the first contribution; the ones
    suggested for this investment first."""
    moves = [
        m
        for m in movements
        if m.account in banks
        and m.day >= state.first.day
        and investments.is_credit_candidate(m, links)
    ]
    return _ranked(moves, _suggested(hints, state, "possible_return"))


def _suggested(
    hints: Mapping[str, Suggestion], state: InvestmentState, kind: str
) -> frozenset[str]:
    return frozenset(fp for fp, s in hints.items() if s.kind == kind and s.state.id == state.id)


def open_investments(
    found: Mapping[int, InvestmentState], include_lost: bool = False
) -> list[InvestmentState]:
    """The investments something can be added to, most recent activity first: for a
    contribution ("add to an existing one"), all but the written-off ones; for a credit
    (`include_lost`), those too: sometimes part of a written-off one gets paid back."""
    ranked = investments.newest_first(found.values())
    return [s for s in ranked if include_lost or s.status != "written_off"]
