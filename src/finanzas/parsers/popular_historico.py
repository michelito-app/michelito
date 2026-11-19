"""Parser de los estados «históricos» del Banco Popular (cuenta corriente o de ahorro).

Es el formato que manda la ejecutiva del banco: un solo PDF con varios estados mensuales
seguidos de la misma cuenta, con páginas en blanco (o con solo un número) entre uno y otro.
`split` lo corta en estados y `parse` interpreta uno; `ingest` valida y guarda cada tramo
por separado.

Cada estado empieza en la página cuya línea del titular termina en "PAG 1" (las siguientes
del mismo estado dicen "PAG 2", "PAG 3"… y repiten la cabecera). La cabecera trae la fecha
de corte ("12 NOV 2025"), la línea de la cuenta (producto, número, moneda y nombre:
"CTA CTE NOMINA <n> RD$ <nombre>", "AHORRO US$ PERS <n> USD <nombre>", "CUENTA DIGITAL <n>
RD$ <nombre>") y un resumen con cantidades y montos. Cada movimiento empieza con dos fechas
"DD MMM" (entrada y transacción, sin año), puede traer la descripción en la misma línea y
termina con el monto ("-" al final si es débito) y el balance; el detalle sigue en las
líneas de abajo, a la derecha de las fechas. Un monto menor que uno no lleva cero inicial
(".00").

El interés pagado sale como una fila de crédito más y no entra en la cantidad de depósitos
del resumen. Las cantidades se leen pero no invalidan (ver `common.count_notes`): en los
meses con interés del ahorro en dólares el banco cuenta una fila de débito menos aunque los
montos y la cadena de balances cuadren.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
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
    normalize,
    parse_amount,
    resolve_day_month,
)

NAME = "popular_historico"
INSTITUTION = "popular"  # la misma que popular_cuenta y popular_web (ver db.account_key)

_MONTHS = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "SET": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}
_DAY = re.compile(r"^\d{2}$")
_YEAR = re.compile(r"^\d{4}$")
_NUMBER = re.compile(r"^\d{6,}$")
_PAGE = re.compile(r"(?:^|\s)PAG ?(?P<number>\d+)(?: DE \d+)?$")
_MONEY = re.compile(r"^(?:\d{1,3}(?:,\d{3})*)?\.\d{2}-?$")
_A = r"((?:\d{1,3}(?:,\d{3})*)?\.\d{2}-?)"
_SUMMARY = {
    "opening": re.compile(rf"^balance anterior {_A}$"),
    "credits": re.compile(rf"^\+ depositos y otros creditos (?:(\d+) )?{_A}$"),
    "debits": re.compile(rf"^- cheques y otros? debitos (?:(\d+) )?{_A}$"),
    "interest_paid": re.compile(rf"^\+ interes pagado {_A}$"),
    "interest_charged": re.compile(rf"^- interes cargado {_A}$"),
    "closing": re.compile(rf"^balance al corte {_A}$"),
}
_REQUIRED = ("opening", "credits", "debits", "closing")
# Tipo de cuenta según las primeras palabras del producto; lo que sobra es el nombre.
_PRODUCTS = (
    (("CTA", "CTE"), "checking", 2),
    (("CUENTA", "DIGITAL"), "checking", 1),
    (("CTA", "AHO"), "savings", 2),
    (("AHORRO",), "savings", 0),
)
_ACCENTS = {"NOMINA": "Nómina"}
_PLACEHOLDER = re.compile(r"\b(?:RD|US)\$ \.00\b")
# Separadores rotos entre palabras: U+FFFD en UTF-8 leído como latin-1, U+FFFD y el espacio
# duro. El primero va antes: contiene caracteres que no son U+FFFD.
_BROKEN_SPACES = ("ï¿½", "�", " ")
# Una línea de detalle va justo debajo de la anterior y a la derecha de las fechas.
_CONTINUATION_GAP = 14.0
# La primera línea de detalle empieza hasta esta distancia a la derecha de las fechas (en los
# estados, unos 30 puntos); las siguientes, a esta tolerancia de la primera.
_DETAIL_BAND = 60.0
_ALIGN_TOLERANCE = 3.0


@dataclass(frozen=True)
class _Summary:
    opening: Decimal
    credits: Decimal
    debits: Decimal
    closing: Decimal
    credit_count: int | None
    debit_count: int | None


def matches(pages: tuple[Page, ...]) -> bool:
    """Nunca lanza: un producto desconocido también se reconoce, y `parse` dice por qué no
    se puede leer."""
    return any(_page_number(page) == 1 and _account_line(page) is not None for page in pages)


def split(pages: tuple[Page, ...]) -> tuple[tuple[Page, ...], ...]:
    """Corta el PDF en estados: cada "PAG 1" empieza uno y las páginas en blanco (sin texto
    o con solo un número) se descartan. Las páginas con texto antes del primer "PAG 1" van
    juntas en un tramo propio: no se pueden leer como estado, pero así quedan registradas
    como un tramo fallido en vez de perderse sin aviso."""
    parts: list[list[Page]] = []
    for page in pages:
        if _is_blank(page):
            continue
        if _page_number(page) == 1 or not parts:
            parts.append([page])
        else:
            parts[-1].append(page)
    return tuple(tuple(part) for part in parts)


def label(pages: tuple[Page, ...]) -> str | None:
    """Fecha de corte (AAAA-MM-DD) de un tramo que `parse` no pudo leer, si se encuentra."""
    for page in pages[:1]:
        try:
            return _period_end(page).isoformat()
        except ParseError:
            return None
    return None


def parse(pages: tuple[Page, ...]) -> Statement:
    """Interpreta un estado (un tramo de `split`)."""
    if not pages:
        raise ParseError("estado vacío")
    first = pages[0]
    found = _account_line(first)
    if found is None:
        raise ParseError("no se encontró la línea de la cuenta")
    words, identifier, currency = found
    kind, product = _product(words)
    period_end = _period_end(first)
    summary = _summary([normalize(line.text) for page in pages for line in page])
    section = Section(
        currency=currency,
        previous_balance=summary.opening,
        closing_balance=summary.closing,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=summary.debits,
        printed_credits=summary.credits,
        transactions=tuple(_movements(pages, currency, period_end)),
        printed_debit_count=summary.debit_count,
        printed_credit_count=summary.credit_count,
    )
    return Statement(
        parser=NAME,
        institution=INSTITUTION,
        kind=kind,
        product=product,
        identifier=identifier,
        period_end=period_end,
        due_date=None,
        sections=(section,),
        period_start=_period_start(pages, period_end),
    )


def _is_blank(page: Page) -> bool:
    return all(token.isdigit() for line in page for token in line.tokens)


def _page_number(page: Page) -> int | None:
    """Número de página al final de una línea (la del titular): "PAG n", "PAGn" o
    "PAG n DE m"."""
    for line in page:
        found = _PAGE.search(line.text)
        if found:
            return int(found["number"])
    return None


def _account_line(page: Page) -> tuple[tuple[str, ...], str, str] | None:
    """Palabras del producto, número y moneda de la línea "<producto> <número> <moneda>
    <nombre>"; el tipo lo decide `_product` (que sí lanza con un producto desconocido)."""
    for line in page:
        tokens = line.tokens
        for index in range(1, len(tokens) - 1):
            if _NUMBER.match(tokens[index]) and tokens[index + 1] in CURRENCIES:
                return tokens[:index], tokens[index], CURRENCIES[tokens[index + 1]]
    return None


