"""Development and e2e test server with made-up data.

Usage: `uv run python -m tests.e2e_server --port 8502`. Creates a temporary SQLite database
(removed on exit), fills it with the synthetic statements and serves the API and the built UI.
It never touches the real data directory.
"""

from __future__ import annotations

import argparse
import tempfile
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import uvicorn

from michelito import cli, db
from michelito.analysis import (
    cash_box_store,
    corrections,
    ledger_store,
    links,
    providers,
    rates,
    recurring_marks,
    spending,
)
from michelito.parsers.common import Section, Statement, Transaction
from michelito.web.app import create_app
from tests import e2e_live
from tests.ledger_helpers import pay, share
from tests.test_spending import seed

# Made-up rates (RD$ per US$) for the seed months and the extra statements.
DEMO_RATES = {
    "2025-12": Decimal("63.1000"),
    "2026-01": Decimal("63.4000"),
    "2026-02": Decimal("63.7000"),
}
# Synthetic Spanish merchant descriptions below are data (upper case, like bank text).
# Transactions with something pending (see `_link_pending`).
PENDING_GIFT = "TIENDA REGALOS FICTICIA"
PENDING_GAVE = "TRANSFERENCIA A CAMBISTA FICTICIO"
PENDING_GOT = "DEPOSITO PRIMO FICTICIO"
PENDING_GOT_NOTE = "Cambio con Pedro"  # spanish-data
# Shared groups already closed (see `_link_closed`): one settled and one written off.
SETTLED_EXPENSE = "TIENDA FICTICIA DE ROPA"
WRITTEN_OFF_EXPENSE = "LIBRERIA INVENTADA SANTO DOMINGO"
# "New group" picker: a big dinner (suggested, at the top) and a small tax (only under "show more").
SUGGESTED_DINNER = "ASADOR FICTICIO CUMPLEANOS"
SMALL_TAX = "IMPUESTO DGII FICTICIO"
# Investments (see `_savings_dollars` and `_link_investments`): with Pedro, for the tests to mark
# (a RD$ 300,000 contribution, a RD$ 100,000 one that gets proposed, a small transfer that does
# not, a return and a mixed return); and the loan to Ana, already closed.
INVEST_SENT = "MB a 0000000066 PEDRO INVERSOR FICTICIO"
INVEST_BACK = "TRANSF DE PEDRO INVERSOR FICTICIO"
LOAN_SENT = "MB a 0000000077 ANA PRESTAMO FICTICIA"
LOAN_BACK = "TRANSF DE ANA PRESTAMO FICTICIA"
# Cash box (see `_cash_box`): an opening balance of US$ 200 (about RD$ 12,620 at the December
# rate). The tests store January's "RETIRO CAJERO SANTO DOMINGO", record an outflow and link
# "DEPOSITO CLIENTE FICTICIO"; at the end they undo it.
CASH_BOX_OPENING = Decimal("200.00")
# The test server's "today": shortly after the newest data point, so the "new group" picker
# (expenses from the last 120 days) has options and ages do not depend on the clock.
DEMO_TODAY = date(2026, 2, 20)
# Household recurring charges (see `_household_card` and `_household_checking`): made-up
# providers added to the real list only in this server (`use_demo_providers`). The phone company
# shows up under four names, January in two payments plus a separate top-up; the water utility
# has no payments of its own (the tests merge the water charge into it).
# spanish-data: begin (synthetic provider names)
DEMO_PROVIDERS = (
    providers.make_provider("telfic", "Telefónica Ficticia", r"TELFIC"),
    providers.make_provider("acueducto-ficticio", "Acueducto Ficticio", r"ACUEDUCTO FICTICIO"),
)
PHONE_PROVIDER = "Telefónica Ficticia"
WATER_PROVIDER = "Acueducto Ficticio"
# spanish-data: end
WATER = "AGUA FICTICIA"  # the merchant key (two words) of "AGUA FICTICIA PAGO"
RENT = "ALQUILER FICTICIO"
HOME_LOAN = "AUT PAGO 0000000088"
# A one-off charge the rule does not detect: the tests mark it as recurring (yearly).
HOME_INSURANCE = "SEGURO HOGAR FICTICIO"
HOME_INSURANCE_KEY = "SEGURO HOGAR"
# Budget and reserves (only with the household flag): a made-up yearly tax in January, already
# marked as yearly recurring (see `_mark_annual_tax`), which yields the "create reserve?" hint.
ANNUAL_TAX = "MARBETE FICTICIO"
# Income from crypto sold over P2P (see `_crypto_checking`, only with the household flag): three
# credits from different third parties that land in the "other income" category (the tests move
# them to "Cripto" in a batch) and a deposit that is not crypto.
CRYPTO_TAG = "P2P"
CRYPTO_CREDITS = (
    ("2026-01-08", f"MB DESDE 0000000123 COMPRADOR {CRYPTO_TAG} FICTICIO", "12000.00"),
    ("2026-01-16", f"TRANSFERENCIA RECIBIDA COMPRADORA {CRYPTO_TAG} FICTICIA", "8500.00"),
    ("2026-01-27", f"LBTR EMPRESA FICTICIA {CRYPTO_TAG}", "20000.00"),
)


