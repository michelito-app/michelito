"""Links between transactions: shared groups, currency exchanges, investments, cash boxes.

A single stored model for all of them (tables `links`, `link_members` and `link_manual`):
- A **shared group** (`kind = 'shared'`) has one or more expenses (`role = 'expense'`), each
  with its split (equal `people`, `my_share_cents` or `for_other`: "I paid it for someone
  else", in `link_members`), the credits that reimburse them (`role = 'reimbursement'`) and the
  reimbursements noted by hand (`link_manual`: cash or another account that is not imported).
  The group has a "with whom" (`with_whom`), an optional name (`name`) and "they won't pay me
  back" (`written_off`). A group without expenses does not exist: removing the last one deletes
  it.
- A **currency exchange** (`kind = 'exchange'`) groups legs (`role = 'leg'`) in two
  currencies, with an optional agreed rate and whether it was marked complete.
- An **investment** (`kind = 'investment'`, schema 13) has contributions
  (`role = 'contribution'`: debits), returns (`'return'`: credits that are income), capital
  repayments (`'capital'`: credits that are not income) and mixed credits (`'mixed'`:
  `capital_cents` of capital, in the credit's currency, and the rest return). It has a "with
  whom", an optional name and "written off" (`written_off`). An investment without
  contributions does not exist: removing the last one deletes it (its credits become free).
  The math is in `investments`.
- A **cash box** (`kind = 'cash_box'`, schema 14) is a manual account (`account_key`): its
  members are the withdrawals stored in it (`role = 'stored'`: debits that are not expenses)
  and the bank deposits that came out of it (`'deposit'`: credits that are not income; if it
  leaves the box in another currency, `box_currency` and, optionally, `box_amount_cents`).
  What is noted by hand in the box goes in `cash_entries` (`cash_box_store`); the math, in
  `cash_box`.

Everything goes by fingerprint (`corrections.fingerprint`), so it survives `parse --retry`.
Each fingerprint is in at most one link (unique index): a credit reimburses a single group, an
expense is in a single group, a leg in a single exchange, and nothing is two things at once. A
fingerprint that no longer exists (a statement that changed) is ignored in the math.

This module only reads and writes; the math of each link is in `shared`, `exchanges` and
`investments`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from functools import cached_property
from typing import TYPE_CHECKING, Literal, get_args

from michelito.i18n import t

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

PERSON_MAX = 80
# The place the UI suggests for a cash reimbursement: stored as no place.
CASH_PLACE = "efectivo"  # spanish-data
RATE_MAX = Decimal(1_000_000)

InvestmentRole = Literal["contribution", "return", "capital", "mixed"]
INVESTMENT_ROLES: tuple[InvestmentRole, ...] = get_args(InvestmentRole)
CashBoxRole = Literal["stored", "deposit"]
CASH_BOX_ROLES: tuple[CashBoxRole, ...] = get_args(CashBoxRole)


class LinkError(ValueError):
    """Invalid request on a link (422)."""


class AlreadyLinked(LinkError):
    """The fingerprint is already in another link (409)."""


@dataclass(frozen=True)
class ManualEntry:
    """Reimbursement noted by hand: in cash or in an account that is not imported."""

    id: int
    amount: Decimal
    day: date
    currency: str  # the money's (for schema 11 rows, their expense's: see `db`)
    person: str = ""
    place: str = ""  # "" = cash


@dataclass(frozen=True)
class SharedExpense:
    """An expense of the group and its split (exactly one form)."""

    fingerprint: str
    people: int | None = None  # "we were N"
    my_share: Decimal | None = None  # "my share: RD$ X"
    for_other: bool = False  # "I paid it for someone else": my share is 0


@dataclass(frozen=True)
class Shared:
    """A shared group: its expenses (in the order they were added), its reimbursements and
    with whom."""

    id: int
    expenses: tuple[SharedExpense, ...]
    with_whom: str = ""  # "with whom"
    name: str = ""  # optional, e.g. a trip name
    written_off: bool = False  # "they won't pay me back"
    reimbursements: tuple[str, ...] = ()  # fingerprints of the credits
    manual: tuple[ManualEntry, ...] = ()

    @classmethod
    def one(
        cls,
        id: int,  # noqa: A002
        expense: str,
        *,
        people: int | None = None,
        my_share: Decimal | None = None,
        for_other: bool = False,
        with_whom: str = "",
        name: str = "",
        written_off: bool = False,
        reimbursements: tuple[str, ...] = (),
        manual: tuple[ManualEntry, ...] = (),
    ) -> Shared:
        """A group with a single expense (as all were before schema 12)."""
        return cls(
            id,
            (SharedExpense(expense, people, my_share, for_other),),
            with_whom,
            name,
            written_off,
            reimbursements,
            manual,
        )

    def split(self, fingerprint: str) -> SharedExpense | None:
        return next((e for e in self.expenses if e.fingerprint == fingerprint), None)


@dataclass(frozen=True)
class Exchange:
    id: int
    legs: tuple[str, ...]  # fingerprints, in the order they were added
    agreed_rate: Decimal | None = None  # agreed RD$ per US$
    closed: bool = False  # "exchange complete"


@dataclass(frozen=True)
class InvestmentMember:
    """A transaction of an investment: its role and, for a mixed credit, the capital part."""

    fingerprint: str
    role: InvestmentRole
    capital: Decimal | None = None  # "mixed" only: capital in the credit's currency


@dataclass(frozen=True)
class Investment:
    """An investment: its transactions (in the order they were added), with whom and its state."""

    id: int
    members: tuple[InvestmentMember, ...]
    with_whom: str = ""
    name: str = ""
    written_off: bool = False  # "written off"

    @property
    def contributions(self) -> tuple[str, ...]:
        return tuple(m.fingerprint for m in self.members if m.role == "contribution")

    def member(self, fingerprint: str) -> InvestmentMember | None:
        return next((m for m in self.members if m.fingerprint == fingerprint), None)


@dataclass(frozen=True)
class CashBoxMember:
    """A withdrawal stored in the box or a deposit that came out of it."""

    fingerprint: str
    role: CashBoxRole
    # Only on a deposit that leaves the box in a currency other than the credit's: that
    # currency and, if given, how much left in it (otherwise it is converted at the rate of the
    # deposit's month).
    box_currency: str | None = None
    box_amount: Decimal | None = None


@dataclass(frozen=True)
class CashBox:
    """A cash box: its manual account and its stored withdrawals and deposits (in the order
    they were added)."""

    id: int
    account_key: str
    members: tuple[CashBoxMember, ...] = ()

    def member(self, fingerprint: str) -> CashBoxMember | None:
        return next((m for m in self.members if m.fingerprint == fingerprint), None)


@dataclass(frozen=True)
class Candidate:
    """An option of a link picker, already sorted: `primary` says whether it goes in the
    visible part (the interface shows a few and leaves the rest behind "See more")."""

    move: Movement
    primary: bool


@dataclass(frozen=True)
class Links:
    shared: tuple[Shared, ...] = ()
    exchanges: tuple[Exchange, ...] = field(default_factory=tuple)
    investments: tuple[Investment, ...] = ()
    cash_boxes: tuple[CashBox, ...] = ()
    # Expenses linked to a reserve (schema 17): fingerprint -> reserve id. The link does not
    # change their category (see `reserve_store`).
    reserved: Mapping[str, int] = field(default_factory=dict)

    @cached_property
    def _by_expense(self) -> dict[str, Shared]:
        return {e.fingerprint: s for s in self.shared for e in s.expenses}

    @cached_property
    def _by_credit(self) -> dict[str, Shared]:
        return {credit: s for s in self.shared for credit in s.reimbursements}

    @cached_property
    def _by_leg(self) -> dict[str, Exchange]:
        return {leg: e for e in self.exchanges for leg in e.legs}

    def shared_for(self, fingerprint: str) -> Shared | None:
        """The shared group holding this expense."""
        return self._by_expense.get(fingerprint)

    def reimbursed(self, fingerprint: str) -> Shared | None:
        """The shared group this credit reimburses."""
        return self._by_credit.get(fingerprint)

    def group(self, link_id: int) -> Shared | None:
        return next((s for s in self.shared if s.id == link_id), None)

    @cached_property
    def _by_investment(self) -> dict[str, Investment]:
        return {m.fingerprint: i for i in self.investments for m in i.members}

    def investment_for(self, fingerprint: str) -> Investment | None:
        """The investment holding this transaction (as a contribution or as a credit)."""
        return self._by_investment.get(fingerprint)

    def investment(self, investment_id: int) -> Investment | None:
        return next((i for i in self.investments if i.id == investment_id), None)

    @cached_property
    def _by_cash_box(self) -> dict[str, CashBox]:
        return {m.fingerprint: box for box in self.cash_boxes for m in box.members}

    def cash_box_for(self, fingerprint: str) -> CashBox | None:
        """The box of this stored withdrawal or deposit."""
        return self._by_cash_box.get(fingerprint)

    def exchange_for(self, fingerprint: str) -> Exchange | None:
        return self._by_leg.get(fingerprint)

    def exchange(self, exchange_id: int) -> Exchange | None:
        return next((e for e in self.exchanges if e.id == exchange_id), None)

    def is_linked(self, fingerprint: str) -> bool:
        return (
            fingerprint in self._by_expense
            or fingerprint in self._by_credit
            or fingerprint in self._by_leg
            or fingerprint in self._by_investment
            or fingerprint in self._by_cash_box
            or fingerprint in self.reserved
        )

    @cached_property
    def fingerprints(self) -> frozenset[str]:
        """All fingerprints that are in some link."""
        return frozenset(
            (
                *self._by_expense,
                *self._by_credit,
                *self._by_leg,
                *self._by_investment,
                *self._by_cash_box,
                *self.reserved,
            )
        )

    def reserve_for(self, fingerprint: str) -> int | None:
        """The reserve covering this expense."""
        return self.reserved.get(fingerprint)


NONE = Links()


def load(conn: sqlite3.Connection) -> Links:
    members: dict[int, list[sqlite3.Row]] = {}
    for row in conn.execute("SELECT * FROM link_members ORDER BY added_at, rowid"):
        members.setdefault(row["link_id"], []).append(row)
    manual: dict[int, list[ManualEntry]] = {}
    for row in conn.execute("SELECT * FROM link_manual ORDER BY day, id"):
        manual.setdefault(row["link_id"], []).append(
            ManualEntry(
                id=row["id"],
                amount=Decimal(row["amount_cents"]) / 100,
                day=date.fromisoformat(row["day"]),
                person=row["person"] or "",
                place=row["place"] or "",
                currency=row["currency"],
            )
        )
    shared: list[Shared] = []
    exchanges: list[Exchange] = []
    investments: list[Investment] = []
    boxes: list[CashBox] = []
    reserved: dict[str, int] = {}
    for row in conn.execute("SELECT * FROM links ORDER BY id"):
        rows = members.get(row["id"], [])
        if row["kind"] == "reserve":
            reserved.update((m["fingerprint"], int(row["id"])) for m in rows)
            continue
        if row["kind"] == "cash_box":
            boxes.append(_cash_box(row, rows))
            continue
        if row["kind"] == "exchange":
            exchanges.append(_exchange(row, rows))
            continue
        if row["kind"] == "investment":
            found = _investment(row, rows)
            if found.contributions:
                investments.append(found)
            continue
        expenses = tuple(_split(m) for m in rows if m["role"] == "expense")
        if not expenses:
            continue
        shared.append(
            Shared(
                id=row["id"],
                expenses=expenses,
                with_whom=row["with_whom"] or "",
                name=row["name"] or "",
                written_off=bool(row["written_off"]),
                reimbursements=tuple(
                    m["fingerprint"] for m in rows if m["role"] == "reimbursement"
                ),
                manual=tuple(manual.get(row["id"], ())),
            )
        )
    return Links(tuple(shared), tuple(exchanges), tuple(investments), tuple(boxes), reserved)


def _cash_box(row: sqlite3.Row, members: Iterable[sqlite3.Row]) -> CashBox:
    found = []
    for m in members:
        if m["role"] not in CASH_BOX_ROLES:
            continue
        cents = m["box_amount_cents"]
        found.append(
            CashBoxMember(
                fingerprint=m["fingerprint"],
                role=m["role"],
                box_currency=m["box_currency"],
                box_amount=None if cents is None else Decimal(cents) / 100,
            )
        )
    return CashBox(id=row["id"], account_key=row["account_key"] or "", members=tuple(found))


def _investment(row: sqlite3.Row, members: Iterable[sqlite3.Row]) -> Investment:
    found = []
    for m in members:
        if m["role"] not in INVESTMENT_ROLES:
            continue
        cents = m["capital_cents"]
        capital = None if cents is None or m["role"] != "mixed" else Decimal(cents) / 100
        found.append(InvestmentMember(m["fingerprint"], m["role"], capital))
    return Investment(
        id=row["id"],
        members=tuple(found),
        with_whom=row["with_whom"] or "",
        name=row["name"] or "",
        written_off=bool(row["written_off"]),
    )


def _split(row: sqlite3.Row) -> SharedExpense:
    cents = row["my_share_cents"]
    return SharedExpense(
        fingerprint=row["fingerprint"],
        people=row["people"],
        my_share=None if cents is None else Decimal(cents) / 100,
        for_other=bool(row["for_other"]),
    )


def _exchange(row: sqlite3.Row, members: Iterable[sqlite3.Row]) -> Exchange:
    return Exchange(
        id=row["id"],
        legs=tuple(m["fingerprint"] for m in members if m["role"] == "leg"),
        agreed_rate=None if row["agreed_rate"] is None else Decimal(row["agreed_rate"]),
        closed=bool(row["closed"]),
    )


# --- Shared groups -------------------------------------------------------------------------


def set_shared(
    conn: sqlite3.Connection,
    expense: str,
    amount: Decimal,
    *,
    people: int | None = None,
    my_share: Decimal | None = None,
    for_other: bool = False,
    with_whom: str | None = None,
) -> int:
    """Marks (or changes) the split of an expense; exactly one of the three forms.

    If the expense is already in a group, its split changes (the group and its reimbursements
    stay); otherwise a new group is created with it (`with_whom`: optional "with whom").
    `amount`: the expense amount (positive), to validate my share (0 < X <= amount). Returns
    the group id.
    """
    _check_split(amount, people, my_share, for_other)
    current = _shared_id(conn, expense)
    if current is not None:
        conn.execute(
            "UPDATE link_members SET people = ?, my_share_cents = ?, for_other = ? "
            "WHERE link_id = ? AND fingerprint = ? AND role = 'expense'",
            (people, _share_cents(my_share), int(for_other), current, expense),
        )
        _touch(conn, current)
        return current
    if _link_of(conn, expense) is not None:
        raise AlreadyLinked(t("analysis.links.already_linked"))
    now = _now()
    cursor = conn.execute(
        "INSERT INTO links (kind, with_whom, created_at, updated_at) VALUES ('shared', ?, ?, ?)",
        (_text(with_whom, t("analysis.links.field_with_whom")), now, now),
    )
    found = int(cursor.lastrowid or 0)
    _insert_expense(conn, found, expense, people, my_share, for_other)
    return found


def add_expense(
    conn: sqlite3.Connection,
    link_id: int,
    expense: str,
    amount: Decimal,
    *,
    people: int | None = None,
    my_share: Decimal | None = None,
    for_other: bool = False,
) -> None:
    """Adds an expense (with its split) to an existing group."""
    _require_group(conn, link_id)
    _check_split(amount, people, my_share, for_other)
    if _link_of(conn, expense) is not None:
        raise AlreadyLinked(t("analysis.links.already_linked"))
    _insert_expense(conn, link_id, expense, people, my_share, for_other)
    _touch(conn, link_id)


def _insert_expense(
    conn: sqlite3.Connection,
    link_id: int,
    expense: str,
    people: int | None,
    my_share: Decimal | None,
    for_other: bool,
) -> None:
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at, people, "
        "my_share_cents, for_other) VALUES (?, ?, 'expense', ?, ?, ?, ?)",
        (link_id, expense, _now(), people, _share_cents(my_share), int(for_other)),
    )


def _share_cents(my_share: Decimal | None) -> int | None:
    return None if my_share is None else _to_cents(my_share)


def _check_split(
    amount: Decimal, people: int | None, my_share: Decimal | None, for_other: bool
) -> None:
    if amount <= 0:
        raise LinkError(t("analysis.links.only_expense_shared"))
    given = sum((people is not None, my_share is not None, for_other))
    if given != 1:
        raise LinkError(t("analysis.links.choose_split"))
    if people is not None and not 2 <= people <= 100:
        raise LinkError(t("analysis.links.people_range"))
    if my_share is not None and not 0 < my_share <= amount:
        raise LinkError(t("analysis.links.share_range"))


def unshare(conn: sqlite3.Connection, expense: str) -> bool:
    """Removes the expense from its group; the reimbursements stay in the group. If it was the
    last expense, deletes the group: its credits go back to their category and the ones noted
    by hand are deleted. Returns whether the group was deleted."""
    found = _shared_id(conn, expense)
    if found is None:
        return False
    conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ? AND role = 'expense'",
        (found, expense),
    )
    left = conn.execute(
        "SELECT COUNT(*) FROM link_members WHERE link_id = ? AND role = 'expense'", (found,)
    ).fetchone()[0]
    if left == 0:
        conn.execute("DELETE FROM links WHERE id = ?", (found,))
        return True
    _touch(conn, found)
    return False


def set_group(
    conn: sqlite3.Connection,
    link_id: int,
    *,
    name: str | None | object = ...,
    with_whom: str | None | object = ...,
) -> None:
    """Name and "with whom" of the group: absent (`...`) leaves it; empty or None clears it."""
    _require_group(conn, link_id)
    if name is not ...:
        text = _text(name if isinstance(name, str) else None, t("analysis.links.field_name"))
        conn.execute("UPDATE links SET name = ? WHERE id = ?", (text, link_id))
    if with_whom is not ...:
        text = _text(
            with_whom if isinstance(with_whom, str) else None, t("analysis.links.field_with_whom")
        )
        conn.execute("UPDATE links SET with_whom = ? WHERE id = ?", (text, link_id))
    _touch(conn, link_id)


def set_written_off(conn: sqlite3.Connection, link_id: int, written_off: bool) -> None:
    _require_group(conn, link_id)
    conn.execute(
        "UPDATE links SET written_off = ?, updated_at = ? WHERE id = ?",
        (int(written_off), _now(), link_id),
    )


def add_reimbursement(conn: sqlite3.Connection, link_id: int, credit: str) -> None:
    _require_group(conn, link_id)
    if _link_of(conn, credit) is not None:
        raise AlreadyLinked(t("analysis.links.credit_already_linked"))
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at) "
        "VALUES (?, ?, 'reimbursement', ?)",
        (link_id, credit, _now()),
    )


def remove_reimbursement(conn: sqlite3.Connection, link_id: int, credit: str) -> None:
    _require_group(conn, link_id)
    cursor = conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ? AND role = 'reimbursement'",
        (link_id, credit),
    )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.links.not_group_reimbursement"))


def add_manual(
    conn: sqlite3.Connection,
    link_id: int,
    amount: Decimal,
    day: date,
    currency: str,
    person: str | None = None,
    place: str | None = None,
) -> int:
    """Reimbursement in cash (empty `place`) or in another account (`place`: where), in
    `currency` (always stored: if an expense in another currency is added later, it does not
    change)."""
    _require_group(conn, link_id)
    if amount <= 0:
        raise LinkError(t("analysis.links.amount_positive"))
    if currency not in ("DOP", "USD"):
        raise LinkError(t("analysis.links.currency_choice"))
    cursor = conn.execute(
        "INSERT INTO link_manual (link_id, amount_cents, day, person, place, currency, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            link_id,
            _to_cents(amount),
            day.isoformat(),
            _text(person, t("analysis.links.field_from_whom")),
            _place(place),
            currency,
            _now(),
        ),
    )
    return int(cursor.lastrowid or 0)


def remove_manual(conn: sqlite3.Connection, link_id: int, entry_id: int) -> None:
    _require_group(conn, link_id)
    cursor = conn.execute(
        "DELETE FROM link_manual WHERE id = ? AND link_id = ?", (entry_id, link_id)
    )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.links.manual_not_in_group"))


def places(conn: sqlite3.Connection) -> list[str]:
    """Where reimbursements were noted before (cash excluded), the most recent first."""
    rows = conn.execute(
        "SELECT place, MAX(created_at) AS last FROM link_manual WHERE place IS NOT NULL "
        "GROUP BY place ORDER BY last DESC, place"
    )
    return [row["place"] for row in rows]


def _place(place: str | None) -> str | None:
    text = _text(place, t("analysis.links.field_place"))
    return None if text is None or text.casefold() == CASH_PLACE else text


# --- Currency exchanges ---------------------------------------------------------------------


def create_exchange(
    conn: sqlite3.Connection, legs: Iterable[str], agreed_rate: Decimal | None = None
) -> int:
    """New exchange with these legs (the caller validates currencies and directions)."""
    chosen = list(dict.fromkeys(legs))
    if len(chosen) < 2:
        raise LinkError(t("analysis.links.exchange_needs_legs"))
    for leg in chosen:
        if _link_of(conn, leg) is not None:
            raise AlreadyLinked(t("analysis.links.leg_already_linked"))
    now = _now()
    cursor = conn.execute(
        "INSERT INTO links (kind, agreed_rate, created_at, updated_at) "
        "VALUES ('exchange', ?, ?, ?)",
        (_rate_text(agreed_rate), now, now),
    )
    found = int(cursor.lastrowid or 0)
    _insert_legs(conn, found, chosen, now)
    return found


def add_legs(conn: sqlite3.Connection, exchange_id: int, legs: Iterable[str]) -> None:
    _require_exchange(conn, exchange_id)
    chosen = list(dict.fromkeys(legs))
    for leg in chosen:
        if _link_of(conn, leg) is not None:
            raise AlreadyLinked(t("analysis.links.leg_already_linked"))
    _insert_legs(conn, exchange_id, chosen, _now())


def _insert_legs(conn: sqlite3.Connection, exchange_id: int, legs: list[str], now: str) -> None:
    conn.executemany(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at) VALUES (?, ?, 'leg', ?)",
        [(exchange_id, leg, now) for leg in legs],
    )


def remove_leg(conn: sqlite3.Connection, exchange_id: int, leg: str) -> None:
    _require_exchange(conn, exchange_id)
    conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ?", (exchange_id, leg)
    )


def update_exchange(
    conn: sqlite3.Connection,
    exchange_id: int,
    *,
    agreed_rate: Decimal | None | object = ...,
    closed: bool | None = None,
) -> None:
    """`agreed_rate`: absent (`...`) leaves it; `None` goes back to the implied rate."""
    _require_exchange(conn, exchange_id)
    if agreed_rate is not ...:
        rate = agreed_rate if isinstance(agreed_rate, Decimal) else None
        conn.execute(
            "UPDATE links SET agreed_rate = ? WHERE id = ?", (_rate_text(rate), exchange_id)
        )
    if closed is not None:
        conn.execute("UPDATE links SET closed = ? WHERE id = ?", (int(closed), exchange_id))
    conn.execute("UPDATE links SET updated_at = ? WHERE id = ?", (_now(), exchange_id))


def delete_exchange(conn: sqlite3.Connection, exchange_id: int) -> None:
    conn.execute("DELETE FROM links WHERE id = ? AND kind = 'exchange'", (exchange_id,))


def _rate_text(rate: Decimal | None) -> str | None:
    if rate is None:
        return None
    if not rate.is_finite() or not 0 < rate < RATE_MAX:
        raise LinkError(t("analysis.links.rate_positive"))
    return str(rate.quantize(Decimal("0.0001")))


# --- Investments -----------------------------------------------------------------------------


def create_investment(
    conn: sqlite3.Connection,
    contribution: str,
    *,
    with_whom: str | None = None,
    name: str | None = None,
) -> int:
    """New investment with this contribution (the caller validates it is a debit)."""
    if _link_of(conn, contribution) is not None:
        raise AlreadyLinked(t("analysis.links.already_linked"))
    with_text, name_text = (
        _text(with_whom, t("analysis.links.field_with_whom")),
        _text(name, t("analysis.links.field_name")),
    )
    now = _now()
    cursor = conn.execute(
        "INSERT INTO links (kind, with_whom, name, created_at, updated_at) "
        "VALUES ('investment', ?, ?, ?, ?)",
        (with_text, name_text, now, now),
    )
    found = int(cursor.lastrowid or 0)
    _insert_member(conn, found, contribution, "contribution", None)
    return found


def add_investment_member(
    conn: sqlite3.Connection,
    investment_id: int,
    fingerprint: str,
    role: InvestmentRole,
    amount: Decimal,
    capital: Decimal | None = None,
) -> None:
    """Adds a contribution or a credit to the investment. `amount`: the transaction amount
    (positive), to validate the capital part of a mixed one (0 < capital < amount)."""
    _require_investment(conn, investment_id)
    _check_role(role, amount, capital)
    if _link_of(conn, fingerprint) is not None:
        raise AlreadyLinked(t("analysis.links.already_linked"))
    _insert_member(conn, investment_id, fingerprint, role, capital)
    _touch(conn, investment_id)


def set_investment_role(
    conn: sqlite3.Connection,
    investment_id: int,
    fingerprint: str,
    role: InvestmentRole,
    amount: Decimal,
    capital: Decimal | None = None,
) -> None:
    """Changes the kind of an investment credit (return, capital or mixed)."""
    _require_investment(conn, investment_id)
    if role == "contribution":
        raise LinkError(t("analysis.links.credit_not_contribution"))
    _check_role(role, amount, capital)
    cursor = conn.execute(
        "UPDATE link_members SET role = ?, capital_cents = ? WHERE link_id = ? "
        "AND fingerprint = ? AND role IN ('return', 'capital', 'mixed')",
        (role, _capital_cents(role, capital), investment_id, fingerprint),
    )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.links.credit_not_in_investment"))
    _touch(conn, investment_id)


def remove_investment_member(
    conn: sqlite3.Connection, investment_id: int, fingerprint: str
) -> bool:
    """Removes the transaction from the investment. If it was the last contribution, deletes
    the investment (its credits go back to their category). Returns whether it was deleted."""
    _require_investment(conn, investment_id)
    cursor = conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ?",
        (investment_id, fingerprint),
    )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.links.move_not_in_investment"))
    left = conn.execute(
        "SELECT COUNT(*) FROM link_members WHERE link_id = ? AND role = 'contribution'",
        (investment_id,),
    ).fetchone()[0]
    if left == 0:
        conn.execute("DELETE FROM links WHERE id = ?", (investment_id,))
        return True
    _touch(conn, investment_id)
    return False


def set_investment(
    conn: sqlite3.Connection,
    investment_id: int,
    *,
    name: str | None | object = ...,
    with_whom: str | None | object = ...,
    written_off: bool | None = None,
) -> None:
    """Name, "with whom" and "written off": absent (`...`, or None for `written_off`) leaves
    it; an empty text or None clears it."""
    _require_investment(conn, investment_id)
    if name is not ...:
        text = _text(name if isinstance(name, str) else None, t("analysis.links.field_name"))
        conn.execute("UPDATE links SET name = ? WHERE id = ?", (text, investment_id))
    if with_whom is not ...:
        text = _text(
            with_whom if isinstance(with_whom, str) else None, t("analysis.links.field_with_whom")
        )
        conn.execute("UPDATE links SET with_whom = ? WHERE id = ?", (text, investment_id))
    if written_off is not None:
        conn.execute(
            "UPDATE links SET written_off = ? WHERE id = ?", (int(written_off), investment_id)
        )
    _touch(conn, investment_id)


def _check_role(role: str, amount: Decimal, capital: Decimal | None) -> None:
    if role not in INVESTMENT_ROLES:
        raise LinkError(t("analysis.links.unknown_role", role=role))
    if amount <= 0:
        raise LinkError(t("analysis.links.amount_positive"))
    if role != "mixed":
        if capital is not None:
            raise LinkError(t("analysis.links.capital_only_mixed"))
        return
    if capital is None or not 0 < capital < amount:
        raise LinkError(t("analysis.links.capital_range"))


def _capital_cents(role: str, capital: Decimal | None) -> int | None:
    return _to_cents(capital) if role == "mixed" and capital is not None else None


def _insert_member(
    conn: sqlite3.Connection,
    investment_id: int,
    fingerprint: str,
    role: InvestmentRole,
    capital: Decimal | None,
) -> None:
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at, capital_cents) "
        "VALUES (?, ?, ?, ?, ?)",
        (investment_id, fingerprint, role, _now(), _capital_cents(role, capital)),
    )


def _require_investment(conn: sqlite3.Connection, investment_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM links WHERE id = ? AND kind = 'investment'", (investment_id,)
    ).fetchone()
    if row is None:
        raise LookupError(t("analysis.links.unknown_investment", id=investment_id))


# --- Helpers --------------------------------------------------------------------------------


def _link_of(conn: sqlite3.Connection, fingerprint: str) -> int | None:
    row = conn.execute(
        "SELECT link_id FROM link_members WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    return None if row is None else int(row[0])


def _shared_id(conn: sqlite3.Connection, expense: str) -> int | None:
    row = conn.execute(
        "SELECT link_id FROM link_members WHERE fingerprint = ? AND role = 'expense'", (expense,)
    ).fetchone()
    return None if row is None else int(row[0])


def group_of(conn: sqlite3.Connection, expense: str) -> int:
    """The group of this expense; LinkError if it is not shared."""
    found = _shared_id(conn, expense)
    if found is None:
        raise LinkError(t("analysis.links.not_shared"))
    return found


def _require_group(conn: sqlite3.Connection, link_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM links WHERE id = ? AND kind = 'shared'", (link_id,)
    ).fetchone()
    if row is None:
        raise LookupError(t("analysis.links.unknown_group", id=link_id))


def _touch(conn: sqlite3.Connection, link_id: int) -> None:
    conn.execute("UPDATE links SET updated_at = ? WHERE id = ?", (_now(), link_id))


def _require_exchange(conn: sqlite3.Connection, exchange_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM links WHERE id = ? AND kind = 'exchange'", (exchange_id,)
    ).fetchone()
    if row is None:
        raise LookupError(t("analysis.links.unknown_exchange", id=exchange_id))


def _to_cents(amount: Decimal) -> int:
    try:
        scaled = amount * 100
        if scaled != scaled.to_integral_value():
            raise LinkError(t("analysis.links.too_many_decimals"))
    except InvalidOperation:
        raise LinkError(t("analysis.links.invalid_amount")) from None
    return int(scaled)


def _text(value: str | None, what: str) -> str | None:
    text = " ".join((value or "").split())
    if len(text) > PERSON_MAX:
        raise LinkError(t("analysis.links.text_too_long", field=what, max=PERSON_MAX))
    return text or None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
