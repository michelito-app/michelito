"""Reserves in the database (schema 17; the logic is in `reserves`).

A reserve is a `'reserve'` link in `links` (its plan in `reserve_cents`, `category_id`,
`due_month`, `every_months`, `multiple`, `source` and the name in `name`) and its expenses are
`'reserved'` members in `link_members`, by fingerprint like the other links: the unique index on
`link_members.fingerprint` ensures a fingerprint is in only one link (a reserve, a group, an
investment...). The link does **not** change the expense's category: it only takes it out of the
cap. Dismissed suggestions are stored by their key in `reserve_dismissals`.

Nothing here commits: the caller wraps the write in `with conn:` (and in `changelog.track`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from michelito.analysis import catalog
from michelito.analysis.links import AlreadyLinked
from michelito.analysis.reserves import (
    AMOUNT_MAX,
    EVERY_CHOICES,
    NAME_MAX,
    Reserve,
    ReserveError,
    check_month,
)
from michelito.i18n import t

_UNSET = object()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def load(conn: sqlite3.Connection) -> list[Reserve]:
    members: dict[int, list[str]] = {}
    for row in conn.execute(
        "SELECT m.link_id, m.fingerprint FROM link_members m JOIN links l ON l.id = m.link_id "
        "WHERE l.kind = 'reserve' ORDER BY m.added_at, m.rowid"
    ):
        members.setdefault(int(row[0]), []).append(str(row[1]))
    found = []
    for row in conn.execute("SELECT * FROM links WHERE kind = 'reserve' ORDER BY id"):
        found.append(
            Reserve(
                id=int(row["id"]),
                name=row["name"] or t("analysis.reserve_store.default_name", id=row["id"]),
                amount=Decimal(row["reserve_cents"] or 0) / 100,
                category_id=int(row["category_id"] or 0),
                due_month=row["due_month"] or "",
                every_months=row["every_months"],
                multiple=bool(row["multiple"]),
                members=tuple(members.get(int(row["id"]), ())),
                created_month=row["start_month"] or str(row["created_at"])[:7],
                source=row["source"],
            )
        )
    return found


def get(conn: sqlite3.Connection, reserve_id: int) -> Reserve:
    found = next((r for r in load(conn) if r.id == reserve_id), None)
    if found is None:
        raise LookupError(t("analysis.reserve_store.unknown", id=reserve_id))
    return found


def _name(value: str) -> str:
    text = " ".join((value or "").split())
    if not text:
        raise ReserveError(t("analysis.reserve_store.name_required"))
    if len(text) > NAME_MAX:
        raise ReserveError(t("analysis.reserve_store.name_too_long", max=NAME_MAX))
    return text


def _amount_cents(value: Decimal) -> int:
    if value <= 0 or value > AMOUNT_MAX:
        raise ReserveError(t("analysis.reserve_store.amount_range"))
    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise ReserveError(t("analysis.cash_box.amount_decimals"))
    return int(scaled)


def _every(value: int | None) -> int | None:
    if value is not None and value not in EVERY_CHOICES:
        raise ReserveError(t("analysis.reserve_store.every_choices"))
    return value


def _category(conn: sqlite3.Connection, category_id: int) -> int:
    found = catalog.load(conn).by_id(category_id)
    if found is None:
        raise ReserveError(t("analysis.reserve_store.unknown_category"))
    if found.kind != "expense":
        raise ReserveError(t("analysis.reserve_store.expense_category"))
    catalog.check_choosable(found)
    return category_id


def create(
    conn: sqlite3.Connection,
    *,
    name: str,
    amount: Decimal,
    category_id: int,
    due_month: str,
    every_months: int | None,
    multiple: bool = False,
    source: str | None = None,
    start_month: str | None = None,
) -> int:
    """A new reserve. `start_month`: the month saving starts from (today's; by default, the
    clock's), which sets the contribution of a one-time reserve."""
    now = _now()
    cursor = conn.execute(
        "INSERT INTO links (kind, name, reserve_cents, category_id, due_month, every_months, "
        "multiple, source, start_month, created_at, updated_at) "
        "VALUES ('reserve', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _name(name),
            _amount_cents(amount),
            _category(conn, category_id),
            check_month(due_month),
            _every(every_months),
            int(multiple),
            (source or "")[:200] or None,
            check_month(start_month or now[:7]),
            now,
            now,
        ),
    )
    return int(cursor.lastrowid or 0)