def _purchase(
    day: str,
    description: str,
    amount: str,
    currency: str = "DOP",
    mcc: str | None = None,
    direction: str = "debit",
) -> Transaction:
    posted = date.fromisoformat(day)
    return Transaction(
        transacted_on=posted,
        posted_on=posted,
        description=description,
        amount=Decimal(amount),
        direction=direction,
        currency=currency,
        reference=None,
        mcc=mcc,
        raw_line=f"{day} {description} {amount}",
    )


def _payment(day: str, amount: str) -> Transaction:
    return _purchase(day, "SU PAGO GRACIAS", amount, direction="credit")


def _extra_card() -> Statement:
    """Made-up card with a February 10 cut-off: leaves February as a partial month."""
    purchases = (
        _purchase("2026-01-20", "RESTAURANTE INVENTADO SANTO DOMINGO", "1850.00"),
        _purchase("2026-01-28", "GASOLINERA FICTICIA SANTIAGO", "2400.00"),
        _purchase("2026-02-03", "SUPERMERCADO FICTICIO SANTO DOMINGO", "3120.75"),
        _purchase("2026-02-07", "CINE INVENTADO SANTO DOMINGO", "640.00"),
        # No MCC and no rule (stays in "other"): the TALLER keyword moves it in the tests.
        _purchase("2026-02-04", "TALLER FICTICIO MECANICA", "1500.00"),
        # Large unusual purchase (new category and merchant): shows up as a possible one-off.
        _purchase("2026-02-06", "AGENCIA FICTICIA VIAJES PUNTA CANA", "45000.00", mcc="4722"),
        # Dinner for three: the tests mark it shared and link the TOKE DE from the 4th.
        _purchase("2026-02-02", "RESTAURANTE COMPARTIDO FICTICIO", "3000.00", mcc="5812"),
        _purchase("2026-02-09", SUGGESTED_DINNER, "5200.00", mcc="5812"),
        _purchase("2026-02-09", SMALL_TAX, "3.00"),
        # Gift paid for someone else (Luis): shows up in Pending as owed to you.
        _purchase("2025-12-20", PENDING_GIFT, "4000.00", mcc="5947"),
    )
    # Made-up recurring charges: the streaming price goes up in February.
    streaming = tuple(
        _purchase(day, "STREAMING FICTICIO", amount, "USD", mcc="4899")
        for day, amount in (
            ("2025-12-05", "9.99"),
            ("2026-01-05", "9.99"),
            ("2026-02-05", "11.99"),
        )
    )
    gym = tuple(
        _purchase(day, "GIMNASIO FICTICIO", "2500.00", mcc="9999")
        for day in ("2025-12-08", "2026-01-08", "2026-02-08")
    )
    return Statement(
        parser="demo",
        institution="demo",
        kind="credit_card",
        product="VISA DEMO",
        identifier="4242",
        period_end=date(2026, 2, 10),
        due_date=date(2026, 3, 5),
        sections=(
            _section("DOP", purchases + gym, "500.00", Decimal("80000.00")),
            _section("USD", streaming, "25.00"),
        ),
    )


