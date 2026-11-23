"""Hosted mode's routes for the browser extension (see `hosted.extension`).

With the session (Settings):

- `GET /api/extension`: whether an extension is linked, when, its last use and how many orders
  have names;
- `POST /api/extension/code`: a new one-time code (10 minutes; the previous one stops working);
- `DELETE /api/extension`: revoke: the token stops working at once (the names already sent stay,
  like any other receipt detail);
- `GET /api/extension/download`: the extension's zip (`hosted.extension_bundle`).

Without a session, only from the extension (`EXTENSION_ORIGIN`, or no `Origin` at all, as a
non-browser client sends): any other origin is refused before anything is read, and only the
extension's origin is ever named in `Access-Control-Allow-Origin`. Neither route uses cookies, so
a page cannot make the browser send the token for it (no CSRF):

- `POST /api/extension/link` (`{"code"}`) → `{"token"}`: the code once, for the account's
  token. Attempts are limited per source network and for the whole server.
- `PUT /api/extension/orders` (`Authorization: Bearer <token>`, `{"orders": [{"order",
  "items": [{"title", "quantity"?, "price_cents"?}]}]}`) → `{"orders", "items",
  "with_receipt"}`: an idempotent upsert of each order's item names
  (`analysis.receipt_items`). The token is checked before the body is read; requests without a
  valid one are limited per source network, and valid ones per account. The body is limited in
  size (`BODY_LIMIT`) and validated strictly: an order number of the merchant's shape, at most
  `ORDERS_PER_REQUEST` orders and `receipt_items.ITEMS_MAX` items each, plain-text titles
  (invisible and control characters removed, whitespace collapsed) and nothing else: any other
  field is refused. A refusal names only the field that failed, never a value. Nothing it
  receives is logged.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

from michelito import db
from michelito.analysis import changelog, receipt_items
from michelito.demo import network
from michelito.hosted import extension_bundle
from michelito.hosted.auth import SignIn
from michelito.hosted.extension import Linker
from michelito.hosted.limits import Window
from michelito.hosted.routes import current
from michelito.hosted.store import Account
from michelito.i18n import t

log = logging.getLogger(__name__)

EXTENSION_ID = "mkahllpkflehegjefgjplmgcnoahblaa"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"
LINK_PATH = "/api/extension/link"
ORDERS_PATH = "/api/extension/orders"
OPEN_PATHS = frozenset({LINK_PATH, ORDERS_PATH})
BODY_LIMIT = 256 * 1024
ORDERS_PER_REQUEST = 20
ORDER_PATTERN = r"^[0-9A-Z]{3}-[0-9]{7}-[0-9]{7}$"
PRICE_MAX = 100_000_000  # US$ 1,000,000 in cents
_BEARER = re.compile(r"Bearer ([A-Za-z0-9_-]{1,200})")

Connect = Callable[[], AbstractContextManager[sqlite3.Connection]]


@dataclass(frozen=True)
class ExtensionCaps:
    """Codes made per account per hour; link attempts per source network per 15 minutes, and
    wrong codes for the whole server per hour; requests without a valid token per source network
    per 15 minutes; and accepted requests per account per hour (a walk sends one per page)."""

    codes_per_hour: int = 10
    links_per_source: int = 10
    links_per_hour: int = 300
    unauthorized_per_source: int = 30
    orders_per_hour: int = 300


@dataclass
class Hooks:
    service: SignIn
    linker: Linker
    caps: ExtensionCaps = field(default_factory=ExtensionCaps)
    proxies: tuple[network.Network, ...] = ()


def _plain(text: str) -> str:
    """Visible text only: no control or format characters, single spaces."""
    kept = "".join(
        " " if unicodedata.category(c) == "Cc" else c
        for c in text
        if unicodedata.category(c) not in ("Cf", "Co", "Cs")
    )
    return " ".join(kept.split())


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[StrictStr, Field(max_length=receipt_items.TITLE_MAX)]
    quantity: Annotated[StrictInt, Field(ge=1, le=receipt_items.QUANTITY_MAX)] | None = None
    price_cents: Annotated[StrictInt, Field(ge=0, le=PRICE_MAX)] | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        cleaned = _plain(value)
        if not cleaned:
            raise ValueError("empty")
        return cleaned


class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: Annotated[StrictStr, Field(pattern=ORDER_PATTERN)]
    items: Annotated[list[ItemIn], Field(min_length=1, max_length=receipt_items.ITEMS_MAX)]


class OrdersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orders: Annotated[list[OrderIn], Field(min_length=1, max_length=ORDERS_PER_REQUEST)]


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[StrictStr, Field(max_length=40)]


class StatusOut(BaseModel):
    linked: bool
    linked_at: str | None
    last_used_at: str | None
    orders: int  # orders with names


class CodeOut(BaseModel):
    code: str
    expires_at: str


def _iso(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, UTC).isoformat()


def _refused(status: int, key: str) -> JSONResponse:
    return JSONResponse({"detail": t(key)}, status_code=status)


def _invalid(error: ValidationError) -> JSONResponse:
    """Which fields failed, never their values."""
    where = sorted({".".join(str(part) for part in e["loc"]) for e in error.errors()})[:10]
    return JSONResponse({"detail": "invalid body", "fields": where}, status_code=422)


def _for_extension(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = EXTENSION_ORIGIN
    response.headers["Vary"] = "Origin"
    return response


def register(app: FastAPI, hooks: Hooks, connection: Connect) -> None:
    service, linker, caps = hooks.service, hooks.linker, hooks.caps
    clock = linker.clock
    codes = Window(caps.codes_per_hour, 3600, clock)
    link_sources = Window(caps.links_per_source, 15 * 60, clock)
    link_everyone = Window(caps.links_per_hour, 3600, clock)
    strangers = Window(caps.unauthorized_per_source, 15 * 60, clock)
    sends = Window(caps.orders_per_hour, 3600, clock)

    def source(request: Request) -> tuple[tuple[str, int], ...]:
        return network.quota_keys(network.client_ip(request, hooks.proxies))

    def other_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        return origin is not None and origin != EXTENSION_ORIGIN

    def status_of(account_id: int) -> StatusOut:
        link = linker.status(account_id)
        with connection() as conn:
            stored = receipt_items.count(conn)
        return StatusOut(
            linked=link is not None,
            linked_at=_iso(link.linked_at) if link else None,
            last_used_at=_iso(link.last_used_at) if link else None,
            orders=stored,
        )

    @app.get("/api/extension")
    def get_status(request: Request) -> StatusOut:
        return status_of(current(request).account.id)

    @app.post("/api/extension/code")
    def post_code(request: Request) -> CodeOut:
        account_id = current(request).account.id
        if not codes.take([(f"account:{account_id}", 1)]):
            raise HTTPException(429, t("extension.rate_limited"))
        code, expires_at = linker.issue(account_id)
        return CodeOut(code=code, expires_at=_iso(expires_at) or "")

    @app.delete("/api/extension")
    def delete_link(request: Request) -> StatusOut:
        account_id = current(request).account.id
        linker.revoke(account_id)
        return status_of(account_id)

    @app.get("/api/extension/download")
    def get_download(request: Request) -> Response:
        current(request)
        return Response(
            extension_bundle.bundle(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{extension_bundle.FILENAME}"'},
        )

    @app.post(LINK_PATH)
    async def post_link(request: Request) -> Response:
        if other_origin(request):
            return _refused(403, "extension.other_origin")
        if not link_everyone.can([("all", 1)]) or not link_sources.take(source(request)):
            return _for_extension(_refused(429, "extension.rate_limited"))
        try:
            body = LinkIn.model_validate_json(await request.body())
        except ValidationError as error:
            return _for_extension(_invalid(error))
        token = await anyio.to_thread.run_sync(linker.exchange, body.code)
        if token is None:
            link_everyone.take([("all", 1)])  # only wrong codes use the server's budget
            return _for_extension(_refused(400, "extension.bad_code"))
        return _for_extension(JSONResponse({"token": token}))

    def save(account: Account, orders: OrdersIn) -> dict[str, int]:
        """In a thread: the token's account's own database, opened for this request only."""
        workspace = service.workspace_of(account)
        assert workspace.key is not None
        found = [
            receipt_items.Order(
                o.order,
                tuple(receipt_items.Item(i.title, i.quantity, i.price_cents) for i in o.items),
            )
            for o in orders.orders
        ]
        with closing(db.connect(workspace.database, workspace.key)) as conn, conn:
            saved = receipt_items.save(conn, found, changelog.now().isoformat())
            matched = receipt_items.with_receipt(conn, [o.number for o in found])
        return {"orders": saved.orders, "items": saved.items, "with_receipt": matched}

    @app.put(ORDERS_PATH)
    async def put_orders(request: Request) -> Response:
        if other_origin(request):
            return _refused(403, "extension.other_origin")
        found = _BEARER.fullmatch(request.headers.get("authorization", ""))
        account = (
            await anyio.to_thread.run_sync(linker.account_of, found.group(1)) if found else None
        )
        if account is None:
            if not strangers.take(source(request)):
                return _for_extension(_refused(429, "extension.rate_limited"))
            return _for_extension(_refused(401, "extension.no_token"))
        if not sends.take([(f"account:{account.id}", 1)]):
            return _for_extension(_refused(429, "extension.rate_limited"))
        try:
            orders = OrdersIn.model_validate_json(await request.body())
        except ValidationError as error:
            return _for_extension(_invalid(error))
        try:
            answer = await anyio.to_thread.run_sync(save, account, orders)
        except receipt_items.TooManyOrders:
            return _for_extension(_refused(409, "extension.too_many_orders"))
        except Exception as exc:  # noqa: BLE001 - never the body: only the class name
            log.error("item names could not be saved: %s", type(exc).__name__)
            return _for_extension(_refused(503, "extension.failed"))
        return _for_extension(JSONResponse(answer))
