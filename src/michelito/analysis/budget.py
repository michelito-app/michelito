"""Budget per category (Monarch style, not zero-based). Pure logic, everything in RD$.

- Each expense category can have a monthly **cap** (`Cap`). There is no income allocation and
  no **rollover**: each month only that month's spending is compared against the cap.
- Spending against the cap is the month's spending in that category (for a shared expense, only
  your part, as everywhere else: `Movement.amount` already comes that way; a refund subtracts),
  **without** one-off expenses (shown apart, "+ RD$ X in one-off expenses", and still in the
  month's total) and **without** expenses linked to a reserve ("covered by the reserve").
  Amounts in US$ convert to RD$ at their month's rate; without a rate they don't add up and are
  counted apart.
- A category's **usual amount** (`habitual`): the median spent (without one-offs or what
  reserves cover) over the last `BASELINE_MONTHS` complete months (at least one is needed;
  months with no spending in it count as 0), across all accounts: caps belong to the whole
  household even when an account filter is applied.
- **Initial value** on activation: the rounded usual amount (`round_cap`: to the nearest
  multiple of `CAP_STEP`, at least `CAP_STEP` if there was anything; with no usual amount,
  "no budget").
- **"Usual changed" warning** (`warning`): only on a cap not touched by hand, when today's
  rounded usual amount differs from the one already seen (`basis`) by at least
  max(`CAP_STEP`, `WARN_SHARE` of the one seen). It never changes by itself: accepting sets the
  new cap; ignoring only marks the new value as seen (no new warning until it changes again).
- **Over**: a category counts as over (`passed`, in the totals and in the Summary) only if it
  exceeds its cap by more than max(`PASS_SHARE` of the cap, `PASS_FLOOR`): a US$ rent that
  rises a bit with the rate is not. The exact difference (`over`) is shown anyway.
- **Negative net spending**: if the month's refunds exceed what was spent, spending against the
  cap stays at 0 and the excess refunded goes apart ("refunds: RD$ X", `refunds`); it does not
  subtract from the budget's total spent.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

BASELINE_MONTHS = 6
CAP_STEP = Decimal(500)
WARN_SHARE = Decimal("0.10")
CAP_MAX = Decimal(100_000_000)
PASS_SHARE = Decimal("0.05")
PASS_FLOOR = Decimal(500)
_ZERO = Decimal(0)


@dataclass(frozen=True)
class Cap:
    category_id: int
    cap: Decimal | None  # None: "no budget"
    manual: bool = False  # edited by hand: stays fixed
    basis: Decimal | None = None  # the rounded usual amount already seen


@dataclass(frozen=True)
class Item:
    """An expense of the month already in RD$ (`dop` None: US$ without a rate)."""

    fingerprint: str
    month: str
    category_id: int
    dop: Decimal | None
    one_off: bool = False
    reserved: bool = False  # linked to a reserve


@dataclass(frozen=True)
class Warning:
    habitual: Decimal  # today's rounded usual amount
    basis: Decimal  # the one already seen

    @property
    def up(self) -> bool:
        return self.habitual > self.basis


@dataclass(frozen=True)
class Line:
    category_id: int
    cap: Decimal | None
    manual: bool
    spent: Decimal  # against the cap
    one_offs: Decimal  # the month's one-off expenses (apart)
    covered: Decimal  # covered by reserves (apart)
    without_rate: int  # US$ expenses without a rate (not added)
    habitual: Decimal | None  # today's rounded usual amount (None: no reference months)
    warning: Warning | None
    refunds: Decimal = _ZERO  # excess refunded in the month (spending stays at 0)

    @property
    def over(self) -> Decimal:
        """How much the cap is exceeded, exactly (0 if not exceeded or no cap)."""
        if self.cap is None:
            return _ZERO
        return max(self.spent - self.cap, _ZERO)

    @property
    def passed(self) -> bool:
        """Exceeded the cap by more than the margin (see the module docstring)."""
        if self.cap is None:
            return False
        return self.over > max(self.cap * PASS_SHARE, PASS_FLOOR)

    @property
    def ratio(self) -> float:
        if self.cap is None or self.cap <= 0:
            return float("inf") if self.spent > 0 and self.cap is not None else 0.0
        return float(self.spent / self.cap)

    @property
    def active(self) -> bool:
        """Shown at the top: has a cap, something this month or a warning."""
        return bool(
            self.cap is not None
            or self.spent
            or self.one_offs
            or self.covered
            or self.refunds
            or self.without_rate
            or self.warning
        )


def round_cap(value: Decimal | None) -> Decimal | None:
    """The usual amount rounded to the nearest multiple of `CAP_STEP` (half up), at least
    `CAP_STEP` if there was spending; None without a usual amount or spending."""
    if value is None or value <= 0:
        return None
    steps = (value / CAP_STEP).to_integral_value(rounding=ROUND_HALF_UP)
    return max(steps, Decimal(1)) * CAP_STEP


def reference_months(complete: Iterable[str], count: int = BASELINE_MONTHS) -> list[str]:
    """The last `count` complete months (oldest to newest)."""
    return sorted(set(complete))[-count:]


def habitual(items: Iterable[Item], months: Sequence[str]) -> dict[int, Decimal]:
    """The usual amount per category: the median spent in `months` without one-offs or what
    reserves cover (months without spending count 0). Empty without months."""
    if not months:
        return {}
    wanted = set(months)
    totals: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for item in items:
        if item.month in wanted and not item.one_off and not item.reserved and item.dop is not None:
            totals[item.category_id][item.month] += item.dop
    return {
        category: statistics.median(by_month.get(m, _ZERO) for m in months)
        for category, by_month in totals.items()
    }


def initial_caps(categories: Iterable[int], usual: Mapping[int, Decimal]) -> list[Cap]:
    """The caps on activation: each category's rounded usual amount (or "no budget")."""
    found = []
    for category in categories:
        rounded = round_cap(usual.get(category))
        found.append(Cap(category, rounded, False, rounded or _ZERO))
    return found


