"""Cuentas de la caja fuerte: el efectivo guardado que no es gasto (funciones puras).

Por omisión nada cambia: un retiro de cajero es gasto en «Efectivo» el día del retiro. Solo lo
que el usuario marca a mano entra en la caja (no hay sugerencias):

- **Retiro guardado** (`links`, rol `'stored'`): un débito de categoría «Efectivo» de un banco o
  de una tarjeta (`can_store`). Pasa a «Caja fuerte» (transferencia: no es gasto ni resta de lo
  que te quedó) y suma al saldo en su moneda. Quitar la marca lo devuelve a gasto.
- **Depósito al banco** (rol `'deposit'`): un crédito de una cuenta bancaria cuya categoría es de
  ingreso, que no sea salario ni rendimiento ni intereses que paga el banco ("PAGO INTERESES": su
  categoría es «Otros ingresos», así que se reconoce por la palabra INTERES/INTERESES en la
  descripción) (`can_deposit`). Un pago de tarjeta, un envío entre tus cuentas, un cambio, un
  reembolso o una reversión son transferencias y quedan fuera. Pasa a «Caja fuerte» (no es
  ingreso) y baja el saldo. Por omisión sale de la caja en la moneda del crédito
  y por el mismo monto. Si salió en la otra moneda (dólares de la caja depositados en pesos),
  `box_currency` lo dice y `box_amount` cuánto salió; sin monto, se convierte a la tasa del mes
  del depósito (`rates.rate_for`, la misma del board) y, sin ninguna tasa, no baja el saldo y se
  avisa (`uncounted`), sin inventar.
- **A mano** (`cash_box_store`, tabla `cash_entries`): *saldo inicial* (efectivo que ya estaba:
  no es ingreso de ningún mes ni sale en Transacciones), *entrada* (efectivo recibido: ingreso
  en su mes, por omisión «Otros ingresos») y *salida* (gasto en su categoría y mes, por omisión
  «Efectivo»). Entradas y salidas son movimientos de la cuenta «Caja fuerte» (`spending`): se
  buscan, se corrigen, admiten nota, «gasto único» y compartir como cualquier otro. Su huella es
  `caja-<id>`: no choca con las de los estados (24 dígitos hexadecimales) ni cambia con
  `parse --retry`, que solo rehace las filas de `transactions`.

**Saldo**: por moneda, entradas (saldo inicial, entradas, retiros guardados) menos salidas
(salidas y depósitos), cada movimiento en su moneda. Un saldo negativo se permite y se avisa
(`negative`: «la caja quedaría en −US$ 200; ¿ajustar el saldo inicial?»). **≈ RD$**: cada
movimiento a la tasa de su mes; los US$ sin ninguna tasa van aparte (`unconverted`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Literal, get_args

from finanzas.analysis import categories
from finanzas.analysis.accounts import CASH_BOX_KEY
from finanzas.analysis.links import CashBox, CashBoxMember, Links
from finanzas.analysis.rates import Rate, rate_for, to_dop

if TYPE_CHECKING:
    from finanzas.analysis.spending import Movement

EntryKind = Literal["initial", "income", "expense"]
ENTRY_KINDS: tuple[EntryKind, ...] = get_args(EntryKind)
LineKind = Literal["initial", "income", "expense", "stored", "deposit"]
CURRENCIES = ("DOP", "USD")
FINGERPRINT_PREFIX = "caja-"
MERCHANT = "CAJA FUERTE"
DESCRIPTIONS: Mapping[str, str] = {
    "initial": "Saldo inicial de la caja fuerte",
    "income": "Entrada a la caja fuerte",
    "expense": "Salida de la caja fuerte",
}
# Categoría por omisión de lo anotado a mano (el usuario la cambia como en cualquier otro).
DEFAULT_CATEGORY: Mapping[str, str] = {
    "income": categories.OTHER_INCOME,
    "expense": categories.CASH,
}
# El tipo de categoría que admite cada movimiento a mano al anotarlo.
ENTRY_CATEGORY_KIND: Mapping[str, categories.Kind] = {"income": "ingreso", "expense": "gasto"}
# Fechas admitidas en lo anotado a mano: ni antes de esto ni más de un mes adelante de hoy.
FIRST_DAY = date(2000, 1, 1)
DAYS_AHEAD = 31
_CENT = Decimal("0.01")
# Ingresos que nunca vienen de la caja: el sueldo y lo que rinde una inversión.
_NOT_DEPOSIT = frozenset({categories.SALARY, categories.INVESTMENT_RETURN, *categories.LINK_ONLY})
# Los intereses que paga el banco ("PAGO INTERESES", "CR INTERESES GANADOS").
_INTEREST = re.compile(r"\bINTERES(ES)?\b")
_ZERO = Decimal(0)


class CashBoxError(ValueError):
    """Pedido inválido sobre la caja fuerte (422)."""


@dataclass(frozen=True)
class ManualEntry:
    """Un movimiento anotado a mano en la caja (`cash_entries`). `amount`, siempre positivo."""

    id: int
    kind: EntryKind
    day: date
    amount: Decimal
    currency: str
    account_key: str = CASH_BOX_KEY

    @property
    def fingerprint(self) -> str:
        return entry_fingerprint(self.id)


def entry_fingerprint(entry_id: int) -> str:
    return f"{FINGERPRINT_PREFIX}{entry_id}"


def entry_id(fingerprint: str) -> int | None:
    """El id de un movimiento a mano por su huella; None si no es uno."""
    digits = fingerprint.removeprefix(FINGERPRINT_PREFIX)
    if digits == fingerprint or not digits.isdigit() or digits.startswith("0"):
        return None
    return int(digits)


def is_manual(fingerprint: str) -> bool:
    return entry_id(fingerprint) is not None


def manual_kind(amount: Decimal) -> categories.Kind:
    """El tipo de categoría que lleva un movimiento a mano de la caja (como al anotarlo,
    `cash_box_store._category`): una entrada (monto negativo) es ingreso; una salida, gasto."""
    return ENTRY_CATEGORY_KIND["income" if amount < 0 else "expense"]


def manual_category_error(fingerprint: str, amount: Decimal, kind: str) -> str | None:
    """Por qué esa categoría no le cabe a un movimiento a mano de la caja (None si le cabe o si
    no es uno)."""
    if not is_manual(fingerprint):
        return None
    wanted = manual_kind(amount)
    if kind == wanted:
        return None
    if wanted == "ingreso":
        return "en la caja fuerte, una entrada va a una categoría de ingreso"
    return "en la caja fuerte, una salida va a una categoría de gasto"


@dataclass(frozen=True)
class Line:
    """Una entrada o salida de la caja, con su signo en la moneda de la caja (+ entra, − sale)."""

    kind: LineKind
    day: date
    fingerprint: str
    currency: str  # en la caja
    amount: Decimal | None  # None: un depósito en otra moneda sin tasa (no baja el saldo)
    dop: Decimal | None  # ≈ RD$ a la tasa de su mes; None sin tasa
    # El movimiento como aparece (el crédito o débito del banco, o lo anotado), positivo.
    source_amount: Decimal
    source_currency: str
    move: Movement | None = None  # en el flujo (todos menos el saldo inicial)
    entry: ManualEntry | None = None  # lo anotado a mano

    @property
    def counted(self) -> bool:
        return self.amount is not None


@dataclass(frozen=True)
class BoxState:
    account_key: str
    lines: tuple[Line, ...]  # la más reciente primero
    balances: tuple[tuple[str, Decimal], ...]  # por moneda, RD$ primero
    total_dop: Decimal  # ≈ RD$, cada movimiento a la tasa de su mes
    unconverted: tuple[tuple[str, Decimal], ...]  # lo que no tiene tasa, por moneda
    uncounted: tuple[str, ...] = ()  # depósitos en otra moneda sin tasa: no bajan el saldo

    def balance(self, currency: str) -> Decimal:
        return dict(self.balances).get(currency, _ZERO)

    @property
    def negative(self) -> tuple[tuple[str, Decimal], ...]:
        """Las monedas en que la caja quedó en negativo (se avisa, nunca se bloquea)."""
        return tuple((c, amount) for c, amount in self.balances if amount < 0)


def after(state: BoxState, currency: str, delta: Decimal) -> Decimal | None:
    """El saldo de `currency` tras mover `delta` (negativo: sale); None si no queda negativo."""
    left = state.balance(currency) + delta
    return left if left < 0 else None


def state_of(
    box: CashBox | None,
    entries: Iterable[ManualEntry],
    movements: Sequence[Movement],
    rates: Mapping[str, Rate],
    account_key: str = CASH_BOX_KEY,
) -> BoxState:
    """La caja con sus líneas y saldos. `movements`: el flujo (`spending.load_all`), donde están
    los retiros, los depósitos y lo anotado a mano; uno que ya no aparece (o ya no es un débito o
    un crédito) no cuenta."""
    by_fp = {m.fingerprint: m for m in movements}
    lines = [
        _entry_line(entry, by_fp.get(entry.fingerprint), rates)
        for entry in entries
        if entry.account_key == account_key
    ]
    for member in () if box is None else box.members:
        move = by_fp.get(member.fingerprint)
        if move is None:
            continue
        line = _member_line(member, move, rates)
        if line is not None:
            lines.append(line)
    lines.sort(key=lambda line: (line.day, line.fingerprint), reverse=True)
    return BoxState(
        account_key=account_key,
        lines=tuple(lines),
        balances=_by_currency((line.currency, line.amount) for line in lines),
        total_dop=sum((line.dop for line in lines if line.dop is not None), _ZERO),
        unconverted=_by_currency(
            (line.currency, line.amount) for line in lines if line.dop is None
        ),
        uncounted=tuple(line.fingerprint for line in lines if not line.counted),
    )


def _by_currency(
    pairs: Iterable[tuple[str, Decimal | None]],
) -> tuple[tuple[str, Decimal], ...]:
    totals: dict[str, Decimal] = {}
    for currency, amount in pairs:
        if amount is not None:
            totals[currency] = totals.get(currency, _ZERO) + amount
    return tuple(sorted(totals.items(), key=lambda item: (item[0] != "DOP", item[0])))


def _entry_line(entry: ManualEntry, move: Movement | None, rates: Mapping[str, Rate]) -> Line:
    signed = -entry.amount if entry.kind == "expense" else entry.amount
    return Line(
        kind=entry.kind,
        day=entry.day,
        fingerprint=entry.fingerprint,
        currency=entry.currency,
        amount=signed,
        dop=_dop(signed, entry.currency, entry.day, rates),
        source_amount=entry.amount,
        source_currency=entry.currency,
        move=move,
        entry=entry,
    )


def _member_line(member: CashBoxMember, move: Movement, rates: Mapping[str, Rate]) -> Line | None:
    gross = move.gross if move.gross is not None else move.amount
    if member.role == "stored":
        if gross <= 0:
            return None
        amount: Decimal | None = gross
        currency = move.currency
    else:
        if gross >= 0:
            return None
        currency = member.box_currency or move.currency
        taken = deposit_amount(member, -gross, move.currency, move.month, rates)
        amount = None if taken is None else -taken
    return Line(
        kind=member.role,
        day=move.day,
        fingerprint=move.fingerprint,
        currency=currency,
        amount=amount,
        dop=None if amount is None else _dop(amount, currency, move.day, rates),
        source_amount=abs(gross),
        source_currency=move.currency,
        move=move,
    )


def deposit_amount(
    member: CashBoxMember,
    credit: Decimal,
    currency: str,
    month: str,
    rates: Mapping[str, Rate],
) -> Decimal | None:
    """Lo que salió de la caja por un depósito de `credit` (positivo, en `currency`): lo mismo si
    sale en esa moneda; si no, lo dicho a mano o el crédito a la tasa del mes; None sin tasa."""
    target = member.box_currency or currency
    if target == currency:
        return credit
    if member.box_amount is not None:
        return member.box_amount
    rate = rate_for(rates, month)
    if rate is None or rate.value <= 0:
        return None
    converted = credit * rate.value if currency == "USD" else credit / rate.value
    return converted.quantize(_CENT, rounding=ROUND_HALF_UP)


def _dop(amount: Decimal, currency: str, day: date, rates: Mapping[str, Rate]) -> Decimal | None:
    return to_dop(amount, currency, rate_for(rates, day.strftime("%Y-%m")))


# --- Qué se puede marcar --------------------------------------------------------------------


def can_store(move: Movement, links: Links) -> bool:
    """Un débito de «Efectivo» (un retiro de cajero o un avance) de un banco o una tarjeta, sin
    otro vínculo. Lo anotado a mano en la caja no: ya está en ella."""
    return (
        move.amount > 0
        and move.ref == categories.CASH
        and move.account != CASH_BOX_KEY
        and not is_manual(move.fingerprint)
        and not links.is_linked(move.fingerprint)
    )


def can_deposit(move: Movement, links: Links, banks: Iterable[str]) -> bool:
    """Un crédito de una cuenta bancaria, sin otro vínculo, cuya categoría es de ingreso y no es
    salario ni rendimiento, ni son intereses del banco (ver el docstring del módulo)."""
    return (
        move.amount < 0
        and move.account in set(banks)
        and move.kind == "ingreso"
        and move.ref not in _NOT_DEPOSIT
        and _INTEREST.search(move.description.upper()) is None
        and not links.is_linked(move.fingerprint)
    )


def stored_dop(movements: Iterable[Movement], rates: Mapping[str, Rate], month: str) -> Decimal:
    """Los retiros guardados del mes en RD$ (los US$ sin tasa no cuentan): «de eso, RD$ X fueron
    a la caja fuerte». Un depósito (crédito) no resta de esa línea."""
    total = _ZERO
    for move in movements:
        if move.link != "cash_box" or move.amount <= 0 or move.month != month:
            continue
        total += to_dop(move.amount, move.currency, rate_for(rates, month)) or _ZERO
    return total


def last_day(today: date) -> date:
    return today + timedelta(days=DAYS_AHEAD)


def check_day(day: date, today: date) -> None:
    """La fecha de lo anotado a mano: desde FIRST_DAY hasta hoy + DAYS_AHEAD días."""
    if not FIRST_DAY <= day <= last_day(today):
        raise CashBoxError(
            f"la fecha va del {FIRST_DAY.isoformat()} al {last_day(today).isoformat()}"
        )


def check_entry(kind: str, amount: Decimal, currency: str) -> None:
    if kind not in ENTRY_KINDS:
        raise CashBoxError(f"tipo desconocido: {kind}")
    if not amount.is_finite() or amount <= 0:
        raise CashBoxError("el monto tiene que ser mayor que 0")
    if amount != amount.quantize(_CENT):
        raise CashBoxError("el monto tiene más de dos decimales")
    if currency not in CURRENCIES:
        raise CashBoxError("la moneda es RD$ o US$")
