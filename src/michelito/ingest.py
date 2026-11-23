"""Parses the downloaded documents and stores only the statements that balance.

Possible statuses of a document:
- parsed: parsed, validated and stored.
- invalid: parsed, but it does not balance with its totals; it does not enter the database.
- error: it could not be read or parsed.
- unsupported: no parser recognizes the format.
- duplicate: there is already a statement for that account, currency and closing date (or a
  website printout with the same dates).
- archived: not a PDF; it is kept but not parsed in phase 1.

A website printout does not state its currency (a bare "$"): the one given when importing is
used (`printout_currency`) or, failing that, the one given before for that account
(`account_currency`); with neither, DOP. The given one is remembered for the account when the
printout balances.

A PDF with several statements in a row (a parser with `split`, such as `popular_history`) is cut
into parts and each part is parsed, validated and stored separately, all with the same document;
each one's result goes to `document_parts`. The document ends up:
- parsed: if at least one part entered (now or in an earlier run); the detail says how many and
  names the repeated and the failed ones;
- duplicate: if every part was already stored from other documents;
- invalid or error: if none entered (invalid if one of them does not balance).
`retry` also retries the documents with failed parts; a part already stored from the same
document is not stored again.

The details stored in `documents.detail` and `document_parts` are Spanish text from the catalog
(`core.ingest.*`): the import screens and the demo's sample statement show them.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from michelito import db
from michelito.analysis import installment_store, live_match, loan_store, receipt_match
from michelito.config import ARCHIVE_ONLY
from michelito.i18n import t
from michelito.parsers import StatementParser, detect, labeler, popular_web, splitter
from michelito.parsers.common import Page, Statement, count_notes, validate_statement

_LOG = logging.getLogger(__name__)
PageReader = Callable[[Path, str], tuple[Page, ...]]
RETRYABLE = ("invalid", "error", "unsupported")


def process_documents(
    conn: sqlite3.Connection,
    password: str,
    read_pages: PageReader,
    *,
    retry: bool = False,
    only: Collection[int] | None = None,
    printout_currency: str | None = None,
    archive_only: Collection[str] = ARCHIVE_ONLY,
) -> Counter[str]:
    """Parse the pending documents (or the failed ones, with `retry`); `only` limits them to
    those IDs. `printout_currency` is the currency of the website printouts (and is remembered
    per account); it does not affect the official statements, which print it. Those from the
    `archive_only` sources are only archived."""
    if printout_currency is not None and printout_currency not in popular_web.CURRENCIES:
        raise ValueError(f"unknown currency: {printout_currency!r}")
    statuses = ("pending", *RETRYABLE) if retry else ("pending",)
    marks = ", ".join("?" for _ in statuses)
    query = f"SELECT id, path, filename, source FROM documents WHERE (status IN ({marks})"
    params: list[object] = list(statuses)
    if retry:
        failed = ", ".join("?" for _ in db.FAILED_PART_STATUSES)
        query += f" OR id IN (SELECT document_id FROM document_parts WHERE status IN ({failed}))"
        params.extend(db.FAILED_PART_STATUSES)
    query += ")"
    if only is not None:
        query += f" AND id IN ({', '.join('?' for _ in only)})"
        params.extend(only)
    rows = conn.execute(f"{query} ORDER BY received_at", params).fetchall()
    outcome: Counter[str] = Counter()
    for row in rows:
        outcome[_process(conn, row, password, read_pages, printout_currency, archive_only)] += 1
    return outcome


@dataclass(frozen=True)
class _Unread:
    """A document that does not reach a parser: status and reason."""

    status: str
    detail: str


def ingest_statement(
    conn: sqlite3.Connection, document_id: int, parser: str, statement: Statement
) -> str:
    """Validate and store an already parsed statement (the ones the demo generates, without a
    PDF) with the same rules as a document: it enters only if it balances, and the document is
    marked (`parsed`, `invalid` or `duplicate`). Returns the final status."""
    problems = validate_statement(statement)
    if problems:
        _mark(conn, document_id, "invalid", parser, "; ".join(problems))
        return "invalid"
    return _store(conn, document_id, parser, statement)


def _process(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    password: str,
    read_pages: PageReader,
    printout_currency: str | None,
    archive_only: Collection[str],
) -> str:
    """Parse a document and mark it; returns its final status."""
    found = _recognize(row, password, read_pages, archive_only)
    if isinstance(found, _Unread):
        reason = _scrub(found.detail, password) or found.detail
        return _mark_unread(conn, row["id"], _Unread(found.status, reason))
    pages, parser = found
    split = splitter(parser)
    if split is not None:
        return _process_parts(conn, row["id"], parser, split(pages), password)
    status, detail, statement = _interpret(conn, parser, pages, printout_currency)
    if status == "parsed" and statement is not None:
        remember = printout_currency if parser.NAME == db.PRINTOUT_PARSER else None
        return _store(conn, row["id"], parser.NAME, statement, remember)
    _mark(conn, row["id"], status, parser.NAME, _scrub(detail, password))
    return status


def _recognize(
    row: sqlite3.Row, password: str, read_pages: PageReader, archive_only: Collection[str]
) -> _Unread | tuple[tuple[Page, ...], StatementParser]:
    """Read the document and choose its parser."""
    if row["source"] in archive_only:
        return _Unread("archived", t("core.ingest.archived_source"))
    try:
        pages = read_pages(Path(row["path"]), password)
    except Exception as exc:  # pdfminer raises assorted classes; all count as unreadable
        error = f"{type(exc).__name__}: {exc}"
        return _Unread("error", t("core.ingest.unreadable_pdf", error=error))
    try:
        parser = detect(pages)
    except Exception as exc:  # a failing `matches` must not stop the rest of the run
        error = f"{type(exc).__name__}: {exc}"
        return _Unread("error", t("core.ingest.detect_failed", error=error))
    if parser is None:
        return _Unread("unsupported", t("core.ingest.unsupported"))
    return pages, parser


def _mark_unread(conn: sqlite3.Connection, document_id: int, unread: _Unread) -> str:
    """Mark a document that did not reach a parser. One that already has stored statements (a
    PDF with several statements being retried) stays `parsed`: the reason goes to its detail
    and its failed parts stay as they were."""
    if not db.has_statements(conn, document_id):
        _mark(conn, document_id, unread.status, None, unread.detail)
        return unread.status
    row = conn.execute(
        "SELECT parser, detail FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    previous = (row["detail"] or "").split(t("core.ingest.retry_separator"))[0]
    detail = t("core.ingest.retry", previous=previous, status=unread.status, reason=unread.detail)
    _mark(conn, document_id, "parsed", row["parser"], detail)
    return "parsed"


def _interpret(
    conn: sqlite3.Connection,
    parser: StatementParser,
    pages: tuple[Page, ...],
    printout_currency: str | None,
) -> tuple[str, str | None, Statement | None]:
    """Parse and validate: (status, reason, the parsed statement if it could be parsed)."""
    try:
        statement = _parse(conn, parser, pages, printout_currency)
    except Exception as exc:  # an unexpected format must not stop the rest of the run
        return "error", f"{type(exc).__name__}: {exc}", None
    problems = validate_statement(statement)
    if problems:
        return "invalid", "; ".join(problems), statement
    return "parsed", None, statement


# Number, label, status, reason and note (a printed count that does not match: not invalid).
PartResult = tuple[int, str, str, str | None, str | None]


def _process_parts(
    conn: sqlite3.Connection,
    document_id: int,
    parser: StatementParser,
    parts: tuple[tuple[Page, ...], ...],
    password: str,
) -> str:
    """Parse, validate and store each part separately; one that fails does not block the
    others. Each one's result goes to `document_parts`."""
    results: list[PartResult] = []
    find_label = labeler(parser)
    for number, pages in enumerate(parts, start=1):
        status, detail, statement = _interpret(conn, parser, pages, None)
        if statement is not None:
            label = statement.period_end.isoformat()
        else:
            label = (find_label(pages) if find_label else None) or t(
                "core.ingest.part_label", number=number
            )
        note = None
        if statement is not None and db.stored_for_document(conn, document_id, statement):
            # It entered in an earlier run: it is kept even if it does not balance now.
            status, detail = "parsed", t("core.ingest.already_stored")
        elif status == "parsed" and statement is not None:
            status, detail = _store_part(conn, document_id, statement)
            note = "; ".join(count_notes(statement)) or None
        results.append((number, label, status, _scrub(detail, password), note))
    status, detail = _parts_outcome(conn, document_id, results)
    with conn:
        db.replace_document_parts(conn, document_id, results)
        _update(conn, document_id, status, parser.NAME, detail)
    return status


