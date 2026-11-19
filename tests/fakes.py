"""Dobles de prueba para el cliente de Gmail."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from finanzas.gmail import AttachmentRef, MailMessage


def make_message(
    message_id: str,
    attachments: dict[str, bytes],
    *,
    received: datetime = datetime(2026, 1, 14, 12, 0, tzinfo=UTC),
    subject: str = "Estado de cuenta",
) -> tuple[MailMessage, dict[str, bytes]]:
    refs = tuple(
        AttachmentRef(filename=name, attachment_id=f"{message_id}-{name}", size=len(data))
        for name, data in attachments.items()
    )
    payloads = {f"{message_id}-{name}": data for name, data in attachments.items()}
    message = MailMessage(
        message_id=message_id,
        sender="Banco <estados@banco.example>",
        subject=subject,
        received_at=received,
        body_text="Adjunto su estado de cuenta.",
        attachments=refs,
    )
    return message, payloads


class FakeClient:
    def __init__(self, *messages: tuple[MailMessage, dict[str, bytes]]) -> None:
        self.messages = {message.message_id: message for message, _ in messages}
        self.payloads = {key: data for _, payloads in messages for key, data in payloads.items()}
        self.fetched: list[str] = []

    def list_message_ids(self, query: str) -> Iterator[str]:
        yield from self.messages

    def get_message(self, message_id: str) -> MailMessage:
        self.fetched.append(message_id)
        return self.messages[message_id]

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        return self.payloads[attachment_id]
