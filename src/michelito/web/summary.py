"""Summary queries: everything in RD$, calendar month by purchase date."""

from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from michelito.analysis import anomalies, cash_box, categories, ledger, spending
from michelito.analysis.accounts import AccountInfo, account_label
from michelito.analysis.exchanges import ExchangeState
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.analysis.spending import Movement
from michelito.i18n import t

BASELINE_MONTHS = 6
SAME_FLOOR = Decimal(500)
SAME_SHARE = Decimal("0.05")
MIN_INCOME_SHARE = Decimal("0.01")  # income below this share of spending: no savings rate
TOP_CHANGES = 3
TREND_MONTHS = 12
ACTIVE_DAYS = 45

_CREDIT_CARD = "credit_card"
_BANK_KINDS = ("savings", "checking")
_ZERO = Decimal(0)
_MONTHS = tuple(t(f"web.summary.month_{number:02d}") for number in range(1, 13))


@dataclass(frozen=True)
class MonthOption:
    month: str
    label: str
    partial: bool


@dataclass(frozen=True)
class Coverage:
    key: str
    label: str
    through: date | None
    complete: bool


@dataclass(frozen=True)
class CategoryLine:
    category: str
    amount: Decimal
    habitual: Decimal | None
    diff: Decimal | None
    same: bool
    share: float
    one_offs: Decimal
    purchases: int
    habitual_purchases: int | None


@dataclass(frozen=True)
class Change:
    category: str
    diff: Decimal
    one_offs: Decimal
    purchases: int
    habitual_purchases: int | None


@dataclass(frozen=True)
class IncomeLine:
    """The month's income of one category (Salary, Crypto, Other income…), in RD$."""

    category: str
    amount: Decimal  # positive: what came in
    count: int
    ref: str = ""  # the stable reference (`Movement.ref`): renaming the category keeps it


@dataclass(frozen=True)
class MonthTotal:
    month: str
    label: str  # abbreviated ("sep"), for the chart
    total: Decimal
    income: Decimal
    partial: bool = False  # month in progress for the chosen accounts: drawn in a light color
    # Unusual month ("up"/"down") against the usual (see `analysis.anomalies`); None when it is
    # not or is not compared. The usual is None with fewer than three reference months.
    spent_flag: anomalies.Direction | None = None
    spent_habitual: Decimal | None = None
    income_flag: anomalies.Direction | None = None
    income_habitual: Decimal | None = None


@dataclass(frozen=True)
class AccountTotal:
    key: str
    label: str
    total: Decimal
    usd: Decimal


@dataclass(frozen=True)
class Summary:
    option: MonthOption
    coverage: list[Coverage]
    total: Decimal
    income: Decimal
    third_party: Decimal  # the month's third-party transfers: not spending, but money out
    net: (
        Decimal | None
    )  # income - expenses - third party; None if the chosen accounts have no income flow
    savings_rate: float | None  # net / income; None without income or with incomplete income
    income_through: date | None  # income known only up to here (a bank cuts earlier)
    regular_total: Decimal
    one_offs: Decimal
    habitual: Decimal | None
    usd: Decimal
    usd_in_dop: Decimal | None
    rate: Rate | None
    categories: list[CategoryLine]
    changes: list[Change]
    trend: list[MonthTotal]
    by_account: list[AccountTotal]
    # Only with some accounts chosen (otherwise all zero and False):
    needs_income: bool = False  # no bank account chosen: no flow to show
    to_cards: Decimal = _ZERO  # payments from the chosen accounts to cards not chosen
    to_own: Decimal = _ZERO  # "Between my accounts" leaving the chosen ones
    # Owed to you: what is pending of the month's group expenses you paid (by expense date) in
    # the chosen accounts, in RD$. It subtracts from nothing: it is no longer in the expenses.
    owed: Decimal = _ZERO
    # Open currency exchanges that started in the month (their oldest leg) with some leg in the
    # chosen accounts: what is pending, in RD$. Informational: not subtracted.
    exchanges_pending: Decimal = _ZERO
    # "What happened": if the month is unusual, the merchants that explain it most (expense,
    # then income).
    what_happened: list[anomalies.Contribution] = field(default_factory=list)
    # The month's investment contributions from the chosen accounts, in RD$ (US$ without a rate
    # do not count). They do not subtract from what you kept: "of that, RD$ X went to
    # investments".
    invested: Decimal = _ZERO
    # The month's withdrawals stored in the cash box from the chosen accounts, in RD$ (US$
    # without a rate do not count). They do not subtract either: "of that, RD$ X went to the
    # cash box".
    to_cash_box: Decimal = _ZERO
    # The month's income by category, largest first (they add up to `income`).
    income_lines: list[IncomeLine] = field(default_factory=list)
    # Of `total`, what is still provisional (from bank alerts, without a statement yet), RD$.
    provisional: Decimal = _ZERO


