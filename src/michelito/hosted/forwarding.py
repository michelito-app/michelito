"""Email forwarding: each account's address and the signed requests of the Email Worker.

- **Address**: `<PREFIX>.<token>@<domain>` (on michelito.app): the token is 160
  random bits in lowercase base32 (32 characters). The accounts database keeps only its
  SHA-256 (`store.forwarding_addresses`), so a copy of it reveals no address; the address
  itself is shown from the account's own encrypted database (`hosted.inbox`). A new token
  replaces the old hash in one statement: the old address stops working at once.
- **Signed requests**: the Cloudflare Email Worker (`deploy/email-worker/`) POSTs every message
  to `/api/inbound-email` with three headers: a Unix timestamp, a random nonce and
  `HMAC-SHA256(secret, "<timestamp>.<nonce>." + body)` in hex. `verify` checks the signature
  (in constant time, before anything else is read), then that the timestamp is within
  `WINDOW` seconds of now; the caller then records the nonce (`store.take_nonce`), so a request
  replayed within the window is refused too.
- **The shared secret** is a file (a Docker secret, `MICHELITO_INBOUND_SECRET_FILE`), never
  logged: its text (at least 32 characters, e.g. `openssl rand -hex 32`) is the HMAC key on
  both sides. Without it the endpoint answers 404 (forwarding is off).

Nothing here logs or returns a token, a secret or a signature.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

DOMAIN = "michelito.app"
PREFIX = "estados"  # spanish-data: the address's fixed part, as the owner chose it
TOKEN_BYTES = 20  # 160 bits
TOKEN = re.compile(r"[a-z2-7]{32}")
WINDOW = 300  # seconds a signed request is valid, either side of now
SECRET_ENV = "MICHELITO_INBOUND_SECRET_FILE"
SECRET_MIN = 32
TIMESTAMP_HEADER = "X-Michelito-Timestamp"
NONCE_HEADER = "X-Michelito-Nonce"
SIGNATURE_HEADER = "X-Michelito-Signature"
PREAUTH_HEADER = "X-Michelito-Preauth"
NONCE = re.compile(r"[A-Za-z0-9_-]{16,64}")
SIGNATURE = re.compile(r"[0-9a-f]{64}")


class SecretError(Exception):
    """The inbound secret file cannot be used (the message names only the path)."""


def new_token() -> str:
    return base64.b32encode(secrets.token_bytes(TOKEN_BYTES)).decode("ascii").lower()


def token_hash(token: str) -> str:
    return hashlib.sha256(f"forwarding\0{token}".encode()).hexdigest()


def address(token: str, domain: str = DOMAIN) -> str:
    return f"{PREFIX}.{token}@{domain}"


def token_of(recipient: str, domain: str = DOMAIN) -> str | None:
    """The token of an envelope recipient `<PREFIX>.<token>@<domain>` (case-insensitive), or None
    for anything else."""
    text = recipient.strip().lower()
    local, at, host = text.rpartition("@")
    if not at or host != domain.lower():
        return None
    prefix, dot, token = local.partition(".")
    if not dot or prefix != PREFIX or not TOKEN.fullmatch(token):
        return None
    return token


def load_secret(path: Path | None) -> bytes | None:
    """The inbound secret from `path` (or `MICHELITO_INBOUND_SECRET_FILE`); None when neither
    is set. `SecretError` if it is set but missing, unreadable or too short."""
    if path is None:
        named = os.environ.get(SECRET_ENV, "").strip()
        path = Path(named) if named else None
    if path is None:
        return None
    try:
        text = path.read_bytes().strip()
    except OSError:
        raise SecretError(f"{path}: the inbound secret cannot be read") from None
    if len(text) < SECRET_MIN:
        raise SecretError(f"{path}: the inbound secret must have at least {SECRET_MIN} characters")
    return text


def sign(secret: bytes, timestamp: str, nonce: str, body: bytes) -> str:
    message = f"{timestamp}.{nonce}.".encode("ascii") + body
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def preauth(secret: bytes, timestamp: str, nonce: str, length: int) -> str:
    """The pre-authentication tag the Worker sends with the headers: an HMAC over the
    timestamp, the nonce and the body's length, so a request is known to come from the Worker
    before any of its body is read (the full-body HMAC stays the real authentication)."""
    message = f"pre\0{timestamp}\0{nonce}\0{length}".encode("ascii")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def precheck(
    secret: bytes,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    tag: str | None,
    length: int | None,
    now: float,
) -> int | None:
    """Before the body is read: the timestamp (as a number) if every header is well formed, the
    time is within `WINDOW` and the pre-authentication tag matches the declared length (in
    constant time); None otherwise (refused without reading)."""
    if not timestamp or not nonce or not signature or not tag or length is None:
        return None
    if not (timestamp.isascii() and timestamp.isdigit() and len(timestamp) <= 12):
        return None
    if not NONCE.fullmatch(nonce) or not SIGNATURE.fullmatch(signature):
        return None
    if not SIGNATURE.fullmatch(tag):
        return None
    moment = int(timestamp)
    if abs(now - moment) > WINDOW:
        return None
    if not hmac.compare_digest(preauth(secret, timestamp, nonce, length), tag):
        return None
    return moment


class Mac:
    """The request's HMAC, computed while the body streams in (`update` per chunk)."""

    def __init__(self, secret: bytes, timestamp: str, nonce: str) -> None:
        self._mac = hmac.new(secret, f"{timestamp}.{nonce}.".encode("ascii"), hashlib.sha256)

    def update(self, chunk: bytes) -> None:
        self._mac.update(chunk)

    def matches(self, signature: str) -> bool:
        return hmac.compare_digest(self._mac.hexdigest(), signature)


@dataclass(frozen=True)
class Signed:
    """A request whose signature and time checked out; `nonce` still has to be recorded."""

    timestamp: int
    nonce: str = field(repr=False)


def verify(
    secret: bytes,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    body: bytes,
    now: float,
) -> Signed | None:
    """The request if its signature is right and its time within `WINDOW`; None otherwise
    (the caller answers alike whatever failed)."""
    if not timestamp or not nonce or not signature:
        return None
    if not (timestamp.isascii() and timestamp.isdigit() and len(timestamp) <= 12):
        return None
    if not NONCE.fullmatch(nonce) or not SIGNATURE.fullmatch(signature):
        return None
    expected = sign(secret, timestamp, nonce, body)
    if not hmac.compare_digest(expected, signature):
        return None
    moment = int(timestamp)
    if abs(now - moment) > WINDOW:
        return None
    return Signed(moment, nonce)
