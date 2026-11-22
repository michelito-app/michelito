"""Hosted mode's connected-Gmail routes (see `hosted.mailbox`). All of them under `/api/mailbox`
(`/api/gmail` is the local board's, blocked in hosted mode); writes need `X-Michelito: 1`.

- `GET /api/mailbox`: whether the feature is on (`available`: a Google client is configured),
  and the connection: its address, when it was made and last read, its problem (`reconnect`,
  `failed`), how many merchant emails were read and whether a read is running. Never the token.
- `POST /api/mailbox/google/start` → `{url}`: Google's consent page for `gmail.readonly`, with
  PKCE and a fresh `state`. The state's hash, the session it belongs to and the PKCE verifier
  stay **in memory** for 10 minutes (a few per account), never in a database or a cookie.
- `GET /api/mailbox/google/callback`: where Google sends the browser back (a top-level
  navigation, so the `SameSite=Lax` session cookie comes along; reachable without one, to
  answer with a redirect instead of an error). The state must exist, be fresh and belong to
  the same account **and** session; it is used once. Then the code is exchanged with the
  verifier, the scope checked (a person may untick it), the address fetched and the refresh
  token stored sealed (`mailbox.store`), and the first read (12 months) starts in the
  background. It always answers 303 to `/settings?gmail=<outcome>#mailbox`.
- `DELETE /api/mailbox`: revoke the token at Google (best effort, reported) and delete it.
- `POST /api/mailbox/sync`: read now, in the background (202); 429 while a read runs or for a
  minute after one finished.

Reads of one account never overlap (`Hooks.lock`, shared with the hourly `Sweeper`). Nothing
about the mailbox (address, message, token, Google's answer) is ever logged: only outcomes and
error class names.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from michelito import db
from michelito.hosted import mailbox
from michelito.hosted.auth import SignIn
from michelito.hosted.inbox_store import Sealer, SealError
from michelito.hosted.mailbox import Google, GoogleClient, Outcome
from michelito.hosted.routes import current
from michelito.hosted.store import Account, Session
from michelito.i18n import t
from michelito.web.workspace import CURRENT, Workspace

log = logging.getLogger(__name__)

Connect = Callable[[], AbstractContextManager[sqlite3.Connection]]

STATE_SECONDS = 10 * 60.0
PENDING_PER_ACCOUNT = 3
SYNC_PAUSE = 60.0  # seconds after a read before "read now" is accepted again
SWEEP_EVERY = 3600.0
DISCONNECT_WAIT = 30.0  # seconds a disconnection waits for a running read to stop
RETURN_PATH = "/settings"
RETURN_ANCHOR = "mailbox"
PARAM_MAX = 2048  # longer than any code or state Google sends
Result = str  # one of OUTCOMES
OUTCOMES = ("connected", "denied", "scope", "failed", "expired")


@dataclass(frozen=True)
class Pending:
    """A consent started in Settings and not finished yet."""

    account_id: int
    session_id: int
    verifier: str = field(repr=False)
    expires: float


@dataclass
class Hooks:
    service: SignIn
    client: GoogleClient | None
    google: Google
    redirect_uri: str
    background: bool = True  # read in a thread (False: inline, for tests)
    clock: Callable[[], float] = time.time
    _pending: dict[str, Pending] = field(default_factory=dict, repr=False)
    _locks: dict[int, threading.Lock] = field(default_factory=dict)
    _queued: set[int] = field(default_factory=set)
    _finished: dict[int, float] = field(default_factory=dict)
    _cancelled: set[int] = field(default_factory=set)  # disconnecting: running reads stop
    _guard: threading.Lock = field(default_factory=threading.Lock)

    @property
    def available(self) -> bool:
        return self.client is not None

    def lock(self, account_id: int) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(account_id, threading.Lock())

    # The single-use states.

    def begin(self, account_id: int, session_id: int) -> tuple[str, str]:
        """A new `(state, verifier)` for this session; the oldest pending ones of the account
        beyond `PENDING_PER_ACCOUNT` are dropped."""
        state, verifier = mailbox.new_state(), mailbox.new_verifier()
        now = self.clock()
        with self._guard:
            self._prune(now)
            mine = [key for key, p in self._pending.items() if p.account_id == account_id]
            for key in mine[: max(0, len(mine) - PENDING_PER_ACCOUNT + 1)]:  # oldest first
                del self._pending[key]
            self._pending[mailbox.state_key(state)] = Pending(
                account_id, session_id, verifier, now + STATE_SECONDS
            )
        return state, verifier

    def _prune(self, now: float) -> None:
        """Forget states expired a while ago (a just-expired one still says "expired")."""
        for key in [k for k, p in self._pending.items() if p.expires + STATE_SECONDS < now]:
            del self._pending[key]

    def claim(self, state: str, account_id: int, session_id: int) -> Pending | Result:
        """The pending consent of `state`, used up whatever the answer; or why not."""
        with self._guard:
            found = self._pending.pop(mailbox.state_key(state), None)
        if found is None or (found.account_id, found.session_id) != (account_id, session_id):
            return "failed"
        if found.expires < self.clock():
            return "expired"
        return found

    # Reads.

    def busy(self, account_id: int) -> bool:
        with self._guard:
            queued = account_id in self._queued
        return queued or self.lock(account_id).locked()

    def recent(self, account_id: int) -> bool:
        with self._guard:
            finished = self._finished.get(account_id)
        return finished is not None and self.clock() - finished < SYNC_PAUSE

    def read(self, account: Account, workspace: Workspace, wait: bool) -> Outcome | None:
        """Read the account's mailbox under its lock (None: no client, or busy and not
        `wait`). Never raises; only the error's class name is logged."""
        try:
            if self.client is None:
                return None
            lock = self.lock(account.id)
            if not lock.acquire(blocking=wait):
                return None
            try:
                return self._read(account.id, workspace, self.client)
            finally:
                with self._guard:
                    self._finished[account.id] = self.clock()
                    self._cancelled.discard(account.id)
                lock.release()
        finally:
            with self._guard:
                self._queued.discard(account.id)

    def cancelled(self, account_id: int) -> bool:
        with self._guard:
            return account_id in self._cancelled

    def _read(self, account_id: int, workspace: Workspace, client: GoogleClient) -> Outcome:
        try:
            assert workspace.key is not None
            with closing(db.connect(workspace.database, workspace.key)) as conn:
                return mailbox.sync(
                    conn,
                    Sealer.of(workspace.key),
                    client,
                    self.google,
                    stop=lambda: self.cancelled(account_id),
                )
        except Exception as exc:  # noqa: BLE001 - see `read`
            log.error("a connected mailbox could not be read: %s", type(exc).__name__)
            return "failed"

    def disconnect(self, account: Account, workspace: Workspace) -> bool:
        """Forget the account's token and revoke it at Google (best effort); True if Google
        confirmed. A running read is told to stop and waited for (at most `DISCONNECT_WAIT`
        seconds), so it adds nothing after this; no database stays open during the revoke."""
        with self._guard:
            self._cancelled.add(account.id)
        lock = self.lock(account.id)
        held = lock.acquire(timeout=DISCONNECT_WAIT)
        try:
            assert workspace.key is not None
            with closing(db.connect(workspace.database, workspace.key)) as conn:
                try:
                    refresh = mailbox.token(conn, Sealer.of(workspace.key))
                except SealError:
                    refresh = None
                with conn:
                    mailbox.forget(conn)
        finally:
            if held:  # otherwise the read still running clears it when it ends
                with self._guard:
                    self._cancelled.discard(account.id)
                lock.release()
        return _revoke(self.google, refresh) if refresh else False

    def revoke_account(self, account: Account) -> None:
        """Before an account is deleted (its key still exists): revoke its Gmail grant, if
        any. Best effort: it never stops the deletion; only the error's class is logged."""
        try:
            self.disconnect(account, self.service.workspace_of(account))
        except Exception as exc:  # noqa: BLE001 - see above
            log.warning("a deleted account's Gmail grant was not revoked: %s", type(exc).__name__)

    def later(self, account: Account, workspace: Workspace, wait: bool) -> None:
        """Read in a thread (inline without `background`)."""
        with self._guard:
            self._queued.add(account.id)
        if not self.background:
            self.read(account, workspace, wait)
            return
        threading.Thread(
            target=self.read,
            args=(account, workspace, wait),
            name="michelito-mailbox",
            daemon=True,
        ).start()