@dataclass(frozen=True)
class _Converted:
    """A movement already converted to RD$."""

    move: Movement
    dop: Decimal


def month_label(month: str) -> str:
    year, number = month.split("-")
    return f"{_MONTHS[int(number) - 1].capitalize()} {year}"


def _short_label(month: str) -> str:
    return _MONTHS[int(month.split("-")[1]) - 1][:3]


def selection(
    accounts: Sequence[AccountInfo], selected: Collection[str] | None
) -> frozenset[str] | None:
    """The chosen accounts; None if they are all of them (or none was chosen)."""
    if selected is None:
        return None
    chosen = frozenset(selected)
    return None if chosen >= {a.key for a in accounts} else chosen


def month_options(
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    selected: Collection[str] | None = None,
    today: date | None = None,
) -> list[MonthOption]:
    """From the newest month with expenses to the oldest, without gaps.

    Only expenses bound the months: stray income or transfers do not create months. Months
    before the first one with card movements do not count either: an older bank statement
    would bring months with only part of the spending.

    With `selected` (account keys) the months are the same, so the picker does not change, but
    a month is partial according to the chosen accounts (see `_coverage_accounts`).

    With `today`: when the newest month with expenses is the one before today's, today's month
    (in progress, nothing spent yet) comes first, so the Summary can open it on the 1st.
    """
    found = {m.month for m in movements if m.kind == "expense"}
    first_card = _first_card_month(movements, accounts)
    if first_card is not None:
        found = {m for m in found if m >= first_card}
    if not found:
        return []
    newest = max(found)
    if today is not None:
        current = f"{today.year:04d}-{today.month:02d}"
        if spending.months_back(current, 2)[0] == newest:
            newest = current
    span = _month_span(min(found), newest)
    chosen = selection(accounts, selected)
    if chosen is None:
        active = _active_cards(accounts)
        return [MonthOption(m, month_label(m), not _covered(active, m)) for m in reversed(span)]
    # As without a selection: with no active account among the chosen ones, every month is partial.
    cuts = [a.through for a in _coverage_accounts(accounts, chosen) if a.through]
    return [MonthOption(m, month_label(m), not _covered(cuts, m)) for m in reversed(span)]


def _coverage_accounts(
    accounts: Sequence[AccountInfo], chosen: frozenset[str]
) -> list[AccountInfo]:
    """The chosen accounts that decide whether a month is complete.

    The chosen cards, as without a selection; if there are none, the chosen bank accounts. Only
    the active ones (a recent cut compared with the newest of their kind among all accounts); if
    none is active, every month stays partial, as without a selection.
    """
    picked = [a for a in accounts if a.key in chosen]
    cards = [a for a in picked if a.kind == _CREDIT_CARD]
    group = cards or [a for a in picked if a.kind in _BANK_KINDS]
    kinds = {a.kind for a in group}
    newest = max(
        (a.through for a in accounts if a.through and _same_group(a.kind, kinds)), default=None
    )
    return [
        a
        for a in group
        if a.through is not None
        and newest is not None
        and newest - a.through <= timedelta(days=ACTIVE_DAYS)
    ]


def _same_group(kind: str, kinds: set[str]) -> bool:
    if kind == _CREDIT_CARD:
        return _CREDIT_CARD in kinds
    return kind in _BANK_KINDS and bool(kinds & set(_BANK_KINDS))


