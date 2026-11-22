"""Amazon's order confirmation and shipment emails.

What they carry (and nothing else is read): the order number(s), a total, and, in a shipment,
the shipment's identifier inside its tracking link. They carry no item names, prices or payment
method; the subject gives a count and a list of categories ("Ordered 6 items: Kitchen, Tools,
and more"), kept as the summary.

- An order confirmation can hold several orders. Each is closed by a "Grand Total:" line; every
  "Order #" since the previous total must name the same order.
- A shipment has one "Total". One package can combine items of two orders: the visible order
  number and the one in the tracking link are both kept.

Both parts are understood: the plain text (short lines, "35.8 USD") and the HTML (text nodes,
"$35.80", links behind a redirect, an invisible mark before the order number). A link counts
only on Amazon's own host. Nothing is read unless DKIM and DMARC pass for the sender's domain.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from michelito.alerts.common import AlertEmail, AlertParseError, fold, require_authenticated
from michelito.receipts.common import (
    ORDERS_MAX,
    RECEIPTS_MAX,
    REFERENCE_MAX,
    SUMMARY_MAX,
    Part,
    Receipt,
    ReceiptKind,
    clean,
    parts,
)

MERCHANT = "Amazon"
SENDER_DOMAIN = "amazon.com"
HOSTS = ("www.amazon.com", "amazon.com")
CURRENCY = "USD"
_REDIRECT_PATH = "/gp/r.html"
_REDIRECT_PARAMETER = "U"
_TRACKING_PATH = "/progress-tracker/"
_ORDER_PAGE = "https://www.amazon.com/gp/css/summary/print.html?orderID={order}"

_ORDER = re.compile(r"\d{3}-\d{7}-\d{7}", re.ASCII)
_ORDER_LABEL = "order #"
_REFERENCE = re.compile(rf"[A-Za-z0-9]{{1,{REFERENCE_MAX}}}", re.ASCII)
# Up to nine whole digits: more is not a purchase (and would not fit the stored cents).
_AMOUNT = re.compile(
    r"(\$)?\s*(\d{1,3}(?:,\d{3}){1,2}|\d{1,9})(?:\.(\d{1,2}))?(?:\s*(USD))?", re.ASCII
)
_SUBJECT = re.compile(r"[A-Za-z]+\s+(\d{1,4})\s+items?:\s*(.*)", re.IGNORECASE | re.ASCII)


@dataclass(frozen=True)
class Reader:
    """One kind of Amazon email: who sends it, how its subject starts, what its total is called."""

    NAME: str
    kind: ReceiptKind
    sender: str
    subject: str  # the subject's first word
    total: str  # the total's label, folded, without its colon

    def matches(self, email: AlertEmail) -> bool:
        if email.sender_address != self.sender:
            return False
        words = fold(email.subject).replace(":", " ").split()
        return bool(words) and words[0] == self.subject

    def parse(self, email: AlertEmail) -> tuple[Receipt, ...]:
        return _parse(self, email)


ORDER = Reader("amazon_order", "order", "auto-confirm@amazon.com", "ordered", "grand total")
SHIPMENT = Reader("amazon_shipment", "shipment", "shipment-tracking@amazon.com", "shipped", "total")
READERS = (ORDER, SHIPMENT)


def parse(email: AlertEmail) -> tuple[Receipt, ...]:
    """The receipts of an Amazon email (one per order, or one shipment)."""
    reader = next((found for found in READERS if found.matches(email)), None)
    if reader is None:
        raise AlertParseError("table")
    return reader.parse(email)


def read_amount(text: str) -> Decimal:
    """'35.8 USD', '$35.80' or '$1,234.56' -> Decimal (positive, in dollars). A number with
    neither the sign nor the code is not an amount."""
    match = _AMOUNT.fullmatch(clean(text))
    if match is None or not (match[1] or match[4]):
        raise AlertParseError("amount")
    try:
        value = Decimal(f"{match[2].replace(',', '')}.{(match[3] or '').ljust(2, '0')}")
    except InvalidOperation:
        raise AlertParseError("amount") from None
    if value <= 0:
        raise AlertParseError("amount")
    return value


def _parse(reader: Reader, email: AlertEmail) -> tuple[Receipt, ...]:
    require_authenticated(email, SENDER_DOMAIN)
    read = _orders if reader.kind == "order" else _shipment
    available = parts(email, _REDIRECT_PATH, _REDIRECT_PARAMETER, HOSTS)
    found = _first_understood(available, reader, read)
    count, summary = _subject(email.subject)
    return tuple(
        Receipt(
            parser=reader.NAME,
            merchant=MERCHANT,
            kind=reader.kind,
            orders=orders,
            amount=amount,
            currency=CURRENCY,
            reference=reference,
            summary=summary,
            item_count=count,
            link=_ORDER_PAGE.format(order=orders[0]),
        )
        for orders, amount, reference in found
    )


_Found = tuple[tuple[str, ...], Decimal, str]  # order numbers, amount, shipment identifier


def _first_understood(
    available: list[Part], reader: Reader, read: Callable[[Part, Reader], list[_Found]]
) -> list[_Found]:
    """What the first part that can be read says; the last failure if none can."""
    failure = AlertParseError("amount")
    for part in available:
        try:
            return read(part, reader)
        except AlertParseError as error:
            failure = error
    raise failure


def _subject(subject: str) -> tuple[int | None, str]:
    """The count and the category list of "Ordered 6 items: Kitchen, Tools, and more"."""
    match = _SUBJECT.fullmatch(clean(subject))
    if match is None:
        return None, ""
    return int(match[1]), match[2][:SUMMARY_MAX].strip()


def _order_on(lines: tuple[str, ...], index: int) -> str | None:
    """The order number an "Order #" line names: on the same line or on the next one."""
    line = lines[index]
    if not fold(line).startswith(_ORDER_LABEL):
        return None
    following = lines[index + 1] if index + 1 < len(lines) else ""
    for candidate in (line[len(_ORDER_LABEL) :], following):
        if _ORDER.fullmatch(candidate.strip()):
            return candidate.strip()
    return None


def _is_label(line: str, label: str) -> bool:
    return fold(line).rstrip(":").strip() == label


def _amount_after(lines: tuple[str, ...], index: int) -> Decimal:
    if index + 1 >= len(lines):
        raise AlertParseError("amount")
    return read_amount(lines[index + 1])


def _orders(part: Part, reader: Reader) -> list[_Found]:
    """Every order of a confirmation: the "Order #" lines up to each total name one order."""
    found: list[_Found] = []
    pending: list[str] = []
    for index in range(len(part.lines)):
        order = _order_on(part.lines, index)
        if order is not None:
            pending.append(order)
        elif _is_label(part.lines[index], reader.total):
            if len(set(pending)) != 1:
                raise AlertParseError("order")
            found.append(((pending[0],), _amount_after(part.lines, index), ""))
            pending = []
    if not found:
        raise AlertParseError("amount")
    if len(found) > RECEIPTS_MAX:
        raise AlertParseError("order")
    return found


def _shipment(part: Part, reader: Reader) -> list[_Found]:
    visible = [
        order
        for index in range(len(part.lines))
        if (order := _order_on(part.lines, index)) is not None
    ]
    tracking = [
        link for link in part.links if link.host in HOSTS and link.path.startswith(_TRACKING_PATH)
    ]
    linked = _valid(_ORDER, (value for link in tracking for value in link.query.get("orderId", ())))
    orders = tuple(dict.fromkeys([*visible, *linked]))
    if not orders or len(orders) > ORDERS_MAX:
        raise AlertParseError("order")
    totals = [i for i in range(len(part.lines)) if _is_label(part.lines[i], reader.total)]
    if len(totals) != 1:
        raise AlertParseError("amount")
    references = _valid(
        _REFERENCE, (value for link in tracking for value in link.query.get("shipmentId", ()))
    )
    return [(orders, _amount_after(part.lines, totals[0]), references[0] if references else "")]


def _valid(pattern: re.Pattern[str], values: Iterable[str]) -> list[str]:
    return [value for value in values if pattern.fullmatch(value)]
