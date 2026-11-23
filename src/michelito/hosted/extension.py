"""The browser extension's link to an account (hosted mode; routes in `hosted.extension_routes`).

- **The code.** Settings makes a one-time code (`issue`): 12 characters from an alphabet without
  look-alikes (about 59 bits), shown as three groups, valid for `CODE_SECONDS`. Only its keyed
  hash (HMAC-SHA256 under the server's code-hash secret) is stored, one per account: a new one
  replaces the previous one.
- **The token.** The extension exchanges the code once (`exchange`) for a random 256-bit token
  that can only write item names (`PUT /api/extension/orders`): it is never a session and opens
  no other route. Only its SHA-256 is stored, one per account: linking again replaces it,
  revoking (`revoke`) deletes it, and so do signing out everywhere, the account's deletion or
  suspension (the token of a disabled account finds nothing). Unused for `IDLE_SECONDS` (since
  it was made or last used), it stops working.

The tables are `extension_codes` and `extension_tokens` in the accounts database (`hosted.store`,
migration 9). Times are whole seconds since the epoch.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from michelito.hosted.store import Account, Store

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 12
CODE_GROUP = 4
CODE_SECONDS = 10 * 60
CODE_PATTERN = re.compile(
    rf"[{CODE_ALPHABET}]{{{CODE_GROUP}}}(-[{CODE_ALPHABET}]{{{CODE_GROUP}}}){{2}}"
)
CODE_INPUT_MAX = 40
IDLE_SECONDS = 90 * 24 * 3600  # a token unused this long stops working (link it again)
TOKEN_PREFIX = "mchx_"
TOKEN_BYTES = 32
TOKEN_MAX = 100
_CODE_LABEL = "extension code"
_ACCOUNT = "a.id, a.email, a.created_at, a.status, a.folder"


@dataclass(frozen=True)
class Link:
    linked_at: int
    last_used_at: int | None


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + CODE_GROUP] for i in range(0, CODE_LENGTH, CODE_GROUP))


def normalize_code(text: str) -> str | None:
    """The code as typed or pasted (any case, spaces or dashes), or None if it cannot be one."""
    if len(text) > CODE_INPUT_MAX:
        return None
    found = re.sub(r"[\s-]", "", text).upper()
    if len(found) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in found):
        return None
    return found


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Linker:
    """Codes and tokens over the accounts `store`; `secret` keys the code hashes."""

    def __init__(self, store: Store, secret: bytes, clock: Callable[[], float] = time.time) -> None:
        if len(secret) < 32:
            raise ValueError("the code-hash secret must have at least 32 bytes")
        self.store = store
        self._secret = secret
        self.clock = clock

    def __repr__(self) -> str:
        return "Linker()"

    def _now(self) -> int:
        return int(self.clock())

    def _code_hash(self, normalized: str) -> str:
        message = f"{_CODE_LABEL}\0{normalized}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def issue(self, account_id: int) -> tuple[str, int]:
        """A new one-time code for the account (the previous one stops working) and when it
        expires."""
        code = new_code()
        normalized = normalize_code(code)
        assert normalized is not None
        now = self._now()
        expires_at = now + CODE_SECONDS
        with self.store.connect() as conn, conn:
            conn.execute(
                "INSERT INTO extension_codes (account_id, code_hash, created_at, expires_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET "
                "code_hash = excluded.code_hash, created_at = excluded.created_at, "
                "expires_at = excluded.expires_at",
                (account_id, self._code_hash(normalized), now, expires_at),
            )
        return code, expires_at

    def exchange(self, code: str) -> str | None:
        """The token for a live code of an active account (the code is used up and the
        account's previous token stops working), or None."""
        normalized = normalize_code(code)
        if normalized is None:
            return None
        now = self._now()
        token = new_token()
        with self.store.connect() as conn, conn:
            # Consumed in the statement that finds it: two exchanges of one code at the same
            # time cannot both get it.
            row = conn.execute(
                "DELETE FROM extension_codes WHERE code_hash = ? AND expires_at >= ? "
                "AND account_id IN (SELECT id FROM accounts WHERE status = 'active') "
                "RETURNING account_id",
                (self._code_hash(normalized), now),
            ).fetchone()
            if row is None:
                return None
            account_id = int(row["account_id"])
            conn.execute(
                "INSERT INTO extension_tokens (account_id, token_hash, created_at, last_used_at) "
                "VALUES (?, ?, ?, NULL) ON CONFLICT(account_id) DO UPDATE SET "
                "token_hash = excluded.token_hash, created_at = excluded.created_at, "
                "last_used_at = NULL",
                (account_id, token_hash(token), now),
            )
        return token

    def account_of(self, token: str) -> Account | None:
        """The active account of this token (its last use is recorded), or None."""
        if not token.startswith(TOKEN_PREFIX) or len(token) > TOKEN_MAX:
            return None
        now = self._now()
        with self.store.connect() as conn, conn:
            row = conn.execute(
                f"SELECT {_ACCOUNT} FROM extension_tokens t JOIN accounts a "
                "ON a.id = t.account_id WHERE t.token_hash = ? AND a.status = 'active' "
                "AND COALESCE(t.last_used_at, t.created_at) >= ?",
                (token_hash(token), now - IDLE_SECONDS),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE extension_tokens SET last_used_at = ? WHERE account_id = ?",
                (now, row["id"]),
            )
        return Account(row["id"], row["email"], row["created_at"], row["status"], row["folder"])

    def status(self, account_id: int) -> Link | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT created_at, last_used_at FROM extension_tokens WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        if row is None:
            return None
        return Link(int(row["created_at"]), row["last_used_at"])

    def revoke(self, account_id: int) -> bool:
        """Delete the account's token and pending code; whether there was a token."""
        with self.store.connect() as conn, conn:
            conn.execute("DELETE FROM extension_codes WHERE account_id = ?", (account_id,))
            gone = conn.execute(
                "DELETE FROM extension_tokens WHERE account_id = ?", (account_id,)
            ).rowcount
        return gone > 0