def build_summary(
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    rates: Mapping[str, Rate],
    month: str,
    selected: Collection[str] | None = None,
    groups: Mapping[int, ledger.GroupState] | None = None,
    exchange_states: Mapping[int, ExchangeState] | None = None,
    today: date | None = None,
) -> Summary:
    """The month's summary. Takes every kind of movement (`spending.load_all`).

    Expenses, dollars and comparisons come only from expense movements; income adds up
    separately and transfers count in neither, except third-party transfers: they are not
    spending, but they subtract from what you kept (`net`). An investment contribution
    (`categories.INVESTMENT`) does not subtract: it is part of what you kept (`invested`).

    `selected`: keys of the accounts to look at (None: all). Transfers are already detected
    across all accounts, so a card payment is still a transfer even if the card is not chosen;
    here only the movements and the accounts are trimmed.

    `groups` (`ledger.states`) and `exchange_states` (`exchanges.states`): for "Owed to you" and
    "Pending exchanges"; without them, zero. `today`: as in `month_options` (today's month with
    nothing spent yet is a month).
    """
    chosen = selection(accounts, selected)
    options = month_options(movements, accounts, chosen, today)
    option = next((o for o in options if o.month == month), None)
    if option is None:
        raise LookupError(t("web.month_without_movements", month=month))
    mine = movements if chosen is None else [m for m in movements if m.account in chosen]
    seen = accounts if chosen is None else [a for a in accounts if a.key in chosen]
    incomes = _convert((m for m in mine if m.kind == "income"), rates)
    expenses = [m for m in mine if m.kind == "expense"]
    converted = _convert(expenses, rates)
    current = [p for p in converted if p.move.month == month]
    baseline = [] if option.partial else _baseline(options, month)
    total, one_offs = _sum(current), _sum(p for p in current if p.move.one_off)
    chosen_rate = rate_for(rates, month)
    usd = sum((m.amount for m in _in_usd(expenses, month)), _ZERO)
    income = -_sum(p for p in incomes if p.move.month == month)
    third_party = _third_party(mine, rates, month)
    outflow = total + third_party
    lines = _category_lines(current, converted, baseline, total)
    income_through = _income_through(seen, month)
    # Without chosen bank accounts (only cards, or the cash box) there is no flow: income arrives
    # at the bank.
    needs_income = chosen is not None and not any(a.kind in _BANK_KINDS for a in seen)
    savings_rate = None if income_through or needs_income else _savings_rate(income, outflow)
    to_cards, to_own = _to_unselected(mine, accounts, chosen, rates, month)
    flow = _Flow(converted, incomes, options, seen, needs_income)
    trend = _trend(flow, month)
    return Summary(
        option=option,
        coverage=_coverages(accounts, chosen, month),
        total=total,
        income=income,
        third_party=third_party,
        net=None if needs_income else income - outflow,
        savings_rate=savings_rate,
        income_through=income_through,
        regular_total=total - one_offs,
        one_offs=one_offs,
        habitual=_habitual_total(converted, baseline),
        usd=usd,
        usd_in_dop=_usd_in_dop(usd, chosen_rate),
        rate=chosen_rate,
        categories=lines,
        changes=_changes(lines),
        trend=trend,
        by_account=_by_account(current, expenses, accounts, month),
        needs_income=needs_income,
        to_cards=to_cards,
        to_own=to_own,
        owed=_owed(movements, groups or {}, chosen, rates, month),
        exchanges_pending=_exchanges_pending(exchange_states or {}, chosen, month),
        what_happened=_what_happened(flow, trend[-1]),
        invested=_invested(mine, rates, month),
        to_cash_box=cash_box.stored_dop(mine, rates, month),
        income_lines=_income_lines(p for p in incomes if p.move.month == month),
        provisional=_sum(p for p in current if p.move.provisional),
    )


def _income_lines(incomes: Iterable[_Converted]) -> list[IncomeLine]:
    """Income by category (each one apart: crypto is not mixed with other income),
    largest first; ties by name."""
    amounts: dict[str, Decimal] = defaultdict(Decimal)
    counts: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    for item in incomes:
        ref = item.move.ref
        names.setdefault(ref, item.move.category)
        amounts[ref] -= item.dop
        counts[ref] += 1
    refs = sorted(amounts, key=lambda ref: (-amounts[ref], names[ref]))
    return [IncomeLine(names[ref], amounts[ref], counts[ref], ref) for ref in refs if amounts[ref]]


def _invested(movements: Iterable[Movement], rates: Mapping[str, Rate], month: str) -> Decimal:
    """The month's investment contributions in RD$ (the `categories.INVESTMENT` category)."""
    chosen = (m for m in movements if m.ref == categories.INVESTMENT and m.month == month)
    return _sum(_convert(chosen, rates))


