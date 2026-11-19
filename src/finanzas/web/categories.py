"""Pantalla de Categorías: lista con cuántas transacciones tiene cada una y previsualización
de palabras clave (qué movería guardarlas, sin guardar)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from finanzas.analysis import catalog, categories, rates
from finanzas.analysis.catalog import Catalog, Category
from finanzas.analysis.rates import Rate
from finanzas.analysis.spending import Movement


@dataclass(frozen=True)
class CategoryView:
    category: Category
    count_year: int  # transacciones del año en curso con esta categoría


@dataclass(frozen=True)
class Preview:
    count: int  # transacciones que cambiarían de categoría
    total: Decimal  # su monto en RD$ (en valor absoluto), sin los US$ sin tasa
    unconverted_usd: Decimal
    conflicts: int  # de las que se moverían por las palabras nuevas, cuántas tocan otra categoría


def category_views(known: Catalog, movements: Sequence[Movement], year: int) -> list[CategoryView]:
    counts = Counter(m.ref for m in movements if m.day.year == year)
    return [CategoryView(c, counts[c.ref]) for c in known.items]


def preview(
    now: Sequence[Movement],
    proposed: Sequence[Movement],
    known: Catalog,
    category_id: int,
    rates_by_month: Mapping[str, Rate],
) -> Preview:
    """Compara la carga de hoy (`now`) con la que daría el catálogo propuesto (`proposed`).

    Las dos listas vienen de `spending.load_all` sobre la misma base, en el mismo orden.
    `known` es el catálogo propuesto: de él salen las palabras de `category_id`.
    """
    before = {m.fingerprint: m.ref for m in now}
    moved = [m for m in proposed if before.get(m.fingerprint) != m.ref]
    total = unconverted = Decimal(0)
    for item in moved:
        dop = rates.to_dop(
            abs(item.amount), item.currency, rates.rate_for(rates_by_month, item.month)
        )
        if dop is None:
            unconverted += abs(item.amount)
        else:
            total += dop
    # Solo chocan las que de verdad se moverían (no las corregidas a mano ni las detectadas).
    return Preview(len(moved), total, unconverted, _conflicts(moved, known, category_id))


def _conflicts(movements: Sequence[Movement], known: Catalog, category_id: int) -> int:
    found = 0
    for item in movements:
        hits = known.keyword_hits(categories.clean(item.description))
        mine = any(hit.category.id == category_id for hit in hits)
        if mine and any(hit.category.id != category_id for hit in hits):
            found += 1
    return found


# Errores de categorías -> código HTTP (lo demás de `catalog.CategoryError`, 422).
_STATUS: tuple[tuple[type[catalog.CategoryError], int], ...] = (
    (catalog.NotFound, 404),
    (catalog.DuplicateName, 409),
    (catalog.Forbidden, 400),
)


def http_status(exc: catalog.CategoryError) -> int:
    return next((code for kind, code in _STATUS if isinstance(exc, kind)), 422)


def filter_ref(known: Catalog, name: str | None, category_id: int | None) -> str | None:
    """Referencia de la categoría pedida en un filtro, por id o por nombre (de hoy o de antes).

    Una desconocida da una referencia que no coincide con nada: la lista sale vacía.
    """
    if category_id is not None:
        found = known.by_id(category_id)
        return f"?{category_id}" if found is None else found.ref
    if name is None:
        return None
    by_name = known.by_name(name)
    return f"?{name}" if by_name is None else by_name.ref


def edit_target(known: Catalog, name: str | None, category_id: int | None) -> int | None:
    """Id de la categoría pedida al corregir (`category_id` gana sobre el nombre).

    None si no se pidió ninguna; `catalog.CategoryError` si no existe o solo la pone su vínculo
    («Caja fuerte», «Inversiones», «Devolución de capital»).
    """
    if category_id is not None:
        found = known.by_id(category_id)
    elif name is not None:
        found = known.by_name(name)
    else:
        return None
    if found is None:
        raise catalog.CategoryError(f"categoría desconocida: {category_id or name}")
    catalog.check_choosable(found)
    return found.id
