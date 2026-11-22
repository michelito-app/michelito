"""Hosted mode's own routes: sign-in, sessions and devices, step-up and account deletion.

All of them are under `/api/auth/` (plus `/api/account` and `/api/invitations`); every write
still needs `X-Michelito: 1` (the board's middleware). Asking for a code and checking one take at
least `floor` seconds whatever happens, so their timing says nothing about the email. No
response, log line or error message carries a code, a link token or a session token; the session
token only goes into the `Set-Cookie` header.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from michelito.demo import network
from michelito.hosted.auth import AuthError, SignIn, normalize, valid_email
from michelito.hosted.store import Account, Session
from michelito.i18n import t

T = TypeVar("T")
_STATUS = {
    "code": (400, "hosted.wrong_code"),
    "rate": (429, "hosted.rate_limited"),
    "mail": (503, "hosted.mail_unavailable"),
    "step_up": (403, "hosted.step_up_required"),
    "email": (422, "hosted.bad_email"),
    "member": (409, "hosted.already_member"),
    "send": (503, "hosted.mail_unavailable"),
}


class EmailBody(BaseModel):
    email: str = Field(max_length=320)


class VerifyBody(BaseModel):
    email: str = Field(max_length=320)
    code: str = Field(max_length=16)


class LinkBody(BaseModel):
    token: str = Field(max_length=128)


class CodeBody(BaseModel):
    code: str = Field(max_length=16)


class DeviceOut(BaseModel):
    id: int
    browser: str
    os: str
    last_seen: str  # a date (YYYY-MM-DD, UTC): never the time, never the IP
    created: str
    current: bool


class MeOut(BaseModel):
    email: str
    step_up_fresh: bool


@dataclass(frozen=True)
class Hooks:
    """What the routes need from `hosted.app`."""

    service: SignIn
    cookie: str
    secure_cookie: bool
    floor: float
    proxies: tuple[network.Network, ...]
    device_cookie: str
    # Called with the account's id when its sessions end here (sign out, sign out everywhere,
    # deleting the account): what it holds in memory (upload jobs) is dropped.
    on_leave: Callable[[int], None] | None = None
    # Called with the account just before it is deleted (its key still exists): revoking what
    # it granted elsewhere (its Gmail). Best effort: it never raises.
    on_delete: Callable[[Account], None] | None = None


# Machine-readable reason of a refusal, for the interface (the `detail` is for people).
ERROR_HEADER = "X-Michelito-Error"
_CODES = {"step_up": "step_up_required"}


def failure(error: AuthError) -> HTTPException:
    status, key = _STATUS.get(error.kind, (400, "hosted.wrong_code"))
    reason = _CODES.get(error.kind)
    return HTTPException(status, t(key), headers={ERROR_HEADER: reason} if reason else None)


def current(request: Request) -> Session:
    """The request's session (the provider put it there); 401 without one."""
    session = getattr(request.state, "hosted_session", None)
    if session is None:
        raise HTTPException(401, t("hosted.signed_out"))
    return session


def _day(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).date().isoformat()