def warning(cap: Cap, usual: Decimal | None) -> Warning | None:
    """The "usual changed" warning (see the module docstring)."""
    if cap.manual or cap.basis is None:
        return None
    now = round_cap(usual) or _ZERO
    if abs(now - cap.basis) < max(CAP_STEP, cap.basis * WARN_SHARE):
        return None
    return Warning(now, cap.basis)


def lines(
    items: Iterable[Item],
    month: str,
    caps: Mapping[int, Cap],
    usual: Mapping[int, Decimal],
    categories: Collection[int],
) -> list[Line]:
    """One line per expense category (`categories`, plus those with something this month),
    sorted by excess (the most over first), then by how much of their cap they have used."""
    spent: dict[int, Decimal] = defaultdict(Decimal)
    one_offs: dict[int, Decimal] = defaultdict(Decimal)
    covered: dict[int, Decimal] = defaultdict(Decimal)
    missing: dict[int, int] = defaultdict(int)
    seen = set(categories)
    for item in items:
        if item.month != month:
            continue
        seen.add(item.category_id)
        if item.dop is None:
            missing[item.category_id] += 1
        elif item.reserved:
            covered[item.category_id] += item.dop
        elif item.one_off:
            one_offs[item.category_id] += item.dop
        else:
            spent[item.category_id] += item.dop
    found = []
    for category in seen:
        cap = caps.get(category)
        rounded = round_cap(usual.get(category)) if usual else None
        found.append(
            Line(
                category_id=category,
                cap=None if cap is None else cap.cap,
                manual=bool(cap and cap.manual),
                spent=max(spent[category], _ZERO),
                one_offs=one_offs[category],
                covered=covered[category],
                without_rate=missing[category],
                habitual=rounded,
                warning=None if cap is None else warning(cap, usual.get(category, _ZERO)),
                refunds=max(-spent[category], _ZERO),
            )
        )
    return sorted(
        found,
        key=lambda line: (not line.passed, -line.over, -line.ratio, -line.spent, line.category_id),
    )


@dataclass(frozen=True)
class Totals:
    cap: Decimal  # sum of the caps
    spent: Decimal  # spent against a cap (in the categories with a cap)
    over_count: int
    over: Decimal


def totals(found: Iterable[Line]) -> Totals:
    capped = [line for line in found if line.cap is not None]
    passed = [line for line in capped if line.passed]
    return Totals(
        cap=sum((line.cap or _ZERO for line in capped), _ZERO),
        spent=sum((line.spent for line in capped), _ZERO),
        over_count=len(passed),
        over=sum((line.over for line in passed), _ZERO),
    )