def _owed(
    movements: Sequence[Movement],
    groups: Mapping[int, ledger.GroupState],
    chosen: frozenset[str] | None,
    rates: Mapping[str, Rate],
    month: str,
) -> Decimal:
    """What is still owed to you for the month's group expenses (by expense date), in RD$ (US$
    without a rate do not count). With chosen accounts, only those paid from them."""
    accounts = {m.fingerprint: m.account for m in movements}
    total = _ZERO
    for state in groups.values():
        for item in state.entries:
            fp = item.entry.fingerprint
            if item.pending <= 0 or item.day.strftime("%Y-%m") != month:
                continue
            if chosen and (fp is None or accounts.get(fp) not in chosen):
                continue
            value = to_dop(item.pending, item.currency, rate_for(rates, month))
            total += value or _ZERO
    return total


def _exchanges_pending(
    states: Mapping[int, ExchangeState], chosen: frozenset[str] | None, month: str
) -> Decimal:
    picked = (
        s
        for s in states.values()
        if s.month == month and (chosen is None or any(leg.account in chosen for leg in s.legs))
    )
    return sum((s.pending_dop for s in picked), _ZERO)


def coverage_for(
    accounts: Sequence[AccountInfo], selected: Collection[str] | None, month: str
) -> list[Coverage]:
    """The month's coverage with the chosen accounts (the one on the Summary cards)."""
    return _coverages(accounts, selection(accounts, selected), month)


def _coverages(
    accounts: Sequence[AccountInfo], chosen: frozenset[str] | None, month: str
) -> list[Coverage]:
    if chosen is None:
        cards = [a for a in accounts if a.kind == _CREDIT_CARD]
        return [_coverage(a, month) for a in cards if _is_active(a, accounts)]
    return [_coverage(a, month) for a in _coverage_accounts(accounts, chosen)]


def _to_unselected(
    mine: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    chosen: frozenset[str] | None,
    rates: Mapping[str, Rate],
    month: str,
) -> tuple[Decimal, Decimal]:
    """(payments to cards, moved to other accounts) leaving the chosen accounts.

    It is approximate: the exact account each outflow went to is unknown, so every outflow of
    the category counts as soon as some account of the other kind is not chosen (a card for
    the payments, a bank account for "Between my accounts"), even if that particular outflow
    went to a chosen account. With all chosen, nothing.
    """
    if chosen is None:
        return _ZERO, _ZERO
    kinds = {a.key: a.kind for a in accounts}
    card_left = any(a.kind == _CREDIT_CARD and a.key not in chosen for a in accounts)
    bank_left = any(a.kind in _BANK_KINDS and a.key not in chosen for a in accounts)
    out = [m for m in mine if m.month == month and m.amount > 0]
    payments = [
        m for m in out if m.ref == categories.CARD_PAYMENT and kinds.get(m.account) != _CREDIT_CARD
    ]
    moved = [m for m in out if m.ref == categories.OWN_TRANSFER]
    return (
        _sum(_convert(payments, rates)) if card_left else _ZERO,
        _sum(_convert(moved, rates)) if bank_left else _ZERO,
    )


def _third_party(movements: Iterable[Movement], rates: Mapping[str, Rate], month: str) -> Decimal:
    """The month's third-party transfers in RD$; a credit corrected into the category subtracts."""
    chosen = (m for m in movements if m.ref == categories.THIRD_PARTY and m.month == month)
    return _sum(_convert(chosen, rates))


def _savings_rate(income: Decimal, outflow: Decimal) -> float | None:
    """What you kept / income; None without income or with negligible income against what went
    out.

    `outflow` is spending plus third-party transfers.
    """
    if income <= 0 or income < MIN_INCOME_SHARE * outflow:
        return None
    return float((income - outflow) / income)


def _income_through(accounts: Sequence[AccountInfo], month: str) -> date | None:
    """The oldest cut of the bank accounts if it does not reach the end of the month; else None.

    A checking account can cut mid-month: what came in afterwards (sometimes the second
    fortnight's pay) arrives with the next statement. Only accounts active for the month count:
    their last cut is from the previous month or later. An account without recent statements
    (closed, or with missing statements) does not mark the following months incomplete.
    """
    start = _previous_month_start(month)
    cuts = [
        a.through
        for a in accounts
        if a.kind in _BANK_KINDS and a.through is not None and a.through >= start
    ]
    if not cuts or min(cuts) >= _month_end(month):
        return None
    return min(cuts)