class MailboxOut(BaseModel):
    available: bool
    connected: bool
    address: str | None
    connected_at: str | None
    synced_at: str | None
    problem: str | None  # reconnect or failed
    receipts: int  # merchant emails read from the connected mailbox
    syncing: bool
    revoked: bool | None = None  # only after disconnecting: whether Google confirmed it


class StartOut(BaseModel):
    url: str


class StartedOut(BaseModel):
    started: bool


OFF = MailboxOut(
    available=False,
    connected=False,
    address=None,
    connected_at=None,
    synced_at=None,
    problem=None,
    receipts=0,
    syncing=False,
)


def _session_workspace() -> Workspace:
    found = CURRENT.get()
    if found is None or found.key is None:
        raise HTTPException(401, t("hosted.signed_out"))
    return found


def _status(conn: sqlite3.Connection, syncing: bool, available: bool = True) -> MailboxOut:
    found = mailbox.status(conn)
    return MailboxOut(
        available=available,
        connected=found is not None,
        address=found.address if found else None,
        connected_at=found.connected_at if found else None,
        synced_at=found.synced_at if found else None,
        problem=found.problem if found else None,
        receipts=mailbox.gmail_receipts(conn),
        syncing=syncing,
    )


def back(outcome: Result) -> RedirectResponse:
    """Settings, with the outcome to show once (the interface removes it from the address)."""
    chosen = outcome if outcome in OUTCOMES else "failed"
    return RedirectResponse(f"{RETURN_PATH}?gmail={chosen}#{RETURN_ANCHOR}", status_code=303)


