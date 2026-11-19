"""Pendientes: quién te debe y a quién debes, de todos los meses.

- **Te deben**: los grupos compartidos con pendiente, una fila por grupo (`shared.states`: ya
  imputan los reembolsos, convertidos, del gasto más viejo al más nuevo) y los cambios de
  divisas con pendiente cuyo lado base salió de tus cuentas (tú diste primero: la pata más
  antigua es un débito).
- **Debes**: los cambios con pendiente cuyo lado base entró (te dieron primero y falta devolver
  la otra moneda).
- Fuera: lo marcado "No me lo van a pagar" y los cambios completos o sin pendiente (los estados
  ya los dejan en 0).

En RD$: un cambio vale a su propia tasa (la acordada o la implícita, `ExchangeState.pending_dop`:
es el precio al que se pactó la deuda, así que nunca queda sin tasa); lo pendiente en US$ de un
grupo, a la tasa más reciente guardada (la del mes de `today` o la del mes anterior más cercano)
y, sin ninguna, aparte, sin inventar. Con cuentas elegidas, un grupo cuenta si alguno de sus
gastos es de ellas (su fila abre el primer gasto del grupo y da la cuenta del primero de esas
cuentas); un cambio, si alguna de sus patas lo es, y su fila es la primera de esas patas (la que
abre su pantalla y da la cuenta). La fecha y la antigüedad de un grupo son las de su gasto
pendiente más viejo; las de un cambio, las de su primera pata. Cada lista va de lo más viejo a
lo más nuevo.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from finanzas.analysis.exchanges import ExchangeState
from finanzas.analysis.rates import Rate, rate_for, to_dop
from finanzas.analysis.shared import SharedState
from finanzas.analysis.spending import Movement

WHO_CHARS = 40  # una nota más larga se recorta para la fila
_ZERO = Decimal(0)
_USD = "USD"

Kind = Literal["shared", "exchange"]


@dataclass(frozen=True)
class PendingItem:
    kind: Kind
    fingerprint: str  # la del primer gasto del grupo, o la de la primera pata del cambio
    day: date
    merchant: str  # el título del grupo (nombre, «Con quién» o comercio) o el del cambio
    account_label: str
    who: str  # «Con quién» del grupo o, si no, la nota (recortada); puede ir vacío
    pending: Decimal  # en `currency`
    currency: str
    pending_dop: Decimal | None  # None: en US$ sin ninguna tasa
    age_days: int
    rate: Decimal | None = None  # RD$ por US$ usados para `pending_dop` (None: no hizo falta)
    # Un grupo: cuántos gastos tiene, su id y lo pendiente por moneda (RD$ antes que US$).
    expense_count: int = 1
    link_id: int | None = None
    parts: tuple[tuple[str, Decimal], ...] = ()
    unconverted_usd: Decimal = Decimal(0)  # US$ pendientes sin ninguna tasa


@dataclass(frozen=True)
class Pending:
    owed_to_me: tuple[PendingItem, ...]
    i_owe: tuple[PendingItem, ...]
    rate: Rate | None  # la más reciente: la de los gastos compartidos en US$

    @property
    def owed_to_me_dop(self) -> Decimal:
        return _dop_total(self.owed_to_me)

    @property
    def i_owe_dop(self) -> Decimal:
        return _dop_total(self.i_owe)

    @property
    def net_dop(self) -> Decimal:
        return self.owed_to_me_dop - self.i_owe_dop

    @property
    def unconverted_owed_to_me(self) -> Decimal:
        return _unconverted(self.owed_to_me)

    @property
    def unconverted_i_owe(self) -> Decimal:
        return _unconverted(self.i_owe)


def build_pending(
    movements: Sequence[Movement],
    groups: Mapping[int, SharedState],
    exchange_states: Mapping[int, ExchangeState],
    labels: Mapping[str, str],
    rates: Mapping[str, Rate],
    today: date,
    chosen: Collection[str] | None = None,
) -> Pending:
    """Las dos listas y la tasa usada. `chosen`: claves de las cuentas (None: todas)."""
    rate = rate_for(rates, today.strftime("%Y-%m"))
    owed: list[PendingItem] = []
    owing: list[PendingItem] = []
    for state in groups.values():
        moves = [e.move for e in state.expenses]
        if not state.has_pending or not _picked(moves, chosen):
            continue
        first = next(m for m in moves if chosen is None or m.account in chosen)
        owed.append(_shared_item(state, first, labels, rate, today))
    for exchange in exchange_states.values():
        shown = _shown_leg(exchange, chosen)
        if exchange.pending <= 0 or shown is None:
            continue
        item = _exchange_item(exchange, shown, labels, today)
        # El lado base salió de tus cuentas (diste primero): te deben; si entró, debes.
        base = next(leg for leg in exchange.legs if leg.currency == exchange.base)
        (owed if base.amount > 0 else owing).append(item)
    return Pending(_oldest_first(owed), _oldest_first(owing), rate)


def _shared_item(
    state: SharedState, shown: Movement, labels: Mapping[str, str], rate: Rate | None, today: date
) -> PendingItem:
    parts = tuple(sorted(state.pending.items()))
    oldest = state.oldest_pending or state.first
    converted = [(to_dop(value, currency, rate), value, currency) for currency, value in parts]
    dop_parts = [dop for dop, _, _ in converted if dop is not None]
    unconverted = sum((v for dop, v, c in converted if dop is None and c == _USD), _ZERO)
    main_currency, main_value = parts[0]
    return PendingItem(
        kind="shared",
        fingerprint=state.first.fingerprint,
        day=oldest.day,
        merchant=state.title,
        account_label=labels.get(shown.account, shown.account),
        who=_trim(state.link.with_whom or state.first.move.note),
        pending=main_value,
        currency=main_currency,
        pending_dop=sum(dop_parts, _ZERO) if dop_parts else None,
        age_days=(today - oldest.day).days,
        rate=rate.value if rate is not None and any(c == _USD for c, _ in parts) else None,
        expense_count=len(state.expenses),
        link_id=state.id,
        parts=parts,
        unconverted_usd=unconverted if dop_parts else _ZERO,
    )


def _exchange_item(
    exchange: ExchangeState, shown: Movement, labels: Mapping[str, str], today: date
) -> PendingItem:
    return PendingItem(
        kind="exchange",
        fingerprint=shown.fingerprint,
        day=exchange.first_day,
        merchant=_name(shown),
        account_label=labels.get(shown.account, shown.account),
        who=_trim(next((leg.note for leg in exchange.legs if leg.note), "")),
        pending=exchange.pending,
        currency=exchange.pending_currency,
        pending_dop=exchange.pending_dop,
        age_days=(today - exchange.first_day).days,
        rate=exchange.rate,
    )


def _shown_leg(exchange: ExchangeState, chosen: Collection[str] | None) -> Movement | None:
    """La pata que representa al cambio: la primera de las cuentas elegidas (None: ninguna)."""
    return next((leg for leg in exchange.legs if chosen is None or leg.account in chosen), None)


def _name(move: Movement) -> str:
    return move.merchant or move.description


def _picked(moves: Iterable[Movement], chosen: Collection[str] | None) -> bool:
    return chosen is None or any(m.account in chosen for m in moves)


def _trim(text: str) -> str:
    clean = " ".join(text.split())
    if len(clean) <= WHO_CHARS:
        return clean
    return clean[: WHO_CHARS - 1].rstrip() + "…"


def _oldest_first(items: Iterable[PendingItem]) -> tuple[PendingItem, ...]:
    return tuple(sorted(items, key=lambda i: (i.day, i.fingerprint)))


def _dop_total(items: Iterable[PendingItem]) -> Decimal:
    return sum((i.pending_dop for i in items if i.pending_dop is not None), _ZERO)


def _unconverted(items: Iterable[PendingItem]) -> Decimal:
    whole = sum((i.pending for i in items if i.pending_dop is None and i.currency == _USD), _ZERO)
    return whole + sum((i.unconverted_usd for i in items), _ZERO)
