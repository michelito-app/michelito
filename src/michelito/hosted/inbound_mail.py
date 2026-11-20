"""Reading a forwarded email's structure in memory: who sent it, its id, its PDF attachments.

`parse(raw)` never opens an attachment (a PDF is only decoded from its transfer encoding, to be
handed to the isolated worker later or sealed in the account's database) and never keeps an
attachment's file name. `gmail_confirmation` reads the confirmation code and link of Gmail's
"confirm forwarding" email; the person uses them in Gmail themselves (nothing is confirmed
here).

Nothing here logs anything.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from typing import cast

from michelito import alerts
from michelito.alerts.common import AlertEmail

PDF_MAGIC = b"%PDF"
MAX_PARTS = 64  # a message with more MIME parts is read only up to here
MAX_PDFS = 8
GMAIL_SENDER = "forwarding-noreply@google.com"
GMAIL_DOMAIN = "google.com"
_CODE = re.compile(r"(?<!\d)(\d{6,12})(?!\d)")
_CODE_LABEL = re.compile(
    r"(?:confirmation code|c[oó]digo de confirmaci[oó]n)\s*[:#]?\s*(\d{6,12})",  # spanish-data
    re.IGNORECASE,
)
_SUBJECT_CODE = re.compile(r"\(#\s*(\d{6,12})\s*\)")
_LINK = re.compile(r"https://[A-Za-z0-9.-]{1,64}/[^\s\"'<>()]{1,400}")
LINK_HOSTS = frozenset({"mail-settings.google.com", "mail.google.com"})
# The confirmation link's path: /mail/vf-<token>, the token only letters, digits, "-", "_" and
# "%5B"/"%5D" ([ and ]); nothing else is rebuilt into a link.
_LINK_PATH = re.compile(r"/mail/vf-[A-Za-z0-9_\-]*(?:%5[BbDd][A-Za-z0-9_\-]*)*")
_REQUESTER = re.compile(
    r"([A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24})\s+"
    r"(?:has requested|ha solicitado)",  # spanish-data
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Inbound:
    """A forwarded message's structure: never an attachment's name, never its content read."""

    message_key: str  # sha256 of the Message-ID (or of the message, without one)
    raw_key: str  # sha256 of the message's bytes (how quarantined messages are deduplicated)
    sender: str  # the From address, lowercase
    subject: str = field(repr=False)
    received_at: datetime
    attachments: int  # every attachment, of any kind
    pdfs: tuple[bytes, ...] = field(default=(), repr=False)
    email: AlertEmail | None = field(default=None, repr=False)

    @property
    def sender_domain(self) -> str:
        return self.sender.rpartition("@")[2]


class Unreadable(ValueError):
    """Not a message that can be read at all (the reason is safe to log)."""


def parse(raw: bytes) -> Inbound:
    try:
        message = cast(EmailMessage, BytesParser(policy=policy.default).parsebytes(raw))
        sender = parseaddr(str(message.get("from", "")))[1].lower()
        subject = str(message.get("subject", ""))
        message_id = str(message.get("message-id", "")).strip().strip("<>").strip()
        received = _date(message.get("date"))
        attachments, pdfs = _attachments(message)
        email = alerts.from_bytes(raw, message_id=message_id or None)
    except Exception as exc:  # noqa: BLE001 - a malformed message is just unreadable
        raise Unreadable(type(exc).__name__) from None
    basis = message_id.encode() if message_id else raw
    key = hashlib.sha256(b"message\0" + basis).hexdigest()
    raw_key = hashlib.sha256(b"raw\0" + raw).hexdigest()
    return Inbound(key, raw_key, sender, subject, received, attachments, pdfs, email)


def _attachments(message: EmailMessage) -> tuple[int, tuple[bytes, ...]]:
    count = 0
    pdfs: list[bytes] = []
    for number, part in enumerate(message.walk()):
        if number >= MAX_PARTS:
            break
        if part.is_multipart() or part.get_content_disposition() not in ("attachment", "inline"):
            continue
        if part.get_content_disposition() == "inline" and part.get_content_maintype() == "text":
            continue
        count += 1
        data = part.get_payload(decode=True)
        if isinstance(data, bytes) and data.startswith(PDF_MAGIC) and len(pdfs) < MAX_PDFS:
            pdfs.append(data)
    return count, tuple(pdfs)


def _date(value: object) -> datetime:
    if value:
        try:
            found = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            found = None
        if found is not None:
            return found if found.tzinfo else found.replace(tzinfo=UTC)
    return datetime.now(UTC)


@dataclass(frozen=True)
class Confirmation:
    code: str | None
    link: str | None
    requester: str | None  # the Gmail address that asked to forward (shown to the person)


def safe_link(found: str | None) -> str | None:
    """The confirmation link **rebuilt** from an allowlisted host and path pattern: https only,
    no query or fragment, no `..`, no encoded dot or slash, no redirector (`/url`); else None."""
    if not found:
        return None
    text = html.unescape(found)
    if not text.startswith("https://"):
        return None
    host, slash, rest = text[len("https://") :].partition("/")
    path = slash + rest.split("?", 1)[0].split("#", 1)[0]
    lowered = path.lower()
    if host.lower() not in LINK_HOSTS or ".." in path or "%2e" in lowered or "%2f" in lowered:
        return None
    if lowered.startswith("/url") or not _LINK_PATH.fullmatch(path):
        return None
    return f"https://{host.lower()}{path}"


def gmail_confirmation(inbound: Inbound) -> Confirmation:
    """The code (digits only) and the confirmation link (only an https link on Google's mail
    settings hosts) of Gmail's "confirm forwarding" email."""
    email = inbound.email
    text = "" if email is None else f"{email.text}\n{email.html}"
    found = _CODE_LABEL.search(text) or _SUBJECT_CODE.search(inbound.subject)
    if found is None and email is not None and not email.html:
        found = _CODE.search(email.text)
    link = next((safe for m in _LINK.finditer(text) if (safe := safe_link(m.group(0)))), None)
    asked = _REQUESTER.search(email.text if email is not None else "")
    return Confirmation(
        found.group(1) if found else None, link, asked.group(1).lower() if asked else None
    )