def register(app: FastAPI, hooks: Hooks, connection: Connect) -> None:
    google = hooks.google

    def client() -> GoogleClient:
        if hooks.client is None:
            raise HTTPException(404, t("mailbox.off"))
        return hooks.client

    @app.get("/api/mailbox")
    def get_mailbox(request: Request) -> MailboxOut:
        session = current(request)
        if not hooks.available:
            return OFF
        with connection() as conn:
            return _status(conn, hooks.busy(session.account.id))

    @app.post("/api/mailbox/google/start")
    def post_start(request: Request) -> StartOut:
        session = current(request)
        found = client()
        state, verifier = hooks.begin(session.account.id, session.id)
        return StartOut(url=mailbox.authorization_url(found, hooks.redirect_uri, state, verifier))

    def connect(session: Session, found: GoogleClient, code: str, verifier: str) -> Result:
        """After the state checked out: the exchange, the scope, the address, the token."""
        try:
            granted = google.exchange(found, hooks.redirect_uri, code, verifier)
        except Exception as exc:  # noqa: BLE001 - Google's answer is never shown or logged
            log.warning("a Gmail authorization could not be exchanged: %s", type(exc).__name__)
            return "failed"
        if mailbox.SCOPE not in granted.scopes:
            _revoke(google, granted.refresh_token)  # useless without the scope
            return "scope"
        address: str | None = None
        try:
            address = google.mailbox(found, granted.refresh_token).address() or None
        except Exception as exc:  # noqa: BLE001 - the address is only shown; go on without
            log.warning("a connected mailbox's address was not read: %s", type(exc).__name__)
        workspace = _session_workspace()
        assert workspace.key is not None
        sealer = Sealer.of(workspace.key)
        try:
            with connection() as conn:
                replaced = _previous(conn, sealer)
                mailbox.ensure(conn)
                with conn:
                    mailbox.store(conn, sealer, granted.refresh_token, address)
        except Exception as exc:  # noqa: BLE001 - never leave a live token nobody keeps
            log.error("a Gmail connection could not be stored: %s", type(exc).__name__)
            _revoke(google, granted.refresh_token)
            return "failed"
        if replaced is not None and _other_mailbox(replaced, address):
            _revoke(google, replaced[0])
        hooks.later(session.account, workspace, wait=True)
        return "connected"

    @app.get(mailbox.CALLBACK_PATH)
    def get_callback(
        request: Request,
        code: str | None = Query(None, max_length=PARAM_MAX),
        state: str | None = Query(None, max_length=PARAM_MAX),
        error: str | None = Query(None, max_length=PARAM_MAX),
    ) -> RedirectResponse:
        session: Session | None = getattr(request.state, "hosted_session", None)
        found = hooks.client
        if session is None or found is None or not state:
            return back("failed")
        claimed = hooks.claim(state, session.account.id, session.id)
        if not isinstance(claimed, Pending):
            return back(claimed)
        if error:
            return back("denied" if error == "access_denied" else "failed")
        if not code:
            return back("failed")
        return back(connect(session, found, code, claimed.verifier))

    @app.delete("/api/mailbox")
    def delete_mailbox(request: Request) -> MailboxOut:
        """Works even with the feature off: a stored token is still forgotten and revoked."""
        session = current(request)
        revoked = hooks.disconnect(session.account, _session_workspace())
        with connection() as conn:
            out = _status(conn, hooks.busy(session.account.id), hooks.available)
        return out.model_copy(update={"revoked": revoked})

    @app.post("/api/mailbox/sync", status_code=202)
    def post_sync(request: Request) -> StartedOut:
        session = current(request)
        client()
        workspace = _session_workspace()
        account = session.account
        with connection() as conn:
            connected = mailbox.status(conn) is not None
        if not connected:
            raise HTTPException(409, t("mailbox.not_connected"))
        if hooks.busy(account.id):
            raise HTTPException(429, t("mailbox.busy"))
        if hooks.recent(account.id):
            raise HTTPException(429, t("mailbox.too_soon"))
        hooks.later(account, workspace, wait=False)
        return StartedOut(started=True)


