"""Saved monthly analyses (insights): one Markdown text per month.

Claude Code (or the user) writes it from `michelito analysis` and it is saved with
`michelito insight save` or from Reports. It carries the hash of the dossier data
(`dossier.data_hash`) so the interface can say "the data changed since this analysis", and
the analyzed accounts (None: all of them). Nothing here commits, except `is_fresh` (it updates
the hash of an insight saved before the English rename).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Collection
from dataclasses import dataclass

from michelito.i18n import t

TEXT_MAX = 4000
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


@dataclass(frozen=True)
class Insight:
    month: str
    text: str
    data_hash: str
    accounts: tuple[str, ...] | None  # analyzed accounts; None: all of them
    created_at: str
    updated_at: str


def clean_text(text: str) -> str:
    """The text without leading and trailing whitespace; ValueError if empty or too long."""
    cleaned = text.strip()
    if not cleaned:
        raise ValueError(t("analysis.insights.empty"))
    if len(cleaned) > TEXT_MAX:
        raise ValueError(t("analysis.insights.too_long", max=TEXT_MAX, length=len(cleaned)))
    return cleaned


def check_month(month: str) -> str:
    if not _MONTH.fullmatch(month):
        raise ValueError(t("analysis.insights.invalid_month", month=month))
    return month


def _accounts_text(accounts: Collection[str] | None) -> str | None:
    return None if not accounts else ",".join(sorted(set(accounts)))


def save(
    conn: sqlite3.Connection,
    month: str,
    text: str,
    data_hash: str,
    accounts: Collection[str] | None,
    now: str,
) -> None:
    """Save (or replace) the month's analysis; `created_at` stays the first one."""
    conn.execute(
        "INSERT INTO insights (month, text, data_hash, accounts, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(month) DO UPDATE SET "
        "text = excluded.text, data_hash = excluded.data_hash, accounts = excluded.accounts, "
        "updated_at = excluded.updated_at",
        (check_month(month), clean_text(text), data_hash, _accounts_text(accounts), now, now),
    )


def edit_text(conn: sqlite3.Connection, month: str, text: str, now: str) -> None:
    """Change only the text (the hash is still that of the analyzed data)."""
    cursor = conn.execute(
        "UPDATE insights SET text = ?, updated_at = ? WHERE month = ?",
        (clean_text(text), now, check_month(month)),
    )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.insights.missing", month=month))


def is_fresh(
    conn: sqlite3.Connection, found: Insight, data_hash: str, legacy_hash: Callable[[], str]
) -> bool:
    """Whether the data is still what `found` analyzed: its hash is today's dossier hash
    (`data_hash`) or, for an insight saved before the English rename, the hash that release
    computes for today's data (`legacy_hash`, only computed when needed). In that case the stored
    hash is replaced by `data_hash` (and committed), so the old one is checked only once."""
    if found.data_hash == data_hash:
        return True
    if found.data_hash != legacy_hash():
        return False
    with conn:
        conn.execute(
            "UPDATE insights SET data_hash = ? WHERE month = ? AND data_hash = ?",
            (data_hash, found.month, found.data_hash),
        )
    return True


def get(conn: sqlite3.Connection, month: str) -> Insight | None:
    row = conn.execute(
        "SELECT month, text, data_hash, accounts, created_at, updated_at FROM insights "
        "WHERE month = ?",
        (month,),
    ).fetchone()
    return None if row is None else _insight(row)


def list_all(conn: sqlite3.Connection) -> list[Insight]:
    """From the most recent month to the oldest."""
    rows = conn.execute(
        "SELECT month, text, data_hash, accounts, created_at, updated_at FROM insights "
        "ORDER BY month DESC"
    )
    return [_insight(row) for row in rows]


def delete(conn: sqlite3.Connection, month: str) -> bool:
    return conn.execute("DELETE FROM insights WHERE month = ?", (month,)).rowcount > 0


def _insight(row: sqlite3.Row) -> Insight:
    accounts = row["accounts"]
    return Insight(
        month=row["month"],
        text=row["text"],
        data_hash=row["data_hash"],
        accounts=None if not accounts else tuple(accounts.split(",")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