def _section(
    currency: str,
    transactions: tuple[Transaction, ...],
    minimum_payment: str,
    credit_limit: Decimal | None = None,
) -> Section:
    total = sum((t.amount for t in transactions), Decimal(0))
    return Section(
        currency=currency,
        previous_balance=Decimal(0),
        closing_balance=total,
        minimum_payment=Decimal(minimum_payment),
        credit_limit=credit_limit,
        printed_debits=total,
        printed_credits=Decimal(0),
        transactions=transactions,
    )


def _interest_card() -> tuple[Statement, ...]:
    """Made-up card with three cut-offs: November's was paid in full, December's was not
    (RD$ 6,150 remain and the January statement charges interest) and January's is due on
    February 22, after the demo's newest data point.

    The November cut-off only carries a balance, without transactions, so it adds no month. The
    last cut-off (Jan 28) leaves January incomplete, so December stays the last complete month.
    """
    cuts = (
        (date(2025, 11, 28), date(2025, 12, 23), Decimal("6000.00"), (), "300.00"),
        (
            date(2025, 12, 28),
            date(2026, 1, 22),
            Decimal("6000.00"),
            (
                _payment("2025-12-12", "6000.00"),
                _purchase("2025-12-06", "FERRETERIA INVENTADA SANTIAGO", "9800.00"),
                _purchase("2025-12-18", "TIENDA FICTICIA DE ROPA", "4350.00"),
            ),
            "710.00",
        ),
        (
            date(2026, 1, 28),
            date(2026, 2, 22),
            Decimal("14150.00"),
            (
                _payment("2026-01-12", "8000.00"),
                _purchase("2026-01-09", "LIBRERIA INVENTADA SANTO DOMINGO", "1200.00"),
                _purchase("2026-01-28", "INTERESES FINANCIAMIENTO", "287.40"),
            ),
            "380.00",
        ),
    )
    return tuple(
        Statement(
            parser="demo",
            institution="ficticio",
            kind="credit_card",
            product="MASTERCARD FICTICIA",
            identifier="5151",
            period_end=cut,
            due_date=due,
            sections=(_carried_section(previous, rows, minimum),),
        )
        for cut, due, previous, rows, minimum in cuts
    )


def _carried_section(
    previous: Decimal, transactions: tuple[Transaction, ...], minimum_payment: str
) -> Section:
    """RD$ section with a previous balance; the printed totals match the rows."""
    debits = sum((t.amount for t in transactions if t.direction == "debit"), Decimal(0))
    credits = sum((t.amount for t in transactions if t.direction == "credit"), Decimal(0))
    return Section(
        currency="DOP",
        previous_balance=previous,
        closing_balance=previous + debits - credits,
        minimum_payment=Decimal(minimum_payment),
        credit_limit=Decimal("50000.00"),
        printed_debits=debits,
        printed_credits=credits,
        transactions=transactions,
    )


