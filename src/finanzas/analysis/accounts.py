"""Nombre visible y cobertura de cada cuenta guardada."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

_CREDIT_CARD = "credit_card"
BANK_KINDS = ("savings", "checking")
# La caja fuerte (`analysis.cash_box`): una cuenta manual, sin estados; se crea en `accounts` la
# primera vez que se usa. Otro `kind` que el de los bancos: no es una cuenta bancaria.
CASH_KIND = "cash"
CASH_BOX_KEY = "manual:caja-fuerte"
CASH_BOX_NAME = "Caja fuerte"

# Una fila por cuenta; en las tarjetas, el plástico más reciente da producto y últimos 4.
_ACCOUNTS = """
SELECT a.key, a.kind, a.name,
       (SELECT c.product FROM cards c WHERE c.account_id = a.id
        ORDER BY c.last_seen DESC, c.id DESC LIMIT 1) AS product,
       (SELECT c.last4 FROM cards c WHERE c.account_id = a.id
        ORDER BY c.last_seen DESC, c.id DESC LIMIT 1) AS last4,
       (SELECT MAX(s.period_end) FROM statements s WHERE s.account_id = a.id) AS through
FROM accounts a
"""


@dataclass(frozen=True)
class AccountInfo:
    key: str
    kind: str
    label: str
    through: date | None  # corte más reciente guardado de la cuenta


def account_infos(conn: sqlite3.Connection) -> list[AccountInfo]:
    """Cuentas con su nombre visible; las tarjetas de crédito primero, luego por nombre."""
    infos = [_info(row) for row in conn.execute(_ACCOUNTS)]
    return sorted(infos, key=lambda info: (info.kind != _CREDIT_CARD, info.label))


def _info(row: sqlite3.Row) -> AccountInfo:
    if row["kind"] == _CREDIT_CARD and row["product"] and row["last4"]:
        label = f"{row['product']} ···{row['last4']}"
    else:
        label = row["name"]
    through = date.fromisoformat(row["through"]) if row["through"] else None
    return AccountInfo(key=row["key"], kind=row["kind"], label=label, through=through)
