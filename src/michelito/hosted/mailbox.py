"""Gmail connected in hosted mode: read-only access to the person's own mailbox, used only to
read the merchant receipts of `michelito.receipts` (see `.superpowers/sdd/email-links.md`).

- **The client** (`GoogleClient`) is the OAuth web client the owner created in Google Cloud: a
  Docker secret file in Google's own JSON format (`MICHELITO_GOOGLE_CLIENT_FILE`). Without it the
  feature is off: Settings does not offer it and nothing is ever asked of Google.
- **Connecting** asks for one scope, `gmail.readonly`, with PKCE and a single-use `state` bound
  to the session's account (`hosted.mailbox_routes`). What is kept is the refresh token only,
  AES-256-GCM sealed (`inbox_store.Sealer`) inside the account's encrypted database, and the
  mailbox's address to show it; never an access token, never a message.
- **Reading** lists only the messages of the receipt senders (`query`), of the last 12 months,
  and hands them to the same pipeline as the local sync (`extract.extract_receipts`): each one
  is read in memory and only its fields are stored. Receipts read this way come from the
  person's own mailbox, so a single exact charge is linked on its own (`receipt_match`).
- **Disconnecting** (and deleting the account) revokes the token at Google and deletes it. A
  token Google no longer honours (`invalid_grant`: revoked by the person, or expired) leaves
  the connection marked `reconnect`; any other refusal is a `failed` read, tried again later.
  Each read takes at most `READ_LIMIT` new messages; the next ones take the rest.

Everything that talks to Google goes through `Google`, so tests use a fake one.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlencode, urlsplit

from michelito import config, extract, receipts
from michelito.extract import ExtractStats, MailClient
from michelito.gmail import SCOPES, MailMessage
from michelito.hosted.inbox_store import Sealer, SealError

log = logging.getLogger(__name__)

CLIENT_FILE_ENV = "MICHELITO_GOOGLE_CLIENT_FILE"
CALLBACK_PATH = "/api/mailbox/google/callback"
SCOPE = SCOPES[0]
SOURCE = "gmail"  # the receipts' source: not `forwarding`, so they may be linked on their own
HISTORY = "newer_than:12m"
AUTH_HOSTS = ("accounts.google.com",)
TOKEN_HOSTS = ("oauth2.googleapis.com", "www.googleapis.com", "accounts.google.com")
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
ADDRESS_MAX = 320
CLIENT_FILE_MAX = 16 * 1024
_TABLE = "mailbox_google"
_SEAL = "mailbox"

Problem = Literal["reconnect", "failed"]


class ClientError(ValueError):
    """The client file cannot be used: the message says why (never its content)."""


@dataclass(frozen=True)
class GoogleClient:
    client_id: str
    client_secret: str = field(repr=False)
    auth_uri: str
    token_uri: str


def _https(address: str, hosts: tuple[str, ...]) -> bool:
    """https on one of `hosts`, on the default port (an explicit one only if it is 443)."""
    parts = urlsplit(address)
    try:
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and (parts.hostname or "") in hosts and port in (None, 443)


def parse_client(text: str) -> GoogleClient:
    """Google's client JSON (`{"web": {...}}`, as Google Cloud downloads it)."""
    try:
        found = json.loads(text)
    except (ValueError, RecursionError):
        raise ClientError("the Google client file is not JSON") from None
    web = found.get("web") if isinstance(found, dict) else None
    if not isinstance(web, dict):
        raise ClientError("the Google client file is not a web application client")
    values = {key: web.get(key) for key in ("client_id", "client_secret", "auth_uri", "token_uri")}
    if not all(isinstance(value, str) and value.strip() for value in values.values()):
        raise ClientError("the Google client file lacks its id, secret or addresses")
    client = GoogleClient(**{key: str(value).strip() for key, value in values.items()})
    if not _https(client.auth_uri, AUTH_HOSTS) or not _https(client.token_uri, TOKEN_HOSTS):
        raise ClientError("the Google client file names addresses that are not Google's")
    return client