def _checking_account() -> Statement:
    """Made-up checking account: payroll and a deposit (income), an ATM withdrawal and a loan
    payment ("AUT PAGO", expenses), a transfer to another person ("MB a", third-party transfer:
    not an expense, but it reduces what you have left) and the January 12 payment to the
    MASTERCARD FICTICIA (a transfer: same amount and card-payment text). Month coverage only
    looks at the cards, so this does not change which month is complete.
    """
    rows = (
        _purchase(
            "2025-12-15", "DEPOSITO NOMINA EMPRESA INVENTADA", "85000.00", direction="credit"
        ),
        _purchase("2026-01-11", "PAGO TARJETA DE CREDITO FICTICIA", "8000.00"),
        _purchase(
            "2026-01-15", "DEPOSITO NOMINA EMPRESA INVENTADA", "85000.00", direction="credit"
        ),
        _purchase("2026-01-18", "RETIRO CAJERO SANTO DOMINGO", "5000.00"),
        _purchase("2026-01-20", "MB a 0000000001 PERSONA INVENTADA", "3000.00"),
        _purchase("2026-01-25", "AUT PAGO 0000000009 PRESTAMO FICTICIO", "2000.00"),
        _purchase("2026-01-22", "DEPOSITO CLIENTE FICTICIO", "12000.00", direction="credit"),
    )
    debits = sum((t.amount for t in rows if t.direction == "debit"), Decimal(0))
    credits = sum((t.amount for t in rows if t.direction == "credit"), Decimal(0))
    opening = Decimal("20000.00")
    return Statement(
        parser="demo",
        institution="ficticio",
        kind="checking",
        product="Cuenta corriente",  # spanish-data
        identifier="777-0",
        period_end=date(2026, 1, 31),
        due_date=None,
        sections=(
            Section(
                currency="DOP",
                previous_balance=opening,
                closing_balance=opening + credits - debits,
                minimum_payment=None,
                credit_limit=None,
                printed_debits=debits,
                printed_credits=credits,
                transactions=rows,
            ),
        ),
    )


def _checking_february() -> Statement:
    """February of the made-up checking account: two small TOKE DE credits (refunds of the
    shared dinner), a transfer from Carola (refund of a group of two expenses), a RD$ 63,700
    deposit and, in the dollar section, a US$ 1,000 transfer to a person: at the February rate
    (63.70) they look like a currency exchange. Another US$ 61.67 transfer completes that
    exchange at the agreed rate of 60 (the leg added later)."""
    january = _checking_account().sections[0]
    dop_rows = (
        _purchase("2026-02-04", "TOKE DE PERSONA FICTICIA", "1000.00", direction="credit"),
        _purchase("2026-02-06", "TOKE DE AMIGA INVENTADA", "500.00", direction="credit"),
        # Pays two VISA DEMO expenses at once (supermarket and cinema: RD$ 3,760.75) that the
        # shared-group tests join with Carola as the other person.
        _purchase("2026-02-09", "TRANSF DE CAROLA FICTICIA", "3760.75", direction="credit"),
        _purchase("2026-02-12", "DEPOSITO CAMBIO FICTICIO", "63700.00", direction="credit"),
    )
    dollars = (
        _purchase("2026-02-13", "TRANSFERENCIA A PERSONA FICTICIA", "1000.00", "USD"),
        _purchase("2026-02-14", "TRANSFERENCIA SALDO PERSONA FICTICIA", "61.67", "USD"),
    )
    return Statement(
        parser="demo",
        institution="ficticio",
        kind="checking",
        product="Cuenta corriente",  # spanish-data
        identifier="777-0",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 15),  # cut-off mid-month: February is still open
        due_date=None,
        sections=(
            _bank_section("DOP", january.closing_balance or Decimal(0), dop_rows),
            _bank_section("USD", Decimal("5000.00"), dollars),
        ),
    )


def _bank_section(currency: str, opening: Decimal, rows: tuple[Transaction, ...]) -> Section:
    debits = sum((t.amount for t in rows if t.direction == "debit"), Decimal(0))
    credits = sum((t.amount for t in rows if t.direction == "credit"), Decimal(0))
    return Section(
        currency=currency,
        previous_balance=opening,
        closing_balance=opening + credits - debits,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=debits,
        printed_credits=credits,
        transactions=rows,
    )


