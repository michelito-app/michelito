"""`michelito verify-import`: the same figures computed on the owner's machine and on the server.

For each chosen month it takes the Summary, and once the Shared balances and the investments,
exactly as the board's API returns them (`GET /api/summary?month=…`, `/api/shared`,
`/api/investments`, called in process on the board app: no server, no port, no network), and
reduces each to a short hash of its canonical JSON. The same output on both machines means the
same numbers; `--exact` prints the numeric values instead, to find where they differ.

The figures only go to the terminal: nothing here writes them to a file or a log (and the command
refuses to print into a regular file).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, TextIO
from urllib.parse import urlencode

from michelito.web.app import create_app, local_mode
from michelito.web.workspace import Workspace

HASH_CHARS = 16
DECIMAL = re.compile(r"-?\d+\.\d+")


class FiguresError(Exception):
    """A figure could not be computed (the message names no value)."""


@dataclass(frozen=True)
class Section:
    name: str  # "summary 2025-01", "shared", "investments"
    payload: Any


def _get(app: Any, path: str, query: dict[str, str] | None = None) -> tuple[int, bytes]:
    """One GET to the ASGI `app`, in process (what a browser on 127.0.0.1 would ask)."""
    body: list[bytes] = []
    status: list[int] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": urlencode(query or {}).encode(),
        "headers": [(b"host", b"127.0.0.1"), (b"accept", b"application/json")],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(int(message["status"]))
        elif message["type"] == "http.response.body":
            body.append(message.get("body", b""))

    asyncio.run(app(scope, receive, send))
    return status[0], b"".join(body)


def collect(workspace: Workspace, months: Sequence[str], today: date) -> list[Section]:
    """The sections for `months` from the database of `workspace` (plain or encrypted)."""
    app = create_app(workspace.database, None, lambda: today, mode=local_mode(workspace))

    def fetch(path: str, query: dict[str, str] | None = None) -> Any:
        code, raw = _get(app, path, query)
        if code == 404:
            return None  # no data for it: the same on both sides
        if code != 200:
            raise FiguresError(f"{path} answered {code}")
        return json.loads(raw)

    found = [Section(f"summary {m}", fetch("/api/summary", {"month": m})) for m in months]
    found.append(Section("shared", fetch("/api/shared")))
    found.append(Section("investments", fetch("/api/investments")))
    return found


def fingerprint(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:HASH_CHARS]


def _numeric(value: Any) -> bool:
    """A number, or an amount sent as a decimal string ("1234.50")."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    return isinstance(value, str) and DECIMAL.fullmatch(value) is not None


def numbers(payload: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Every numeric leaf of `payload` with its path (labels and names are left out)."""
    if isinstance(payload, dict):
        for key in sorted(payload):
            yield from numbers(payload[key], f"{prefix}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            yield from numbers(item, f"{prefix}[{index}]")
    elif _numeric(payload):
        yield prefix or ".", payload


def render(sections: Sequence[Section], exact: bool) -> list[str]:
    lines = []
    if exact:
        for section in sections:
            for path, value in numbers(section.payload):
                lines.append(f"{section.name} {path} = {value}")
    else:
        width = max(len(s.name) for s in sections)
        for section in sections:
            lines.append(f"{section.name.ljust(width)}  {fingerprint(section.payload)}")
        everything = [[s.name, s.payload] for s in sections]
        lines.append(f"{'all'.ljust(width)}  {fingerprint(everything)}")
    return lines


def refuse_file(stream: TextIO) -> bool:
    """Whether `stream` is a regular file (the figures must not land on disk)."""
    try:
        mode = os.fstat(stream.fileno()).st_mode
    except (OSError, ValueError, AttributeError):
        return False  # not a real descriptor (a test's capture): fine
    return stat.S_ISREG(mode)


def show(
    workspace: Workspace,
    months: Sequence[str],
    today: date,
    exact: bool,
    write: Callable[[str], None] | None = None,
) -> None:
    out = write or (lambda line: print(line, file=sys.stdout))
    for line in render(collect(workspace, months, today), exact):
        out(line)
