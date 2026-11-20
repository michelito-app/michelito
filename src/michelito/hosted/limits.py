"""In-memory rate limits for sign-in (a single process; nothing is written to disk).

- `Window(limit, seconds)` allows `limit` events per key within any `seconds` window. A request
  counts in several buckets at once (`Keys`): an IP is its `demo.network.quota_keys` (an IPv4
  address; an IPv6 /64, plus its /56 and /48 with a wider limit), so rotating IPv6 addresses
  inside one allocation does not multiply the quota. An event is counted only when **every**
  bucket has room.
- `Spread` blocks a key only after events from several distinct sources.

The keys are opaque: the per-email ones are a keyed hash of the email, the per-IP ones the
quota keys (never stored).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

# (key, times the base limit): what one request counts against.
Keys = Sequence[tuple[str, int]]


class Window:
    """At most `limit` (× the key's factor) events per key in the last `seconds`."""

    def __init__(self, limit: int, seconds: float, clock: Callable[[], float] = time.time):
        self.limit = limit
        self.seconds = seconds
        self.clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def can(self, keys: Keys) -> bool:
        """Whether every bucket has room (nothing is counted)."""
        now = self.clock()
        with self._lock:
            return all(len(self._live(k, now)) < self.limit * f for k, f in keys)

    def take(self, keys: Keys) -> bool:
        """Count one event in every bucket; False (and nothing counted) if any is full."""
        now = self.clock()
        with self._lock:
            buckets = [(self._live(key, now), factor) for key, factor in keys]
            if any(len(events) >= self.limit * factor for events, factor in buckets):
                return False
            for events, _ in buckets:
                events.append(now)
            if len(self._events) > 10_000:
                self._prune(now)
            return True

    def _live(self, key: str, now: float) -> deque[float]:
        events = self._events.setdefault(key, deque())
        while events and events[0] <= now - self.seconds:
            events.popleft()
        return events

    def _prune(self, now: float) -> None:
        self._events = {k: v for k, v in self._events.items() if v and v[-1] > now - self.seconds}


class Spread:
    """Per key, `limit` events in the last `seconds` **from at least `sources` distinct
    buckets** before it is blocked: one source alone can never block it."""

    def __init__(
        self, limit: int, sources: int, seconds: float, clock: Callable[[], float] = time.time
    ) -> None:
        self.limit = limit
        self.sources = sources
        self.seconds = seconds
        self.clock = clock
        self._events: dict[str, deque[tuple[float, str]]] = {}
        self._lock = threading.Lock()

    def add(self, key: str, bucket: str) -> None:
        now = self.clock()
        with self._lock:
            self._live(key, now).append((now, bucket))
            if len(self._events) > 10_000:
                self._events = {
                    k: v for k, v in self._events.items() if v and v[-1][0] > now - self.seconds
                }

    def blocked(self, key: str) -> bool:
        with self._lock:
            events = self._live(key, self.clock())
            buckets = {bucket for _, bucket in events}
            return len(events) >= self.limit and len(buckets) >= self.sources

    def _live(self, key: str, now: float) -> deque[tuple[float, str]]:
        events = self._events.setdefault(key, deque())
        while events and events[0][0] <= now - self.seconds:
            events.popleft()
        return events


@dataclass(frozen=True)
class Caps:
    """The sign-in limits (see `login.md` and `hosted.guard`).

    Visible (429 for every email alike), per `window`: `codes_per_ip` code requests per network,
    `codes_per_email` per email from every network (anonymous requests only) and
    `verifications_per_ip` checks per network; per hour, an email is blocked for checks after
    `checks_per_email_hour` checks from at least `check_sources_per_email` distinct networks
    (anonymous requests only).

    Silent (same answer, the email just does not go out), per day: `emails_per_ip_day` per
    network, `emails_per_email_ceiling` per email for anonymous requests and
    `emails_per_email_absolute` per email for everyone; and no new email while the newest code
    of that email is younger than `resend_after`.

    Trusted requests (a session of that account, or a known device of it) skip the anonymous
    per-email limits, never the absolute ceiling nor the 5 attempts per code."""

    codes_per_ip: int = 10
    codes_per_email: int = 3
    verifications_per_ip: int = 30
    checks_per_email_hour: int = 20
    check_sources_per_email: int = 5
    window: float = 15 * 60.0
    emails_per_ip_day: int = 20
    emails_per_email_ceiling: int = 15
    emails_per_email_absolute: int = 30
    resend_after: int = 60
