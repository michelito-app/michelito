"""What a credit card billed, read from its statements the way the bank reads them.

The figure is a fact of the statements, not of the person's categories: each transaction goes to
one fixed group by its direction, MCC and text, and category corrections never move it (they
keep driving spending, `web.summary`). The period is whole statements: those whose closing date
falls in the months asked for. Portal printouts never count, since they do not cover a cycle.

Every group is a positive amount except `bank_fees`, which is net of fee reversals (a credit
with fee text). Nothing is subtracted for the reader: each bank decides what its target counts.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from michelito.analysis import categories
from michelito.analysis.rates import Rate, rate_for
from michelito.db import PRINTOUT_PARSERS
from michelito.parsers.common import CREDIT

PURCHASES = "purchases"
CASH_ADVANCES = "cash_advances"
BANK_FEES = "bank_fees"
REFUNDS = "refunds"
PAYMENTS = "payments"
GROUPS: tuple[str, ...] = (PURCHASES, CASH_ADVANCES, BANK_FEES, REFUNDS, PAYMENTS)
CARD_KIND = "credit_card"
MAX_RANGE_MONTHS = 36  # the longest range a request may ask for (keeps the work bounded)

_PRINTOUTS = ", ".join(f"'{name}'" for name in PRINTOUT_PARSERS)
_STATEMENTS = f"""
SELECT s.id, s.currency, s.period_end, s.previous_balance_cents, s.closing_balance_cents
FROM statements s
WHERE s.account_id = ? AND s.parser NOT IN ({_PRINTOUTS})
  AND substr(s.period_end, 1, 7) BETWEEN ? AND ?
ORDER BY s.period_end, s.currency, s.id
"""
_TRANSACTIONS = """
SELECT statement_id, direction, mcc, description, amount_cents
FROM transactions WHERE statement_id IN ({marks})
"""


class AccountNotFound(LookupError):
    """No account has that key."""


class NotACard(ValueError):
    """Billing is only measured on credit cards."""


def group_of(direction: str, mcc: str | None, description: str) -> str:
    """The fixed group of one statement transaction."""
    if direction == CREDIT:
        if mcc:
            return REFUNDS
        # Fee text wins over the refund prefix: "DEVOLUCION COMISION" gives back a fee.
        if categories.is_bank_fee_text(description):
            return BANK_FEES
        return REFUNDS if categories.is_refund_text(description) else PAYMENTS
    if mcc:
        return CASH_ADVANCES if categories.category_for_mcc(mcc) == categories.CASH else PURCHASES
    if categories.is_bank_fee_text(description):
        return BANK_FEES
    return CASH_ADVANCES if categories.is_cash_text(description) else PURCHASES


def signed_cents(direction: str, group: str, cents: int) -> int:
    """The amount as its group adds it: only a fee reversal subtracts."""
    return -cents if group == BANK_FEES and direction == CREDIT else cents


@dataclass(frozen=True)
class StatementBilling:
    statement_id: int
    period_end: date
    currency: str
    groups: Mapping[str, int]  # cents, by GROUPS
    previous_balance_cents: int | None
    closing_balance_cents: int | None
    rate: Rate | None  # of the closing month (or the closest earlier one); RD$ needs none

    @property
    def converted_dop(self) -> Mapping[str, int] | None:
        """The groups in RD$ at `rate`; None for US$ without a rate."""
        if self.currency != "USD":
            return self.groups
        if self.rate is None:
            return None
        return {g: round(cents * self.rate.value) for g, cents in self.groups.items()}


@dataclass(frozen=True)
class Billing:
    account_key: str
    from_month: str
    to_month: str
    statements: tuple[StatementBilling, ...]
    missing: tuple[str, ...]  # months of the range without any statement
    totals: Mapping[str, Mapping[str, int]] = field(default_factory=dict)  # currency -> groups

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def converted_dop(self) -> Mapping[str, int] | None:
        """Every statement in RD$; None when a US$ statement has no rate."""
        parts = [s.converted_dop for s in self.statements]
        if any(part is None for part in parts):
            return None
        return _sum(part for part in parts if part is not None)


def account_billing(
    conn: sqlite3.Connection,
    account_key: str,
    from_month: str,
    to_month: str,
    rates: Mapping[str, Rate],
) -> Billing:
    """The card's billing over the statements closing in `from_month..to_month` (YYYY-MM)."""
    account_id = require_card(conn, account_key)
    rows = conn.execute(_STATEMENTS, (account_id, from_month, to_month)).fetchall()
    groups = _groups_by_statement(conn, [r["id"] for r in rows])
    statements = tuple(_statement(row, groups.get(row["id"], {}), rates) for row in rows)
    covered = {s.period_end.isoformat()[:7] for s in statements}
    by_currency: dict[str, list[Mapping[str, int]]] = {}
    for s in statements:
        by_currency.setdefault(s.currency, []).append(s.groups)
    return Billing(
        account_key=account_key,
        from_month=from_month,
        to_month=to_month,
        statements=statements,
        missing=tuple(m for m in months_between(from_month, to_month) if m not in covered),
        totals={currency: _sum(parts) for currency, parts in sorted(by_currency.items())},
    )


