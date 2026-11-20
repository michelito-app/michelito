"""Bank-alert parsers: each one recognizes and reads one kind of alert email.

Like the statement parsers, each module exposes `NAME`, `matches(email)` and `parse(email)`,
where `email` is an `AlertEmail` (headers plus HTML/text body). `from_bytes` builds one from a
raw RFC 822 message (a forwarded email, a saved `.eml`); the Gmail sync builds it from its own
message (`extract`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Protocol, cast

from michelito import charset
from michelito.alerts import popular_purchase
from michelito.alerts.common import Alert, AlertEmail, AlertKind


class AlertParser(Protocol):
    NAME: str
    INSTITUTION: str  # the `accounts.institution` its cards belong to
    STATUSES: dict[str, AlertKind]  # the bank's status word (folded) -> kind

    def matches(self, email: AlertEmail) -> bool: ...

    def parse(self, email: AlertEmail) -> Alert: ...


PARSERS: tuple[AlertParser, ...] = (popular_purchase,)  # type: ignore[assignment]


def detect(email: AlertEmail) -> AlertParser | None:
    return next((parser for parser in PARSERS if parser.matches(email)), None)


def by_name(name: str | None) -> AlertParser | None:
    return next((parser for parser in PARSERS if name == parser.NAME), None)


def from_bytes(raw: bytes, message_id: str | None = None) -> AlertEmail:
    """An `AlertEmail` from a raw message, entirely in memory. `message_id`: the id to keep it
    idempotent (by default its `Message-ID` header)."""
    message = cast(EmailMessage, BytesParser(policy=policy.default).parsebytes(raw))
    headers = {key.lower(): str(value) for key, value in message.items()}
    html_part = message.get_body(preferencelist=("html",))
    text_part = message.get_body(preferencelist=("plain",))
    return AlertEmail(
        message_id=message_id or headers.get("message-id", "").strip("<> "),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        received_at=_date(headers.get("date")),
        html=_content(html_part),
        text=_content(text_part),
        headers=headers,
        auth_results=tuple(str(v) for v in message.get_all("Authentication-Results") or ()),
    )


def _content(part: object) -> str:
    """The part's text, decoded from its bytes with its declared charset (then UTF-8, then
    windows-1252), never with replacement characters."""
    if not isinstance(part, EmailMessage):
        return ""
    data = part.get_payload(decode=True)
    if not isinstance(data, bytes):
        return ""
    return charset.decode(data, part.get_content_charset())


def _date(value: str | None) -> datetime:
    if value:
        try:
            found = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            found = None
        if found is not None:
            return found if found.tzinfo else found.replace(tzinfo=UTC)
    return datetime.now(UTC)
