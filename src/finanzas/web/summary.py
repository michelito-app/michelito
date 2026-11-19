"""Consultas del Resumen: todo en RD$, mes de calendario por fecha de compra."""

from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from finanzas.analysis import anomalies, cash_box, categories, spending
from finanzas.analysis.accounts import AccountInfo
from finanzas.analysis.exchanges import ExchangeState
from finanzas.analysis.rates import Rate, rate_for, to_dop
from finanzas.analysis.shared import ExpenseState
from finanzas.analysis.spending import Movement

BASELINE_MONTHS = 6
SAME_FLOOR = Decimal(500)
SAME_SHARE = Decimal("0.05")
MIN_INCOME_SHARE = Decimal("0.01")  # ingreso menor a este % del gasto: sin % de ahorro
TOP_CHANGES = 3
TREND_MONTHS = 12
ACTIVE_DAYS = 45

_CREDIT_CARD = "credit_card"
_BANK_KINDS = ("savings", "checking")
_ZERO = Decimal(0)
_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


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
    """Los ingresos del mes de una categoría (Salario, Cripto, Otros ingresos…), en RD$."""

    category: str
    amount: Decimal  # positivo: lo que entró
    count: int
    ref: str = ""  # la referencia estable (`Movement.ref`): renombrarla no la cambia


@dataclass(frozen=True)
class MonthTotal:
    month: str
    label: str  # abreviado ("sep"), para el gráfico
    total: Decimal
    income: Decimal
    partial: bool = False  # mes en curso para las cuentas elegidas: va en color claro
    # Mes atípico ("up"/"down") frente a lo habitual (ver `analysis.anomalies`); None si no lo
    # es o no se compara. Lo habitual es None con menos de tres meses de referencia.
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
    third_party: Decimal  # transferencias a terceros del mes: no son gasto, pero salen
    net: Decimal | None  # ingresos − gastos − terceros; None si las cuentas elegidas no tienen
    savings_rate: float | None  # net / income; None sin ingresos o con ingresos incompletos
    income_through: date | None  # ingresos conocidos solo hasta aquí (un banco corta antes)
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
    # Solo con algunas cuentas elegidas (si no, todo en cero y False):
    needs_income: bool = False  # ninguna cuenta bancaria elegida: no hay flujo que mostrar
    to_cards: Decimal = _ZERO  # pagos desde las elegidas a tarjetas no elegidas
    to_own: Decimal = _ZERO  # "Entre mis cuentas" que sale de las elegidas
    # Te deben: lo pendiente de los gastos compartidos del mes (por fecha del gasto) de las
    # cuentas elegidas, en RD$. No resta de nada: ya no está en los gastos.
    owed: Decimal = _ZERO
    # Cambios de divisas abiertos que empezaron en el mes (su pata más antigua) con alguna pata
    # en las cuentas elegidas: lo pendiente en RD$. Informativo: no se resta.
    exchanges_pending: Decimal = _ZERO
    # "Qué pasó": si el mes es atípico, los comercios que más lo explican (gasto, luego ingreso).
    what_happened: list[anomalies.Contribution] = field(default_factory=list)
    # Aportes a inversiones del mes desde las cuentas elegidas, en RD$ (los US$ sin tasa no
    # cuentan). No restan de lo que te quedó: «de eso, RD$ X fueron a inversiones».
    invested: Decimal = _ZERO
    # Retiros del mes guardados en la caja fuerte desde las cuentas elegidas, en RD$ (los US$ sin
    # tasa no cuentan). Tampoco restan: «de eso, RD$ X fueron a la caja fuerte».
    to_cash_box: Decimal = _ZERO
    # Los ingresos del mes por categoría, de mayor a menor (suman `income`).
    income_lines: list[IncomeLine] = field(default_factory=list)


@dataclass(frozen=True)
class _Peso:
    """Un movimiento ya convertido a RD$."""

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
    """Las cuentas elegidas; None si son todas (o ninguna se eligió)."""
    if selected is None:
        return None
    chosen = frozenset(selected)
    return None if chosen >= {a.key for a in accounts} else chosen


def month_options(
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    selected: Collection[str] | None = None,
) -> list[MonthOption]:
    """Del mes más reciente al más antiguo con gastos, sin huecos.

    Solo los gastos delimitan los meses: ingresos o transferencias sueltas no crean meses.
    Tampoco cuentan los meses anteriores al primero con movimientos de tarjeta: un estado
    bancario más viejo traería meses con solo una parte del gasto.

    Con `selected` (claves de cuentas) los meses son los mismos, para que el selector no
    cambie, pero un mes es parcial según las cuentas elegidas (ver `_coverage_cuts`).
    """
    found = {m.month for m in movements if m.kind == "gasto"}
    first_card = _first_card_month(movements, accounts)
    if first_card is not None:
        found = {m for m in found if m >= first_card}
    if not found:
        return []
    newest = max(found)
    span = _month_span(min(found), newest)
    chosen = selection(accounts, selected)
    if chosen is None:
        active = _active_cards(accounts)
        return [MonthOption(m, month_label(m), not _covered(active, m)) for m in reversed(span)]
    # Como sin selección: sin ninguna cuenta activa entre las elegidas, todo mes es parcial.
    cuts = [a.through for a in _coverage_accounts(accounts, chosen) if a.through]
    return [MonthOption(m, month_label(m), not _covered(cuts, m)) for m in reversed(span)]