def _savings_dollars() -> Statement:
    """Made-up savings account with two December currency exchanges (see `_link_pending`):
    one where you gave RD$ first and got too few US$ back, and one where you received RD$ and
    have not yet returned all the US$. Cut-off matches the checking account (February 15) so it
    does not change up to when each month's income is known."""
    dop_rows = (
        _purchase("2025-12-03", PENDING_GAVE, "31550.00"),
        _purchase("2025-12-10", PENDING_GOT, "18930.00", direction="credit"),
        _purchase("2025-12-02", INVEST_SENT, "300000.00"),
        _purchase("2025-12-05", LOAN_SENT, "50000.00"),
        _purchase("2025-12-15", INVEST_SENT, "100000.00"),
        _purchase("2025-12-18", INVEST_SENT, "1500.00"),
        _purchase("2025-12-22", INVEST_BACK, "9000.00", direction="credit"),
        _purchase("2025-12-26", LOAN_BACK, "52000.00", direction="credit"),
        _purchase("2025-12-29", INVEST_BACK, "60000.00", direction="credit"),
    )
    dollars = (
        _purchase("2025-12-04", "DEPOSITO CAMBISTA FICTICIO", "400.00", "USD", direction="credit"),
        _purchase("2025-12-11", "ENVIO A PRIMO FICTICIO", "100.00", "USD"),
    )
    return Statement(
        parser="demo",
        institution="ficticio",
        kind="savings",
        product="Cuenta de ahorro",  # spanish-data
        identifier="888-1",
        period_start=date(2025, 12, 1),
        period_end=date(2026, 2, 15),
        due_date=None,
        sections=(
            _bank_section("DOP", Decimal("600000.00"), dop_rows),
            _bank_section("USD", Decimal("2000.00"), dollars),
        ),
    )


def use_demo_providers() -> None:
    """Add the made-up providers to the list (idempotent; only in this server)."""
    known = {p.key for p in providers.PROVIDERS}
    providers.PROVIDERS = (
        *providers.PROVIDERS,
        *(p for p in DEMO_PROVIDERS if p.key not in known),
    )


def _household_card() -> Statement:
    """Made-up household card (same cut-off as the VISA DEMO): the phone company under four
    names (two payments in January), a top-up and a purchase in its store, water, rent and a
    one-off yearly insurance."""
    rows = (
        _purchase("2025-12-05", "TELFIC PAGO", "1500.00", mcc="4814"),
        _purchase("2026-01-06", "TELFIC IBANKING", "900.00", mcc="4814"),
        _purchase("2026-01-20", "TELFIC P", "600.00", mcc="4814"),
        _purchase("2026-02-04", "TELFIC WB", "1500.00", mcc="4814"),
        _purchase("2026-01-10", "TELFIC RECARGA 8095550000", "300.00", mcc="4814"),
        # A phone bought in one of the provider's stores: not the bill.
        _purchase("2026-01-18", "TELFIC AGORA MALL", "7500.00", mcc="4814"),
        _purchase("2025-12-09", f"{WATER} PAGO", "450.00", mcc="4900"),
        _purchase("2026-01-09", f"{WATER} PAGO", "450.00", mcc="4900"),
        _purchase("2026-02-09", f"{WATER} PAGO", "450.00", mcc="4900"),
        _purchase("2025-12-01", RENT, "25000.00", mcc="6513"),
        _purchase("2026-01-01", RENT, "25000.00", mcc="6513"),
        _purchase("2026-02-01", RENT, "25000.00", mcc="6513"),
        _purchase("2026-01-15", HOME_INSURANCE, "4800.00", mcc="6300"),
        _purchase("2026-01-20", ANNUAL_TAX, "3400.00", mcc="9311"),
    )
    return Statement(
        parser="demo",
        institution="hogar",  # spanish-data
        kind="credit_card",
        product="VISA HOGAR",
        identifier="6262",
        period_end=date(2026, 2, 10),
        due_date=date(2026, 3, 5),
        sections=(_section("DOP", rows, "900.00", Decimal("150000.00")),),
    )


