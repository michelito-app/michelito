"""The demo's made-up movements, month by month (pure logic, fixed seed).

A made-up person (`PERSONA`) with three made-up accounts: a card with RD$ and US$ sections, a
checking account and a savings one (RD$ and US$). Each rule of `_month` adds one month's worth:
supermarket and restaurant purchases, fuel, pharmacy, gym, utilities from a provider with four
names (one month without a payment and the next one double), top-ups, subscriptions in dollars
(one of them goes up), each March's trip, Christmas, shared dinners, payroll, loan installments
with extra payments, rent in dollars, crypto income through P2P, an investment with returns,
ATM withdrawals, one-offs and, in the last complete month, something to review.

Every merchant, person and account name is made up ("FICTICIO", "INVENTADO"). The names are
Spanish data, like a Dominican bank statement: the uppercase ones inline, the others in the
`spanish-data` block below.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

PERSONA = "MARIA FICTICIA INVENTADA"
SEED = 20240101
MONTHS = 24
CUT_DAY = 10  # the card's closing day

# Accounts: (institution, kind, product, identifier). Made-up identifiers.
# spanish-data: begin
CARD = ("banco-ficticio", "credit_card", "VISA FICTICIA", "4242")
CHECKING = ("banco-ficticio", "checking", "Cuenta corriente FICTICIA", "777-0")
SAVINGS = ("banco-inventado", "savings", "Ahorro INVENTADO", "888-1")
# spanish-data: end

CARD_PAYMENT = "SU PAGO GRACIAS"
CARD_PAYMENT_FROM_BANK = "PAGO TARJETA CREDITO FICTICIA"
SHARED_DINNER = "RESTAURANTE COMPARTIDO FICTICIO"
SHARED_REFUND = "TOKE DE AMIGA FICTICIA"
# The beach trip with two friends (last complete month): a dinner the person paid, what they sent
# to one friend and what the other one sent back (not linked yet: "To review" proposes it).
TRIP_DINNER = "RESTAURANTE PLAYA FICTICIO"
TRIP_SENT = "TRANSFERENCIA A LUIS FICTICIO"
TRIP_BACK = "TOKE DE ROSA INVENTADA"
TRIP_DINNER_AMOUNT = Decimal("4500.00")
TRIP_SENT_AMOUNT = Decimal("6000.00")
TRIP_BACK_AMOUNT = Decimal("1500.00")
INVEST_SENT = "MB a 0000000066 INVERSOR FICTICIO"
INVEST_BACK = "TRANSF DE INVERSOR FICTICIO"
ATM = "RETIRO CAJERO FICTICIO SANTO DOMINGO"
CRYPTO = "MB DESDE 0000000123 COMPRADOR P2P FICTICIO"
RENT = "ALQUILER APARTAMENTO FICTICIO"
PHONE = "TELFIC"  # made-up phone provider (see `michelito.demo.generate.PROVIDERS`)
POWER = "ELECTRICA FICTICIA"
_PHONE_NAMES = ("PAGO", "IBANKING", "WB", "P")


@dataclass(frozen=True)
class Row:
    """A movement: day, description, amount (positive), direction, currency and MCC."""

    day: date
    description: str
    amount: Decimal
    direction: str = "debit"
    currency: str = "DOP"
    mcc: str | None = None


@dataclass
class Plan:
    """The movements per account and currency (built in order and not changed afterwards)."""

    rows: dict[tuple[str, str], list[Row]] = field(default_factory=dict)

    def add(self, account: tuple[str, str, str, str], row: Row) -> None:
        self.rows.setdefault((account[3], row.currency), []).append(row)

    def of(self, account: tuple[str, str, str, str], currency: str) -> list[Row]:
        return sorted(self.rows.get((account[3], currency), []), key=lambda r: r.day)


def month_start(day: date, shift: int = 0) -> date:
    """The first day of `day`'s month, shifted `shift` months."""
    index = day.year * 12 + day.month - 1 + shift
    return date(index // 12, index % 12 + 1, 1)


def on(month: date, day: int) -> date:
    """Day `day` of the month (or the last one, if the month is shorter)."""
    last = (month_start(month, 1) - timedelta(days=1)).day
    return month.replace(day=min(day, last))


def window(today: date) -> list[date]:
    """The `MONTHS` months (first day) that end in `today`'s month."""
    return [month_start(today, shift) for shift in range(-MONTHS + 1, 1)]


def last_complete_month(today: date) -> date:
    """The last month the card fully covers: its next month's closing date already passed."""
    return month_start(today, -1 if today.day > CUT_DAY else -2)


def _money(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(rng.randrange(low * 100, high * 100)) / 100


def plan(today: date) -> Plan:
    """Every movement of the window, up to yesterday (today's have not arrived yet)."""
    rng = random.Random(SEED)
    found = Plan()
    months = window(today)
    for index, month in enumerate(months):
        _month(found, rng, index, month, last_complete_month(today))
    found.rows = {key: [row for row in rows if row.day < today] for key, rows in found.rows.items()}
    return found


def one_month(month: date, index: int, seed: int, review: bool = False) -> Plan:
    """The movements of a single month (the sample statement): `index` is its place in the
    series (it decides the rules that apply every so many months) and `review`, whether it
    brings something to review."""
    found = Plan()
    _month(found, random.Random(seed), index, month, month if review else None)
    return found


def _month(plan_: Plan, rng: random.Random, index: int, month: date, review: date | None) -> None:
    _groceries(plan_, rng, month)
    _going_out(plan_, rng, index, month)
    _services(plan_, rng, index, month)
    _subscriptions(plan_, index, month)
    _income(plan_, rng, index, month)
    _bank(plan_, rng, index, month)
    if month.month == 3:
        _trip(plan_, rng, month)
    if month.month == 12:
        _christmas(plan_, rng, month)
    _yearly(plan_, month)
    _one_offs(plan_, index, month)
    if month == review:
        _to_review(plan_, month)
        _beach_trip(plan_, month)


def _beach_trip(plan_: Plan, month: date) -> None:
    """The movements of the shared beach trip (see `generate`: the group and its payments)."""
    plan_.add(CARD, Row(on(month, 11), TRIP_DINNER, TRIP_DINNER_AMOUNT, mcc="5812"))
    plan_.add(CHECKING, Row(on(month, 20), TRIP_SENT, TRIP_SENT_AMOUNT))
    plan_.add(CHECKING, Row(on(month, 22), TRIP_BACK, TRIP_BACK_AMOUNT, direction="credit"))


def _groceries(plan_: Plan, rng: random.Random, month: date) -> None:
    for day in (3, 10, 17, 24):
        plan_.add(
            CARD,
            Row(
                on(month, day),
                "SUPERMERCADO FICTICIO SANTO DOMINGO",
                _money(rng, 2800, 6200),
                mcc="5411",
            ),
        )
    plan_.add(CARD, Row(on(month, 14), "COLMADO INVENTADO", _money(rng, 600, 1500), mcc="5411"))
    plan_.add(CARD, Row(on(month, 19), "FARMACIA INVENTADA", _money(rng, 800, 2500), mcc="5912"))
    for day in (6, 21):
        plan_.add(
            CARD, Row(on(month, day), "GASOLINERA FICTICIA", _money(rng, 2000, 3200), mcc="5541")
        )
    plan_.add(CARD, Row(on(month, 8), "GIMNASIO FICTICIO", Decimal("2500.00"), mcc="7997"))


def _going_out(plan_: Plan, rng: random.Random, index: int, month: date) -> None:
    places = ("RESTAURANTE INVENTADO", "PIZZERIA FICTICIA", "CAFE FICTICIO")
    for day, place in zip((5, 12, 26), places, strict=True):
        plan_.add(CARD, Row(on(month, day), place, _money(rng, 900, 3500), mcc="5812"))
    if index % 3 == 1:  # dinner for two; the friend pays back her share (see `generate`)
        plan_.add(CARD, Row(on(month, 15), SHARED_DINNER, Decimal("4800.00"), mcc="5812"))
        if index < MONTHS - 3:  # the last one is still pending
            plan_.add(
                CHECKING, Row(on(month, 18), SHARED_REFUND, Decimal("2400.00"), direction="credit")
            )


def _services(plan_: Plan, rng: random.Random, index: int, month: date) -> None:
    """Phone service with four names by channel: one month without a payment, the next double."""
    skipped = index % 7 == 4
    if not skipped:
        name = f"{PHONE} {_PHONE_NAMES[index % len(_PHONE_NAMES)]}"
        plan_.add(CARD, Row(on(month, 7), name, _money(rng, 2050, 2300), mcc="4814"))
    if index % 7 == 5:
        plan_.add(CARD, Row(on(month, 9), f"{PHONE} PAGO", _money(rng, 2050, 2300), mcc="4814"))
    if index % 2 == 0:
        plan_.add(CARD, Row(on(month, 20), f"{PHONE} RECARGA", Decimal("500.00"), mcc="4814"))
    summer = month.month in (6, 7, 8, 9)
    power = _money(rng, 4800, 6200) if summer else _money(rng, 3000, 4200)
    plan_.add(CARD, Row(on(month, 16), f"{POWER} PAGO", power, mcc="4900"))


def _subscriptions(plan_: Plan, index: int, month: date) -> None:
    streaming = Decimal("11.99") if index >= 16 else Decimal("9.99")  # its price goes up
    for day, name, amount in (
        (5, "STREAMING FICTICIO", streaming),
        (12, "MUSICA INVENTADA", Decimal("5.99")),
        (20, "NUBE FICTICIA", Decimal("2.99")),
    ):
        plan_.add(CARD, Row(on(month, day), name, amount, currency="USD", mcc="4899"))


def _income(plan_: Plan, rng: random.Random, index: int, month: date) -> None:
    salary = Decimal("104000.00") if index >= 12 else Decimal("98500.00")
    plan_.add(
        CHECKING,
        Row(on(month, 25), "DEPOSITO NOMINA EMPRESA INVENTADA", salary, direction="credit"),
    )
    plan_.add(
        SAVINGS,
        Row(
            on(month, 28),
            "TRANSFERENCIA RECIBIDA CLIENTE EXTERIOR FICTICIO",
            Decimal("950.00"),
            direction="credit",
            currency="USD",
        ),
    )
    if index % 4 == 2:
        plan_.add(CHECKING, Row(on(month, 9), CRYPTO, _money(rng, 12000, 25000), "credit"))


def _bank(plan_: Plan, rng: random.Random, index: int, month: date) -> None:
    plan_.add(CHECKING, Row(on(month, 2), ATM, Decimal("10000.00" if index == 10 else "5000.00")))
    plan_.add(
        CHECKING, Row(on(month, 12), "AUT PAGO 0000000009 PRESTAMO FICTICIO", Decimal("12750.00"))
    )
    if index in (6, 13, 19):  # extra payments on the loan
        plan_.add(
            CHECKING,
            Row(on(month, 27), "AUT PAGO 0000000009 PRESTAMO FICTICIO", Decimal("25000.00")),
        )
    own = Decimal("10000.00")
    plan_.add(CHECKING, Row(on(month, 26), f"MB a 0000000055 {PERSONA}", own))
    plan_.add(SAVINGS, Row(on(month, 26), f"TRANSF DE {PERSONA}", own, direction="credit"))
    plan_.add(SAVINGS, Row(on(month, 1), RENT, Decimal("700.00"), currency="USD"))
    if index == 2:
        plan_.add(SAVINGS, Row(on(month, 4), INVEST_SENT, Decimal("150000.00")))
    elif index > 2:
        plan_.add(SAVINGS, Row(on(month, 5), INVEST_BACK, Decimal("2250.00"), direction="credit"))


# March's trip and Christmas change merchants every year (they are not recurring: they are
# seasonal expenses, the source of the peak reserve suggestions).
_TRIPS = (
    (
        (1, "AEROLINEA FICTICIA", 380, 460, "4511"),
        (18, "HOTEL INVENTADO ORLANDO", 650, 800, "7011"),
        (18, "RENTA AUTOS FICTICIA", 170, 210, "7512"),
        (19, "PARQUE TEMATICO FICTICIO", 220, 260, "7996"),
    ),
    (
        (2, "VUELOS INVENTADOS", 400, 480, "4511"),
        (17, "RESORT FICTICIO CANCUN", 700, 850, "7011"),
        (17, "AUTOS INVENTADOS RENTA", 160, 200, "7512"),
        (19, "TOUR FICTICIO CANCUN", 180, 240, "4722"),
    ),
)
_CHRISTMAS = (
    (
        (13, "JUGUETERIA FICTICIA", 9000, 16000, "5945"),
        (18, "TIENDA REGALOS INVENTADA", 6000, 12000, "5947"),
        (22, "TIENDA FICTICIA DE ROPA", 5000, 9000, "5651"),
    ),
    (
        (12, "JUGUETES INVENTADOS", 9000, 16000, "5945"),
        (17, "REGALOS FICTICIOS", 6000, 12000, "5947"),
        (21, "BOUTIQUE INVENTADA", 5000, 9000, "5651"),
    ),
)


def _trip(plan_: Plan, rng: random.Random, month: date) -> None:
    for day, name, low, high, mcc in _TRIPS[month.year % 2]:
        plan_.add(CARD, Row(on(month, day), name, _money(rng, low, high), currency="USD", mcc=mcc))


def _christmas(plan_: Plan, rng: random.Random, month: date) -> None:
    for day, name, low, high, mcc in _CHRISTMAS[month.year % 2]:
        plan_.add(CARD, Row(on(month, day), name, _money(rng, low, high), mcc=mcc))
    dinner = Row(on(month, 23), "SUPERMERCADO FICTICIO SANTO DOMINGO", _money(rng, 9000, 14000))
    plan_.add(CARD, Row(dinner.day, dinner.description, dinner.amount, mcc="5411"))


def _yearly(plan_: Plan, month: date) -> None:
    if month.month == 9:
        plan_.add(CARD, Row(on(month, 11), "MARBETE FICTICIO", Decimal("3400.00"), mcc="9311"))
    if month.month == 5:
        plan_.add(CARD, Row(on(month, 15), "SEGURO AUTO FICTICIO", Decimal("28000.00"), mcc="6300"))


def _one_offs(plan_: Plan, index: int, month: date) -> None:
    for at, name, amount, mcc in (
        (7, "TIENDA ELECTRODOMESTICOS FICTICIA", "38500.00", "5722"),
        (15, "CLINICA DENTAL INVENTADA", "16500.00", "8021"),
        (20, "TALLER FICTICIO MECANICA", "9800.00", "7538"),
    ):
        if index == at:
            plan_.add(CARD, Row(on(month, 22), name, Decimal(amount), mcc=mcc))


def _to_review(plan_: Plan, month: date) -> None:
    """To review: a repeated charge, a large transfer to another person and a new income."""
    for _ in range(2):
        plan_.add(CARD, Row(on(month, 27), "PIZZERIA FICTICIA", Decimal("1650.00"), mcc="5812"))
    plan_.add(CHECKING, Row(on(month, 20), "MB a 0000000044 PERSONA FICTICIA", Decimal("48000.00")))
    plan_.add(
        CHECKING,
        Row(
            on(month, 21), "DEPOSITO BONO EMPRESA FICTICIA", Decimal("65000.00"), direction="credit"
        ),
    )
