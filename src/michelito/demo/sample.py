"""The "try a sample statement" button: the made-up card's next closing.

It takes the last stored statement of the demo's card, generates the next closing (one month
later, with the same rules as the template, the full payment of the previous balance and a
repeated charge to review) and imports it along the same path as the template
(`generate.store`: registration, validation and storage). Each click brings the next one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from michelito.demo import generate
from michelito.demo import movements as mv
from michelito.parsers.common import Statement

CARD_KEY = f"{mv.CARD[0]}:{mv.CARD[1]}"


class NoCard(LookupError):
    """The copy does not have the demo's card (should not happen)."""


@dataclass(frozen=True)
class Result:
    status: str  # parsed (it balances), invalid or duplicate
    detail: str | None
    transactions: int
    account: str
    period_start: date
    period_end: date

    @property
    def balanced(self) -> bool:
        return self.status == "parsed"

    @property
    def months(self) -> list[str]:
        """The months the statement touches, from oldest to newest."""
        first = self.period_start.strftime("%Y-%m")
        last = self.period_end.strftime("%Y-%m")
        return [first] if first == last else [first, last]


def import_next(conn: sqlite3.Connection, today: date) -> Result:
    """Generate and import the card's next closing."""
    last_cut, balances = _last_card(conn)
    cut = mv.on(mv.month_start(last_cut, 1), mv.CUT_DAY)
    statement = _next_statement(last_cut, cut, balances)
    stored = generate.store(conn, statement, f"sample-{cut.isoformat()}", today)
    return Result(
        stored.status,
        stored.detail,
        stored.transactions,
        f"{mv.CARD[2]} ···{mv.CARD[3]}",
        last_cut + timedelta(days=1),
        cut,
    )


def _last_card(conn: sqlite3.Connection) -> tuple[date, dict[str, Decimal]]:
    rows = conn.execute(
        "SELECT s.period_end, s.currency, s.closing_balance_cents FROM statements s "
        "JOIN accounts a ON a.id = s.account_id WHERE a.key = ? "
        "AND s.period_end = (SELECT MAX(s2.period_end) FROM statements s2 "
        "WHERE s2.account_id = s.account_id)",
        (CARD_KEY,),
    ).fetchall()
    if not rows:
        raise NoCard("the copy has no statements of the demo card")
    balances = {row[1]: Decimal(row[2] or 0) / 100 for row in rows}
    return date.fromisoformat(rows[0][0]), balances


def _next_statement(last_cut: date, cut: date, balances: dict[str, Decimal]) -> Statement:
    months = (mv.month_start(last_cut), mv.month_start(cut))
    seed = mv.SEED + cut.toordinal()
    plans = [mv.one_month(m, 30 + n, seed + n, review=n == 0) for n, m in enumerate(months)]
    sections = []
    paid_on = last_cut + generate.PAYMENT_DELAY
    for currency in ("DOP", "USD"):
        rows = [
            row for plan in plans for row in plan.of(mv.CARD, currency) if last_cut < row.day <= cut
        ]
        owed = balances.get(currency, Decimal(0))
        if owed > 0:
            rows.append(mv.Row(paid_on, mv.CARD_PAYMENT, owed, "credit", currency))
        sections.append(generate.section(currency, owed, rows, liability=True, minimum=True))
    return generate.statement(mv.CARD, None, cut, cut + timedelta(days=25), sections)
