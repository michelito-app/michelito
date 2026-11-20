"""Types and helpers shared by the bank-alert parsers.

An alert is an email a bank sends for each movement (a card purchase, a deposit…). It is not a
document: it is parsed in memory from an `AlertEmail` (headers plus HTML and/or text body, the
shape both the Gmail sync and a forwarding endpoint can build) and only the extracted fields are
stored (see `analysis.live`).

A parser that cannot read an alert raises `AlertParseError` naming the field that failed; the
caller stores `failure_fingerprint`, which is data-free (sender domain, alert type, failed field,
layout), never the email or any value from it.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Literal

from michelito.alerts import authres

AlertKind = Literal["approved", "declined", "reversed", "unknown"]
# The fields an alert parser extracts; one of them names what failed.
FIELDS = ("authentication", "table", "card", "amount", "currency", "date", "merchant", "status")
Layout = Literal["horizontal", "vertical", "none"]


GMAIL_AUTHSERV = "mx.google.com"


@dataclass(frozen=True)
class AlertEmail:
    """A parsed email, independent of where it came from (Gmail, a forwarded message)."""

    message_id: str
    sender: str
    subject: str
    received_at: datetime
    html: str = ""
    text: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    # Every `Authentication-Results` header, in message order (the topmost first: the one the
    # receiving provider added; lower ones may come from the sender). See `authres`.
    auth_results: tuple[str, ...] = ()
    # The authserv-ids whose header is trusted: the receiver that built this email (Gmail by
    # default; the hosted path names its own).
    trusted_authserv: tuple[str, ...] = (GMAIL_AUTHSERV,)
    # A verdict an outside verifier already reached (the hosted forwarding path passes the Email
    # Worker's DKIM and DMARC results here); None: read `auth_results`.
    verified: authres.Verdict | None = None

    @property
    def sender_address(self) -> str:
        return parseaddr(self.sender)[1].lower()

    @property
    def sender_domain(self) -> str:
        return self.sender_address.rpartition("@")[2]


@dataclass(frozen=True)
class Alert:
    """What an alert says. `amount` is always positive; `kind` comes from `status_kind`."""

    parser: str
    kind: AlertKind
    last4: str
    amount: Decimal
    currency: str  # DOP or USD
    day: date
    merchant: str
    status: str  # the bank's word, normalized (to extend the status table)


class AlertParseError(ValueError):
    """The alert does not have the expected shape: `field` says which part failed."""

    def __init__(self, field_name: str, layout: Layout = "none") -> None:
        super().__init__(f"alert field not understood: {field_name}")
        self.field = field_name
        self.layout = layout


FIELD_MAX = 100  # each fingerprint field, cut (the sender controls some of them)
FINGERPRINT_MAX = 400  # the serialized fingerprint (`alerts.failure` allows this much)


def failure_fingerprint(email: AlertEmail, parser: str, error: AlertParseError) -> dict[str, str]:
    """A data-free description of a failure: enough to fix the parser, nothing personal. Every
    field is cut to FIELD_MAX characters; `failure_json` keeps the whole under FINGERPRINT_MAX."""
    found = {
        "sender_domain": email.sender_domain,
        "alert_type": parser,
        "failed_field": error.field,
        "layout": error.layout,
        "has_html": "yes" if email.html.strip() else "no",
        "has_text": "yes" if email.text.strip() else "no",
    }
    return {key: str(value)[:FIELD_MAX] for key, value in found.items()}


def failure_json(fingerprint: Mapping[str, str]) -> str:
    """The fingerprint as JSON, never longer than FINGERPRINT_MAX (fields cut further if a
    sender filled them with characters that escape long)."""
    limit = FIELD_MAX
    while True:
        text = json.dumps({k: v[:limit] for k, v in fingerprint.items()}, sort_keys=True)
        if len(text) <= FINGERPRINT_MAX or limit == 0:
            return text[:FINGERPRINT_MAX]
        limit //= 2


def verdict(email: AlertEmail) -> authres.Verdict:
    """Who vouches for the email: the outside verifier's verdict (`verified`) or, failing
    that, the topmost `Authentication-Results` from a trusted receiver (`authres`)."""
    if email.verified is not None:
        return email.verified
    return authres.trusted_verdict(email.auth_results, email.trusted_authserv)


def require_authenticated(email: AlertEmail, domain: str) -> None:
    """`AlertParseError("authentication")` unless DKIM and DMARC both pass for `domain` (or a
    subdomain), according to `verdict`."""
    if not authres.authenticated(verdict(email), domain):
        raise AlertParseError("authentication")


def fold(text: str) -> str:
    """Lowercase, without accents, with single spaces: for comparing labels and statuses."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


def status_kind(status: str, table: Mapping[str, AlertKind]) -> AlertKind:
    """The kind of a bank status word; an unknown one is "unknown" (never approved)."""
    key = re.sub(r"[^a-z ]+", "", fold(status)).strip()
    return table.get(key, "unknown")


_AMOUNT = re.compile(r"^(?:[A-Z]{2,3}\$?|\$)?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?$")


