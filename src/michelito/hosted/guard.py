"""Every sign-in limit in one place (`Guard`), so `auth` only asks "may this happen?".

- Asking for a code (visible, 429 for every email alike): per network (an IPv4, or an IPv6 /64
  that also counts in its /56 and /48, see `limits`); and 3 per email per 15 minutes from every
  network, unless the request is **trusted** (a session of that account or a known device).
- Sending (silent: same answer, the email just does not go out): per network; an anonymous
  per-email ceiling unless trusted; and an **absolute** per-email ceiling that binds everyone,
  trusted included (above the anonymous one, so strangers never use all of it).
- Checking a code (visible): per network; and per email once checks in the last hour came from
  several distinct networks (`Spread`), so no single network's allowance reaches it. A trusted
  request skips that per-email block; nothing skips the 5 attempts per code (`store`).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from michelito.hosted.limits import Caps, Keys, Spread, Window

DAY = 24 * 3600
HOUR = 3600


def widest(source: Keys) -> str:
    """The source's widest bucket (an IPv4, or an IPv6 /48)."""
    return source[-1][0] if source else ""


class Guard:
    def __init__(self, caps: Caps, clock: Callable[[], float] = time.time) -> None:
        self.caps = caps
        self._ip_codes = Window(caps.codes_per_ip, caps.window, clock)
        self._ip_checks = Window(caps.verifications_per_ip, caps.window, clock)
        self._email_codes = Window(caps.codes_per_email, caps.window, clock)
        self._ip_emails = Window(caps.emails_per_ip_day, DAY, clock)
        self._email_emails = Window(caps.emails_per_email_ceiling, DAY, clock)
        self._email_emails_all = Window(caps.emails_per_email_absolute, DAY, clock)
        self._email_checks = Spread(
            caps.checks_per_email_hour, caps.check_sources_per_email, HOUR, clock
        )

    def code_request(self, email_key: str, source: Keys, trusted: bool) -> bool:
        """Visible: may this source ask for a code for this email now?"""
        if not self._ip_codes.take(source):
            return False
        return trusted or self._email_codes.take([(email_key, 1)])

    def may_send(self, email_key: str, source: Keys, trusted: bool) -> bool:
        """Silent: may an email actually go out (counting it if so)?"""
        whole = [(email_key, 1)]
        if not self._email_emails_all.can(whole) or not self._ip_emails.can(source):
            return False
        if not trusted and not self._email_emails.take(whole):
            return False
        self._ip_emails.take(source)
        return self._email_emails_all.take(whole)

    def check(self, email_key: str, source: Keys, trusted: bool = False) -> bool:
        """Visible: may this source check a code for this email now? Counts the check against
        the email (before any comparison) unless trusted."""
        if not self._ip_checks.take(source):
            return False
        if trusted:
            return True
        if self._email_checks.blocked(email_key):
            return False
        self._email_checks.add(email_key, widest(source))
        return True
