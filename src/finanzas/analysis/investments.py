"""Cuentas de las inversiones: lo aportado, lo devuelto, lo que rinde y las sugerencias.

Una inversión (`links.Investment`) junta aportes (débitos), rendimientos, devoluciones de capital
y créditos mixtos (una parte capital, el resto rendimiento). No se guardan términos pactados
(tasa ni frecuencia): todo sale de lo que pasó.

- **Moneda**: la del primer aporte presente (por fecha). Un movimiento en otra moneda se
  muestra en la suya y suma convertido a la tasa de su mes (o la del mes anterior más cercano,
  `rates.rate_for`); sin ninguna, no suma y va aparte (`unconverted`), sin inventar.
- **Aportado** A = Σ aportes. **Capital devuelto** K = Σ devoluciones + Σ partes de capital de
  los mixtos, cada una topada en el capital invertido ese día (`effective_capitals`: en orden de
  fecha, los aportes de un día antes que sus créditos): lo devuelto de más es ganancia y cuenta
  como **rendimiento** (también en el Resumen y los reportes, ver `spending.with_links`).
  **Capital por volver** = A − K (nunca negativo). **Rendimientos** R = Σ rendimientos + Σ
  (crédito − capital) de los mixtos + lo devuelto de más (`excess`). **Último cobro**: el
  crédito más reciente.
- **Estado**: "closed" (Cerrada) en cuanto el capital por volver llega a 0, sola; si no,
  "written_off" si se marcó «Dada por perdida»; si no, "active" (Activa).
- **% anual aproximado** (`annual_rate`): R / capital promedio invertido × 365 / días. El capital
  invertido en cada día es C(t) = aportado hasta t − capital devuelto (topado) hasta t, que
  nunca baja de 0 en ningún paso (cada movimiento cuenta desde su día). Desde el primer aporte
  (d0) hasta el final (E: hoy si está activa; si no, el día del último movimiento), los
  capital-días son Σ C(t) por cada día de [d0, E). Capital promedio = capital-días / días,
  así que % anual = R × 365 / capital-días (una fracción: 0.12 = 12 %). Sin capital-días (todo
  el mismo día) no hay % (None); sin rendimientos es 0.

Sugerencias (`suggestions`; nunca se enlaza solo, confirmar es un toque):
- **El nombre** de «Con quién» coincide si la descripción trae todas sus palabras
  significativas (`shared.name_words`: 4 letras o más) o, si tiene más de dos, al menos dos: con
  «Juan Pérez», «JUAN GARCIA» o «PAGO JUAN SUPERMERCADO» no coinciden.
- **¿Otro aporte?** (`aporte_posible`): un débito sin vínculo de al menos
  LARGE_CONTRIBUTION_DOP en RD$ (= `review.LARGE_THIRD_PARTY_DOP`; con tasa, si no, no) que va
  al mismo destino que un aporte de una inversión no perdida: el mismo comercio exacto (en un
  banco, la cuenta destino: "MB A 0000000066") o el nombre. Así los envíos chicos a la misma
  persona (que no son de la inversión) no se proponen.
- **¿Cobro?** (`cobro_posible`): un crédito sin vínculo, desde el primer aporte, de una inversión
  activa, cuya descripción trae el nombre, el comercio exacto de un crédito ya enlazado o, como
  palabra entera, la cuenta destino de un aporte (los dígitos tras "A" en "MB A 0000…"; no
  otras referencias); y que vale al menos max(RETURN_MIN_DOP, RETURN_MIN_SHARE × aportado) en
  RD$: la misma persona también manda montos chicos que no son de la inversión.
Si un movimiento encaja en varias, la de actividad más reciente.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from finanzas.analysis import categories, shared
from finanzas.analysis.links import Investment, InvestmentMember, InvestmentRole, Links
from finanzas.analysis.rates import Rate, rate_for, to_dop

if TYPE_CHECKING:
    from finanzas.analysis.spending import Movement

# «¿Otro aporte?» desde este monto en RD$: el mismo que `review.LARGE_THIRD_PARTY_DOP` (no se
# importa: `spending` usa este módulo y `review` usa `spending`; una prueba los compara).
LARGE_CONTRIBUTION_DOP = Decimal(25_000)
RETURN_MIN_DOP = Decimal(1_000)
RETURN_MIN_SHARE = Decimal("0.01")
DAYS_PER_YEAR = 365
_ZERO = Decimal(0)
# La cuenta destino de un envío: "MB a 0000000066 …", "TOKE A 0000…" (no una referencia).
_DESTINATION = re.compile(r"\bA\s+(\d{6,})\b", re.IGNORECASE)
_NAME_MATCHES = 2  # con más palabras en «Con quién», bastan estas
# Lo que nunca es un aporte ni un cobro de una inversión.
NOT_INVESTMENT = frozenset(
    {
        categories.CARD_PAYMENT,
        categories.OWN_TRANSFER,
        categories.CURRENCY_EXCHANGE,
        categories.REIMBURSEMENT,
        categories.SALARY,
    }
)

Status = Literal["active", "closed", "written_off"]
SuggestionKind = Literal["aporte_posible", "cobro_posible"]


@dataclass(frozen=True)
class Entry:
    """Un movimiento presente de la inversión, en su moneda y en la de la inversión."""

    move: Movement
    role: InvestmentRole
    amount: Decimal  # el del estado, positivo, en la moneda del movimiento
    capital: Decimal  # parte de capital que cuenta (aporte: 0), en la moneda del movimiento
    value: Decimal | None  # `amount` en la moneda de la inversión; None: sin tasa
    capital_value: Decimal | None
    return_value: Decimal | None  # el rendimiento, en la moneda de la inversión
    excess: Decimal = _ZERO  # capital devuelto de más (cuenta como rendimiento), en su moneda
    excess_value: Decimal | None = None

    @property
    def fingerprint(self) -> str:
        return self.move.fingerprint

    @property
    def day(self) -> date:
        return self.move.day

    @property
    def currency(self) -> str:
        return self.move.currency

    @property
    def is_credit(self) -> bool:
        return self.role != "contribution"

    @property
    def counted(self) -> bool:
        return self.value is not None

    @property
    def returned(self) -> Decimal:
        """El rendimiento, en la moneda del movimiento."""
        return _ZERO if self.role == "contribution" else self.amount - self.capital


@dataclass(frozen=True)
class InvestmentState:
    link: Investment
    currency: str
    entries: tuple[Entry, ...]  # por (fecha, huella)

    @property
    def id(self) -> int:
        return self.link.id

    @property
    def counted(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.counted)

    @property
    def unconverted(self) -> tuple[Entry, ...]:
        """Movimientos en otra moneda sin ninguna tasa: no suman."""
        return tuple(e for e in self.entries if not e.counted)

    @property
    def contributions(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.role == "contribution")

    @property
    def credits(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.is_credit)

    @property
    def first(self) -> Entry:
        """El primer aporte (por fecha): da la moneda y abre la pantalla de la inversión."""
        return self.contributions[0]

    @property
    def contributed(self) -> Decimal:
        return sum((e.value or _ZERO for e in self.contributions), _ZERO)

    @property
    def capital_returned(self) -> Decimal:
        return sum((e.capital_value or _ZERO for e in self.credits), _ZERO)

    @property
    def returns(self) -> Decimal:
        return sum((e.return_value or _ZERO for e in self.credits), _ZERO)

    @property
    def excess(self) -> Decimal:
        """Lo devuelto de más que lo aportado (ya está en `returns`)."""
        return sum((e.excess_value or _ZERO for e in self.credits), _ZERO)

    @property
    def pending(self) -> Decimal:
        """Capital por volver (nunca negativo)."""
        return max(self.contributed - self.capital_returned, _ZERO)

    @property
    def status(self) -> Status:
        if self.pending == 0:
            return "closed"
        return "written_off" if self.link.written_off else "active"

    @property
    def title(self) -> str:
        """Nombre, si no «Con quién», si no el comercio del primer aporte."""
        move = self.first.move
        return self.link.name or self.link.with_whom or move.merchant or move.description

    @property
    def last_activity(self) -> date:
        return max(e.day for e in self.entries)

    @property
    def last_credit(self) -> date | None:
        """Fecha del último cobro (rendimiento o capital)."""
        return max((e.day for e in self.credits), default=None)

    def end(self, today: date) -> date:
        """Hasta cuándo se mide el % anual: hoy si está activa; si no, su último movimiento."""
        last = self.last_activity
        return max(today, last) if self.status == "active" else last

    def annual_rate(self, today: date) -> Decimal | None:
        return annual_rate(self.counted, self.returns, self.end(today))


def annual_rate(entries: Iterable[Entry], returns: Decimal, end: date) -> Decimal | None:
    """R × 365 / capital-días (ver el docstring del módulo); None sin capital-días."""
    days = capital_days(entries, end)
    if days <= 0:
        return None
    return returns * DAYS_PER_YEAR / days


def capital_days(entries: Iterable[Entry], end: date) -> Decimal:
    """Σ del capital invertido de cada día, desde el primer aporte hasta `end` (sin incluirlo)."""
    changes: dict[date, Decimal] = {}
    for e in entries:
        delta = (e.value or _ZERO) if e.role == "contribution" else -(e.capital_value or _ZERO)
        if delta:
            changes[e.day] = changes.get(e.day, _ZERO) + delta
    total, capital, previous = _ZERO, _ZERO, None
    for day in sorted(d for d in changes if d < end):
        if previous is not None:
            total += capital * (day - previous).days
        capital = max(capital + changes[day], _ZERO)  # nunca negativo, en ningún paso
        previous = day
    if previous is not None:
        total += capital * (end - previous).days
    return total


def _nominal_capital(member: InvestmentMember, amount: Decimal) -> Decimal:
    if member.role == "capital":
        return amount
    if member.role == "mixed":
        return min(member.capital or amount, amount)
    return _ZERO


Present = Sequence[tuple["Movement", InvestmentMember]]


def _order(pair: tuple[Movement, InvestmentMember]) -> tuple[date, bool, str]:
    move, member = pair
    return (move.day, member.role != "contribution", move.fingerprint)


def investment_currency(present: Present) -> str | None:
    """La del primer aporte (débito) presente, por fecha; None sin ninguno."""
    debits = sorted(
        (move for move, m in present if m.role == "contribution" and shared.gross(move) > 0),
        key=lambda move: (move.day, move.fingerprint),
    )
    return debits[0].currency if debits else None


def effective_capitals(present: Present, rates: Mapping[str, Rate]) -> dict[str, Decimal]:
    """Crédito -> la parte de capital que cuenta, en su moneda: la nominal (todo en una
    devolución, la parte de capital en un mixto) topada en el capital invertido hasta ese día. Lo
    que sobra es ganancia (rendimiento). Un crédito sin tasa conserva la nominal."""
    currency = investment_currency(present)
    if currency is None:
        return {}
    running, found = _ZERO, {}
    for move, member in sorted(present, key=_order):
        gross = shared.gross(move)
        amount, day = abs(gross), move.day
        if member.role == "contribution":
            value = shared.convert(amount, move.currency, currency, day, rates)
            if gross > 0 and value is not None:
                running += value
            continue
        if gross >= 0:
            continue
        nominal = _nominal_capital(member, amount)
        value = shared.convert(nominal, move.currency, currency, day, rates)
        if nominal == 0 or value is None:
            found[move.fingerprint] = nominal
            continue
        applied = min(value, running)
        running -= applied
        if applied == value:
            found[move.fingerprint] = nominal
        elif applied <= 0:
            found[move.fingerprint] = _ZERO
        else:
            back = shared.convert(applied, currency, move.currency, day, rates)
            found[move.fingerprint] = min(back or _ZERO, nominal)
    return found


def _entry(
    move: Movement,
    member: InvestmentMember,
    currency: str,
    rates: Mapping[str, Rate],
    capitals: Mapping[str, Decimal],
) -> Entry:
    amount = abs(shared.gross(move))
    nominal = _nominal_capital(member, amount)
    capital = capitals.get(move.fingerprint, nominal)

    def value(of: Decimal) -> Decimal | None:
        return shared.convert(of, move.currency, currency, move.day, rates)

    whole = value(amount)
    return Entry(
        move=move,
        role=member.role,
        amount=amount,
        capital=capital,
        value=whole,
        capital_value=None if whole is None else value(capital),
        return_value=None if whole is None else value(amount - capital),
        excess=nominal - capital,
        excess_value=None if whole is None else value(nominal - capital),
    )


def state_of(
    link: Investment, by_fp: Mapping[str, Movement], rates: Mapping[str, Rate]
) -> InvestmentState | None:
    """Las cuentas de la inversión con sus movimientos presentes (los que siguen enlazados como
    inversión); None si no le queda ningún aporte presente."""
    present = [
        (move, m)
        for m in link.members
        if (move := by_fp.get(m.fingerprint)) is not None and move.link == "investment"
    ]
    contributions = sorted(
        (move for move, m in present if m.role == "contribution"),
        key=lambda move: (move.day, move.fingerprint),
    )
    if not contributions:
        return None
    currency = contributions[0].currency
    capitals = effective_capitals(present, rates)
    entries = sorted(
        (_entry(move, m, currency, rates, capitals) for move, m in present),
        key=lambda e: (e.day, e.fingerprint),
    )
    return InvestmentState(link=link, currency=currency, entries=tuple(entries))


def states(
    movements: Sequence[Movement], links: Links, rates: Mapping[str, Rate]
) -> dict[int, InvestmentState]:
    """Cuentas de cada inversión con algún aporte presente, por id."""
    by_fp = {m.fingerprint: m for m in movements}
    found = {}
    for link in links.investments:
        state = state_of(link, by_fp, rates)
        if state is not None:
            found[link.id] = state
    return found


def newest_first(found: Iterable[InvestmentState]) -> list[InvestmentState]:
    return sorted(found, key=lambda s: (s.last_activity, s.id), reverse=True)


# --- Elegibles y sugerencias ---------------------------------------------------------------


def _free(move: Movement, links: Links) -> bool:
    return (
        not move.link and not links.is_linked(move.fingerprint) and move.ref not in NOT_INVESTMENT
    )


def is_contribution_candidate(move: Movement, links: Links) -> bool:
    """Un débito que puede ser un aporte: sin vínculo y no es un pago, un envío propio, etc."""
    return move.amount > 0 and _free(move, links)


def is_credit_candidate(move: Movement, links: Links) -> bool:
    """Un crédito que puede ser de una inversión (rendimiento, capital o mixto)."""
    return move.amount < 0 and _free(move, links)


@dataclass(frozen=True)
class Suggestion:
    kind: SuggestionKind
    state: InvestmentState

    @property
    def reason(self) -> str:
        if self.kind == "aporte_posible":
            return f"¿Es otro aporte a {self.state.title}?"
        return f"¿Es un cobro de {self.state.title}?"


def _dop(move: Movement, rates: Mapping[str, Rate]) -> Decimal | None:
    value = to_dop(abs(shared.gross(move)), move.currency, rate_for(rates, move.month))
    return None if value is None else abs(value)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", shared.fold(text)))


def names_match(with_whom: str, text: str) -> bool:
    """La descripción trae el nombre: todas las palabras significativas de «Con quién» o, si
    tiene más de dos, al menos dos (ver el docstring del módulo)."""
    names = shared.name_words(with_whom)
    if not names:
        return False
    found = len(names & _words(text))
    return found == len(names) or found >= _NAME_MATCHES


def destinations(descriptions: Iterable[str]) -> frozenset[str]:
    """Las cuentas destino de estos envíos ("MB a 0000000066 …" -> "0000000066")."""
    return frozenset(n for text in descriptions for n in _DESTINATION.findall(text))


def _same_destination(move: Movement, state: InvestmentState) -> bool:
    merchants = {e.move.merchant for e in state.contributions if e.move.merchant}
    return move.merchant in merchants or names_match(state.link.with_whom, move.description)


def _from_origin(move: Movement, state: InvestmentState) -> bool:
    credit_merchants = {e.move.merchant for e in state.credits if e.move.merchant}
    accounts = destinations(e.move.description for e in state.contributions)
    text = move.description
    return (
        names_match(state.link.with_whom, text)
        or move.merchant in credit_merchants
        or any(re.search(rf"\b{n}\b", text) for n in accounts)
    )


def _contributed_dop(state: InvestmentState, rates: Mapping[str, Rate]) -> Decimal:
    return sum((_dop(e.move, rates) or _ZERO for e in state.contributions), _ZERO)


def suggestions(
    movements: Iterable[Movement],
    links: Links,
    found: Mapping[int, InvestmentState],
    rates: Mapping[str, Rate],
    banks: Collection[str] | None = None,
) -> dict[str, Suggestion]:
    """Huella -> la inversión que parece (ver el docstring del módulo). Solo propone. `banks`:
    las cuentas bancarias (solo sus movimientos se proponen; None: todas)."""
    ranked = newest_first(found.values())
    open_ = [s for s in ranked if s.status != "written_off"]
    active = [s for s in ranked if s.status == "active"]
    result: dict[str, Suggestion] = {}
    for move in movements:
        if banks is not None and move.account not in banks:
            continue
        if is_contribution_candidate(move, links):
            value = _dop(move, rates)
            if value is None or value < LARGE_CONTRIBUTION_DOP:
                continue
            hit = next((s for s in open_ if _same_destination(move, s)), None)
            if hit is not None:
                result[move.fingerprint] = Suggestion("aporte_posible", hit)
        elif is_credit_candidate(move, links):
            value = _dop(move, rates)
            if value is None:
                continue
            hit = next(
                (
                    s
                    for s in active
                    if move.day >= s.first.day
                    and value >= max(RETURN_MIN_DOP, RETURN_MIN_SHARE * _contributed_dop(s, rates))
                    and _from_origin(move, s)
                ),
                None,
            )
            if hit is not None:
                result[move.fingerprint] = Suggestion("cobro_posible", hit)
    return result
