"""The AI connector's OAuth 2.1 server (hosted mode; routes in `hosted.connector_routes`).

An MCP client (Claude) connects to an account like this:

1. **Registration** (RFC 7591, `register_client`): the client registers itself with its name and
   redirect URIs. Only the redirect URIs in `Policy.redirect_uris` (Claude's callback) are
   accepted, so a code can only ever travel to Claude. It gets a random `client_id`; it is a
   public client (no secret: PKCE protects the code).
2. **Authorization** (`start`): the client sends the person to `/oauth/authorize`; a valid
   request is kept for `REQUEST_SECONDS` under a random id and the person sees the consent
   screen in Michelito (signed in). `decide` answers it: approved, a one-time code for
   `CODE_SECONDS`, bound to the account, the client, the redirect URI and the PKCE challenge
   (S256 only); refused, `access_denied`.
3. **Tokens** (`exchange_code`, `refresh`): the code with its PKCE verifier gives an access token
   (`ACCESS_SECONDS`) and a refresh token; each refresh gives a new pair and the old one stops
   working (rotation). Both belong to one **connection** (a grant): it lasts until the person
   revokes it in Settings, stays unused for `IDLE_SECONDS`, or signs out everywhere; deleting or
   suspending the account ends it too.

Only the SHA-256 of requests, codes and tokens is stored (`connector_*` tables in the accounts
database, migration 10). A token never opens a session or any `/api` route: only the MCP
endpoint (`hosted.mcp_routes`) accepts it. Times are whole seconds since the epoch.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

from michelito.hosted.store import Account, Store

SCOPE = "michelito"
OFFLINE = "offline_access"  # accepted and ignored: every connection gets a refresh token
KNOWN_SCOPES = frozenset({SCOPE, OFFLINE})
CLAUDE_CALLBACKS = (
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
)
REQUEST_SECONDS = 10 * 60
REQUESTS_PER_CLIENT = 10  # pending authorization requests one client may have at once
REQUESTS_MAX = 2000  # and the whole server
CODE_SECONDS = 60
ACCESS_SECONDS = 3600
IDLE_SECONDS = 90 * 24 * 3600
TOUCH_SECONDS = 60  # last use is written at most once a minute
CLIENT_UNUSED_SECONDS = 24 * 3600  # a client nobody connected with is forgotten after a day
NAME_MAX = 80
STATE_MAX = 512
REDIRECTS_MAX = 5
TOKEN_MAX = 120
_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_ACCOUNT = "a.id, a.email, a.created_at, a.status, a.folder"

ACCESS_PREFIX = "mcpa_"
REFRESH_PREFIX = "mcpr_"
CODE_PREFIX = "mcpc_"
REQUEST_PREFIX = "mcpq_"
CLIENT_PREFIX = "mcpk_"


class ConnectorError(Exception):
    """An OAuth error: `code` is the RFC 6749 / 7591 error code (`invalid_grant`, ...)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Policy:
    redirect_uris: tuple[str, ...] = CLAUDE_CALLBACKS
    resource: str = ""  # the MCP endpoint's exact URL (the `resource` clients must name)


@dataclass(frozen=True)
class Client:
    client_id: str
    name: str
    redirect_uris: tuple[str, ...]


@dataclass(frozen=True)
class Pending:
    """An authorization request waiting for the person's answer."""

    client_name: str
    redirect_host: str


@dataclass(frozen=True)
class Tokens:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    scope: str


@dataclass(frozen=True)
class Grant:
    """A connection as Settings lists it."""

    id: int
    client_name: str
    created_at: int
    last_used_at: int


@dataclass(frozen=True)
class Caller:
    """Who an access token belongs to."""

    account: Account
    grant_id: int
    client_name: str


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def plain_name(text: str) -> str:
    """A client's name as shown: visible characters only, single spaces, cut to `NAME_MAX`."""
    kept = "".join(c for c in text if unicodedata.category(c)[0] not in ("C",))
    return " ".join(kept.split())[:NAME_MAX]


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _with_query(uri: str, params: dict[str, str]) -> str:
    joiner = "&" if urlsplit(uri).query else "?"
    return f"{uri}{joiner}{urlencode(params)}"


