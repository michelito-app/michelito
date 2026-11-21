"""Hosted mode: the board's same FastAPI, with one database per signed-in account.

`create_hosted_app(settings, mailer)` opens the accounts database (`hosted.store`), builds the
sign-in service (`hosted.auth`) and the hosted `Mode` for `create_app`:

- database: **only** the one of the session's account (`HostedProvider`), resolved from the
  `__Host-session` cookie on every request. Without a valid session, `/api/*` answers 401 except
  health, mode and the sign-in routes (`OPEN`), and no database is opened;
- hosts: the public one and loopback; authors: only the user; writes need `X-Michelito: 1`;
- bodies up to `max_body`; system routes (sync, Gmail, secrets, file import) answer 403;
- its own routes (`hosted.routes`) and the upload and onboarding ones (`hosted.onboarding_routes`):
  `POST /api/uploads` may carry up to `uploads.body_limit` bytes, and the installed app's share
  target (`/share-target`, which opens no database) needs no `X-Michelito`;
- email forwarding (`hosted.forwarding_routes`): `POST /api/inbound-email` needs no session (it
  is signed by the Email Worker with the inbound secret, `Settings.inbound_secret` /
  `MICHELITO_INBOUND_SECRET_FILE`; without one it answers 404) and may carry up to
  `forwarding.body_limit` bytes.

Folder layout (`settings.data`): `accounts.db`, `secret.key` (unless `MICHELITO_HOSTED_SECRET_FILE`
names another file) and `users/<folder>/michelito.db`, one per account, **encrypted** with the
account's data key (`hosted.keys`). The master key that wraps those keys is a file outside this
folder (`Settings.master_key`, `MICHELITO_MASTER_KEY_FILE`): without a usable one the app does
not start (`MasterKeyError`). At start-up it also encrypts batch 1's plain placeholders, refuses
data keys wrapped by another master key and removes the folders of deleted accounts.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from michelito import config
from michelito.demo import network
from michelito.hosted import (
    forwarding,
    forwarding_routes,
    holders_files,
    inbox,
    onboarding_routes,
    pdf_worker,
    routes,
)
from michelito.hosted.auth import USERS, Policy, SignIn
from michelito.hosted.keys import MASTER_FILE_ENV, MasterKeyError, load_master
from michelito.hosted.limits import Caps
from michelito.hosted.mailer import Dispatcher, Mailer
from michelito.hosted.notices import Notices
from michelito.hosted.store import FILENAME, Session, Store
from michelito.i18n import t
from michelito.web.app import create_app
from michelito.web.workspace import Mode, Resolution, Workspace

PRODUCT = "Michelito"
DEFAULT_HOST = "michelito.app"
DEFAULT_DEMO_URL = "https://demo.michelito.app"
LOOPBACK = ("127.0.0.1", "localhost")
BLOCKED = ("/api/sync", "/api/gmail", "/api/secrets", "/api/import", "/api/system")
# Without a session only these answer; any other `/api/*` is 401.
OPEN = frozenset(
    {
        "/api/health",
        "/api/mode",
        "/api/auth/code",
        "/api/auth/verify",
        "/api/auth/link",
        "/api/auth/link/peek",
        forwarding_routes.INBOUND_PATH,  # signed by the Email Worker instead
    }
)
# `__Host-`: the browser keeps it only with `Secure`, `Path=/` and no `Domain`, so no subdomain
# can set or read it. Without `Secure` (tests over http on the machine) the prefix is refused.
SECURE_COOKIE = "__Host-session"
PLAIN_COOKIE = "session"
# The known-device cookie (signed, names nobody): same rules.
SECURE_DEVICE_COOKIE = "__Host-device"
PLAIN_DEVICE_COOKIE = "device"
SECRET_FILE_ENV = "MICHELITO_HOSTED_SECRET_FILE"
SECRET_NAME = "secret.key"


@dataclass(frozen=True)
class Settings:
    """Hosted mode's settings (see `michelito hosted --help`)."""

    data: Path  # accounts.db and the per-account folders (never the real local data folder)
    public_host: str = DEFAULT_HOST
    public_url: str = ""  # the address in the emails; by default https://<public_host>
    demo_url: str = DEFAULT_DEMO_URL  # the "see sample data" link on the signed-out page
    secure_cookie: bool = True  # False only to test over http on the machine
    proxies: tuple[str, ...] = ()  # trusted proxies (IP or network); without them XFF is ignored
    policy: Policy = field(default_factory=Policy)
    caps: Caps = field(default_factory=Caps)
    max_body: int = 64 * 1024
    floor: float = 0.4  # minimum seconds to answer a code request or check
    daily_mail_limit: int = 100  # Resend's free plan: 100 emails a day
    background_mail: bool = True  # send in a thread (False: inline, for tests)
    sweep: bool = True  # drop expired upload jobs and shares every minute (tests: by hand)
    uploads: onboarding_routes.UploadCaps = field(default_factory=onboarding_routes.UploadCaps)
    master_key: Path | None = None  # the master key file (never inside `data`)
    inbound_secret: Path | None = None  # the Email Worker's HMAC secret (else the environment)
    inbound_domain: str = forwarding.DOMAIN  # the forwarding addresses' domain
    inbound_authserv: tuple[str, ...] = inbox.TRUSTED_AUTHSERV  # whose verdict the Worker passes
    forwarding: forwarding_routes.ForwardingCaps = field(
        default_factory=forwarding_routes.ForwardingCaps
    )
    inbox_background: bool = True  # read forwarded PDFs in a thread (tests: inline)

    @property
    def url(self) -> str:
        return (self.public_url or f"https://{self.public_host}").rstrip("/")

    @property
    def cookie(self) -> str:
        return SECURE_COOKIE if self.secure_cookie else PLAIN_COOKIE

    @property
    def device_cookie(self) -> str:
        return SECURE_DEVICE_COOKIE if self.secure_cookie else PLAIN_DEVICE_COOKIE


