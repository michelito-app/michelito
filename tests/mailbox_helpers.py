"""A fake Google for the connected-Gmail tests: no network, synthetic tokens and messages only
(the merchant emails come from `tests.receipt_samples`)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from michelito.alerts.common import AlertEmail
from michelito.gmail import MailMessage
from michelito.hosted import mailbox
from michelito.hosted.mailbox import GoogleClient, Granted
from tests import receipt_samples as samples

TOKEN = "1//synthetic-refresh-token-not-real"
ADDRESS = "alice.mailbox@example.com"
CLIENT = {
    "web": {
        "client_id": "synthetic-client.apps.googleusercontent.com",
        "client_secret": "synthetic-client-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["https://app.example/api/mailbox/google/callback"],
    }
}


def client_file(folder: Path) -> Path:
    path = folder / "google-client.json"
    path.write_text(json.dumps(CLIENT), encoding="utf-8")
    return path


def client() -> GoogleClient:
    return mailbox.parse_client(json.dumps(CLIENT))


def message(email: AlertEmail) -> MailMessage:
    return MailMessage(
        message_id=email.message_id,
        sender=email.sender,
        subject=email.subject,
        received_at=email.received_at,
        body_text=email.text,
        attachments=(),
        body_html=email.html,
        auth_results=email.auth_results,
    )


def receipts() -> tuple[MailMessage, ...]:
    """An order confirmation and a shipment (two emails, three receipts)."""
    return (message(samples.order_email()), message(samples.shipment_email()))


@dataclass
class FakeMailbox:
    messages: tuple[MailMessage, ...]
    mail_address: str = ADDRESS
    queries: list[str] = field(default_factory=list)

    def list_message_ids(self, query: str) -> Iterator[str]:
        self.queries.append(query)
        yield from (found.message_id for found in self.messages)

    def get_message(self, message_id: str) -> MailMessage:
        return next(found for found in self.messages if found.message_id == message_id)

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        raise AssertionError("receipts never download attachments")

    def address(self) -> str:
        return self.mail_address


@dataclass
class FakeGoogle:
    """Google's side: what it was asked, and how it answers (each answer can be changed)."""

    messages: tuple[MailMessage, ...] = field(default_factory=receipts)
    token: str = TOKEN
    scopes: frozenset[str] = frozenset({mailbox.SCOPE})
    refuse_code: bool = False
    revoke_works: bool = True
    open_error: Exception | None = None  # raised when the mailbox is opened
    address_error: Exception | None = None
    exchanged: list[tuple[str, str, str]] = field(default_factory=list)  # code, verifier, uri
    revoked: list[str] = field(default_factory=list)
    opened: list[FakeMailbox] = field(default_factory=list)

    def exchange(
        self, client: GoogleClient, redirect_uri: str, code: str, verifier: str
    ) -> Granted:
        self.exchanged.append((code, verifier, redirect_uri))
        if self.refuse_code:
            raise mailbox.Revoked("synthetic refusal")
        return Granted(self.token, self.scopes)

    def revoke(self, token: str) -> bool:
        self.revoked.append(token)
        return self.revoke_works

    def mailbox(self, client: GoogleClient, refresh_token: str) -> FakeMailbox:
        assert refresh_token == self.token
        if self.open_error is not None:
            raise self.open_error
        opened = _Addressed(self.messages, error=self.address_error)
        self.opened.append(opened)
        return opened


@dataclass
class _Addressed(FakeMailbox):
    error: Exception | None = None

    def address(self) -> str:
        if self.error is not None:
            raise self.error
        return super().address()
