"""Installment plans as stored (schema 25, `migrations_v25`; the matching is `installment_match`).

- `load` gives every plan with its linked charges; `taken` and `dismissed`, what the matching
  needs to know about the links.
- `create`, `delete`, `confirm` (link a charge as installment n), `unlink` (it is not part of
  the plan: refused, so it is not linked again).
- `reconcile` links the exact charges of the flow and, for a member's plan, records each
  linked installment as that member's whole share of an expense in their group (the same as
  sharing it by hand). It returns the off-script charges for review.

Nothing here commits: the caller wraps it in `with conn:` (and the change log).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from michelito.analysis import installment_match, ledger_store
from michelito.analysis.installment_match import Charge, Matches, Terms
from michelito.analysis.ledger import Split
from michelito.analysis.links import LinkError
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.migrations_v25 import COUNT_MAX, NAME_MAX

_CENTS = 100


@dataclass(frozen=True)
class Plan:
    id: int
    name: str
    account: str
    matcher: str
    amount_cents: int
    currency: str
    count: int
    first_month: str
    group_id: int | None = None
    contact_id: int | None = None
    receipt_id: int | None = None
    links: dict[int, str] = field(default_factory=dict)  # number -> fingerprint
    entries: dict[int, int] = field(default_factory=dict)  # number -> ledger entry it recorded

    @property
    def terms(self) -> Terms:
        return Terms(
            self.id,
            self.account,
            self.matcher,
            self.amount_cents,
            self.currency,
            self.count,
            self.first_month,
        )

    @property
    def for_member(self) -> bool:
        return self.group_id is not None and self.contact_id is not None

    @property
    def last_month(self) -> str:
        return installment_match.month_of_number(self.first_month, self.count)


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'installment_plans'"
    ).fetchone()
    return row is not None


def load(conn: sqlite3.Connection) -> list[Plan]:
    if not _has_tables(conn):
        return []
    links: dict[int, dict[int, str]] = {}
    entries: dict[int, dict[int, int]] = {}
    for plan_id, number, fingerprint, entry_id in conn.execute(
        "SELECT plan_id, number, fingerprint, entry_id FROM installment_links ORDER BY number"
    ):
        links.setdefault(int(plan_id), {})[int(number)] = str(fingerprint)
        if entry_id is not None:
            entries.setdefault(int(plan_id), {})[int(number)] = int(entry_id)
    rows = conn.execute(
        "SELECT id, name, account_key, matcher, amount_cents, currency, count, first_month, "
        "group_id, contact_id, receipt_id FROM installment_plans ORDER BY id"
    ).fetchall()
    return [
        Plan(
            id=int(r[0]),
            name=str(r[1]),
            account=str(r[2]),
            matcher=str(r[3]),
            amount_cents=int(r[4]),
            currency=str(r[5]),
            count=int(r[6]),
            first_month=str(r[7]),
            group_id=None if r[8] is None else int(r[8]),
            contact_id=None if r[9] is None else int(r[9]),
            receipt_id=None if r[10] is None else int(r[10]),
            links=links.get(int(r[0]), {}),
            entries=entries.get(int(r[0]), {}),
        )
        for r in rows
    ]


def taken(conn: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    if not _has_tables(conn):
        return {}
    rows = conn.execute("SELECT fingerprint, plan_id, number FROM installment_links")
    return {str(r[0]): (int(r[1]), int(r[2])) for r in rows}


def dismissed(conn: sqlite3.Connection) -> set[tuple[int, str]]:
    if not _has_tables(conn):
        return set()
    rows = conn.execute("SELECT plan_id, fingerprint FROM installment_dismissals")
    return {(int(r[0]), str(r[1])) for r in rows}


def create(
    conn: sqlite3.Connection,
    *,
    name: str,
    account: str,
    matcher: str,
    amount_cents: int,
    currency: str,
    count: int,
    first_month: str,
    now: str,
    group_id: int | None = None,
    contact_id: int | None = None,
    receipt_id: int | None = None,
) -> int:
    """A new plan; a member's plan needs both its group and the member, who must be in it."""
    if (group_id is None) != (contact_id is None):
        raise LinkError(t("analysis.installments.member_needs_group"))
    if not 2 <= count <= COUNT_MAX:
        raise LinkError(t("analysis.installments.count_range", max=COUNT_MAX))
    if group_id is not None and contact_id is not None:
        member = conn.execute(
            "SELECT 1 FROM ledger_members WHERE group_id = ? AND contact_id = ?",
            (group_id, contact_id),
        ).fetchone()
        if member is None:
            raise LinkError(t("analysis.installments.not_a_member"))
    cursor = conn.execute(
        "INSERT INTO installment_plans (name, account_key, matcher, amount_cents, currency, "
        "count, first_month, group_id, contact_id, receipt_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ledger_store.clean_name(name, limit=NAME_MAX),
            account,
            matcher,
            amount_cents,
            currency,
            count,
            first_month,
            group_id,
            contact_id,
            receipt_id,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid or 0)


def _plan(conn: sqlite3.Connection, plan_id: int) -> Plan:
    found = next((p for p in load(conn) if p.id == plan_id), None)
    if found is None:
        raise LookupError(plan_id)
    return found


def delete(conn: sqlite3.Connection, plan_id: int) -> None:
    """The plan, its links and the group expenses it recorded (the charges stay as they are)."""
    plan = _plan(conn, plan_id)
    for entry_id in plan.entries.values():
        _drop_entry(conn, entry_id)
    conn.execute("DELETE FROM installment_plans WHERE id = ?", (plan_id,))


