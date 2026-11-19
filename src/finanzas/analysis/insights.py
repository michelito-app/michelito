"""Análisis del mes guardados (insights): un texto en Markdown por mes.

Lo escribe Claude Code (o el usuario) a partir de `finanzas analisis` y se guarda con
`finanzas insight guardar` o desde Reportes. Va con la huella de los datos del dossier
(`dossier.data_hash`) para que la interfaz pueda decir "los datos cambiaron desde este
análisis", y con las cuentas analizadas (None: todas). Nada aquí hace commit.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass

TEXT_MAX = 4000
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


@dataclass(frozen=True)
class Insight:
    month: str
    text: str
    data_hash: str
    accounts: tuple[str, ...] | None  # cuentas analizadas; None: todas
    created_at: str
    updated_at: str


def clean_text(text: str) -> str:
    """El texto sin espacios de más al principio y al final; ValueError si queda vacío o largo."""
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("el análisis está vacío")
    if len(cleaned) > TEXT_MAX:
        raise ValueError(f"el análisis pasa de {TEXT_MAX} caracteres ({len(cleaned)})")
    return cleaned


def check_month(month: str) -> str:
    if not _MONTH.fullmatch(month):
        raise ValueError(f"mes inválido '{month}'; use AAAA-MM")
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
    """Guarda (o reemplaza) el análisis del mes; `created_at` queda el de la primera vez."""
    conn.execute(
        "INSERT INTO insights (month, text, data_hash, accounts, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(month) DO UPDATE SET "
        "text = excluded.text, data_hash = excluded.data_hash, accounts = excluded.accounts, "
        "updated_at = excluded.updated_at",
        (check_month(month), clean_text(text), data_hash, _accounts_text(accounts), now, now),
    )


def edit_text(conn: sqlite3.Connection, month: str, text: str, now: str) -> None:
    """Cambia solo el texto (la huella sigue siendo la de los datos analizados)."""
    cursor = conn.execute(
        "UPDATE insights SET text = ?, updated_at = ? WHERE month = ?",
        (clean_text(text), now, check_month(month)),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"no hay análisis de {month}")


def get(conn: sqlite3.Connection, month: str) -> Insight | None:
    row = conn.execute(
        "SELECT month, text, data_hash, accounts, created_at, updated_at FROM insights "
        "WHERE month = ?",
        (month,),
    ).fetchone()
    return None if row is None else _insight(row)


def list_all(conn: sqlite3.Connection) -> list[Insight]:
    """Del mes más reciente al más viejo."""
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
