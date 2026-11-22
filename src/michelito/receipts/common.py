"""Types and helpers shared by the merchant-email readers.

A receipt is what a merchant's email says about a purchase (an order confirmation, a shipment
notice). Unlike a bank alert it never creates a transaction: it adds detail to one that a
statement or an alert already brought (see `analysis.receipt_match`). It is read in memory from
the same `AlertEmail` the bank alerts use, only when the merchant's own signature passes, and
only the fields below are kept: never the body.

A reader that cannot read an email raises `alerts.common.AlertParseError` naming the field that
failed, as the alert parsers do.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from michelito.alerts.common import HTML_MAX, AlertEmail, AlertParseError

ReceiptKind = Literal["order", "shipment"]
# The fields a reader extracts; one of them names what failed.
FIELDS = ("authentication", "size", "order", "amount")

SUMMARY_MAX = 120  # the merchant's own summary line (the sender controls it)
REFERENCE_MAX = 40
RECEIPTS_MAX = 20  # receipts in one email
ORDERS_MAX = 5  # order numbers on one receipt
_LINES_MAX = 2000  # visible lines read from one part
_LINKS_MAX = 200


@dataclass(frozen=True)
class Receipt:
    """What a merchant's email says about one purchase or one shipment of it."""

    parser: str
    merchant: str  # the display name ("Amazon")
    kind: ReceiptKind
    orders: tuple[str, ...]  # the merchant's order numbers (a shipment may carry several)
    amount: Decimal  # positive
    currency: str
    reference: str = ""  # the merchant's shipment identifier, when the email has one
    summary: str = ""  # the merchant's own summary of the items ("Kitchen, Tools, and more")
    item_count: int | None = None
    link: str = ""  # the order's page at the merchant, built from the order number


@dataclass(frozen=True)
class Link:
    """A link of the email, already past the merchant's redirect."""

    host: str
    path: str
    query: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Part:
    """One body part as the readers see it: its visible lines and its links."""

    lines: tuple[str, ...]
    links: tuple[Link, ...]


def clean(text: str) -> str:
    """Single-spaced, without invisible format characters (direction marks, zero-width ones)."""
    visible = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return " ".join(visible.split())


def read_link(
    address: str,
    redirect_path: str = "",
    redirect_parameter: str = "",
    redirect_hosts: Collection[str] = (),
) -> Link | None:
    """An https link, following one redirect of the merchant's (`redirect_path` on one of
    `redirect_hosts`, carrying the real address in `redirect_parameter`). The same path on any
    other host is not a redirect: the link is that host's. None for anything that is not https."""
    found = _split(address)
    if found is None:
        return None
    if redirect_path and found.path == redirect_path and found.host in redirect_hosts:
        targets = found.query.get(redirect_parameter, ())
        inner = _split(targets[0]) if targets else None
        return inner if inner is not None else found
    return found


def _split(address: str) -> Link | None:
    try:
        parts = urlsplit(address.strip())
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    query = {key: tuple(values) for key, values in parse_qs(parts.query).items()}
    return Link(parts.hostname.lower(), parts.path, query)


class _Collector(HTMLParser):
    """The visible text of an HTML body, one line per text node, and every link's address."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.addresses: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag == "a" and len(self.addresses) < _LINKS_MAX:
            address = next((value for name, value in attrs if name == "href" and value), None)
            if address:
                self.addresses.append(address)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head"):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        if self._skip or len(self.lines) >= _LINES_MAX:
            return
        line = clean(data)
        if line:
            self.lines.append(line)


def _too_large(source: str) -> None:
    if len(source) > HTML_MAX:
        raise AlertParseError("size")


def html_part(
    source: str,
    redirect_path: str = "",
    redirect_parameter: str = "",
    redirect_hosts: Collection[str] = (),
) -> Part:
    _too_large(source)
    collector = _Collector()
    collector.feed(source)
    collector.close()
    links = (
        read_link(a, redirect_path, redirect_parameter, redirect_hosts) for a in collector.addresses
    )
    return Part(tuple(collector.lines), tuple(link for link in links if link is not None))


def text_part(
    source: str,
    redirect_path: str = "",
    redirect_parameter: str = "",
    redirect_hosts: Collection[str] = (),
) -> Part:
    """A plain-text body: its non-empty lines; a line that is an address is a link."""
    _too_large(source)
    lines = [line for line in (clean(raw) for raw in source.splitlines()) if line][:_LINES_MAX]
    addresses = [word for line in lines for word in line.split() if word.startswith("https://")]
    links = (
        read_link(a, redirect_path, redirect_parameter, redirect_hosts)
        for a in addresses[:_LINKS_MAX]
    )
    return Part(tuple(lines), tuple(link for link in links if link is not None))


def parts(
    email: AlertEmail,
    redirect_path: str = "",
    redirect_parameter: str = "",
    redirect_hosts: Collection[str] = (),
) -> list[Part]:
    """The email's body parts, the plain text first (the simpler one). A part over the size
    limit refuses the whole email."""
    found = []
    if email.text.strip():
        found.append(text_part(email.text, redirect_path, redirect_parameter, redirect_hosts))
    if email.html.strip():
        found.append(html_part(email.html, redirect_path, redirect_parameter, redirect_hosts))
    return found