def load_client(path: Path | None = None) -> GoogleClient | None:
    """The client named by `path` or `MICHELITO_GOOGLE_CLIENT_FILE`; None when neither is set
    (the feature is off). A file that is set but unusable is an error, said at start-up."""
    named = path or (
        Path(found) if (found := os.environ.get(CLIENT_FILE_ENV, "").strip()) else None
    )
    if named is None:
        return None
    try:
        if named.stat().st_size > CLIENT_FILE_MAX:
            raise ClientError("the Google client file is too large")
        text = named.read_text(encoding="utf-8")
    except OSError:
        raise ClientError("the Google client file cannot be read") from None
    except UnicodeDecodeError:
        raise ClientError("the Google client file is not UTF-8 text") from None
    try:
        return parse_client(text)
    except ClientError:
        raise
    except (ValueError, RecursionError):  # anything else the parsing may raise
        raise ClientError("the Google client file is not a web application client") from None


def query() -> str:
    """The Gmail search: only the receipt senders, of the last 12 months."""
    senders = " ".join(f"from:{sender}" for sender in sorted(receipts.SENDERS))
    return f"{{{senders}}} {HISTORY}"


SOURCE_CONFIG = config.Source(SOURCE, query(), (), receipts=True)


# PKCE (RFC 7636) and the single-use state.


def new_verifier() -> str:
    return secrets.token_urlsafe(64)


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_state() -> str:
    return secrets.token_urlsafe(32)


def state_key(state: str) -> str:
    """What is kept of a state: its hash (the state itself travels through the browser)."""
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def authorization_url(client: GoogleClient, redirect_uri: str, state: str, verifier: str) -> str:
    params = {
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",  # a refresh token, to read while the person is away
        "prompt": "consent",  # a refresh token every time (a reconnection needs a new one)
        "include_granted_scopes": "false",
        "state": state,
        "code_challenge": challenge(verifier),
        "code_challenge_method": "S256",
    }
    return f"{client.auth_uri}?{urlencode(params)}"


# What Google answers.


class Revoked(RuntimeError):
    """Google no longer honours the token (revoked by the person, or expired)."""


@dataclass(frozen=True)
class Granted:
    refresh_token: str = field(repr=False)
    scopes: frozenset[str]


class Google(Protocol):
    def exchange(
        self, client: GoogleClient, redirect_uri: str, code: str, verifier: str
    ) -> Granted: ...

    def revoke(self, token: str) -> bool: ...

    def mailbox(self, client: GoogleClient, refresh_token: str) -> Mailbox: ...


class Mailbox(MailClient, Protocol):
    def address(self) -> str: ...


TIMEOUT = 15.0


class RealGoogle:
    """Google's OAuth endpoints and the Gmail API (`requests` and `google-api-python-client`)."""

    def exchange(
        self, client: GoogleClient, redirect_uri: str, code: str, verifier: str
    ) -> Granted:
        import requests  # noqa: PLC0415 (only when someone connects)

        response = requests.post(
            client.token_uri,
            data={
                "code": code,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=TIMEOUT,
            allow_redirects=False,
        )
        if response.status_code != 200:  # noqa: PLR2004
            raise Revoked("Google refused the authorization code")
        body = response.json()
        token = body.get("refresh_token")
        if not isinstance(token, str) or not token:
            raise Revoked("Google gave no refresh token")
        return Granted(token, frozenset(str(body.get("scope", "")).split()))

    def revoke(self, token: str) -> bool:
        import requests  # noqa: PLC0415

        try:
            response = requests.post(
                REVOKE_URL, data={"token": token}, timeout=TIMEOUT, allow_redirects=False
            )
        except requests.RequestException:
            return False
        return response.status_code == 200  # noqa: PLR2004

    def mailbox(self, client: GoogleClient, refresh_token: str) -> Mailbox:
        from google.auth.exceptions import RefreshError  # noqa: PLC0415
        from google.auth.transport.requests import Request  # noqa: PLC0415
        from google.oauth2.credentials import Credentials  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415

        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client.client_id,
            client_secret=client.client_secret,
            token_uri=client.token_uri,
            scopes=[SCOPE],
        )
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            if invalid_grant(exc):  # revoked by the person, or expired: they must reconnect
                raise Revoked("Google refused to refresh the token") from None
            raise  # anything else may pass: the read is only `failed`
        return _GmailMailbox(build("gmail", "v1", credentials=credentials, cache_discovery=False))


