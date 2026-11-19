"""Budget caps in the database (`budget_caps`, schema 17; the logic lives in `budget`).

With no rows, the budget is not active. Nothing here commits: the caller wraps the write in
`with conn:` (and in `changelog.track`, for the change log).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from michelito.analysis.budget import CAP_MAX, Cap
from michelito.i18n import t


class BudgetError(ValueError):
    """Invalid request on the budget (422)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _cents(value: Decimal | None) -> int | None:
    return None if value is None else int(value * 100)


def _amount(cents: int | None) -> Decimal | None:
    return None if cents is None else Decimal(cents) / 100


def load(conn: sqlite3.Connection) -> dict[int, Cap]:
    rows = conn.execute("SELECT category_id, cap_cents, manual, basis_cents FROM budget_caps")
    return {int(r[0]): Cap(int(r[0]), _amount(r[1]), bool(r[2]), _amount(r[3])) for r in rows}


def is_active(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM budget_caps LIMIT 1").fetchone() is not None


def activate(conn: sqlite3.Connection, caps: Iterable[Cap]) -> int:
    """Creates the initial caps; BudgetError if already active. Returns how many it created."""
    if is_active(conn):
        raise BudgetError(t("analysis.budget_store.already_active"))
    now = _now()
    rows = [(c.category_id, _cents(c.cap), int(c.manual), _cents(c.basis), now, now) for c in caps]
    conn.executemany(
        "INSERT INTO budget_caps (category_id, cap_cents, manual, basis_cents, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def check_cap(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if value < 0 or value > CAP_MAX:
        raise BudgetError(t("analysis.budget_store.cap_range"))
    if value != value.quantize(Decimal(1)):
        raise BudgetError(t("analysis.budget_store.cap_whole"))
    return value


def set_cap(conn: sqlite3.Connection, category_id: int, cap: Decimal | None) -> None:
    """A cap set by hand (None: "no budget"): it stays fixed, with no "usual changed" warnings."""
    value = check_cap(cap)
    now = _now()
    conn.execute(
        "INSERT INTO budget_caps (category_id, cap_cents, manual, basis_cents, created_at, "
        "updated_at) VALUES (?, ?, 1, NULL, ?, ?) ON CONFLICT(category_id) DO UPDATE SET "
        "cap_cents = excluded.cap_cents, manual = 1, updated_at = excluded.updated_at",
        (category_id, _cents(value), now, now),
    )


def resolve_warning(
    conn: sqlite3.Connection, category_id: int, usual: Decimal, accept: bool
) -> None:
    """Accepting sets the cap to the rounded usual amount (0: "no budget"); ignoring only marks
    it as seen. Both leave `basis` at that value. LookupError if the category has no row."""
    cap = None if usual <= 0 else usual
    if accept:
        cursor = conn.execute(
            "UPDATE budget_caps SET cap_cents = ?, basis_cents = ?, updated_at = ? "
            "WHERE category_id = ? AND manual = 0",
            (_cents(cap), _cents(usual), _now(), category_id),
        )
    else:
        cursor = conn.execute(
            "UPDATE budget_caps SET basis_cents = ?, updated_at = ? "
            "WHERE category_id = ? AND manual = 0",
            (_cents(usual), _now(), category_id),
        )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.budget_store.no_untouched_cap"))
