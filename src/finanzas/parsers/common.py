"""Tipos y utilidades compartidas por los parsers de estados de cuenta."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

DEBIT = "debit"
CREDIT = "credit"
CURRENCIES = {"RD$": "DOP", "DOP": "DOP", "US$": "USD", "USD": "USD"}
LINE_TOLERANCE = 2.5
# Diferencia mínima (en puntos) entre las dos columnas más cercanas a un monto.
COLUMN_MARGIN = 3.0
POSTING_TOLERANCE = timedelta(days=7)

_AMOUNT = re.compile(r"^(?P<lead>-)?(?P<int>\d{1,3}(?:,\d{3})+|\d+)\.(?P<dec>\d{2})(?P<trail>-)?$")
_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d")


class ParseError(ValueError):
    """El documento no tiene la forma que el parser espera."""


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float


@dataclass(frozen=True)
class Line:
    words: tuple[Word, ...]

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(word.text for word in self.words)

    @property
    def text(self) -> str:
        return " ".join(self.tokens)


Page = tuple[Line, ...]


@dataclass(frozen=True)
class Transaction:
    transacted_on: date
    posted_on: date | None
    description: str
    amount: Decimal  # siempre positivo; el sentido va en `direction`
    direction: str
    currency: str
    reference: str | None
    mcc: str | None
    raw_line: str
    balance: Decimal | None = None  # balance impreso tras el movimiento, si el banco lo da


@dataclass(frozen=True)
class Section:
    """La parte de un estado en una sola moneda."""

    currency: str
    previous_balance: Decimal | None
    closing_balance: Decimal | None
    minimum_payment: Decimal | None
    credit_limit: Decimal | None
    printed_debits: Decimal | None
    printed_credits: Decimal | None
    transactions: tuple[Transaction, ...]
    # Cantidad de movimientos que imprime el resumen, si la imprime y el parser la lee.
    printed_debit_count: int | None = None
    printed_credit_count: int | None = None


@dataclass(frozen=True)
class Statement:
    parser: str
    institution: str
    kind: str
    product: str
    identifier: str
    period_end: date
    due_date: date | None
    sections: tuple[Section, ...]
    period_start: date | None = None  # primer día cubierto, si el documento lo dice

    @property
    def is_liability(self) -> bool:
        return self.kind == "credit_card"


def is_amount(text: str) -> bool:
    return _AMOUNT.match(text) is not None


def parse_amount(text: str) -> Decimal:
    match = _AMOUNT.match(text)
    if match is None:
        raise ParseError(f"monto inválido: {text!r}")
    value = Decimal(f"{match['int'].replace(',', '')}.{match['dec']}")
    return -value if match["lead"] or match["trail"] else value


def parse_date(text: str) -> date:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"fecha inválida: {text!r}")


def resolve_day_month(text: str, reference: date) -> date:
    """Convierte 'dd/mm' en la fecha más reciente que no sea posterior al corte.

    Un movimiento no puede ser posterior a la fecha de corte; se tolera
    `POSTING_TOLERANCE` por fechas de aplicación tardías.
    """
    try:
        day, month = (int(part) for part in text.split("/"))
    except ValueError as exc:
        raise ParseError(f"fecha inválida: {text!r}") from exc
    latest = reference + POSTING_TOLERANCE
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate <= latest:
            candidates.append(candidate)
    if not candidates:
        raise ParseError(f"fecha inválida: {text!r}")
    return max(candidates)


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


def group_lines(words: Iterable[Word], tolerance: float = LINE_TOLERANCE) -> Page:
    """Agrupa palabras en líneas por su altura y las ordena de izquierda a derecha."""
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if rows and abs(word.top - rows[-1][0].top) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    return tuple(Line(tuple(sorted(row, key=lambda w: w.x0))) for row in rows)


def column_positions(line: Line, names: tuple[str, ...]) -> dict[str, float] | None:
    """Borde derecho de cada encabezado de columna, si la línea los tiene todos."""
    found: dict[str, float] = {}
    for word in line.words:
        key = normalize(word.text)
        if key in names and key not in found:
            found[key] = word.x1
    return found if len(found) == len(names) else None


def nearest_column(word: Word, columns: Mapping[str, float]) -> str:
    """Columna con el borde derecho más cercano al de la palabra (montos alineados a la derecha).

    Si la palabra queda casi a igual distancia de dos columnas, no se adivina.
    """
    ranked = sorted(columns, key=lambda name: abs(columns[name] - word.x1))
    if len(ranked) > 1:
        best, runner_up = (abs(columns[name] - word.x1) for name in ranked[:2])
        if runner_up - best < COLUMN_MARGIN:
            raise ParseError(f"no se puede decidir la columna de un monto en x={word.x1:.0f}")
    return ranked[0]


def validate_statement(statement: Statement) -> tuple[str, ...]:
    if not statement.sections:
        return ("el estado no tiene secciones",)
    return tuple(
        problem
        for section in statement.sections
        for problem in validate_section(section, liability=statement.is_liability)
    )


def count_notes(statement: Statement) -> tuple[str, ...]:
    """Diferencias entre las filas leídas y la cantidad que imprime el resumen. No invalidan
    el estado: los montos y la cadena de balances ya lo validan, y el banco a veces cuenta
    una fila menos (visto en los meses con interés pagado del ahorro del Popular)."""
    notes = []
    for section in statement.sections:
        for label, direction, count in (
            ("débitos", DEBIT, section.printed_debit_count),
            ("créditos", CREDIT, section.printed_credit_count),
        ):
            rows = sum(1 for t in section.transactions if t.direction == direction)
            if count is not None and rows != count:
                notes.append(f"{section.currency}: {label}: {rows} filas ≠ {count} impresas")
    return tuple(notes)


def validate_section(section: Section, *, liability: bool) -> tuple[str, ...]:
    """Compara lo leído contra los totales que imprime el banco."""
    debits = _total(section, DEBIT)
    credits = _total(section, CREDIT)
    problems: list[str] = []
    checks = 0
    for label, read, printed in (
        ("débitos", debits, section.printed_debits),
        ("créditos", credits, section.printed_credits),
    ):
        if printed is None:
            continue
        checks += 1
        if read != printed:
            problems.append(f"{section.currency}: {label} leídos {read} ≠ impresos {printed}")
    if section.previous_balance is not None and section.closing_balance is not None:
        checks += 1
        change = debits - credits if liability else credits - debits
        expected = section.previous_balance + change
        if expected != section.closing_balance:
            problems.append(
                f"{section.currency}: balance anterior {section.previous_balance} con movimientos "
                f"da {expected} ≠ balance al corte {section.closing_balance}"
            )
    chain = _chain_problems(section, liability=liability)
    if chain is not None:
        checks += 1
        problems.extend(chain)
    if checks == 0:
        problems.append(f"{section.currency}: no hay totales impresos para validar")
    return tuple(problems)


def _chain_problems(section: Section, *, liability: bool) -> list[str] | None:
    """Revisa el balance impreso fila por fila; None si el documento no imprime balances."""
    balances = [t.balance for t in section.transactions]
    if section.previous_balance is None or not balances or None in balances:
        return None
    problems = []
    running = section.previous_balance
    for index, item in enumerate(section.transactions, start=1):
        grows = (item.direction == DEBIT) == liability
        running += item.amount if grows else -item.amount
        if item.balance is not None and running != item.balance:
            problems.append(
                f"{section.currency}: la fila {index} ({item.transacted_on}) imprime balance "
                f"{item.balance}, pero el anterior con su monto da {running}"
            )
            running = item.balance
    return problems


def _total(section: Section, direction: str) -> Decimal:
    return sum((t.amount for t in section.transactions if t.direction == direction), Decimal(0))