def _previous_month_start(month: str) -> date:
    first = date(int(month[:4]), int(month[5:]), 1)
    return (first - timedelta(days=1)).replace(day=1)


def _first_card_month(movements: Sequence[Movement], accounts: Sequence[AccountInfo]) -> str | None:
    cards = {a.key for a in accounts if a.kind == _CREDIT_CARD}
    return min((m.month for m in movements if m.account in cards), default=None)


def _month_span(first: str, last: str) -> list[str]:
    count = (int(last[:4]) - int(first[:4])) * 12 + int(last[5:]) - int(first[5:]) + 1
    return list(spending.months_back(last, count))


def _active_cards(accounts: Iterable[AccountInfo]) -> list[date]:
    cuts = [a.through for a in accounts if a.kind == _CREDIT_CARD and a.through]
    if not cuts:
        return []
    newest = max(cuts)
    return [c for c in cuts if newest - c <= timedelta(days=ACTIVE_DAYS)]


def _usd_in_dop(usd: Decimal, rate: Rate | None) -> Decimal | None:
    if usd == 0:
        return _ZERO
    return None if rate is None else usd * rate.value


def _is_active(account: AccountInfo, accounts: Sequence[AccountInfo]) -> bool:
    return account.through is not None and account.through in _active_cards(accounts)


def _month_end(month: str) -> date:
    year, number = int(month[:4]), int(month[5:])
    return date(year, number, calendar.monthrange(year, number)[1])


def _covered(active: Sequence[date], month: str) -> bool:
    return bool(active) and all(through >= _month_end(month) for through in active)


def _coverage(account: AccountInfo, month: str) -> Coverage:
    done = account.through is not None and account.through >= _month_end(month)
    return Coverage(account.key, account.label, account.through, done)


def _convert(movements: Iterable[Movement], rates: Mapping[str, Rate]) -> list[_Converted]:
    """To RD$ with each month's rate; US$ without any rate are left out."""
    converted = []
    for move in movements:
        dop = to_dop(move.amount, move.currency, rate_for(rates, move.month))
        if dop is not None:
            converted.append(_Converted(move, dop))
    return converted


def _in_usd(movements: Iterable[Movement], month: str) -> list[Movement]:
    return [m for m in movements if m.month == month and m.currency == "USD"]


def _sum(items: Iterable[_Converted]) -> Decimal:
    return sum((p.dop for p in items), _ZERO)


def _baseline(options: Sequence[MonthOption], month: str) -> list[str]:
    earlier = sorted(o.month for o in options if o.month < month and not o.partial)
    return earlier[-BASELINE_MONTHS:]


def _habitual_total(converted: Sequence[_Converted], baseline: Sequence[str]) -> Decimal | None:
    if not baseline:
        return None
    regular = [p for p in converted if not p.move.one_off]
    return statistics.median(_sum(p for p in regular if p.move.month == m) for m in baseline)


def _purchases(items: Iterable[_Converted]) -> int:
    return sum(1 for p in items if p.move.amount > 0)


def _category_lines(
    current: Sequence[_Converted],
    converted: Sequence[_Converted],
    baseline: Sequence[str],
    total: Decimal,
) -> list[CategoryLine]:
    now = _group(current)
    before = _group(p for p in converted if p.move.month in baseline and not p.move.one_off)
    names = set(now) | set(before)
    lines = [
        _line(name, now.get(name, []), before.get(name, []), baseline, total) for name in names
    ]
    return sorted(lines, key=lambda line: (-line.amount, line.category))


def _group(items: Iterable[_Converted]) -> dict[str, list[_Converted]]:
    groups: defaultdict[str, list[_Converted]] = defaultdict(list)
    for item in items:
        groups[item.move.category].append(item)
    return groups


def _line(
    name: str,
    now: Sequence[_Converted],
    before: Sequence[_Converted],
    baseline: Sequence[str],
    total: Decimal,
) -> CategoryLine:
    amount = _sum(now)
    habitual = habitual_count = diff = None
    same = False
    if baseline:
        habitual = statistics.median(_sum(p for p in before if p.move.month == m) for m in baseline)
        habitual_count = round(
            statistics.median(_purchases(p for p in before if p.move.month == m) for m in baseline)
        )
        diff = amount - habitual
        same = abs(diff) < max(SAME_FLOOR, habitual * SAME_SHARE)
    return CategoryLine(
        category=name,
        amount=amount,
        habitual=habitual,
        diff=diff,
        same=same,
        share=float(max(amount, _ZERO) / total) if total > 0 else 0.0,
        one_offs=_sum(p for p in now if p.move.one_off),
        purchases=_purchases(now),
        habitual_purchases=habitual_count,
    )