class _GmailMailbox:
    def __init__(self, service: object) -> None:
        from michelito.gmail import GmailClient  # noqa: PLC0415

        self._service = service
        self._client = GmailClient(service)

    def list_message_ids(self, query: str) -> Iterator[str]:
        return self._client.list_message_ids(query)

    def get_message(self, message_id: str) -> MailMessage:
        return self._client.get_message(message_id)

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        return self._client.get_attachment(message_id, attachment_id)

    def address(self) -> str:
        users = self._service.users()  # type: ignore[attr-defined]
        found = users.getProfile(userId="me").execute(num_retries=2)
        return str(found.get("emailAddress", ""))[:ADDRESS_MAX]


# What is stored, inside the account's encrypted database (hosted mode only).

SCHEMA = f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    uid TEXT NOT NULL,
    sealed BLOB NOT NULL,
    address TEXT CHECK (address IS NULL OR length(address) <= {ADDRESS_MAX}),
    connected_at TEXT NOT NULL,
    synced_at TEXT,
    problem TEXT CHECK (problem IS NULL OR problem IN ('reconnect', 'failed'))
)"""


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA secure_delete = ON")  # a deleted token is zeroed, not just freed
    conn.execute(SCHEMA)


def _exists(conn: sqlite3.Connection) -> bool:
    """Whether the table was ever made (reading never creates it: an account that never
    connected Gmail keeps its database untouched)."""
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (_TABLE,)
    ).fetchone()
    return found is not None


@dataclass(frozen=True)
class Connection:
    address: str | None
    connected_at: str
    synced_at: str | None
    problem: Problem | None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def status(conn: sqlite3.Connection) -> Connection | None:
    if not _exists(conn):
        return None
    row = conn.execute(
        f"SELECT address, connected_at, synced_at, problem FROM {_TABLE} WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return Connection(row[0], str(row[1]), row[2], row[3])


def store(conn: sqlite3.Connection, sealer: Sealer, token: str, address: str | None) -> None:
    """Keep the refresh token, sealed (replaces a previous connection). In the caller's
    transaction."""
    ensure(conn)
    uid = secrets.token_hex(16)
    sealed = sealer.seal(_SEAL, uid, token.encode("utf-8"))
    conn.execute(
        f"INSERT INTO {_TABLE} (id, uid, sealed, address, connected_at) VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET uid = excluded.uid, sealed = excluded.sealed, "
        "address = excluded.address, connected_at = excluded.connected_at, synced_at = NULL, "
        "problem = NULL",
        (uid, sealed, None if address is None else address[:ADDRESS_MAX], _now()),
    )


@dataclass(frozen=True)
class _Stored:
    uid: str  # which connection: a reconnection gets a new one
    token: str = field(repr=False)


def _stored(conn: sqlite3.Connection, sealer: Sealer) -> _Stored | None:
    if not _exists(conn):
        return None
    row = conn.execute(f"SELECT uid, sealed FROM {_TABLE} WHERE id = 1").fetchone()
    if row is None:
        return None
    uid = str(row[0])
    return _Stored(uid, sealer.open(_SEAL, uid, bytes(row[1])).decode("utf-8"))


def token(conn: sqlite3.Connection, sealer: Sealer) -> str | None:
    """The refresh token; `SealError` if it does not open (another key, or damaged)."""
    found = _stored(conn, sealer)
    return None if found is None else found.token


def forget(conn: sqlite3.Connection) -> None:
    """Delete the connection (`secure_delete`: the database zeroes the deleted row). The
    receipts already read stay, like any other data of the account."""
    if not _exists(conn):
        return
    ensure(conn)
    conn.execute(f"DELETE FROM {_TABLE}")


def mark(
    conn: sqlite3.Connection, problem: Problem | None, synced: bool, uid: str | None = None
) -> None:
    """Record how a read went; with `uid`, only if that is still the connection (a read that
    outlived a disconnection or a reconnection marks nothing)."""
    conn.execute(
        f"UPDATE {_TABLE} SET problem = ?, synced_at = CASE WHEN ? THEN ? ELSE synced_at END "
        "WHERE id = 1 AND (? IS NULL OR uid = ?)",
        (problem, synced, _now(), uid, uid),
    )


def invalid_grant(error: BaseException) -> bool:
    """Whether Google's refusal is `invalid_grant` (the only one that means "reconnect")."""
    return any("invalid_grant" in str(arg) for arg in error.args)


