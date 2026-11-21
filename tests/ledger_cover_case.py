"""The synthetic "one person paid for several, in another currency" case (made-up people and
amounts), as pure ledger objects: a group of three where the user paid two expenses in US$
split among the three, Ana paid the user three times in RD$ (really for herself and Beto) and
Beto paid RD$ 41,000 once. Ana's payments are attributed to her alone, so her US$ claims get
settled at each month's rate and the rest of the last one becomes a RD$ claim the other way:
"owed to you US$ 629.31 · you owe RD$ 40,107.83" while Beto still owes. Covering Beto with
the last payment settles him and leaves Ana an exchange leftover of RD$ 20.78.

The same shape is built through the API by `frontend/e2e/shared.spec.ts` (`coverCase`) on the
e2e server, whose rates are these.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from michelito.analysis.ledger import Contact, Entry, Group, Ledger, Member, Payment, equal_split
from michelito.analysis.rates import Rate

D = Decimal
ME, ANA, BETO = 1, 2, 3
CONTACTS = {
    ME: Contact(ME, "me", is_me=True),
    ANA: Contact(ANA, "Ana Ficticia"),
    BETO: Contact(BETO, "Beto Inventado"),
}
# The e2e server's made-up rates (RD$ per US$).
RATES = {
    "2025-12": Rate(D("63.10"), "2025-12", "bcrd"),
    "2026-01": Rate(D("63.40"), "2026-01", "bcrd"),
    "2026-02": Rate(D("63.70"), "2026-02", "bcrd"),
}
HOTEL, FLIGHTS = D("2400.00"), D("1428.00")  # US$, paid by the user, split among the three
# (payment id, who, RD$, day): Ana three times, Beto once.
PAYMENTS = (
    (1, ANA, D("40000.00"), date(2025, 12, 20)),
    (2, ANA, D("40000.00"), date(2026, 1, 15)),
    (3, BETO, D("41000.00"), date(2026, 1, 20)),
    (4, ANA, D("40820.00"), date(2026, 2, 10)),
)
LAST = 4  # Ana's payment whose excess is still open


def _entry(entry_id: int, amount: Decimal, day: date) -> Entry:
    people = (ME, ANA, BETO)
    return Entry(entry_id, 1, ME, amount, "USD", day, "x", equal_split(amount, people, ME), "equal")


def group(
    *payments: Payment,
    members: tuple[Member, ...] | None = None,
    dismissed: frozenset = frozenset(),
) -> Group:
    return Group(
        1,
        "Viaje de prueba",  # spanish-data
        members or (Member(ME), Member(ANA), Member(BETO)),
        entries=(_entry(1, HOTEL, date(2025, 12, 5)), _entry(2, FLIGHTS, date(2025, 12, 10))),
        payments=payments or base_payments(),
        dismissed=dismissed,
    )


def base_payments() -> tuple[Payment, ...]:
    return tuple(Payment(pid, 1, who, ME, amount, "DOP", day) for pid, who, amount, day in PAYMENTS)


def book(found: Group | None = None) -> Ledger:
    return Ledger(ME, CONTACTS, (found or group(),))


# --- Several payments with an excess (the shape of the owner's real group, made-up figures) ---

# One rate for every month (RD$ per US$): conversions are easy to follow.
SPREAD_RATES = {"2025-09": Rate(D("61.21"), "2025-09", "bcrd")}
# US$ 5,742.15 the user paid, split among the three: US$ 1,914.05 each.
SPREAD_EXPENSES = ((1, D("3828.00"), date(2025, 9, 10)), (2, D("1914.15"), date(2025, 9, 20)))
# Ana pays RD$ 191,500 in three payments (really for herself and Beto); Beto, RD$ 41,000.
SPREAD_PAYMENTS = (
    (11, ANA, D("125000.00"), date(2025, 10, 3)),
    (12, BETO, D("41000.00"), date(2025, 10, 8)),
    (13, ANA, D("25000.00"), date(2025, 10, 15)),
    (14, ANA, D("41500.00"), date(2025, 11, 2)),
)


def spread_group(*, dismissed: frozenset = frozenset()) -> Group:
    """Ana's three payments each attributed to her alone: the first settles her US$ 1,914.05 and
    the rest of it, and the other two whole, become a RD$ claim the other way (≈ RD$ 74,340)
    while Beto still owes ≈ US$ 1,244.22."""
    return Group(
        2,
        "Viaje largo",  # spanish-data
        (Member(ME), Member(ANA), Member(BETO)),
        entries=tuple(_entry(eid, amount, day) for eid, amount, day in SPREAD_EXPENSES),
        payments=tuple(
            Payment(pid, 2, who, ME, amount, "DOP", day)
            for pid, who, amount, day in SPREAD_PAYMENTS
        ),
        dismissed=dismissed,
    )