def master_key_path(given: str | None = None) -> Path | None:
    """The master key file: the one given, else `MICHELITO_MASTER_KEY_FILE`, else none."""
    text = (given or os.environ.get(MASTER_FILE_ENV, "")).strip()
    return Path(text).expanduser() if text else None


def load_secret(data: Path) -> bytes:
    """The key of the code hashes: the file in `MICHELITO_HOSTED_SECRET_FILE` (a Docker secret)
    or `<data>/secret.key`, created at random (0600) the first time."""
    named = os.environ.get(SECRET_FILE_ENV, "").strip()
    path = Path(named) if named else data / SECRET_NAME
    if not path.exists() and not named:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(secrets.token_bytes(32))
    return path.read_bytes()


@dataclass(frozen=True)
class HostedProvider:
    """Each request's database: the one of its session's account, and nothing else."""

    service: SignIn
    cookie: str
    proxies: tuple[network.Network, ...] = ()

    async def resolve(self, request: Request) -> Resolution:
        path = request.url.path
        network.warn_unconfigured_proxy(request, self.proxies)
        if not path.startswith("/api/") and path != "/api":
            return Resolution(None)
        token = request.cookies.get(self.cookie)
        found = await anyio.to_thread.run_sync(self._open, token) if token else None
        session, workspace = found or (None, None)
        request.state.hosted_session = session
        if session is None:
            if path in OPEN:
                return Resolution(None)
            return Resolution(
                None, refusal=JSONResponse({"detail": t("hosted.signed_out")}, status_code=401)
            )
        return Resolution(workspace)

    def _open(self, token: str) -> tuple[Session, Workspace] | None:
        """In a thread: the cookie's live session and its account's workspace (key unwrapped)."""
        session = self.service.lookup(token)
        if session is None:
            return None
        return session, self.service.workspace(session)

    def has_session(self, request: Request) -> bool:
        session: Session | None = getattr(request.state, "hosted_session", None)
        return session is not None


def _same_key(master: bytes, secret: bytes) -> bool:
    """Whether the code-hash secret is the master key (raw, or the same hexadecimal text)."""
    if hmac.compare_digest(master, secret):
        return True
    try:
        return hmac.compare_digest(master, bytes.fromhex(secret.strip().decode("ascii")))
    except (UnicodeDecodeError, ValueError):
        return False


class HostedStateError(Exception):
    """The hosted folder is not in a state the server may start on (the message says why)."""


def check_accounts_database(data: Path) -> None:
    """Refuse to create a new, empty accounts database next to existing user folders: that
    would be a lost or replaced `accounts.db`, and every account (and key) would be gone."""
    users = data / USERS
    if (data / FILENAME).exists() or not users.is_dir():
        return
    if any(users.iterdir()):
        raise HostedStateError(
            f"{data / FILENAME} is missing but {users} holds account folders: restore the "
            "accounts database from a backup (a new one would orphan every account)"
        )


def build_service(
    settings: Settings,
    mailer: Mailer,
    clock: Callable[[], float] = time.time,
    with_master: bool = True,
) -> SignIn:
    """The sign-in service over the hosted folder. `with_master`: load the master key (refused
    if missing or unusable); `michelito invite` goes without (it opens no user database)."""
    data = config.ensure_private_dir(settings.data)
    master = load_master(settings.master_key, data) if with_master else None
    check_accounts_database(data)
    secret = load_secret(data)
    if master is not None and _same_key(master.secret, secret):
        raise MasterKeyError("the master key must not be the same as the code-hash secret")
    store = Store(data / FILENAME)
    dispatcher = Dispatcher(
        mailer,
        settings.daily_mail_limit,
        background=settings.background_mail,
        clock=clock,
        ledger=store,  # the day's count is shared with `michelito invite`
    )
    return SignIn(
        store,
        dispatcher,
        secret,
        data,
        settings.url,
        settings.policy,
        settings.caps,
        clock,
        master,
    )