def _store_part(
    conn: sqlite3.Connection, document_id: int, statement: Statement
) -> tuple[str, str | None]:
    """Store a part in its own transaction."""
    before = _last_statement(conn)
    try:
        with conn:
            stored = db.store_statement(conn, document_id, statement)
    except sqlite3.IntegrityError as exc:
        if db.DUPLICATE_PERIOD_INDEX in str(exc):
            return "duplicate", t("core.ingest.duplicate_period")
        return "error", f"IntegrityError: {exc}"
    _reconcile(conn, before)
    return "parsed", t("core.ingest.stored", count=stored)


def _parts_outcome(
    conn: sqlite3.Connection, document_id: int, results: list[PartResult]
) -> tuple[str, str]:
    """The document's status and detail from its parts."""
    if not results:
        return "error", t("core.ingest.no_statement")
    statuses = [result[2] for result in results]
    parsed = statuses.count("parsed")
    if parsed:
        status = "parsed"
    elif all(s == "duplicate" for s in statuses):
        status = "duplicate"
    else:
        status = "invalid" if "invalid" in statuses else "error"
    stored = conn.execute(
        "SELECT COUNT(*) FROM transactions t JOIN statements s ON s.id = t.statement_id "
        "WHERE s.document_id = ?",
        (document_id,),
    ).fetchone()[0]
    pieces = [t("core.ingest.parts_stored", parsed=parsed, total=len(results), count=stored)]
    repeated = [label for _, label, s, _, _ in results if s == "duplicate"]
    if repeated:
        pieces.append(t("core.ingest.parts_repeated", labels=", ".join(repeated)))
    pieces.extend(
        f"{label} {s}: {detail}"
        for _, label, s, detail, _ in results
        if s in db.FAILED_PART_STATUSES
    )
    pieces.extend(
        t("core.ingest.part_note", label=label, note=note)
        for _, label, _, _, note in results
        if note
    )
    return status, "; ".join(pieces)


