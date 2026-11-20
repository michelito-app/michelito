"""Schema 19: shared groups move from `links` (kind `shared`) to the ledger (`analysis.ledger`).

It runs once (`user_version` below 19), last in `db`'s migration transaction, so either all of
it stays or nothing does. For each old group:

- **People**: "With whom" splits into names on " y ", "," and "&"; a name seen in another group
  is the same contact (ignoring accents and case). When the splits need more people than were
  named ("we were 4" with one name), the group gets placeholder people ("Person 2"…) to review
  in "Review your people" (a one-time screen: `ledger_settings`).
- **Entries**: each present expense (still a positive expense; the old math ignored the rest)
  becomes an entry the user paid, linked to its transaction, with the user's share exactly as
  before (`legacy_share`: "we were N" rounds half to even, "my share" is exact, "I paid for
  someone else" is 0); the rest is split equally among the other people (leftover cents to the
  first). They are inserted in the old order (date, fingerprint), so the ledger's (date, id)
  order applies payments the same way.
- **Payments**: each present reimbursement (a linked credit or one noted by hand), in the old
  order (date, key), becomes a payment to the user: attributed to the only other person when
  there is one and the group was not paid back in excess (in the ledger an attributed excess
  becomes a claim the other way, which the old math did not have), otherwise unattributed
  ("unassigned"). Linked credits stay linked.
- **Splits** are stored as exact amounts (the user's share as before and the rest), so editing
  an entry's description never moves a cent.
- **Dormant links**: an expense that is no longer a positive expense (or no longer there) and a
  credit that is no longer a credit (or no longer there) counted nothing in the old math. They
  are kept in `ledger_dormant` (fingerprint, old link, new group, role): zero effect, and the
  check script counts them. Each old link id maps to its new group in `ledger_migration`.
- «They won't pay me back» marks every other member.
- A group with no expense present (dormant) is kept archived with its payments, so its credits
  stay reimbursements as before.

**Invariant** (`check_balances`): each group's balances (by currency: the user's share, what was
paid back, what is pending and what was written off), what each expense counts as spending and
what each credit counts are computed with the old math (`legacy_state`, frozen here) before and
with the ledger after; any difference raises and the whole migration is rolled back.

The old shared rows are deleted first (`links` with their members and manual reimbursements;
foreign keys may be off during the migration, so the children go explicitly): everything was
read before, and their fingerprints are linked again in the ledger.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from michelito.i18n import t

if TYPE_CHECKING:
    from michelito.analysis.rates import Rate
    from michelito.analysis.spending import Movement

VERSION = 19

_CENT = Decimal("0.01")
_ZERO = Decimal(0)
_MANUAL = "manual:"
_MIN_EXCESS = {"DOP": Decimal(1), "USD": Decimal("0.05")}
_NAME_SPLIT = re.compile(r"\s*(?:,|&|\by\b|\bY\b)\s*")


class MigrationMismatch(sqlite3.IntegrityError):
    """The ledger would not give the same balances as the old groups."""


# --- The old model, frozen (schema 18) ------------------------------------------------------


@dataclass(frozen=True)
class LegacyExpense:
    fingerprint: str
    people: int | None = None
    my_share: Decimal | None = None
    for_other: bool = False


@dataclass(frozen=True)
class LegacyManual:
    id: int
    amount: Decimal
    day: date
    currency: str
    person: str = ""
    place: str = ""


@dataclass(frozen=True)
class LegacyGroup:
    id: int
    expenses: tuple[LegacyExpense, ...]
    with_whom: str = ""
    name: str = ""
    written_off: bool = False
    reimbursements: tuple[str, ...] = ()
    manual: tuple[LegacyManual, ...] = ()


@dataclass(frozen=True)
class LegacyRefund:
    key: str
    day: date
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class LegacyExpenseState:
    move: Movement
    split: LegacyExpense
    amount: Decimal
    share: Decimal
    reimbursed: Decimal
    pending: Decimal
    written_off: Decimal

    @property
    def counted(self) -> Decimal:
        return self.share + self.written_off


@dataclass(frozen=True)
class LegacyState:
    group: LegacyGroup
    expenses: tuple[LegacyExpenseState, ...]
    refunds: tuple[LegacyRefund, ...]
    excess: tuple[tuple[str, Decimal], ...]
    uncounted: frozenset[str]
    leftover: bool = False  # some reimbursement was left over (any amount, with a rate)

    def totals(self) -> dict[str, tuple[Decimal, Decimal, Decimal, Decimal]]:
        """By currency: (share, reimbursed, pending, written off)."""
        found: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {}
        for currency in sorted({e.move.currency for e in self.expenses}):
            mine = [e for e in self.expenses if e.move.currency == currency]
            found[currency] = (
                sum((e.share for e in mine), _ZERO),
                sum((e.reimbursed for e in mine), _ZERO),
                sum((e.pending for e in mine), _ZERO),
                sum((e.written_off for e in mine), _ZERO),
            )
        return found


def load_legacy(conn: sqlite3.Connection) -> list[LegacyGroup]:
    """The schema 18 shared groups (with or without expenses present)."""
    members: dict[int, list[sqlite3.Row]] = {}
    for row in conn.execute("SELECT * FROM link_members ORDER BY added_at, rowid"):
        members.setdefault(int(row["link_id"]), []).append(row)
    manual: dict[int, list[LegacyManual]] = {}
    for row in conn.execute("SELECT * FROM link_manual ORDER BY day, id"):
        manual.setdefault(int(row["link_id"]), []).append(
            LegacyManual(
                id=int(row["id"]),
                amount=Decimal(row["amount_cents"]) / 100,
                day=date.fromisoformat(row["day"]),
                currency=row["currency"] or "DOP",
                person=row["person"] or "",
                place=row["place"] or "",
            )
        )
    found = []
    for row in conn.execute("SELECT * FROM links WHERE kind = 'shared' ORDER BY id"):
        rows = members.get(int(row["id"]), [])
        found.append(
            LegacyGroup(
                id=int(row["id"]),
                expenses=tuple(
                    LegacyExpense(
                        m["fingerprint"],
                        m["people"],
                        None if m["my_share_cents"] is None else Decimal(m["my_share_cents"]) / 100,
                        bool(m["for_other"]),
                    )
                    for m in rows
                    if m["role"] == "expense"
                ),
                with_whom=row["with_whom"] or "",
                name=row["name"] or "",
                written_off=bool(row["written_off"]),
                reimbursements=tuple(
                    m["fingerprint"] for m in rows if m["role"] == "reimbursement"
                ),
                manual=tuple(manual.get(int(row["id"]), ())),
            )
        )
    return found


def legacy_share(split: LegacyExpense, amount: Decimal) -> Decimal:
    if split.for_other:
        return _ZERO
    if split.people is not None:
        return (amount / split.people).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    return min(split.my_share if split.my_share is not None else amount, amount)


def _gross(move: Movement) -> Decimal:
    return move.amount if move.gross is None else move.gross


def is_present(move: Movement | None) -> bool:
    """The old rule: an expense counts while it is still a positive expense."""
    return move is not None and move.kind == "expense" and _gross(move) > 0


def legacy_refunds(group: LegacyGroup, by_fp: Mapping[str, Movement]) -> tuple[LegacyRefund, ...]:
    found = [
        LegacyRefund(fp, move.day, -move.amount, move.currency)
        for fp in group.reimbursements
        if (move := by_fp.get(fp)) is not None and move.amount < 0
    ]
    found.extend(
        LegacyRefund(f"{_MANUAL}{m.id}", m.day, m.amount, m.currency) for m in group.manual
    )
    return tuple(sorted(found, key=lambda r: (r.day, r.key)))


def legacy_convert(
    amount: Decimal, source: str, target: str, day: date, rates: Mapping[str, Rate]
) -> Decimal | None:
    """`analysis.shared.convert` as schema 18 had it (frozen: the ledger's may change)."""
    from michelito.analysis.rates import rate_for  # noqa: PLC0415

    if source == target:
        return amount
    rate = rate_for(rates, day.strftime("%Y-%m"))
    if rate is None or rate.value <= 0:
        return None
    if source == "DOP" and target == "USD":
        return (amount / rate.value).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    if source == "USD" and target == "DOP":
        return (amount * rate.value).quantize(_CENT, rounding=ROUND_HALF_EVEN)
    return None


def legacy_impute(
    refund: LegacyRefund,
    currencies: Sequence[str],
    remaining: list[Decimal],
    applied: list[Decimal],
    rates: Mapping[str, Rate],
) -> tuple[Decimal, bool, bool]:
    """`analysis.shared._impute` as schema 18 had it (frozen): applies a reimbursement from the
    oldest expense to the newest; returns what is left, whether anything counted and whether an
    expense was skipped for lack of a rate."""
    left, counted, blocked = refund.amount, False, False
    for index, currency in enumerate(currencies):
        if left <= 0:
            break
        if remaining[index] <= 0:
            continue
        value = legacy_convert(left, refund.currency, currency, refund.day, rates)
        if value is None:
            blocked = True
            continue
        used = min(value, remaining[index])
        applied[index] += used
        remaining[index] -= used
        counted = counted or used > 0
        if used == value:
            return _ZERO, counted, blocked
        back = legacy_convert(used, currency, refund.currency, refund.day, rates) or _ZERO
        left = max(_ZERO, left - back)
    return left, counted, blocked


def legacy_state(
    group: LegacyGroup, by_fp: Mapping[str, Movement], rates: Mapping[str, Rate]
) -> LegacyState | None:
    """The schema 18 accounting (`analysis.shared.group_state` as it was); None if dormant."""
    present = [
        move
        for e in group.expenses
        if (move := by_fp.get(e.fingerprint)) is not None and is_present(move)
    ]
    if not present:
        return None
    ordered = sorted(present, key=lambda m: (m.day, m.fingerprint))
    splits = {e.fingerprint: e for e in group.expenses}
    amounts = [_gross(m) for m in ordered]
    shares = [legacy_share(splits[m.fingerprint], a) for m, a in zip(ordered, amounts, strict=True)]
    remaining = [a - s for a, s in zip(amounts, shares, strict=True)]
    applied = [_ZERO] * len(ordered)
    currencies = [m.currency for m in ordered]
    refunds = legacy_refunds(group, by_fp)
    excess: dict[str, Decimal] = {}
    uncounted: set[str] = set()
    leftover = False
    for refund in refunds:
        left, counted, blocked = legacy_impute(refund, currencies, remaining, applied, rates)
        if left <= 0:
            continue
        if not blocked:
            excess[refund.currency] = excess.get(refund.currency, _ZERO) + left
            leftover = True
            continue
        if not counted and not refund.key.startswith(_MANUAL):
            uncounted.add(refund.key)
    states = tuple(
        LegacyExpenseState(
            move=move,
            split=splits[move.fingerprint],
            amount=amount,
            share=share,
            reimbursed=applied[i],
            pending=_ZERO if group.written_off else remaining[i],
            written_off=remaining[i] if group.written_off else _ZERO,
        )
        for i, (move, amount, share) in enumerate(zip(ordered, amounts, shares, strict=True))
    )
    return LegacyState(
        group=group,
        expenses=states,
        refunds=refunds,
        excess=tuple(sorted((c, v) for c, v in excess.items() if v >= _MIN_EXCESS[c])),
        uncounted=frozenset(uncounted),
        leftover=leftover,
    )


# --- Conversion -----------------------------------------------------------------------------


def split_names(with_whom: str) -> list[str]:
    """«Ana y Luis, Pedro & Rosa» -> [Ana, Luis, Pedro, Rosa] (no empties, no repeats)."""
    names = [" ".join(part.split()) for part in _NAME_SPLIT.split(with_whom or "")]
    seen: dict[str, str] = {}
    for name in names:
        if name and name.casefold() not in seen:
            seen[name.casefold()] = name[:80]
    return list(seen.values())


def _others_needed(group: LegacyGroup) -> int:
    needed = 0
    for split in group.expenses:
        needed = max(needed, (split.people - 1) if split.people is not None else 1)
    return needed


def _spread(total: Decimal, people: Sequence[int]) -> dict[int, Decimal]:
    cents = int((total * 100).to_integral_value())
    base, left = divmod(cents, len(people))
    return {p: Decimal(base + (left if i == 0 else 0)) / 100 for i, p in enumerate(people)}


def _title(group: LegacyGroup, first: Movement | None) -> str:
    text = group.name or group.with_whom
    if not text and first is not None:
        text = first.merchant or first.description
    return (" ".join((text or "").split()) or t("analysis.ledger.migrated_group", id=group.id))[:80]


def convert_group(
    conn: sqlite3.Connection,
    group: LegacyGroup,
    state: LegacyState | None,
    by_fp: Mapping[str, Movement],
) -> tuple[int, bool]:
    """Writes the group in the ledger; returns its id and whether it made placeholder people."""
    from michelito.analysis import ledger_store as store  # noqa: PLC0415

    me = store.ensure_me(conn)
    first = None if state is None else state.expenses[0].move
    group_id = store.create_group(conn, _title(group, first))
    people = [store.contact_for(conn, name) for name in split_names(group.with_whom)]
    placeholders = False
    if state is not None:
        for number in range(len(people), _others_needed(group)):
            people.append(
                store.create_contact(conn, t("analysis.ledger.placeholder", number=number + 2))
            )
            placeholders = True
    for person in people:
        store.add_member(conn, group_id, person)
    if state is None:
        store.update_group(conn, group_id, archived=True)
    for expense in () if state is None else state.expenses:
        _convert_expense(conn, group_id, me, people, expense)
    single = len(people) == 1 and state is not None and not state.leftover
    attributed = people[0] if single else None
    for refund in legacy_refunds(group, by_fp):
        manual = next((m for m in group.manual if f"{_MANUAL}{m.id}" == refund.key), None)
        note = None if manual is None else " · ".join(p for p in (manual.person, manual.place) if p)
        store.add_payment(
            conn,
            group_id,
            from_contact=attributed,
            to_contact=me,
            amount=refund.amount,
            currency=refund.currency,
            day=refund.day,
            note=note,
            fingerprint=None if manual is not None else refund.key,
        )
    if group.written_off:
        store.set_written_off(conn, group_id, None, True)
    _keep_dormant(conn, group, group_id, by_fp)
    conn.execute(
        "INSERT INTO ledger_migration (link_id, group_id) VALUES (?, ?)", (group.id, group_id)
    )
    return group_id, placeholders


def _keep_dormant(
    conn: sqlite3.Connection, group: LegacyGroup, group_id: int, by_fp: Mapping[str, Movement]
) -> None:
    """The old group's expenses and credits that counted nothing (see the module docstring)."""
    rows = [
        (e.fingerprint, "expense")
        for e in group.expenses
        if (move := by_fp.get(e.fingerprint)) is None or not is_present(move)
    ]
    rows += [
        (fp, "payment")
        for fp in group.reimbursements
        if (move := by_fp.get(fp)) is None or move.amount >= 0
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO ledger_dormant (fingerprint, link_id, group_id, role) "
        "VALUES (?, ?, ?, ?)",
        [(fp, group.id, group_id, role) for fp, role in rows],
    )


def dormant_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """How many expenses and credits were kept dormant by the migration, by role."""
    rows = conn.execute("SELECT role, COUNT(*) FROM ledger_dormant GROUP BY role")
    return {str(role): int(count) for role, count in rows}


def _convert_expense(
    conn: sqlite3.Connection,
    group_id: int,
    me: int,
    people: Sequence[int],
    expense: LegacyExpenseState,
) -> None:
    from michelito.analysis import ledger_store as store  # noqa: PLC0415
    from michelito.analysis.ledger import Split  # noqa: PLC0415

    split = expense.split
    others = list(people)
    if split.people is not None:
        others = others[: split.people - 1]
    rest = expense.amount - expense.share
    shares = {me: expense.share}
    if rest > 0:
        shares.update(_spread(rest, others))
    move = expense.move
    store.add_entry(
        conn,
        group_id,
        paid_by=me,
        amount=expense.amount,
        currency=move.currency,
        day=move.day,
        description=(move.merchant or move.description or move.fingerprint)[:120],
        splits=[Split(c, v) for c, v in shares.items() if v > 0],
        mode="exact",
        fingerprint=move.fingerprint,
    )


# --- Invariant ------------------------------------------------------------------------------


def check_balances(
    old: Mapping[int, LegacyState],
    new_ids: Mapping[int, int],
    conn: sqlite3.Connection,
    rates: Mapping[str, Rate],
) -> None:
    """Every migrated group gives the same figures; raises `MigrationMismatch` otherwise."""
    from michelito.analysis import ledger, ledger_store  # noqa: PLC0415

    book = ledger_store.load(conn)
    for old_id, state in old.items():
        group = book.group(new_ids[old_id])
        if group is None:
            raise MigrationMismatch(f"shared group {old_id} was not migrated")
        after = ledger.group_state(group, book.me, rates)
        totals = {
            x.currency: (x.share, x.reimbursed, x.pending, x.written_off) for x in after.totals
        }
        counted = {e.entry.fingerprint: e.counted for e in after.entries}
        expected = {e.move.fingerprint: e.counted for e in state.expenses}
        excess = tuple(sorted(after.excess.items()))
        if (
            totals != state.totals()
            or counted != expected
            or excess != state.excess
            or after.uncounted != state.uncounted
            or any(x.i_owe for x in after.totals)
            or any(p.turned for p in after.payments)
        ):
            raise MigrationMismatch(f"shared group {old_id} would change its balances")


def legacy_snapshot(
    conn: sqlite3.Connection,
) -> tuple[list[LegacyGroup], dict[int, LegacyState], dict[str, Movement], dict[str, Rate]]:
    """The old groups, their states and what they were computed from (for `migrate` and the
    check script)."""
    from michelito.analysis import rates as rate_data  # noqa: PLC0415
    from michelito.analysis import spending  # noqa: PLC0415

    groups = load_legacy(conn)
    by_fp = {m.fingerprint: m for m in spending.load_all(conn)} if groups else {}
    rates = rate_data.load(conn)
    old = {g.id: state for g in groups if (state := legacy_state(g, by_fp, rates)) is not None}
    return groups, old, by_fp, rates


def migrate(conn: sqlite3.Connection) -> dict[int, int]:
    """Moves every shared group to the ledger; returns old link id -> new group id."""
    from michelito.analysis import ledger_store  # noqa: PLC0415

    groups, old, by_fp, rates = legacy_snapshot(conn)
    if not groups:
        return {}
    # Everything is in memory: the old rows go first, so their fingerprints can be linked again.
    shared = "SELECT id FROM links WHERE kind = 'shared'"
    conn.execute(f"DELETE FROM link_members WHERE link_id IN ({shared})")
    conn.execute(f"DELETE FROM link_manual WHERE link_id IN ({shared})")
    conn.execute("DELETE FROM links WHERE kind = 'shared'")
    new_ids: dict[int, int] = {}
    review = False
    for group in groups:
        new_ids[group.id], placeholders = convert_group(conn, group, old.get(group.id), by_fp)
        review = review or placeholders or bool(group.with_whom)
    check_balances(old, new_ids, conn, rates)
    if review:
        ledger_store.set_review_people(conn, True)
    return new_ids
