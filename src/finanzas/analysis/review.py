"""«Para revisar»: movimientos del mes que conviene mirar, con reglas locales y deterministas.

Funciones puras sobre movimientos ya cargados. Tipos (`Kind`):
- "unico": posible gasto único (`one_offs.suggest`, sin cambios).
- "ingreso_inusual": un ingreso de al menos UNUSUAL_INCOME_DOP de una contraparte (comercio)
  que no aparece como ingreso en el año anterior. Solo si ya hay NEW_COUNTERPART_DAYS de datos
  antes de ese día: al principio todo parecería nuevo.
- "tercero_grande": una transferencia a terceros de al menos LARGE_THIRD_PARTY_DOP.
- "duplicado": un gasto con la misma cuenta, comercio, monto y moneda que otro del mismo día o
  del día anterior (se marca el segundo). Al día siguiente, solo desde NEXT_DAY_MIN_DOP; y no
  si ese mismo cargo ya se repite (RECURRING_CHARGES o más en los RECURRING_DAYS anteriores,
  como un peaje o un parqueo).
- "subio": un cargo recurrente que subió de precio en el mes (los avisos de Recurrentes; quien
  llama los pasa ya calculados, por huella).
- "aporte_posible" y "cobro_posible": un débito que parece otro aporte a una inversión o un
  crédito que parece un cobro de una (`investments.suggestions`; quien llama los pasa ya
  calculados, por huella, como `Hint`). Solo proponen: el usuario confirma.
- "regla_posible": un comercio que recibió a mano «solo esta» la misma categoría varias veces
  (`changelog_rules.rule_suggestions`; quien llama lo agrega, en el mes de la más reciente).
- "reserva_posible": un gasto que parece de una reserva (`reserves.link_suggestions`; quien
  llama lo agrega). «Sí» lo vincula; «No» lo da por revisado y no vuelve.

Lo que ya es de una inversión no sale como "tercero_grande" (un aporte es "Inversiones", no
"Transferencias a terceros") ni como "ingreso_inusual" (ni el rendimiento ni el capital que
vuelve). Un movimiento que se propone como aporte o cobro sale solo con esa propuesta, salvo
que ya se haya revisado («No es»): entonces la propuesta queda revisada (solo en el historial)
y vuelve a salir lo demás que sea.

Lo revisado se guarda aparte por huella y tipo (`review_marks`; los gastos únicos usan sus
descartes de siempre, `one_off_dismissals`), así sobrevive a `parse --retry`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, get_args

from finanzas.analysis import categories, one_offs
from finanzas.analysis.rates import Rate, to_dop
from finanzas.analysis.recurring_marks import Mark
from finanzas.analysis.report import money
from finanzas.analysis.spending import Movement

Kind = Literal[
    "unico",
    "ingreso_inusual",
    "tercero_grande",
    "duplicado",
    "subio",
    "aporte_posible",
    "cobro_posible",
    "regla_posible",
    "reserva_posible",
]
KINDS: tuple[Kind, ...] = get_args(Kind)

UNUSUAL_INCOME_DOP = Decimal(10_000)
LARGE_THIRD_PARTY_DOP = Decimal(25_000)
NEW_COUNTERPART_DAYS = 60
HISTORY_DAYS = 365
DUPLICATE_DAYS = 1
NEXT_DAY_MIN_DOP = Decimal(500)  # al día siguiente, un duplicado se revisa desde este monto
RECURRING_DAYS = 60  # un cargo igual repetido tantas veces en estos días no es un duplicado
RECURRING_CHARGES = 3

RateForMonth = Callable[[str], Rate | None]


@dataclass(frozen=True)
class Item:
    kind: Kind
    fingerprint: str
    day: date
    merchant: str
    description: str
    account: str
    amount: Decimal  # en la moneda original, positivo (lo que entró o salió)
    currency: str
    amount_dop: Decimal | None  # None: US$ sin tasa
    reason: str
    reviewed: bool = False
    investment_id: int | None = None  # aporte o cobro posible: la inversión que se propone
    category_id: int | None = None  # regla posible: la categoría que se propone
    reserve_id: int | None = None  # reserva posible: la reserva que se propone


@dataclass(frozen=True)
class Hint:
    """Una propuesta de inversión para un movimiento (ver `investments.suggestions`)."""

    kind: Kind  # "aporte_posible" o "cobro_posible"
    reason: str
    investment_id: int


def detect(
    movements: Sequence[Movement],
    month: str,
    *,
    rate_for_month: RateForMonth,
    marks: Mapping[tuple[str, str], Mark] | None = None,
    price_ups: Mapping[str, str] | None = None,
    reviewed: Collection[tuple[str, str]] = (),
    dismissed: Collection[str] = (),
    hints: Mapping[str, Hint] | None = None,
    unions: Mapping[str, str] | None = None,
) -> list[Item]:
    """Todo lo de `month` para revisar, pendiente y revisado (`Item.reviewed`).

    `reviewed`: pares (huella, tipo) marcados "Ya lo revisé"; `dismissed`: gastos únicos
    descartados ("No es único"), que cuentan como revisados. `price_ups`: huella del cobro que
    subió -> frase del aviso de Recurrentes. `hints`: huella -> aporte o cobro posible.
    """
    done = set(reviewed)
    # Una propuesta ya revisada («No es») no esconde lo que ese movimiento es por sí mismo.
    proposed = {fp: hint for fp, hint in (hints or {}).items() if (fp, hint.kind) not in done}
    found = [
        *_one_offs(movements, month, rate_for_month, marks or {}, dismissed, unions),
        *(
            i
            for i in _unusual_incomes(movements, month, rate_for_month)
            if i.fingerprint not in proposed
        ),
        *(
            i
            for i in _large_third_party(movements, month, rate_for_month)
            if i.fingerprint not in proposed
        ),
        *_duplicates(movements, month, rate_for_month),
        *_price_ups(movements, month, rate_for_month, price_ups or {}),
        *_investment_hints(movements, month, rate_for_month, hints or {}),
    ]
    marked = [
        _with_reviewed(
            item,
            (item.fingerprint, item.kind) in done
            or (item.kind == "unico" and item.fingerprint in dismissed),
        )
        for item in found
    ]
    return sorted(marked, key=lambda i: (-i.day.toordinal(), KINDS.index(i.kind), i.fingerprint))


def _with_reviewed(item: Item, reviewed: bool) -> Item:
    return item if item.reviewed == reviewed else replace(item, reviewed=reviewed)


def _item(kind: Kind, move: Movement, dop: Decimal | None, reason: str) -> Item:
    return Item(
        kind=kind,
        fingerprint=move.fingerprint,
        day=move.day,
        merchant=move.merchant,
        description=move.description,
        account=move.account,
        amount=abs(move.amount),
        currency=move.currency,
        amount_dop=None if dop is None else abs(dop),
        reason=reason,
    )


def _dop(move: Movement, rate_for_month: RateForMonth) -> Decimal | None:
    return to_dop(move.amount, move.currency, rate_for_month(move.month))


def _one_offs(
    movements: Sequence[Movement],
    month: str,
    rate_for_month: RateForMonth,
    marks: Mapping[tuple[str, str], Mark],
    dismissed: Collection[str],
    unions: Mapping[str, str] | None = None,
) -> list[Item]:
    """Las sugerencias pendientes y, aparte, las ya descartadas (para el historial)."""

    def suggest(skip: Collection[str], limit: int | None) -> list[one_offs.Suggestion]:
        return one_offs.suggest(
            movements,
            month,
            rate_for_month=rate_for_month,
            dismissed=skip,
            marks=marks,
            limit=limit,
            unions=unions,
        )

    pending = suggest(dismissed, one_offs.MAX_PER_MONTH)
    seen = {s.fingerprint for s in pending}
    # Sin tope: un descartado no debe perderse del historial porque haya 5 más grandes.
    everything = suggest((), None)
    done = [s for s in everything if s.fingerprint in dismissed and s.fingerprint not in seen]
    by_fp = {m.fingerprint: m for m in movements}
    return [
        _item("unico", by_fp[s.fingerprint], s.amount_dop, " · ".join(s.reasons))
        for s in (*pending, *done)
        if s.fingerprint in by_fp
    ]


def _unusual_incomes(
    movements: Sequence[Movement], month: str, rate_for_month: RateForMonth
) -> list[Item]:
    if not movements:
        return []
    first = min(m.day for m in movements)
    incomes = [m for m in movements if m.kind == "ingreso" and m.amount < 0]
    found = []
    for move in incomes:
        if move.link == "investment":
            continue  # un rendimiento ya enlazado: se sabe de dónde vino
        if move.month != month or move.day - first < timedelta(days=NEW_COUNTERPART_DAYS):
            continue
        dop = _dop(move, rate_for_month)
        if dop is None or -dop < UNUSUAL_INCOME_DOP:
            continue
        start = move.day - timedelta(days=HISTORY_DAYS)
        seen = any(
            other.merchant == move.merchant and start <= other.day < move.day for other in incomes
        )
        if not seen:
            known = min(HISTORY_DAYS, (move.day - first).days)
            since = "en el último año" if known >= HISTORY_DAYS else f"en los últimos {known} días"
            reason = f"Ingreso de {money(-dop, 'DOP')} de una contraparte nueva: no te pagó {since}"
            found.append(_item("ingreso_inusual", move, dop, reason))
    return found


def _large_third_party(
    movements: Sequence[Movement], month: str, rate_for_month: RateForMonth
) -> list[Item]:
    found = []
    for move in movements:
        if move.month != month or move.ref != categories.THIRD_PARTY or move.amount <= 0:
            continue
        dop = _dop(move, rate_for_month)
        if dop is not None and dop >= LARGE_THIRD_PARTY_DOP:
            reason = (
                f"Transferencia a terceros de {money(dop, 'DOP')} "
                f"(desde {money(LARGE_THIRD_PARTY_DOP, 'DOP')} se revisa)"
            )
            found.append(_item("tercero_grande", move, dop, reason))
    return found


def _investment_hints(
    movements: Iterable[Movement],
    month: str,
    rate_for_month: RateForMonth,
    hints: Mapping[str, Hint],
) -> list[Item]:
    found = []
    for move in movements:
        hint = hints.get(move.fingerprint)
        if hint is None or move.month != month:
            continue
        item = _item(hint.kind, move, _dop(move, rate_for_month), hint.reason)
        found.append(replace(item, investment_id=hint.investment_id))
    return found


def _duplicates(
    movements: Sequence[Movement], month: str, rate_for_month: RateForMonth
) -> list[Item]:
    groups: defaultdict[tuple[str, str, Decimal, str], list[Movement]] = defaultdict(list)
    for move in movements:
        if move.kind == "gasto" and move.amount > 0:
            groups[(move.account, move.merchant, move.amount, move.currency)].append(move)
    found = []
    for charges in groups.values():
        charges.sort(key=lambda m: (m.day, m.fingerprint))
        for index, (before, after) in enumerate(zip(charges, charges[1:], strict=False)):
            if after.month != month or (after.day - before.day).days > DUPLICATE_DAYS:
                continue
            dop = _dop(after, rate_for_month)
            same_day = after.day == before.day
            if not same_day and (dop if dop is not None else after.amount) < NEXT_DAY_MIN_DOP:
                continue  # un cargo chico al día siguiente (un peaje, un café) es normal
            if _recurs(charges[:index], before.day):
                continue
            when = "el mismo día" if same_day else "el día anterior"
            reason = f"Mismo comercio, monto y cuenta que otro cargo {when}"
            found.append(_item("duplicado", after, dop, reason))
    return found


def _recurs(earlier: Sequence[Movement], day: date) -> bool:
    """El mismo cargo ya se repite: RECURRING_CHARGES o más en los RECURRING_DAYS anteriores."""
    start = day - timedelta(days=RECURRING_DAYS)
    return sum(1 for m in earlier if start <= m.day < day) >= RECURRING_CHARGES


def _price_ups(
    movements: Iterable[Movement],
    month: str,
    rate_for_month: RateForMonth,
    price_ups: Mapping[str, str],
) -> list[Item]:
    return [
        _item("subio", move, _dop(move, rate_for_month), price_ups[move.fingerprint])
        for move in movements
        if move.fingerprint in price_ups and move.month == month
    ]
