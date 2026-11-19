"""Cuentas de un grupo compartido: tu parte, lo reembolsado y lo que te deben, por gasto.

Un grupo tiene uno o más gastos, cada uno con su reparto. Con un gasto de monto A, tu parte S
sale de su reparto:
- "Éramos N": S = A / N, redondeada al centavo (mitad al par);
- "Mi parte: X": S = X (0 < X <= A);
- "Lo pagué por otra persona": S = 0.
Lo que te deben de ese gasto es A − S, en su moneda.

Los reembolsos (créditos enlazados y anotados a mano, juntos) se imputan **del gasto más viejo
al más nuevo** (FIFO): en orden (fecha, huella), cada uno salda primero lo que queda del gasto
más antiguo (orden (fecha, huella)) y lo que sobra pasa al siguiente. Un reembolso en otra
moneda que la del gasto que está saldando se convierte a la tasa del mes del reembolso (la de
`converted`); lo que sobra vuelve a su moneda con esa misma tasa y sigue al próximo gasto. Sin
tasa para convertir, el resto de ese reembolso no cuenta (`unconverted`: la interfaz avisa).
- Pendiente de un gasto P = A − S − lo imputado; el del grupo, P por moneda.
- Exceso: lo que sobra de los reembolsos tras saldar todos los gastos, en la moneda de cada
  reembolso; no cuenta ni baja tu parte (la interfaz avisa: suele ser un reembolso repetido).
- Lo que cuenta como gasto: S mientras P esté pendiente; con "No me lo van a pagar" (del grupo
  entero) S + P en cada gasto: lo pendiente vuelve a su gasto (en su mes), que por FIFO son los
  más recientes.

Los créditos enlazados dejan de ser ingreso o transferencia: son "Reembolso" (ver `spending`),
salvo uno que no contó nada por falta de tasa (si no, ese dinero desaparecería de los totales).

Reembolsos posibles de un grupo (`pick_credits`): créditos de cualquier cuenta y moneda (con
tasa para pasarlos a la moneda de cada gasto), desde el gasto más viejo hasta PICK_WINDOW_DAYS
días después del más nuevo (a veces pagan meses después), que no pasan lo gastado en el grupo
(uno igual a un único gasto en su moneda suele ser su devolución), y que no son salario, pagos de
tarjeta, envíos entre mis cuentas, intereses ni otro vínculo. Primero los que caben en lo
pendiente (con PENDING_MARGIN de margen). Se *sugiere* enlazar un crédito, sin que lo pidas
(`suggestions`), si está en la moneda del grupo, llega a lo sumo SUGGEST_WINDOW_DAYS días después
de un gasto del grupo y cabe en su pendiente; o si su descripción trae una palabra (de 4 letras o
más, sin acentos ni mayúsculas) de «Con quién» de un grupo con pendiente, en cualquier moneda
(con tasa) y hasta PICK_WINDOW_DAYS días después del gasto pendiente más viejo. Nunca se enlaza
solo.

La conversión se rehace en cada lectura con las tasas guardadas: si cambias a mano la tasa de un
mes, o llega la del BCRD de un mes que usaba la del anterior, lo reembolsado cambia con ella.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from finanzas.analysis import categories
from finanzas.analysis.links import Candidate, Links, Shared, SharedExpense
from finanzas.analysis.rates import Rate, rate_for

if TYPE_CHECKING:
    from finanzas.analysis.spending import Movement

PICK_WINDOW_DAYS = 120  # lo que lista "Me devolvieron parte" / "Es reembolso de…"
SUGGEST_WINDOW_DAYS = 14  # lo que se sugiere solo por monto ("¿Reembolso?")
PENDING_MARGIN = Decimal("0.05")  # en los selectores: "cabe en lo pendiente" con este margen
NAME_MIN_LETTERS = 4  # palabras de «Con quién» que cuentan para sugerir por nombre
_CENT = Decimal("0.01")
_NO_RATES: Mapping[str, Rate] = {}
_ZERO = Decimal(0)
_MANUAL = "manual:"
# Por debajo de esto, lo devuelto de más es redondeo de las conversiones: ni exceso ni aviso.
_MIN_EXCESS = {"DOP": Decimal(1), "USD": Decimal("0.05")}
# Créditos que nunca son el reembolso de un gasto compartido.
NOT_REIMBURSEMENT = frozenset(
    {
        categories.SALARY,
        categories.OWN_TRANSFER,
        categories.CARD_PAYMENT,
        categories.CURRENCY_EXCHANGE,
        categories.REIMBURSEMENT,
    }
)
# Movimientos que nunca son un gasto que se comparte («Agregar otro gasto»): retiros de
# efectivo, pagos de préstamo (los «AUT PAGO»), pagos de tarjeta, envíos entre mis cuentas y
# cambios de divisas.
NOT_SHARED_EXPENSE = frozenset(
    {
        categories.CASH,
        categories.LOANS,
        categories.CARD_PAYMENT,
        categories.OWN_TRANSFER,
        categories.CURRENCY_EXCHANGE,
    }
)
# Intereses que paga el banco: caen en "Otros ingresos" como un envío, pero nunca son reembolso.
_INTEREST = re.compile(r"\bINTERES(ES)?\b")
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ExpenseState:
    """Un gasto del grupo tras imputar los reembolsos (en su moneda)."""

    move: Movement
    split: SharedExpense
    amount: Decimal  # el gasto completo
    share: Decimal  # tu parte según su reparto
    reimbursed: Decimal  # lo imputado a este gasto
    pending: Decimal  # te deben de este gasto (0 con "No me lo van a pagar")
    written_off: Decimal  # lo pendiente que volvió a tu gasto

    @property
    def fingerprint(self) -> str:
        return self.move.fingerprint

    @property
    def currency(self) -> str:
        return self.move.currency

    @property
    def day(self) -> date:
        return self.move.day

    @property
    def owed(self) -> Decimal:
        return self.amount - self.share

    @property
    def counted(self) -> Decimal:
        """Lo que cuenta como tu gasto."""
        return self.share + self.written_off


@dataclass(frozen=True)
class Refund:
    """Un reembolso del grupo: un crédito enlazado (su huella) o uno a mano (`manual:<id>`)."""

    key: str
    day: date
    amount: Decimal  # positivo, en `currency`
    currency: str

    @property
    def is_manual(self) -> bool:
        return self.key.startswith(_MANUAL)


@dataclass(frozen=True)
class CurrencyTotals:
    currency: str
    share: Decimal
    reimbursed: Decimal
    pending: Decimal
    written_off: Decimal


@dataclass(frozen=True)
class SharedState:
    link: Shared
    expenses: tuple[ExpenseState, ...]  # del más viejo al más nuevo
    refunds: tuple[Refund, ...]  # en el orden en que se imputan
    excess_by: tuple[tuple[str, Decimal], ...] = ()  # sobra tras saldar todo, por moneda
    unconverted: tuple[str, ...] = ()  # reembolsos (o su resto) que no contaron: sin tasa
    uncounted: frozenset[str] = frozenset()  # créditos que no contaron nada (sin tasa)

    @property
    def id(self) -> int:
        return self.link.id

    @property
    def first(self) -> ExpenseState:
        return self.expenses[0]

    @property
    def title(self) -> str:
        """Nombre, si no «Con quién», si no el comercio del primer gasto."""
        move = self.first.move
        return self.link.name or self.link.with_whom or move.merchant or move.description

    @property
    def pending(self) -> dict[str, Decimal]:
        """Te deben, por moneda (solo las que tienen algo)."""
        return {t.currency: t.pending for t in self.totals if t.pending > 0}

    @property
    def excess(self) -> dict[str, Decimal]:
        return dict(self.excess_by)

    @property
    def has_pending(self) -> bool:
        return any(e.pending > 0 for e in self.expenses)

    @property
    def oldest_pending(self) -> ExpenseState | None:
        return next((e for e in self.expenses if e.pending > 0), None)

    @property
    def last_day(self) -> date:
        return max(e.day for e in self.expenses)

    @property
    def totals(self) -> tuple[CurrencyTotals, ...]:
        """Tu parte, lo devuelto, lo pendiente y lo dado por perdido de los gastos de cada
        moneda (RD$ antes que US$)."""
        found = []
        for currency in sorted({e.currency for e in self.expenses}):
            mine = [e for e in self.expenses if e.currency == currency]
            found.append(
                CurrencyTotals(
                    currency,
                    sum((e.share for e in mine), _ZERO),
                    sum((e.reimbursed for e in mine), _ZERO),
                    sum((e.pending for e in mine), _ZERO),
                    sum((e.written_off for e in mine), _ZERO),
                )
            )
        return tuple(found)

    def expense(self, fingerprint: str) -> ExpenseState | None:
        return next((e for e in self.expenses if e.fingerprint == fingerprint), None)


def nominal_share(split: SharedExpense, amount: Decimal) -> Decimal:
    if split.for_other:
        return _ZERO
    if split.people is not None:
        return (amount / split.people).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    return min(split.my_share if split.my_share is not None else amount, amount)


def convert(
    amount: Decimal, source: str, target: str, day: date, rates: Mapping[str, Rate]
) -> Decimal | None:
    """`amount` en `source` pasado a `target` a la tasa del mes de `day` (o la del mes anterior
    más cercano), al centavo. Tal cual si es la misma moneda; `None` sin tasa."""
    if source == target:
        return amount
    rate = rate_for(rates, day.strftime("%Y-%m"))
    if rate is None or rate.value <= 0:
        return None
    if source == "DOP" and target == "USD":
        return (amount / rate.value).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    if source == "USD" and target == "DOP":
        return (amount * rate.value).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    return None


def converted(credit: Movement, currency: str, rates: Mapping[str, Rate]) -> Decimal | None:
    """Lo que entró con el crédito (positivo), en `currency` (ver `convert`)."""
    return convert(-credit.amount, credit.currency, currency, credit.day, rates)


def gross(move: Movement) -> Decimal:
    """Monto del movimiento antes de repartir (el del estado de cuenta)."""
    return move.amount if move.gross is None else move.gross


def refunds_of(link: Shared, by_fingerprint: Mapping[str, Movement]) -> tuple[Refund, ...]:
    """Los reembolsos presentes del grupo, en el orden en que se imputan (fecha, huella)."""
    found = [
        Refund(fp, move.day, -move.amount, move.currency)
        for fp in link.reimbursements
        if (move := by_fingerprint.get(fp)) is not None and move.amount < 0
    ]
    found.extend(Refund(f"{_MANUAL}{m.id}", m.day, m.amount, m.currency) for m in link.manual)
    return tuple(sorted(found, key=lambda r: (r.day, r.key)))


def group_state(
    link: Shared,
    expenses: Sequence[Movement],
    by_fingerprint: Mapping[str, Movement],
    rates: Mapping[str, Rate] = _NO_RATES,
) -> SharedState:
    """Cuentas del grupo con estos gastos presentes (al menos uno; su monto es `gross`)."""
    ordered = sorted(expenses, key=lambda m: (m.day, m.fingerprint))
    splits = [link.split(m.fingerprint) or SharedExpense(m.fingerprint) for m in ordered]
    amounts = [gross(m) for m in ordered]
    shares = [nominal_share(s, a) for s, a in zip(splits, amounts, strict=True)]
    remaining = [a - s for a, s in zip(amounts, shares, strict=True)]
    applied = [_ZERO] * len(ordered)
    refunds = refunds_of(link, by_fingerprint)
    excess: dict[str, Decimal] = {}
    unconverted: list[str] = []
    uncounted: set[str] = set()
    for refund in refunds:
        left, counted, blocked = _impute(refund, ordered, remaining, applied, rates)
        if left <= 0:
            continue
        if not blocked:
            excess[refund.currency] = excess.get(refund.currency, _ZERO) + left
            continue
        # Lo que queda le tocaba a un gasto sin tasa para convertirlo: no cuenta.
        unconverted.append(refund.key)
        if not counted and not refund.is_manual:
            uncounted.add(refund.key)
    states = tuple(
        ExpenseState(
            move=move,
            split=split,
            amount=amount,
            share=share,
            reimbursed=applied[index],
            pending=_ZERO if link.written_off else remaining[index],
            written_off=remaining[index] if link.written_off else _ZERO,
        )
        for index, (move, split, amount, share) in enumerate(
            zip(ordered, splits, amounts, shares, strict=True)
        )
    )
    return SharedState(
        link=link,
        expenses=states,
        refunds=refunds,
        excess_by=tuple(sorted((c, v) for c, v in excess.items() if v >= _MIN_EXCESS[c])),
        unconverted=tuple(unconverted),
        uncounted=frozenset(uncounted),
    )


def _impute(
    refund: Refund,
    ordered: Sequence[Movement],
    remaining: list[Decimal],
    applied: list[Decimal],
    rates: Mapping[str, Rate],
) -> tuple[Decimal, bool, bool]:
    """Imputa un reembolso del gasto más viejo al más nuevo (actualiza `remaining` y
    `applied`). Un gasto sin tasa para convertir el reembolso se salta: sigue con los
    siguientes. Devuelve lo que sobra (en la moneda del reembolso), si algo contó y si se saltó
    algún gasto con pendiente por falta de tasa."""
    left, counted, blocked = refund.amount, False, False
    for index, move in enumerate(ordered):
        if left <= 0:
            break
        if remaining[index] <= 0:
            continue
        value = convert(left, refund.currency, move.currency, refund.day, rates)
        if value is None:
            blocked = True
            continue
        used = min(value, remaining[index])
        applied[index] += used
        remaining[index] -= used
        counted = counted or used > 0
        if used == value:
            return _ZERO, counted, blocked
        back = convert(used, move.currency, refund.currency, refund.day, rates) or _ZERO
        left = max(_ZERO, left - back)
    return left, counted, blocked


def states(
    movements: Sequence[Movement], links: Links, rates: Mapping[str, Rate] = _NO_RATES
) -> dict[int, SharedState]:
    """Cuentas de cada grupo con algún gasto presente (y que sigue siendo gasto), por id."""
    by_fp = {m.fingerprint: m for m in movements}
    found: dict[int, SharedState] = {}
    for link in links.shared:
        present = [
            move
            for e in link.expenses
            if (move := by_fp.get(e.fingerprint)) is not None and move.link == "shared"
        ]
        if present:
            found[link.id] = group_state(link, present, by_fp, rates)
    return found


def by_expense(groups: Mapping[int, SharedState]) -> dict[str, ExpenseState]:
    """El estado de cada gasto compartido presente, por su huella."""
    return {e.fingerprint: e for g in groups.values() for e in g.expenses}


def is_shareable(move: Movement) -> bool:
    return move.kind == "gasto" and gross(move) > 0


def is_eligible_credit(move: Movement, links: Links) -> bool:
    """Un crédito que puede ser reembolso: no es salario, pago, envío propio, intereses ni otro
    vínculo."""
    return (
        move.amount < 0
        and move.ref not in NOT_REIMBURSEMENT
        and not move.link
        and not links.is_linked(move.fingerprint)
        and not _INTEREST.search(move.description.upper())
    )


# --- Selectores y sugerencias --------------------------------------------------------------


def _in_currency(
    values: Iterable[tuple[Decimal, str]], currency: str, day: date, rates: Mapping[str, Rate]
) -> Decimal | None:
    """La suma de estos montos pasada a `currency` a la tasa del mes de `day` (None sin tasa)."""
    total = _ZERO
    for amount, source in values:
        value = convert(amount, source, currency, day, rates)
        if value is None:
            return None
        total += value
    return total


def _fits(state: SharedState, credit: Movement, rates: Mapping[str, Rate]) -> bool:
    """El crédito puede reembolsar el grupo: en fecha, con tasa y sin pasar lo gastado."""
    if credit.day < state.first.day:
        return False
    if (credit.day - state.last_day).days > PICK_WINDOW_DAYS:
        return False
    value = -credit.amount
    spent = _in_currency(
        ((e.amount, e.currency) for e in state.expenses), credit.currency, credit.day, rates
    )
    if spent is None:
        return False
    # Uno igual al único gasto, en su moneda, suele ser su devolución, no un reembolso.
    only = state.expenses[0] if len(state.expenses) == 1 else None
    if only is not None and only.currency == credit.currency:
        return value < spent
    return value <= spent


def _pending_in(state: SharedState, currency: str, day: date, rates: Mapping[str, Rate]) -> Decimal:
    found = _in_currency(((v, c) for c, v in state.pending.items()), currency, day, rates)
    return found or _ZERO


def _fits_pending(value: Decimal, pending: Decimal) -> bool:
    return pending > 0 and value <= pending * (1 + PENDING_MARGIN)


def candidates(
    state: SharedState,
    movements: Iterable[Movement],
    links: Links,
    rates: Mapping[str, Rate] = _NO_RATES,
) -> list[Movement]:
    """Créditos que pueden reembolsar el grupo, del más cercano al gasto más viejo al más
    lejano."""
    found = [m for m in movements if is_eligible_credit(m, links) and _fits(state, m, rates)]
    return sorted(found, key=lambda m: ((m.day - state.first.day).days, m.amount))


def pick_credits(
    state: SharedState,
    movements: Iterable[Movement],
    links: Links,
    rates: Mapping[str, Rate] = _NO_RATES,
) -> list[Candidate]:
    """El selector de reembolsos de un grupo: los `candidates` que caben en lo pendiente (con
    PENDING_MARGIN) primero y primarios, por fecha; luego los demás, por fecha."""
    marked = [
        Candidate(m, _fits_pending(-m.amount, _pending_in(state, m.currency, m.day, rates)))
        for m in candidates(state, movements, links, rates)
    ]
    return sorted(marked, key=lambda c: not c.primary)  # estable: conserva el orden por fecha


@dataclass(frozen=True)
class GroupCandidate:
    state: SharedState
    primary: bool


def groups_for(
    credit: Movement, groups: Mapping[int, SharedState], rates: Mapping[str, Rate] = _NO_RATES
) -> list[SharedState]:
    """Grupos con pendiente que este crédito podría reembolsar, el del gasto más cercano antes
    del crédito primero."""
    options = [g for g in groups.values() if g.has_pending and _fits(g, credit, rates)]
    return sorted(options, key=lambda g: (_distance(g, credit), g.id))


def _distance(state: SharedState, credit: Movement) -> int:
    return min((credit.day - e.day).days for e in state.expenses if e.day <= credit.day)


def pick_groups(
    credit: Movement, groups: Mapping[int, SharedState], rates: Mapping[str, Rate] = _NO_RATES
) -> list[GroupCandidate]:
    """El selector desde un crédito: los grupos con pendiente que puede reembolsar; primero (y
    primarios) aquellos cuyo pendiente lo cubre."""
    marked = [
        GroupCandidate(
            g, _fits_pending(-credit.amount, _pending_in(g, credit.currency, credit.day, rates))
        )
        for g in groups_for(credit, groups, rates)
    ]
    return sorted(marked, key=lambda c: not c.primary)


def pick_expenses(
    state: SharedState,
    movements: Iterable[Movement],
    links: Links,
    rates: Mapping[str, Rate] = _NO_RATES,
) -> list[Candidate]:
    """«Agregar otro gasto»: gastos sin vínculo a ±PICK_WINDOW_DAYS días de los del grupo.

    Fuera: retiros, préstamos, pagos de tarjeta, envíos propios y cambios (NOT_SHARED_EXPENSE).
    Primarios: si el grupo tiene exceso (te devolvieron de más: falta un gasto), los que están a
    ±PENDING_MARGIN de él (pasados a su moneda a la tasa de su mes), del más cercano al
    exceso al más lejano; luego los del mismo comercio que uno del grupo o cuya nota o
    descripción comparte una palabra con «Con quién», por cercanía de fecha. Después, el resto.
    """
    merchants = {e.move.merchant for e in state.expenses if e.move.merchant}
    names = name_words(state.link.with_whom)
    found: list[tuple[tuple[int, Decimal, int, str], Candidate]] = []
    for move in movements:
        if move.link or links.is_linked(move.fingerprint) or not is_shareable(move):
            continue
        if move.ref in NOT_SHARED_EXPENSE:
            continue
        distance = min(abs((move.day - e.day).days) for e in state.expenses)
        if distance > PICK_WINDOW_DAYS:
            continue
        gap = _excess_gap(state, move, rates)
        words = set(_words(f"{move.note} {move.description}"))
        related = move.merchant in merchants or bool(names & words)
        rank = 0 if gap is not None else 1 if related else 2
        key = (rank, gap if gap is not None else _ZERO, distance, move.fingerprint)
        found.append((key, Candidate(move, rank < 2)))
    found.sort(key=lambda pair: pair[0])
    return [candidate for _, candidate in found]


def _excess_gap(state: SharedState, move: Movement, rates: Mapping[str, Rate]) -> Decimal | None:
    """Qué tan lejos está el gasto del exceso del grupo, si está a ±PENDING_MARGIN de él."""
    gaps = []
    for currency, excess in state.excess_by:
        value = convert(gross(move), move.currency, currency, move.day, rates)
        if value is not None and abs(value - excess) <= excess * PENDING_MARGIN:
            gaps.append(abs(value - excess))
    return min(gaps) if gaps else None


def open_groups(groups: Mapping[int, SharedState]) -> list[SharedState]:
    """Grupos con pendiente (para «Sumarlo a un grupo»), los más recientes primero."""
    found = [g for g in groups.values() if g.has_pending]
    return sorted(found, key=lambda g: (g.last_day, g.id), reverse=True)


def fold(text: str) -> str:
    """Sin acentos y en minúsculas."""
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).casefold()


def _words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def name_words(with_whom: str) -> frozenset[str]:
    """Las palabras de «Con quién» que sirven para sugerir: de NAME_MIN_LETTERS letras o más."""
    return frozenset(w for w in _words(with_whom) if len(w) >= NAME_MIN_LETTERS and not w.isdigit())


def suggestions(
    movements: Sequence[Movement],
    links: Links,
    groups: Mapping[int, SharedState],
    rates: Mapping[str, Rate] = _NO_RATES,
) -> dict[str, int]:
    """Crédito -> grupo que parece reembolsar: por monto (misma moneda, poco después de un
    gasto, cabe en lo pendiente) o, si no, por nombre («Con quién» en la descripción)."""
    open_ = [g for g in groups.values() if g.has_pending]
    if not open_:
        return {}
    found: dict[str, int] = {}
    for credit in movements:
        if not is_eligible_credit(credit, links):
            continue
        chosen = _by_amount(credit, open_) or _by_name(credit, open_, rates)
        if chosen is not None:
            found[credit.fingerprint] = chosen.id
    return found


def _by_amount(credit: Movement, groups: Sequence[SharedState]) -> SharedState | None:
    options = []
    for group in groups:
        near = [
            (credit.day - e.day).days
            for e in group.expenses
            if e.currency == credit.currency
            and 0 <= (credit.day - e.day).days <= SUGGEST_WINDOW_DAYS
        ]
        if near and -credit.amount <= group.pending.get(credit.currency, _ZERO):
            options.append((min(near), group.id, group))
    return min(options, key=lambda o: (o[0], o[1]))[2] if options else None


def _by_name(
    credit: Movement, groups: Sequence[SharedState], rates: Mapping[str, Rate]
) -> SharedState | None:
    words = set(_words(credit.description))
    options = []
    for group in groups:
        oldest = group.oldest_pending
        if oldest is None or not name_words(group.link.with_whom) & words:
            continue
        if not 0 <= (credit.day - oldest.day).days <= PICK_WINDOW_DAYS:
            continue
        currencies = {e.currency for e in group.expenses}
        if any(converted(credit, c, rates) is None for c in currencies):
            continue
        # Como en el selector: tiene que caber en lo pendiente (con PENDING_MARGIN).
        pending = _pending_in(group, credit.currency, credit.day, rates)
        if not _fits_pending(-credit.amount, pending):
            continue
        options.append((oldest.day, oldest.fingerprint, group))
    return min(options, key=lambda o: (o[0], o[1]))[2] if options else None