def create_hosted_app(
    settings: Settings,
    mailer: Mailer,
    static_dir: Path | None = None,
    today: Callable[[], date] = config.local_today,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    service = build_service(settings, mailer, clock)
    data = service.root
    store = service.store
    dispatcher = service.dispatcher
    service.check_keys()  # first: nothing is unwrapped under the wrong master key
    inbound = forwarding.load_secret(settings.inbound_secret)
    if inbound is not None and (
        _same_key(service._require_master().secret, inbound)
        or _same_key(load_secret(data), inbound)
    ):
        raise MasterKeyError("the inbound secret must not be another server key")
    service.seal_placeholders()
    holders_files.absorb(store, service._require_master(), data)  # no plaintext holders
    service.remove_deleted()
    store.prune_codes(int(clock()))
    proxies = network.networks(settings.proxies)
    provider = HostedProvider(service, settings.cookie, proxies)
    hooks = routes.Hooks(
        service=service,
        cookie=settings.cookie,
        secure_cookie=settings.secure_cookie,
        floor=settings.floor,
        proxies=proxies,
        device_cookie=settings.device_cookie,
    )
    check_demo_url(settings.demo_url)
    gate = onboarding_routes.Hooks(
        store=store, caps=settings.uploads, proxies=proxies, secure_cookie=settings.secure_cookie
    )

    def leave(account_id: int) -> None:
        """An account's sessions ended here: drop its upload jobs (with their bytes and the key
        their thread holds) and forget that it was past the gate."""
        gate.jobs.forget(account_id)
        gate.opened.discard(account_id)

    hooks = replace(hooks, on_leave=leave)
    pdf_worker.configure(settings.uploads.worker_slots)

    mail = forwarding_routes.Hooks(
        service=service,
        secret=inbound,
        notices=Notices(dispatcher, settings.url),
        domain=settings.inbound_domain,
        trusted=settings.inbound_authserv,
        caps=settings.forwarding,
        limits=settings.uploads.worker,
        background=settings.inbox_background,
        proxies=proxies,
        clock=clock,
    )

    def register(app: FastAPI, connection, load_flow) -> None:  # noqa: ANN001
        routes.register(app, hooks)
        onboarding_routes.register(app, gate, connection, load_flow)
        forwarding_routes.register(app, mail, connection)

    mode = Mode(
        name="hosted",
        provider=provider,
        allowed_hosts=(settings.public_host, *LOOPBACK),
        authors=("user",),
        blocked=BLOCKED,
        max_body=settings.max_body,
        info={"name": PRODUCT, "demo_url": settings.demo_url},
        register=register,
        body_limits=(
            ("/api/uploads", settings.uploads.body_limit),
            (onboarding_routes.SHARE_PATH, settings.uploads.body_limit),
            (forwarding_routes.INBOUND_PATH, settings.forwarding.body_limit),
        ),
        open_writes=frozenset({onboarding_routes.SHARE_PATH}),
        guard=onboarding_routes.gate_guard(gate),
    )
    # The path is never opened: with a mode, every database comes from the provider.
    app = create_app(data / "unused.db", static_dir, today, mode=mode)
    app.state.service = service
    app.state.dispatcher = dispatcher
    app.state.uploads = gate
    app.state.forwarding = mail
    if settings.sweep:
        app.state.sweeper = Sweeper(gate)

    @app.middleware("http")
    async def no_store(request: Request, call_next):  # noqa: ANN001, ANN202
        # Every API answer is someone's private data or session state: never cached anywhere.
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app


class Sweeper:
    """Every `every` seconds, drop expired upload jobs and shares (and their bytes), even when no
    request comes. A daemon thread: it ends with the process."""

    def __init__(self, gate: onboarding_routes.Hooks, every: float = 60.0) -> None:
        self.gate = gate
        self.every = every
        self._stop = threading.Event()
        threading.Thread(target=self._run, name="michelito-sweeper", daemon=True).start()

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            self.gate.jobs.prune()
            self.gate.shares.prune()

    def stop(self) -> None:
        self._stop.set()


def check_demo_url(url: str) -> None:
    """The "see sample data" link must be https (http only on loopback, for tests). That demo
    must be started with `--return-url` pointing back here, or it shows no way back (the band):
    a deployment pairs them (see the README)."""
    parsed = urlsplit(url)
    loopback = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and loopback:
        return
    raise ValueError("the demo URL must be https (http only on loopback)")