def _previous(conn: sqlite3.Connection, sealer: Sealer) -> tuple[str, str | None] | None:
    """The token and address a new connection replaces (None if none, or it does not open)."""
    try:
        refresh = mailbox.token(conn, sealer)
    except SealError:
        return None
    found = mailbox.status(conn)
    return None if refresh is None or found is None else (refresh, found.address)


def _other_mailbox(replaced: tuple[str, str | None], address: str | None) -> bool:
    """Whether the replaced token is of another mailbox. Only then is it revoked: Google may
    tie the tokens of one person and client to one grant, so revoking the old token of the
    same mailbox could revoke the new one too (and Google retires old ones on its own)."""
    old = replaced[1]
    return old is not None and address is not None and old.lower() != address.lower()


def _revoke(google: Google, refresh: str) -> bool:
    try:
        return google.revoke(refresh)
    except Exception as exc:  # noqa: BLE001 - best effort: the token is deleted anyway
        log.warning("a Gmail token could not be revoked: %s", type(exc).__name__)
        return False


# The hourly read, without the person present.


def sweep(hooks: Hooks) -> tuple[int, int]:
    """Read every active account's connected mailbox once; returns (read, failed). An account
    that is busy is skipped (its read is running); one that fails never stops the others."""
    read = failed = 0
    if hooks.client is None:
        return read, failed
    service = hooks.service
    # This opens every active account's database once an hour, even those that never connected
    # Gmail: fine for the handful of accounts there are; with many, keep a list of connected
    # accounts in accounts.db instead.
    for account in service.store.active_accounts():
        try:
            workspace = service.workspace_of(account)
            assert workspace.key is not None
            with closing(db.connect(workspace.database, workspace.key)) as conn:
                found = mailbox.status(conn)
                # A refused token needs the person: it is not tried again until they reconnect.
                connected = found is not None and found.problem != "reconnect"
        except Exception as exc:  # noqa: BLE001 - see above
            log.error("an account could not be opened to read its mailbox: %s", type(exc).__name__)
            failed += 1
            continue
        if not connected:
            continue
        outcome = hooks.read(account, workspace, wait=False)
        if outcome == "read":
            read += 1
        elif outcome in ("failed", "reconnect"):
            failed += 1
    if read or failed:
        log.info("connected mailboxes read: %d, not read: %d", read, failed)
    return read, failed


class Sweeper:
    """Every `every` seconds, `sweep`. A daemon thread: it ends with the process."""

    def __init__(self, hooks: Hooks, every: float = SWEEP_EVERY) -> None:
        self.hooks = hooks
        self.every = every
        self._stop = threading.Event()
        threading.Thread(target=self._run, name="michelito-mailbox-sweeper", daemon=True).start()

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            try:
                sweep(self.hooks)
            except Exception as exc:  # noqa: BLE001 - the next hour tries again
                log.error("the mailbox sweep failed: %s", type(exc).__name__)

    def stop(self) -> None:
        self._stop.set()
