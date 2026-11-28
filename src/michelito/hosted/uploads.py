"""Reading an uploaded statement in hosted mode: entirely in memory, only what squares is kept.

`examine(data, password)` opens the PDF from the bytes in a limited worker process
(`hosted.pdf_worker`: memory, CPU, wall-clock and page caps; neither the original nor a decrypted
copy is ever written to disk), picks the parser, parses every part and validates it
against the printed totals. It touches no database. `store(conn, name, data, examined, now)`
then registers the document (`importer.register_upload`, no file) and runs the same ingestion as
any other document (`ingest.process_documents`, with a reader that hands back the pages already in
memory), but only when at least one statement squared: a file that does not square leaves
nothing behind.

A loan statement (`analysis.loan_statements`, tried when no account parser recognizes the file)
squares when its parser reads it: its payments then go to the loan with its number, and without
such a loan nothing is kept (`NO_LOAN`).

When a file fails, `Fingerprint` describes it **without any data from the statement**: the bank
and parser (if recognized), the page count, the stage and the failing checks (e.g.
`section1:balance`). It is what gets logged, so the case can be reproduced with a synthetic
statement in `tests/samples.py`. The password is never logged, returned or stored; it only lives
in the caller's variables for the duration of the call.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from michelito import db, importer, ingest
from michelito.analysis import loan_statements
from michelito.hosted import pdf_worker
from michelito.parsers import StatementParser, detect, splitter
from michelito.parsers.common import (
    CREDIT,
    DEBIT,
    LoanStatement,
    Page,
    ParseError,
    Section,
    Statement,
    Word,
    group_lines,
    validate_statement,
)

log = logging.getLogger(__name__)
PDF_MAGIC = b"%PDF"

# A file's final states (`squared` and `duplicate` open the gate).
SQUARED = "squared"
DUPLICATE = "duplicate"
INVALID = "invalid"  # read, but it does not square: not saved
LOCKED = "locked"  # it needs a password (or the one given did not open it)
UNSUPPORTED = "unsupported"  # no parser recognizes it
UNREADABLE = "unreadable"  # not a PDF, damaged, or a parser failed on it
TOO_COMPLEX = "too_complex"  # too many pages, or opening it needed too much memory or time
NO_LOAN = "no_loan"  # a loan statement that squares, of a loan the person has not added
LOAN_KIND = "loan"  # a loan statement's `Read.kind`


@dataclass(frozen=True)
class Fingerprint:
    """A failure's structure, with no amounts, names, account numbers or statement text."""

    stage: str  # open, detect, parse, validate
    pages: int = 0
    bank: str | None = None
    parser: str | None = None
    checks: tuple[str, ...] = ()

    def line(self) -> str:
        checks = ",".join(self.checks) or "-"
        return (
            f"stage={self.stage} bank={self.bank or '-'} parser={self.parser or '-'} "
            f"pages={self.pages} checks={checks}"
        )


@dataclass(frozen=True)
class Read:
    """What one statement that squared says about itself (for the processing screen)."""

    bank: str
    kind: str
    identifier: str
    month: str  # YYYY-MM of its closing date (a loan's: of its last payment)
    transactions: int  # a loan's: its payments


@dataclass(frozen=True)
class Examined:
    state: str
    pages: tuple[Page, ...] = ()
    squared: tuple[Statement, ...] = ()
    fingerprint: Fingerprint | None = None
    bank: str | None = None  # the bank, when the parser recognized it
    parts: int = 0
    reads: tuple[Read, ...] = field(default=())
    loan: LoanStatement | None = None  # the file is a loan statement: what it says


def examine(data: bytes, password: str, limits: pdf_worker.Limits | None = None) -> Examined:
    """Read (in a limited worker process), recognize, parse and validate. Touches no database
    and no disk."""
    if not data.startswith(PDF_MAGIC):
        return Examined(UNREADABLE, fingerprint=Fingerprint("open"))
    try:
        pages = pdf_worker.read(data, password, limits or pdf_worker.Limits())
    except pdf_worker.WrongPassword:
        return Examined(LOCKED)
    except pdf_worker.TooComplex as exc:
        return Examined(TOO_COMPLEX, fingerprint=Fingerprint("limits", checks=(exc.reason,)))
    except pdf_worker.Unreadable:
        return Examined(UNREADABLE, fingerprint=Fingerprint("open"))
    return examine_pages(pages)


