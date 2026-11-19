"""«Para revisar» para la web: las reglas de `analysis.review` con los avisos de Recurrentes,
las cuentas elegidas y la etiqueta de cada cuenta. Funciones puras."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property

from finanzas.analysis import investments, reserves, review
from finanzas.analysis import links as link_data
from finanzas.analysis.accounts import BANK_KINDS, AccountInfo
from finanzas.analysis.changelog_rules import RuleSuggestion
from finanzas.analysis.rates import Rate, rate_for, to_dop
from finanzas.analysis.recurring_marks import Mark
from finanzas.analysis.reserves import Reserve
from finanzas.analysis.spending import Movement
from finanzas.web import recurring as recurring_view

HISTORY_MONTHS = 12


@dataclass(frozen=True)
class ReviewView:
    item: review.Item
    account_label: str


@dataclass(frozen=True)
class Context:
    """Lo que no cambia de un mes a otro."""

    flow: Sequence[Movement]  # todos los movimientos (todas las cuentas)
    accounts: Sequence[AccountInfo]
    rates: Mapping[str, Rate]
    marks: Mapping[tuple[str, str], Mark]
    reviewed: Collection[tuple[str, str]]
    dismissed: Collection[str]
    selected: frozenset[str] | None = None
    links: link_data.Links = link_data.NONE  # para proponer aportes y cobros de inversiones
    # Reglas por comercio propuestas (de la bitácora), con el nombre de su categoría.
    rules: Sequence[tuple[RuleSuggestion, str]] = ()
    unions: Mapping[str, str] = field(default_factory=dict)  # uniones de Recurrentes
    # Gastos que parecen de una reserva (`web.budget.link_hints`): huella -> la reserva.
    reserve_hints: Mapping[str, Reserve] = field(default_factory=dict)

    @cached_property
    def hints(self) -> dict[str, review.Hint]:
        """Aportes y cobros posibles de las inversiones, con todas las cuentas (como
        Compartidos): se calculan una vez por pedido, no una por mes del historial."""
        if not self.links.investments:
            return {}
        found = investments.states(self.flow, self.links, self.rates)
        banks = {a.key for a in self.accounts if a.kind in BANK_KINDS}
        proposed = investments.suggestions(self.flow, self.links, found, self.rates, banks)
        return {fp: review.Hint(s.kind, s.reason, s.state.id) for fp, s in proposed.items()}


def month_items(ctx: Context, month: str) -> list[ReviewView]:
    """Lo del mes, pendiente y revisado, con la historia de las cuentas elegidas.

    Como la tarjeta de gastos únicos: una compra rara en la tarjeta elegida se juzga contra lo
    que se compra con ella. Los avisos de precio salen de Recurrentes con las mismas cuentas,
    medidos contra el último dato de todas.
    """
    mine = [m for m in ctx.flow if ctx.selected is None or m.account in ctx.selected]
    labels = {info.key: info.label for info in ctx.accounts}
    found = review.detect(
        mine,
        month,
        rate_for_month=lambda m: rate_for(ctx.rates, m),
        marks=ctx.marks,
        price_ups=_price_ups(ctx, mine, month),
        reviewed=ctx.reviewed,
        dismissed=ctx.dismissed,
        hints=ctx.hints,
        unions=ctx.unions,
    )
    found = [*_rule_items(ctx, mine, month), *_reserve_items(ctx, mine, month), *found]
    return [ReviewView(item, labels.get(item.account, item.account)) for item in found]


def _rule_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """«UBER EATS: lo pusiste 2 veces en Delivery. ¿Siempre?», en el mes de la más reciente de
    esas transacciones (si es de las cuentas elegidas)."""
    by_fp = {m.fingerprint: m for m in mine}
    items = []
    for found, name in ctx.rules:
        latest = next((by_fp[fp] for fp in found.fingerprints if fp in by_fp), None)
        if latest is None or latest.month != month:
            continue
        amount = abs(latest.gross if latest.gross is not None else latest.amount)
        items.append(
            review.Item(
                kind="regla_posible",
                fingerprint=latest.fingerprint,
                day=latest.day,
                merchant=latest.merchant,
                description=latest.description,
                account=latest.account,
                amount=amount,
                currency=latest.currency,
                amount_dop=to_dop(amount, latest.currency, rate_for(ctx.rates, month)),
                reason=f"{found.merchant}: lo pusiste {found.count} veces en {name}. ¿Siempre?",
                category_id=found.category_id,
            )
        )
    return items


def _reserve_items(ctx: Context, mine: Sequence[Movement], month: str) -> list[review.Item]:
    """«¿Es de la reserva «Marbete»? (vence en enero)» para cada gasto del mes que lo parece; lo
    ya marcado «No» sale como revisado."""
    items = []
    for move in mine:
        reserve = ctx.reserve_hints.get(move.fingerprint)
        if reserve is None or move.month != month:
            continue
        due = reserves.near_due(reserve, month) or reserve.due_month
        items.append(
            review.Item(
                kind="reserva_posible",
                fingerprint=move.fingerprint,
                day=move.day,
                merchant=move.merchant,
                description=move.description,
                account=move.account,
                amount=abs(move.amount),
                currency=move.currency,
                amount_dop=to_dop(abs(move.amount), move.currency, rate_for(ctx.rates, month)),
                reason=f"¿Es de la reserva «{reserve.name}»? Vence en "
                f"{reserves.month_name(due)} {due[:4]}",
                reviewed=(move.fingerprint, "reserva_posible") in ctx.reviewed,
                reserve_id=reserve.id,
            )
        )
    return items


def history(ctx: Context, months: Sequence[str], kind: str | None = None) -> list[ReviewView]:
    """Lo de los meses dados (los más recientes primero), pendiente y revisado."""
    found = [
        view for month in sorted(set(months), reverse=True) for view in month_items(ctx, month)
    ]
    return [view for view in found if kind is None or view.item.kind == kind]


def _price_ups(ctx: Context, mine: Sequence[Movement], month: str) -> dict[str, str]:
    expenses = [m for m in mine if m.kind == "gasto"]
    if not expenses:
        return {}
    as_of = max(m.day for m in ctx.flow if m.kind == "gasto")
    overview = recurring_view.build_overview(
        expenses, ctx.marks, ctx.rates, month, as_of=as_of, unions=ctx.unions
    )
    return {a.fingerprint: a.detail for a in overview.alerts if a.kind == "subio" and a.fingerprint}
