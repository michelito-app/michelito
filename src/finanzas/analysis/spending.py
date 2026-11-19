"""Movimientos: carga, categoriza y agrega las transacciones guardadas.

Se cargan tarjetas y cuentas bancarias (ahorro y corriente). Qué cuenta como gasto:
- Los débitos de tarjeta de crédito (compras, intereses, comisiones).
- Los débitos de cuentas bancarias que reconoce una regla (impuestos, cargos del banco,
  seguros, efectivo, préstamos; ver `categories.categorize_bank`). Los demás son
  "Transferencias a terceros": no son gasto, pero el Resumen los resta de lo que te quedó.
- Las devoluciones y créditos de tarjeta que no son pagos restan (monto negativo), igual
  que un reembolso de la aseguradora en una cuenta bancaria (Salud en negativo).
- Los créditos de promoción de la tarjeta (cashback, bonos) son ingresos ("Otros ingresos").
- Los créditos de cuentas bancarias son ingresos ("Salario" u "Otros ingresos"; negativos),
  salvo una reversión ("DEV …"): toma la categoría del débito que anula (`reversals`) o,
  sin él, resta de "Transferencias a terceros".
- Los pagos a la tarjeta y entre mis cuentas son transferencias: no cuentan.
- Un gasto compartido cuenta solo por tu parte (`shared`); los créditos que lo reembolsan son
  "Reembolso" y las patas de un cambio de divisas, "Cambio de divisas" (`links`): ninguno de
  los dos es ingreso ni gasto.
- En una inversión (`links`, `investments`) el aporte es "Inversiones" (transferencia: no resta
  de lo que te quedó), el rendimiento "Rendimientos" (ingreso) y la devolución de capital
  "Devolución de capital" (transferencia); de un crédito mixto solo la parte de rendimiento es
  ingreso (`amount`; `gross` guarda el crédito entero).
- La caja fuerte (`cash_box`) es una cuenta más: sus entradas (ingreso) y salidas (gasto)
  anotadas a mano son movimientos suyos; un retiro guardado en ella o un depósito que salió de
  ella es "Caja fuerte" (transferencia: ni gasto ni ingreso, no resta de lo que te quedó).

Cada moneda se agrega por separado; no se convierte.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from finanzas.analysis import (
    accounts,
    cash_box,
    cash_box_store,
    catalog,
    categories,
    corrections,
    coverage,
    investments,
    links,
    reversals,
    shared,
    transfers,
)
from finanzas.analysis.rates import Rate
from finanzas.analysis.rates import load as load_rates
from finanzas.parsers.common import CREDIT

# Una tarjeta sin corte en este tiempo (respecto de la más reciente) se da por cerrada
# y no limita hasta dónde están completos los datos.
_ACTIVE_WINDOW = timedelta(days=45)

# El orden (fecha, corte, posición en el estado) no depende de los ids, así que la
# huella de dos cargos idénticos el mismo día se asigna igual tras reprocesar.
_TRANSACTIONS = """
SELECT t.statement_id, t.transacted_on, t.description, t.amount_cents, t.direction,
       t.currency, t.mcc,
       a.institution, a.kind, a.key AS account
