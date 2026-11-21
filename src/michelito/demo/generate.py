"""Generator of the demo database: 24 made-up months ending in the current month.

`build_template(directory, today)` builds the template every visitor copies
(`michelito.demo.copies`): `michelito.db` and `holders.txt`. The movements come from
`movements.plan` (fixed seed, dates relative to `today`); here they are cut into statements (the
card on day 10, the banks at the end of the month and the current month up to yesterday) and
each one **goes through the real validation and ingestion** (`importer.register_generated` +
`ingest.ingest_statement`): one that does not balance does not enter and the generation fails.
On top go, with the same functions the API uses, the links the person would make (shared
groups with people, expenses paid by others and reconciled and unlinked payments, an
investment, the cash box, the dollar rates and the Crypto keyword). The budget and the reserves
are left **not activated**.

Nothing here belongs to anyone: "FICTICIO"/"INVENTADO" names, made-up accounts and amounts. The
names the person types (providers, people, a loan) are Spanish data in `spanish-data` blocks.
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

from michelito import db, importer, ingest
from michelito.analysis import (
    cash_activation,
    cash_box_store,
    cash_schedule_store,
    catalog,
    categories,
    ledger,
    ledger_store,
    links,
    live_store,
    providers,
    rates,
    spending,
)
from michelito.demo import movements as mv
from michelito.i18n import t
from michelito.parsers.common import Section, Statement, Transaction

PARSER = "demo"
DATABASE = "michelito.db"
HOLDERS = "holders.txt"
HOLDERS_TEXT = f"# Made-up holder of the demo accounts\n{mv.PERSONA}\n"
PAYMENT_DELAY = timedelta(days=23)  # from the card's closing date to its payment
# The demo's made-up providers: added to the list only in the demo process.
# spanish-data: begin
PROVIDERS = (
    providers.make_provider("telfic", "Telefónica Ficticia", mv.PHONE),
    providers.make_provider("electrica-ficticia", "Eléctrica Ficticia", mv.POWER),
)
# Names the person gave to their links.
_FRIEND = "Amiga Ficticia"
_FRIEND_BANK = "AMIGA FICTICIA"
_DINNERS = "Cenas con Amiga"
_TRIP = "Viaje a la playa"
_TRIP_PEOPLE = (("Luis Ficticio", "LUIS FICTICIO"), ("Rosa Inventada", "ROSA INVENTADA"))
_HOTEL = "Hotel en la playa"
_CAR = "Alquiler de carro"
_INVESTOR = "Inversor Ficticio"
_LOAN = "Préstamo FICTICIO"
# Card purchases from this week that only bank alerts know about (live sync): (days before
# today, merchant, RD$ amount). The statement that confirms them has not closed yet.
PROVISIONALS = (
    (1, "SUPERMERCADO FICTICIO", Decimal("2875.40")),
    (2, "FARMACIA INVENTADA", Decimal("640.00")),
    (4, "GASOLINERA FICTICIA", Decimal("1500.00")),
)
# Cash written by hand (schema 23): (days before today, concept, RD$ amount), and a weekly cash
# payment that started three weeks ago.
CASH_EXPENSES = (
    (8, "Colmado Ficticio", Decimal("850.00")),
    (3, "Propina", Decimal("200.00")),
)
CASH_WEEKLY = ("Limpieza", Decimal("3000.00"))
# spanish-data: end
_OPENING = {
    (mv.CHECKING[3], "DOP"): Decimal("60000.00"),
    (mv.SAVINGS[3], "DOP"): Decimal("250000.00"),
    (mv.SAVINGS[3], "USD"): Decimal("3500.00"),
}


class GenerationError(RuntimeError):
    """A generated statement did not balance: the template is not built."""


@dataclass(frozen=True)
class Template:
    database: Path
    holders: Path
    seconds: float


def use_demo_providers() -> None:
    """Add the made-up providers to the list (idempotent; only in the demo process)."""
    known = {p.key for p in providers.PROVIDERS}
    providers.PROVIDERS = (*providers.PROVIDERS, *(p for p in PROVIDERS if p.key not in known))


def build_template(directory: Path, today: date) -> Template:
    """Generate the template in `directory` (replacing it whole, never leaving it half done)."""
    started = time.perf_counter()
    directory.parent.mkdir(parents=True, exist_ok=True)
    _clean_leftovers(directory)
    work = Path(tempfile.mkdtemp(prefix=f".{directory.name}-new-", dir=directory.parent))
    try:
        fill(work / DATABASE, today)
        (work / HOLDERS).write_text(HOLDERS_TEXT, encoding="utf-8")
        old = directory.with_name(f".{directory.name}-old")
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
    """Removes what an interrupted generation left (`.template-new-*`, `.template-old`)."""
    for leftover in directory.parent.glob(f".{directory.name}-*"):
        shutil.rmtree(leftover, ignore_errors=True)


def fill(path: Path, today: date) -> None:
    """Fill the database at `path` with the generated statements and the person's links."""
    found = statements(today)
    with closing(db.connect(path)) as conn:
        for number, statement in enumerate(found):
            stored = store(conn, statement, f"demo-{number:03d}", today)
            if stored.status != "parsed":
                raise GenerationError(f"statement {number}: {stored.status}: {stored.detail}")
        with conn:
            rates.store_bcrd(conn, dollar_rates(today))
            crypto = catalog.resolve_ref(conn, categories.CRYPTO)
            catalog.set_keywords(conn, crypto, ["P2P"])
            rent = catalog.resolve_ref(conn, categories.HOUSING)
            catalog.set_keywords(conn, rent, ["ALQUILER APARTAMENTO"])
        _link(conn, today)
        _provisionals(conn, today)