def _product(words: tuple[str, ...]) -> tuple[str, str]:
    for prefix, kind, drop in _PRODUCTS:
        if words[: len(prefix)] == prefix:
            name = words[drop:] or words
            return kind, " ".join(_title(word) for word in name)
    raise ParseError(f"tipo de cuenta desconocido: {' '.join(words)!r}")


def _title(word: str) -> str:
    if "$" in word:
        return word
    return _ACCENTS.get(word, word.capitalize())


def _period_end(page: Page) -> date:
    """Fecha de corte de la cabecera: "DD MMM AAAA" al final de una línea."""
    for line in page:
        tokens = line.tokens
        if (
            len(tokens) >= 3
            and _DAY.match(tokens[-3])
            and tokens[-2] in _MONTHS
            and _YEAR.match(tokens[-1])
        ):
            return date(int(tokens[-1]), _MONTHS[tokens[-2]], int(tokens[-3]))
    raise ParseError("no se encontró la fecha de corte")


def _summary(texts: list[str]) -> _Summary:
    """Totales impresos; el interés pagado o cargado va aparte en el resumen pero sale como
    una fila más, así que se suma a su lado (y a la cantidad, si no es cero)."""
    values: dict[str, Decimal] = {}
    counts: dict[str, int | None] = {}
    for text in texts:
        for name, pattern in _SUMMARY.items():
            found = pattern.match(text)
            if found is None or name in values:
                continue
            values[name] = _amount(found.groups()[-1])
            if name in ("credits", "debits"):
                counts[name] = None if found.group(1) is None else int(found.group(1))
    missing = [name for name in _REQUIRED if name not in values]
    if missing:
        raise ParseError(f"resumen incompleto; falta: {', '.join(missing)}")
    paid = values.get("interest_paid", Decimal(0))
    charged = values.get("interest_charged", Decimal(0))
    return _Summary(
        opening=values["opening"],
        credits=values["credits"] + paid,
        debits=values["debits"] + charged,
        closing=values["closing"],
        credit_count=_with_interest(counts["credits"], paid),
        debit_count=_with_interest(counts["debits"], charged),
    )


