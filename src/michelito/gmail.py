"""Minimal Gmail API client, read-only."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from michelito import charset

SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)
_PAGE_SIZE = 500
# Retries with exponential backoff on 429 and on 403 for quota limits (googleapiclient).
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
    body_html: str = ""  # bank alerts are HTML (`michelito.alerts`); read only in memory
    # Every Authentication-Results header, topmost (Gmail's own) first: alerts need its DKIM.
    auth_results: tuple[str, ...] = ()


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
    return MailMessage(
        message_id=data["id"],
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        received_at=datetime.fromtimestamp(int(data["internalDate"]) / 1000, tz=UTC),
        body_text=_body(parts, "text/plain"),
        attachments=attachments,
        body_html=_body(parts, "text/html"),
        auth_results=tuple(
            h["value"]
            for h in payload.get("headers", [])
            if h["name"].lower() == "authentication-results"
        ),
    )


def _part_charset(part: dict[str, Any]) -> str | None:
    """The charset the part's own Content-Type declares (Gmail lists the part's headers)."""
    headers = {h["name"].lower(): h["value"] for h in part.get("headers", [])}
    return charset.declared(headers.get("content-type"))


def _body(parts: list[dict[str, Any]], mime_type: str) -> str:
    """The first inline (not attached) part of that type, decoded with its declared charset
    (falling back to UTF-8 and windows-1252; never with replacement characters)."""
    return next(
        (
            charset.decode(decode_base64url(part["body"]["data"]), _part_charset(part))
            for part in parts
            if part.get("mimeType") == mime_type
            and not part.get("filename")
            and part.get("body", {}).get("data")
        ),
        "",
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
    """Build the client from the saved token, refreshing (and saving) it if it expired."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_authorized_user_info(json.loads(token_json), list(SCOPES))
    if not credentials.valid:
        if not credentials.refresh_token:
            raise RuntimeError("the Gmail token cannot be refreshed; run: michelito auth")
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            raise RuntimeError(
                "Google refused to refresh the token (revoked, or app in testing mode?); "
                "run: michelito auth"
            ) from exc
        save_token(credentials.to_json())
    return GmailClient(build("gmail", "v1", credentials=credentials, cache_discovery=False))


def authorize(client_config: dict[str, Any]) -> str:
    """Open the browser so you authorize read-only access; return the token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(client_config, list(SCOPES))
    credentials = flow.run_local_server(port=0, open_browser=True)
    return credentials.to_json()
