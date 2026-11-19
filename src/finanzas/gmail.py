"""Cliente mínimo de la API de Gmail, en modo solo lectura."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)
_PAGE_SIZE = 500
# Reintentos con espera exponencial ante 429 y 403 por límite de cuota (googleapiclient).
_RETRIES = 8


@dataclass(frozen=True)
class AttachmentRef:
    filename: str
    attachment_id: str
    size: int


@dataclass(frozen=True)
class MailMessage:
    message_id: str
    sender: str
    subject: str
    received_at: datetime
    body_text: str
    attachments: tuple[AttachmentRef, ...]


def decode_base64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def message_from_api(data: dict[str, Any]) -> MailMessage:
    payload = data.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    parts = list(_walk(payload))
    attachments = tuple(
        AttachmentRef(
            part["filename"], part["body"]["attachmentId"], int(part["body"].get("size", 0))
        )
        for part in parts
        if part.get("filename") and part.get("body", {}).get("attachmentId")
    )
    body = next(
        (
            decode_base64url(part["body"]["data"]).decode("utf-8", errors="replace")
            for part in parts
            if part.get("mimeType") == "text/plain"
            and not part.get("filename")
            and part.get("body", {}).get("data")
        ),
        "",
    )
    return MailMessage(
        message_id=data["id"],
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        received_at=datetime.fromtimestamp(int(data["internalDate"]) / 1000, tz=UTC),
        body_text=body,
        attachments=attachments,
    )


def _walk(part: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield part
    for child in part.get("parts") or []:
        yield from _walk(child)


class GmailClient:
    def __init__(self, service: Any) -> None:
        self._messages = service.users().messages()

    def list_message_ids(self, query: str) -> Iterator[str]:
        token: str | None = None
        while True:
            response = self._messages.list(
                userId="me", q=query, pageToken=token, maxResults=_PAGE_SIZE
            ).execute(num_retries=_RETRIES)
            for item in response.get("messages", []):
                yield item["id"]
            token = response.get("nextPageToken")
            if not token:
                return

    def get_message(self, message_id: str) -> MailMessage:
        data = self._messages.get(userId="me", id=message_id, format="full").execute(
            num_retries=_RETRIES
        )
        return message_from_api(data)

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        response = (
            self._messages.attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute(num_retries=_RETRIES)
        )
        return decode_base64url(response["data"])


def build_client(token_json: str, save_token: Callable[[str], None]) -> GmailClient:
    """Crea el cliente con el token guardado, renovándolo (y guardándolo) si venció."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_authorized_user_info(json.loads(token_json), list(SCOPES))
    if not credentials.valid:
        if not credentials.refresh_token:
            raise RuntimeError("el token de Gmail no se puede renovar; corre: finanzas auth")
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            raise RuntimeError(
                "Google rechazó renovar el token (¿revocado o app en modo prueba?); "
                "corre: finanzas auth"
            ) from exc
        save_token(credentials.to_json())
    return GmailClient(build("gmail", "v1", credentials=credentials, cache_discovery=False))


def authorize(client_config: dict[str, Any]) -> str:
    """Abre el navegador para que autorices el acceso de solo lectura; devuelve el token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(client_config, list(SCOPES))
    credentials = flow.run_local_server(port=0, open_browser=True)
    return credentials.to_json()