def _changes(lines: Sequence[CategoryLine]) -> list[Change]:
    moved = [line for line in lines if line.diff is not None and not line.same]
    moved.sort(key=lambda line: (-abs(line.diff or _ZERO), line.category))
    return [
        Change(line.category, line.diff, line.one_offs, line.purchases, line.habitual_purchases)
        for line in moved[:TOP_CHANGES]
        if line.diff is not None
    ]


@dataclass(frozen=True)
class _Flow:
    """What the trend and the unusual months need, already in RD$."""

    converted: Sequence[_Converted]  # expenses
    incomes: Sequence[_Converted]  # income (negative)
    options: Sequence[MonthOption]
    accounts: Sequence[AccountInfo]  # the chosen ones
    needs_income: bool

    def spent(self, month: str, regular: bool = False) -> Decimal:
        return _sum(
            p for p in self.converted if p.move.month == month and not (regular and p.move.one_off)
        )

    def income(self, month: str) -> Decimal:
        return -_sum(p for p in self.incomes if p.move.month == month)


def _trend(flow: _Flow, month: str) -> list[MonthTotal]:
    partial = {o.month: o.partial for o in flow.options}
    oldest = flow.options[-1].month
    months = [m for m in spending.months_back(month, TREND_MONTHS) if m >= oldest]
    return [_month_total(flow, m, partial.get(m, False)) for m in months]


def _month_total(flow: _Flow, month: str, partial: bool) -> MonthTotal:
    """The month's total with its unusual-month flags (see `analysis.anomalies`)."""
    total, income = flow.spent(month), flow.income(month)
    baseline = _baseline(flow.options, month)
    spent_usual = anomalies.habitual([flow.spent(m, regular=True) for m in baseline])
    income_usual = anomalies.habitual([flow.income(m) for m in baseline])
    income_known = not flow.needs_income and _income_through(flow.accounts, month) is None
    compare = not partial
    return MonthTotal(
        month,
        _short_label(month),
        total,
        income,
        partial,
        spent_flag=_flag(total, spent_usual) if compare else None,
        spent_habitual=spent_usual,
        income_flag=_flag(income, income_usual) if compare and income_known else None,
        income_habitual=income_usual,
    )


def _flag(value: Decimal, usual: Decimal | None) -> anomalies.Direction | None:
    return None if usual is None else anomalies.deviation(value, usual)


def _what_happened(flow: _Flow, chosen: MonthTotal) -> list[anomalies.Contribution]:
    """The merchants that explain the chosen month's deviation: spending first, then income."""
    baseline = _baseline(flow.options, chosen.month)
    found: list[anomalies.Contribution] = []
    if chosen.spent_flag is not None:
        found += anomalies.contributions(
            _entries(flow.converted, chosen.month),
            {m: _entries(flow.converted, m, regular=True) for m in baseline},
            chosen.spent_flag,
            "expense",
        )
    if chosen.income_flag is not None:
        found += anomalies.contributions(
            _entries(flow.incomes, chosen.month, sign=-1),
            {m: _entries(flow.incomes, m, sign=-1) for m in baseline},
            chosen.income_flag,
            "income",
        )
    return found


def _entries(
    items: Sequence[_Converted], month: str, *, regular: bool = False, sign: int = 1
) -> list[anomalies.Entry]:
    return [
        anomalies.Entry(p.move, p.dop * sign)
        for p in items
        if p.move.month == month and not (regular and p.move.one_off)
    ]


def _by_account(
    current: Sequence[_Converted],
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    month: str,
) -> list[AccountTotal]:
    labels = {a.key: a.label for a in accounts}
    usd: defaultdict[str, Decimal] = defaultdict(Decimal)
    for move in _in_usd(movements, month):
        usd[move.account] += move.amount
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    for item in current:
        totals[item.move.account] += item.dop
    rows = [AccountTotal(k, account_label(labels, k), t, usd[k]) for k, t in totals.items()]
    return sorted(rows, key=lambda row: (-row.total, row.key))
