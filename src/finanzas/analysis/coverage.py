"""Qué documento cuenta cada día de una cuenta bancaria, para no contar dos veces.

Un estado oficial y una impresión (`db.PRINTOUT_PARSERS`: la del portal del Popular, ver
`parsers.popular_web`, y el mes en curso de Banreservas y de ahorro de BHD) pueden traer el
mismo movimiento con otra fecha o descripción, así que no se pueden emparejar fila por fila.
Se decide por día y cuenta:
- Si algún estado oficial cubre el día, las impresiones no aportan filas ese día.
- Si no, de las impresiones que lo cubren solo cuenta la más reciente: la que termina más
  tarde y, si terminan el mismo día, la última importada (mayor id).

Un estado oficial y una impresión cubren de su `period_start` a su `period_end`: en un
estado, hasta su corte; en una impresión del Popular, de su primera a su última fila; en el
mes en curso de Banreservas, del inicio del periodo al día del reporte; en el de BHD, del
inicio del periodo a su última fila (no imprime cuándo se bajó). Los estados guardados
antes de que existiera `period_start` lo tienen en NULL (`parse --retry` no reprocesa lo
ya interpretado) y los parsers que no lo dan también: para ellos se toma el primer posteo
del estado (posteo o, sin él, transacción), la misma base de fechas que la impresión. No
se usa "corte anterior + 1": si falta un estado, eso cubriría un mes del que no hay
movimientos oficiales. Las tarjetas no tienen impresiones: todo lo suyo cuenta
siempre.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from finanzas.db import PRINTOUT_PARSERS

_STATEMENTS = """
SELECT s.id, s.account_id, s.parser, s.period_end,
       COALESCE(
           s.period_start,
           (SELECT MIN(COALESCE(t.posted_on, t.transacted_on))
            FROM transactions t WHERE t.statement_id = s.id),
           s.period_end
       ) AS period_start
FROM statements s JOIN accounts a ON a.id = s.account_id
WHERE a.kind IN ('savings', 'checking')
"""

Span = tuple[date, date]


@dataclass(frozen=True)
class BankCoverage:
    official: dict[int, tuple[Span, ...]]  # por cuenta
    printouts: dict[int, tuple[int, Span]]  # por estado: (cuenta, rango)

    def keeps(self, statement_id: int, day: date) -> bool:
        """¿Cuentan las filas de `statement_id` en `day`? Solo filtra impresiones."""
        printout = self.printouts.get(statement_id)
        if printout is None:
            return True
        account, _ = printout
        if any(_covers(span, day) for span in self.official.get(account, ())):
            return False
        newest = max(
            (span[1], other)
            for other, (other_account, span) in self.printouts.items()
            if other_account == account and _covers(span, day)
        )
        return newest[1] == statement_id


def bank_coverage(conn: sqlite3.Connection) -> BankCoverage:
    official: defaultdict[int, list[Span]] = defaultdict(list)
    printouts: dict[int, tuple[int, Span]] = {}
    for row in conn.execute(_STATEMENTS):
        span = (date.fromisoformat(row["period_start"]), date.fromisoformat(row["period_end"]))
        if row["parser"] in PRINTOUT_PARSERS:
            printouts[row["id"]] = (row["account_id"], span)
        else:
            official[row["account_id"]].append(span)
    return BankCoverage({k: tuple(v) for k, v in official.items()}, printouts)


def _covers(span: Span, day: date) -> bool:
    return span[0] <= day <= span[1]
