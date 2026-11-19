"""Consultas y correcciones de transacciones para la web."""

from __future__ import annotations

import sqlite3
import unicodedata
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, get_args

from finanzas.analysis import catalog, categories, corrections, rates
from finanzas.analysis.accounts import AccountInfo
from finanzas.analysis.categories import Kind
from finanzas.analysis.rates import Rate
from finanzas.analysis.spending import Movement
from finanzas.web.links import RowLinks

Scope = Literal["transaction", "merchant"]
SCOPES: tuple[str, ...] = get_args(Scope)
# Filtro de gastos compartidos: todos o solo los que tienen pendiente ("te deben").
SharedFilter = Literal["shared", "pending"]


@dataclass(frozen=True)
class TxView:
    fingerprint: str
    day: date
    merchant: str
    description: str
    category: str
    kind: Kind
    original_category: str
    account: str
    account_label: str
    amount: Decimal
    currency: str
    amount_dop: Decimal | None  # None: dólares sin tasa del mes
    one_off: bool
    corrected: bool
    merchant_year_count: int  # compras del comercio en el año de la transacción
    one_off_reasons: tuple[str, ...] = ()  # sugerida como gasto único: por qué
    one_off_dismissed: bool = False  # el usuario dijo "No es único"
    category_id: int | None = None
    note: str = ""
    gross: Decimal | None = None  # monto del estado de un gasto compartido (amount: tu parte)
    links: RowLinks = RowLinks()

    @property
    def suggested_one_off(self) -> bool:
        return bool(self.one_off_reasons)


@dataclass(frozen=True)
class Filters:
    month: str
    account: str | None = None
    category: str | None = None
    q: str | None = None
    kind: Kind | None = None
    accounts: Collection[str] | None = None  # varias cuentas; None: todas
    # Referencia estable de la categoría pedida (la resuelve quien llama, ver `catalog`);
    # gana sobre `category` (un nombre).
    category_ref: str | None = None
    shared: SharedFilter | None = None


def list_transactions(
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    rates_by_month: Mapping[str, Rate],
    filters: Filters,
    suggested: Mapping[str, tuple[str, ...]] | None = None,
    dismissed: Collection[str] = (),
    known: catalog.Catalog | None = None,
    link_rows: Callable[[Collection[str]], Mapping[str, RowLinks]] | None = None,
) -> list[TxView]:
    """Transacciones del mes, de la más reciente a la más antigua (orden de carga por día).

    `suggested`: razones de las filas sugeridas como gasto único, por huella; `dismissed`:
    huellas cuya sugerencia el usuario descartó; `known`, el catálogo (para el id de cada
    categoría); `link_rows`, lo de los vínculos de unas huellas (`web.links.row_links`).
    """
    reasons = suggested or {}
    labels = {info.key: info.label for info in accounts}
    needle = _fold(filters.q or "").strip()
    # Un enlace viejo puede traer el nombre anterior de una categoría renombrada.
    category = None if filters.category is None else categories.canonical(filters.category)
    year_counts = Counter(
        (m.merchant, m.day.year) for m in movements if m.amount > 0 and m.kind == "gasto"
    )
    selected = [
        m
        for m in movements
        if m.month == filters.month
        and (filters.account is None or m.account == filters.account)
        and (filters.accounts is None or m.account in filters.accounts)
        and _in_category(m, filters.category_ref, category)
        and (filters.kind is None or m.kind == filters.kind)
        and (not needle or _matches(m, needle))
    ]
    selected.sort(key=lambda m: m.day, reverse=True)  # estable: conserva el orden de carga
    rows = link_rows([m.fingerprint for m in selected]) if link_rows else {}
    if filters.shared is not None:
        selected = [m for m in selected if _in_shared(rows.get(m.fingerprint), filters.shared)]
    return [
        TxView(
            fingerprint=m.fingerprint,
            day=m.day,
            merchant=m.merchant,
            description=m.description,
            category=m.category,
            kind=m.kind,
            original_category=m.original_category,
            account=m.account,
            account_label=labels.get(m.account, m.account),
            amount=m.amount,
            currency=m.currency,
            amount_dop=rates.to_dop(m.amount, m.currency, rates.rate_for(rates_by_month, m.month)),
            one_off=m.one_off,
            corrected=m.corrected,
            merchant_year_count=year_counts[(m.merchant, m.day.year)],
            one_off_reasons=reasons.get(m.fingerprint, ()),
            one_off_dismissed=m.fingerprint in dismissed,
            category_id=_id_of(known, m.ref),
            note=m.note,
            gross=m.gross,
            links=rows.get(m.fingerprint, RowLinks()),
        )
        for m in selected
    ]


def _in_shared(row: RowLinks | None, wanted: SharedFilter) -> bool:
    state = None if row is None else row.expense
    if state is None:
        return False
    return wanted == "shared" or state.pending > 0


def _matches(item: Movement, needle: str) -> bool:
    """La búsqueda mira el comercio, la descripción y la nota."""
    return any(needle in _fold(text) for text in (item.merchant, item.description, item.note))


def _in_category(item: Movement, ref: str | None, name: str | None) -> bool:
    if ref is not None:
        return item.ref == ref
    return name is None or item.category == name


def _id_of(known: catalog.Catalog | None, ref: str) -> int | None:
    found = None if known is None else known.by_ref(ref)
    return None if found is None else found.id


def find(movements: Sequence[Movement], fingerprint: str) -> Movement:
    for movement in movements:
        if movement.fingerprint == fingerprint:
            return movement
    raise LookupError(f"transacción desconocida: {fingerprint}")


def apply_edit(
    conn: sqlite3.Connection,
    movement: Movement,
    category: str | int | None,
    one_off: bool | None,
    scope: Scope,
    note: str | None = None,
) -> None:
    """Guarda la corrección en la transacción de base de datos de quien llama (`with conn:`).

    `category`: id o referencia del análisis (`catalog.Category.ref`). Con alcance de
    comercio, la regla nueva reemplaza la corrección puntual que tuviera la transacción (si
    no, esa corrección seguiría ganando). `None` no toca ese campo; una nota vacía la borra.
    """
    if scope not in SCOPES:
        raise ValueError(f"alcance desconocido: {scope}")
    if category is not None:
        catalog.resolve_ref(conn, category)  # error antes de escribir nada
    if note is not None:
        corrections.set_note(conn, movement.fingerprint, note)
    if one_off is not None and one_off != movement.one_off:
        corrections.set_one_off(conn, movement.fingerprint, one_off)
    if category is None:
        return
    if scope == "merchant":
        corrections.set_transaction_category(conn, movement.fingerprint, None)
        corrections.set_merchant_category(conn, movement.merchant, category)
    else:
        corrections.set_transaction_category(conn, movement.fingerprint, category)


def _fold(text: str) -> str:
    """Minúsculas sin acentos, para comparar."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
