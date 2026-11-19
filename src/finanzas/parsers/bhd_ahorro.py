"""Parser del estado de cuenta de ahorro del Banco BHD.

Los datos de cabecera van en una columna derecha: cada etiqueta en una línea
y su valor en la siguiente. Las transacciones tienen columnas de débitos,
créditos y balance; al final se imprimen la cantidad y suma de cada tipo.

Hay dos variantes de la tabla. La del correo fecha con "dd/mm" y solo llena la
columna del movimiento. La del portal fecha con "dd/mm/aaaa" y llena ambas
columnas ("0.00" en la que no aplica): el sentido lo da la columna con monto.

El portal también deja bajar el mes en curso, antes del corte: imprime la fecha de corte
del mes (posterior a la última fila) y "Balance final" en 0.00, así que no cuadra como
estado. Ese documento es parcial y se guarda como impresión (`PARTIAL_NAME`, ver
`db.PRINTOUT_PARSERS`), no como estado. El portal no imprime cuándo se bajó: cubre del
inicio del mes (la línea "Balance inicial: dd/mm/aaaa" de la tabla, o el día siguiente a
la de "Balance anterior:") hasta la fecha de la última fila, lo único que se sabe que ya
estaba listado. Los días siguientes hasta la descarga quedan sin cubrir: es preferible a
dar por cubiertos días de los que quizá falten posteos. Su balance final es el de la
columna Balance de la última fila, y se valida la cadena de balances fila por fila (y los
totales impresos) en vez del "Balance final". Cuando llega el mes completo se guarda como
estado y gana en esos días. Un mes que de verdad cierra en 0.00 sin filas hasta el corte
también queda como impresión: cuenta mientras no haya estado y no bloquea el oficial.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from finanzas.parsers.common import (
    CREDIT,
    CURRENCIES,
    DEBIT,
    Line,
    Page,
    ParseError,
    Section,
    Statement,
    Transaction,
    Word,
    column_positions,
    is_amount,
    nearest_column,
    normalize,
    parse_amount,
    parse_date,
    resolve_day_month,
)

NAME = "bhd_ahorro"
PARTIAL_NAME = "bhd_ahorro_parcial"  # el mes en curso bajado del portal: una impresión
INSTITUTION = "bhd"

_COLUMNS = ("debitos", "creditos", "balance")
_MOVEMENT_COLUMNS = ("debitos", "creditos")
_DAY_MONTH = re.compile(r"^\d{2}/\d{2}$")
_FULL_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_REFERENCE = re.compile(r"^\d{6,}$")
_DEBIT_TOTAL = re.compile(r"\b(?P<count>\d+)\s?DEBITOS\s+(?P<amount>[\d,]+\.\d{2})\b")
_CREDIT_TOTAL = re.compile(r"\b(?P<count>\d+)\s?CREDITOS\s+(?P<amount>[\d,]+\.\d{2})\b")
# Primera línea de la tabla del portal: "Balance inicial: 01/01/2026" es el primer día del
# periodo; "Balance anterior: 31/12/2025", el corte anterior.
_OPENING = re.compile(r"^balance (?P<kind>inicial|anterior): (?P<day>\d{2}/\d{2}/\d{4})\b")
_ACCOUNT_LABEL = "numero de cuenta"
_VALUE_SEARCH_LINES = 4
# El formato 2025 no imprime la moneda; esas cuentas son en pesos.
_DEFAULT_CURRENCY = "DOP"


def matches(pages: tuple[Page, ...]) -> bool:
    if not pages:
        return False
    texts = [normalize(line.text) for line in pages[0]]
    return any(t.endswith(_ACCOUNT_LABEL) for t in texts) and any(
        t.endswith("balance inicial") for t in texts
    )


def parse(pages: tuple[Page, ...]) -> Statement:
    if not pages:
        raise ParseError("documento vacío")
    first = pages[0]
    account = _value_after(first, _ACCOUNT_LABEL, lambda text: "-" in text)
    currency_text = _optional_value(first, "moneda", lambda text: text in CURRENCIES)
    currency = CURRENCIES[currency_text] if currency_text else _DEFAULT_CURRENCY
    period_end = parse_date(_value_after(first, "fecha de corte", _is_date))
    opening = parse_amount(_value_after(first, "balance inicial", is_amount))
    printed_final = _optional_value(first, "balance final", is_amount)
    movements = _read_movements(pages, currency, period_end)
    totals = _read_totals(pages)
    statement = Statement(
        parser=NAME,
        institution=INSTITUTION,
        kind="savings",
        product="Cuenta de ahorro",
        identifier=account.split("-", 1)[-1],
        period_end=period_end,
        due_date=None,
        sections=(),
    )
    if _is_partial(printed_final, movements, period_end):
        # La cadena de balances reemplaza al "Balance final" 0.00: cada fila lleva el suyo.
        chained = [
            replace(m, transaction=replace(m.transaction, balance=m.balance)) for m in movements
        ]
        return _partial(statement, pages, _section(currency, opening, None, totals, chained))
    if printed_final is not None:
        closing = parse_amount(printed_final)
    else:
        closing = movements[-1].balance if movements else opening
    section = _section(currency, opening, closing, totals, movements)
    return replace(statement, sections=(section,))


def _section(
    currency: str,
    opening: Decimal,
    closing: Decimal | None,
    totals: _Totals,
    movements: list[_Movement],
) -> Section:
    return Section(
        currency=currency,
        previous_balance=opening,
        closing_balance=closing,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=totals.debits,
        printed_credits=totals.credits,
        transactions=tuple(m.transaction for m in movements),
    )


def _is_partial(printed_final: str | None, movements: list[_Movement], cut: date) -> bool:
    """¿Es el mes en curso? Portal, "Balance final" en 0.00 y sin filas hasta el corte.

    Un mes que de verdad cierra en 0.00 también cae aquí: como impresión es seguro (cuenta
    mientras no haya estado oficial y no impide importar luego el mes completo).
    """
    if printed_final is None or parse_amount(printed_final) != 0 or not movements:
        return False
    return all(m.portal for m in movements) and movements[-1].transaction.transacted_on < cut


def _partial(statement: Statement, pages: tuple[Page, ...], section: Section) -> Statement:
    """El mes en curso: del inicio del periodo a la última fila, cerrando en su balance."""
    start = _period_start(pages)
    # Las filas del portal van de la más vieja a la más nueva: la última da el fin y el balance.
    last = section.transactions[-1].transacted_on
    outside = [t.transacted_on for t in section.transactions if t.transacted_on < start]
    if outside:
        raise ParseError(f"movimiento del {outside[0]:%d/%m/%Y} antes del inicio del periodo")
    return replace(
        statement,
        parser=PARTIAL_NAME,
        period_end=last,
        period_start=start,
        sections=(replace(section, closing_balance=section.transactions[-1].balance),),
    )


def _period_start(pages: tuple[Page, ...]) -> date:
    for line in (line for page in pages for line in page):
        found = _OPENING.match(normalize(line.text))
        if found:
            day = parse_date(found["day"])
            return day if found["kind"] == "inicial" else day + timedelta(days=1)
    raise ParseError("no se encontró el inicio del periodo del mes en curso")


def _value_after(page: Page, label: str, accept: Callable[[str], bool]) -> str:
    value = _optional_value(page, label, accept)
    if value is None:
        raise ParseError(f"no se encontró '{label}' en el estado de ahorro")
    return value


def _optional_value(page: Page, label: str, accept: Callable[[str], bool]) -> str | None:
    """Primer valor aceptable escrito debajo de la etiqueta, en su misma columna.

    La columna izquierda (nombre y dirección) se intercala con las etiquetas,
    así que se descartan las palabras que terminan antes de donde empieza la
    etiqueta; `accept` salta fragmentos sueltos de texto que no son el valor.
    La etiqueta se compara sin mayúsculas ni acentos (cambian entre formatos).
    """
    label_size = len(label.split())
    for index, line in enumerate(page):
        if not normalize(line.text).endswith(label):
            continue
        label_left = line.words[-label_size].x0
        for following in page[index + 1 : index + 1 + _VALUE_SEARCH_LINES]:
            for word in following.words:
                if word.x1 > label_left and accept(word.text):
                    return word.text
    return None


def _is_date(text: str) -> bool:
    try:
        parse_date(text)
    except ParseError:
        return False
    return True


@dataclass(frozen=True)
class _Movement:
    transaction: Transaction  # sin balance, salvo en el mes en curso (ver `parse`)
    balance: Decimal  # el de la columna Balance, tras el movimiento
    portal: bool  # fila del portal (fecha dd/mm/aaaa)


def _read_movements(pages: tuple[Page, ...], currency: str, period_end: date) -> list[_Movement]:
    columns: dict[str, float] | None = None
    found: list[_Movement] = []
    for line in (line for page in pages for line in page):
        if header := column_positions(line, _COLUMNS):
            columns = header
        elif columns is not None and _is_movement(line.tokens):
            transaction, balance = _movement(line, columns, currency, period_end)
            found.append(
                _Movement(transaction, balance, _FULL_DATE.match(line.tokens[0]) is not None)
            )
    return found


def _is_movement(tokens: tuple[str, ...]) -> bool:
    if len(tokens) < 4 or not (is_amount(tokens[-1]) and is_amount(tokens[-2])):
        return False
    if _FULL_DATE.match(tokens[0]):
        return len(tokens) >= 5 and is_amount(tokens[-3])
    return _DAY_MONTH.match(tokens[0]) is not None


def _movement(
    line: Line, columns: Mapping[str, float], currency: str, period_end: date
) -> tuple[Transaction, Decimal]:
    tokens = line.tokens
    has_reference = _REFERENCE.match(tokens[1]) is not None
    movement_columns = {name: columns[name] for name in _MOVEMENT_COLUMNS}
    if _FULL_DATE.match(tokens[0]):
        transacted_on = parse_date(tokens[0])
        amount, column = _portal_amount(line.words[-3:-1], movement_columns)
        amounts_from = -3
    else:
        transacted_on = resolve_day_month(tokens[0], period_end)
        movement = line.words[-2]
        amount = parse_amount(movement.text)
        column = nearest_column(movement, movement_columns)
        amounts_from = -2
    transaction = Transaction(
        transacted_on=transacted_on,
        posted_on=None,
        description=" ".join(tokens[2 if has_reference else 1 : amounts_from]),
        amount=abs(amount),
        direction=CREDIT if column == "creditos" else DEBIT,
        currency=currency,
        reference=tokens[1] if has_reference else None,
        mcc=None,
        raw_line=line.text,
    )
    return transaction, parse_amount(tokens[-1])


def _portal_amount(words: tuple[Word, ...], columns: Mapping[str, float]) -> tuple[Decimal, str]:
    """Monto y columna de una fila del portal: un monto por columna, solo uno distinto de cero."""
    by_column = {nearest_column(word, columns): parse_amount(word.text) for word in words}
    if len(by_column) != len(columns):
        raise ParseError("una fila del portal no tiene un monto en cada columna")
    filled = [(amount, name) for name, amount in by_column.items() if amount != 0]
    if len(filled) != 1:
        raise ParseError("una fila del portal no tiene monto en exactamente una columna")
    return filled[0]


@dataclass(frozen=True)
class _Totals:
    debits: Decimal
    credits: Decimal


def _read_totals(pages: tuple[Page, ...]) -> _Totals:
    """Suma impresa de débitos y de créditos (la cantidad impresa no es confiable).

    Son obligatorias: sin ellas la única comprobación sería el balance de la
    última fila leída, que se deriva de lo mismo que se quiere validar.
    """
    text = " ".join(line.text for page in pages for line in page)
    debit = _DEBIT_TOTAL.search(text)
    credit = _CREDIT_TOTAL.search(text)
    if debit is None or credit is None:
        raise ParseError("no se encontraron los totales impresos de débitos y créditos")
    return _Totals(
        debits=parse_amount(debit["amount"]),
        credits=parse_amount(credit["amount"]),
    )