def examine_pages(pages: tuple[Page, ...]) -> Examined:
    """`examine`'s steps after reading: recognize, parse and validate pages already read."""
    try:
        parser = detect(pages)
    except Exception:  # a failing `matches` counts as not recognized
        parser = None
    if parser is not None:
        return _parse_all(parser, pages)
    try:
        loan_parser = loan_statements.parser_for(pages)
    except Exception:  # a failing `matches` counts as not recognized
        loan_parser = None
    if loan_parser is None:
        return Examined(UNSUPPORTED, pages, fingerprint=Fingerprint("detect", len(pages)))
    return _parse_loan(loan_parser, pages)


def _parse_loan(parser: loan_statements.Parser, pages: tuple[Page, ...]) -> Examined:
    """A loan statement squares if its parser reads it (it checks the balances itself)."""
    bank = parser.INSTITUTION
    try:
        statement = parser.parse(pages)
    except Exception as exc:  # an unexpected layout, or one that does not square
        kind = type(exc).__name__ if isinstance(exc, ParseError | ValueError) else "error"
        fingerprint = Fingerprint("parse", len(pages), bank, parser.NAME, (kind,))
        return Examined(UNREADABLE, pages, fingerprint=fingerprint, bank=bank, parts=1)
    read = Read(
        bank=bank,
        kind=LOAN_KIND,
        identifier="".join(c for c in statement.number if c.isalnum())[-4:],
        month=max(line.day for line in statement.lines).isoformat()[:7],
        transactions=len(statement.lines),
    )
    return Examined(SQUARED, pages, bank=bank, parts=1, reads=(read,), loan=statement)


def pages_json(pages: tuple[Page, ...]) -> bytes:
    """The positioned words of read pages (the pdf worker's own format), to seal and keep."""
    return json.dumps(
        [[[w.text, w.x0, w.x1, w.top] for line in page for w in line.words] for page in pages]
    ).encode("utf-8")


def pages_of(data: bytes) -> tuple[Page, ...]:
    return tuple(
        group_lines(Word(str(w[0]), float(w[1]), float(w[2]), float(w[3])) for w in page)
        for page in json.loads(data)
    )


def _parse_all(parser: StatementParser, pages: tuple[Page, ...]) -> Examined:
    split = splitter(parser)
    parts = split(pages) if split is not None else (pages,)
    squared: list[Statement] = []
    checks: list[str] = []
    stage = "validate"
    bank: str | None = None
    for number, part in enumerate(parts, start=1):
        try:
            statement = parser.parse(part)
        except Exception as exc:  # an unexpected layout must not stop the other parts
            stage = "parse"
            kind = type(exc).__name__ if isinstance(exc, ParseError | ValueError) else "error"
            checks.append(f"part{number}:{kind}")
            continue
        bank = statement.institution
        if validate_statement(statement):
            checks.extend(f"part{number}:{check}" for check in failing_checks(statement))
        else:
            squared.append(statement)
    if squared:
        return Examined(
            SQUARED,
            pages,
            tuple(squared),
            bank=bank,
            parts=len(parts),
            reads=tuple(read_of(s) for s in squared),
        )
    state = INVALID if stage == "validate" else UNREADABLE
    fingerprint = Fingerprint(stage, len(pages), bank, parser.NAME, tuple(checks))
    return Examined(state, pages, fingerprint=fingerprint, bank=bank, parts=len(parts))


def failing_checks(statement: Statement) -> tuple[str, ...]:
    """Which of `validate_statement`'s checks fail, by name and section (no values)."""
    if not statement.sections:
        return ("no_sections",)
    found: list[str] = []
    for index, section in enumerate(statement.sections, start=1):
        names = _section_checks(section, statement.is_liability)
        found.extend(f"section{index}:{name}" for name in names)
    return tuple(found)


