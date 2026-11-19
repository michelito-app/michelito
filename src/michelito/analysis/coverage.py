"""Which document counts on each day of a bank account, so nothing is counted twice.

An official statement and a printout (`db.PRINTOUT_PARSERS`: the Popular web portal's, see
`parsers.popular_web`, and the current month of Banreservas and of BHD savings) can carry the
same transaction with another date or description, so they cannot be matched row by row.
The decision is per day and account:
- If some official statement covers the day, printouts contribute no rows that day.
- Otherwise, of the printouts covering it only the most recent counts: the one ending
  latest and, if they end the same day, the last imported (highest id).

An official statement and a printout cover from their `period_start` to their `period_end`:
for a statement, up to its cutoff; for a Popular printout, from its first to its last row;
for the Banreservas current month, from the period start to the report day; for BHD's, from
the period start to its last row (it does not print when it was downloaded). Statements
stored before `period_start` existed have it NULL (`parse --retry` does not reprocess what
was already parsed), and so do parsers that do not provide it: for them the statement's
first posting is used (posting date or, without one, transaction date), the same date basis
as the printout. "Previous cutoff + 1" is not used: if a statement is missing, that would
cover a month with no official transactions. Cards have no printouts: all of theirs always
counts.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from michelito.db import PRINTOUT_PARSERS

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
    official: dict[int, tuple[Span, ...]]  # per account
    printouts: dict[int, tuple[int, Span]]  # per statement: (account, span)

    def keeps(self, statement_id: int, day: date) -> bool:
        """Do the rows of `statement_id` count on `day`? Only printouts are filtered."""
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
