"""Generador de la base de la demo: 24 meses inventados que terminan en el mes actual.

`build_template(carpeta, hoy)` arma la plantilla que copia cada visitante (`finanzas.demo.copias`):
`finanzas.db` y `titulares.txt`. Los movimientos salen de `movimientos.plan` (semilla fija, fechas
relativas a `hoy`); aquí se cortan en estados de cuenta (la tarjeta el día 10, los bancos a fin de
mes y el mes en curso hasta ayer) y cada uno **pasa por la validación y la ingesta reales**
(`importer.register_generated` + `ingest.ingest_statement`): uno que no cuadre no entra y la
generación falla. Encima van, con las mismas funciones que usa la API, los vínculos que haría la
persona (cenas compartidas y reembolsos, una inversión, la caja fuerte, las tasas del dólar y la
palabra clave de Cripto). El presupuesto y las reservas quedan **sin activar**.

Nada aquí es de nadie: nombres «FICTICIO»/«INVENTADO», cuentas y montos inventados.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from finanzas import db, importer, ingest
from finanzas.analysis import cash_box_store, catalog, categories, links, providers, rates, spending
from finanzas.demo import movimientos as mv
from finanzas.parsers.common import Section, Statement, Transaction

PARSER = "demo"
DATABASE = "finanzas.db"
HOLDERS = "titulares.txt"
HOLDERS_TEXT = f"# Titular inventado de las cuentas de la demo\n{mv.PERSONA}\n"
PAYMENT_DELAY = timedelta(days=23)  # del corte de la tarjeta a su pago
# Proveedores inventados de la demo: se suman a la lista solo en el proceso de la demo.
PROVIDERS = (
    providers.make_provider("telfic", "Telefónica Ficticia", mv.PHONE),
    providers.make_provider("electrica-ficticia", "Eléctrica Ficticia", mv.POWER),
)
_OPENING = {
    (mv.CHECKING[3], "DOP"): Decimal("60000.00"),
    (mv.SAVINGS[3], "DOP"): Decimal("250000.00"),
    (mv.SAVINGS[3], "USD"): Decimal("3500.00"),
}


class GenerationError(RuntimeError):
    """Un estado generado no cuadró: la plantilla no se arma."""


@dataclass(frozen=True)
class Template:
    database: Path
    holders: Path
    seconds: float


def use_demo_providers() -> None:
    """Suma los proveedores inventados a la lista (idempotente; solo en el proceso de la demo)."""
    known = {p.key for p in providers.PROVIDERS}
    providers.PROVIDERS = (*providers.PROVIDERS, *(p for p in PROVIDERS if p.key not in known))


def build_template(directory: Path, today: date) -> Template:
    """Genera la plantilla en `directory` (la reemplaza entera, sin dejarla a medias)."""
    started = time.perf_counter()
    directory.parent.mkdir(parents=True, exist_ok=True)
    _clean_leftovers(directory)
    work = Path(tempfile.mkdtemp(prefix=f".{directory.name}-nueva-", dir=directory.parent))
    try:
        fill(work / DATABASE, today)
        (work / HOLDERS).write_text(HOLDERS_TEXT, encoding="utf-8")
        old = directory.with_name(f".{directory.name}-vieja")
        if directory.exists():
            os.replace(directory, old)
        os.replace(work, directory)
        shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    seconds = time.perf_counter() - started
    return Template(directory / DATABASE, directory / HOLDERS, seconds)


def _clean_leftovers(directory: Path) -> None:
    """Borra los restos de una generación cortada (`.plantilla-nueva-*`, `.plantilla-vieja`)."""
    for leftover in directory.parent.glob(f".{directory.name}-*"):
        shutil.rmtree(leftover, ignore_errors=True)


def fill(path: Path, today: date) -> None:
    """Llena la base en `path` con los estados generados y los vínculos de la persona."""
    found = statements(today)
    with closing(db.connect(path)) as conn:
        for number, statement in enumerate(found):
            stored = store(conn, statement, f"demo-{number:03d}", today)
            if stored.status != "parsed":
                raise GenerationError(f"estado {number}: {stored.status}: {stored.detail}")
        with conn:
            rates.store_bcrd(conn, dollar_rates(today))
            crypto = catalog.resolve_ref(conn, categories.CRYPTO)
            catalog.set_keywords(conn, crypto, ["P2P"])
            rent = catalog.resolve_ref(conn, categories.HOUSING)
            catalog.set_keywords(conn, rent, ["ALQUILER APARTAMENTO"])
        _link(conn, today)


@dataclass(frozen=True)
class Stored:
    status: str  # el del documento: parsed, invalid o duplicate
    detail: str | None
    transactions: int


def store(conn, statement: Statement, name: str, today: date) -> Stored:  # noqa: ANN001
    """Registra el estado generado como documento y lo valida y guarda por el camino de siempre
    (`ingest.ingest_statement`): solo entra si cuadra."""
    content = json.dumps(_fingerprint(statement), sort_keys=True).encode()
    now = datetime.combine(today, datetime.min.time(), UTC)
    registered = importer.register_generated(conn, f"{name}.estado", content, now)
    if not registered.new:
        return Stored("duplicate", "ese estado ya se importó", 0)
    status = ingest.ingest_statement(conn, registered.document_id, PARSER, statement)
    detail = conn.execute(
        "SELECT detail FROM documents WHERE id = ?", (registered.document_id,)
    ).fetchone()[0]
    count = sum(len(section.transactions) for section in statement.sections)
    return Stored(status, detail, count if status == "parsed" else 0)


def _fingerprint(statement: Statement) -> list[str]:
    return [
        statement.institution,
        statement.kind,
        statement.identifier,
        statement.period_end.isoformat(),
        *(t.raw_line for section in statement.sections for t in section.transactions),
    ]


def dollar_rates(today: date) -> dict[str, Decimal]:
    """Tasas inventadas (RD$ por US$) de cada mes de la ventana y de los dos siguientes."""
    months = [*mv.window(today), mv.month_start(today, 1), mv.month_start(today, 2)]
    return {
        month.strftime("%Y-%m"): Decimal("58.40") + Decimal("0.17") * index
        for index, month in enumerate(months)
    }


def statements(today: date) -> list[Statement]:
    """Los estados de la ventana: los de la tarjeta (con sus pagos) y luego los de los bancos."""
    plan = mv.plan(today)
    cards, payments = card_statements(plan.of(mv.CARD, "DOP"), plan.of(mv.CARD, "USD"), today)
    for payment in payments:
        account = mv.CHECKING if payment.currency == "DOP" else mv.SAVINGS
        plan.add(account, payment)
    banks = [
        *bank_statements(mv.CHECKING, plan, ("DOP",), today),
        *bank_statements(mv.SAVINGS, plan, ("DOP", "USD"), today),
    ]
    return [*cards, *banks]


def card_cuts(today: date) -> list[date]:
    """Los cortes (día 10) de la ventana que ya pasaron."""
    cuts = [mv.on(month, mv.CUT_DAY) for month in mv.window(today)]
    return [cut for cut in cuts if cut < today]


def card_statements(
    dop: Sequence[mv.Row], usd: Sequence[mv.Row], today: date
) -> tuple[list[Statement], list[mv.Row]]:
    """Un estado por corte; cada corte paga completo el saldo del anterior (un crédito en la
    tarjeta y su débito en el banco, que vuelven como `payments`)."""
    found: list[Statement] = []
    payments: list[mv.Row] = []
    balances = {"DOP": Decimal(0), "USD": Decimal(0)}
    previous = mv.month_start(mv.window(today)[0]) - timedelta(days=1)
    for cut in card_cuts(today):
        sections = []
        for currency, rows in (("DOP", dop), ("USD", usd)):
            chosen = [r for r in rows if previous < r.day <= cut]
            owed = balances[currency]
            paid_on = previous + PAYMENT_DELAY
            if owed > 0 and previous < paid_on <= cut:
                chosen.append(mv.Row(paid_on, mv.CARD_PAYMENT, owed, "credit", currency))
                bank = mv.Row(
                    paid_on, f"{mv.CARD_PAYMENT_FROM_BANK} {currency}", owed, "debit", currency
                )
                payments.append(bank)
            built = section(currency, owed, chosen, liability=True, minimum=True)
            balances[currency] = built.closing_balance or Decimal(0)
            sections.append(built)
        found.append(statement(mv.CARD, None, cut, cut + timedelta(days=25), sections))
        previous = cut
    return found, payments


def bank_statements(
    account: tuple[str, str, str, str], plan: mv.Plan, currencies: Sequence[str], today: date
) -> list[Statement]:
    """Un estado por mes (el actual, hasta ayer); el saldo de cada uno abre el siguiente."""
    found: list[Statement] = []
    balances = {c: _OPENING[(account[3], c)] for c in currencies}
    for month in mv.window(today):
        end = min(mv.month_start(month, 1) - timedelta(days=1), today - timedelta(days=1))
        if end < month:
            continue
        sections = []
        for currency in currencies:
            rows = [r for r in plan.of(account, currency) if month <= r.day <= end]
            built = section(currency, balances[currency], rows, liability=False)
            balances[currency] = built.closing_balance or Decimal(0)
            sections.append(built)
        found.append(statement(account, month, end, None, sections))
    return found


def statement(
    account: tuple[str, str, str, str],
    start: date | None,
    end: date,
    due: date | None,
    sections: Sequence[Section],
) -> Statement:
    institution, kind, product, identifier = account
    return Statement(
        parser=PARSER,
        institution=institution,
        kind=kind,
        product=product,
        identifier=identifier,
        period_start=start,
        period_end=end,
        due_date=due,
        sections=tuple(sections),
    )


def section(
    currency: str,
    previous: Decimal,
    rows: Sequence[mv.Row],
    *,
    liability: bool,
    minimum: bool = False,
) -> Section:
    """Una sección con sus totales impresos: los que valida `validate_section`."""
    ordered = sorted(rows, key=lambda r: r.day)
    transactions = tuple(_transaction(r) for r in ordered)
    debits = sum((r.amount for r in ordered if r.direction == "debit"), Decimal(0))
    credits = sum((r.amount for r in ordered if r.direction == "credit"), Decimal(0))
    closing = previous + (debits - credits if liability else credits - debits)
    return Section(
        currency=currency,
        previous_balance=previous,
        closing_balance=closing,
        minimum_payment=(closing * Decimal("0.05")).quantize(Decimal("0.01")) if minimum else None,
        credit_limit=Decimal("150000.00" if currency == "DOP" else "3000.00")
        if liability
        else None,
        printed_debits=debits,
        printed_credits=credits,
        transactions=transactions,
    )


def _transaction(row: mv.Row) -> Transaction:
    return Transaction(
        transacted_on=row.day,
        posted_on=row.day,
        description=row.description,
        amount=row.amount,
        direction=row.direction,
        currency=row.currency,
        reference=None,
        mcc=row.mcc,
        raw_line=f"{row.day.isoformat()} {row.description} {row.amount} {row.direction}",
    )


def _link(conn, today: date) -> None:  # noqa: ANN001
    """Lo que la persona ya vinculó: cenas compartidas (la última aún sin devolver), la
    inversión con sus rendimientos y la caja fuerte (saldo inicial y un retiro guardado)."""
    movements = spending.load_all(conn, ())
    dinners = [m for m in movements if m.description == mv.SHARED_DINNER]
    refunds = [m for m in movements if m.description == mv.SHARED_REFUND]
    with conn:
        for number, dinner in enumerate(dinners):
            group = links.set_shared(
                conn, dinner.fingerprint, dinner.amount, people=2, with_whom="Amiga Ficticia"
            )
            if number < len(dinners) - 1 and number < len(refunds):
                links.add_reimbursement(conn, group, refunds[number].fingerprint)
        sent = next((m for m in movements if m.description == mv.INVEST_SENT), None)
        if sent is not None:
            investment = links.create_investment(
                conn, sent.fingerprint, with_whom="Inversor Ficticio", name="Préstamo FICTICIO"
            )
            for back in (m for m in movements if m.description == mv.INVEST_BACK):
                links.add_investment_member(
                    conn, investment, back.fingerprint, "return", abs(back.amount)
                )
        start = mv.window(today)[0]
        cash_box_store.add_entry(conn, "initial", start, Decimal("300.00"), "USD", today=today)
        stored = [m for m in movements if m.description == mv.ATM and m.amount >= 10000]
        for atm in stored:
            cash_box_store.store(conn, atm.fingerprint)