READ_LIMIT = 200  # new messages per read; the rest come in the next ones


class _Bounded:
    """The mailbox, listing no more once `limit` new messages were fetched or `stop()` says so
    (a disconnection). The ones not reached are read next time: what was read is skipped."""

    def __init__(self, inner: MailClient, limit: int, stop: Callable[[], bool]) -> None:
        self._inner = inner
        self._left = limit
        self._stop = stop

    def list_message_ids(self, query: str) -> Iterator[str]:
        for message_id in self._inner.list_message_ids(query):
            if self._left <= 0 or self._stop():
                return
            yield message_id

    def get_message(self, message_id: str) -> MailMessage:
        self._left -= 1
        return self._inner.get_message(message_id)

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        return self._inner.get_attachment(message_id, attachment_id)


def read_receipts(
    conn: sqlite3.Connection,
    mailbox: MailClient,
    limit: int = READ_LIMIT,
    stop: Callable[[], bool] = lambda: False,
) -> ExtractStats:
    """Read up to `limit` of the receipt senders' messages not read yet (see the module)."""
    return extract.extract_receipts(conn, _Bounded(mailbox, limit, stop), SOURCE_CONFIG)


Outcome = Literal["none", "read", "reconnect", "failed"]


def sync(
    conn: sqlite3.Connection,
    sealer: Sealer,
    client: GoogleClient,
    google: Google,
    limit: int = READ_LIMIT,
    stop: Callable[[], bool] = lambda: False,
) -> Outcome:
    """Read what is new in the connected mailbox and record how it went (never raises for
    Google's or a message's sake; only the error's class name is logged)."""
    try:
        found = _stored(conn, sealer)
    except SealError:
        log.warning("a connected mailbox's token did not open")
        with conn:
            mark(conn, "reconnect", synced=False)
        return "reconnect"
    if found is None:
        return "none"
    try:
        opened = google.mailbox(client, found.token)
        read_receipts(conn, opened, limit, stop)
    except Revoked:
        with conn:
            mark(conn, "reconnect", synced=False, uid=found.uid)
        return "reconnect"
    except Exception as exc:  # noqa: BLE001 - one account's mailbox must not stop anything
        log.warning("reading a connected mailbox failed (%s)", type(exc).__name__)
        if conn.in_transaction:
            conn.rollback()
        with conn:
            mark(conn, "failed", synced=False, uid=found.uid)
        return "failed"
    _fill_address(conn, opened, found.uid)
    with conn:
        mark(conn, None, synced=True, uid=found.uid)
    return "read"


def _fill_address(conn: sqlite3.Connection, opened: Mailbox, uid: str) -> None:
    """The address, if the connection could not read it (best effort: a failure is logged and
    the read still counts)."""
    row = conn.execute(f"SELECT address FROM {_TABLE} WHERE id = 1 AND uid = ?", (uid,)).fetchone()
    if row is None or row[0] is not None:
        return
    try:
        address = opened.address()
    except Exception as exc:  # noqa: BLE001 - the address is only shown in Settings
        log.warning("a connected mailbox's address was not read (%s)", type(exc).__name__)
        return
    if not address:
        return
    with conn:
        conn.execute(
            f"UPDATE {_TABLE} SET address = ? WHERE id = 1 AND uid = ? AND address IS NULL",
            (address[:ADDRESS_MAX], uid),
        )


def gmail_receipts(conn: sqlite3.Connection) -> int:
    """How many merchant emails were read from the connected mailbox."""
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'receipt_emails'"
    ).fetchone()
    if found is None:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) FROM receipt_emails WHERE source = ? AND status = 'read'", (SOURCE,)
    ).fetchone()
    return int(row[0])