FROM transactions t
JOIN statements s ON s.id = t.statement_id
JOIN accounts a ON a.id = s.account_id
WHERE a.kind {kinds}
ORDER BY t.transacted_on, s.period_end, s.currency, t.sequence
"""
_CARD_TRANSACTIONS = _TRANSACTIONS.format(kinds="= 'credit_card'")
_BANK_TRANSACTIONS = _TRANSACTIONS.format(kinds="IN ('savings', 'checking')")

_IDENTITY = ("account", "transacted_on", "description", "amount_cents", "direction", "currency")

_CUTS_BY_CARD = """
SELECT MIN(s.period_end), MAX(s.period_end)
FROM statements s JOIN accounts a ON a.id = s.account_id
WHERE a.kind = 'credit_card'
GROUP BY a.id
"""


@dataclass(frozen=True)
class Movement:
    day: date
    merchant: str
    description: str
    category: str
    amount: Decimal  # positivo: gasto; negativo: devolución o crédito
    currency: str
    institution: str
    fingerprint: str = ""
    one_off: bool = False  # gasto extraordinario: fuera de los promedios
    corrected: bool = False  # la categoría la puso el usuario
    account: str = ""  # accounts.key de la tarjeta
    original_category: str = ""  # categoría antes de las correcciones (regla aprendida o MCC)
    # Referencias estables (`catalog.Category.ref`) cuando `category` / `original_category`
    # son el nombre que se muestra; vacías: el nombre es la referencia (así se arman en las
    # pruebas). La lógica compara `ref`, nunca el nombre: renombrar no la cambia.
    category_key: str = ""
    original_key: str = ""
    category_kind: categories.Kind | None = None  # tipo de una categoría del usuario
    note: str = ""  # nota libre del usuario
    # Vínculo (`links`): "shared" (gasto compartido: `amount` es lo que cuenta como tu gasto y
    # `gross` el monto del estado), "reimbursement" (crédito que reembolsa uno) o "exchange"
    # (pata de un cambio de divisas) o "investment" (aporte o crédito de una inversión; en un
    # crédito mixto `amount` es solo el rendimiento y `gross` el crédito entero). Vacío: ninguno.
    link: str = ""
    gross: Decimal | None = None

    @property
    def ref(self) -> str:
        return self.category_key or self.category

    @property
    def original_ref(self) -> str:
        return self.original_key or self.original_category

    @property
    def kind(self) -> categories.Kind:
        """Tipo del movimiento: lo da su categoría, así que corregirla lo cambia."""
        return self.category_kind or categories.kind_of(self.ref)

    @property
    def month(self) -> str:
        return self.day.strftime("%Y-%m")


@dataclass(frozen=True)
class MerchantTotal:
    name: str
    total: Decimal
    purchases: int


@dataclass(frozen=True)
class CategoryChange:
    category: str
    current: Decimal
    average: Decimal


def load_movements(
    conn: sqlite3.Connection,
    holders: Sequence[str] | transfers.Holders = (),
    known: catalog.Catalog | None = None,
) -> tuple[Movement, ...]:
    """Movimientos de tipo gasto, con las correcciones del usuario ya aplicadas.

    `holders` como en `load_all`: sin ellos, un envío a una cuenta propia queda como
    transferencia a terceros (no es gasto, pero tampoco "Entre mis cuentas").
    """
    return tuple(m for m in load_all(conn, holders, known) if m.kind == "gasto")


def load_all(
    conn: sqlite3.Connection,
    holders: Sequence[str] | transfers.Holders = (),
    known: catalog.Catalog | None = None,
) -> tuple[Movement, ...]:
    """Todos los movimientos de tarjeta y de cuentas bancarias (gastos, ingresos, transferencias).

    Las transferencias se detectan (ver `transfers`): pagos a la tarjeta y movimientos entre
    las cuentas del usuario, que se reconocen por el nombre de un titular en `holders`
    (normalizados con `categories.clean`; o un `transfers.Holders`, que trae también números
    de cuentas propias) o por el número de otra cuenta propia.
    Las impresiones del portal no repiten días ya cubiertos (ver `coverage`).
    En una cuenta bancaria, la categoría por defecto sale de `categories.categorize_bank`;
    una reversión ("DEV …") toma la de su débito (ver `reversals`).
    Las correcciones del usuario siempre ganan sobre lo detectado; en una cuenta bancaria,
    la de un comercio solo si su tipo encaja con la dirección (ver `_bank_kinds`).

    Orden: 1. correcciones (la de la transacción gana a la del comercio); 2. transferencias
    detectadas; 3. palabras clave del usuario (`catalog`; en un banco, solo si el tipo encaja
    con la dirección, como una regla de comercio); 4. reglas, MCC y comercios aprendidos.
    `known`: el catálogo a usar (por defecto el de la base; otro, para previsualizar palabras
    clave). Cada movimiento sale con el nombre actual de su categoría y su referencia.
    """
    known = known or catalog.load(conn)
    cards = list(conn.execute(_CARD_TRANSACTIONS))
    # Antes de contar ocurrencias: una fila de impresión repetida no debe correr las huellas.
    covered = coverage.bank_coverage(conn)
    banks = [
        row
        for row in conn.execute(_BANK_TRANSACTIONS)
        if covered.keeps(row["statement_id"], date.fromisoformat(row["transacted_on"]))
    ]
    learned = categories.learn_merchants(
        (row["description"], row["mcc"]) for row in cards if not _is_payment(row)
    )
    fixes = corrections.load(conn, known)
    seen: Counter[tuple[object, ...]] = Counter()
    movements = []
    for row in (*cards, *banks):
        identity = tuple(row[key] for key in _IDENTITY)
        movements.append(_movement(row, learned, fixes, seen[identity]))
        seen[identity] += 1
    infos = accounts.account_infos(conn)
    detected = transfers.detect_transfers(
        movements, infos, holders, card_last4=transfers.last4_by_card_account(conn)
    )
    kinds = {info.key: info.kind for info in infos}
    found = [
        _with_detected(m, detected[m.fingerprint])
        if m.fingerprint in detected
        else _with_keyword(m, known, kinds.get(m.account))
        for m in movements
    ]
    # Al final: una reversión toma la categoría final del débito (detectada o corregida).
    reversed_ = reversals.pair_reversals(found, infos)
    paired = [_with_reversal(m, reversed_.get(m.fingerprint), fixes) for m in found]
    # Lo anotado a mano en la caja fuerte, después de detectar transferencias y reversiones: no
    # es de un estado (ver `cash_box`).
    manual = [_manual_movement(e, fixes) for e in cash_box_store.load_entries(conn)]
    named = tuple(_named(m, known) for m in (*paired, *(m for m in manual if m is not None)))
    # Último: los vínculos del usuario (gastos compartidos, reembolsos y cambios) ganan.
    bank_keys = {info.key for info in infos if info.kind in accounts.BANK_KINDS}
    return with_links(named, links.load(conn), known, bank_keys, load_rates(conn))


def with_links(
    movements: Sequence[Movement],
    found: links.Links,
    known: catalog.Catalog,
    banks: Collection[str] | None = None,
    rates: Mapping[str, Rate] | None = None,
) -> tuple[Movement, ...]:
    """Aplica los vínculos: sin ninguno, devuelve los mismos movimientos.

    - Cada gasto de un grupo compartido (si sigue siendo un gasto positivo) cuenta por lo que
      dice `shared.group_state` (su parte y lo dado por perdido que le toque); `gross` guarda
      el monto del estado.
    - Un crédito enlazado como reembolso es "Reembolso" siempre, aunque el vínculo esté
      dormido (su gasto ya no aparece o dejó de ser gasto): sigue enlazado hasta que se quite.
      La excepción: uno en la otra moneda del gasto sin tasa de su mes sigue como estaba.
    - Las patas de un cambio son "Cambio de divisas" siempre (también si al cambio le falta
      una pata o ya no cuadra), salvo las que no son de una cuenta bancaria.
    - En una inversión, un aporte (si sigue siendo un débito) es "Inversiones"; un crédito,
      "Rendimientos" o "Devolución de capital" según su tipo; uno mixto es "Rendimientos" por la
      parte que no es capital (`gross`, el crédito entero). Si la parte de capital ya no es menor
      que el crédito (el estado cambió), cuenta todo como capital. El capital devuelto de más
      que lo aportado hasta ese día es ganancia: cuenta como "Rendimientos" (ingreso).
    `banks`: cuentas bancarias (las patas de un cambio solo pueden ser de ellas; None: todas).
    `rates`: tasas por mes, para contar un reembolso en la otra moneda del gasto (sin ellas, un
    reembolso en otra moneda no baja lo que te deben).
    """
    if not found.shared and not found.exchanges and not found.investments and not found.cash_boxes:
        return tuple(movements)
    by_fp = {m.fingerprint: m for m in movements}
    counted: dict[str, Decimal] = {}
    credits = {
        credit
        for link in found.shared
        for credit in link.reimbursements
        if credit in by_fp and by_fp[credit].amount < 0
    }
    for link in found.shared:
        present = [
            move
            for e in link.expenses
            if (move := by_fp.get(e.fingerprint)) is not None
            and move.kind == "gasto"
            and move.amount > 0
        ]
        if not present:
            continue
        state = shared.group_state(link, present, by_fp, rates or {})
        counted.update((e.fingerprint, e.counted) for e in state.expenses)
        # Un crédito en la otra moneda sin tasa no baja ningún gasto: tampoco deja de ser
        # ingreso (si no, ese dinero desaparecería de los totales).
        credits -= state.uncounted
    legs = {
        leg
        for exchange in found.exchanges
        for leg in exchange.legs
        if leg in by_fp and (banks is None or by_fp[leg].account in banks)
    }
    invested = {
        member.fingerprint: member
        for investment in found.investments
        for member in investment.members
        if member.fingerprint in by_fp
    }
    capitals: dict[str, Decimal] = {}
    for investment in found.investments:
        pairs = [(by_fp[m.fingerprint], m) for m in investment.members if m.fingerprint in by_fp]
        capitals.update(investments.effective_capitals(pairs, rates or {}))
    boxed = {m.fingerprint: m.role for box in found.cash_boxes for m in box.members}
    return tuple(
        _invested(m, invested[m.fingerprint], capitals.get(m.fingerprint), known)
        if m.fingerprint in invested
        else _boxed(m, boxed[m.fingerprint], known)
        if m.fingerprint in boxed
        else _linked(m, counted, credits, legs, known)
        for m in movements
    )


def _boxed(item: Movement, role: str, known: catalog.Catalog) -> Movement:
    """Un retiro guardado (si sigue siendo un débito) o un depósito de la caja (si sigue siendo
    un crédito) es "Caja fuerte"; si el estado cambió, queda como estaba."""
    if (role == "stored" and item.amount > 0) or (role == "deposit" and item.amount < 0):
        return _relabeled(item, categories.CASH_BOX, known, "cash_box")
    return item


def _manual_movement(
    entry: cash_box.ManualEntry, fixes: corrections.Corrections
) -> Movement | None:
    """Una entrada (ingreso) o salida (gasto) anotada en la caja como movimiento de su cuenta; el
    saldo inicial no es un movimiento del flujo. La categoría puesta a mano (al anotarla o al
    corregirla) gana; las reglas de comercio y las palabras clave no aplican."""
    if entry.kind == "initial":
        return None
    mark = entry.fingerprint
    original = cash_box.DEFAULT_CATEGORY[entry.kind]
    chosen = fixes.transaction_category(mark)
    return Movement(
        day=entry.day,
        merchant=cash_box.MERCHANT,
        description=cash_box.DESCRIPTIONS[entry.kind],
        category=chosen or original,
        amount=-entry.amount if entry.kind == "income" else entry.amount,
        currency=entry.currency,
        institution="manual",
        fingerprint=mark,
        one_off=fixes.is_one_off(mark),
        note=fixes.note_for(mark),
        corrected=chosen is not None and chosen != original,
        account=entry.account_key,
        original_category=original,
    )


def _invested(
    item: Movement,
    member: links.InvestmentMember,
    capital: Decimal | None,
    known: catalog.Catalog,
) -> Movement:
    """Un movimiento de una inversión con la categoría que le da su tipo (ver `with_links`). Un
    aporte que ya no es un débito, o un crédito que ya no es un crédito, queda como estaba.
    `capital`: la parte de capital que cuenta (`investments.effective_capitals`): lo devuelto de
    más que lo aportado es rendimiento."""
    if member.role == "contribution":
        if item.amount <= 0:
            return item
        return _relabeled(item, categories.INVESTMENT, known, "investment")
    if item.amount >= 0:
        return item
    if member.role == "return":
        return _relabeled(item, categories.INVESTMENT_RETURN, known, "investment")
    if capital is None:
        capital = -item.amount if member.role == "capital" else (member.capital or -item.amount)
    if capital >= -item.amount:
        return _relabeled(item, categories.INVESTMENT_CAPITAL, known, "investment")
    if capital <= 0:
        return _relabeled(item, categories.INVESTMENT_RETURN, known, "investment")
    relabeled = _relabeled(item, categories.INVESTMENT_RETURN, known, "investment")
    return replace(relabeled, amount=item.amount + capital, gross=item.amount)


def _linked(
    item: Movement,
    counted: Mapping[str, Decimal],
    credits: Collection[str],
    legs: Collection[str],
    known: catalog.Catalog,
) -> Movement:
    if item.fingerprint in counted:
        return replace(item, amount=counted[item.fingerprint], gross=item.amount, link="shared")
    if item.fingerprint in credits:
        return _relabeled(item, categories.REIMBURSEMENT, known, "reimbursement")
    if item.fingerprint in legs:
        return _relabeled(item, categories.CURRENCY_EXCHANGE, known, "exchange")
    return item


def _relabeled(item: Movement, ref: str, known: catalog.Catalog, link: str) -> Movement:
    return replace(
        item,
        category=known.name_of(ref),
        category_key=ref,
        category_kind=known.kind_of(ref),
        corrected=False,
        link=link,
    )


def _with_keyword(item: Movement, known: catalog.Catalog, account_kind: str | None) -> Movement:
    """La palabra clave más larga que aplica decide, si el usuario no corrigió la transacción."""
    if item.corrected:
        return item
    allowed = _kinds_for(account_kind, item.amount < 0)
    text = categories.clean(item.description)
    for hit in known.keyword_hits(text):
        if allowed is None or hit.category.kind in allowed:
            ref = hit.category.ref
            return replace(item, category=ref, original_category=ref)
    return item


def _named(item: Movement, known: catalog.Catalog) -> Movement:
    """Con el nombre actual de la categoría y su referencia estable."""
    ref, original = item.ref, item.original_ref
    return replace(
        item,
        category=known.name_of(ref),
        category_key=ref,
        original_category=known.name_of(original),
        original_key=original,
        category_kind=known.kind_of(ref),
    )


def _with_detected(item: Movement, category: str | None) -> Movement:
    """Lo detectado (transferencia o reversión) es la categoría por defecto; una corrección
    la reemplaza."""
    if category is None:
        return item
    chosen = item.category if item.corrected else category
    return replace(item, category=chosen, original_category=category)


def _with_reversal(
    item: Movement, category: str | None, fixes: corrections.Corrections
) -> Movement:
    """Una reversión emparejada toma la categoría final de su débito.

    Solo la corrección de esa transacción le gana: las reversiones comparten clave de comercio
    ("DEV LBTR"), así que una regla de comercio (o una de la clave anterior) no cuenta.
    """
    if category is None:
        return item
    own = fixes.transaction_category(item.fingerprint)
    return replace(
        item, category=own or category, corrected=own is not None, original_category=category
    )


def _is_payment(row: sqlite3.Row) -> bool:
    return row["direction"] == CREDIT and categories.is_payment(row["description"])


def _is_promotion(row: sqlite3.Row) -> bool:
    return row["direction"] == CREDIT and categories.is_promotion(row["description"])


def _movement(
    row: sqlite3.Row, learned: dict[str, str], fixes: corrections.Corrections, occurrence: int
) -> Movement:
    day = date.fromisoformat(row["transacted_on"])
    mark = corrections.fingerprint(
        row["account"],
        day,
        row["description"],
        row["amount_cents"],
        row["direction"],
        row["currency"],
        occurrence,
    )
    legacy = categories.merchant_key(row["description"])
    if row["kind"] == "credit_card":
        merchant, chosen = legacy, fixes.category_for(mark, legacy)
    else:
        merchant = categories.bank_merchant_key(row["description"])
        previous = categories.previous_bank_key(row["description"])
        chosen = fixes.category_for(mark, merchant, _bank_kinds(row), (previous, legacy))
    amount = Decimal(row["amount_cents"]) / 100
    if row["kind"] != "credit_card":
        original = categories.categorize_bank(row["description"], row["direction"])
    elif _is_payment(row):
        original = categories.CARD_PAYMENT
    elif _is_promotion(row):
        original = categories.OTHER_INCOME
    else:
        original = categories.categorize(row["description"], row["mcc"], learned)
    return Movement(
        day=day,
        merchant=merchant,
        description=row["description"],
        category=chosen or original,
        amount=-amount if row["direction"] == CREDIT else amount,
        currency=row["currency"],
        institution=row["institution"],
        fingerprint=mark,
        one_off=fixes.is_one_off(mark),
        note=fixes.note_for(mark),
        corrected=chosen is not None,
        account=row["account"],
        original_category=original,
    )


def _bank_kinds(row: sqlite3.Row) -> tuple[categories.Kind, ...] | None:
    """Tipos que una regla de comercio puede dar a un movimiento bancario; en tarjetas, todos.

    La misma contraparte manda y recibe ("LBTR JUAN PEREZ"), y una clave anterior era solo
    el canal ("PAGO DE", "MB A"): sin este límite, una regla pensada para un depósito
    cambiaría también los débitos.
    """
    return _kinds_for(row["kind"], row["direction"] == CREDIT)


def _kinds_for(account_kind: str | None, credit: bool) -> tuple[categories.Kind, ...] | None:
    if account_kind in (None, "credit_card"):
        return None
    if credit:
        return ("ingreso", "transferencia")
    return ("gasto", "transferencia")


def _active_cards(conn: sqlite3.Connection) -> list[tuple[date, date]]:
    """Primer y último corte de cada tarjeta que sigue recibiendo estados."""
    cuts = [
        (date.fromisoformat(first), date.fromisoformat(last))
        for first, last in conn.execute(_CUTS_BY_CARD)
    ]
    if not cuts:
        return []
    newest = max(last for _, last in cuts)
    return [(first, last) for first, last in cuts if newest - last <= _ACTIVE_WINDOW]


def complete_through(conn: sqlite3.Connection) -> date | None:
    """Último día con datos de todas las tarjetas activas (el corte más antiguo entre ellas)."""
    cards = _active_cards(conn)
    return min(last for _, last in cards) if cards else None


def first_full_month(conn: sqlite3.Connection) -> str | None:
    """Primer mes cubierto entero por todas las tarjetas activas.

    El primer estado de una tarjeta trae solo el final del mes anterior a su corte;
    el mes del corte ya queda completo con el estado siguiente.
    """
    cards = _active_cards(conn)
    return max(first for first, _ in cards).strftime("%Y-%m") if cards else None


def last_full_month(through: date) -> str:
    """Último mes cubierto entero hasta `through`."""
    if (through + timedelta(days=1)).month != through.month:
        return through.strftime("%Y-%m")
    return (through.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def months_back(last: str, count: int) -> tuple[str, ...]:
    year, month = (int(part) for part in last.split("-"))
    found: list[str] = []
    for _ in range(count):
        found.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return tuple(reversed(found))


def _select(movements: Iterable[Movement], currency: str, months: Sequence[str]) -> list[Movement]:
    wanted = set(months)
    return [m for m in movements if m.currency == currency and m.month in wanted]


def monthly_totals(
    movements: Iterable[Movement], currency: str, months: Sequence[str]
) -> dict[str, Decimal]:
    totals = dict.fromkeys(months, Decimal(0))
    for item in _select(movements, currency, months):
        totals[item.month] += item.amount
    return totals


def by_category(
    movements: Iterable[Movement], currency: str, months: Sequence[str]
) -> list[tuple[str, Decimal]]:
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    for item in _select(movements, currency, months):
        totals[item.category] += item.amount
    return sorted(((name, total) for name, total in totals.items() if total), key=_by_amount)


def monthly_by_category(
    movements: Iterable[Movement], currency: str, months: Sequence[str]
) -> dict[str, dict[str, Decimal]]:
    """Gasto de cada categoría en cada mes; los meses sin gasto quedan en cero."""
    table: dict[str, dict[str, Decimal]] = {}
    for item in _select(movements, currency, months):
        row = table.setdefault(item.category, dict.fromkeys(months, Decimal(0)))
        row[item.month] += item.amount
    return table


def top_merchants(
    movements: Iterable[Movement], currency: str, months: Sequence[str], limit: int
) -> list[MerchantTotal]:
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    purchases: Counter[str] = Counter()
    for item in _select(movements, currency, months):
        totals[item.merchant] += item.amount
        if item.amount > 0:
            purchases[item.merchant] += 1
    ranked = sorted(totals.items(), key=_by_amount)[:limit]
    return [MerchantTotal(name, total, purchases[name]) for name, total in ranked]


def compare_month(
    movements: Sequence[Movement], currency: str, month: str, baseline: Sequence[str]
) -> list[CategoryChange]:
    """Gasto del mes por categoría frente al promedio mensual de `baseline`.

    Los gastos únicos cuentan en el mes, pero no en el promedio.
    """
    current = dict(by_category(movements, currency, (month,)))
    before = dict(by_category(regular(movements), currency, baseline))
    periods = Decimal(len(baseline) or 1)
    changes = [
        CategoryChange(name, current.get(name, Decimal(0)), before.get(name, Decimal(0)) / periods)
        for name in current.keys() | before.keys()
    ]
    return sorted(changes, key=lambda c: (-(c.current - c.average), c.category))


def regular(movements: Iterable[Movement]) -> list[Movement]:
    """Movimientos sin los gastos únicos: la base de cualquier promedio."""
    return [m for m in movements if not m.one_off]


def _by_amount(item: tuple[str, Decimal]) -> tuple[Decimal, str]:
    return (-item[1], item[0])
