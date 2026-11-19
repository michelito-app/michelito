import base64
from datetime import UTC, datetime

from michelito.gmail import GmailClient, decode_base64url, message_from_api


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


API_MESSAGE = {
    "id": "m1",
    "internalDate": "1792005355000",
    "payload": {
        "mimeType": "multipart/mixed",
        "headers": [
            {"name": "From", "value": "Bank <statements@bank.example>"},
            {"name": "Subject", "value": "Account: 1234 | Date: 13/10/2026 |"},
        ],
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "filename": "",
                        "body": {"data": _b64("Hola ñ".encode())},  # spanish-data
                    },
                    {
                        "mimeType": "text/html",
                        "filename": "",
                        "body": {"data": _b64(b"<p>Hello</p>")},
                    },
                ],
            },
            {
                "mimeType": "application/pdf",
                "filename": "statement.pdf",
                "body": {"attachmentId": "a1", "size": 47506},
            },
            {"mimeType": "image/png", "filename": "logo.png", "body": {"data": _b64(b"x")}},
        ],
    },
}


def test_decode_base64url_handles_missing_padding() -> None:
    assert decode_base64url(_b64(b"abcd")) == b"abcd"


def test_message_from_api() -> None:
    message = message_from_api(API_MESSAGE)
    assert message.message_id == "m1"
    assert message.sender == "Bank <statements@bank.example>"
    assert message.subject.startswith("Account: 1234")
    assert message.received_at == datetime.fromtimestamp(1792005355, tz=UTC)
    assert message.body_text == "Hola ñ"  # spanish-data
    assert [(a.filename, a.attachment_id, a.size) for a in message.attachments] == [
        ("statement.pdf", "a1", 47506)
    ]


class _Call:
    def __init__(self, result: dict) -> None:
        self._result = result

    def execute(self, num_retries: int = 0) -> dict:
        # Gmail limits queries per minute; without retries a long run gets cut off.
        assert num_retries >= 5, "every API call must retry on the quota limit"
        return self._result


class _Attachments:
    def get(self, userId: str, messageId: str, id: str) -> _Call:  # noqa: A002, N803
        return _Call({"data": _b64(f"{messageId}:{id}".encode())})


class _Messages:
    def __init__(self) -> None:
        self.queries: list[tuple[str, str | None]] = []

    def list(self, userId: str, q: str, pageToken: str | None, maxResults: int) -> _Call:  # noqa: N803
        self.queries.append((q, pageToken))
        if pageToken is None:
            return _Call({"messages": [{"id": "m1"}], "nextPageToken": "p2"})
        return _Call({"messages": [{"id": "m2"}]})

    def get(self, userId: str, id: str, format: str) -> _Call:  # noqa: A002, N803
        return _Call({**API_MESSAGE, "id": id})

    def attachments(self) -> _Attachments:
        return _Attachments()


class _Service:
    def __init__(self) -> None:
        self.messages_api = _Messages()

    def users(self) -> "_Service":
        return self

    def messages(self) -> _Messages:
        return self.messages_api


def test_client_paginates_and_fetches() -> None:
    service = _Service()
    client = GmailClient(service)
    assert list(client.list_message_ids("from:x")) == ["m1", "m2"]
    assert service.messages_api.queries == [("from:x", None), ("from:x", "p2")]
    assert client.get_message("m2").message_id == "m2"
    assert client.get_attachment("m1", "a1") == b"m1:a1"