class Connector:
    """Clients, requests, codes and connections over the accounts `store`."""

    def __init__(
        self, store: Store, policy: Policy, clock: Callable[[], float] = time.time
    ) -> None:
        self.store = store
        self.policy = policy
        self.clock = clock

    def __repr__(self) -> str:
        return "Connector()"

    def _now(self) -> int:
        return int(self.clock())

    # Registration ------------------------------------------------------------------------

    def register_client(self, name: object, redirect_uris: object) -> Client:
        """A new public client. `invalid_redirect_uri` unless every URI is an allowed one;
        `invalid_client_metadata` for a missing or malformed name or list."""
        if not isinstance(redirect_uris, list) or not 1 <= len(redirect_uris) <= REDIRECTS_MAX:
            raise ConnectorError("invalid_redirect_uri")
        if not all(isinstance(u, str) and u in self.policy.redirect_uris for u in redirect_uris):
            raise ConnectorError("invalid_redirect_uri")
        shown = plain_name(name) if isinstance(name, str) else ""
        if name is not None and not isinstance(name, str):
            raise ConnectorError("invalid_client_metadata")
        client = Client(
            _token(CLIENT_PREFIX)[:32], shown or "MCP", tuple(dict.fromkeys(redirect_uris))
        )
        with self.store.connect() as conn, conn:
            conn.execute(
                "INSERT INTO connector_clients (client_id, name, redirect_uris, created_at) "
                "VALUES (?, ?, ?, ?)",
                (client.client_id, client.name, json.dumps(client.redirect_uris), self._now()),
            )
        return client

    def client(self, client_id: str) -> Client | None:
        if not client_id.startswith(CLIENT_PREFIX) or len(client_id) > TOKEN_MAX:
            return None
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT client_id, name, redirect_uris FROM connector_clients WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        if row is None:
            return None
        return Client(row["client_id"], row["name"], tuple(json.loads(row["redirect_uris"])))

    # Authorization -----------------------------------------------------------------------

    def check_client(self, client_id: str, redirect_uri: str) -> Client:
        """The client, if `redirect_uri` is one of its own (else the request must not redirect
        anywhere: `invalid_client` / `invalid_redirect_uri`)."""
        client = self.client(client_id)
        if client is None:
            raise ConnectorError("invalid_client")
        if redirect_uri not in client.redirect_uris:
            raise ConnectorError("invalid_redirect_uri")
        return client

    def start(self, client: Client, query: dict[str, str]) -> str:
        """Keep a valid authorization request (its client and redirect URI already checked) and
        return its id. Errors are ones the client receives at its redirect URI."""
        if query.get("response_type") != "code":
            raise ConnectorError("unsupported_response_type")
        challenge = query.get("code_challenge", "")
        if query.get("code_challenge_method") != "S256" or not _CHALLENGE.fullmatch(challenge):
            raise ConnectorError("invalid_request")
        resource = query.get("resource")
        if resource is not None and resource.rstrip("/") != self.policy.resource.rstrip("/"):
            raise ConnectorError("invalid_target")
        requested = set(query.get("scope", SCOPE).split()) or {SCOPE}
        if not requested <= KNOWN_SCOPES:
            raise ConnectorError("invalid_scope")
        state = query.get("state", "")
        if len(state) > STATE_MAX:
            raise ConnectorError("invalid_request")
        request_id = _token(REQUEST_PREFIX)
        now = self._now()
        with self.store.connect() as conn, conn:
            waiting = conn.execute(
                "SELECT COUNT(*) FROM connector_requests WHERE expires_at >= ? AND client_id = ?",
                (now, client.client_id),
            ).fetchone()[0]
            everyone = conn.execute(
                "SELECT COUNT(*) FROM connector_requests WHERE expires_at >= ?", (now,)
            ).fetchone()[0]
            if waiting >= REQUESTS_PER_CLIENT or everyone >= REQUESTS_MAX:
                raise ConnectorError("temporarily_unavailable")
            conn.execute(
                "INSERT INTO connector_requests (request_hash, client_id, redirect_uri, state, "
                "code_challenge, scope, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _hash(request_id),
                    client.client_id,
                    query["redirect_uri"],
                    state,
                    challenge,
                    SCOPE,
                    now + REQUEST_SECONDS,
                ),
            )
        return request_id

    def error_redirect(self, redirect_uri: str, code: str, state: str | None) -> str:
        params = {"error": code}
        if state:
            params["state"] = state
        return _with_query(redirect_uri, params)

    def pending(self, request_id: str) -> Pending | None:
        row = self._request(request_id)
        if row is None:
            return None
        return Pending(row["name"], urlsplit(row["redirect_uri"]).hostname or "")

    def _request(self, request_id: str):  # noqa: ANN202 - a sqlite3.Row or None
        if not request_id.startswith(REQUEST_PREFIX) or len(request_id) > TOKEN_MAX:
            return None
        with self.store.connect() as conn:
            return conn.execute(
                "SELECT r.*, c.name FROM connector_requests r JOIN connector_clients c "
                "ON c.client_id = r.client_id WHERE r.request_hash = ? AND r.expires_at >= ?",
                (_hash(request_id), self._now()),
            ).fetchone()

    def decide(self, request_id: str, account_id: int, approve: bool) -> str | None:
        """Answer a pending request (it is used up): the URL to send the person back to, with a
        one-time code or `access_denied`; None if the request is unknown or expired."""
        now = self._now()
        with self.store.connect() as conn, conn:
            row = conn.execute(
                "DELETE FROM connector_requests WHERE request_hash = ? AND expires_at >= ? "
                "RETURNING client_id, redirect_uri, state, code_challenge, scope",
                (_hash(request_id), now),
            ).fetchone()
            if row is None:
                return None
            if not approve:
                return self.error_redirect(row["redirect_uri"], "access_denied", row["state"])
            code = _token(CODE_PREFIX)
            conn.execute(
                "INSERT INTO connector_codes (code_hash, account_id, client_id, redirect_uri, "
                "code_challenge, scope, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _hash(code),
                    account_id,
                    row["client_id"],
                    row["redirect_uri"],
                    row["code_challenge"],
                    row["scope"],
                    now + CODE_SECONDS,
                ),
            )
        params = {"code": code}
        if row["state"]:
            params["state"] = row["state"]
        return _with_query(row["redirect_uri"], params)

    # Tokens ------------------------------------------------------------------------------

    def exchange_code(self, client_id: str, code: str, redirect_uri: str, verifier: str) -> Tokens:
        """A new connection for a live code (used up even when the rest does not match)."""
        if not _VERIFIER.fullmatch(verifier) or len(code) > TOKEN_MAX:
            raise ConnectorError("invalid_grant")
        now = self._now()
        with self.store.connect() as conn:
            with conn:  # used up first, and committed: a failed check below cannot undo it
                row = conn.execute(
                    "DELETE FROM connector_codes WHERE code_hash = ? AND expires_at >= ? "
                    "RETURNING account_id, client_id, redirect_uri, code_challenge, scope",
                    (_hash(code), now),
                ).fetchone()
            if (
                row is None
                or row["client_id"] != client_id
                or row["redirect_uri"] != redirect_uri
                or not hmac.compare_digest(row["code_challenge"], s256(verifier))
            ):
                raise ConnectorError("invalid_grant")
            with conn:
                active = conn.execute(
                    "SELECT c.name FROM accounts a JOIN connector_clients c ON c.client_id = ? "
                    "WHERE a.id = ? AND a.status = 'active'",
                    (client_id, row["account_id"]),
                ).fetchone()
                if active is None:
                    raise ConnectorError("invalid_grant")
                tokens = self._new_tokens(row["scope"])
                conn.execute(
                    "INSERT INTO connector_grants (account_id, client_id, client_name, scope, "
                    "created_at, last_used_at, access_hash, access_expires_at, refresh_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["account_id"],
                        client_id,
                        active["name"],
                        row["scope"],
                        now,
                        now,
                        _hash(tokens.access_token),
                        now + ACCESS_SECONDS,
                        _hash(tokens.refresh_token),
                    ),
                )
        return tokens

    def refresh(self, client_id: str, refresh_token: str) -> Tokens:
        """A new pair for a live connection's current refresh token (the old pair stops)."""
        if not refresh_token.startswith(REFRESH_PREFIX) or len(refresh_token) > TOKEN_MAX:
            raise ConnectorError("invalid_grant")
        now = self._now()
        with self.store.connect() as conn, conn:
            row = conn.execute(
                "SELECT g.id, g.scope FROM connector_grants g JOIN accounts a "
                "ON a.id = g.account_id WHERE g.refresh_hash = ? AND g.client_id = ? "
                "AND a.status = 'active' AND g.last_used_at >= ?",
                (_hash(refresh_token), client_id, now - IDLE_SECONDS),
            ).fetchone()
            if row is None:
                raise ConnectorError("invalid_grant")
            tokens = self._new_tokens(row["scope"])
            # Only if the token is still the current one: of two refreshes racing with the same
            # token, one wins and the other gets `invalid_grant`.
            changed = conn.execute(
                "UPDATE connector_grants SET access_hash = ?, access_expires_at = ?, "
                "refresh_hash = ?, last_used_at = ? WHERE id = ? AND refresh_hash = ?",
                (
                    _hash(tokens.access_token),
                    now + ACCESS_SECONDS,
                    _hash(tokens.refresh_token),
                    now,
                    row["id"],
                    _hash(refresh_token),
                ),
            ).rowcount
            if changed != 1:
                raise ConnectorError("invalid_grant")
        return tokens

    def _new_tokens(self, scope: str) -> Tokens:
        return Tokens(_token(ACCESS_PREFIX), _token(REFRESH_PREFIX), ACCESS_SECONDS, scope)

    def caller(self, access_token: str) -> Caller | None:
        """The active account and connection of a live access token (its use is recorded)."""
        if not access_token.startswith(ACCESS_PREFIX) or len(access_token) > TOKEN_MAX:
            return None
        now = self._now()
        with self.store.connect() as conn, conn:
            row = conn.execute(
                f"SELECT {_ACCOUNT}, g.id AS grant_id, g.client_name, g.last_used_at "
                "FROM connector_grants g "
                "JOIN accounts a ON a.id = g.account_id WHERE g.access_hash = ? "
                "AND g.access_expires_at >= ? AND a.status = 'active' AND g.last_used_at >= ?",
                (_hash(access_token), now, now - IDLE_SECONDS),
            ).fetchone()
            if row is None:
                return None
            if now - int(row["last_used_at"]) >= TOUCH_SECONDS:
                conn.execute(
                    "UPDATE connector_grants SET last_used_at = ? WHERE id = ?",
                    (now, row["grant_id"]),
                )
        account = Account(row["id"], row["email"], row["created_at"], row["status"], row["folder"])
        return Caller(account, int(row["grant_id"]), row["client_name"])

    # Settings ----------------------------------------------------------------------------

    def connections(self, account_id: int) -> list[Grant]:
        """The account's live connections, the most recently used first."""
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT id, client_name, created_at, last_used_at FROM connector_grants "
                "WHERE account_id = ? AND last_used_at >= ? ORDER BY last_used_at DESC, id DESC",
                (account_id, self._now() - IDLE_SECONDS),
            ).fetchall()
        return [Grant(r["id"], r["client_name"], r["created_at"], r["last_used_at"]) for r in rows]

    def revoke(self, account_id: int, grant_id: int) -> bool:
        """End one of the account's connections at once; whether it existed."""
        with self.store.connect() as conn, conn:
            gone = conn.execute(
                "DELETE FROM connector_grants WHERE id = ? AND account_id = ?",
                (grant_id, account_id),
            ).rowcount
        return gone > 0

    def prune(self) -> None:
        """Drop expired requests and codes, idle connections and clients nobody connected with."""
        now = self._now()
        with self.store.connect() as conn, conn:
            conn.execute("DELETE FROM connector_requests WHERE expires_at < ?", (now,))
            conn.execute("DELETE FROM connector_codes WHERE expires_at < ?", (now,))
            conn.execute(
                "DELETE FROM connector_grants WHERE last_used_at < ?", (now - IDLE_SECONDS,)
            )
            conn.execute(
                "DELETE FROM connector_clients WHERE created_at < ? AND client_id NOT IN "
                "(SELECT client_id FROM connector_grants) AND client_id NOT IN "
                "(SELECT client_id FROM connector_codes) AND client_id NOT IN "
                "(SELECT client_id FROM connector_requests)",
                (now - CLIENT_UNUSED_SECONDS,),
            )
