"""Accounts queries: each account with its statements by closing date."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from michelito.analysis.accounts import account_infos
from michelito.analysis.interest import StatementMoney, statement_money
from michelito.analysis.report import money
from michelito.db import PRINTOUT_PARSERS
from michelito.i18n import t
from michelito.web.summary import ACTIVE_DAYS

MISSING_STATEMENT_DAYS = 35
STATEMENT_HISTORY = 12  # closing dates shown per account
DUE_WINDOW_DAYS = 8  # days ahead to warn about a due date

_STATEMENTS = """
SELECT s.id AS statement_id, a.key AS account_key, a.kind AS account_kind,
       s.card_id, s.parser, s.currency, s.period_start, s.period_end, s.due_date,
       s.closing_balance_cents, s.minimum_payment_cents,
       s.printed_debits_cents, s.printed_credits_cents
FROM statements s JOIN accounts a ON a.id = s.account_id
ORDER BY s.period_end DESC, s.id
"""


@dataclass(frozen=True)
class StatementLine:
    statement_id: int
    period_start: date | None
    period_end: date
    currency: str
    charges: Decimal | None
    payments: Decimal | None
    balance: Decimal | None
    due_date: date | None
    minimum_payment: Decimal | None
    paid_full: bool | None  # None: no next statement or no balance to pay
    left_over: Decimal | None  # what was left when not paid in full
    paid_late: bool  # the balance was covered, but after the due date
    next_interest: Decimal  # interest of the next statement (0 if none)
    printout: bool = False  # portal printout, not a statement: no closing date


@dataclass(frozen=True)
class DuePayment:
    """What to pay before the due date to avoid interest."""

    key: str
    label: str
    due_date: date
    amounts: list[tuple[str, Decimal]]  # closing balance by currency, DOP first
    minimums: list[tuple[str, Decimal]]


_MONTHS = tuple(t(f"web.account.month_{number:02d}") for number in range(1, 13))


def due_text(payment: DuePayment) -> str:
    """Warning: what to pay, and by when, to avoid interest."""
    amounts = t("web.account.and").join(
        money(value, currency) for currency, value in payment.amounts
    )
    due = payment.due_date
    return t(
        "web.account.due",
        label=payment.label,
        amounts=amounts,
        day=due.day,
        month=_MONTHS[due.month - 1],
    )


@dataclass(frozen=True)
class AccountView:
    key: str
    kind: str
    label: str
    cut_day: int | None
    currencies: list[str]
    latest: list[
        StatementLine
    ]  # one statement per currency, of the latest closing date (no printouts)
    missing_statement: bool
    statements: list[StatementLine]  # newest to oldest, printouts included
    to_pay: DuePayment | None


def account_views(conn: sqlite3.Connection, today: date) -> list[AccountView]:
    """One view per account, in `account_infos` order."""
    rows_by_account = _lines_by_account(conn)
    cuts_by_account = {
        key: [line for line in lines if not line.printout] for key, lines in rows_by_account.items()
    }
    newest_overall = max(
        (cuts[0].period_end for cuts in cuts_by_account.values() if cuts), default=None
    )
    views = []
    for info in account_infos(conn):
        lines = rows_by_account.get(info.key, [])
        latest = _latest(cuts_by_account.get(info.key, []))
        newest = latest[0].period_end if latest else None
        views.append(
            AccountView(
                key=info.key,
                kind=info.kind,
                label=info.label,
                cut_day=newest.day if newest else None,
                currencies=sorted({line.currency for line in lines}, key=_dop_first),
                latest=latest,
                missing_statement=_is_missing(newest, newest_overall, today),
                statements=_history(lines),
                to_pay=_to_pay(info.key, info.label, latest)
                if info.kind == "credit_card"
                else None,
            )
        )
    return views


def upcoming_payments(
    views: Sequence[AccountView], today: date, window: int = DUE_WINDOW_DAYS
) -> list[DuePayment]:
    """Pending payments whose due date falls between today and today + `window` days, by date."""
    limit = today + timedelta(days=window)
    due = [v.to_pay for v in views if v.to_pay is not None]
    return sorted((p for p in due if today <= p.due_date <= limit), key=lambda p: p.due_date)


def _to_pay(key: str, label: str, latest: list[StatementLine]) -> DuePayment | None:
    owed = [line for line in latest if line.balance is not None and line.balance > 0]
    dues = [line.due_date for line in owed if line.due_date is not None]
    if not owed or not dues:
        return None
    return DuePayment(
        key=key,
        label=label,
        due_date=min(dues),
        amounts=[(line.currency, line.balance) for line in owed if line.balance is not None],
        minimums=[
            (line.currency, line.minimum_payment)
            for line in owed
            if line.minimum_payment is not None
        ],
    )


def _is_missing(newest: date | None, newest_overall: date | None, today: date) -> bool:
    """A statement is missing only for active accounts: ones no longer received don't count."""
    if newest is None or newest_overall is None:
        return False
    if newest_overall - newest > timedelta(days=ACTIVE_DAYS):
        return False
    return today > newest + timedelta(days=MISSING_STATEMENT_DAYS)


