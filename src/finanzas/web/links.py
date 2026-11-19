"""Vínculos para la web: lo que cada fila de Transacciones muestra de grupos compartidos,
reembolsos, cambios de divisas e inversiones, y las validaciones de los pedidos que los
cambian."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from functools import cached_property

from finanzas.analysis import cash_box, exchanges, investments, shared
from finanzas.analysis.accounts import BANK_KINDS, AccountInfo
from finanzas.analysis.exchanges import ExchangeState
from finanzas.analysis.investments import InvestmentState, Suggestion
from finanzas.analysis.links import AlreadyLinked, LinkError, Links
from finanzas.analysis.rates import Rate, rate_for
from finanzas.analysis.shared import ExpenseState, SharedState
from finanzas.analysis.spending import Movement


@dataclass(frozen=True)
class LinkedTx:
    """Otra transacción mencionada en el detalle (un reembolso, una pata, una sugerencia)."""

    fingerprint: str
    day: date
    merchant: str
    account_label: str
    amount: Decimal  # el del estado (un crédito, negativo)
    currency: str
    # Un crédito en otra moneda que la del gasto: lo que vale en la del gasto (a la tasa del mes).
    converted: Decimal | None = None
    converted_currency: str | None = None
    description: str = ""  # como aparece en el estado (el buscador de los selectores la mira)


@dataclass(frozen=True)
class GroupView:
    """Un grupo compartido con sus gastos y créditos listos para mostrar."""

    state: SharedState
    expenses: tuple[tuple[ExpenseState, LinkedTx], ...]  # del más viejo al más nuevo
    credits: tuple[LinkedTx, ...]  # créditos enlazados presentes, por fecha


@dataclass(frozen=True)
class RowLinks:
    # Vínculo guardado de la fila, aunque esté dormido (su gasto ya no aparece o dejó de ser
    # gasto; al cambio le falta una pata): "shared", "reimbursement", "exchange", "investment"
    # o "".
    kind: str = ""
    link_id: int | None = None
    # Qué se puede hacer con la fila (las mismas reglas que valida el servidor).
    can_share: bool = False
    can_reimburse: bool = False
    can_exchange: bool = False
    group: GroupView | None = None  # el grupo activo de la fila (como gasto o como reembolso)
    expense: ExpenseState | None = None  # la fila como gasto de un grupo
    reimbursement_of: LinkedTx | None = None  # el primer gasto del grupo que reembolsa
    suggested_group: SharedState | None = None  # «¿Reembolso de <grupo>?»
    exchange: ExchangeState | None = None
    exchange_legs: tuple[LinkedTx, ...] = ()  # todas las patas del cambio
    suggested_exchange_with: LinkedTx | None = None
    can_invest: bool = False  # un débito que puede ser un aporte («Es una inversión…»)
    can_invest_credit: bool = False  # un crédito que puede ser de una («Es de una inversión…»)
    investment: InvestmentState | None = None  # la inversión de la fila (activa)
    investment_role: str = ""  # su tipo en ella ("contribution", "return", "capital", "mixed")
    investment_capital: Decimal | None = None  # en un crédito mixto, la parte de capital
    suggested_investment: Suggestion | None = None  # «¿Otro aporte a…?» / «¿Cobro de…?»
    can_store: bool = False  # un retiro que se puede marcar «Lo guardé en la caja fuerte»
    can_deposit: bool = False  # un crédito bancario que puede ser «Vino de la caja fuerte»
    cash_box_role: str = ""  # "stored" (retiro guardado), "deposit" (depósito de la caja) o ""
    # En un depósito: la moneda en que salió de la caja y cuánto (None: sin tasa, no cuenta).
    cash_box_currency: str | None = None
    cash_box_amount: Decimal | None = None


@dataclass(frozen=True)
class Context:
    """Todo lo de los vínculos calculado una vez por pedido."""

    links: Links
    movements: tuple[Movement, ...]
    labels: Mapping[str, str]
    banks: frozenset[str]
    groups: Mapping[int, SharedState] = field(default_factory=dict)
    exchange_states: Mapping[int, ExchangeState] = field(default_factory=dict)
    reimbursement_suggestions: Mapping[str, int] = field(default_factory=dict)
    exchange_suggestions: Mapping[str, str] = field(default_factory=dict)
    rates: Mapping[str, Rate] = field(default_factory=dict)
    investment_states: Mapping[int, InvestmentState] = field(default_factory=dict)
    investment_suggestions: Mapping[str, Suggestion] = field(default_factory=dict)

    def movement(self, fingerprint: str) -> Movement | None:
        return self._by_fp.get(fingerprint)

    def linked(self, fingerprint: str) -> LinkedTx | None:
        move = self._by_fp.get(fingerprint)
        return None if move is None else linked_tx(move, self.labels)

    def credit_for(self, credit: Movement, currency: str) -> LinkedTx:
        """Un crédito mencionado junto a un gasto en `currency`: si es de la otra moneda, con
        su equivalente (o sin él si falta la tasa)."""
        found = linked_tx(credit, self.labels)
        if credit.currency == currency:
            return found
        value = shared.converted(credit, currency, self.rates)
        return replace(found, converted=value, converted_currency=currency)

    @cached_property
    def expense_states(self) -> dict[str, ExpenseState]:
        """El estado de cada gasto compartido presente, por huella."""
        return shared.by_expense(self.groups)

    def group_view(self, link_id: int) -> GroupView | None:
        state = self.groups.get(link_id)
        if state is None:
            return None
        currency = state.first.currency
        credits = sorted(
            (move for fp in state.link.reimbursements if (move := self.movement(fp)) is not None),
            key=lambda m: (m.day, m.fingerprint),
        )
        return GroupView(
            state=state,
            expenses=tuple((e, linked_tx(e.move, self.labels)) for e in state.expenses),
            credits=tuple(self.credit_for(m, currency) for m in credits),
        )

    @cached_property
    def _by_fp(self) -> dict[str, Movement]:
        return {m.fingerprint: m for m in self.movements}


def linked_tx(move: Movement, labels: Mapping[str, str]) -> LinkedTx:
    return LinkedTx(
        fingerprint=move.fingerprint,
        day=move.day,
        merchant=move.merchant,
        account_label=labels.get(move.account, move.account),
        amount=shared.gross(move),
        currency=move.currency,
        description=move.description,
    )


def context(
    movements: Sequence[Movement],
    found: Links,
    accounts: Sequence[AccountInfo],
    rates: Mapping[str, Rate],
    suggest: bool = True,
    reviewed: Collection[tuple[str, str]] = (),
) -> Context:
    """`suggest=False` no busca sugerencias (el Resumen no las necesita). `reviewed`: lo marcado
    en «Para revisar» (huella, tipo): una propuesta de inversión ya revisada («No es») no se
    vuelve a sugerir en la fila."""
    banks = frozenset(a.key for a in accounts if a.kind in BANK_KINDS)
    labels = {a.key: a.label for a in accounts}
    moves = tuple(movements)
    groups = shared.states(moves, found, rates)
    invested = investments.states(moves, found, rates)
    if not suggest:
        return Context(
            found,
            moves,
            labels,
            banks,
            groups,
            exchanges.states(moves, found),
            rates=rates,
            investment_states=invested,
        )
    return Context(
        links=found,
        movements=moves,
        labels=labels,
        banks=banks,
        groups=groups,
        exchange_states=exchanges.states(moves, found),
        reimbursement_suggestions=shared.suggestions(moves, found, groups, rates),
        exchange_suggestions=exchanges.suggestions(
            moves, found, banks, lambda month: rate_for(rates, month)
        ),
        rates=rates,
        investment_states=invested,
        investment_suggestions={
            fp: hint
            for fp, hint in investments.suggestions(moves, found, invested, rates, banks).items()
            if (fp, hint.kind) not in reviewed
        },
    )


def row_links(ctx: Context, fingerprints: Collection[str]) -> dict[str, RowLinks]:
    """Lo que muestra cada una de estas filas (y qué se puede hacer con ellas)."""
    by_fp = {m.fingerprint: m for m in ctx.movements}
    exchange_of = {
        leg.fingerprint: state for state in ctx.exchange_states.values() for leg in state.legs
    }
    found: dict[str, RowLinks] = {}
    for fp in fingerprints:
        move = by_fp.get(fp)
        if move is None:
            continue
        found[fp] = _row(ctx, move, exchange_of.get(fp))
    return found


def _row(ctx: Context, move: Movement, exchange: ExchangeState | None) -> RowLinks:
    fp = move.fingerprint
    expense = ctx.expense_states.get(fp)
    kind, link_id = _stored(ctx.links, fp)
    group = None
    if link_id is not None and (expense is not None or kind == "reimbursement"):
        group = ctx.group_view(link_id)
    owner = ctx.links.reimbursed(fp)
    of = None
    if owner is not None:
        first = ctx.groups[owner.id].first.fingerprint if owner.id in ctx.groups else None
        of = ctx.linked(first or owner.expenses[0].fingerprint)
    suggested = ctx.reimbursement_suggestions.get(fp)
    counterpart = ctx.exchange_suggestions.get(fp)
    stored = ctx.links.investment_for(fp)
    member = None if stored is None else stored.member(fp)
    box = ctx.links.cash_box_for(fp)
    boxed = None if box is None else box.member(fp)
    return RowLinks(
        kind=kind,
        link_id=link_id,
        can_share=kind in ("", "shared") and is_shareable(move),
        can_reimburse=shared.is_eligible_credit(move, ctx.links),
        can_exchange=exchanges.is_eligible(move, ctx.links, ctx.banks),
        group=group,
        expense=expense,
        reimbursement_of=of,
        suggested_group=None if suggested is None else ctx.groups.get(suggested),
        exchange=exchange,
        exchange_legs=()
        if exchange is None
        else tuple(linked_tx(leg, ctx.labels) for leg in exchange.legs),
        suggested_exchange_with=None if counterpart is None else ctx.linked(counterpart),
        can_invest=can_invest(ctx, move),
        can_invest_credit=can_invest_credit(ctx, move),
        investment=None if stored is None else ctx.investment_states.get(stored.id),
        investment_role="" if member is None else member.role,
        investment_capital=None if member is None else member.capital,
        suggested_investment=ctx.investment_suggestions.get(fp),
        can_store=cash_box.can_store(move, ctx.links),
        can_deposit=cash_box.can_deposit(move, ctx.links, ctx.banks),
        **_boxed(ctx, move, boxed),
    )


def _boxed(ctx: Context, move: Movement, member: cash_box.CashBoxMember | None) -> dict:
    """Lo de la caja fuerte de la fila: su rol y, en un depósito, lo que salió de la caja."""
    if member is None:
        return {}
    if member.role == "stored":
        return {"cash_box_role": "stored"}
    gross = shared.gross(move)
    currency = member.box_currency or move.currency
    taken = (
        cash_box.deposit_amount(member, -gross, move.currency, move.month, ctx.rates)
        if gross < 0
        else None
    )
    return {"cash_box_role": "deposit", "cash_box_currency": currency, "cash_box_amount": taken}


def _stored(found: Links, fingerprint: str) -> tuple[str, int | None]:
    """El vínculo guardado de la huella (rol e id), esté activo o dormido."""
    if (owner := found.shared_for(fingerprint)) is not None:
        return "shared", owner.id
    if (owner := found.reimbursed(fingerprint)) is not None:
        return "reimbursement", owner.id
    if (exchange := found.exchange_for(fingerprint)) is not None:
        return "exchange", exchange.id
    if (investment := found.investment_for(fingerprint)) is not None:
        return "investment", investment.id
    if (box := found.cash_box_for(fingerprint)) is not None:
        return "cash_box", box.id
    if (reserve := found.reserve_for(fingerprint)) is not None:
        return "reserve", reserve
    return "", None


def can_invest(ctx: Context, move: Movement) -> bool:
    """Un débito de una cuenta bancaria que puede ser un aporte (las tarjetas no mandan dinero a
    otra persona: así no se ofrece en cada compra)."""
    return move.account in ctx.banks and investments.is_contribution_candidate(move, ctx.links)


def can_invest_credit(ctx: Context, move: Movement) -> bool:
    """Un crédito de una cuenta bancaria que puede ser de una inversión."""
    return move.account in ctx.banks and investments.is_credit_candidate(move, ctx.links)


def is_shareable(move: Movement) -> bool:
    return shared.is_shareable(move)


# --- Validaciones de los pedidos ------------------------------------------------------------


def check_shareable(found: Links, move: Movement) -> None:
    if found.is_linked(move.fingerprint) and found.shared_for(move.fingerprint) is None:
        raise AlreadyLinked("la transacción ya está en otro vínculo")
    if not is_shareable(move):
        raise LinkError("solo un gasto (monto positivo) se puede compartir")


def check_reimbursement(ctx: Context, link_id: int, credit: Movement) -> None:
    """El crédito puede reembolsar el grupo: no está enlazado, es un crédito elegible y hay tasa
    para pasarlo a la moneda de cada gasto del grupo."""
    if ctx.links.is_linked(credit.fingerprint):
        raise AlreadyLinked("ese crédito ya está enlazado")
    state = ctx.groups.get(link_id)
    if state is None:
        raise LinkError("el gasto no está marcado como compartido")
    if credit.amount >= 0:
        raise LinkError("solo un crédito puede ser un reembolso")
    currencies = {e.currency for e in state.expenses}
    if any(shared.converted(credit, c, ctx.rates) is None for c in currencies):
        raise LinkError(
            "falta la tasa de cambio de ese mes para pasar el crédito a la moneda del gasto"
        )
    if not shared.is_eligible_credit(credit, ctx.links):
        raise LinkError("ese crédito no puede ser un reembolso")


def check_joinable(ctx: Context, link_id: int, move: Movement) -> None:
    """El gasto se puede sumar al grupo: es un gasto sin vínculo y el grupo existe."""
    if ctx.links.group(link_id) is None:
        raise LookupError(f"grupo desconocido: {link_id}")
    if ctx.links.is_linked(move.fingerprint):
        raise AlreadyLinked("la transacción ya está en otro vínculo")
    if not is_shareable(move):
        raise LinkError("solo un gasto (monto positivo) se puede compartir")


def check_legs(ctx: Context, new: Sequence[Movement], current: Sequence[Movement] = ()) -> None:
    """Las patas nuevas pueden serlo y, con las que ya tiene el cambio, forman uno."""
    for leg in new:
        if ctx.links.is_linked(leg.fingerprint):
            raise AlreadyLinked("una de las transacciones ya está en otro vínculo")
        if leg.account not in ctx.banks:
            raise LinkError("las patas de un cambio son de cuentas bancarias")
        if not exchanges.is_eligible(leg, ctx.links, ctx.banks):
            raise LinkError(
                "salario, pagos de tarjeta, envíos entre tus cuentas o algo ya enlazado "
                "no pueden ser una pata"
            )
    exchanges.check_legs([*current, *new])
