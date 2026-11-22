"""Manual marks on recurring charges, and merchant unions.

Each series (per currency) can be confirmed, dismissed or cancelled, carry how many installments
are left and, when chosen by hand ("Is recurring..."), its cadence and group. The key is the
series key (`recurring.series_key`): a merchant, or `provider:<id>` for one from the list.
`status_on` and `installments_on` are the dates of each one's latest mark: charges after a
cancellation and installments already paid are counted from them. They are kept apart so that
noting installments does not move the cancellation date.

A mark saved under the key of a merchant that today goes in a bigger series (a provider or a
manual union) is neither moved nor deleted: `for_series` hands it to that series while the
series has no mark of its own, and it applies on its own again if the merchant is separated.

Unions (`recurring_unions`) go per merchant, in all its currencies: merchant -> key of the
series it joins (another merchant or a provider). Joining a merchant with itself separates it
from its listed provider.

As in `corrections`, nothing here commits: the caller wraps the write in `with conn:`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal, get_args

from michelito.analysis.recurring import GROUPS, Cadence
from michelito.i18n import t

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

MarkStatus = Literal["confirmed", "dismissed", "cancelled"]
_STATUSES = frozenset(get_args(MarkStatus))
_CADENCES = frozenset(get_args(Cadence))
_CURRENCIES = frozenset({"DOP", "USD"})
# Column -> its date column (None: has none). The names go into the SQL: a closed list.
_COLUMNS: dict[str, str | None] = {
    "status": "status_on",
    "installments_left": "installments_on",
    "cadence": None,
    "group_key": None,
}
_EMPTY = " AND ".join(f"{c} IS NULL" for c in _COLUMNS)
KEY_MAX = 200


@dataclass(frozen=True)
class Mark:
    status: MarkStatus | None
    installments_left: int | None
    status_on: date | None
    installments_on: date | None
    cadence: Cadence | None = None  # chosen by hand
    group: str | None = None  # `recurring.GROUPS` key chosen by hand


def load(conn: sqlite3.Connection) -> dict[tuple[str, str], Mark]:
    rows = conn.execute(
        "SELECT merchant, currency, status, installments_left, status_on, installments_on, "
        "cadence, group_key FROM recurring_marks"
    )
    return {
        (row["merchant"], row["currency"]): Mark(
            row["status"],
            row["installments_left"],
            _day(row["status_on"]),
            _day(row["installments_on"]),
            row["cadence"],
            row["group_key"],
        )
        for row in rows
    }


def load_for(
    conn: sqlite3.Connection, movements: Iterable[Movement]
) -> dict[tuple[str, str], Mark]:
    """The marks, with those of previous bank keys moved to the current one (see below)."""
    return with_previous_keys(load(conn), movements)


def with_previous_keys(
    marks: Mapping[tuple[str, str], Mark], movements: Iterable[Movement]
) -> dict[tuple[str, str], Mark]:
    """Moves to a bank movement's current key the mark saved under its previous key
    (`categories.previous_bank_key`), if the current one has none.

    The old mark leaves its key unless some movement still has that key: so no marked recurring
    item is left without charges. Card keys never change.
    """
    items = list(movements)
    in_use = {(m.merchant, m.currency) for m in items}
    resolved = dict(marks)
    moved: set[tuple[str, str]] = set()
    for item in items:
        if item.previous_bank_key is None:
            continue  # card (or a key that is not the bank one)
        old = (item.previous_bank_key, item.currency)
        new = (item.merchant, item.currency)
        if old == new or old not in marks:
            continue
        if new not in marks:
            resolved[new] = marks[old]
        moved.add(old)
    for old in moved - in_use:
        resolved.pop(old, None)
    return resolved


def for_series(
    marks: Mapping[tuple[str, str], Mark], members: Mapping[str, Collection[str]]
) -> dict[tuple[str, str], Mark]:
    """Marks per series: the series' own when it has its own row (even if empty: an explicit
    "no mark"); otherwise its merchants' marks combined (`merge`). Those of a merchant that goes
    in another series leave its key (no separate recurring item is left with that merchant).
    Nothing is deleted from the database: this is only the read. The first write on the series
    first copies what it inherits into its row (`materialize`), so the merge is field by field:
    what is changed wins and the rest comes from the merchants.

    `members`: series key -> its merchants (`recurring.members`)."""
    resolved = dict(marks)
    absorbed: set[str] = set()
    for key, names in members.items():
        others = [name for name in names if name != key]
        if not others:
            continue
        absorbed.update(others)
        currencies = {cur for (name, cur) in marks if name in others}
        for currency in currencies:
            if (key, currency) in marks:
                continue
            found = [marks[(name, currency)] for name in others if (name, currency) in marks]
            resolved[(key, currency)] = merge(found)
    own = set(members)
    for name, currency in list(resolved):
        if name in absorbed and name not in own:
            resolved.pop((name, currency))
    return resolved


def merge(found: Iterable[Mark]) -> Mark:
    """Several marks of merchants of one series: the status of the latest marked, the
    installments of the latest noted, and the cadence and group of the first that has them
    (in that same order)."""
    items = list(found)
    by_status = sorted(
        (m for m in items if m.status is not None), key=lambda m: m.status_on or date.min
    )
    by_left = sorted(
        (m for m in items if m.installments_left is not None),
        key=lambda m: m.installments_on or date.min,
    )
    base = Mark(None, None, None, None)
    if by_status:
        base = replace(base, status=by_status[-1].status, status_on=by_status[-1].status_on)
    if by_left:
        latest = by_left[-1]
        base = replace(
            base, installments_left=latest.installments_left, installments_on=latest.installments_on
        )
    ordered = [*reversed(by_status), *items]
    cadence = next((m.cadence for m in ordered if m.cadence is not None), None)
    group = next((m.group for m in ordered if m.group is not None), None)
    return replace(base, cadence=cadence, group=group)


def set_status(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    status: MarkStatus | None,
    today: date,
    *,
    keep: bool = False,
) -> None:
    if status is not None and status not in _STATUSES:
        raise ValueError(t("analysis.recurring_marks.unknown_status", status=status))
    _write(conn, merchant, currency, "status", status, today, keep)


def set_installments(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    left: int | None,
    today: date,
    *,
    keep: bool = False,
) -> None:
    if left is not None and left < 0:
        raise ValueError(t("analysis.recurring_marks.negative_installments", left=left))
    _write(conn, merchant, currency, "installments_left", left, today, keep)


def set_cadence(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    cadence: Cadence | None,
    today: date,
    *,
    keep: bool = False,
) -> None:
    if cadence is not None and cadence not in _CADENCES:
        raise ValueError(t("analysis.recurring_marks.unknown_cadence", cadence=cadence))
    _write(conn, merchant, currency, "cadence", cadence, today, keep)


def set_group(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    group: str | None,
    today: date,
    *,
    keep: bool = False,
) -> None:
    if group is not None and group not in GROUPS:
        raise ValueError(t("analysis.recurring_marks.unknown_group", group=group))
    _write(conn, merchant, currency, "group_key", group, today, keep)


def _write(
    conn: sqlite3.Connection,
    merchant: str,
    currency: str,
    column: str,
    value: str | int | None,
    today: date,
    keep: bool = False,
) -> None:
    """`keep`: a row left empty is not deleted (it is the explicit "no mark" of a series that,
    without a row, would inherit its merchants' marks)."""
    if column not in _COLUMNS:  # the names go into the SQL: a closed list
        raise ValueError(f"unknown column: {column}")
    if currency not in _CURRENCIES:
        raise ValueError(t("analysis.recurring_marks.unknown_currency", currency=currency))
    if not merchant or len(merchant) > KEY_MAX:
        raise ValueError(t("analysis.recurring_marks.invalid_merchant"))
    key = (merchant, currency)
    current = conn.execute(
        f"SELECT {column} FROM recurring_marks WHERE merchant = ? AND currency = ?", key
    ).fetchone()
    if current is None and value is None:
        return
    if current is not None and current[column] == value:
        return  # same value: keep the date
    day_column = _COLUMNS[column]
    names = [column] if day_column is None else [column, day_column]
    values: list[str | int | None] = [value]
    if day_column is not None:
        values.append(None if value is None else today.isoformat())
    updates = ", ".join(f"{n} = excluded.{n}" for n in [*names, "updated_at"])
    conn.execute(
        f"INSERT INTO recurring_marks (merchant, currency, {', '.join(names)}, updated_at) "
        f"VALUES (?, ?, {', '.join('?' * len(names))}, ?) ON CONFLICT(merchant, currency) "
        f"DO UPDATE SET {updates}",
        (*key, *values, _now()),
    )
    if not keep:
        conn.execute(
            f"DELETE FROM recurring_marks WHERE merchant = ? AND currency = ? AND {_EMPTY}", key
        )


def inherited(
    marks: Mapping[tuple[str, str], Mark], key: str, currency: str, names: Collection[str]
) -> Mark | None:
    """What series `key` inherits from its merchants `names` (excluding itself), or None."""
    found = [marks[(n, currency)] for n in names if n != key and (n, currency) in marks]
    return merge(found) if found else None


def materialize(conn: sqlite3.Connection, key: str, currency: str, mark: Mark) -> None:
    """Saves the inherited mark in the series' own row (before changing it: so what is not
    touched is kept, dates included). Does nothing if the series already has a row."""
    if currency not in _CURRENCIES:
        raise ValueError(t("analysis.recurring_marks.unknown_currency", currency=currency))
    conn.execute(
        "INSERT INTO recurring_marks (merchant, currency, status, installments_left, status_on, "
        "installments_on, cadence, group_key, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(merchant, currency) DO NOTHING",
        (
            key,
            currency,
            mark.status,
            mark.installments_left,
            None if mark.status_on is None else mark.status_on.isoformat(),
            None if mark.installments_on is None else mark.installments_on.isoformat(),
            mark.cadence,
            mark.group,
            _now(),
        ),
    )


def load_unions(conn: sqlite3.Connection) -> dict[str, str]:
    """Merchant -> the key of the series it was joined to by hand."""
    return {row[0]: row[1] for row in conn.execute("SELECT merchant, target FROM recurring_unions")}


def set_union(conn: sqlite3.Connection, merchant: str, target: str | None) -> None:
    """Joins the merchant to series `target` (or to itself: separates it); None deletes it."""
    for text in (merchant, target or "x"):
        if not text or len(text) > KEY_MAX:
            raise ValueError(t("analysis.recurring_marks.invalid_merchant"))
    if target is None:
        conn.execute("DELETE FROM recurring_unions WHERE merchant = ?", (merchant,))
        return
    conn.execute(
        "INSERT INTO recurring_unions (merchant, target, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(merchant) DO UPDATE SET target = excluded.target, "
        "updated_at = excluded.updated_at WHERE target != excluded.target",
        (merchant, target, _now()),
    )


def _day(text: str | None) -> date | None:
    return None if text is None else date.fromisoformat(text)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
