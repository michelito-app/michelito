"""The Resend adapter: `POST /emails` on Resend's HTTP API with the standard library.

- The API key comes from the environment (`RESEND_API_KEY`) or a file (`RESEND_API_KEY_FILE`, a
  Docker secret); it is never logged, printed or put in an error message (`__repr__` hides it).
- Emails go out as **plain text only**: there is no HTML, so no open-tracking pixel can be added
  and no link can be rewritten for click tracking. The sending domain must also have open and
  click tracking turned off in Resend (see README, "Hosted mode").
- A 429 with a daily or monthly quota error is `MailCapReached` (the free plan's hard cap); any
  other failure is `MailError` with only the HTTP status or the error's name.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from michelito.hosted.mailer import Email, MailCapReached, MailError

API = "https://api.resend.com"
KEY_ENV = "RESEND_API_KEY"
KEY_FILE_ENV = "RESEND_API_KEY_FILE"
_CAP_ERRORS = frozenset({"daily_quota_exceeded", "monthly_quota_exceeded"})


def key_from_environment() -> str | None:
    """The API key from `RESEND_API_KEY_FILE` (preferred) or `RESEND_API_KEY`."""
    path = os.environ.get(KEY_FILE_ENV, "").strip()
    if path:
        return Path(path).read_text(encoding="utf-8").strip() or None
    return os.environ.get(KEY_ENV, "").strip() or None


class ResendMailer:
    def __init__(self, api_key: str, sender: str, base_url: str = API, timeout: float = 10.0):
        if not api_key:
            raise ValueError("missing Resend API key")
        self._key = api_key
        self.sender = sender
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"ResendMailer(sender={self.sender!r}, base_url={self.base_url!r})"

    def send(self, email: Email) -> None:
        body = json.dumps(
            {"from": self.sender, "to": [email.to], "subject": email.subject, "text": email.text}
        ).encode()
        request = urllib.request.Request(
            f"{self.base_url}/emails",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "User-Agent": "michelito",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            name = _error_name(exc)
            if exc.code == 429 and name in _CAP_ERRORS:
                raise MailCapReached(name) from None
            raise MailError(f"Resend answered {exc.code} ({name or 'no error name'})") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MailError(f"Resend could not be reached ({type(exc).__name__})") from None


def _error_name(exc: urllib.error.HTTPError) -> str:
    """The `name` field of Resend's error body (e.g. "daily_quota_exceeded"), if readable."""
    try:
        found = json.loads(exc.read() or b"{}").get("name", "")
    except (ValueError, AttributeError, OSError):
        return ""
    return found if isinstance(found, str) and found.replace("_", "").isalnum() else ""
