"""The AI connector's OAuth routes (hosted mode; see `hosted.connector`).

Without a session (they are what the MCP client calls):

- `GET /.well-known/oauth-protected-resource` (also under `/api/mcp`): the MCP endpoint's
  resource metadata (RFC 9728), naming this server as its authorization server;
- `GET /.well-known/oauth-authorization-server`: the authorization server metadata (RFC 8414):
  authorization code with S256 PKCE, public clients only, dynamic registration;
- `POST /oauth/register`: dynamic client registration (RFC 7591), JSON, limited per source
  network and for the whole server;
- `GET /oauth/authorize`: checks the request and sends the person to the consent screen
  (`/connect?request=...`); a request with an unknown client or redirect URI is answered here
  and never redirected;
- `POST /oauth/token`: form-encoded, `authorization_code` and `refresh_token`; errors are
  RFC 6749 codes; never cached.

With the session (the consent screen and Settings): `GET /api/connector/requests/{id}` (who is
asking), `POST /api/connector/requests/{id}` (`{"approve"}` → `{"redirect"}`),
`GET /api/connector/connections` and `DELETE /api/connector/connections/{id}`.

Nothing a client sends is logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from michelito.demo import network
from michelito.hosted.connector import KNOWN_SCOPES, SCOPE, Connector, ConnectorError
from michelito.hosted.limits import Window
from michelito.hosted.routes import current
from michelito.i18n import t

PROTECTED_PATH = "/.well-known/oauth-protected-resource"
SERVER_PATH = "/.well-known/oauth-authorization-server"
REGISTER_PATH = "/oauth/register"
AUTHORIZE_PATH = "/oauth/authorize"
TOKEN_PATH = "/oauth/token"
CONSENT_PATH = "/connect"
OPEN_WRITES = frozenset({REGISTER_PATH, TOKEN_PATH})
FORM_MAX = 8 * 1024
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@dataclass(frozen=True)
class ConnectorCaps:
    """Registrations per source network per hour and for the whole server; authorization
    requests and token requests per source network per 15 minutes; decisions per account per
    hour."""

    registrations_per_source: int = 20
    registrations_per_hour: int = 500
    authorizations_per_source: int = 60
    # Claude's servers send every user's refreshes from a few addresses: generous.
    tokens_per_source: int = 3000
    decisions_per_hour: int = 30


@dataclass
class Hooks:
    connector: Connector
    url: str  # this server's public URL, without a trailing slash
    resource: str  # the MCP endpoint's URL
    caps: ConnectorCaps = field(default_factory=ConnectorCaps)
    proxies: tuple[network.Network, ...] = ()


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: StrictBool


class RequestOut(BaseModel):
    client_name: str
    redirect_host: str


class DecisionOut(BaseModel):
    redirect: str


class ConnectionOut(BaseModel):
    id: int
    client_name: str
    created_at: str
    last_used_at: str


def _iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat()


def oauth_error(code: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status, headers=_NO_STORE)


def protected_metadata(hooks: Hooks) -> dict[str, Any]:
    return {
        "resource": hooks.resource,
        "authorization_servers": [hooks.url],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Michelito",
    }


def server_metadata(hooks: Hooks) -> dict[str, Any]:
    return {
        "issuer": hooks.url,
        "authorization_endpoint": hooks.url + AUTHORIZE_PATH,
        "token_endpoint": hooks.url + TOKEN_PATH,
        "registration_endpoint": hooks.url + REGISTER_PATH,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": sorted(KNOWN_SCOPES),
    }


def register(app: FastAPI, hooks: Hooks) -> None:
    connector, caps = hooks.connector, hooks.caps
    clock = connector.clock
    sources = Window(caps.registrations_per_source, 3600, clock)
    everyone = Window(caps.registrations_per_hour, 3600, clock)
    tokens = Window(caps.tokens_per_source, 15 * 60, clock)
    authorizations = Window(caps.authorizations_per_source, 15 * 60, clock)
    decisions = Window(caps.decisions_per_hour, 3600, clock)

    def source(request: Request) -> tuple[tuple[str, int], ...]:
        return network.quota_keys(network.client_ip(request, hooks.proxies))

    @app.get(PROTECTED_PATH, include_in_schema=False)
    @app.get(PROTECTED_PATH + "/api/mcp", include_in_schema=False)
    def get_protected() -> JSONResponse:
        return JSONResponse(protected_metadata(hooks))

    @app.get(SERVER_PATH, include_in_schema=False)
    def get_server() -> JSONResponse:
        return JSONResponse(server_metadata(hooks))

    @app.post(REGISTER_PATH, include_in_schema=False)
    async def post_register(request: Request) -> Response:
        if not everyone.can([("all", 1)]) or not sources.take(source(request)):
            return oauth_error("temporarily_unavailable", 429)
        try:
            body = json.loads(await request.body())
        except ValueError:
            return oauth_error("invalid_client_metadata")
        if not isinstance(body, dict):
            return oauth_error("invalid_client_metadata")
        try:
            client = await anyio.to_thread.run_sync(
                connector.register_client, body.get("client_name"), body.get("redirect_uris")
            )
        except ConnectorError as error:
            return oauth_error(error.code)
        everyone.take([("all", 1)])
        return JSONResponse(
            {
                "client_id": client.client_id,
                "client_id_issued_at": int(clock()),
                "client_name": client.name,
                "redirect_uris": list(client.redirect_uris),
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            status_code=201,
            headers=_NO_STORE,
        )

    @app.get(AUTHORIZE_PATH, include_in_schema=False)
    def get_authorize(request: Request) -> Response:
        if not authorizations.take(source(request)):
            return Response(t("connector.rate_limited"), status_code=429, media_type="text/plain")
        query = dict(request.query_params)
        redirect_uri = query.get("redirect_uri", "")
        try:
            client = connector.check_client(query.get("client_id", ""), redirect_uri)
        except ConnectorError:
            # Unknown client or redirect URI: never redirected anywhere.
            return Response(t("connector.bad_request"), status_code=400, media_type="text/plain")
        try:
            request_id = connector.start(client, query)
        except ConnectorError as error:
            return RedirectResponse(
                connector.error_redirect(redirect_uri, error.code, query.get("state")), 302
            )
        return RedirectResponse(f"{hooks.url}{CONSENT_PATH}?request={request_id}", 302)

    @app.post(TOKEN_PATH, include_in_schema=False)
    async def post_token(request: Request) -> Response:
        if not tokens.take(source(request)):
            return oauth_error("temporarily_unavailable", 429)
        raw = await request.body()
        if len(raw) > FORM_MAX:
            return oauth_error("invalid_request")
        form = dict(parse_qsl(raw.decode("utf-8", errors="replace"), keep_blank_values=True))
        client_id = form.get("client_id", "")
        if await anyio.to_thread.run_sync(connector.client, client_id) is None:
            return oauth_error("invalid_client", 401)
        grant = form.get("grant_type")
        try:
            if grant == "authorization_code":
                found = await anyio.to_thread.run_sync(
                    connector.exchange_code,
                    client_id,
                    form.get("code", ""),
                    form.get("redirect_uri", ""),
                    form.get("code_verifier", ""),
                )
            elif grant == "refresh_token":
                found = await anyio.to_thread.run_sync(
                    connector.refresh, client_id, form.get("refresh_token", "")
                )
            else:
                return oauth_error("unsupported_grant_type")
        except ConnectorError as error:
            return oauth_error(error.code)
        return JSONResponse(
            {
                "access_token": found.access_token,
                "token_type": "Bearer",
                "expires_in": found.expires_in,
                "refresh_token": found.refresh_token,
                "scope": found.scope,
            },
            headers=_NO_STORE,
        )

    @app.get("/api/connector/requests/{request_id}")
    def get_request(request_id: str, request: Request) -> RequestOut:
        current(request)
        found = connector.pending(request_id)
        if found is None:
            raise HTTPException(404, t("connector.request_gone"))
        return RequestOut(client_name=found.client_name, redirect_host=found.redirect_host)

    @app.post("/api/connector/requests/{request_id}")
    def post_request(request_id: str, body: DecisionIn, request: Request) -> DecisionOut:
        account_id = current(request).account.id
        if not decisions.take([(f"account:{account_id}", 1)]):
            raise HTTPException(429, t("connector.rate_limited"))
        redirect = connector.decide(request_id, account_id, body.approve)
        if redirect is None:
            raise HTTPException(404, t("connector.request_gone"))
        return DecisionOut(redirect=redirect)

    @app.get("/api/connector/connections")
    def get_connections(request: Request) -> list[ConnectionOut]:
        account_id = current(request).account.id
        return [
            ConnectionOut(
                id=g.id,
                client_name=g.client_name,
                created_at=_iso(g.created_at),
                last_used_at=_iso(g.last_used_at),
            )
            for g in connector.connections(account_id)
        ]

    @app.delete("/api/connector/connections/{grant_id}", status_code=204)
    def delete_connection(grant_id: int, request: Request) -> Response:
        if not connector.revoke(current(request).account.id, grant_id):
            raise HTTPException(404, t("connector.connection_gone"))
        return Response(status_code=204)