def _coverage_accounts(
    accounts: Sequence[AccountInfo], chosen: frozenset[str]
) -> list[AccountInfo]:
    """Cuentas elegidas que deciden si un mes está completo.

    Las tarjetas elegidas, como sin selección; si no hay ninguna, las cuentas bancarias
    elegidas. Solo las activas (corte reciente frente al más nuevo de su tipo entre todas las
    cuentas); si ninguna lo está, todo mes queda parcial, igual que sin selección.
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
    shared_states: Mapping[str, ExpenseState] | None = None,
    exchange_states: Mapping[int, ExchangeState] | None = None,
) -> Summary:
    """Resumen del mes. Recibe todos los tipos de movimiento (`spending.load_all`).

    Los gastos, los dólares y las comparaciones salen solo de los movimientos de tipo gasto;
    los ingresos suman aparte y las transferencias no cuentan en ninguno, salvo las
    transferencias a terceros: no son gasto, pero restan de lo que te quedó (`net`). Un aporte a
    una inversión ("Inversiones") no resta: es parte de lo que te quedó (`invested`).

    `selected`: claves de las cuentas a mirar (None: todas). Las transferencias ya vienen
    detectadas sobre todas las cuentas, así que un pago de tarjeta sigue siendo transferencia
    aunque la tarjeta no esté elegida; aquí solo se recortan los movimientos y las cuentas.

    `shared_states` (el estado de cada gasto compartido, `shared.by_expense`) y `exchange_states`
    (`exchanges.states`): para "Te deben"
    y "Cambios pendientes"; sin ellos, en cero.
    """
    chosen = selection(accounts, selected)
    options = month_options(movements, accounts, chosen)
    option = next((o for o in options if o.month == month), None)
    if option is None:
        raise LookupError(f"mes sin movimientos: {month}")
    mine = movements if chosen is None else [m for m in movements if m.account in chosen]
    seen = accounts if chosen is None else [a for a in accounts if a.key in chosen]
    incomes = _convert((m for m in mine if m.kind == "ingreso"), rates)
    expenses = [m for m in mine if m.kind == "gasto"]
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
    # Sin cuentas bancarias elegidas (solo tarjetas, o la caja fuerte) no hay flujo: los ingresos
    # llegan al banco.
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
        owed=_owed(movements, shared_states or {}, chosen, rates, month),
        exchanges_pending=_exchanges_pending(exchange_states or {}, chosen, month),
        what_happened=_what_happened(flow, trend[-1]),
        invested=_invested(mine, rates, month),
        to_cash_box=cash_box.stored_dop(mine, rates, month),
        income_lines=_income_lines(p for p in incomes if p.move.month == month),
    )


def _income_lines(incomes: Iterable[_Peso]) -> list[IncomeLine]:
    """Los ingresos por categoría (cada una aparte: «Cripto» no se mezcla con «Otros
    ingresos»), de mayor a menor; en empate, por nombre."""
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
    """Aportes a inversiones del mes en RD$ (la categoría "Inversiones")."""
    chosen = (m for m in movements if m.ref == categories.INVESTMENT and m.month == month)
    return _sum(_convert(chosen, rates))


def _owed(
    movements: Sequence[Movement],
    states: Mapping[str, ExpenseState],
    chosen: frozenset[str] | None,
    rates: Mapping[str, Rate],
    month: str,
) -> Decimal:
    """Pendiente de los gastos compartidos del mes en las cuentas elegidas, en RD$ (los US$ sin
    tasa no cuentan)."""
    total = _ZERO
    for move in movements:
        state = states.get(move.fingerprint)
        if state is None or move.month != month or (chosen and move.account not in chosen):
            continue
        total += to_dop(state.pending, move.currency, rate_for(rates, move.month)) or _ZERO
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
    """La cobertura del mes con las cuentas elegidas (la de las fichas del Resumen)."""
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
    """(pagos a tarjetas, movido a otras cuentas) que salen de las cuentas elegidas.

    Es aproximado: no se sabe a qué cuenta exacta fue cada salida, así que se cuenta toda
    salida de la categoría en cuanto falta por elegir alguna cuenta del otro tipo (una
    tarjeta para los pagos, una cuenta bancaria para "Entre mis cuentas"), aunque esa salida
    en particular haya ido a una cuenta elegida. Con todas elegidas, nada.
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
    """Transferencias a terceros del mes en RD$; un crédito corregido a la categoría resta."""
    chosen = (m for m in movements if m.ref == categories.THIRD_PARTY and m.month == month)
    return _sum(_convert(chosen, rates))