def _drop_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    if conn.execute("SELECT 1 FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone():
        ledger_store.delete_entry(conn, entry_id)


def _record_share(conn: sqlite3.Connection, plan: Plan, move: Movement) -> int | None:
    """A member's installment as their whole share of an expense the user paid. None when the
    charge is already in a group or linked to something else (the person did it by hand)."""
    if plan.group_id is None or plan.contact_id is None:
        return None
    if move.fingerprint in ledger_store.linked_fingerprints(conn):
        return None
    amount = abs(move.gross if move.gross is not None else move.amount)
    me = ledger_store.ensure_me(conn)
    group = conn.execute(
        "SELECT category_id FROM ledger_groups WHERE id = ?", (plan.group_id,)
    ).fetchone()
    try:
        return ledger_store.add_entry(
            conn,
            plan.group_id,
            paid_by=me,
            amount=amount,
            currency=move.currency,
            day=move.day,
            description=plan.name,
            splits=(Split(plan.contact_id, amount),),
            mode="exact",
            category_id=None if group is None else group[0],
            fingerprint=move.fingerprint,
        )
    except LinkError:
        return None


def _link(
    conn: sqlite3.Connection, plan: Plan, move: Movement, number: int, origin: str, now: str
) -> None:
    entry_id = _record_share(conn, plan, move)
    conn.execute(
        "INSERT INTO installment_links (plan_id, number, fingerprint, origin, entry_id, "
        "linked_at) VALUES (?, ?, ?, ?, ?, ?)",
        (plan.id, number, move.fingerprint, origin, entry_id, now),
    )
    conn.execute(
        "DELETE FROM installment_dismissals WHERE plan_id = ? AND fingerprint = ?",
        (plan.id, move.fingerprint),
    )


def confirm(conn: sqlite3.Connection, plan_id: int, move: Movement, number: int, now: str) -> None:
    """ "It is installment n": link it whatever its amount, if n is free and the charge is not
    in another plan."""
    plan = _plan(conn, plan_id)
    if not can_be_installment(move) or (move.account, move.currency) != (
        plan.account,
        plan.currency,
    ):
        raise LinkError(t("analysis.installments.not_this_plan"))
    if not 1 <= number <= plan.count or number in plan.links:
        raise LinkError(t("analysis.installments.number_taken"))
    if move.fingerprint in taken(conn):
        raise LinkError(t("analysis.installments.charge_taken"))
    _link(conn, plan, move, number, "confirmed", now)


def unlink(conn: sqlite3.Connection, plan_id: int, fingerprint: str, now: str) -> None:
    """It is not part of the plan: the link goes (and the group expense it recorded) and the
    pair is not proposed again."""
    plan = _plan(conn, plan_id)
    number = next((n for n, fp in plan.links.items() if fp == fingerprint), None)
    if number is not None:
        entry_id = plan.entries.get(number)
        conn.execute(
            "DELETE FROM installment_links WHERE plan_id = ? AND number = ?", (plan_id, number)
        )
        if entry_id is not None:
            _drop_entry(conn, entry_id)
    conn.execute(
        "INSERT OR IGNORE INTO installment_dismissals (plan_id, fingerprint, dismissed_at) "
        "VALUES (?, ?, ?)",
        (plan_id, fingerprint, now),
    )


def charge_of(move: Movement) -> Charge:
    """A movement as the matching sees it: the statement amount (for a shared one, the gross)."""
    amount = move.gross if move.gross is not None else move.amount
    return Charge(
        move.fingerprint,
        move.day,
        move.account,
        move.description,
        int((amount * _CENTS).to_integral_value()),
        move.currency,
    )


def can_be_installment(move: Movement) -> bool:
    """A charge from a statement (a provisional changes fingerprint), not an exchange or an
    investment, on an account, for a positive amount."""
    return (
        not move.provisional
        and move.link not in ("exchange", "investment")
        and bool(move.fingerprint)
        and bool(move.account)
        and charge_of(move).cents > 0
    )


def charges(flow: Sequence[Movement]) -> list[Charge]:
    """The card movements that may be installments: from statements (a provisional one changes
    fingerprint when its statement arrives) and not exchanges or investments."""
    return [
        charge_of(m)
        for m in flow
        if not m.provisional and m.link not in ("exchange", "investment") and m.fingerprint
    ]


def reconcile(conn: sqlite3.Connection, flow: Sequence[Movement], now: str) -> Matches:
    """Link the exact charges (recording a member's share) and give the off-script ones."""
    plans = load(conn)
    if not plans:
        return Matches()
    by_fp = {m.fingerprint: m for m in flow}
    found = installment_match.match(
        [p.terms for p in plans], charges(flow), taken(conn), dismissed(conn)
    )
    by_id = {p.id: p for p in plans}
    for fingerprint, (plan_id, number) in sorted(found.links.items(), key=lambda i: i[1]):
        _link(conn, by_id[plan_id], by_fp[fingerprint], number, "automatic", now)
    return found


def reconcile_stored(conn: sqlite3.Connection, now: str) -> Matches:
    """`reconcile` against the whole flow as stored, loaded only if there is a plan. For the
    places that store statements outside a board request (the sync, the forwarding inbox)."""
    from michelito.analysis import spending  # noqa: PLC0415 (it loads every analysis module)

    if not load(conn):
        return Matches()
    return reconcile(conn, spending.load_all(conn), now)


def remaining_cents(plan: Plan) -> int:
    return (plan.count - len(plan.links)) * plan.amount_cents


def amount_of(cents: int) -> Decimal:
    return Decimal(cents) / _CENTS
