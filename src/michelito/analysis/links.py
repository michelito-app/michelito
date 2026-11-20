"""Links between transactions: currency exchanges, investments, cash boxes and reserves.

A single stored model for all of them (tables `links` and `link_members`):
- Shared expenses no longer live here (schema 19): they are in the ledger (`ledger`,
  `ledger_store`), which links transactions through `ledger_links`; `Links.ledger` carries those
  fingerprints so that a fingerprint is still in at most one link of any kind. Old `'shared'`
  rows (and `link_manual`) are moved by `migrations_v19`.
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
Each fingerprint is in at most one link (unique index, and `link_of` also looks at
`ledger_links`): a leg is in a single exchange, and nothing is two things at once. A fingerprint
that no longer exists (a statement that changed) is ignored in the math.

This module only reads and writes; the math of each link is in `exchanges`, `investments`,
`cash_box` and `reserves`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import cached_property
from typing import TYPE_CHECKING, Literal, get_args

from michelito.i18n import t

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

PERSON_MAX = 80
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
    exchanges: tuple[Exchange, ...] = field(default_factory=tuple)
    investments: tuple[Investment, ...] = ()
    cash_boxes: tuple[CashBox, ...] = ()
    # Expenses linked to a reserve (schema 17): fingerprint -> reserve id. The link does not
    # change their category (see `reserve_store`).
    reserved: Mapping[str, int] = field(default_factory=dict)
    # Transactions linked to the shared ledger (schema 19): fingerprint -> (group id, "entry" or
    # "payment").
    ledger: Mapping[str, tuple[int, str]] = field(default_factory=dict)

    @cached_property
    def _by_leg(self) -> dict[str, Exchange]:
        return {leg: e for e in self.exchanges for leg in e.legs}

    def ledger_for(self, fingerprint: str) -> tuple[int, str] | None:
        """The ledger group and role ("entry" or "payment") of this transaction."""
        return self.ledger.get(fingerprint)

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
            fingerprint in self.ledger
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
                *self.ledger,
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
    exchanges: list[Exchange] = []
    investments: list[Investment] = []
    boxes: list[CashBox] = []
    reserved: dict[str, int] = {}
    for row in conn.execute("SELECT * FROM links ORDER BY id"):
        rows = members.get(row["id"], [])
        if row["kind"] == "reserve":
            reserved.update((m["fingerprint"], int(row["id"])) for m in rows)
        elif row["kind"] == "cash_box":
            boxes.append(_cash_box(row, rows))
        elif row["kind"] == "exchange":
            exchanges.append(_exchange(row, rows))
        elif row["kind"] == "investment":
            found = _investment(row, rows)
            if found.contributions:
                investments.append(found)
    return Links(tuple(exchanges), tuple(investments), tuple(boxes), reserved, _ledger_links(conn))


def _ledger_links(conn: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    if not _has_table(conn, "ledger_links"):
        return {}
    return {
        row["fingerprint"]: (int(row["group_id"]), "entry" if row["entry_id"] else "payment")
        for row in conn.execute("SELECT * FROM ledger_links")
    }


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return found is not None


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


def _exchange(row: sqlite3.Row, members: Iterable[sqlite3.Row]) -> Exchange:
    return Exchange(
        id=row["id"],
        legs=tuple(m["fingerprint"] for m in members if m["role"] == "leg"),
        agreed_rate=None if row["agreed_rate"] is None else Decimal(row["agreed_rate"]),
        closed=bool(row["closed"]),
    )


# --- Currency exchanges ---------------------------------------------------------------------


def create_exchange(
    conn: sqlite3.Connection, legs: Iterable[str], agreed_rate: Decimal | None = None
) -> int:
    """New exchange with these legs (the caller validates currencies and directions)."""
    chosen = list(dict.fromkeys(legs))
    if len(chosen) < 2:
        raise LinkError(t("analysis.links.exchange_needs_legs"))
    for leg in chosen:
        if link_of(conn, leg) is not None:
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
        if link_of(conn, leg) is not None:
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
    if link_of(conn, contribution) is not None:
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
    if link_of(conn, fingerprint) is not None:
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


def link_of(conn: sqlite3.Connection, fingerprint: str) -> int | None:
    """The link (or ledger group) holding this fingerprint, if any."""
    row = conn.execute(
        "SELECT link_id FROM link_members WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    if row is None and _has_table(conn, "ledger_links"):
        row = conn.execute(
            "SELECT group_id FROM ledger_links WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
    return None if row is None else int(row[0])


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
