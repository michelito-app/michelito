"""The demo's own routes: session (create the copy), sample statement, feedback, usage and events.

They all write, so they need `X-Michelito: 1` (the board's middleware checks it). None stores the
IP or the `demo_id`: the IP only counts copies per day in memory (`CopyStore`) and the cookie only
picks the copy and the per-copy caps (also in memory). Visitor-facing text comes from the catalog
(`michelito.i18n`, `demo.*`).
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from michelito.demo import feedback_store, network, sample
from michelito.demo.copies import CopyStore, DemoFull
from michelito.i18n import t

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
log = logging.getLogger(__name__)
# Key events that are counted (per day, with nothing about the visitor): method, path and name.
_EVENTS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("POST", re.compile(r"/api/budget/activate"), "budget_activated"),
    ("POST", re.compile(r"/api/reserves"), "reserve_created"),
    ("PATCH", re.compile(r"/api/transactions"), "multi_select"),
    ("POST", re.compile(r"/api/log/\d+/undo"), "undo"),
)


def event_of(method: str, path: str, status: int) -> str | None:
    """The key event of a request that succeeded, if it is one."""
    if not 200 <= status < 300:
        return None
    return next((name for m, rx, name in _EVENTS if m == method and rx.fullmatch(path)), None)


@dataclass(frozen=True)
class Hooks:
    """What the demo routes need from `demo.app`."""

    provider: Any  # DemoProvider (not imported: avoids the cycle)
    store: CopyStore
    feedback: feedback_store.Feedback
    opinions: Any  # PerCopy
    samples: Any  # PerCopy
    visits: Any  # PerCopy
    events: Any  # PerCopy (interface events, apart from the visits)
    today: Callable[[], date]
    proxies: tuple[network.Network, ...] = ()


class OpinionBody(BaseModel):
    text: str = Field(max_length=feedback_store.TEXT_MAX)
    email: str | None = Field(default=None, max_length=feedback_store.EMAIL_MAX)
    page: str | None = Field(default=None, max_length=feedback_store.PAGE_MAX)
    width: int | None = None
    version: str | None = Field(default=None, max_length=feedback_store.VERSION_MAX)
    ref: str | None = Field(default=None, max_length=64)


class VisitBody(BaseModel):
    screen: str = Field(max_length=feedback_store.PAGE_MAX)


# Events only the interface sees (e.g. copying to the clipboard never reaches the server).
CLIENT_EVENTS = frozenset({"copy_for_claude"})


class EventBody(BaseModel):
    event: str = Field(max_length=40)


class SampleOut(BaseModel):
    balanced: bool
    status: str
    detail: str | None
    transactions: int
    account: str
    period_start: str
    period_end: str
    months: list[str]


def _copy_id(request: Request, hooks: Hooks) -> str:
    """The request's copy; 401 if it has none (nothing is written without a session)."""
    copy_id = request.cookies.get(hooks.provider.cookie)
    if copy_id is None or hooks.store.workspace(copy_id) is None:
        raise HTTPException(401, t("demo.no_session"))
    return copy_id


def _count(hooks: Hooks, kind: str, key: str) -> None:
    """A counter never brings the response down."""
    try:
        hooks.feedback.count(kind, key)
    except Exception:
        log.exception("could not count %s %s", kind, key)


def _refused(exc: DemoFull) -> JSONResponse:
    if exc.reason == "full":
        return JSONResponse({"detail": t("demo.full")}, status_code=503)
    detail = t("demo.restarts") if exc.reason == "restart" else t("demo.too_many_copies")
    return JSONResponse({"detail": detail}, status_code=429)