def parse_amount(text: str) -> Decimal:
    """'1,234.56', 'RD$ 1,234.56', '$95.00' or '700' -> Decimal (positive)."""
    cleaned = " ".join(text.replace(" ", " ").split()).upper()
    match = _AMOUNT.match(cleaned)
    if match is None:
        raise AlertParseError("amount")
    try:
        value = Decimal(f"{match[1].replace(',', '')}.{match[2] or '00'}")
    except InvalidOperation:
        raise AlertParseError("amount") from None
    if value <= 0:
        raise AlertParseError("amount")
    return value


_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y")
_TIME_SUFFIX = re.compile(r"\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]\.?\s?m\.?)?$", re.IGNORECASE)


def parse_day(text: str) -> date:
    """'25/02/2026', '25-02-2026', '2026-02-25', optionally followed by a time."""
    cleaned = _TIME_SUFFIX.sub("", " ".join(text.split()))
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise AlertParseError("date")


@dataclass(frozen=True)
class Table:
    """One HTML table: its rows (each a list of cell texts), nested tables apart."""

    rows: tuple[tuple[str, ...], ...]


HTML_MAX = 256 * 1024  # a larger body is not an alert: rejected before parsing
_TABLE_DEPTH = 8  # tables nested deeper than this are read as plain text


class _TableCollector(HTMLParser):
    """Collects every table's rows and the visible text. A nested table is its own table: the
    outer cell gets its text too, but header matching looks for cells that are exactly a label,
    so it finds the innermost row."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._stack: list[list[list[str]]] = []
        # Open cells (innermost last), each with the table depth it belongs to: at most one per
        # table level (bounded by _TABLE_DEPTH), so appending text stays linear.
        self._cells: list[tuple[int, list[str]]] = []
        self._ignored = 0  # tables opened beyond _TABLE_DEPTH
        self._skip = 0
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: Sequence[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag == "table":
            if len(self._stack) >= _TABLE_DEPTH:
                self._ignored += 1
                return
            table: list[list[str]] = []
            self.tables.append(table)
            self._stack.append(table)
        elif self._ignored:
            return
        elif tag == "tr" and self._stack:
            self._close_cell()  # as in HTML: a new row closes this table's open cell
            self._stack[-1].append([])
        elif tag in ("td", "th") and self._stack:
            self._close_cell()  # and so does a new cell
            if not self._stack[-1]:
                self._stack[-1].append([])
            self._cells.append((len(self._stack), []))
        elif tag == "br":
            self._data(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head"):
            self._skip = max(0, self._skip - 1)
        elif tag == "table" and self._ignored:
            self._ignored -= 1
        elif tag == "table" and self._stack:
            self._close_cell()
            self._stack.pop()
        elif tag in ("td", "th"):
            self._close_cell()
        elif tag in ("p", "div", "tr", "li") or tag.startswith("h"):
            self._data(" ")

    def _close_cell(self) -> None:
        """Close the current table's open cell, if it has one."""
        if self._cells and self._stack and self._cells[-1][0] == len(self._stack):
            _, parts = self._cells.pop()
            self._stack[-1][-1].append(" ".join("".join(parts).split()))

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._data(data)

    def _data(self, data: str) -> None:
        self.text.append(data)
        for _, cell in self._cells:
            cell.append(data)


@dataclass(frozen=True)
class Document:
    tables: tuple[Table, ...]
    text: str  # visible text, single-spaced


def read_html(source: str) -> Document:
    if len(source) > HTML_MAX:
        raise AlertParseError("size")
    collector = _TableCollector()
    collector.feed(source)
    collector.close()
    tables = tuple(
        Table(tuple(tuple(row) for row in table if any(cell for cell in row)))
        for table in collector.tables
    )
    return Document(tables, " ".join("".join(collector.text).split()))


def read_text(source: str) -> Document:
    """A plain-text body: lines become one-cell rows of a single table (for `labeled_values`)."""
    if len(source) > HTML_MAX:
        raise AlertParseError("size")
    lines = tuple((" ".join(line.split()),) for line in html.unescape(source).splitlines())
    rows = tuple(row for row in lines if row[0])
    return Document((Table(rows),), " ".join(" ".join(r) for r in rows))


def header_values(document: Document, labels: Sequence[str]) -> dict[str, str] | None:
    """A horizontal table: a row whose cells are exactly the labels (folded), then the first
    following row with as many cells. Returns label -> value text."""
    wanted = {fold(label) for label in labels}
    for table in document.tables:
        for index, row in enumerate(table.rows):
            folded = [fold(cell).rstrip(":") for cell in row]
            if not wanted <= set(folded):
                continue
            for values in table.rows[index + 1 :]:
                if len(values) == len(row):
                    return {
                        label: values[folded.index(fold(label))]
                        for label in labels
                        if fold(label) in folded
                    }
    return None


def labeled_values(document: Document, labels: Sequence[str]) -> dict[str, str]:
    """A vertical table (or a text body): a cell "Label" followed by its value in the next cell,
    or a single cell "Label: value". Returns the labels found -> value text."""
    found: dict[str, str] = {}
    keys = {fold(label): label for label in labels}
    for table in document.tables:
        for row in table.rows:
            for position, cell in enumerate(row):
                head, colon, rest = cell.partition(":")
                key = fold(head)
                if key not in keys or keys[key] in found:
                    continue
                if colon and rest.strip():
                    found[keys[key]] = rest.strip()
                elif position + 1 < len(row) and row[position + 1].strip():
                    found[keys[key]] = row[position + 1].strip()
    return found
