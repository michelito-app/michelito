"""One copy of the database per demo visitor, chosen by the `demo_id` cookie.

- The cookie is random (128 bits, 32 hex letters) and is validated **by its shape** before being
  used in a path: nothing that is not `[0-9a-f]{32}` reaches the file system.
- Each copy is a folder `<copies>/<id>/` with `michelito.db` and `holders.txt`, copied from the
  template. It is created in a temporary folder and published with an atomic `rename`: no request
  sees a half-made copy, and two created at the same time do not overwrite each other.
- The last use is the folder's modification time (touched at most once a minute). Those unused
  for more than `ttl` are deleted at startup and in the background maintenance (`demo.app`):
  first they are renamed, so no new request finds them; an already open connection keeps working
  on the deleted file until it closes.
- Limits: `per_ip` new copies per IP per day (the IP lives **only in memory** and is forgotten
  when the day changes; see `demo.network` for which IP and its keys), `per_minute_new` new
  copies per minute across everyone, `max_live` live copies (when full, the one unused for more
  than `evict_after` is evicted), `min_free` free bytes on disk and `per_minute` cost units per
  minute per copy (`allow_request`: an expensive route costs more).

A single process: the counters and the lock live in memory (see README, "Demo").
"""

from __future__ import annotations

import math
import os
import re
import secrets
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from michelito.demo import generate
from michelito.web.workspace import Workspace

COOKIE = "demo_id"
_ID = re.compile(r"[0-9a-f]{32}")
_TOUCH_EVERY = 60.0
_TRASH = ".trash-"
_WORK = ".new-"