def _parse(
    conn: sqlite3.Connection,
    parser: StatementParser,
    pages: tuple[Page, ...],
    printout_currency: str | None,
) -> Statement:
    """Parse; a printout, in the given currency or the one remembered for its account."""
    if parser.NAME != db.PRINTOUT_PARSER:
        return parser.parse(pages)
    if printout_currency is not None:
        # Straight in the given currency: read first as DOP, a printout that mixes "$" and
        # "US$" would fail for mixing currencies.
        return popular_web.parse(pages, currency=printout_currency)
    # The account (and its remembered currency) comes from the header: it is parsed again.
    statement = popular_web.parse(pages)
    stored = db.account_currency(conn, db.account_key(statement))
    return statement if stored is None else popular_web.parse(pages, currency=stored)


def _store(
    conn: sqlite3.Connection,
    document_id: int,
    parser: str | None,
    statement: Statement,
    currency: str | None = None,
) -> str:
    """Store the statement and mark the document in the same transaction; `currency`, if
    given, becomes the currency of the account's printouts (also when it was a duplicate)."""
    before = _last_statement(conn)
    try:
        with conn:
            stored = db.store_statement(conn, document_id, statement)
            _update(conn, document_id, "parsed", parser, t("core.ingest.stored", count=stored))
            _remember(conn, statement, currency)
    except sqlite3.IntegrityError as exc:
        if db.DUPLICATE_PERIOD_INDEX in str(exc):
            status, detail = "duplicate", t("core.ingest.duplicate_period")
        elif db.DUPLICATE_PRINTOUT_INDEX in str(exc):
            status, detail = "duplicate", t("core.ingest.duplicate_printout")
        else:
            status, detail = "error", f"IntegrityError: {exc}"
        with conn:
            _update(conn, document_id, status, parser, detail)
            if status == "duplicate":
                _remember(conn, statement, currency)
        return status
    _reconcile(conn, before)
    return "parsed"


def _last_statement(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM statements").fetchone()[0])


def _reconcile(conn: sqlite3.Connection, after: int) -> None:
    """Once the statement is committed, in a transaction of its own: it may confirm provisionals
    from bank alerts (`live_match`), handing their identity only to the rows just stored. If it
    fails the statement stays; the next reconcile (the next sync) does the same work."""
    stored = [
        int(row[0]) for row in conn.execute("SELECT id FROM statements WHERE id > ?", (after,))
    ]
    try:
        with conn:
            live_match.reconcile(conn, _now(), stored)
    except sqlite3.Error as exc:
        _LOG.warning(
            "reconciling bank alerts failed (%s); the next sync retries", type(exc).__name__
        )
    # After the alerts: a provisional that just became its statement row changed fingerprint.
    try:
        with conn:
            receipt_match.reconcile_stored(conn, _now())
    except Exception as exc:  # noqa: BLE001 - receipts are an extra: the statement stays
        _LOG.warning(
            "matching merchant receipts failed (%s); the next sync retries", type(exc).__name__
        )
    # Installments only come with statements (a provisional changes fingerprint).
    try:
        with conn:
            installment_store.reconcile_stored(conn, _now())
    except Exception as exc:  # noqa: BLE001 - plans are an extra: the statement stays
        _LOG.warning(
            "matching installment plans failed (%s); the next sync retries", type(exc).__name__
        )
    # Loans: every charge with a loan's number, from any account.
    try:
        with conn:
            loan_store.reconcile_stored(conn, _now())
    except Exception as exc:  # noqa: BLE001 - loans are an extra: the statement stays
        _LOG.warning(
            "matching loan payments failed (%s); the next sync retries", type(exc).__name__
        )


def _remember(conn: sqlite3.Connection, statement: Statement, currency: str | None) -> None:
    if currency is not None:
        db.set_account_currency(conn, db.account_key(statement), currency, _now())


def _scrub(detail: str | None, password: str) -> str | None:
    """Extra defense: no stored error message may contain the password."""
    if detail is None or not password:
        return detail
    return detail.replace(password, "***")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _mark(
    conn: sqlite3.Connection, document_id: int, status: str, parser: str | None, detail: str | None
) -> None:
    with conn:
        _update(conn, document_id, status, parser, detail)


def _update(
    conn: sqlite3.Connection, document_id: int, status: str, parser: str | None, detail: str | None
) -> None:
    conn.execute(
        "UPDATE documents SET status = ?, parser = ?, detail = ?, processed_at = ? WHERE id = ?",
        (status, parser, detail, _now(), document_id),
    )
