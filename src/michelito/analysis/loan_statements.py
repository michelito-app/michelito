"""Loan statements: the hook a parser plugs into, and how what it reads is stored.

A loan statement parser works like the account parsers (`parsers/`): it exposes `NAME`,
`matches(pages)` and `parse(pages)`, receives the pages as lines of words and returns a
`LoanStatement` (the loan number and one `StatementLine` per payment: principal, interest,
other charges and the balance after it). `store` puts those lines on the loan with that number;
from then on they win over the contract for their months, and `loan_review` sends the
differences to review.

`PARSERS` are the registered ones. A new bank's format is learned from a real sample first
(looking only at the shape of the data, never copying its content into the repository).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Protocol

from michelito.analysis import loan_match, loan_store
from michelito.analysis.links import LinkError
from michelito.i18n import t
from michelito.parsers import popular_loan
from michelito.parsers.common import LoanStatement, Page

Pages = tuple[Page, ...]


class Parser(Protocol):
    NAME: str
    INSTITUTION: str

    def matches(self, pages: Pages) -> bool: ...

    def parse(self, pages: Pages) -> LoanStatement: ...


PARSERS: tuple[Parser, ...] = (popular_loan,)  # type: ignore[assignment]


def parser_for(pages: Pages, parsers: Sequence[Parser] = PARSERS) -> Parser | None:
    return next((p for p in parsers if p.matches(pages)), None)


def loan_for(conn: sqlite3.Connection, printed: str) -> loan_store.Loan | None:
    """The loan with the number a statement prints, if the person has it."""
    number = loan_match.clean_number(printed)
    return next(
        (loan for loan in loan_store.load(conn) if loan_match.same_number(loan.number, number)),
        None,
    )


def store(
    conn: sqlite3.Connection, statement: LoanStatement, document: str | None, now: str
) -> tuple[int, int]:
    """The statement's lines on the loan with its number: (the loan, how many lines are new)."""
    loan = loan_for(conn, statement.number)
    if loan is None:
        raise LinkError(t("analysis.loans.unknown_number"))
    return loan.id, loan_store.add_statement_lines(conn, loan.id, statement.lines, document, now)