def _dop_first(currency: str) -> tuple[bool, str]:
    return (currency != "DOP", currency)


def _lines_by_account(conn: sqlite3.Connection) -> dict[str, list[StatementLine]]:
    """Each account's lines, newest to oldest, with period start and verdict.

    Portal printouts stay out of the chain of closing dates: their period is their own.
    """
    rows = conn.execute(_STATEMENTS).fetchall()
    per_statement = statement_money(conn)
    # The previous/next closing is looked up by account, card and currency (order is descending).
    previous: dict[tuple[str, int | None, str], sqlite3.Row] = {}
    next_of: dict[int, int] = {}
    starts: dict[int, date | None] = {}
    for row in reversed(rows):
        if row["parser"] in PRINTOUT_PARSERS:
            starts[row["statement_id"]] = date.fromisoformat(row["period_start"])
            continue
        group = (row["account_key"], row["card_id"], row["currency"])
        before = previous.get(group)
        # Without a stored previous closing, the start the statement itself carries (if any).
        starts[row["statement_id"]] = (
            date.fromisoformat(before["period_end"]) + timedelta(days=1)
            if before
            else _optional_date(row["period_start"])
        )
        if before:
            next_of[before["statement_id"]] = row["statement_id"]
        previous[group] = row
    lines: dict[str, list[StatementLine]] = defaultdict(list)
    for row in reversed(rows):
        # Only cards have debt to pay: a savings balance has no verdict.
        is_card = row["account_kind"] == "credit_card"
        has_next = is_card and row["statement_id"] in next_of
        following = per_statement.get(next_of[row["statement_id"]]) if has_next else None
        lines[row["account_key"]].append(
            _line(row, starts[row["statement_id"]], has_next, following)
        )
    return {key: lines_[::-1] for key, lines_ in lines.items()}


def _line(
    row: sqlite3.Row, start: date | None, has_next: bool, following: StatementMoney | None
) -> StatementLine:
    balance = _money(row["closing_balance_cents"])
    due_date = date.fromisoformat(row["due_date"]) if row["due_date"] else None
    # Only what was paid on time counts (up to the due date); without a due date, everything.
    # Payment reversals (bounced check) are not subtracted: a rare case.
    on_time = following.payments_through(due_date) if following else Decimal(0)
    total = following.payments if following else Decimal(0)
    judged = has_next and balance is not None and balance > 0
    paid_full = (on_time >= balance) if judged and balance is not None else None
    paid_late = bool(judged and balance is not None and paid_full is False and total >= balance)
    return StatementLine(
        statement_id=row["statement_id"],
        period_start=start,
        period_end=date.fromisoformat(row["period_end"]),
        currency=row["currency"],
        charges=_money(row["printed_debits_cents"]),
        payments=_money(row["printed_credits_cents"]),
        balance=balance,
        due_date=due_date,
        minimum_payment=_money(row["minimum_payment_cents"]),
        paid_full=paid_full,
        left_over=max(Decimal(0), balance - on_time) if paid_full is False and balance else None,
        paid_late=paid_late,
        next_interest=following.interest if following else Decimal(0),
        printout=row["parser"] in PRINTOUT_PARSERS,
    )


def _optional_date(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _money(cents: int | None) -> Decimal | None:
    return None if cents is None else Decimal(cents) / 100


def _latest(lines: list[StatementLine]) -> list[StatementLine]:
    if not lines:
        return []
    newest = lines[0].period_end
    chosen: dict[str, StatementLine] = {}
    for line in lines:
        if line.period_end == newest:
            chosen.setdefault(line.currency, line)
    return sorted(chosen.values(), key=lambda line: _dop_first(line.currency))


def _history(lines: list[StatementLine]) -> list[StatementLine]:
    cuts = set(sorted({line.period_end for line in lines}, reverse=True)[:STATEMENT_HISTORY])
    kept = [line for line in lines if line.period_end in cuts]
    return sorted(kept, key=lambda line: (-line.period_end.toordinal(), _dop_first(line.currency)))
