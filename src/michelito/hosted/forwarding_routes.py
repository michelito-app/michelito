"""Hosted mode's email-forwarding routes (see `hosted.forwarding` and `hosted.inbox`).

- `POST /api/inbound-email` (no session; the Cloudflare Email Worker): signed with HMAC-SHA256
  over timestamp, nonce and body; the signature is checked before anything else is read, then
  the time window, then the nonce (each once). The body is `{"recipient", "raw", "auth"}`
  (`raw`: the whole message in base64; `auth`: the `Authentication-Results` header Cloudflare's
  receiving server wrote). The account comes **only** from the signed recipient's token; then
  per-account and global rate limits, idempotency by Message-ID (in the account's database) and
  the routing (`inbox.receive`). Statement PDFs are read after the answer, in a background
  thread. Nothing about the message (body, addresses beyond the domain, attachment names) is
  ever logged or returned: the answer is only `{"status": "accepted"}`.
- `GET /api/forwarding`: the address, Gmail's confirmation code and link (never confirmed here),
  the waiting statements, the quarantine, which banks have a stored password (yes/no, never the
  password), the latest arrivals, problems and late statements.
- `POST /api/forwarding/address` (create, only when there is none) and
  `POST /api/forwarding/address/rotate` (step-up: a fresh verification; the old address stops
  working at once).
- `POST /api/forwarding/confirmation/dismiss`.
- `POST /api/forwarding/waiting/unlock` (`{"bank", "password"}`, read by hand like the upload's
  password: never logged, stored or echoed).
- `POST /api/forwarding/quarantine/{id}/approve` and `DELETE /api/forwarding/quarantine/{id}`.
- `PUT /api/forwarding/passwords/{bank}` (step-up; `{"password"}`: stored sealed in the
  account's database, then tried on that bank's waiting statements) and
  `DELETE /api/forwarding/passwords/{bank}` ("forget my password").
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from dataclasses import dataclass, field
from datetime import date, timedelta

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from michelito import db
from michelito.analysis import changelog
from michelito.demo import network
from michelito.hosted import forwarding, inbound_mail, inbox, inbox_store, pdf_worker
from michelito.hosted.auth import AuthError, SignIn
from michelito.hosted.inbox_store import Sealer
from michelito.hosted.limits import Window
from michelito.hosted.notices import Notices
from michelito.hosted.routes import ERROR_HEADER, current, failure
from michelito.hosted.store import Account
from michelito.i18n import t
from michelito.web.workspace import CURRENT, Workspace

log = logging.getLogger(__name__)
MB = 1024 * 1024
INBOUND_PATH = "/api/inbound-email"
UNLOCK_BANKS = (*inbox.SUPPORTED_BANKS, inbox.OTHER_BANK)
CONFIRM_CODE = "confirmation_required"
PROBLEM_DAYS = 30
PROBLEMS = frozenset(
    {"invalid", "unsupported", "unreadable", "too_complex", "full", "failed", "password_wrong"}
)

Connect = Callable[[], AbstractContextManager[sqlite3.Connection]]


RECIPIENT_MAX = 320
AUTH_MAX = 8000
# The JSON around the message: its keys, quotes and the recipient and verdict at their longest.
ENVELOPE = RECIPIENT_MAX + AUTH_MAX + 512


@dataclass(frozen=True)
class ForwardingCaps:
    """Inbound limits: the largest message (`message_bytes`); requests whose **signature
    failed**, per source network per minute (`per_source_minute`) and for the whole server per
    minute (`unsigned_minute`): a validly signed request never counts against them, so junk
    from the Worker's shared egress cannot block genuine mail; messages per account per hour
    and per day and for the whole server per hour, both counted only once the recipient is a
    real address; requests for unknown addresses per hour (`unknown_hour`, their own budget:
    they never use the real ones'); and typed passwords per account."""

    message_bytes: int = 10 * MB
    per_source_minute: int = 300
    unsigned_minute: int = 1000
    per_account_hour: int = 60
    per_account_day: int = 300
    global_hour: int = 1000
    unknown_hour: int = 200
    concurrent_reads: int = 4  # bodies read at once on the inbound route (503 beyond)
    read_seconds: float = 30.0  # a whole body, at most (408 beyond)
    idle_seconds: float = 10.0  # between two chunks of a body, at most (408 beyond)
    unlocks_per_window: int = 10
    unlock_window: float = 15 * 60.0

    @property
    def base64_limit(self) -> int:
        return (self.message_bytes + 2) // 3 * 4

    @property
    def body_limit(self) -> int:
        """What a `message_bytes` message needs in base64, plus the envelope: nothing more."""
        return self.base64_limit + ENVELOPE


class Slots:
    """A non-blocking count of in-flight body reads: `enter` is False when all are taken."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._used = 0
        self._lock = threading.Lock()

    def enter(self) -> bool:
        with self._lock:
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    def leave(self) -> None:
        with self._lock:
            self._used = max(0, self._used - 1)


@dataclass
class Hooks:
    service: SignIn
    secret: bytes | None = field(repr=False)
    notices: Notices
    domain: str = forwarding.DOMAIN
    trusted: tuple[str, ...] = inbox.TRUSTED_AUTHSERV
    caps: ForwardingCaps = field(default_factory=ForwardingCaps)
    limits: pdf_worker.Limits | None = None
    background: bool = True  # read PDFs in a thread (False: inline, for tests)
    clock: Callable[[], float] = time.time
    proxies: tuple[network.Network, ...] = ()
    reads: Slots = field(init=False)
    _locks: dict[tuple[str, int], threading.Lock] = field(default_factory=dict)
    _guard: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.reads = Slots(self.caps.concurrent_reads)

    def lock(self, account_id: int, purpose: str = "inbox") -> threading.Lock:
        """One lock per account and purpose: reading its PDFs, or changing its address."""
        with self._guard:
            return self._locks.setdefault((purpose, account_id), threading.Lock())


class AddressOut(BaseModel):
    address: str | None
    created: bool  # a token exists for the account (rotating it needs a step-up)


class ConfirmationOut(BaseModel):
    code: str | None
    link: str | None  # rebuilt from an allowlisted pattern (`inbound_mail.safe_link`)
    requester: str | None  # the Gmail address that asked to forward here
    received_at: str


class WaitingOut(BaseModel):
    id: int
    bank: str
    state: str  # queued, password (locked) or approval (an account not known yet)
    reason: str  # "" (being read), "missing", "wrong" or "new_account"
    received_at: str


class QuarantineOut(BaseModel):
    id: int
    sender_domain: str
    received_at: str
    attachments: int
    reason: str  # unknown_sender, unauthenticated or unknown_card
    claims_bank: bool  # it says it comes from one of the banks: approving it needs a warning


class ApprovalOut(BaseModel):
    id: int
    kind: str  # statement or alert
    sender_domain: str
    approved_at: str


class ConfirmBody(BaseModel):
    confirmed: bool = False


class ArrivalOut(BaseModel):
    bank: str | None
    kind: str | None  # the account's kind (credit_card, savings...)
    identifier: str | None
    month: str | None
    at: str


class ProblemOut(BaseModel):
    kind: str
    outcome: str
    bank: str | None
    at: str


class OverdueOut(BaseModel):
    bank: str
    kind: str
    identifier: str
    expected: str


class ForwardingOut(BaseModel):
    address: str | None
    created: bool
    confirmation: ConfirmationOut | None
    waiting: list[WaitingOut]
    quarantine: list[QuarantineOut]
    passwords: dict[str, bool]
    approvals: list[ApprovalOut]
    arrivals: list[ArrivalOut]
    problems: list[ProblemOut]
    overdue: list[OverdueOut]


class UnlockOut(BaseModel):
    opened: int
    left: int


class StoredOut(BaseModel):
    stored: bool
    opened: int
    left: int


def _password_body(raw: bytes, with_bank: bool) -> tuple[str, str]:
    """`(bank, password)` read by hand: a malformed body gets a fixed message that never
    repeats what was sent."""
    try:
        payload = json.loads(raw)
        password = payload["password"]
        bank = payload["bank"] if with_bank else ""
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, t("forwarding.bad_request")) from None
    if not isinstance(password, str) or not 0 < len(password) <= 128:
        raise HTTPException(422, t("forwarding.bad_request"))
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        raise HTTPException(422, t("forwarding.bad_request")) from None
    if with_bank and bank not in UNLOCK_BANKS:
        raise HTTPException(422, t("forwarding.unknown_bank"))
    return str(bank), password


def _inbound_body(raw: bytes, caps: ForwardingCaps) -> tuple[str, bytes, str]:
    try:
        payload = json.loads(raw)
        recipient, message, auth = payload["recipient"], payload["raw"], payload.get("auth", "")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(422, t("forwarding.bad_request")) from None
    if not (isinstance(recipient, str) and isinstance(message, str) and isinstance(auth, str)):
        raise HTTPException(422, t("forwarding.bad_request"))
    if len(recipient) > RECIPIENT_MAX or len(auth) > AUTH_MAX:
        raise HTTPException(422, t("forwarding.bad_request"))
    if len(message) > caps.base64_limit:
        raise HTTPException(413, t("forwarding.too_large"))
    try:
        data = base64.b64decode(message, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, t("forwarding.bad_request")) from None
    if not data or len(data) > caps.message_bytes:
        raise HTTPException(413, t("forwarding.too_large"))
    return recipient, data, auth


def _session_workspace() -> Workspace:
    found = CURRENT.get()
    if found is None or found.key is None:
        raise HTTPException(401, t("hosted.signed_out"))
    return found


def register(app: FastAPI, hooks: Hooks, connection: Connect) -> None:
    service, caps = hooks.service, hooks.caps
    store = service.store
    hourly = Window(caps.per_account_hour, 3600, hooks.clock)
    daily = Window(caps.per_account_day, 24 * 3600, hooks.clock)
    everyone = Window(caps.global_hour, 3600, hooks.clock)
    strangers = Window(caps.unknown_hour, 3600, hooks.clock)
    sources = Window(caps.per_source_minute, 60, hooks.clock)
    unsigned = Window(caps.unsigned_minute, 60, hooks.clock)
    unlocks = Window(caps.unlocks_per_window, caps.unlock_window, hooks.clock)

    def drain(account: Account, workspace: Workspace, wait: bool = True) -> None:
        """Read the account's queued PDFs (one drain per account at a time); then email its
        problems. Whatever fails, only the error's class name is logged."""
        lock = hooks.lock(account.id)
        if not lock.acquire(blocking=wait):
            return
        try:
            assert workspace.key is not None
            with closing(db.connect(workspace.database, workspace.key)) as conn:
                done = inbox.drain(conn, Sealer.of(workspace.key), hooks.limits)
                hooks.notices.send(conn, account.email, done.notices)
        except Exception as exc:  # noqa: BLE001 - see above
            log.error("forwarded statements could not be read: %s", type(exc).__name__)
        finally:
            lock.release()

    def later(account: Account, workspace: Workspace) -> None:
        if hooks.background:
            threading.Thread(
                target=drain, args=(account, workspace), name="michelito-inbox", daemon=True
            ).start()
        else:
            drain(account, workspace)

    def deliver(recipient: str, raw: bytes, auth: str) -> Response:
        """In a thread: find the account by its token, check its limits and route the message."""
        unknown = JSONResponse({"detail": t("forwarding.unknown_address")}, status_code=404)
        token = forwarding.token_of(recipient, hooks.domain)
        if token is None:
            strangers.take([("unknown", 1)])
            return unknown  # the Worker rejects it for good (no retry)
        account = store.account_by_forwarding(forwarding.token_hash(token))
        if account is None:
            # Their own budget: guessing addresses never uses the real accounts' one. Once
            # spent, the answer is the same 404, with no more work.
            strangers.take([("unknown", 1)])
            return unknown
        # Only a real address counts against the whole server's budget.
        if not everyone.take([("all", 1)]):
            return JSONResponse({"detail": t("forwarding.rate_limited")}, status_code=429)
        mine = [(f"account:{account.id}", 1)]
        if not daily.can(mine) or not hourly.take(mine):
            return JSONResponse({"detail": t("forwarding.rate_limited")}, status_code=429)
        daily.take(mine)
        workspace = service.workspace_of(account)
        assert workspace.key is not None
        with closing(db.connect(workspace.database, workspace.key)) as conn:
            result = inbox.receive(conn, Sealer.of(workspace.key), raw, auth, hooks.trusted)
            hooks.notices.send(conn, account.email, result.notices)
        log.info("forwarded email handled: %s", result.route)
        if result.queued:
            later(account, workspace)
        return JSONResponse({"status": "accepted"}, status_code=202)

    @app.post(INBOUND_PATH, status_code=202)
    async def post_inbound(request: Request) -> Response:
        """Cheap refusals first, without reading the body: malformed signature headers, a time
        outside the window, a missing or oversized Content-Length, or a pre-authentication
        tag (HMAC over timestamp, nonce and length) that does not match: only the Worker can
        make one, so nobody else ever takes a read slot. Those count against the
        failed-signature buckets, and a full bucket never refuses a request before its tag is
        known (the Worker's egress is shared). Then at most `concurrent_reads` bodies are read
        at once (503 beyond: the Worker retries), each streamed into the HMAC, exactly the
        declared length, within `read_seconds` in all and `idle_seconds` between chunks
        (408 otherwise). The full-body HMAC is the real authentication."""
        if hooks.secret is None:
            return JSONResponse({"detail": t("forwarding.off")}, status_code=404)
        headers = request.headers
        timestamp = headers.get(forwarding.TIMESTAMP_HEADER)
        nonce = headers.get(forwarding.NONCE_HEADER)
        signature = headers.get(forwarding.SIGNATURE_HEADER)
        declared = headers.get("content-length", "")
        length = int(declared) if declared.isascii() and declared.isdigit() else None
        if length is not None and length > caps.body_limit:
            return JSONResponse({"detail": t("forwarding.too_large")}, status_code=413)
        moment = forwarding.precheck(
            hooks.secret,
            timestamp,
            nonce,
            signature,
            headers.get(forwarding.PREAUTH_HEADER),
            length,
            hooks.clock(),
        )
        if moment is None or None in (timestamp, nonce, signature, length):
            return failed(request)
        assert timestamp is not None and nonce is not None and signature is not None
        assert length is not None
        if not hooks.reads.enter():
            return JSONResponse({"detail": t("forwarding.busy")}, status_code=503)
        try:
            mac = forwarding.Mac(hooks.secret, timestamp, nonce)
            read = await read_exactly(request, length, mac, caps)
        finally:
            hooks.reads.leave()
        if isinstance(read, Response):
            return read
        body, mac = read
        if not mac.matches(signature):
            return failed(request)
        now = int(hooks.clock())
        expires = moment + forwarding.WINDOW + 1
        fresh = await anyio.to_thread.run_sync(store.take_nonce, nonce, now, expires)
        if not fresh:
            return JSONResponse({"detail": t("forwarding.replayed")}, status_code=409)
        recipient, raw, auth = _inbound_body(body, caps)
        try:
            return await anyio.to_thread.run_sync(deliver, recipient, raw, auth)
        except Exception as exc:  # noqa: BLE001 - never the message: only the class name
            log.error("a forwarded email could not be handled: %s", type(exc).__name__)
            return JSONResponse({"detail": t("forwarding.failed")}, status_code=503)

    def failed(request: Request) -> Response:
        """A request whose signature is missing, malformed, outside the window or wrong: it is
        counted per source network and for the whole server (only these ever are)."""
        where = network.quota_keys(network.client_ip(request, hooks.proxies))
        if not sources.take(where) or not unsigned.take([("all", 1)]):
            return JSONResponse({"detail": t("forwarding.rate_limited")}, status_code=429)
        return JSONResponse({"detail": t("forwarding.bad_signature")}, status_code=401)

    # The person's routes (a session; after the gate).

    def address_of(account: Account, conn: sqlite3.Connection) -> AddressOut:
        """The account's address. The account's database is written first and the hash second
        (`new_address`), so a mismatch can only be a change that stopped half-way: it is
        finished here (the token in the account's database becomes the one that works)."""
        token = inbox_store.token(conn)
        if token is None:
            return AddressOut(address=None, created=store.forwarding_hash(account.id) is not None)
        with hooks.lock(account.id, "address"):
            if store.forwarding_hash(account.id) != forwarding.token_hash(token):
                store.set_forwarding(account.id, forwarding.token_hash(token), int(hooks.clock()))
        return AddressOut(address=forwarding.address(token, hooks.domain), created=True)

    def state(request: Request) -> ForwardingOut:
        session = current(request)
        workspace = _session_workspace()
        today = date.today()
        with connection() as conn:
            inbox_store.ensure(conn)
            with conn:
                inbox_store.prune(conn, today)
            found = address_of(session.account, conn)
            queued = inbox_store.waiting(conn, state="queued")
            out = ForwardingOut(
                address=found.address,
                created=found.created,
                confirmation=_confirmation(conn),
                waiting=[
                    WaitingOut(
                        id=w.id,
                        bank=w.bank,
                        state=w.state,
                        reason=w.reason,
                        received_at=w.received_at,
                    )
                    for w in inbox_store.waiting(conn)
                ],
                quarantine=[
                    QuarantineOut(
                        id=q.id,
                        sender_domain=q.sender_domain,
                        received_at=q.received_at,
                        attachments=q.attachments,
                        reason=q.reason,
                        claims_bank=q.claims_bank,
                    )
                    for q in inbox_store.quarantined(conn)
                ],
                passwords={
                    bank: bank in inbox_store.stored_banks(conn) for bank in inbox.SUPPORTED_BANKS
                },
                approvals=[
                    ApprovalOut(
                        id=a.id,
                        kind=a.kind,
                        sender_domain=a.sender_domain,
                        approved_at=a.approved_at,
                    )
                    for a in inbox_store.approvals(conn)
                ],
                arrivals=_arrivals(conn),
                problems=_problems(conn, today),
                overdue=[
                    OverdueOut(
                        bank=o.bank,
                        kind=o.kind,
                        identifier=o.identifier,
                        expected=o.expected.isoformat(),
                    )
                    for o in inbox.overdue(conn, today)
                ]
                if found.created
                else [],
            )
        if queued:  # left behind (a restart): read them now, without making this request wait
            threading.Thread(
                target=drain, args=(session.account, workspace, False), daemon=True
            ).start()
        return out

    @app.get("/api/forwarding")
    def get_forwarding(request: Request) -> ForwardingOut:
        return state(request)

    def new_address(account: Account, create: bool) -> None:
        """Under the account's address lock: the account's database first (what Settings
        shows), then the hash (what works). A crash in between leaves the old address working
        and the new one shown; `address_of` then finishes the change."""
        with hooks.lock(account.id, "address"), connection() as conn:
            inbox_store.ensure(conn)
            if create and (
                inbox_store.token(conn) is not None or store.forwarding_hash(account.id) is not None
            ):
                raise HTTPException(409, t("forwarding.address_exists"))
            token = forwarding.new_token()
            with conn:
                inbox_store.set_token(conn, token)
            # From this moment only the new address works.
            store.set_forwarding(account.id, forwarding.token_hash(token), int(hooks.clock()))

    @app.post("/api/forwarding/address")
    def post_address(request: Request) -> ForwardingOut:
        session = current(request)
        new_address(session.account, create=True)
        return state(request)

    @app.post("/api/forwarding/address/rotate")
    def post_rotate(request: Request) -> ForwardingOut:
        session = current(request)
        try:
            service.require_step_up(session)
        except AuthError as error:
            raise failure(error) from None
        new_address(session.account, create=False)
        return state(request)

    @app.post("/api/forwarding/confirmation/dismiss", status_code=204)
    def post_dismiss(request: Request) -> Response:
        current(request)
        with connection() as conn:
            inbox_store.ensure(conn)
            with conn:
                inbox_store.drop_confirmation(conn)
        return Response(status_code=204)

    def unlocked(account: Account, bank: str, password: str) -> UnlockOut:
        workspace = _session_workspace()
        assert workspace.key is not None
        with hooks.lock(account.id), connection() as conn:
            done = inbox.unlock(conn, Sealer.of(workspace.key), bank, password, hooks.limits)
            hooks.notices.send(conn, account.email, done.notices)
        return UnlockOut(opened=done.opened, left=done.left)

    @app.post("/api/forwarding/waiting/unlock")
    async def post_unlock(request: Request) -> UnlockOut:
        session = current(request)
        bank, password = _password_body(await request.body(), with_bank=True)
        if not unlocks.take([(f"account:{session.account.id}", 1)]):
            raise HTTPException(429, t("forwarding.rate_limited"))
        place = CURRENT.get()

        def work() -> UnlockOut:
            token = CURRENT.set(place)
            try:
                return unlocked(session.account, bank, password)
            finally:
                CURRENT.reset(token)

        return await anyio.to_thread.run_sync(work)

    def confirmed(body: ConfirmBody | None) -> None:
        """Approving is an explicit second step: the interface shows what it means (and, for a
        message that claims to be the bank's, that someone may be impersonating it) first."""
        if body is None or not body.confirmed:
            raise HTTPException(
                409, t("forwarding.confirm_first"), headers={ERROR_HEADER: CONFIRM_CODE}
            )

    @app.post("/api/forwarding/quarantine/{item_id}/approve")
    def post_approve(
        item_id: int, request: Request, body: ConfirmBody | None = None
    ) -> ForwardingOut:
        session = current(request)
        confirmed(body)
        workspace = _session_workspace()
        assert workspace.key is not None
        with connection() as conn:
            result = inbox.approve(conn, Sealer.of(workspace.key), item_id)
            if result is None:
                raise HTTPException(404, t("forwarding.unknown_item"))
            hooks.notices.send(conn, session.account.email, result.notices)
        if result.queued:
            drain(session.account, workspace)
        return state(request)

    @app.delete("/api/forwarding/quarantine/{item_id}", status_code=204)
    def delete_quarantine(item_id: int, request: Request) -> Response:
        current(request)
        with connection() as conn:
            if not inbox.discard(conn, item_id):
                raise HTTPException(404, t("forwarding.unknown_item"))
        return Response(status_code=204)

    @app.post("/api/forwarding/waiting/{item_id}/approve")
    def post_approve_held(
        item_id: int, request: Request, body: ConfirmBody | None = None
    ) -> ForwardingOut:
        """A statement of an account the person does not have yet: approved, it is stored."""
        session = current(request)
        confirmed(body)
        workspace = _session_workspace()
        with connection() as conn:
            if not inbox.approve_held(conn, item_id):
                raise HTTPException(404, t("forwarding.unknown_item"))
        drain(session.account, workspace)
        return state(request)

    @app.delete("/api/forwarding/waiting/{item_id}", status_code=204)
    def delete_waiting(item_id: int, request: Request) -> Response:
        current(request)
        with connection() as conn:
            if not inbox.discard_waiting(conn, item_id):
                raise HTTPException(404, t("forwarding.unknown_item"))
        return Response(status_code=204)

    @app.post("/api/forwarding/approvals/{item_id}/undo")
    def post_take_back(item_id: int, request: Request) -> ForwardingOut:
        """Take back what entered by approval: an alert's provisional is discarded (in the log,
        undoable there); a statement's transactions are removed, if nothing uses them."""
        current(request)
        with connection() as conn:
            try:
                found = inbox.take_back(conn, item_id, changelog.now().isoformat())
            except inbox.Linked:
                raise HTTPException(409, t("forwarding.approval_in_use")) from None
            if not found:
                raise HTTPException(404, t("forwarding.unknown_item"))
        return state(request)

    def bank_of(bank: str) -> str:
        if bank not in inbox.SUPPORTED_BANKS:
            raise HTTPException(422, t("forwarding.unknown_bank"))
        return bank

    @app.put("/api/forwarding/passwords/{bank}")
    async def put_password(bank: str, request: Request) -> StoredOut:
        session = current(request)
        chosen = bank_of(bank)
        _, password = _password_body(await request.body(), with_bank=False)
        try:
            service.require_step_up(session)
        except AuthError as error:
            raise failure(error) from None
        place = CURRENT.get()

        def work() -> StoredOut:
            token = CURRENT.set(place)
            try:
                workspace = _session_workspace()
                assert workspace.key is not None
                with connection() as conn:
                    inbox_store.ensure(conn)
                    with conn:
                        inbox_store.store_password(conn, Sealer.of(workspace.key), chosen, password)
                done = unlocked(session.account, chosen, password)
                return StoredOut(stored=True, opened=done.opened, left=done.left)
            finally:
                CURRENT.reset(token)

        return await anyio.to_thread.run_sync(work)

    @app.delete("/api/forwarding/passwords/{bank}", status_code=204)
    def delete_password(bank: str, request: Request) -> Response:
        current(request)
        chosen = bank_of(bank)
        with connection() as conn:
            inbox_store.ensure(conn)
            with conn:
                inbox_store.forget_password(conn, chosen)
        return Response(status_code=204)


async def read_exactly(
    request: Request, length: int, mac: forwarding.Mac, caps: ForwardingCaps
) -> tuple[bytes, forwarding.Mac] | Response:
    """The body, exactly `length` bytes, fed to `mac` chunk by chunk, within the deadlines;
    a Response (400, 408) instead when it does not arrive that way."""
    chunks: list[bytes] = []
    size = 0
    stream = request.stream().__aiter__()
    try:
        with anyio.fail_after(caps.read_seconds):
            while True:
                with anyio.fail_after(caps.idle_seconds):
                    try:
                        chunk = await stream.__anext__()
                    except StopAsyncIteration:
                        break
                size += len(chunk)
                if size > length:
                    return JSONResponse({"detail": t("forwarding.bad_length")}, status_code=400)
                mac.update(chunk)
                chunks.append(chunk)
    except TimeoutError:
        return JSONResponse({"detail": t("forwarding.too_slow")}, status_code=408)
    if size != length:
        return JSONResponse({"detail": t("forwarding.bad_length")}, status_code=400)
    return b"".join(chunks), mac


def _confirmation(conn: sqlite3.Connection) -> ConfirmationOut | None:
    found = inbox_store.confirmation(conn)
    if found is None:
        return None
    return ConfirmationOut(
        code=found.code,
        link=inbound_mail.safe_link(found.link),
        requester=found.requester,
        received_at=found.received_at,
    )


def _arrivals(conn: sqlite3.Connection) -> list[ArrivalOut]:
    """The newest statement that arrived by email per account (bank and last four)."""
    newest: dict[tuple[str | None, str | None], ArrivalOut] = {}
    for event in inbox_store.events(conn, limit=inbox_store.EVENTS_KEPT):
        if event.kind != "statement" or event.outcome not in ("squared", "duplicate"):
            continue
        key = (event.bank, event.identifier)
        if key not in newest:
            newest[key] = ArrivalOut(
                bank=event.bank,
                kind=event.account_kind,
                identifier=event.identifier,
                month=event.month,
                at=event.at,
            )
    return list(newest.values())


def _problems(conn: sqlite3.Connection, today: date) -> list[ProblemOut]:
    since = (today - timedelta(days=PROBLEM_DAYS)).isoformat()
    return [
        ProblemOut(kind=e.kind, outcome=e.outcome, bank=e.bank, at=e.at)
        for e in inbox_store.events(conn, limit=50)
        if e.outcome in PROBLEMS and e.at >= since
    ]