def _section_checks(section: Section, liability: bool) -> list[str]:
    debits = _total(section, DEBIT)
    credits = _total(section, CREDIT)
    names = []
    present = False
    for name, read, printed in (
        ("debits", debits, section.printed_debits),
        ("credits", credits, section.printed_credits),
    ):
        if printed is None:
            continue
        present = True
        if read != printed:
            names.append(name)
    if section.previous_balance is not None and section.closing_balance is not None:
        present = True
        change = debits - credits if liability else credits - debits
        if section.previous_balance + change != section.closing_balance:
            names.append("balance")
    balances = [item.balance for item in section.transactions]
    if section.previous_balance is not None and balances and None not in balances:
        present = True
        if _chain_breaks(section, liability):
            names.append("chain")
    if not present:
        names.append("no_totals")
    return names


def _total(section: Section, direction: str) -> Decimal:
    return sum(
        (item.amount for item in section.transactions if item.direction == direction),
        Decimal(0),
    )


def _chain_breaks(section: Section, liability: bool) -> bool:
    running = section.previous_balance or Decimal(0)
    for item in section.transactions:
        signed = item.amount if item.direction == DEBIT else -item.amount
        running += signed if liability else -signed
        if item.balance is not None and running != item.balance:
            return True
    return False


def read_of(statement: Statement) -> Read:
    return Read(
        bank=statement.institution,
        kind=statement.kind,
        identifier="".join(c for c in statement.identifier if c.isalnum())[-4:],
        month=statement.period_end.isoformat()[:7],
        transactions=sum(len(s.transactions) for s in statement.sections),
    )


def store(
    conn: sqlite3.Connection, name: str, data: bytes, examined: Examined, now: datetime
) -> str:
    """Keep what squared (only call it with a `SQUARED` examination): `SQUARED`, or
    `DUPLICATE` when the file or every statement in it was already stored. A loan statement of
    a loan the person does not have is `NO_LOAN`, and nothing is kept.

    The same file uploaded before counts as a duplicate only if its statements are stored; a
    row left without them (an earlier attempt that failed half-way) is processed again. If the
    ingestion fails, a row this call registered is deleted again, so no orphan stays behind."""
    if examined.state != SQUARED:
        raise ValueError("only a statement that squares is stored")
    if examined.loan is not None and loan_statements.loan_for(conn, examined.loan.number) is None:
        return NO_LOAN
    registered = importer.register_upload(conn, name, data, now)
    document_id = registered.document_id
    if not registered.new:
        if db.has_statements(conn, document_id):
            return DUPLICATE
        with conn:
            conn.execute("UPDATE documents SET status = 'pending' WHERE id = ?", (document_id,))
    pages = examined.pages

    def from_memory(path: Path, password: str) -> tuple[Page, ...]:
        return pages

    try:
        outcome = ingest.process_documents(conn, "", from_memory, only=[document_id])
    except Exception:
        if registered.new:
            _forget_document(conn, document_id)
        raise
    return SQUARED if outcome.get("parsed") else DUPLICATE


def _forget_document(conn: sqlite3.Connection, document_id: int) -> None:
    """Remove a just-registered upload that could not be ingested (it has no statements)."""
    if db.has_statements(conn, document_id):
        return
    with conn:
        row = conn.execute(
            "SELECT message_id FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        conn.execute("DELETE FROM document_parts WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        if row is not None:
            conn.execute(
                "DELETE FROM gmail_messages WHERE message_id = ? AND NOT EXISTS "
                "(SELECT 1 FROM documents WHERE message_id = ?)",
                (row[0], row[0]),
            )


def log_failure(fingerprint: Fingerprint | None) -> None:
    """The data-free structural fingerprint of a failure (nothing from the statement)."""
    if fingerprint is not None:
        log.warning("upload not stored: %s", fingerprint.line())


def months_of(reads: Sequence[Read]) -> list[str]:
    return sorted({read.month for read in reads}, reverse=True)
