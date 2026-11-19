"""Categories screen: the list with how many transactions each one has, and the keyword
preview (what saving them would move, without saving)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from michelito.analysis import catalog, categories, rates
from michelito.analysis.catalog import Catalog, Category
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from michelito.i18n import t


@dataclass(frozen=True)
class CategoryView:
    category: Category
    count_year: int  # transactions of the current year with this category


@dataclass(frozen=True)
class Preview:
    count: int  # transactions whose category would change
    total: Decimal  # their amount in RD$ (absolute value), without US$ lacking a rate
    unconverted_usd: Decimal
    conflicts: int  # of those the new keywords would move, how many also hit another category


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
    """Compare today's load (`now`) with the one the proposed catalog would give (`proposed`).

    Both lists come from `spending.load_all` over the same database, in the same order.
    `known` is the proposed catalog: the keywords of `category_id` come from it.
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
    # Only the ones that would really move can conflict (not hand-corrected nor detected ones).
    return Preview(len(moved), total, unconverted, _conflicts(moved, known, category_id))


def _conflicts(movements: Sequence[Movement], known: Catalog, category_id: int) -> int:
    found = 0
    for item in movements:
        hits = known.keyword_hits(categories.clean(item.description))
        mine = any(hit.category.id == category_id for hit in hits)
        if mine and any(hit.category.id != category_id for hit in hits):
            found += 1
    return found


# Category errors -> HTTP status (any other `catalog.CategoryError`, 422).
_STATUS: tuple[tuple[type[catalog.CategoryError], int], ...] = (
    (catalog.NotFound, 404),
    (catalog.DuplicateName, 409),
    (catalog.Forbidden, 400),
)


def http_status(exc: catalog.CategoryError) -> int:
    return next((code for kind, code in _STATUS if isinstance(exc, kind)), 422)


def filter_ref(known: Catalog, name: str | None, category_id: int | None) -> str | None:
    """Reference of the category a filter asks for, by id or by name (current or former).

    An unknown one gives a reference that matches nothing: the list comes out empty.
    """
    if category_id is not None:
        found = known.by_id(category_id)
        return f"?{category_id}" if found is None else found.ref
    if name is None:
        return None
    by_name = known.by_name(name)
    return f"?{name}" if by_name is None else by_name.ref


def edit_target(known: Catalog, name: str | None, category_id: int | None) -> int | None:
    """Id of the category asked for in an edit (`category_id` wins over the name).

    None if none was asked for; `catalog.CategoryError` if it doesn't exist or only its link sets
    it (the cash box, investments and return-of-capital categories).
    """
    if category_id is not None:
        found = known.by_id(category_id)
    elif name is not None:
        found = known.by_name(name)
    else:
        return None
    if found is None:
        raise catalog.CategoryError(t("web.category.unknown", ref=category_id or name))
    catalog.check_choosable(found)
    return found.id