def update(
    conn: sqlite3.Connection,
    reserve_id: int,
    *,
    name: str | None = None,
    amount: Decimal | None = None,
    category_id: int | None = None,
    due_month: str | None = None,
    every_months: int | None | object = _UNSET,
    multiple: bool | None = None,
) -> None:
    """Changes what is given (None or absent: left alone; `every_months=None`: only once)."""
    get(conn, reserve_id)
    sets: list[tuple[str, object]] = []
    if name is not None:
        sets.append(("name", _name(name)))
    if amount is not None:
        sets.append(("reserve_cents", _amount_cents(amount)))
    if category_id is not None:
        sets.append(("category_id", _category(conn, category_id)))
    if due_month is not None:
        sets.append(("due_month", check_month(due_month)))
    if every_months is not _UNSET:
        sets.append(("every_months", _every(every_months)))  # type: ignore[arg-type]
    if multiple is not None:
        sets.append(("multiple", int(multiple)))
    if not sets:
        return
    columns = ", ".join(f"{column} = ?" for column, _ in sets)
    conn.execute(
        f"UPDATE links SET {columns}, updated_at = ? WHERE id = ?",
        (*(value for _, value in sets), _now(), reserve_id),
    )


def delete(conn: sqlite3.Connection, reserve_id: int) -> None:
    """Deletes the reserve; its expenses go back to their category cap (members cascade)."""
    get(conn, reserve_id)
    conn.execute("DELETE FROM links WHERE id = ? AND kind = 'reserve'", (reserve_id,))


def add_member(conn: sqlite3.Connection, reserve_id: int, fingerprint: str) -> None:
    """Links the expense (the caller checks it is an expense). `AlreadyLinked` if it is already in
    a link (this reserve included)."""
    get(conn, reserve_id)
    row = conn.execute(
        "SELECT 1 FROM link_members WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    if row is not None:
        raise AlreadyLinked(t("analysis.links.already_linked"))
    conn.execute(
        "INSERT INTO link_members (link_id, fingerprint, role, added_at) "
        "VALUES (?, ?, 'reserved', ?)",
        (reserve_id, fingerprint, _now()),
    )
    conn.execute("UPDATE links SET updated_at = ? WHERE id = ?", (_now(), reserve_id))


def remove_member(conn: sqlite3.Connection, reserve_id: int, fingerprint: str) -> None:
    """Removes the expense from the reserve: it goes back to its category cap."""
    cursor = conn.execute(
        "DELETE FROM link_members WHERE link_id = ? AND fingerprint = ? AND role = 'reserved'",
        (reserve_id, fingerprint),
    )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.reserve_store.not_member"))
    conn.execute("UPDATE links SET updated_at = ? WHERE id = ?", (_now(), reserve_id))


def dismissed(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(str(r[0]) for r in conn.execute("SELECT key FROM reserve_dismissals"))


def dismiss(conn: sqlite3.Connection, key: str) -> None:
    text = key.strip()
    if not 1 <= len(text) <= 200:
        raise ReserveError(t("analysis.reserve_store.invalid_key"))
    conn.execute(
        "INSERT INTO reserve_dismissals (key, dismissed_at) VALUES (?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        (text, _now()),
    )


def uses_category(conn: sqlite3.Connection, category_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM links WHERE kind = 'reserve' AND category_id = ? LIMIT 1", (category_id,)
    ).fetchone()
    return row is not None


def reassign_category(conn: sqlite3.Connection, old: int, new: int) -> None:
    conn.execute(
        "UPDATE links SET category_id = ? WHERE kind = 'reserve' AND category_id = ?", (new, old)
    )


def fingerprints(reserves: Iterable[Reserve]) -> dict[str, int]:
    """Fingerprint -> the reserve covering it."""
    return {fp: r.id for r in reserves for fp in r.members}
