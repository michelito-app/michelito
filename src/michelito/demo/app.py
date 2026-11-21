"""The public demo: the board's same FastAPI, with one copy of the database per visitor.

`create_demo_app(settings)` generates the template (once, at startup), opens the copy store
(`copies.CopyStore`) and `feedback.db`, and builds the demo's `Mode` for `create_app`:

- database: the visitor's copy according to the `demo_id` cookie (`DemoProvider`); without a
  valid cookie none is opened. The copy is created with `POST /api/demo/session` (the interface
  asks for it on load);
- hosts: the public one (`--public-host`) and loopback (the health check and local tests);
- authors: only the user (`X-Michelito-Author: claude` is rejected); `X-Michelito` is still
  required;
- body of up to `max_body` bytes; system routes (sync, Gmail, secrets, file import) answer 403;
- its own routes (`demo.routes`): session, "start over", sample statement, feedback, usage and
  interface events ("copy for Claude");
- bounded work: one request at a time per copy, `workers` at a time in total (with a bounded
  wait), a cost budget per minute per copy (`COSTS`: expensive routes count more) and a size cap
  per copy (`PRAGMA max_page_count`; when it fills up, 507);
- maintenance in a background thread (`Maintenance`): sweeping copies, flushing the usage
  counts, pruning the in-memory caps and a new template when the month changes.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from michelito.demo import feedback_store, generate, network, routes
from michelito.demo.copies import CopyStore, Limits, valid_id
from michelito.i18n import t
from michelito.web.app import create_app
from michelito.web.workspace import Mode, Resolution

PRODUCT = "Michelito"
DEFAULT_HOST = "demo.michelito.app"
NOTICE = t("demo.notice")
LOOPBACK = ("127.0.0.1", "localhost")
# System routes: they do not exist in today's API, but if one shows up, the demo does not serve it.
BLOCKED = ("/api/sync", "/api/gmail", "/api/secrets", "/api/import", "/api/system")
# The cookie's name: with `Secure`, the `__Host-` prefix makes the browser send it only over
# HTTPS, without `Domain` and with `Path=/`; without `Secure` (tests over http) the prefix is
# not accepted.
SECURE_COOKIE = "__Host-demo_id"
PLAIN_COOKIE = "demo_id"
# The cost of a request in the copy's per-minute budget (by default, 1). Measured on the template
# on a laptop: compare ≈ 0.95 s, review/history ≈ 0.3 s, dossier ≈ 0.15 s, summary ≈ 0.13 s, the
# rest ≈ 0.05 s; the cost is ≈ how long it takes in units of 50 ms (rounded up for the dossier:
# it builds the month's Summary and "to review").
COSTS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"/api/reports/compare"), 20),
    (re.compile(r"/api/review/history"), 6),
    (re.compile(r"/api/insights/.+"), 5),
    (re.compile(r"/api/dossier"), 4),
    (re.compile(r"/api/summary"), 3),
    (re.compile(r"/api/summary/pace"), 3),
    (re.compile(r"/api/demo/sample-statement"), 3),
)
# No database and no work: they neither wait for a turn nor spend budget.
FREE = frozenset({"/api/health", "/api/mode"})
log = logging.getLogger(__name__)


def cost_of(path: str) -> int:
    return next((cost for rx, cost in COSTS if rx.fullmatch(path)), 1)


@dataclass(frozen=True)
class Settings:
    """The demo's settings (see `michelito demo --help`)."""

    data: Path  # demo folder: template, copies and feedback.db (never the real data folder)
    public_host: str = DEFAULT_HOST
    secure_cookie: bool = True  # False only to test over http on the machine
    repo: str = ""
    # The hosted app's address: when set, the interface shows the "sample data, back to
    # uploading my statements" band (the demo exit of the hosted gate). Empty: the usual demo.
    return_url: str = ""
    limits: Limits = field(default_factory=Limits)
    max_body: int = 64 * 1024
    opinions_per_copy: int = 10
    samples_per_copy: int = 6
    visits_per_copy: int = 500
    events_per_copy: int = 50  # interface events ("copy for Claude")
    proxies: tuple[str, ...] = ()  # trusted proxies (IP or network); without them XFF is ignored
    copy_extra: int = 5 * 1024 * 1024  # how much a copy may grow over the template
    workers: int = 4  # requests with a database at a time, across every copy
    copy_wait: float = 15.0  # maximum seconds waiting for the copy's turn (then 429)
    global_wait: float = 10.0  # maximum seconds waiting for a global turn (then 503)
    feedback_caps: feedback_store.Caps = field(default_factory=feedback_store.Caps)
    background: bool = True  # maintenance thread (tests run it by hand)

    @property
    def template(self) -> Path:
        return self.data / "template"

    @property
    def copies(self) -> Path:
        return self.data / "copies"

    @property
    def feedback(self) -> Path:
        return self.data / feedback_store.FILENAME