def _household_checking() -> Statement:
    """Made-up household account: a monthly loan installment and an extra payment in
    January. Same cut-off as the other bank accounts (February 15)."""
    rows = (
        _purchase("2025-12-10", f"{HOME_LOAN} REF 1", "12000.00"),
        _purchase("2026-01-10", f"{HOME_LOAN} REF 2", "12000.00"),
        _purchase("2026-01-28", f"{HOME_LOAN} REF 3", "30000.00"),
        _purchase("2026-02-10", f"{HOME_LOAN} REF 4", "12000.00"),
    )
    return Statement(
        parser="demo",
        institution="hogar",  # spanish-data
        kind="checking",
        product="Cuenta de la casa",  # spanish-data
        identifier="999-2",
        period_start=date(2025, 12, 1),
        period_end=date(2026, 2, 15),
        due_date=None,
        sections=(_bank_section("DOP", Decimal("200000.00"), rows),),
    )


def _crypto_checking() -> Statement:
    """Made-up account receiving the fiat from selling crypto (see `CRYPTO_CREDITS`) and a gift.
    Same cut-off as the other bank accounts (February 15)."""
    rows = (
        *(_purchase(day, text, amount, direction="credit") for day, text, amount in CRYPTO_CREDITS),
        _purchase("2026-01-20", "DEPOSITO REGALO FICTICIO", "1000.00", direction="credit"),
    )
    return Statement(
        parser="demo",
        institution="hogar",  # spanish-data
        kind="checking",
        product="Cuenta P2P",  # spanish-data
        identifier="555-3",
        period_start=date(2025, 12, 1),
        period_end=date(2026, 2, 15),
        due_date=None,
        sections=(_bank_section("DOP", Decimal("1000.00"), rows),),
    )


def _link_pending(conn) -> None:
    """The Pending links: the gift paid for someone else (Luis) and the two exchanges from
    `_savings_dollars` at the agreed rate of 63.10: you are owed US$ 100 (you gave RD$ 31,550 =
    US$ 500 and got US$ 400 back) and you owe US$ 200 (you got RD$ 18,930 = US$ 300 and returned
    US$ 100)."""
    by_text = {m.description: m for m in spending.load_all(conn, ())}
    with conn:
        gift = by_text[PENDING_GIFT]
        share(conn, gift.fingerprint, gift.amount, for_other=True, with_whom="Luis")
        for dop_leg, usd_leg in (
            (PENDING_GAVE, "DEPOSITO CAMBISTA FICTICIO"),
            (PENDING_GOT, "ENVIO A PRIMO FICTICIO"),
        ):
            legs = (by_text[dop_leg].fingerprint, by_text[usd_leg].fingerprint)
            links.create_exchange(conn, legs, Decimal("63.10"))
        corrections.set_note(conn, by_text[PENDING_GOT].fingerprint, PENDING_GOT_NOTE)


def _link_closed(conn) -> None:
    """Two Shared groups already closed: the clothes (RD$ 4,350, two people, named after
    Marta) settled with RD$ 2,175 in cash from Marta on January 10; and the bookstore
    (RD$ 1,200, two people, with Rosa) written off."""
    by_text = {m.description: m for m in spending.load_all(conn, ())}
    with conn:
        clothes = by_text[SETTLED_EXPENSE]
        settled = share(
            conn,
            clothes.fingerprint,
            clothes.amount,
            people=2,
            with_whom="Marta",
            name="Ropa de Marta",  # spanish-data
        )
        pay(conn, settled, amount=Decimal("2175.00"), day=date(2026, 1, 10))
        books = by_text[WRITTEN_OFF_EXPENSE]
        lost = share(conn, books.fingerprint, books.amount, people=2, with_whom="Rosa")
        ledger_store.set_written_off(conn, lost, None, True)


