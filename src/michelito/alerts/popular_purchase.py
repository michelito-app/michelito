"""Popular's credit card purchase alert (the "consumo" notification).

An HTML email: a greeting with the holder's name, the card product and its last four digits,
then a table with the columns amount, currency, date, merchant and status (one purchase). The
holder's name and the product are not read: only the card digits and the table. Nothing is read
unless DKIM and DMARC pass for the bank's domain (`common.require_authenticated`).

The table may come horizontal (a header row and a value row) or vertical (label and value side
by side); a text-only body is read like the vertical one. The status goes through
`STATUSES`, a small table that is easy to extend: a status not listed is "unknown" and never
creates a transaction.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from michelito.alerts.common import (
    Alert,
    AlertEmail,
    AlertKind,
    AlertParseError,
    Document,
    Layout,
    fold,
    header_values,
    labeled_values,
    parse_amount,
    parse_day,
    read_html,
    read_text,
    require_authenticated,
    status_kind,
)

NAME = "popular_purchase"
INSTITUTION = "popular"  # the statements' institution (`parsers.popular_card`)
SENDER = "notificaciones@popularenlinea.com"
SENDER_DOMAIN = "popularenlinea.com"

# spanish-data: begin (the bank's own wording, matched literally)
SUBJECT = "notificacion de consumo"
AMOUNT, CURRENCY, DATE, MERCHANT, STATUS = "Monto", "Moneda", "Fecha", "Comercio", "Estatus"
_CARD = re.compile(r"terminada\s+en\s*[:#]?\s*[*xX•.\s]*(\d{4})\b", re.IGNORECASE)
# The bank's status word (folded: lowercase, no accents) -> what it means.
STATUSES: dict[str, AlertKind] = {
    "aprobada": "approved",
    "aprobado": "approved",
    "aprobada exitosamente": "approved",
    "approved": "approved",
    "declinada": "declined",
    "declinado": "declined",
    "rechazada": "declined",
    "rechazado": "declined",
    "denegada": "declined",
    "denegado": "declined",
    "declined": "declined",
    "reversada": "reversed",
    "reversado": "reversed",
    "reverso": "reversed",
    "reversion": "reversed",
    "anulada": "reversed",
    "anulado": "reversed",
    "reversed": "reversed",
}
# The bank's currency text (folded: lowercase, no accents, no "$" or punctuation) -> ISO code.
# The real alerts write the full name («Peso dominicano», «Dólar estadounidense»).
CURRENCIES = {
    "peso dominicano": "DOP",
    "pesos dominicanos": "DOP",
    "peso": "DOP",
    "pesos": "DOP",
    "rd": "DOP",
    "dop": "DOP",
    "dolar estadounidense": "USD",
    "dolares estadounidenses": "USD",
    "dolar": "USD",
    "dolares": "USD",
    "us": "USD",
    "usd": "USD",
}
# spanish-data: end

LABELS = (AMOUNT, CURRENCY, DATE, MERCHANT, STATUS)


def matches(email: AlertEmail) -> bool:
    if email.sender_address != SENDER and email.sender_domain != SENDER_DOMAIN:
        return False
    return SUBJECT in fold(email.subject)


def _documents(email: AlertEmail) -> list[Document]:
    found = []
    if email.html.strip():
        found.append(read_html(email.html))
    if email.text.strip():
        found.append(read_text(email.text))
    return found


def _values(documents: list[Document]) -> tuple[dict[str, str], Layout]:
    for document in documents:
        horizontal = header_values(document, LABELS)
        if horizontal is not None and len(horizontal) == len(LABELS):
            return horizontal, "horizontal"
    best: dict[str, str] = {}
    for document in documents:
        vertical = labeled_values(document, LABELS)
        if len(vertical) > len(best):
            best = vertical
    if best:
        return best, "vertical"
    return {}, "none"


def _required(values: dict[str, str], label: str, field_name: str, layout: Layout) -> str:
    value = values.get(label, "").strip()
    if not value:
        raise AlertParseError(field_name, layout)
    return value


def parse(email: AlertEmail) -> Alert:
    """The purchase, only if DKIM and DMARC pass for the bank's domain (as the trusted
    receiver verified them): anyone can write a From header."""
    require_authenticated(email, SENDER_DOMAIN)
    documents = _documents(email)
    values, layout = _values(documents)
    if layout == "none":
        raise AlertParseError("table", layout)
    card = next(
        (found[1] for doc in documents if (found := _CARD.search(doc.text)) is not None), None
    )
    if card is None:
        raise AlertParseError("card", layout)
    try:
        amount = parse_amount(_required(values, AMOUNT, "amount", layout))
        currency = _currency(_required(values, CURRENCY, "currency", layout), layout)
        day = parse_day(_required(values, DATE, "date", layout))
    except AlertParseError as error:
        raise AlertParseError(error.field, layout) from None
    merchant = " ".join(_required(values, MERCHANT, "merchant", layout).split())
    status = _required(values, STATUS, "status", layout)
    return Alert(
        parser=NAME,
        kind=status_kind(status, STATUSES),
        last4=card,
        amount=amount,
        currency=currency,
        day=day,
        merchant=merchant.upper(),
        status=fold(status)[:40],
    )


def structure(email: AlertEmail) -> tuple[Layout, dict[str, bool], bool]:
    """What the alert has, without any value: the table layout, whether each field (`FIELDS`)
    was found and understood, and whether the status word is in `STATUSES`. For checking real
    alerts in memory (`alerts.inspect`)."""
    try:
        require_authenticated(email, SENDER_DOMAIN)
        signed = True
    except AlertParseError:
        signed = False
    documents = _documents(email)
    values, layout = _values(documents)
    present = {
        "authentication": signed,
        "table": layout != "none",
        "card": any(_CARD.search(doc.text) for doc in documents),
        "amount": _understood(lambda: parse_amount(values.get(AMOUNT, ""))),
        "currency": _understood(lambda: _currency(values.get(CURRENCY, ""), layout)),
        "date": _understood(lambda: parse_day(values.get(DATE, ""))),
        "merchant": bool(values.get(MERCHANT, "").strip()),
        "status": bool(values.get(STATUS, "").strip()),
    }
    known = status_kind(values.get(STATUS, ""), STATUSES) != "unknown"
    return layout, present, known


def _understood(read: Callable[[], object]) -> bool:
    try:
        read()
    except AlertParseError:
        return False
    return True


def _currency(text: str, layout: Layout) -> str:
    """The ISO code of the currency cell, by its folded text (accents and case do not matter)."""
    key = " ".join(re.sub(r"[^a-z ]+", " ", fold(text)).split())
    found = CURRENCIES.get(key)
    if found is None:
        raise AlertParseError("currency", layout)
    return found
