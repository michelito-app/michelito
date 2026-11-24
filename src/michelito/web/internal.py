"""Calls from the server to its own API, in the same process, for a given workspace.

The AI connector (`hosted.mcp_routes`) reads through the same routes the interface uses, and an
approved proposal (`web.proposal_routes`) is applied through them too, so every check, view and
change-log entry stays the one the app already has. `call` runs the app with a request built
here: the workspace travels in the ASGI scope under `SCOPE_KEY`, which no request from the
network can carry (the server builds their scope), and `create_app`'s middleware uses it instead
of asking the provider. Nothing is sent over a socket.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from starlette.types import ASGIApp, Message

from michelito.web.workspace import Workspace

SCOPE_KEY = "michelito.internal_workspace"
WRITE_HEADER = "X-Michelito"
AUTHOR_HEADER = "X-Michelito-Author"


@dataclass(frozen=True)
class Answer:
    status: int
    body: Any  # the decoded JSON (None when the answer has no JSON body)
    text: str = ""  # the body as text when it is not JSON (the dossier's Markdown)


async def call(
    app: ASGIApp,
    workspace: Workspace,
    host: str,
    method: str,
    path: str,
    query: Mapping[str, str] | None = None,
    body: Any = None,
    author: str = "user",
) -> Answer:
    """`method path?query` with an optional JSON `body`, answered by `app` for `workspace`."""
    payload = b"" if body is None else json.dumps(body).encode()
    headers = [(b"host", host.encode()), (AUTHOR_HEADER.lower().encode(), author.encode())]
    if method not in ("GET", "HEAD"):
        headers.append((WRITE_HEADER.lower().encode(), b"1"))
    if body is not None:
        headers.append((b"content-type", b"application/json"))
        headers.append((b"content-length", str(len(payload)).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": urlencode(dict(query or {})).encode(),
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": (host, 443),
        "state": {},
        SCOPE_KEY: workspace,
    }
    sent = False
    status = 500
    chunks: list[bytes] = []

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message: Message) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    raw = b"".join(chunks)
    try:
        return Answer(status, json.loads(raw) if raw else None)
    except ValueError:
        return Answer(status, None, raw.decode("utf-8", errors="replace"))