def _link_investments(conn) -> None:
    """The loan to Ana, already closed: RD$ 50,000 on December 5 and RD$ 52,000 back on the
    26th (RD$ 50,000 of principal and RD$ 2,000 of return)."""
    by_text = {m.description: m for m in spending.load_all(conn, ())}
    with conn:
        loan = links.create_investment(
            conn,
            by_text[LOAN_SENT].fingerprint,
            with_whom="Ana",
            name="Préstamo a Ana",  # spanish-data
        )
        back = by_text[LOAN_BACK]
        links.add_investment_member(
            conn, loan, back.fingerprint, "mixed", -back.amount, Decimal("50000.00")
        )


def _mark_annual_tax(conn) -> None:
    """The made-up vehicle tax becomes yearly recurring (confirmed by hand), so the budget
    screen suggests a reserve for it."""
    tax = next(m for m in spending.load_all(conn, ()) if m.description == ANNUAL_TAX)
    with conn:
        recurring_marks.set_status(conn, tax.merchant, "DOP", "confirmed", DEMO_TODAY)
        recurring_marks.set_cadence(conn, tax.merchant, "DOP", "yearly", DEMO_TODAY)


def _cash_box(conn) -> None:
    """The cash box opening balance (so the cash box account shows up in the filter)."""
    with conn:
        cash_box_store.add_entry(conn, "initial", date(2025, 12, 1), CASH_BOX_OPENING, "USD")


def _store_extra(conn, household: bool = False) -> None:
    statements = (
        _extra_card(),
        *_interest_card(),
        _checking_account(),
        _checking_february(),
        _savings_dollars(),
        *((_household_card(), _household_checking(), _crypto_checking()) if household else ()),
    )
    with conn:
        for index, statement in enumerate(statements):
            message = f"m-demo-{index}"
            # spanish-data: begin (synthetic mail source)
            conn.execute(
                "INSERT INTO gmail_messages VALUES (?, 'banco', 'x', 'y', 'z', 1, 'z')",
                (message,),
            )
            document_id = conn.execute(
                "INSERT INTO documents (message_id, source, filename, path, sha256, size, "
                "received_at, status) VALUES (?, 'banco', 'f.pdf', 'p', ?, 1, 'z', 'parsed')",
                (message, f"d{index}"),
            ).lastrowid
            # spanish-data: end
            db.store_statement(conn, document_id, statement)


def build_demo_db(path: Path, household: bool = False, live: bool = False) -> None:
    """Fill `path` with the synthetic statements, extra statements and made-up rates. With
    `household`, also the household accounts (household recurring charges), which shift the
    totals: they run in their own test server (household flag) so the other tests' figures stay
    the same. With `live`, also made-up provisional purchases (`tests.e2e_live`), likewise in
    their own server."""
    with closing(db.connect(path)) as conn:
        seed(conn)
        _store_extra(conn, household)
        with conn:
            rates.store_bcrd(conn, DEMO_RATES)
        _link_pending(conn)
        _link_closed(conn)
        _link_investments(conn)
        _cash_box(conn)
        if household:
            _mark_annual_tax(conn)
        if live:
            e2e_live.add_provisionals(conn)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument(
        "--household",
        action="store_true",
        help="include the household accounts and their providers",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="add made-up provisional purchases and the live-sync test routes",
    )
    args = parser.parse_args()
    if args.household:
        use_demo_providers()
    with tempfile.TemporaryDirectory(prefix="michelito-e2e-") as directory:
        path = Path(directory) / "michelito.db"
        build_demo_db(path, household=args.household, live=args.live)
        app = create_app(path, cli.STATIC_DIR, today=lambda: DEMO_TODAY)
        if args.live:
            e2e_live.register(app, path, lambda target: build_demo_db(target, live=True))
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