def register(app: FastAPI, hooks: Hooks) -> None:
    service = hooks.service

    def source(request: Request) -> tuple[tuple[str, int], ...]:
        """The requester's IP buckets: an IPv4, or an IPv6's /64, /56 and /48 (wider limits),
        so rotating addresses inside one allocation does not multiply the quotas."""
        return network.quota_keys(network.client_ip(request, hooks.proxies))

    def trusted(request: Request, email: str) -> bool:
        """A session of that same account, or a browser that already signed in to it."""
        session: Session | None = getattr(request.state, "hosted_session", None)
        if session is not None and session.account.email == normalize(email):
            return True
        return service.knows_device(request.cookies.get(hooks.device_cookie), email)

    async def padded(work: Callable[..., T], *args: Any) -> T:
        """Run `work` in a thread and answer no sooner than `floor` seconds after starting."""
        started = time.perf_counter()
        try:
            return await anyio.to_thread.run_sync(work, *args)
        except AuthError as error:
            raise failure(error) from None
        finally:
            remaining = hooks.floor - (time.perf_counter() - started)
            if remaining > 0:
                await anyio.sleep(remaining)

    def set_session(response: Response, token: str) -> None:
        response.set_cookie(
            hooks.cookie,
            token,
            max_age=service.policy.absolute,
            httponly=True,
            secure=hooks.secure_cookie,
            samesite="lax",
            path="/",
        )

    def clear_session(response: Response) -> None:
        response.delete_cookie(
            hooks.cookie, path="/", secure=hooks.secure_cookie, httponly=True, samesite="lax"
        )

    def signed_in(request: Request, token: str, email: str) -> tuple[str, str]:
        """In the thread: replace this browser's earlier session (not left behind) and record
        it as a known device of the account. Returns (session token, device token)."""
        previous = getattr(request.state, "hosted_session", None)
        if previous is not None:
            service.sign_out(previous)
        return token, service.remember_device(email)

    def cookies(tokens: tuple[str, str]) -> Response:
        token, device = tokens
        response = Response(status_code=204)
        set_session(response, token)
        # A known device: later requests for this email skip the anonymous per-email limits
        # (never the absolute send ceiling nor the 5 attempts per code).
        response.set_cookie(
            hooks.device_cookie,
            device,
            max_age=service.policy.known_device_ttl,
            httponly=True,
            secure=hooks.secure_cookie,
            samesite="lax",
            path="/",
        )
        return response

    # The async handlers do no database work themselves: everything runs in `padded`'s thread.

    @app.post("/api/auth/code", status_code=202)
    async def post_code(body: EmailBody, request: Request) -> dict[str, str]:
        email = normalize(body.email)
        if not valid_email(email):
            raise HTTPException(422, t("hosted.bad_email"))
        where = source(request)

        def work() -> None:
            service.request_code(email, where, trusted(request, email))

        await padded(work)
        return {"status": "sent"}

    @app.post("/api/auth/verify")
    async def post_verify(body: VerifyBody, request: Request) -> Response:
        agent = request.headers.get("user-agent")
        where = source(request)

        def work() -> tuple[str, str]:
            # Only a known device of that account skips the email's hourly check block.
            known = service.knows_device(request.cookies.get(hooks.device_cookie), body.email)
            token = service.verify(body.email, body.code, agent, where, known)
            return signed_in(request, token, body.email)

        return cookies(await padded(work))

    @app.post("/api/auth/link/peek")
    async def post_link_peek(body: LinkBody, request: Request) -> dict[str, str]:
        """Which (masked) email a desktop link is for, without using it."""
        email = await padded(service.peek_link, body.token, source(request))
        return {"email": email}

    @app.post("/api/auth/link")
    async def post_link(body: LinkBody, request: Request) -> Response:
        agent = request.headers.get("user-agent")
        where = source(request)

        def work() -> tuple[str, str]:
            token, email = service.verify_link(body.token, agent, where)
            return signed_in(request, token, email)

        return cookies(await padded(work))

    @app.get("/api/auth/me")
    def get_me(request: Request) -> MeOut:
        session = current(request)
        return MeOut(email=session.account.email, step_up_fresh=service.fresh(session))

    @app.get("/api/auth/devices")
    def get_devices(request: Request) -> list[DeviceOut]:
        session = current(request)
        return [
            DeviceOut(
                id=item.id,
                browser=item.browser,
                os=item.os,
                last_seen=_day(item.last_seen_at),
                created=_day(item.created_at),
                current=item.id == session.id,
            )
            for item in service.store.sessions_of(session.account.id)
        ]

    def left(session: Session) -> None:
        if hooks.on_leave is not None:
            hooks.on_leave(session.account.id)

    @app.post("/api/auth/sign-out", status_code=204)
    def post_sign_out(request: Request) -> Response:
        session = current(request)
        service.sign_out(session)
        left(session)
        response = Response(status_code=204)
        clear_session(response)
        return response

    @app.post("/api/auth/sign-out-everywhere", status_code=204)
    def post_sign_out_everywhere(request: Request) -> Response:
        session = current(request)
        try:
            service.sign_out_everywhere(session)
        except AuthError as error:
            raise failure(error) from None
        left(session)
        response = Response(status_code=204)
        clear_session(response)
        return response

    @app.post("/api/auth/step-up/code", status_code=202)
    async def post_step_up_code(request: Request) -> dict[str, str]:
        session = current(request)
        await padded(service.request_step_up, session, source(request))
        return {"status": "sent"}

    @app.post("/api/auth/step-up/verify", status_code=204)
    async def post_step_up_verify(body: CodeBody, request: Request) -> Response:
        session = current(request)
        await padded(service.verify_step_up, session, body.code, source(request))
        return Response(status_code=204)

    @app.delete("/api/account", status_code=204)
    def delete_account(request: Request) -> Response:
        """Delete the account (fresh verification required): its data key is destroyed first,
        so its database is unreadable on this server from then on (and in backups once the
        older backups of `accounts.db` expire); then its files."""
        session = current(request)
        try:
            service.delete_account(session, before=hooks.on_delete)
        except AuthError as error:
            raise failure(error) from None
        left(session)
        response = Response(status_code=204)
        clear_session(response)
        return response

    @app.post("/api/invitations", status_code=202)
    def post_invitation(body: EmailBody, request: Request) -> dict[str, str]:
        """People inviting people: off by default (`Policy.user_invitations`), with no UI."""
        session = current(request)
        if not service.policy.user_invitations:
            raise HTTPException(403, t("hosted.invitations_off"))
        try:
            service.invite(body.email, invited_by=session.account.id)
        except AuthError as error:
            if error.kind != "member":  # an existing member is not revealed to other people
                raise failure(error) from None
        return {"status": "sent"}
