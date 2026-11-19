"""«Probar con un estado de ejemplo»: el corte siguiente de la tarjeta inventada.

Toma el último estado guardado de la tarjeta de la demo, genera el corte siguiente (un mes después,
con las mismas reglas que la plantilla, el pago completo del saldo anterior y un cobro repetido
para revisar) y lo importa por el mismo camino que la plantilla (`generar.store`: registro,
validación y guardado). Cada clic trae el siguiente.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from finanzas.demo import generar
from finanzas.demo import movimientos as mv
from finanzas.parsers.common import Statement

CARD_KEY = f"{mv.CARD[0]}:{mv.CARD[1]}"


class NoCard(LookupError):
    """La copia no tiene la tarjeta de la demo (no debería pasar)."""


@dataclass(frozen=True)
class Result:
    status: str  # parsed (cuadra), invalid o duplicate
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
        """Los meses que toca el estado, del más viejo al más nuevo."""
        first = self.period_start.strftime("%Y-%m")
        last = self.period_end.strftime("%Y-%m")
        return [first] if first == last else [first, last]


def import_next(conn: sqlite3.Connection, today: date) -> Result:
    """Genera e importa el corte siguiente de la tarjeta."""
    last_cut, balances = _last_card(conn)
    cut = mv.on(mv.month_start(last_cut, 1), mv.CUT_DAY)
    statement = _next_statement(last_cut, cut, balances)
    stored = generar.store(conn, statement, f"ejemplo-{cut.isoformat()}", today)
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
        raise NoCard("no hay estados de la tarjeta de la demo")
    balances = {row[1]: Decimal(row[2] or 0) / 100 for row in rows}
    return date.fromisoformat(rows[0][0]), balances


def _next_statement(last_cut: date, cut: date, balances: dict[str, Decimal]) -> Statement:
    months = (mv.month_start(last_cut), mv.month_start(cut))
    seed = mv.SEED + cut.toordinal()
    plans = [mv.one_month(m, 30 + n, seed + n, review=n == 0) for n, m in enumerate(months)]
    sections = []
    paid_on = last_cut + generar.PAYMENT_DELAY
    for currency in ("DOP", "USD"):
        rows = [
            row for plan in plans for row in plan.of(mv.CARD, currency) if last_cut < row.day <= cut
        ]
        owed = balances.get(currency, Decimal(0))
        if owed > 0:
            rows.append(mv.Row(paid_on, mv.CARD_PAYMENT, owed, "credit", currency))
        sections.append(generar.section(currency, owed, rows, liability=True, minimum=True))
    return generar.statement(mv.CARD, None, cut, cut + timedelta(days=25), sections)
