"""Display name and coverage of each stored account."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from michelito.i18n import t

_CREDIT_CARD = "credit_card"
BANK_KINDS = ("savings", "checking")
# The cash box (`analysis.cash_box`): a manual account with no statements; it is created in
# `accounts` the first time it is used. A `kind` other than the banks': not a bank account.
CASH_KIND = "cash"
CASH_BOX_KEY = "manual:cash-box"
CASH_BOX_NAME = t("analysis.accounts.cash_box_name")
# Group movements (`spending.group_movements`): your share of a shared expense with no transaction
# of yours. Not a stored account: it has no statements and is not in `accounts`.
GROUP_ACCOUNT = "ledger:shared"
GROUP_ACCOUNT_NAME = t("analysis.accounts.group_account_name")


def account_label(labels: Mapping[str, str], key: str) -> str:
    """The account's display name (the group movements' too); the key if unknown."""
    if key == GROUP_ACCOUNT:
        return GROUP_ACCOUNT_NAME
    return labels.get(key, key)


# One row per account; for cards, the most recent card gives the product and last 4 digits.
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
    through: date | None  # most recent stored statement cutoff of the account


def account_infos(conn: sqlite3.Connection) -> list[AccountInfo]:
    """Accounts with their display name; credit cards first, then by name."""
    infos = [_info(row) for row in conn.execute(_ACCOUNTS)]
    return sorted(infos, key=lambda info: (info.kind != _CREDIT_CARD, info.label))


def _info(row: sqlite3.Row) -> AccountInfo:
    if row["kind"] == _CREDIT_CARD and row["product"] and row["last4"]:
        label = f"{row['product']} ···{row['last4']}"
    else:
        label = row["name"]
    through = date.fromisoformat(row["through"]) if row["through"] else None
    return AccountInfo(key=row["key"], kind=row["kind"], label=label, through=through)