def _provisionals(conn, today: date) -> None:  # noqa: ANN001
    """A few purchases of the current month still without a statement (from bank alerts):
    after the card's last closing date, so no statement covers them yet."""
    cuts = card_cuts(today)
    last_cut = cuts[-1] if cuts else date.min
    account = db.account_key(
        Statement(PARSER, mv.CARD[0], mv.CARD[1], mv.CARD[2], mv.CARD[3], today, None, ())
    )
    now = datetime.combine(today, datetime.min.time(), UTC).isoformat()
    with conn:
        for back, merchant, amount in PROVISIONALS:
            day = today - timedelta(days=back)
            if day <= last_cut or day.month != today.month:
                continue
            made = live_store.Made(
                message_id=f"demo-alert-{back}",
                account=account,
                last4=mv.CARD[3],
                day=day,
                amount_cents=int(amount * 100),
                currency="DOP",
                merchant=merchant,
            )
            live_store.add_made_up(conn, made, now)


@dataclass(frozen=True)
class Stored:
    status: str  # the document's: parsed, invalid or duplicate
    detail: str | None
    transactions: int


def store(conn, statement: Statement, name: str, today: date) -> Stored:  # noqa: ANN001
    """Register the generated statement as a document and validate and store it the usual way
    (`ingest.ingest_statement`): it enters only if it balances."""
    content = json.dumps(_fingerprint(statement), sort_keys=True).encode()
    now = datetime.combine(today, datetime.min.time(), UTC)
    registered = importer.register_generated(conn, f"{name}.statement", content, now)
    if not registered.new:
        return Stored("duplicate", t("demo.sample_duplicate"), 0)
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
        *(item.raw_line for section in statement.sections for item in section.transactions),
    ]


def dollar_rates(today: date) -> dict[str, Decimal]:
    """Made-up rates (RD$ per US$) for each month of the window and the two after it."""
    months = [*mv.window(today), mv.month_start(today, 1), mv.month_start(today, 2)]
    return {
        month.strftime("%Y-%m"): Decimal("58.40") + Decimal("0.17") * index
        for index, month in enumerate(months)
    }


def statements(today: date) -> list[Statement]:
    """The window's statements: the card's (with their payments) and then the banks'."""
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
    """The window's card closing dates (day 10) that already passed."""
    cuts = [mv.on(month, mv.CUT_DAY) for month in mv.window(today)]
    return [cut for cut in cuts if cut < today]


def card_statements(
    dop: Sequence[mv.Row], usd: Sequence[mv.Row], today: date
) -> tuple[list[Statement], list[mv.Row]]:
    """One statement per closing date; each one pays the previous balance in full (a credit on
    the card and its debit at the bank, returned as `payments`)."""
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
    """One statement per month (the current one, up to yesterday); each balance opens the next."""
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
    """A section with its printed totals: the ones `validate_section` checks."""
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


