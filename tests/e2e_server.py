"""Servidor de desarrollo y pruebas e2e con datos inventados.

Uso: `uv run python -m tests.e2e_server --port 8502`. Crea una base SQLite temporal (se borra
al salir), la llena con los estados sintéticos y sirve la API y la interfaz compilada.
Nunca toca el directorio de datos real.
"""

from __future__ import annotations

import argparse
import tempfile
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import uvicorn

from finanzas import cli, db
from finanzas.analysis import (
    cash_box_store,
    corrections,
    links,
    providers,
    rates,
    recurring_marks,
    spending,
)
from finanzas.parsers.common import Section, Statement, Transaction
from finanzas.web.app import create_app
from tests.test_spending import seed

# Tasas inventadas (RD$ por US$) de los meses del seed y de los estados extra.
DEMO_RATES = {
    "2025-12": Decimal("63.1000"),
    "2026-01": Decimal("63.4000"),
    "2026-02": Decimal("63.7000"),
}
# Movimientos con algo pendiente (ver `_link_pending`).
PENDING_GIFT = "TIENDA REGALOS FICTICIA"
PENDING_GAVE = "TRANSFERENCIA A CAMBISTA FICTICIO"
PENDING_GOT = "DEPOSITO PRIMO FICTICIO"
# Grupos compartidos ya cerrados (ver `_link_closed`): uno saldado y uno dado por perdido.
SETTLED_EXPENSE = "TIENDA FICTICIA DE ROPA"
WRITTEN_OFF_EXPENSE = "LIBRERIA INVENTADA SANTO DOMINGO"
# «Nuevo grupo…»: una cena grande (se sugiere, arriba) y un impuesto chico (solo en «Ver más»).
SUGGESTED_DINNER = "ASADOR FICTICIO CUMPLEANOS"
SMALL_TAX = "IMPUESTO DGII FICTICIO"
# Inversiones (ver `_savings_dollars` y `_link_investments`): con Pedro, por marcar en las
# pruebas (un aporte de RD$ 300,000, otro de RD$ 100,000 que se propone, un envío chico que no,
# un rendimiento y un cobro mixto); y el préstamo a Ana, ya cerrado.
INVEST_SENT = "MB a 0000000066 PEDRO INVERSOR FICTICIO"
INVEST_BACK = "TRANSF DE PEDRO INVERSOR FICTICIO"
LOAN_SENT = "MB a 0000000077 ANA PRESTAMO FICTICIA"
LOAN_BACK = "TRANSF DE ANA PRESTAMO FICTICIA"
# Caja fuerte (ver `_cash_box`): un saldo inicial de US$ 200 (≈ RD$ 12,620 a la tasa de
# diciembre). Las pruebas guardan el «RETIRO CAJERO SANTO DOMINGO» de enero, registran una salida
# y vinculan el «DEPOSITO CLIENTE FICTICIO»; al final lo deshacen.
CASH_BOX_OPENING = Decimal("200.00")
# «Hoy» del servidor de pruebas: poco después del dato más nuevo, así «Nuevo grupo…» (gastos de
# los últimos 120 días) tiene opciones y las antigüedades no dependen del reloj.
DEMO_TODAY = date(2026, 2, 20)
# Recurrentes del hogar (ver `_household_card` y `_household_checking`): proveedores inventados
# que se suman a la lista real solo en este servidor (`use_demo_providers`). La telefónica
# llega con cuatro nombres, enero en dos pagos y una recarga aparte; el acueducto no tiene
# pagos propios (las pruebas le unen el agua).
DEMO_PROVIDERS = (
    providers.make_provider("telfic", "Telefónica Ficticia", r"TELFIC"),
    providers.make_provider("acueducto-ficticio", "Acueducto Ficticio", r"ACUEDUCTO FICTICIO"),
)
PHONE_PROVIDER = "Telefónica Ficticia"
WATER_PROVIDER = "Acueducto Ficticio"
WATER = "AGUA FICTICIA"  # la clave del comercio (dos palabras) de «AGUA FICTICIA PAGO»
RENT = "ALQUILER FICTICIO"
HOME_LOAN = "AUT PAGO 0000000088"
# Un cobro suelto que la regla no detecta: las pruebas lo marcan «Es recurrente…» (anual).
HOME_INSURANCE = "SEGURO HOGAR FICTICIO"
HOME_INSURANCE_KEY = "SEGURO HOGAR"
# Presupuesto y reservas (solo en `--hogar`): un impuesto anual inventado de enero, ya marcado
# como recurrente anual (ver `_mark_annual_tax`), del que sale la sugerencia «¿Crear reserva…?».
ANNUAL_TAX = "MARBETE FICTICIO"
# Ingresos de cripto vendida por P2P (ver `_crypto_checking`, solo en `--hogar`): tres créditos de
# terceros distintos que caen en «Otros ingresos» (las pruebas los pasan a «Cripto» en lote) y un
# depósito que no es cripto.
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
    """Tarjeta inventada con corte el 10 de febrero: deja febrero como mes parcial."""
    purchases = (
        _purchase("2026-01-20", "RESTAURANTE INVENTADO SANTO DOMINGO", "1850.00"),
        _purchase("2026-01-28", "GASOLINERA FICTICIA SANTIAGO", "2400.00"),
        _purchase("2026-02-03", "SUPERMERCADO FICTICIO SANTO DOMINGO", "3120.75"),
        _purchase("2026-02-07", "CINE INVENTADO SANTO DOMINGO", "640.00"),
        # Sin MCC ni regla (queda en "Otros"): la palabra clave TALLER la mueve en las pruebas.
        _purchase("2026-02-04", "TALLER FICTICIO MECANICA", "1500.00"),
        # Compra grande y rara (categoría y comercio nuevos): sale como posible gasto único.
        _purchase("2026-02-06", "AGENCIA FICTICIA VIAJES PUNTA CANA", "45000.00", mcc="4722"),
        # Cena entre tres: las pruebas la marcan compartida y enlazan el TOKE DE del 4.
        _purchase("2026-02-02", "RESTAURANTE COMPARTIDO FICTICIO", "3000.00", mcc="5812"),
        _purchase("2026-02-09", SUGGESTED_DINNER, "5200.00", mcc="5812"),
        _purchase("2026-02-09", SMALL_TAX, "3.00"),
        # Regalo pagado por otra persona (Luis): sale en Pendientes como «Te deben».
        _purchase("2025-12-20", PENDING_GIFT, "4000.00", mcc="5947"),
    )
    # Cargos recurrentes inventados: el streaming sube de precio en febrero.
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
    """Tarjeta inventada con tres cortes: el de noviembre se pagó completo, el de diciembre
    no (quedan RD$ 6,150 y el estado de enero cobra intereses) y el de enero vence el 22 de
    febrero, después del dato más nuevo de la demo.

    El corte de noviembre solo arrastra saldo, sin movimientos, para no agregar un mes. El
    último corte (28 ene) deja enero incompleto y diciembre sigue siendo el último mes completo.
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
    """Sección en RD$ con saldo anterior; los totales impresos cuadran con las filas."""
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
    """Cuenta corriente inventada: nómina y un depósito (ingresos), un retiro en cajero y un
    pago de préstamo ("AUT PAGO", gastos), un envío a otra persona ("MB a", transferencia a
    terceros: no es gasto, pero resta de lo que te quedó) y el pago del 12 de enero a la
    MASTERCARD FICTICIA (transferencia: mismo monto y texto de pago de tarjeta). La cobertura
    del mes solo mira las tarjetas: no cambia qué mes está completo.
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
        product="Cuenta corriente",
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
    """Febrero de la cuenta corriente inventada: dos TOKE DE pequeños (reembolsos de la cena
    compartida), una transferencia de Carola (reembolso de un grupo de dos gastos), un
    depósito de RD$ 63,700 y, en la sección en dólares, un envío de US$ 1,000 a
    una persona: a la tasa de febrero (63.70) parecen un cambio de divisas. Otro envío de
    US$ 61.67 completa ese cambio a la tasa acordada de 60 (la pata que se agrega después)."""
    january = _checking_account().sections[0]
    pesos = (
        _purchase("2026-02-04", "TOKE DE PERSONA FICTICIA", "1000.00", direction="credit"),
        _purchase("2026-02-06", "TOKE DE AMIGA INVENTADA", "500.00", direction="credit"),
        # Paga de una vez dos gastos de la VISA DEMO (supermercado y cine: RD$ 3,760.75) que las
        # pruebas de grupos compartidos juntan con «Con quién: Carola».
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
        product="Cuenta corriente",
        identifier="777-0",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 15),  # corta a mitad de mes: febrero sigue en curso
        due_date=None,
        sections=(
            _bank_section("DOP", january.closing_balance or Decimal(0), pesos),
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
    """Cuenta de ahorro inventada con dos cambios de divisas de diciembre (ver `_link_pending`):
    uno en que diste RD$ primero y te devolvieron US$ de menos, y otro en que te depositaron
    RD$ y aún no devuelves todos los US$. Corta con la cuenta corriente (15 de febrero) para no
    cambiar hasta cuándo se conocen los ingresos de cada mes."""
    pesos = (
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
        product="Cuenta de ahorro",
        identifier="888-1",
        period_start=date(2025, 12, 1),
        period_end=date(2026, 2, 15),
        due_date=None,
        sections=(
            _bank_section("DOP", Decimal("600000.00"), pesos),
            _bank_section("USD", Decimal("2000.00"), dollars),
        ),
    )


def use_demo_providers() -> None:
    """Suma los proveedores inventados a la lista (idempotente; solo en este servidor)."""
    known = {p.key for p in providers.PROVIDERS}
    providers.PROVIDERS = (
        *providers.PROVIDERS,
        *(p for p in DEMO_PROVIDERS if p.key not in known),
    )


def _household_card() -> Statement:
    """Tarjeta inventada de la casa (corta con la VISA DEMO): la telefónica con cuatro nombres
    (dos pagos en enero), una recarga y una compra en su tienda, el agua, el alquiler y un seguro
    anual suelto."""
    rows = (
        _purchase("2025-12-05", "TELFIC PAGO", "1500.00", mcc="4814"),
        _purchase("2026-01-06", "TELFIC IBANKING", "900.00", mcc="4814"),
        _purchase("2026-01-20", "TELFIC P", "600.00", mcc="4814"),
        _purchase("2026-02-04", "TELFIC WB", "1500.00", mcc="4814"),
        _purchase("2026-01-10", "TELFIC RECARGA 8095550000", "300.00", mcc="4814"),
        # Un teléfono comprado en una tienda del proveedor: no es la factura.
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
        institution="hogar",
        kind="credit_card",
        product="VISA HOGAR",
        identifier="6262",
        period_end=date(2026, 2, 10),
        due_date=date(2026, 3, 5),
        sections=(_section("DOP", rows, "900.00", Decimal("150000.00")),),
    )


def _household_checking() -> Statement:
    """Cuenta inventada de la casa: la cuota de un préstamo cada mes y un abono extra en
    enero. Corta con las demás cuentas de banco (15 de febrero)."""
    rows = (
        _purchase("2025-12-10", f"{HOME_LOAN} REF 1", "12000.00"),
        _purchase("2026-01-10", f"{HOME_LOAN} REF 2", "12000.00"),
        _purchase("2026-01-28", f"{HOME_LOAN} REF 3", "30000.00"),
        _purchase("2026-02-10", f"{HOME_LOAN} REF 4", "12000.00"),
    )
    return Statement(
        parser="demo",
        institution="hogar",
        kind="checking",
        product="Cuenta de la casa",
        identifier="999-2",
        period_start=date(2025, 12, 1),
        period_end=date(2026, 2, 15),
        due_date=None,
        sections=(_bank_section("DOP", Decimal("200000.00"), rows),),
    )


def _crypto_checking() -> Statement:
    """Cuenta inventada donde llega el fiat de vender cripto (ver `CRYPTO_CREDITS`) y un regalo.
    Corta con las demás cuentas de banco (15 de febrero)."""
    rows = (
        *(_purchase(day, text, amount, direction="credit") for day, text, amount in CRYPTO_CREDITS),
        _purchase("2026-01-20", "DEPOSITO REGALO FICTICIO", "1000.00", direction="credit"),
    )
    return Statement(
        parser="demo",
        institution="hogar",
        kind="checking",
        product="Cuenta P2P",
        identifier="555-3",
        period_start=date(2025, 12, 1),
        period_end=date(2026, 2, 15),
        due_date=None,
        sections=(_bank_section("DOP", Decimal("1000.00"), rows),),
    )


def _link_pending(conn) -> None:
    """Los vínculos de Pendientes: el regalo «Lo pagué por otra persona» (Luis) y los dos
    cambios de `_savings_dollars` a la tasa acordada de 63.10: te deben US$ 100 (diste RD$
    31,550 = US$ 500 y volvieron US$ 400) y debes US$ 200 (te dieron RD$ 18,930 = US$ 300 y
    devolviste US$ 100)."""
    by_text = {m.description: m for m in spending.load_all(conn, ())}
    with conn:
        gift = by_text[PENDING_GIFT]
        links.set_shared(conn, gift.fingerprint, gift.amount, for_other=True, with_whom="Luis")
        for pesos, dollars in (
            (PENDING_GAVE, "DEPOSITO CAMBISTA FICTICIO"),
            (PENDING_GOT, "ENVIO A PRIMO FICTICIO"),
        ):
            legs = (by_text[pesos].fingerprint, by_text[dollars].fingerprint)
            links.create_exchange(conn, legs, Decimal("63.10"))
        corrections.set_note(conn, by_text[PENDING_GOT].fingerprint, "Cambio con Pedro")


def _link_closed(conn) -> None:
    """Dos grupos de Compartidos ya cerrados: la ropa (RD$ 4,350, «Éramos 2», nombre «Ropa de
    Marta») saldada con RD$ 2,175 en efectivo de Marta el 10 de enero; y la librería (RD$ 1,200,
    «Éramos 2», con Rosa) dada por perdida."""
    by_text = {m.description: m for m in spending.load_all(conn, ())}
    with conn:
        clothes = by_text[SETTLED_EXPENSE]
        settled = links.set_shared(conn, clothes.fingerprint, clothes.amount, people=2)
        links.set_group(conn, settled, name="Ropa de Marta", with_whom="Marta")
        links.add_manual(conn, settled, Decimal("2175.00"), date(2026, 1, 10), "DOP", "Marta")
        books = by_text[WRITTEN_OFF_EXPENSE]
        lost = links.set_shared(conn, books.fingerprint, books.amount, people=2, with_whom="Rosa")
        links.set_written_off(conn, lost, True)


def _link_investments(conn) -> None:
    """El préstamo a Ana, ya cerrado: RD$ 50,000 el 5 de diciembre y RD$ 52,000 de vuelta el
    26 (RD$ 50,000 de capital y RD$ 2,000 de rendimiento)."""
    by_text = {m.description: m for m in spending.load_all(conn, ())}
    with conn:
        loan = links.create_investment(
            conn, by_text[LOAN_SENT].fingerprint, with_whom="Ana", name="Préstamo a Ana"
        )
        back = by_text[LOAN_BACK]
        links.add_investment_member(
            conn, loan, back.fingerprint, "mixed", -back.amount, Decimal("50000.00")
        )


def _mark_annual_tax(conn) -> None:
    """El marbete inventado queda como recurrente anual (confirmado a mano), así «Presupuesto»
    sugiere una reserva para él."""
    tax = next(m for m in spending.load_all(conn, ()) if m.description == ANNUAL_TAX)
    with conn:
        recurring_marks.set_status(conn, tax.merchant, "DOP", "confirmed", DEMO_TODAY)
        recurring_marks.set_cadence(conn, tax.merchant, "DOP", "anual", DEMO_TODAY)


def _cash_box(conn) -> None:
    """El saldo inicial de la caja fuerte (la cuenta «Caja fuerte» queda en el filtro)."""
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
            conn.execute(
                "INSERT INTO gmail_messages VALUES (?, 'banco', 'x', 'y', 'z', 1, 'z')", (message,)
            )
            document_id = conn.execute(
                "INSERT INTO documents (message_id, source, filename, path, sha256, size, "
                "received_at, status) VALUES (?, 'banco', 'f.pdf', 'p', ?, 1, 'z', 'parsed')",
                (message, f"d{index}"),
            ).lastrowid
            db.store_statement(conn, document_id, statement)


def build_demo_db(path: Path, household: bool = False) -> None:
    """Llena `path` con los estados sintéticos, un estado extra y tasas inventadas. Con
    `household`, también las cuentas de la casa (recurrentes del hogar), que mueven los totales:
    van en su propio servidor de pruebas (`--hogar`) para no cambiar las cifras de las demás."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument(
        "--hogar", action="store_true", help="con las cuentas de la casa y sus proveedores"
    )
    args = parser.parse_args()
    if args.hogar:
        use_demo_providers()
    with tempfile.TemporaryDirectory(prefix="finanzas-e2e-") as directory:
        path = Path(directory) / "finanzas.db"
        build_demo_db(path, household=args.hogar)
        app = create_app(path, cli.STATIC_DIR, today=lambda: DEMO_TODAY)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