class DemoFull(Exception):
    """Another copy cannot be created now (`reason`: "full", "ip" or "restart")."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Limits:
    per_ip: int = 3
    max_live: int = 200
    per_minute_new: int = 20  # new copies per minute across everyone (a range cannot fill it)
    per_minute: int = 120  # cost units per minute per copy (see `demo.app.COSTS`)
    ttl: float = 24 * 3600.0
    sweep_every: float = 600.0
    evict_after: float = 3600.0  # with the demo full, the oldest is evicted if this has passed
    min_free: int = 200 * 1024 * 1024  # free bytes on disk to create another copy
    restart_cooldown: float = 300.0  # "start over": one every so often per copy
    restarts_per_day: int = 10  # per IP key (for IPv6, wider in /56 and /48)
    restarts_per_minute: int = 20  # across everyone


def valid_id(text: str | None) -> bool:
    return text is not None and _ID.fullmatch(text) is not None


class CopyStore:
    """The demo's copies under `root`, made from the template in `template`."""

    def __init__(
        self,
        root: Path,
        template: Path,
        limits: Limits = Limits(),
        clock: Callable[[], float] = time.time,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.root = root
        self.template = template
        self.limits = limits
        self.clock = clock
        self.today = today
        self._lock = threading.Lock()  # creating, sweeping and swapping the template
        self._rate_lock = threading.Lock()  # each copy's per-minute counters
        self._by_ip: dict[str, int] = {}
        self._recent: deque[float] = deque()  # when the last copies were created
        self._recent_restarts: deque[float] = deque()  # when the last restarts were
        self._restarts_by_ip: dict[str, int] = {}
        self._restarted: dict[str, float] = {}  # id -> when it was born from a restart
        self._ip_day: date | None = None
        self._requests: dict[str, tuple[int, int]] = {}  # id -> (minute, requests)
        self._touched: dict[str, float] = {}
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        self.sweep()

    def workspace(self, copy_id: str | None) -> Workspace | None:
        """The copy of that cookie, if it is valid and exists (marking it as used). It touches
        the disk: from the event loop it is called in a thread."""
        if not valid_id(copy_id):
            return None
        assert copy_id is not None
        folder = self.root / copy_id
        if not folder.is_dir():
            return None
        self._touch(copy_id, folder)
        return Workspace(folder / generate.DATABASE, folder / generate.HOLDERS)

    def create(self, quotas: Sequence[tuple[str, int]]) -> str:
        """A new copy from the template; returns its id. `DemoFull` if it cannot be made.
        `quotas`: the quotas it counts in (`network.quota_keys`; they live only in memory)."""
        with self._lock:
            self._check_ip(quotas)
            self._check_window(self._recent, self.limits.per_minute_new, "full")
            self._check_disk()
            if self.live() >= self.limits.max_live:
                self.sweep_locked()
                if self.live() >= self.limits.max_live and not self._evict_oldest():
                    raise DemoFull("full")
            copy_id = self._copy_template()
            for key, _ in quotas:
                self._by_ip[key] = self._by_ip.get(key, 0) + 1
            self._recent.append(self.clock())
            return copy_id

    def restart(self, old: str, quotas: Sequence[tuple[str, int]]) -> str:
        """ "Start over": replace the copy `old` with a new one from the template.

        It has its own caps, apart from new copies (it does not use their quota): one every
        `restart_cooldown` seconds per copy (the new one inherits the wait), `restarts_per_day`
        per IP key and `restarts_per_minute` across everyone. The minute's budget moves from the
        old id to the new one (the other per-copy caps are carried over by `demo.app`).
        `DemoFull("restart")` if it cannot be done."""
        with self._lock:
            if not valid_id(old) or not (self.root / old).is_dir():
                raise DemoFull("restart")
            now = self.clock()
            if now - self._restarted.get(old, -math.inf) < self.limits.restart_cooldown:
                raise DemoFull("restart")
            self._roll_day()
            for key, factor in quotas:
                if self._restarts_by_ip.get(key, 0) >= self.limits.restarts_per_day * factor:
                    raise DemoFull("restart")
            self._check_window(self._recent_restarts, self.limits.restarts_per_minute, "full")
            self._check_disk()
            copy_id = self._copy_template()
            self._remove(old)
            for key, _ in quotas:
                self._restarts_by_ip[key] = self._restarts_by_ip.get(key, 0) + 1
            self._recent_restarts.append(now)
            self._restarted.pop(old, None)
            self._restarted[copy_id] = now
        with self._rate_lock:
            if old in self._requests:
                self._requests[copy_id] = self._requests.pop(old)
        return copy_id

    def _copy_template(self) -> str:
        copy_id = secrets.token_hex(16)
        work = self.root / f"{_WORK}{copy_id}"
        work.mkdir(mode=0o700)
        try:
            for name in (generate.DATABASE, generate.HOLDERS):
                shutil.copyfile(self.template / name, work / name)
                (work / name).chmod(0o600)
            now = self.clock()
            os.utime(work, (now, now))  # the last use: now
            os.rename(work, self.root / copy_id)
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
        return copy_id

    def while_locked(self, action: Callable[[], object]) -> None:
        """Run `action` while no copy is being created (swapping the template)."""
        with self._lock:
            action()

    def allow_request(self, copy_id: str, cost: int = 1) -> bool:
        """Charge `cost` units to the copy in this minute; False (without charging) if it does
        not have enough left."""
        minute = int(self.clock() // 60)
        with self._rate_lock:
            seen, used = self._requests.get(copy_id, (minute, 0))
            used = used if seen == minute else 0
            if used + cost > self.limits.per_minute:
                return False
            self._requests[copy_id] = (minute, used + cost)
            if len(self._requests) > 4 * self.limits.max_live:
                self._requests = {k: v for k, v in self._requests.items() if v[0] == minute}
        return True

    def live(self) -> int:
        return len(self.live_ids())

    def live_ids(self) -> set[str]:
        return {entry.name for entry in os.scandir(self.root) if valid_id(entry.name)}

    def sweep(self) -> int:
        with self._lock:
            return self.sweep_locked()

    def sweep_locked(self) -> int:
        """Delete the copies unused for more than `ttl` and what was left half done; how many."""
        now = self.clock()
        removed = 0
        for entry in os.scandir(self.root):
            name = entry.name
            stale = now - entry.stat().st_mtime > self.limits.ttl
            if valid_id(name) and stale:
                self._remove(name)
                removed += 1
            elif name.startswith((_TRASH, _WORK)) and (name.startswith(_TRASH) or stale):
                shutil.rmtree(entry.path, ignore_errors=True)
        return removed

    def _remove(self, name: str) -> None:
        """Delete a copy: first rename it (nobody finds it any more) and then delete it."""
        trash = self.root / f"{_TRASH}{name}"
        try:
            os.rename(self.root / name, trash)
        except FileNotFoundError:
            return
        shutil.rmtree(trash, ignore_errors=True)
        self._touched.pop(name, None)
        self._restarted.pop(name, None)

    def _evict_oldest(self) -> bool:
        """With the demo full: evict the copy unused for longest if `evict_after` has passed."""
        entries = [e for e in os.scandir(self.root) if valid_id(e.name)]
        if not entries:
            return False
        oldest = min(entries, key=lambda e: e.stat().st_mtime)
        if self.clock() - oldest.stat().st_mtime <= self.limits.evict_after:
            return False
        self._remove(oldest.name)
        return True

    def _touch(self, copy_id: str, folder: Path) -> None:
        now = self.clock()
        if now - self._touched.get(copy_id, 0.0) < _TOUCH_EVERY:
            return
        self._touched[copy_id] = now
        try:
            os.utime(folder, (now, now))
        except FileNotFoundError:  # the sweep deleted it meanwhile
            self._touched.pop(copy_id, None)

    def _check_window(self, recent: deque[float], limit: int, reason: str) -> None:
        """Cap on how many times per minute (across everyone)."""
        now = self.clock()
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= limit:
            raise DemoFull(reason)

    def _roll_day(self) -> None:
        today = self.today()
        if self._ip_day != today:  # a new day: every IP is forgotten
            self._ip_day = today
            self._by_ip = {}
            self._restarts_by_ip = {}

    def _check_disk(self) -> None:
        if shutil.disk_usage(self.root).free < self.limits.min_free:
            raise DemoFull("full")

    def _check_ip(self, quotas: Iterable[tuple[str, int]]) -> None:
        self._roll_day()
        for key, factor in quotas:
            if self._by_ip.get(key, 0) >= self.limits.per_ip * factor:
                raise DemoFull("ip")
