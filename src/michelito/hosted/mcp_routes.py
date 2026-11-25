"""The AI connector's MCP endpoint: `POST /api/mcp` (Streamable HTTP, JSON answers, stateless).

Only an access token from `hosted.connector` opens it (`Authorization: Bearer`); the session
cookie never does, and the token opens nothing else. Without a valid token: 401 with the
`WWW-Authenticate` pointer to the resource metadata, which is how the client starts signing in.
Requests from a browser page of another origin are refused (DNS rebinding); token failures are
limited per source network (an expired but well-formed token does not count: Claude refreshes
from shared addresses) and each `tools/call` per connection.

JSON-RPC methods: `initialize`, `ping`, `tools/list` and `tools/call` (`hosted.mcp_tools`, the
import tools in `hosted.mcp_import_tools` and the onboarding one in `hosted.onboarding_guide`);
notifications are accepted and answered with 202. A tool's failure is a result with
`isError` (the AI reads why); a malformed message is a JSON-RPC error. Each call is logged with
the tool's name and outcome only: never its arguments or answer.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.types import ASGIApp

from michelito import config
from michelito.analysis.spending import Movement
from michelito.demo import network
from michelito.hosted import mcp_import_tools, mcp_tools, onboarding_guide, redact
from michelito.hosted.auth import SignIn
from michelito.hosted.connector import ACCESS_PREFIX, Caller, Connector
from michelito.hosted.limits import Window
from michelito.web import imports, internal, proposals
from michelito.web.workspace import CURRENT, Resolution

log = logging.getLogger(__name__)

MCP_PATH = "/api/mcp"
BODY_LIMIT = 256 * 1024
SERVER_NAME = "michelito"
SERVER_VERSION = "1.0.0"
SERVER_INFO = {"name": SERVER_NAME, "title": "Michelito", "version": SERVER_VERSION}
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
INSTRUCTIONS = (
    "Michelito holds the person's personal finances (Dominican Republic: DOP and USD). Read "
    "with the tools; amounts are in cents. You cannot change anything directly: to change "
    "categories use propose_category_changes, and to bring in transactions (a statement "
    "Michelito could not read, loose charges, cash) the import_ tools; give the person the "
    "link they return, so they approve it in Michelito. When the person wants to set up "
    "Michelito, call get_onboarding and follow its guide. "
    + mcp_tools.DATA_NOTE
    + " Answer the person in their language."
)
_BEARER = re.compile(r"Bearer ([A-Za-z0-9_-]{1,200})")

Connect = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]


@dataclass(frozen=True)
class McpCaps:
    """Requests without a valid token per source network per 15 minutes; tool calls per
    connection per hour."""

    unauthorized_per_source: int = 60
    calls_per_hour: int = 600


@dataclass
class Gate:
    """Resolves `MCP_PATH` requests by their bearer token (the provider asks it)."""

    service: SignIn
    connector: Connector
    url: str
    caps: McpCaps = field(default_factory=McpCaps)
    proxies: tuple[network.Network, ...] = ()

    def __post_init__(self) -> None:
        clock = self.connector.clock
        self._strangers = Window(self.caps.unauthorized_per_source, 15 * 60, clock)
        self._calls = Window(self.caps.calls_per_hour, 3600, clock)

    def challenge(self, error: str | None = None) -> JSONResponse:
        value = f'Bearer resource_metadata="{self.url}/.well-known/oauth-protected-resource"'
        if error:
            value += f', error="{error}"'
        return JSONResponse(
            {"error": error or "unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": value},
        )

    async def resolve(self, request: Request) -> Resolution:
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") != self.url:
            return Resolution(None, refusal=JSONResponse({"error": "origin"}, status_code=403))
        found = _BEARER.fullmatch(request.headers.get("authorization", ""))
        caller = (
            await anyio.to_thread.run_sync(self.connector.caller, found.group(1)) if found else None
        )
        if caller is None:
            # An expired token is normal (Claude refreshes once an hour, from shared addresses):
            # only requests without a well-formed token count against the source.
            if not (found and found.group(1).startswith(ACCESS_PREFIX)):
                keys = network.quota_keys(network.client_ip(request, self.proxies))
                if not self._strangers.take(keys):
                    return Resolution(None, refusal=JSONResponse({"error": "slow_down"}, 429))
            return Resolution(None, refusal=self.challenge("invalid_token" if found else None))
        request.state.mcp_caller = caller
        workspace = await anyio.to_thread.run_sync(self.service.workspace_of, caller.account)
        return Resolution(workspace)

    def take_call(self, caller: Caller) -> bool:
        """Whether the connection may run one more tool (each `tools/call` counts)."""
        return self._calls.take([(f"grant:{caller.grant_id}", 1)])


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    found: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        found["isError"] = True
    return found


def negotiate(requested: Any) -> str:
    return requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]


@dataclass(frozen=True)
class Context:
    app: ASGIApp
    host: str
    url: str
    caller: Caller
    connection: Connect
    load_flow: LoadFlow
    take_call: Callable[[Caller], bool]


async def _account_keys(ctx: Context) -> list[str]:
    workspace = CURRENT.get()
    assert workspace is not None
    answer = await internal.call(ctx.app, workspace, ctx.host, "GET", "/api/accounts")
    if answer.status != 200 or not isinstance(answer.body, list):
        return []
    return [str(a.get("key", "")) for a in answer.body if isinstance(a, dict)]


async def run_read(ctx: Context, tool: mcp_tools.ReadTool, arguments: Any) -> dict[str, Any]:
    try:
        checked = mcp_tools.check_arguments(tool, arguments)
    except mcp_tools.ToolInputError as error:
        return _text(str(error), is_error=True)
    if "accounts" in checked:
        keys = await _account_keys(ctx)
        real = [redact.unmask_key(given, keys) for given in checked["accounts"]]
        if any(key is None for key in real):
            return _text("unknown account: use the keys list_accounts shows", is_error=True)
        checked = {**checked, "accounts": real}
    path, query = mcp_tools.request_of(tool, checked)
    workspace = CURRENT.get()
    assert workspace is not None
    answer = await internal.call(ctx.app, workspace, ctx.host, "GET", path, query)
    if answer.status != 200:
        detail = answer.body.get("detail") if isinstance(answer.body, dict) else None
        reason = detail if isinstance(detail, str) else f"failed ({answer.status})"
        return _text(redact.mask_text(reason), is_error=True)
    if answer.body is None:
        return _text(mcp_tools.text_of(redact.mask_text(answer.text)))
    return _text(mcp_tools.text_of({"note": mcp_tools.DATA_NOTE, "data": redact.mask(answer.body)}))


async def run_onboarding(ctx: Context, arguments: Any) -> dict[str, Any]:
    """`get_onboarding`: the state the onboarding cards show (`hosted.onboarding`, read straight
    from the account's database: its routes need a session), turned into a guide."""
    if arguments not in (None, {}):
        return _text("get_onboarding takes no arguments", is_error=True)

    def read() -> dict[str, Any]:
        with ctx.connection() as conn:
            return onboarding_guide.read(conn, ctx.load_flow(conn), ctx.url)

    built = await anyio.to_thread.run_sync(read)
    return _text(mcp_tools.text_of({"note": mcp_tools.DATA_NOTE, "data": redact.mask(built)}))


def _changes(arguments: Any) -> tuple[str, str, list[proposals.Change]]:
    """The proposal's checked arguments (`ToolInputError` if they do not fit the schema)."""
    if not isinstance(arguments, dict):
        raise mcp_tools.ToolInputError("arguments must be an object")
    allowed = {"title", "explanation", "changes"}
    if set(arguments) - allowed:
        raise mcp_tools.ToolInputError("unknown argument")
    title, explanation, raw = (
        arguments.get("title"),
        arguments.get("explanation", ""),
        arguments.get("changes"),
    )
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise mcp_tools.ToolInputError("title must be a short text")
    if not isinstance(explanation, str) or len(explanation) > 2000:
        raise mcp_tools.ToolInputError("explanation must be a text of at most 2000 characters")
    if not isinstance(raw, list) or not 1 <= len(raw) <= proposals.ITEMS_MAX:
        raise mcp_tools.ToolInputError(f"changes must have 1 to {proposals.ITEMS_MAX} items")
    item_schema = mcp_tools.PROPOSE_SCHEMA["properties"]["changes"]["items"]
    found = []
    for index, change in enumerate(raw):
        if not isinstance(change, dict) or set(change) - set(item_schema["properties"]):
            raise mcp_tools.ToolInputError(f"changes[{index}] has unknown fields")
        for name in item_schema["required"]:
            if name not in change:
                raise mcp_tools.ToolInputError(f"changes[{index}] needs {name}")
        values = {
            name: mcp_tools._value(f"changes[{index}].{name}", item_schema["properties"][name], v)
            for name, v in change.items()
        }
        found.append(
            proposals.Change(
                values["fingerprint"],
                values["category_id"],
                values["scope"],
                values.get("reason", ""),
            )
        )
    return title, explanation, found


async def run_propose(ctx: Context, arguments: Any) -> dict[str, Any]:
    try:
        title, explanation, changes = _changes(arguments)
    except mcp_tools.ToolInputError as error:
        return _text(str(error), is_error=True)

    def save() -> int:
        with ctx.connection() as conn:
            return proposals.propose(
                conn, ctx.load_flow(conn), ctx.caller.client_name, title, explanation, changes
            )

    try:
        proposal_id = await anyio.to_thread.run_sync(save)
    except proposals.ProposalError as error:
        return _text(f"not saved: {error}", is_error=True)
    link = f"{ctx.url}/review?proposal={proposal_id}"
    return _text(
        json.dumps(
            {
                "proposal_id": proposal_id,
                "changes": len(changes),
                "link": link,
                "next": "Nothing changed yet. Give the person this link to review and approve "
                "it in Michelito.",
            }
        )
    )


def _saved(ctx: Context, proposal_id: int, extra: dict[str, Any]) -> dict[str, Any]:
    return _text(
        json.dumps(
            {
                "proposal_id": proposal_id,
                **extra,
                "link": f"{ctx.url}/review?proposal={proposal_id}",
                "next": "Nothing changed yet. Give the person this link to review and approve "
                "it in Michelito.",
            }
        )
    )


async def run_import(ctx: Context, name: str, arguments: Any) -> dict[str, Any]:
    """`import_statement`, `import_provisional_charges` or `import_cash_entries`: checked, then
    saved as a proposal (`web.imports`). Refusals carry only codes and the AI's own numbers."""
    rows: list[imports.RowIn] = []
    payload: dict[str, Any] = {}
    try:
        if name == mcp_import_tools.STATEMENT:
            found, payload = mcp_import_tools.statement_of(arguments)
        else:
            found, rows = mcp_import_tools.rows_of(arguments, name)
    except mcp_tools.ToolInputError as error:
        return _text(str(error), is_error=True)
    account = ""
    if "account" in found:
        real = redact.unmask_key(str(found["account"]), await _account_keys(ctx))
        if real is None:
            return _text("unknown account: use a key list_accounts shows", is_error=True)
        account = real
    title, explanation = found["title"], found.get("explanation", "")
    source = ctx.caller.client_name

    def save() -> tuple[int, int]:
        today = config.local_today()
        with ctx.connection() as conn:
            if name == mcp_import_tools.STATEMENT:
                made = imports.propose_statement(
                    conn, today, source, title, explanation, account, payload
                )
            else:
                kind: imports.RowKind = "cash" if name == mcp_import_tools.CASH else "provisional"
                made = imports.propose_rows(
                    conn,
                    ctx.load_flow(conn),
                    today,
                    source,
                    title,
                    explanation,
                    kind,
                    account,
                    rows,
                )
            repeated = conn.execute(
                "SELECT COUNT(*) FROM ai_import_rows WHERE proposal_id = ? AND duplicate_of != ''",
                (made,),
            ).fetchone()[0]
        return made, int(repeated)

    try:
        proposal_id, repeated = await anyio.to_thread.run_sync(save)
    except proposals.ProposalError as error:
        return _text(f"not saved: {error}", is_error=True)
    extra: dict[str, Any] = {"rows": len(rows)} if rows else {"statement": "squares"}
    if repeated:
        extra["possible_duplicates"] = repeated
    return _saved(ctx, proposal_id, extra)


async def call_tool(ctx: Context, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        return _text("tools/call needs a tool name", is_error=True)
    name = params["name"]
    arguments = params.get("arguments")
    if name == mcp_tools.PROPOSE:
        result = await run_propose(ctx, arguments)
    elif name in mcp_import_tools.NAMES:
        result = await run_import(ctx, name, arguments)
    elif name == onboarding_guide.NAME:
        result = await run_onboarding(ctx, arguments)
    elif name in mcp_tools.BY_NAME:
        result = await run_read(ctx, mcp_tools.BY_NAME[name], arguments)
    else:
        return _text(f"unknown tool {name[:60]}", is_error=True)
    log.info("mcp tool %s: %s", name, "error" if result.get("isError") else "ok")
    return result


async def handle(ctx: Context, message: Any) -> dict[str, Any] | None:
    """One JSON-RPC message's answer (None for a notification)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "invalid request")
    method = message.get("method")
    if "id" not in message:
        return None  # a notification (initialized, cancelled...): nothing to answer
    message_id = message["id"]
    params = message.get("params")
    if method == "initialize":
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        return _result(
            message_id,
            {
                "protocolVersion": negotiate(requested),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "title": "Michelito",
                    "version": SERVER_VERSION,
                },
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        tools = [
            *mcp_tools.descriptors(),
            *mcp_import_tools.descriptors(),
            *onboarding_guide.descriptors(),
        ]
        return _result(message_id, {"tools": tools})
    if method == "tools/call":
        if not ctx.take_call(ctx.caller):
            return _result(message_id, _text("too many calls: wait a few minutes", is_error=True))
        return _result(message_id, await call_tool(ctx, params))
    return _error(message_id, -32601, "method not found")


def register(app: FastAPI, gate: Gate, connection: Connect, load_flow: LoadFlow) -> None:
    @app.post(MCP_PATH, include_in_schema=False)
    async def post_mcp(request: Request) -> Response:
        caller: Caller | None = getattr(request.state, "mcp_caller", None)
        if caller is None:  # the gate answers first; this only happens without it
            return gate.challenge()
        try:
            body = json.loads(await request.body())
        except ValueError:
            return JSONResponse(_error(None, -32700, "parse error"), status_code=400)
        ctx = Context(
            app,
            request.headers.get("host", ""),
            gate.url,
            caller,
            connection,
            load_flow,
            gate.take_call,
        )
        if isinstance(body, list):
            answers = [a for a in [await handle(ctx, m) for m in body[:20]] if a is not None]
            return JSONResponse(answers) if answers else Response(status_code=202)
        answer = await handle(ctx, body)
        if answer is None:
            return Response(status_code=202)
        return JSONResponse(answer)

    @app.get(MCP_PATH, include_in_schema=False)
    @app.delete(MCP_PATH, include_in_schema=False)
    def other_methods() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})
