"""Parser del estado de cuenta mensual de Banreservas (cuenta de ahorro), bajado del portal.

Una página por mes (más si hay muchos movimientos). Arriba trae "Titular:", una fila
"Número de cuenta | Alias | Fecha del reporte | Balance" con sus valores, y "Movimientos"
con el periodo ("01/01/2026 - 01/02/2026"). La tabla tiene Fecha, Descripción, Débito,
Crédito y Balance: el débito lleva "-" delante y va en su columna; el crédito, sin signo,
en la suya. Las filas van de la más nueva a la más vieja; aquí se devuelven de la más vieja
a la más nueva, como las demás. La descripción sigue en renglones debajo de la fila (la
contraparte de una transferencia): cada renglón suelto se une a la fila de arriba.

No imprime totales ni el balance al corte: el "Balance" de la cabecera es el del día del
reporte. Se valida la cadena de balances fila por fila; el balance anterior sale de la
fila más vieja (su balance menos su monto) y el final es el de la más nueva.

El periodo impreso termina el primer día del mes siguiente, el mismo con que empieza el
estado siguiente (sus balances se encadenan sin hueco): ese último día no es del estado.
El corte es el día anterior, y una fila con la fecha final queda fuera del periodo (error):
si el banco la repitiera en los dos estados se contaría dos veces.

Un estado bajado antes de que cierre el mes (reporte del último día cubierto o antes) es
parcial: se guarda como impresión (`PARTIAL_NAME`, ver `db.PRINTOUT_PARSERS`), no como
estado. Cubre del inicio del periodo al día del reporte: hasta ese día el banco lista todo
lo que hubo (los días sin filas también están cubiertos), y lo de después no lo puede
traer. Su balance final es el de la cabecera, el del día del reporte, y tiene que salir de
la cadena. Cuando llega el mes completo se guarda como estado y gana en esos días.

El estado no dice el tipo de cuenta: se toma como de ahorro (paga intereses). Tampoco dice
la moneda salvo que aparezca "US$"/"USD": sin eso es peso.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
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
    is_amount,
    normalize,
    parse_amount,
    parse_date,
)

NAME = "banreservas_cuenta"
PARTIAL_NAME = "banreservas_parcial"  # el mes en curso: una impresión, no un estado
INSTITUTION = "banreservas"
KIND = "savings"
PRODUCT = "Cuenta de ahorro"

_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_ACCOUNT = re.compile(r"^\d{6,}$")
_PERIOD = re.compile(r"^(?P<start>\d{2}/\d{2}/\d{4}) - (?P<end>\d{2}/\d{2}/\d{4})\b")
_TABLE_HEADER = ("fecha", "descripcion", "debito", "credito", "balance")
_ACCOUNT_HEADER = ("numero de cuenta", "alias", "fecha del reporte", "balance")
_USD = {"us$", "usd"}
_DOP = {"rd$", "dop"}
# Un monto está en su columna si su borde derecho queda a esta distancia del encabezado.
_COLUMN_TOLERANCE = 15.0
_ALIGN_TOLERANCE = 3.0
# Un renglón de descripción sigue a la fila (o a su renglón anterior) a esta altura o menos.
_WRAP_DISTANCE = 16.0
# Pie de página ("Página 1 de 2"): no es parte de una descripción.
_FOOTER = re.compile(r"^(pagina\s+)?\d+\s*(de|/)\s*\d+$|^pagina\s+\d+$")


@dataclass(frozen=True)
class _Columns:
    detail_left: float
    debit_left: float  # una descripción no llega a la columna Débito
    debit_right: float
    credit_right: float
    balance_right: float


@dataclass(frozen=True)
class _Header:
    identifier: str
    report: date
    balance: Decimal  # el del día del reporte


@dataclass(frozen=True)
class _Row:
    day: date
    signed: Decimal
    balance: Decimal
    pieces: tuple[str, ...]
    raw: str


def matches(pages: tuple[Page, ...]) -> bool:
    if not pages:
        return False
    texts = [normalize(line.text) for line in pages[0]]
    return (
        any(t.startswith("titular:") for t in texts)
        and any(all(label in t for label in _ACCOUNT_HEADER) for t in texts)
        and "movimientos" in texts
        and any(_is_table_header(line) for line in pages[0])
    )


def parse(pages: tuple[Page, ...]) -> Statement:
    if not pages:
        raise ParseError("documento vacío")
    header = _header(pages[0])
    start, end = _period(pages[0])
    partial = header.report <= end
    covered = header.report if partial else end
    rows = _rows(pages)
    if not rows:
        raise ParseError("el estado no tiene movimientos")
    outside = [row.day for row in rows if not start <= row.day <= covered]
    if outside:
        raise ParseError(f"movimiento del {outside[0]:%d/%m/%Y} fuera del periodo")
    currency = _currency(pages)
    oldest = rows[-1]
    section = Section(
        currency=currency,
        previous_balance=oldest.balance - oldest.signed,
        # Parcial: el balance de la cabecera es el de hoy, y la cadena tiene que llegar a él.
        closing_balance=header.balance if partial else rows[0].balance,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=None,
        printed_credits=None,
        transactions=tuple(_transaction(row, currency) for row in reversed(rows)),
    )
    return Statement(
        parser=PARTIAL_NAME if partial else NAME,
        institution=INSTITUTION,
        kind=KIND,
        product=PRODUCT,
        identifier=header.identifier,
        period_end=covered,
        due_date=None,
        sections=(section,),
        period_start=start,
    )


def _header(page: Page) -> _Header:
    """Número de cuenta, fecha y balance del reporte: la línea que sigue a su encabezado."""
    for index, line in enumerate(page[:-1]):
        text = normalize(line.text)
        if all(label in text for label in _ACCOUNT_HEADER):
            words = page[index + 1].tokens
            dates = [w for w in words if _DATE.match(w)]
            if words and _ACCOUNT.match(words[0]) and len(dates) == 1 and is_amount(words[-1]):
                return _Header(words[0], parse_date(dates[0]), parse_amount(words[-1]))
            break
    raise ParseError("no se encontró la cuenta, la fecha ni el balance del reporte")


def _period(page: Page) -> tuple[date, date]:
    """Primer y último día cubiertos: la fecha final impresa ya es del estado siguiente."""
    for index, line in enumerate(page[:-1]):
        if normalize(line.text) == "movimientos":
            found = _PERIOD.match(page[index + 1].text)
            if found:
                start, after = parse_date(found["start"]), parse_date(found["end"])
                if start < after:
                    return start, after - timedelta(days=1)
            break
    raise ParseError("no se encontró el periodo de los movimientos")


def _currency(pages: tuple[Page, ...]) -> str:
    """La moneda que dice la cabecera (hasta los títulos de la tabla), nunca una descripción."""
    tokens = {normalize(w) for line in _header_lines(pages[0]) for w in line.tokens}
    dollars, pesos = bool(tokens & _USD), bool(tokens & _DOP)
    if dollars and pesos:
        raise ParseError("el estado mezcla monedas")
    return "USD" if dollars else "DOP"


def _header_lines(page: Page) -> list[Line]:
    lines = sorted(page, key=lambda item: item.words[0].top)
    end = next((i for i, line in enumerate(lines) if _is_table_header(line)), len(lines) - 1)
    return lines[: end + 1]


def _is_table_header(line: Line) -> bool:
    return tuple(normalize(word.text) for word in line.words) == _TABLE_HEADER


def _columns(line: Line) -> _Columns:
    words = line.words
    return _Columns(words[1].x0, words[2].x0, words[2].x1, words[3].x1, words[4].x1)


def _rows(pages: tuple[Page, ...]) -> list[_Row]:
    """Filas en el orden del estado, cada una con sus renglones de descripción."""
    rows: list[_Row] = []
    columns: _Columns | None = None
    for page in pages:
        # Lo que va antes del encabezado de la tabla (la cabecera) no es tabla; una página
        # sin encabezado sigue con las columnas de la anterior. Arriba de una página nueva,
        # los renglones de descripción siguen a la última fila de la anterior (`carry`).
        in_table = not any(_is_table_header(line) for line in page)
        last_top: float | None = None
        carry = bool(rows)
        for line in sorted(page, key=lambda item: item.words[0].top):
            if _is_table_header(line):
                columns, in_table, last_top = _columns(line), True, None
                continue
            if columns is None or not in_table:
                continue
            top = line.words[0].top
            row = _row(line, columns)
            if row is not None:
                rows.append(row)
                last_top, carry = top, False
            elif _has_money(line, columns):
                raise ParseError("renglón con monto fuera de una fila")
            elif _is_footer(line):
                last_top = None  # el pie termina la fila, pero no la que sigue en otra página
            elif _in_detail(line, columns) and (carry or _near(line, last_top)):
                rows[-1] = _with_piece(rows[-1], line.text)
                last_top = top
            else:
                last_top, carry = None, False  # otro texto: la fila ya terminó
    return rows


def _row(line: Line, columns: _Columns) -> _Row | None:
    words = line.words
    if not _DATE.match(words[0].text) or words[0].x0 >= columns.detail_left - _ALIGN_TOLERANCE:
        return None
    money = [w for w in words[1:] if _money_column(w, columns) is not None]
    if len(money) != 2 or money[1] is not words[-1]:
        raise ParseError(f"fila del {words[0].text} sin un monto y su balance")
    amount, balance = money
    if _money_column(balance, columns) != "balance":
        raise ParseError(f"fila del {words[0].text} sin balance")
    signed = parse_amount(amount.text)
    column = _money_column(amount, columns)
    if column == "debit" and signed >= 0:
        raise ParseError(f"fila del {words[0].text}: débito sin signo")
    if column == "credit" and signed <= 0:
        raise ParseError(f"fila del {words[0].text}: crédito con signo")
    if column == "balance":
        raise ParseError(f"fila del {words[0].text} sin débito ni crédito")
    detail = " ".join(w.text for w in words[1:] if w is not amount and w is not balance)
    return _Row(
        day=parse_date(words[0].text),
        signed=signed,
        balance=parse_amount(balance.text),
        pieces=(detail,) if detail else (),
        raw=line.text,
    )


def _money_column(word: Word, columns: _Columns) -> str | None:
    if not is_amount(word.text):
        return None
    for name, right in (
        ("debit", columns.debit_right),
        ("credit", columns.credit_right),
        ("balance", columns.balance_right),
    ):
        if abs(word.x1 - right) <= _COLUMN_TOLERANCE:
            return name
    return None


def _has_money(line: Line, columns: _Columns) -> bool:
    return any(_money_column(w, columns) is not None for w in line.words)


def _in_detail(line: Line, columns: _Columns) -> bool:
    """Empieza en la columna Descripción: ni antes, ni en la de Débito o más a la derecha."""
    left = line.words[0].x0
    return columns.detail_left - _ALIGN_TOLERANCE <= left < columns.debit_left - _ALIGN_TOLERANCE


def _near(line: Line, last_top: float | None) -> bool:
    """Pegado a la fila (o a su renglón anterior)."""
    return last_top is not None and line.words[0].top - last_top <= _WRAP_DISTANCE


def _is_footer(line: Line) -> bool:
    return _FOOTER.match(normalize(line.text)) is not None


def _with_piece(row: _Row, text: str) -> _Row:
    return _Row(row.day, row.signed, row.balance, (*row.pieces, text), row.raw)


def _transaction(row: _Row, currency: str) -> Transaction:
    return Transaction(
        transacted_on=row.day,
        posted_on=row.day,
        description=" ".join(" ".join(row.pieces).split()),
        amount=abs(row.signed),
        direction=DEBIT if row.signed < 0 else CREDIT,
        currency=currency,
        reference=None,
        mcc=None,
        raw_line=row.raw,
        balance=row.balance,
    )
