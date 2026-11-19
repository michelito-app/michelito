"""Interpreta los documentos descargados y guarda solo los estados que cuadran.

Estados posibles de un documento:
- parsed: interpretado, validado y guardado.
- invalid: interpretado, pero no cuadra con sus totales; no entra a la base.
- error: no se pudo leer o interpretar.
- unsupported: ningún parser reconoce el formato.
- duplicate: ya hay un estado para esa cuenta, moneda y fecha de corte (o una impresión
  del portal con las mismas fechas).
- archived: no es PDF; se guarda pero no se interpreta en la fase 1.

Una impresión del portal no dice su moneda ("$" a secas): se usa la indicada al importar
(`printout_currency`) o, si no, la que se indicó antes para esa cuenta (`account_currency`);
sin ninguna, peso. La indicada se recuerda para la cuenta cuando la impresión cuadra.

Un PDF con varios estados seguidos (un parser con `split`, como `popular_historico`) se corta
en tramos y cada tramo se interpreta, valida y guarda por separado, todos con el mismo
documento; el resultado de cada uno queda en `document_parts`. El documento queda:
- parsed: si entró al menos un tramo (ahora o en una pasada anterior); el detalle dice
  cuántos y nombra los repetidos y los fallidos;
- duplicate: si todos los tramos ya estaban guardados desde otros documentos;
- invalid o error: si ninguno entró (invalid si alguno no cuadra).
`retry` también reintenta los documentos con tramos fallidos; un tramo ya guardado desde el
mismo documento no se vuelve a guardar.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from finanzas import db
from finanzas.config import ARCHIVE_ONLY
from finanzas.parsers import StatementParser, detect, labeler, popular_web, splitter
from finanzas.parsers.common import Page, Statement, count_notes, validate_statement

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
    """Interpreta los documentos pendientes (o fallidos, con `retry`); `only` limita a esos IDs.
    `printout_currency` es la moneda de las impresiones del portal (y se recuerda por cuenta);
    no afecta a los estados oficiales, que la imprimen. Los de las fuentes `archive_only` solo
    se archivan."""
    if printout_currency is not None and printout_currency not in popular_web.CURRENCIES:
        raise ValueError(f"moneda desconocida: {printout_currency!r}")
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
    """Un documento que no llega a un parser: estado y motivo."""

    status: str
    detail: str


def ingest_statement(
    conn: sqlite3.Connection, document_id: int, parser: str, statement: Statement
) -> str:
    """Valida y guarda un estado que ya viene interpretado (los que genera la demo, sin PDF),
    con el mismo criterio que un documento: solo entra si cuadra y el documento queda marcado
    (`parsed`, `invalid` o `duplicate`). Devuelve el estado final."""
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
    """Interpreta un documento y lo marca; devuelve su estado final."""
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
    """Lee el documento y elige su parser."""
    if row["source"] in archive_only:
        return _Unread("archived", "fuente sin parser en la fase 1")
    try:
        pages = read_pages(Path(row["path"]), password)
    except Exception as exc:  # pdfminer lanza clases variadas; todas cuentan como ilegible
        return _Unread("error", f"no se pudo leer el PDF: {type(exc).__name__}: {exc}")
    try:
        parser = detect(pages)
    except Exception as exc:  # un `matches` que falla no debe detener el resto de la corrida
        return _Unread("error", f"al reconocer el formato: {type(exc).__name__}: {exc}")
    if parser is None:
        return _Unread("unsupported", "ningún parser reconoce el formato")
    return pages, parser


def _mark_unread(conn: sqlite3.Connection, document_id: int, unread: _Unread) -> str:
    """Marca un documento que no llegó a un parser. Uno que ya tiene estados guardados (un
    PDF con varios estados que se reintenta) sigue `parsed`: el motivo va a su detalle y sus
    tramos fallidos quedan como estaban."""
    if not db.has_statements(conn, document_id):
        _mark(conn, document_id, unread.status, None, unread.detail)
        return unread.status
    row = conn.execute(
        "SELECT parser, detail FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    previous = (row["detail"] or "").split("; reintento: ")[0]
    detail = f"{previous}; reintento: {unread.status}: {unread.detail}"
    _mark(conn, document_id, "parsed", row["parser"], detail)
    return "parsed"


def _interpret(
    conn: sqlite3.Connection,
    parser: StatementParser,
    pages: tuple[Page, ...],
    printout_currency: str | None,
) -> tuple[str, str | None, Statement | None]:
    """Interpreta y valida: (estado, motivo, lo interpretado si se pudo interpretar)."""
    try:
        statement = _parse(conn, parser, pages, printout_currency)
    except Exception as exc:  # un formato inesperado no debe detener el resto de la corrida
        return "error", f"{type(exc).__name__}: {exc}", None
    problems = validate_statement(statement)
    if problems:
        return "invalid", "; ".join(problems), statement
    return "parsed", None, statement


# Número, etiqueta, estado, motivo y nota (una cantidad impresa que no coincide: no invalida).
PartResult = tuple[int, str, str, str | None, str | None]


def _process_parts(
    conn: sqlite3.Connection,
    document_id: int,
    parser: StatementParser,
    parts: tuple[tuple[Page, ...], ...],
    password: str,
) -> str:
    """Interpreta, valida y guarda cada tramo por separado; uno que falla no impide los
    demás. Deja el resultado de cada uno en `document_parts`."""
    results: list[PartResult] = []
    find_label = labeler(parser)
    for number, pages in enumerate(parts, start=1):
        status, detail, statement = _interpret(conn, parser, pages, None)
        if statement is not None:
            label = statement.period_end.isoformat()
        else:
            label = (find_label(pages) if find_label else None) or f"estado {number}"
        note = None
        if statement is not None and db.stored_for_document(conn, document_id, statement):
            # Ya entró en una pasada anterior: se conserva aunque ahora no cuadre.
            status, detail = "parsed", "ya guardado"
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
    """Guarda un tramo en su propia transacción."""
    try:
        with conn:
            stored = db.store_statement(conn, document_id, statement)
    except sqlite3.IntegrityError as exc:
        if db.DUPLICATE_PERIOD_INDEX in str(exc):
            return "duplicate", "ya existe un estado para ese corte"
        return "error", f"IntegrityError: {exc}"
    return "parsed", f"{stored} transacciones"


def _parts_outcome(
    conn: sqlite3.Connection, document_id: int, results: list[PartResult]
) -> tuple[str, str]:
    """Estado y detalle del documento a partir de sus tramos."""
    if not results:
        return "error", "no se encontró ningún estado en el documento"
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
    pieces = [f"{parsed} de {len(results)} estados guardados ({stored} transacciones)"]
    repeated = [label for _, label, s, _, _ in results if s == "duplicate"]
    if repeated:
        pieces.append(f"repetidos: {', '.join(repeated)}")
    pieces.extend(
        f"{label} {s}: {detail}"
        for _, label, s, detail, _ in results
        if s in db.FAILED_PART_STATUSES
    )
    pieces.extend(f"{label} nota: {note}" for _, label, _, _, note in results if note)
    return status, "; ".join(pieces)


def _parse(
    conn: sqlite3.Connection,
    parser: StatementParser,
    pages: tuple[Page, ...],
    printout_currency: str | None,
) -> Statement:
    """Interpreta; una impresión, en la moneda indicada o en la recordada para su cuenta."""
    if parser.NAME != db.PRINTOUT_PARSER:
        return parser.parse(pages)
    if printout_currency is not None:
        # Directo en la moneda indicada: leída antes como peso, una impresión que mezcla
        # "$" y "US$" fallaría por mezclar monedas.
        return popular_web.parse(pages, currency=printout_currency)
    # La cuenta (y su moneda recordada) sale de la cabecera: se vuelve a interpretar.
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
    """Guarda el estado y marca el documento en la misma transacción; `currency`, si viene,
    queda como la moneda de las impresiones de la cuenta (también si era repetida)."""
    try:
        with conn:
            stored = db.store_statement(conn, document_id, statement)
            _update(conn, document_id, "parsed", parser, f"{stored} transacciones")
            _remember(conn, statement, currency)
    except sqlite3.IntegrityError as exc:
        if db.DUPLICATE_PERIOD_INDEX in str(exc):
            status, detail = "duplicate", "ya existe un estado para ese corte"
        elif db.DUPLICATE_PRINTOUT_INDEX in str(exc):
            status, detail = "duplicate", "ya existe una impresión igual"
        else:
            status, detail = "error", f"IntegrityError: {exc}"
        with conn:
            _update(conn, document_id, status, parser, detail)
            if status == "duplicate":
                _remember(conn, statement, currency)
        return status
    return "parsed"


def _remember(conn: sqlite3.Connection, statement: Statement, currency: str | None) -> None:
    if currency is not None:
        db.set_account_currency(conn, db.account_key(statement), currency, _now())


def _scrub(detail: str | None, password: str) -> str | None:
    """Defensa extra: ningún mensaje de error guardado puede contener la clave."""
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
