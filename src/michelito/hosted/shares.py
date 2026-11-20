"""PDFs shared to the installed app (Web Share Target), held **in memory** until claimed.

Android posts the shared files to `/share-target` as a form (multipart), as a top-level
navigation that carries no `X-Michelito` header and may carry no session cookie. So that request
opens no database: the files are parsed in memory (`parse_form`, the standard library's MIME
parser, never a temporary file), kept here under a random token for `ttl` seconds and the
browser is sent to `/import#share=<token>`. The signed-in upload screen then claims them with
`POST /api/uploads/shared` (session and `X-Michelito` required), which turns them into an
ordinary upload job of that account. A token is single use. At most `max_bytes` are held in
total, so the stash cannot grow without bound.

The share is **bound to the browser that made it**: `/share-target` also sets a random
`HttpOnly`, `SameSite=Lax` cookie (`__Host-share` over HTTPS) whose hash is stored with the token,
and claiming needs both. So a token someone else made (by posting their own PDFs and luring the
victim to `/import#share=…`) cannot be claimed from the victim's browser.

That cookie alone does not stop a cross-site form from posting to `/share-target` *in the
victim's own browser* (the cookie would be set there too), so the route also checks the fetch
metadata (`allowed_origin`): an OS share arrives as a browser-initiated navigation
(`Sec-Fetch-Site: none`; Chrome on Android also sends no `Origin`, or `null`), never as
`cross-site` or `same-site`. And the upload screen never claims a share by itself: it shows the
names and sizes (`peek`) and waits for an explicit "Import" or "Discard".
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser

FIELD = "statements"
COOKIE_VALUE = re.compile(r"[A-Za-z0-9_-]{32}")


@dataclass(frozen=True)
class Shared:
    created: float
    files: tuple[tuple[str, bytes], ...]
    browser: str  # sha256 of the browser cookie set with it
    source: str = ""  # the network that shared it (its widest quota key)

    @property
    def size(self) -> int:
        return sum(len(data) for _, data in self.files)


def allowed_origin(fetch_site: str | None, origin: str | None, host: str) -> bool:
    """Whether a share-target POST may come from where it says it comes from.

    With `Sec-Fetch-Site` (every current browser, Chrome on Android included): only `none` (the
    OS share sheet, a browser-initiated navigation) and `same-origin`. Without it, only our own
    `Origin` (its host equal to the request's `Host`): a request with neither header is refused,
    since a browser that can install the app always sends fetch metadata."""
    if fetch_site is not None:
        return fetch_site.strip().lower() in ("none", "same-origin")
    if origin is None or origin.strip() in ("", "null"):
        return False
    return origin.split("://", 1)[-1].rstrip("/").lower() == host.lower()


def parse_form(content_type: str, body: bytes, max_files: int) -> tuple[tuple[str, bytes], ...]:
    """The files of a `multipart/form-data` body (any field name), in memory."""
    if not content_type.lower().startswith("multipart/form-data"):
        return ()
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1")
    message = BytesParser(policy=policy.default).parsebytes(head + body)
    if not message.is_multipart():
        return ()
    found: list[tuple[str, bytes]] = []
    for part in message.iter_parts():
        name = part.get_filename()
        payload = part.get_payload(decode=True)
        if name and isinstance(payload, bytes) and payload:
            found.append((name, payload))
        if len(found) >= max_files:
            break
    return tuple(found)


class Shares:
    def __init__(
        self,
        ttl: float = 10 * 60,
        max_bytes: int = 64 * 1024 * 1024,
        per_source: int = 16 * 1024 * 1024,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ttl = ttl
        self.max_bytes = max_bytes
        self.per_source = per_source
        self.clock = clock
        self._items: dict[str, Shared] = {}
        self._lock = threading.Lock()

    def put(
        self, files: tuple[tuple[str, bytes], ...], source: str, browser: str | None = None
    ) -> tuple[str, str] | None:
        """`(token, browser cookie)` for these files; None when the stash is full, in total or
        for that network. A browser that already has a share cookie keeps it, so several
        pending shares of the same browser all stay claimable."""
        if not browser or not COOKIE_VALUE.fullmatch(browser):
            browser = secrets.token_urlsafe(24)
        shared = Shared(self.clock(), files, _digest(browser), source)
        with self._lock:
            self._prune()
            if sum(s.size for s in self._items.values()) + shared.size > self.max_bytes:
                return None
            mine = sum(s.size for s in self._items.values() if s.source == source)
            if mine + shared.size > self.per_source:
                return None
            token = secrets.token_urlsafe(24)
            self._items[token] = shared
        return token, browser

    def peek(self, token: str, browser: str | None) -> tuple[tuple[str, int], ...] | None:
        """The names and sizes, for the browser that shared them; nothing is used up."""
        with self._lock:
            self._prune()
            shared = self._items.get(token)
        if shared is None or not _same_browser(shared, browser):
            return None
        return tuple((name, len(data)) for name, data in shared.files)

    def take(self, token: str, browser: str | None) -> tuple[tuple[str, bytes], ...] | None:
        """The files, once, and only for the browser that shared them (the token stops working
        either way: a wrong browser cannot keep guessing)."""
        with self._lock:
            self._prune()
            shared = self._items.pop(token, None)
        if shared is None or not _same_browser(shared, browser):
            return None
        return shared.files

    def prune(self) -> None:
        with self._lock:
            self._prune()

    def _prune(self) -> None:
        cutoff = self.clock() - self.ttl
        self._items = {k: v for k, v in self._items.items() if v.created > cutoff}


def _same_browser(shared: Shared, browser: str | None) -> bool:
    return bool(browser) and hmac.compare_digest(shared.browser, _digest(browser or ""))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