class PerCopy:
    """Per-copy caps that live in memory (feedback, sample statements, visits)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def take(self, copy_id: str) -> bool:
        with self._lock:
            used = self._counts.get(copy_id, 0)
            if used >= self.limit:
                return False
            self._counts[copy_id] = used + 1
            return True

    def transfer(self, old: str, new: str) -> None:
        """What `old` used moves to `new` ("start over" does not reset the caps)."""
        with self._lock:
            if old in self._counts:
                self._counts[new] = self._counts.pop(old)

    def prune(self, alive: Iterable[str]) -> None:
        """Forget the copies that no longer exist."""
        keep = set(alive)
        with self._lock:
            self._counts = {k: v for k, v in self._counts.items() if k in keep}


class SizeCap:
    """The page cap of each connection to a copy: the template + `extra` bytes."""

    def __init__(self, template: Path, extra: int) -> None:
        self.template = template
        self.extra = extra
        self.pages = 0
        self.measure()

    def measure(self) -> None:
        with sqlite3.connect(self.template / generate.DATABASE) as conn:
            size = conn.execute("PRAGMA page_size").fetchone()[0]
        total = (self.template / generate.DATABASE).stat().st_size + self.extra
        self.pages = math.ceil(total / size)

    def __call__(self, conn: sqlite3.Connection) -> None:
        conn.execute(f"PRAGMA max_page_count = {int(self.pages)}")


class Turns:
    """One request at a time per copy and `workers` at a time in total, with a bounded wait. It
    lives in the event loop (anyio primitives): waiting does not hold threads."""

    def __init__(self, workers: int, copy_wait: float, global_wait: float) -> None:
        self.workers = workers
        self.copy_wait = copy_wait
        self.global_wait = global_wait
        self._global: anyio.Semaphore | None = None
        # A semaphore of 1 per copy (not a Lock: anyone may release it, not only its holder).
        self._copies: dict[str, anyio.Semaphore] = {}

    async def take(self, copy_id: str) -> Callable[[], None] | Response:
        """A turn (returning how to release it) or the 429/503 response if it came too late."""
        if self._global is None:
            self._global = anyio.Semaphore(self.workers)
        if len(self._copies) > 1000:  # prune: the ones nobody holds
            self._copies = {k: v for k, v in self._copies.items() if v.value == 0}
        lock = self._copies.setdefault(copy_id, anyio.Semaphore(1))
        if not await _within(lock.acquire, self.copy_wait):
            return _busy(429, t("demo.copy_busy"))
        semaphore = self._global
        if not await _within(semaphore.acquire, self.global_wait):
            lock.release()
            return _busy(503, t("demo.busy"))

        def release() -> None:
            semaphore.release()
            lock.release()

        return release


async def _within(acquire: Callable[[], Awaitable[None]], seconds: float) -> bool:
    """Wait for `acquire` at most `seconds`; True if it got it."""
    with anyio.move_on_after(seconds):
        await acquire()
        return True
    return False


def _busy(status: int, detail: str) -> Response:
    return JSONResponse({"detail": detail}, status_code=status, headers={"Retry-After": "5"})


@dataclass(frozen=True)
class DemoProvider:
    """Each request's database: the copy of its cookie (if it is valid and exists)."""

    store: CopyStore
    feedback: feedback_store.Feedback
    secure_cookie: bool
    turns: Turns

    @property
    def cookie(self) -> str:
        return SECURE_COOKIE if self.secure_cookie else PLAIN_COOKIE

    async def resolve(self, request: Request) -> Resolution:
        path = request.url.path
        copy_id = request.cookies.get(self.cookie)
        if not path.startswith("/api/") or not valid_id(copy_id):
            return Resolution(None)
        assert copy_id is not None
        workspace = await anyio.to_thread.run_sync(self.store.workspace, copy_id)
        if workspace is None:
            return Resolution(None)
        finish = self._finisher(request)
        if path in FREE:
            return Resolution(workspace, finish=finish)
        if not self.store.allow_request(copy_id, cost_of(path)):
            refusal = _busy(429, t("demo.too_many_requests"))
            return Resolution(None, refusal=refusal)
        turn = await self.turns.take(copy_id)
        if isinstance(turn, Response):
            return Resolution(None, refusal=turn)
        return Resolution(workspace, finish=finish, release=turn)

    def has_session(self, request: Request) -> bool:
        return self.store.workspace(request.cookies.get(self.cookie)) is not None

    def set_cookie(self, response: Response, copy_id: str) -> None:
        response.set_cookie(
            self.cookie,
            copy_id,
            max_age=int(self.store.limits.ttl),
            httponly=True,
            secure=self.secure_cookie,
            samesite="lax",
            path="/",
        )

    def _finisher(self, request: Request) -> Callable[[Response], None]:
        def finish(response: Response) -> None:  # runs in a thread (see `create_app`)
            if request.url.path == "/api/mode":  # the cookie lasts as long as the copy
                self.set_cookie(response, request.cookies.get(self.cookie, ""))
            event = routes.event_of(request.method, request.url.path, response.status_code)
            if event is not None:
                try:
                    self.feedback.count("event", event)
                except Exception:  # a counter must not bring the response down
                    log.exception("could not count the event %s", event)

        return finish


