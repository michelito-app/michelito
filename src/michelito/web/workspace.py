"""Where each request's database comes from: the board's *workspace provider*.

`create_app` no longer opens a fixed path: before each request it asks the provider which
`Workspace` (database and holders) the request gets, and `connection()` opens that one. So the
same FastAPI app serves:

- the local board (`FixedProvider`): always the database and holders of the data folder;
- the public demo (`michelito.demo.copies.DemoProvider`): the visitor's copy, by their cookie;
- in phase 2, the authenticated user's database (another provider with the same interface).

A request without a `Workspace` (no demo session) opens no database: `connection()` answers 401
and nothing is written anywhere.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from starlette.requests import Request
from starlette.responses import Response


@dataclass(frozen=True)
class Workspace:
    """A request's database and its holders file. `key`: the database's encryption key (hosted
    mode; never shown in `repr`); None for a plain file (the local board and the demo)."""

    database: Path
    holders: Path
    key: bytes | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Resolution:
    """What the provider decided for a request.

    `workspace`: the database it gets (None: none). `refusal`: a response that stops the request
    before it reaches the route (e.g. too many requests). `finish`: called (in a thread, off the
    event loop) with the route's response, e.g. to count a use. `release`: always called when
    the request ends (e.g. it frees a work slot)."""

    workspace: Workspace | None
    refusal: Response | None = None
    finish: Callable[[Response], None] | None = None
    release: Callable[[], None] | None = None


class WorkspaceProvider(Protocol):
    async def resolve(self, request: Request) -> Resolution:
        """This request's database (a middleware calls it, before the route). Anything that
        touches the disk runs in a thread: it must not block the event loop."""
        ...

    def has_session(self, request: Request) -> bool:
        """Whether the request already has its own database (always, locally)."""
        ...


@dataclass(frozen=True)
class FixedProvider:
    """The local board: always the same database and the same holders."""

    workspace: Workspace

    async def resolve(self, request: Request) -> Resolution:
        return Resolution(self.workspace)

    def has_session(self, request: Request) -> bool:
        return True


CURRENT: ContextVar[Workspace | None] = ContextVar("michelito_workspace", default=None)


Register = Callable[..., None]
OnConnect = Callable[[sqlite3.Connection], None]
Guard = Callable[..., Response | None]


@dataclass(frozen=True)
class Mode:
    """What differs between the local board and the public demo (see `create_app`).

    `name`: "local" or "demo". `allowed_hosts`: the ones `TrustedHostMiddleware` accepts.
    `authors`: the accepted `X-Michelito-Author` values (in the demo, only the user). `blocked`:
    route prefixes that answer 403. `max_body`: maximum body size in bytes (None: no limit).
    `info`: what `GET /api/mode` tells the interface. `register(app, connection, load_flow)`:
    the mode's own routes, registered before the "not found" one. `on_connect`: applied to every
    connection `connection()` opens (in the demo, the copy's size limit). `body_limits`: a larger
    body size for some exact paths (hosted uploads). `open_writes`: exact paths whose writes do
    not need `X-Michelito` (the installed app's share target, which opens no database). `guard`:
    called (in a thread) with the request and `connection` once the request has its database,
    before the route; a response it returns stops the request (hosted mode: the upload gate).
    `landing`: HTML put inside the interface's `#root` on the home page only, which the interface
    replaces when it starts (hosted mode: what the app is, for readers that run no JavaScript)."""

    name: str
    provider: WorkspaceProvider
    allowed_hosts: tuple[str, ...]
    authors: tuple[str, ...]
    blocked: tuple[str, ...] = ()
    max_body: int | None = None
    info: dict[str, str] | None = None
    register: Register | None = None
    on_connect: OnConnect | None = None
    body_limits: tuple[tuple[str, int], ...] = ()
    open_writes: frozenset[str] = frozenset()
    guard: Guard | None = None
    landing: str | None = None