def require_card(conn: sqlite3.Connection, account_key: str) -> int:
    """The id of the card account with that key; `AccountNotFound` or `NotACard` otherwise."""
    row = conn.execute("SELECT id, kind FROM accounts WHERE key = ?", (account_key,)).fetchone()
    if row is None:
        raise AccountNotFound(account_key)
    if row["kind"] != CARD_KIND:
        raise NotACard(account_key)
    return int(row["id"])


def months_between(first: str, last: str) -> list[str]:
    """Every YYYY-MM from `first` to `last`, both included."""
    year, month = int(first[:4]), int(first[5:7])
    found: list[str] = []
    while f"{year:04d}-{month:02d}" <= last:
        found.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return found


def _groups_by_statement(conn: sqlite3.Connection, ids: list[int]) -> dict[int, dict[str, int]]:
    found: dict[int, dict[str, int]] = {i: dict.fromkeys(GROUPS, 0) for i in ids}
    if not ids:
        return found
    query = _TRANSACTIONS.format(marks=", ".join("?" * len(ids)))
    for row in conn.execute(query, ids):
        group = group_of(row["direction"], row["mcc"], row["description"])
        found[row["statement_id"]][group] += signed_cents(
            row["direction"], group, row["amount_cents"]
        )
    return found


def _statement(
    row: sqlite3.Row, groups: Mapping[str, int], rates: Mapping[str, Rate]
) -> StatementBilling:
    closing = date.fromisoformat(row["period_end"])
    return StatementBilling(
        statement_id=row["id"],
        period_end=closing,
        currency=row["currency"],
        groups=dict(groups) or dict.fromkeys(GROUPS, 0),
        previous_balance_cents=row["previous_balance_cents"],
        closing_balance_cents=row["closing_balance_cents"],
        rate=rate_for(rates, closing.isoformat()[:7]) if row["currency"] == "USD" else None,
    )


def _sum(parts: Iterable[Mapping[str, int]]) -> dict[str, int]:
    total = dict.fromkeys(GROUPS, 0)
    for part in parts:
        for group, cents in part.items():
            total[group] += cents
    return total


def span(first: str, last: str) -> int:
    """How many months `first..last` covers, both included (0 or less when reversed)."""
    return (int(last[:4]) - int(first[:4])) * 12 + int(last[5:7]) - int(first[5:7]) + 1


def months_back(month: str, count: int) -> str:
    """The YYYY-MM `count` months before `month`."""
    index = int(month[:4]) * 12 + int(month[5:7]) - 1 - count
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def latest_month(conn: sqlite3.Connection, account_key: str) -> str | None:
    """The closing month of the card's newest bank statement, if it has any."""
    row = conn.execute(
        f"SELECT max(substr(s.period_end, 1, 7)) FROM statements s "
        f"JOIN accounts a ON a.id = s.account_id "
        f"WHERE a.key = ? AND s.parser NOT IN ({_PRINTOUTS})",
        (account_key,),
    ).fetchone()
    return None if row is None or row[0] is None else str(row[0])