def _with_interest(count: int | None, interest: Decimal) -> int | None:
    return None if count is None else count + (1 if interest else 0)


def _amount(text: str) -> Decimal:
    return parse_amount(f"0{text}" if text.startswith(".") else text)


def _period_start(pages: tuple[Page, ...], period_end: date) -> date | None:
    """Día siguiente a la fila "BALANCE ANTERIOR" (el corte anterior), si la hay."""
    for page in pages:
        for line in page:
            tokens = line.tokens
            if (
                len(tokens) == 5
                and _is_date(tokens, 0)
                and tokens[2:4] == ("BALANCE", "ANTERIOR")
                and _MONEY.match(tokens[4])
            ):
                return _date(tokens, 0, period_end) + timedelta(days=1)
    return None


def _movements(pages: tuple[Page, ...], currency: str, period_end: date) -> Iterator[Transaction]:
    for page in pages:
        current: Transaction | None = None
        anchor: Line | None = None  # línea anterior que puede tener detalle debajo
        dates_right = 0.0
        detail_left: float | None = None  # x de la primera línea de detalle de la fila
        for line in page:
            if _is_movement(line):
                if current is not None:
                    yield current
                current = _movement(line, currency, period_end)
                anchor, dates_right, detail_left = line, line.words[3].x1, None
            elif (
                current is not None
                and anchor is not None
                and _continues(line, anchor, dates_right, detail_left)
            ):
                current = replace(current, description=_clean(f"{current.description} {line.text}"))
                anchor = line
                detail_left = line.words[0].x0 if detail_left is None else detail_left
            else:
                anchor = None
        if current is not None:
            yield current


def _is_movement(line: Line) -> bool:
    tokens = line.tokens
    return (
        len(tokens) >= 6
        and _is_date(tokens, 0)
        and _is_date(tokens, 2)
        and _MONEY.match(tokens[-1]) is not None
        and _MONEY.match(tokens[-2]) is not None
    )


def _is_date(tokens: tuple[str, ...], index: int) -> bool:
    return (
        len(tokens) > index + 1
        and _DAY.match(tokens[index]) is not None
        and tokens[index + 1] in _MONTHS
    )


def _continues(line: Line, anchor: Line, dates_right: float, detail_left: float | None) -> bool:
    """Una línea de detalle va justo debajo de la anterior, sin fechas al principio. La
    primera empieza poco después de las fechas (la columna de descripción); las siguientes,
    alineadas con ella. Así un pie de página más a la derecha no se pega a la descripción."""
    first = line.words[0]
    if detail_left is None:
        aligned = dates_right < first.x0 <= dates_right + _DETAIL_BAND
    else:
        aligned = abs(first.x0 - detail_left) <= _ALIGN_TOLERANCE
    return (
        aligned
        and first.top - anchor.words[0].top <= _CONTINUATION_GAP
        and not _is_date(line.tokens, 0)
    )


def _movement(line: Line, currency: str, period_end: date) -> Transaction:
    tokens = line.tokens
    amount = tokens[-2]
    return Transaction(
        transacted_on=_date(tokens, 2, period_end),
        posted_on=_date(tokens, 0, period_end),
        description=_clean(" ".join(tokens[4:-2])),
        amount=abs(_amount(amount)),
        # Por el sufijo y no por el signo: ".00-" es un débito aunque -0.00 no sea negativo.
        direction=DEBIT if amount.endswith("-") else CREDIT,
        currency=currency,
        reference=None,
        mcc=None,
        raw_line=line.text,
        balance=_amount(tokens[-1]),
    )


def _date(tokens: tuple[str, ...], index: int, period_end: date) -> date:
    """Fecha "DD MMM" sin año: la más reciente que no pase del corte (diciembre en un estado de
    enero es del año anterior)."""
    return resolve_day_month(f"{tokens[index]}/{_MONTHS[tokens[index + 1]]:02d}", period_end)


def _clean(text: str) -> str:
    """Quita la columna vacía de cheque ('RD$ .00') que se cuela en el detalle y deja un solo
    espacio donde el PDF trae un separador roto: el carácter de reemplazo (U+FFFD), sus bytes
    UTF-8 leídos como latin-1 ("ï¿½", visto entre las palabras de un nombre) o un espacio
    duro. Sin eso "FULANOï¿½DEï¿½TAL" no se reconoce como el titular."""
    for broken in _BROKEN_SPACES:
        text = text.replace(broken, " ")
    return " ".join(_PLACEHOLDER.sub(" ", text).split())
