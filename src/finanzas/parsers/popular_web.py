"""Parser de la impresión de "Transacciones" de Popularenlinea (cuenta corriente o de ahorro).

No es un estado: es la página del portal guardada como PDF desde el navegador. Trae la
cuenta ("Cuenta Corriente / <número>"), y una tabla con fecha de posteo, fecha efectiva,
número de cheque, número de referencia, descripción, monto ("-" al final si es débito) y
balance (un sobregiro lleva el "-" delante: "-$5.40"). No imprime totales: lo que se
valida es la cadena de balances, fila por fila (cada balance es el anterior más el monto).
Las filas van de la más vieja a la más nueva.

Una descripción larga se reparte en renglones encima y debajo de la fila (centrada en
ella); por eso cada renglón suelto de la columna de descripción se une a la fila más
cercana en altura, no a la de arriba.

La página no dice la moneda de la cuenta: una de ahorro en dólares imprime "$" a secas,
igual que una en pesos. "$" es peso salvo que quien importa diga otra cosa (`currency`);
"RD$" y "US$" sí la dicen, y si contradicen la indicada la impresión no se acepta.

Se usa la fecha de posteo: es la que ordena la tabla y la cadena de balances, y la que
reparte los movimientos entre estados, así que el rango de la impresión se compara bien
con el periodo de un estado oficial.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finanzas.parsers.common import (
    CREDIT,
    DEBIT,
    Line,
    Page,
    ParseError,
    Section,
    Statement,
    Transaction,
    Word,
    normalize,
    parse_amount,
    parse_date,
)

NAME = "popular_web"
INSTITUTION = "popular"

_ACCOUNT = re.compile(r"^cuenta (?P<type>corriente|de ahorros?) / (?P<number>\d{6,})$")
_KINDS = {
    "corriente": ("checking", "Cuenta corriente"),
    "de ahorro": ("savings", "Cuenta de ahorro"),
    "de ahorros": ("savings", "Cuenta de ahorro"),
}
_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
# El monto negativo lleva el "-" al final ("$5.40-"); el balance negativo (sobregiro), al
# principio ("-$5.40"). Se aceptan las dos formas en las dos columnas, nunca a la vez.
_MONEY = re.compile(
    r"^(?P<lead>-)?(?P<symbol>US\$|RD\$|\$)(?P<amount>\d{1,3}(?:,\d{3})*\.\d{2})(?P<trail>-)?$"
)
CURRENCIES = ("DOP", "USD")
_SYMBOLS = {"RD$": "DOP", "US$": "USD"}  # "$" a secas: la moneda indicada, o peso
_HEADER = ("descripcion", "monto", "balance")
# Un monto está en su columna si su borde derecho queda a esta distancia del encabezado.
_COLUMN_TOLERANCE = 15.0
_ALIGN_TOLERANCE = 3.0
# Un renglón de descripción se une a la fila más cercana si está a esta altura o menos.
_ATTACH_DISTANCE = 24.0


@dataclass(frozen=True)
class _Columns:
    detail_left: float
    amount_right: float
    balance_right: float


@dataclass(frozen=True)
class _Row:
    page: int
    top: float
    posted: date
    reference: str | None
    inline: str
    amount: str
    balance: str
    raw: str


def matches(pages: tuple[Page, ...]) -> bool:
    if not pages:
        return False
    texts = [normalize(line.text) for line in pages[0]]
    return (
        any(_ACCOUNT.match(t) for t in texts)
        and "transacciones" in texts
        and any(_is_header(line) for line in pages[0])
    )


def parse(pages: tuple[Page, ...], currency: str | None = None) -> Statement:
    """`currency`: la moneda de la cuenta, si se sabe (el "$" a secas no la dice)."""
    if currency is not None and currency not in CURRENCIES:
        raise ValueError(f"moneda desconocida: {currency!r}")
    if not pages:
        raise ParseError("documento vacío")
    kind, product, identifier = _account(pages[0])
    rows, details = _rows_and_details(pages)
    if not rows:
        raise ParseError("la impresión no tiene movimientos")
    currency = _currency(rows, currency)
    transactions = tuple(
        _transaction(row, details.get(i, []), currency) for i, row in enumerate(rows)
    )
    first = transactions[0]
    if first.balance is None:  # pragma: no cover - _transaction siempre pone el balance
        raise ParseError("la primera fila no trae balance")
    opening = first.balance - _signed(first)
    section = Section(
        currency=currency,
        previous_balance=opening,
        closing_balance=transactions[-1].balance,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=_sum(transactions, DEBIT),
        printed_credits=_sum(transactions, CREDIT),
        transactions=transactions,
    )
    days = [t.transacted_on for t in transactions]
    return Statement(
        parser=NAME,
        institution=INSTITUTION,
        kind=kind,
        product=product,
        identifier=identifier,
        period_end=max(days),
        due_date=None,
        sections=(section,),
        period_start=min(days),
    )


def _account(page: Page) -> tuple[str, str, str]:
    for line in page:
        found = _ACCOUNT.match(normalize(line.text))
        if found:
            kind, product = _KINDS[found["type"]]
            return kind, product, found["number"]
    raise ParseError("no se encontró la cuenta en la cabecera")


def _is_header(line: Line) -> bool:
    keys = {normalize(word.text) for word in line.words}
    return all(name in keys for name in _HEADER)


def _columns(line: Line) -> _Columns:
    found: dict[str, Word] = {}
    for word in line.words:
        found.setdefault(normalize(word.text), word)
    return _Columns(found["descripcion"].x0, found["monto"].x1, found["balance"].x1)


def _rows_and_details(
    pages: tuple[Page, ...],
) -> tuple[list[_Row], dict[int, list[tuple[int, float, str]]]]:
    """Filas (en orden) y, por fila, los renglones de descripción que le tocan."""
    rows: list[_Row] = []
    loose: list[tuple[int, float, str]] = []
    columns: _Columns | None = None
    for number, page in enumerate(pages):
        # Lo que va antes del encabezado (cabecera de la cuenta, del navegador) no es tabla;
        # una página sin encabezado sigue con las columnas de la anterior.
        in_table = not any(_is_header(line) for line in page)
        for line in page:
            if _is_header(line):
                columns, in_table = _columns(line), True
                continue
            if columns is None or not in_table:
                continue
            row = _row(line, columns, number)
            if row is not None:
                rows.append(row)
            elif _has_money(line, columns):
                # Un monto que no está en una fila sería un movimiento perdido en silencio.
                raise ParseError("renglón con monto fuera de una fila")
            elif _is_detail(line, columns):
                loose.append((number, line.words[0].top, line.text))
    details: dict[int, list[tuple[int, float, str]]] = {}
    for item in loose:
        owner = _nearest_row(rows, item[0], item[1])
        if owner is not None:
            details.setdefault(owner, []).append(item)
    return rows, details


def _row(line: Line, columns: _Columns, page: int) -> _Row | None:
    """La fila que empieza con la fecha de posteo; si algo no está en su columna, falla
    (una fila perdida en silencio solo se notaría si rompe la cadena)."""
    words = line.words
    if not _DATE.match(words[0].text) or words[0].x0 >= columns.detail_left - _ALIGN_TOLERANCE:
        return None
    if len(words) < 4:
        raise ParseError(f"fila del {words[0].text} incompleta")
    amount, balance = words[-2:]
    if not (
        _DATE.match(words[1].text)
        and _in_column(amount, columns.amount_right)
        and _in_column(balance, columns.balance_right)
    ):
        raise ParseError(f"fila del {words[0].text} sin fecha efectiva, monto o balance")
    middle = words[2:-2]
    left = columns.detail_left - _ALIGN_TOLERANCE
    # Las columnas "Nro. de cheque" y "Nro. de referencia" van juntas en `reference`.
    reference = " ".join(w.text for w in middle if w.x0 < left) or None
    inline = " ".join(w.text for w in middle if w.x0 >= left)
    return _Row(
        page=page,
        top=words[0].top,
        posted=parse_date(words[0].text),
        reference=reference,
        inline=inline,
        amount=amount.text,
        balance=balance.text,
        raw=line.text,
    )


def _in_column(word: Word, right: float) -> bool:
    return _match_money(word.text) is not None and abs(word.x1 - right) <= _COLUMN_TOLERANCE


def _match_money(text: str) -> re.Match[str] | None:
    found = _MONEY.match(text)
    if found is None or (found["lead"] and found["trail"]):
        return None
    return found


def _has_money(line: Line, columns: _Columns) -> bool:
    return any(
        _in_column(w, columns.amount_right) or _in_column(w, columns.balance_right)
        for w in line.words
    )


def _is_detail(line: Line, columns: _Columns) -> bool:
    """Renglón suelto de descripción: empieza en su columna (y no trae montos)."""
    return line.words[0].x0 >= columns.detail_left - _ALIGN_TOLERANCE


def _nearest_row(rows: list[_Row], page: int, top: float) -> int | None:
    """Fila de la misma página más cercana en altura; en empate, la de arriba."""
    candidates = [(abs(row.top - top), index) for index, row in enumerate(rows) if row.page == page]
    if not candidates:
        return None
    distance, index = min(candidates)
    return index if distance <= _ATTACH_DISTANCE else None


def _currency(rows: list[_Row], chosen: str | None) -> str:
    symbols = {_symbol(text) for row in rows for text in (row.amount, row.balance)}
    bare = chosen or "DOP"
    currencies = {_SYMBOLS.get(symbol, bare) for symbol in symbols}
    if len(currencies) != 1:
        raise ParseError("la impresión mezcla monedas")
    found = currencies.pop()
    if chosen is not None and found != chosen:
        raise ParseError(f"la impresión dice {found}, pero se indicó {chosen}")
    return found


def _symbol(text: str) -> str:
    found = _match_money(text)
    if found is None:  # pragma: no cover - _row solo acepta montos con símbolo
        raise ParseError(f"monto inválido: {text!r}")
    return found["symbol"]


def _money(text: str) -> Decimal:
    found = _match_money(text)
    if found is None:  # pragma: no cover - _row solo acepta montos con símbolo
        raise ParseError(f"monto inválido: {text!r}")
    value = parse_amount(found["amount"])
    return -value if found["lead"] or found["trail"] else value


def _transaction(row: _Row, details: list[tuple[int, float, str]], currency: str) -> Transaction:
    pieces = sorted([(row.top, row.inline), *((top, text) for _, top, text in details)])
    signed = _money(row.amount)
    return Transaction(
        transacted_on=row.posted,
        posted_on=row.posted,
        description=" ".join(" ".join(text for _, text in pieces).split()),
        amount=abs(signed),
        direction=DEBIT if signed < 0 else CREDIT,
        currency=currency,
        reference=row.reference,
        mcc=None,
        raw_line=row.raw,
        balance=_money(row.balance),
    )


def _signed(item: Transaction) -> Decimal:
    return item.amount if item.direction == CREDIT else -item.amount


def _sum(transactions: tuple[Transaction, ...], direction: str) -> Decimal:
    return sum((t.amount for t in transactions if t.direction == direction), Decimal(0))