class Maintenance:
    """What runs in the background: sweeping, flushing counts, pruning and the month's template."""

    def __init__(
        self,
        settings: Settings,
        store: CopyStore,
        feedback: feedback_store.Feedback,
        per_copy: Iterable[PerCopy],
        size: SizeCap,
        today: Callable[[], date],
    ) -> None:
        self.settings = settings
        self.store = store
        self.feedback = feedback
        self.per_copy = tuple(per_copy)
        self.size = size
        self.today = today
        self.month = today().strftime("%Y-%m")
        self._stop = threading.Event()

    def run_once(self) -> None:
        for step in (self.feedback.flush, self.sweep, self.refresh_template):
            try:
                step()
            except Exception:  # maintenance goes on even if a step fails
                log.exception("demo maintenance failed (%s)", step.__name__)

    def sweep(self) -> None:
        self.store.sweep()
        alive = self.store.live_ids()
        for limits in self.per_copy:
            limits.prune(alive)

    def refresh_template(self) -> None:
        """A new month: a new template (atomic, without creating copies at the same time). The
        live copies keep theirs."""
        today = self.today()
        month = today.strftime("%Y-%m")
        if month == self.month:
            return
        self.store.while_locked(lambda: generate.build_template(self.settings.template, today))
        self.size.measure()
        self.month = month
        log.info("new template for %s", month)

    def start(self) -> None:
        def loop() -> None:
            beat = 60.0
            ticks = 0
            while not self._stop.wait(beat):
                ticks += 1
                self.flush()
                if ticks * beat >= self.settings.limits.sweep_every:
                    ticks = 0
                    self.run_once()

        threading.Thread(target=loop, name="demo-maintenance", daemon=True).start()

    def flush(self) -> None:
        try:
            self.feedback.flush()
        except Exception:
            log.exception("could not flush the usage counts")

    def stop(self) -> None:
        self._stop.set()
        self.flush()


def version() -> str:
    try:
        return metadata.version("michelito")
    except metadata.PackageNotFoundError:  # pragma: no cover - it is always installed
        return "0"


def create_demo_app(
    settings: Settings,
    static_dir: Path | None = None,
    today: Callable[[], date] = date.today,
) -> FastAPI:
    """The demo app; it generates the template before serving."""
    generate.use_demo_providers()
    built = generate.build_template(settings.template, today())
    log.info("template generated in %.2f s", built.seconds)
    store = CopyStore(settings.copies, settings.template, settings.limits, today=today)
    feedback = feedback_store.Feedback(settings.feedback, settings.feedback_caps)
    turns = Turns(settings.workers, settings.copy_wait, settings.global_wait)
    provider = DemoProvider(store, feedback, settings.secure_cookie, turns)
    size = SizeCap(settings.template, settings.copy_extra)
    hooks = routes.Hooks(
        provider=provider,
        store=store,
        feedback=feedback,
        opinions=PerCopy(settings.opinions_per_copy),
        samples=PerCopy(settings.samples_per_copy),
        visits=PerCopy(settings.visits_per_copy),
        events=PerCopy(settings.events_per_copy),
        today=today,
        proxies=network.networks(settings.proxies),
    )
    check_return_url(settings.return_url)
    mode = Mode(
        name="demo",
        provider=provider,
        allowed_hosts=(settings.public_host, *LOOPBACK),
        authors=("user",),
        blocked=BLOCKED,
        max_body=settings.max_body,
        info={
            "name": PRODUCT,
            "version": version(),
            "repo": settings.repo,
            "notice": NOTICE,
            **({"return_url": settings.return_url} if settings.return_url else {}),
        },
        register=lambda app, connection, load_flow: routes.register(app, connection, hooks),
        on_connect=size,
    )
    app = create_app(built.database, static_dir, today, built.holders, mode=mode)
    maintenance = Maintenance(
        settings,
        store,
        feedback,
        (hooks.opinions, hooks.samples, hooks.visits, hooks.events),
        size,
        today,
    )
    if settings.background:
        maintenance.start()
    app.state.template_seconds = built.seconds
    app.state.maintenance = maintenance
    app.state.store = store
    return app


def check_return_url(url: str) -> None:
    """The band's way back to the hosted app: empty (no band), https, or http on loopback."""
    if not url:
        return
    parsed = urlsplit(url)
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return
    raise ValueError("the return URL must be https (http only on loopback)")