def register(app: FastAPI, connection: Connection, hooks: Hooks) -> None:
    @app.exception_handler(sqlite3.OperationalError)
    def database_error(request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        """The copy reached its size cap (`PRAGMA max_page_count`): 507, with a way out."""
        if "full" in str(exc):
            return JSONResponse({"detail": t("demo.copy_full")}, status_code=507)
        log.exception("database error in %s", request.url.path, exc_info=exc)
        return JSONResponse({"detail": t("demo.internal_error")}, status_code=500)

    @app.post("/api/demo/session")
    def post_session(request: Request) -> Response:
        """Creates the visitor's copy (if they have no live one) and sets its cookie."""
        if hooks.provider.has_session(request):
            return JSONResponse({"created": False})
        network.warn_unconfigured_proxy(request, hooks.proxies)
        quotas = network.quota_keys(network.client_ip(request, hooks.proxies))
        try:
            copy_id = hooks.store.create(quotas)
        except DemoFull as exc:
            return _refused(exc)
        response = JSONResponse({"created": True}, status_code=201)
        hooks.provider.set_cookie(response, copy_id)
        _count(hooks, "copy", "created")
        return response

    @app.post("/api/demo/restart")
    def post_restart(request: Request) -> Response:
        """ "Start over": replaces the visitor's copy with a new one from the template."""
        copy_id = _copy_id(request, hooks)
        quotas = network.quota_keys(network.client_ip(request, hooks.proxies))
        try:
            fresh = hooks.store.restart(copy_id, quotas)
        except DemoFull as exc:
            return _refused(exc)
        for limits in (hooks.opinions, hooks.samples, hooks.visits, hooks.events):
            limits.transfer(copy_id, fresh)
        response = JSONResponse({"created": True}, status_code=201)
        hooks.provider.set_cookie(response, fresh)
        return response

    @app.post("/api/demo/sample-statement")
    def post_sample(request: Request) -> SampleOut:
        """Imports the next cut of the sample card (see `demo.sample`)."""
        copy_id = _copy_id(request, hooks)
        if not hooks.samples.take(copy_id):
            raise HTTPException(429, t("demo.samples_used"))
        with connection() as conn:
            result = sample.import_next(conn, hooks.today())
        _count(hooks, "event", "sample_statement")
        return SampleOut(
            balanced=result.balanced,
            status=result.status,
            detail=result.detail,
            transactions=result.transactions,
            account=result.account,
            period_start=result.period_start.isoformat(),
            period_end=result.period_end.isoformat(),
            months=result.months,
        )

    @app.post("/api/feedback", status_code=201)
    def post_opinion(request: Request, body: OpinionBody) -> dict[str, bool]:
        copy_id = _copy_id(request, hooks)
        opinion = feedback_store.Opinion(
            body.text, body.email, body.page, body.width, body.version, body.ref
        )
        try:
            cleaned = feedback_store.clean(opinion)
        except feedback_store.InvalidOpinion as exc:
            raise HTTPException(422, str(exc)) from None
        if not hooks.opinions.take(copy_id):
            raise HTTPException(429, t("demo.feedback_used"))
        try:
            hooks.feedback.save(cleaned)
        except feedback_store.FeedbackFull as exc:
            raise HTTPException(503, t("demo.retry_later", reason=exc)) from None
        return {"saved": True}

    @app.post("/api/usage", status_code=204)
    def post_visit(request: Request, body: VisitBody) -> Response:
        """Counts a visit to a screen (only the screen and the day; it stays in memory until the
        next flush). Past the per-copy cap, it is silently ignored."""
        copy_id = _copy_id(request, hooks)
        if hooks.visits.take(copy_id):
            _count(hooks, "visit", feedback_store.screen(body.screen))
        return Response(status_code=204)

    @app.post("/api/demo/event", status_code=204)
    def post_event(request: Request, body: EventBody) -> Response:
        """Counts an interface event (`CLIENT_EVENTS`; only the name and the day). Past the
        per-copy cap (`events`), it is silently ignored."""
        if body.event not in CLIENT_EVENTS:
            raise HTTPException(422, t("demo.unknown_event"))
        copy_id = _copy_id(request, hooks)
        if hooks.events.take(copy_id):
            _count(hooks, "event", body.event)
        return Response(status_code=204)