def _savings_rate(income: Decimal, outflow: Decimal) -> float | None:
    """Te quedó / ingresos; None sin ingresos o con ingresos despreciables frente a lo que salió.

    `outflow` es el gasto más las transferencias a terceros.
    """
    if income <= 0 or income < MIN_INCOME_SHARE * outflow:
        return None
    return float((income - outflow) / income)


def _income_through(accounts: Sequence[AccountInfo], month: str) -> date | None:
    """Corte más antiguo de las cuentas bancarias si no llega al fin del mes; si no, None.

    Una cuenta corriente puede cortar a mitad de mes: lo que entró después (a veces la
    segunda quincena) llega con el estado siguiente. Solo cuentan las cuentas activas para
    el mes: su último corte es del mes anterior o después. Una cuenta sin estados recientes
    (cerrada, o con estados que faltan) no marca incompletos los meses que siguen.
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


def _convert(movements: Iterable[Movement], rates: Mapping[str, Rate]) -> list[_Peso]:
    """A RD$ con la tasa de cada mes; los US$ sin ninguna tasa quedan fuera."""
    converted = []
    for move in movements:
        dop = to_dop(move.amount, move.currency, rate_for(rates, move.month))
        if dop is not None:
            converted.append(_Peso(move, dop))
    return converted


def _in_usd(movements: Iterable[Movement], month: str) -> list[Movement]:
    return [m for m in movements if m.month == month and m.currency == "USD"]


def _sum(items: Iterable[_Peso]) -> Decimal:
    return sum((p.dop for p in items), _ZERO)


def _baseline(options: Sequence[MonthOption], month: str) -> list[str]:
    earlier = sorted(o.month for o in options if o.month < month and not o.partial)
    return earlier[-BASELINE_MONTHS:]


def _habitual_total(converted: Sequence[_Peso], baseline: Sequence[str]) -> Decimal | None:
    if not baseline:
        return None
    regular = [p for p in converted if not p.move.one_off]
    return statistics.median(_sum(p for p in regular if p.move.month == m) for m in baseline)


def _purchases(items: Iterable[_Peso]) -> int:
    return sum(1 for p in items if p.move.amount > 0)


def _category_lines(
    current: Sequence[_Peso], converted: Sequence[_Peso], baseline: Sequence[str], total: Decimal
) -> list[CategoryLine]:
    now = _group(current)
    before = _group(p for p in converted if p.move.month in baseline and not p.move.one_off)
    names = set(now) | set(before)
    lines = [
        _line(name, now.get(name, []), before.get(name, []), baseline, total) for name in names
    ]
    return sorted(lines, key=lambda line: (-line.amount, line.category))


def _group(items: Iterable[_Peso]) -> dict[str, list[_Peso]]:
    groups: defaultdict[str, list[_Peso]] = defaultdict(list)
    for item in items:
        groups[item.move.category].append(item)
    return groups


def _line(
    name: str,
    now: Sequence[_Peso],
    before: Sequence[_Peso],
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
    """Lo que hace falta para la tendencia y los meses atípicos, ya en RD$."""

    converted: Sequence[_Peso]  # gastos
    incomes: Sequence[_Peso]  # ingresos (negativos)
    options: Sequence[MonthOption]
    accounts: Sequence[AccountInfo]  # las elegidas
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
    """Total del mes con sus marcas de mes atípico (ver `analysis.anomalies`)."""
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
    """Los comercios que explican el desvío del mes elegido: gasto primero, luego ingresos."""
    baseline = _baseline(flow.options, chosen.month)
    found: list[anomalies.Contribution] = []
    if chosen.spent_flag is not None:
        found += anomalies.contributions(
            _entries(flow.converted, chosen.month),
            {m: _entries(flow.converted, m, regular=True) for m in baseline},
            chosen.spent_flag,
            "gasto",
        )
    if chosen.income_flag is not None:
        found += anomalies.contributions(
            _entries(flow.incomes, chosen.month, sign=-1),
            {m: _entries(flow.incomes, m, sign=-1) for m in baseline},
            chosen.income_flag,
            "ingreso",
        )
    return found


def _entries(
    items: Sequence[_Peso], month: str, *, regular: bool = False, sign: int = 1
) -> list[anomalies.Entry]:
    return [
        anomalies.Entry(p.move, p.dop * sign)
        for p in items
        if p.move.month == month and not (regular and p.move.one_off)
    ]


def _by_account(
    current: Sequence[_Peso],
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
    rows = [AccountTotal(k, labels.get(k, k), t, usd[k]) for k, t in totals.items()]
    return sorted(rows, key=lambda row: (-row.total, row.key))