def _dinners(conn, movements: Sequence[spending.Movement]) -> None:  # noqa: ANN001
    """Dinners for two with a friend, each paid back by a transfer (reconciled); the last one is
    still pending."""
    dinners = [m for m in movements if m.description == mv.SHARED_DINNER]
    refunds = [m for m in movements if m.description == mv.SHARED_REFUND]
    if not dinners:
        return
    me = ledger_store.ensure_me(conn)
    friend = ledger_store.contact_for(conn, _FRIEND, _FRIEND_BANK)
    group = ledger_store.create_group(conn, _DINNERS, [friend])
    for dinner in dinners:
        ledger_store.add_entry(
            conn,
            group,
            paid_by=me,
            amount=dinner.amount,
            currency=dinner.currency,
            day=dinner.day,
            description=dinner.merchant or dinner.description,
            splits=ledger.equal_split(dinner.amount, [me, friend], me),
            mode="equal",
            fingerprint=dinner.fingerprint,
        )
    for refund in refunds[: len(dinners) - 1]:
        ledger_store.add_payment(
            conn,
            group,
            from_contact=friend,
            to_contact=me,
            amount=-refund.amount,
            currency=refund.currency,
            day=refund.day,
            fingerprint=refund.fingerprint,
        )


def _beach_trip(conn, movements: Sequence[spending.Movement]) -> None:  # noqa: ANN001
    """A trip with two friends: the hotel paid by one, the car by the other, a dinner the person
    paid (linked), a payment the person made (reconciled with the bank) and another one written
    down but not linked yet. The second friend's transfer is in the bank, unlinked: "To
    review" proposes it."""
    dinner = next((m for m in movements if m.description == mv.TRIP_DINNER), None)
    sent = next((m for m in movements if m.description == mv.TRIP_SENT), None)
    if dinner is None or sent is None:
        return
    me = ledger_store.ensure_me(conn)
    luis, rosa = (ledger_store.contact_for(conn, name, raw) for name, raw in _TRIP_PEOPLE)
    group = ledger_store.create_group(conn, _TRIP, [luis, rosa])
    everyone = [me, luis, rosa]
    for payer, what, amount, days in (
        (luis, _HOTEL, Decimal("18000.00"), 1),
        (rosa, _CAR, Decimal("6000.00"), 2),
    ):
        ledger_store.add_entry(
            conn,
            group,
            paid_by=payer,
            amount=amount,
            currency="DOP",
            day=dinner.day - timedelta(days=days),
            description=what,
            splits=ledger.equal_split(amount, everyone, payer),
            mode="equal",
        )
    ledger_store.add_entry(
        conn,
        group,
        paid_by=me,
        amount=dinner.amount,
        currency=dinner.currency,
        day=dinner.day,
        description=dinner.merchant or dinner.description,
        splits=ledger.equal_split(dinner.amount, everyone, me),
        mode="equal",
        fingerprint=dinner.fingerprint,
    )
    ledger_store.add_payment(
        conn,
        group,
        from_contact=me,
        to_contact=luis,
        amount=sent.amount,
        currency=sent.currency,
        day=sent.day,
        fingerprint=sent.fingerprint,
    )
    ledger_store.add_payment(
        conn,
        group,
        from_contact=me,
        to_contact=rosa,
        amount=Decimal("2000.00"),
        currency="DOP",
        day=sent.day,
    )


def _link(conn, today: date) -> None:  # noqa: ANN001
    """What the person already linked: shared groups (see `_dinners` and `_beach_trip`), the
    investment with its returns and the cash box (opening balance and a withdrawal put away)."""
    movements = spending.load_all(conn, ())
    with conn:
        _dinners(conn, movements)
        _beach_trip(conn, movements)
        sent = next((m for m in movements if m.description == mv.INVEST_SENT), None)
        if sent is not None:
            investment = links.create_investment(
                conn, sent.fingerprint, with_whom=_INVESTOR, name=_LOAN
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
        _cash(conn, today)


def _cash(conn, today: date) -> None:  # noqa: ANN001
    """The cash account: a couple of expenses with their concept, a weekly cash payment whose
    occurrences are paid but the last one (left pending for "To review"), and the account
    activated today (no withdrawal already in the data changes)."""
    for back, concept, amount in CASH_EXPENSES:
        day = today - timedelta(days=back)
        cash_box_store.add_entry(conn, "expense", day, amount, "DOP", today=today, concept=concept)
    concept, amount = CASH_WEEKLY
    draft = cash_schedule_store.ScheduleDraft(
        kind="payment",
        concept=concept,
        amount=amount,
        currency="DOP",
        category_id=None,
        frequency="weekly",
        start=today - timedelta(days=21),
    )
    cash_schedule_store.add(conn, draft, today)
    made = cash_schedule_store.materialize(conn, today)
    for entry_id in made[:-1]:
        cash_schedule_store.answer(conn, entry_id, "confirm", today=today)
    cash_activation.activate(conn, today)
