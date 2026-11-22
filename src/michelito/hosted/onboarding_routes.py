"""Hosted mode's upload and onboarding routes: the gate, the processing screen, the first review
and the checklist (see `hosted.uploads`, `hosted.jobs` and `hosted.onboarding`).

- `POST /api/uploads` (`{"files": [{"name", "data"}]}`, `data` in base64): starts a job and
  answers at once; the files are processed in a background thread. Base64 in JSON instead of a
  multipart form: Starlette's form parser spools big files to a temporary file on disk, and an
  uploaded PDF must never touch the disk.
- `GET /api/uploads/{id}` (and `/latest`): the job's per-file states, polled by the screen.
- `POST /api/uploads/{id}/password` (`{"bank", "password"}`): tries that bank's password on
  every locked file of the job, **within this request**: the password lives only in this
  request's variables, is never logged, stored or echoed (the body is read by hand, so not even a
  validation error can repeat it).
- `POST /api/banks/requests` ("notify me when it is supported"): one more for that bank's counter.
- `GET /api/onboarding`, `GET /api/onboarding/merchants`, `PUT /api/onboarding/merchants/review`
  and `PUT /api/onboarding/flags/{flag}`.
- `POST /share-target` (the installed app's share target) and `POST /api/uploads/shared`.

Every database access goes through `connection()` (the session's own database). Every route but
`/share-target` needs a session; every write needs `X-Michelito: 1`.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import sqlite3
import unicodedata
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from michelito.analysis import changelog
from michelito.analysis.spending import Movement
from michelito.demo import network
from michelito.hosted import mailbox, onboarding, pdf_worker, uploads
from michelito.hosted.guard import widest
from michelito.hosted.jobs import QUEUED, FileState, Job, Jobs
from michelito.hosted.limits import Window
from michelito.hosted.routes import ERROR_HEADER, current
from michelito.hosted.shares import Shares, allowed_origin, parse_form
from michelito.hosted.store import Store
from michelito.i18n import t

log = logging.getLogger(__name__)
DAY = 24 * 3600
MB = 1024 * 1024
CENT = Decimal("0.01")
NAME_MAX = 120
DEFAULT_NAME = "statement.pdf"
SHARE_PATH = "/share-target"
# The banks whose statements are read (the password prompt offers them).
SUPPORTED_BANKS = ("popular", "bhd", "banreservas")
# "notify me when it is supported": a fixed list, so the counter never holds free text.
REQUESTABLE_BANKS = (
    "scotiabank",
    "santa_cruz",
    "apap",
    "cibao",
    "banesco",
    "promerica",
    "bdi",
    "caribe",
    "vimenca",
    "lafise",
    "ademi",
    "lopez_de_haro",
    "other",
)

Flag = Literal["first_review_closed", "checklist_dismissed"]
Connect = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], tuple[Movement, ...]]


@dataclass(frozen=True)
class UploadCaps:
    """Upload limits: per upload (`files_per_upload`, `file_bytes`, `upload_bytes`), per account
    (`uploads_per_hour`, `passwords_per_window` in `password_window` seconds,
    `bank_requests_per_day`) and per network for shares (`shares_per_hour`)."""

    files_per_upload: int = 12
    file_bytes: int = 8 * MB
    upload_bytes: int = 24 * MB
    uploads_per_hour: int = 10
    passwords_per_window: int = 10
    password_window: float = 15 * 60.0
    bank_requests_per_day: int = 10
    shares_per_hour: int = 20
    max_pages: int = 50
    worker_memory: int = 512 * MB
    worker_seconds: float = 30.0
    worker_slots: int = 2  # PDFs read at once in the whole process
    share_bytes_per_network: int = 16 * MB

    @property
    def worker(self) -> pdf_worker.Limits:
        return pdf_worker.Limits(
            max_pages=self.max_pages,
            memory_bytes=self.worker_memory,
            cpu_seconds=max(1, int(self.worker_seconds)),
            wall_seconds=self.worker_seconds,
        )

    @property
    def body_limit(self) -> int:
        """The largest request body: the files in base64 (or a multipart share) plus room for
        what surrounds them."""
        return self.upload_bytes * 4 // 3 + 64 * 1024

    @property
    def base64_limit(self) -> int:
        """The longest base64 text of one file (checked before decoding it)."""
        return (self.file_bytes + 2) // 3 * 4


SECURE_SHARE_COOKIE = "__Host-share"
PLAIN_SHARE_COOKIE = "share"


@dataclass
class Hooks:
    store: Store
    caps: UploadCaps
    proxies: tuple[network.Network, ...]
    secure_cookie: bool = True
    jobs: Jobs = field(default_factory=Jobs)
    shares: Shares = field(default_factory=Shares)
    opened: set[int] = field(default_factory=set)  # accounts already past the gate

    def __post_init__(self) -> None:
        self.shares.per_source = self.caps.share_bytes_per_network


class ReadOut(BaseModel):
    bank: str
    kind: str
    identifier: str
    month: str
    transactions: int


class FileOut(BaseModel):
    id: int
    name: str
    state: str
    bank: str | None
    reads: list[ReadOut]


class TryOut(BaseModel):
    """The last password try: which bank, how many files it opened, how many stay locked."""

    bank: str
    opened: int
    left: int


class JobOut(BaseModel):
    id: str
    files: list[FileOut]
    done: bool
    squared: int
    misses: list[str]
    last_try: TryOut | None


class MissingOut(BaseModel):
    bank: str
    kind: str
    identifier: str
    month: str


class ChecklistOut(BaseModel):
    months: int
    accounts: int
    more_months_done: bool
    other_account_done: bool
    missing: list[MissingOut]
    visible: bool
    automate_done: bool


class OnboardingOut(BaseModel):
    open: bool
    landing: str | None
    checklist: ChecklistOut
    first_review: bool


class MerchantOut(BaseModel):
    merchant: str
    total: str
    count: int
    category: str
    category_id: int | None
    fingerprint: str
    status: Literal["pending", "reviewed", "rule"]


class MerchantBody(BaseModel):
    merchant: str = Field(max_length=200)


class BankBody(BaseModel):
    bank: str = Field(max_length=40)


class SharedFileOut(BaseModel):
    name: str
    size: int


class ShareBody(BaseModel):
    token: str = Field(max_length=64)


def job_out(job: Job) -> JobOut:
    files, misses = job.snapshot()
    tried = job.last_try
    return JobOut(
        id=job.id,
        files=[_file_out(f) for f in files],
        done=all(f.state not in ("queued", "reading") for f in files),
        squared=sum(1 for f in files if f.opened),
        misses=list(misses),
        last_try=None if tried is None else TryOut(bank=tried[0], opened=tried[1], left=tried[2]),
    )


def _file_out(item: FileState) -> FileOut:
    return FileOut(
        id=item.id,
        name=item.name,
        state=item.state,
        bank=item.bank,
        reads=[ReadOut(**vars(read)) for read in item.reads],
    )


def decode_files(raw: bytes, caps: UploadCaps) -> list[tuple[str, bytes]]:
    """The files of `POST /api/uploads`, checked against the limits (422/413 otherwise)."""
    try:
        payload = json.loads(raw)
        items = payload["files"]
        if not isinstance(items, list):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, t("onboarding.bad_request")) from None
    if not items:
        raise HTTPException(422, t("onboarding.no_files"))
    if len(items) > caps.files_per_upload:
        raise HTTPException(413, t("onboarding.too_many_files", count=caps.files_per_upload))
    files = []
    for item in items:
        name, data = _decoded(item, caps)
        if len(data) > caps.file_bytes:
            raise HTTPException(
                413, t("onboarding.file_too_large", megabytes=caps.file_bytes // MB)
            )
        files.append((name, data))
    if sum(len(data) for _, data in files) > caps.upload_bytes:
        raise HTTPException(
            413, t("onboarding.upload_too_large", megabytes=caps.upload_bytes // MB)
        )
    return files


def _decoded(item: Any, caps: UploadCaps) -> tuple[str, bytes]:
    if not isinstance(item, dict):
        raise HTTPException(422, t("onboarding.bad_file"))
    raw_name, data = item.get("name"), item.get("data")
    if not isinstance(raw_name, str) or not isinstance(data, str) or len(raw_name) > 1000:
        raise HTTPException(422, t("onboarding.bad_file"))
    name = clean_name(raw_name)
    if name is None:
        raise HTTPException(422, t("onboarding.bad_file"))
    if len(data) > caps.base64_limit:
        raise HTTPException(413, t("onboarding.file_too_large", megabytes=caps.file_bytes // MB))
    try:
        return name, base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, t("onboarding.bad_file")) from None


def strict_utf8(text: str) -> bool:
    """Whether the text encodes as UTF-8 as it is (no lone surrogates)."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def clean_name(name: str) -> str | None:
    """A file name fit to show and store: strict UTF-8 (None otherwise), no control or format
    characters, no folders, at most `NAME_MAX` characters (the extension kept)."""
    if not strict_utf8(name):
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    visible = "".join(c for c in base if unicodedata.category(c) not in ("Cc", "Cf", "Cs"))
    visible = " ".join(visible.split())
    if len(visible) > NAME_MAX:
        stem, dot, suffix = visible.rpartition(".")
        keep = f"{dot}{suffix}" if dot and len(suffix) <= 8 else ""
        visible = visible[: NAME_MAX - len(keep)] + keep
    return visible or DEFAULT_NAME


def password_body(raw: bytes) -> tuple[str, str]:
    """`(bank, password)`, read by hand: a malformed body gets a fixed message that never
    repeats what was sent."""
    try:
        payload = json.loads(raw)
        bank, password = payload["bank"], payload["password"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, t("onboarding.bad_request")) from None
    if not isinstance(password, str) or not 0 < len(password) <= 128:
        raise HTTPException(422, t("onboarding.bad_request"))
    if not strict_utf8(password):  # before anything can turn it into an error message
        raise HTTPException(422, t("onboarding.bad_request"))
    if bank not in SUPPORTED_BANKS:
        raise HTTPException(422, t("onboarding.unknown_bank"))
    return bank, password


# Before the first statement squares, only these answer (the rest: 403 `gate_closed`).
GATE_OPEN_PREFIXES = (
    "/api/auth/",
    "/api/uploads",
    "/api/onboarding",
    "/api/banks/requests",
)
# Google's callback too: a top-level navigation, it must always get its redirect back.
GATE_OPEN_PATHS = frozenset(
    {"/api/mode", "/api/health", "/api/account", "/api/invitations", mailbox.CALLBACK_PATH}
)
GATE_CODE = "gate_closed"


def gate_guard(hooks: Hooks) -> Callable[[Request, Connect], Response | None]:
    """The gate on the server: until the account has a statement that squared, every other
    `/api` route answers 403 with `X-Michelito-Error: gate_closed`. An account seen open is
    remembered (a gate never closes again)."""

    def guard(request: Request, connection: Connect) -> Response | None:
        path = request.url.path
        if not path.startswith("/api/") or path in GATE_OPEN_PATHS:
            return None
        if path.startswith(GATE_OPEN_PREFIXES):
            return None
        session = getattr(request.state, "hosted_session", None)
        if session is None:
            return None  # the provider already answered 401 where a session is needed
        account = session.account.id
        if account in hooks.opened:
            return None
        with connection() as conn:
            if onboarding.is_open(conn):
                hooks.opened.add(account)
                return None
        return JSONResponse(
            {"detail": t("onboarding.gate_closed")},
            status_code=403,
            headers={ERROR_HEADER: GATE_CODE},
        )

    return guard


def register(app: FastAPI, hooks: Hooks, connection: Connect, load_flow: LoadFlow) -> None:
    jobs, caps = hooks.jobs, hooks.caps
    upload_window = Window(caps.uploads_per_hour, 3600)
    password_window = Window(caps.passwords_per_window, caps.password_window)
    bank_window = Window(caps.bank_requests_per_day, DAY)
    share_window = Window(caps.shares_per_hour, 3600)
    share_cookie = SECURE_SHARE_COOKIE if hooks.secure_cookie else PLAIN_SHARE_COOKIE

    def mine(request: Request) -> list[tuple[str, int]]:
        return [(f"account:{current(request).account.id}", 1)]

    def settle(job: Job, item: FileState, password: str) -> bool:
        """Read one file and give it its final state; False if it stays locked. Whatever goes
        wrong, the file ends in a final state and the log gets only the error's class name
        (an exception's message could carry part of the file or of the password)."""
        try:
            return _settle(job, item, password)
        except Exception as exc:  # noqa: BLE001 - see above: never the message
            log.error("upload failed: %s", type(exc).__name__)
            job.set(item.id, state=uploads.UNREADABLE, data=None)
            return True

    def _settle(job: Job, item: FileState, password: str) -> bool:
        if item.data is None or not jobs.alive(job):  # dropped meanwhile
            job.set(item.id, state=uploads.UNREADABLE, data=None)
            return True
        examined = uploads.examine(item.data, password, caps.worker)
        if examined.state == uploads.LOCKED:
            job.set(item.id, state=uploads.LOCKED)
            return False
        state = examined.state
        if state == uploads.SQUARED:
            try:
                with connection() as conn:
                    state = uploads.store(conn, item.name, item.data, examined, datetime.now(UTC))
            except Exception as exc:  # noqa: BLE001 - only the class name is logged
                log.error("upload could not be stored: %s", type(exc).__name__)
                state = uploads.UNREADABLE
        else:
            uploads.log_failure(examined.fingerprint)
        reads = examined.reads if state in (uploads.SQUARED, uploads.DUPLICATE) else ()
        job.set(item.id, state=state, bank=examined.bank, reads=reads, data=None)
        return True

    def process(job: Job) -> None:
        for item in job.take(frozenset({QUEUED})):
            settle(job, item, "")
        if not jobs.alive(job):
            job.evict()

    def start(request: Request, files: list[tuple[str, bytes]]) -> JobOut:
        if not upload_window.take(mine(request)):
            raise HTTPException(429, t("onboarding.rate_limited"))
        job = jobs.create(current(request).account.id, files)
        jobs.run(job, process)
        return job_out(job)

    def owned(request: Request, job_id: str) -> Job:
        job = jobs.get(current(request).account.id, job_id[:64])
        if job is None:
            raise HTTPException(404, t("onboarding.unknown_job"))
        return job

    @app.post("/api/uploads", status_code=202)
    async def post_upload(request: Request) -> JobOut:
        current(request)
        files = decode_files(await request.body(), caps)
        return start(request, files)

    @app.get("/api/uploads/latest")
    def get_latest_upload(request: Request) -> JobOut | None:
        job = jobs.latest(current(request).account.id)
        return None if job is None else job_out(job)

    @app.get("/api/uploads/{job_id}")
    def get_upload(job_id: str, request: Request) -> JobOut:
        return job_out(owned(request, job_id))

    @app.post("/api/uploads/{job_id}/password")
    async def post_password(job_id: str, request: Request) -> JobOut:
        job = owned(request, job_id)
        bank, password = password_body(await request.body())
        if not password_window.take(mine(request)):
            raise HTTPException(429, t("onboarding.password_rate_limited"))

        def work() -> None:
            chosen = job.take(frozenset({uploads.LOCKED}))
            if not chosen:
                raise HTTPException(409, t("onboarding.no_locked"))
            opened = sum(settle(job, item, password) for item in chosen)
            files, misses = job.snapshot()
            kept = tuple(b for b in misses if b != bank)
            job.set_misses(kept if opened else (*kept, bank))
            job.set_last_try(bank, opened, sum(1 for f in files if f.state == uploads.LOCKED))

        await anyio.to_thread.run_sync(work)
        return job_out(job)

    @app.post("/api/uploads/shared", status_code=202)
    def post_shared(body: ShareBody, request: Request) -> JobOut:
        """The explicit "Import" of a share (the screen never calls it on its own)."""
        current(request)
        files = hooks.shares.take(body.token, request.cookies.get(share_cookie))
        if not files:
            raise HTTPException(404, t("onboarding.unknown_share"))
        return start(request, list(files))

    @app.post("/api/uploads/shared/peek")
    def post_shared_peek(body: ShareBody, request: Request) -> list[SharedFileOut]:
        """The shared files' names and sizes, to ask before importing; uses nothing up."""
        current(request)
        found = hooks.shares.peek(body.token, request.cookies.get(share_cookie))
        if not found:
            raise HTTPException(404, t("onboarding.unknown_share"))
        return [SharedFileOut(name=name, size=size) for name, size in found]

    @app.post("/api/uploads/shared/discard", status_code=204)
    def post_shared_discard(body: ShareBody, request: Request) -> Response:
        current(request)
        hooks.shares.take(body.token, request.cookies.get(share_cookie))
        return Response(status_code=204)

    @app.post(SHARE_PATH)
    async def post_share_target(request: Request) -> Response:
        """No session is needed (nor opened): the files wait in memory for the upload screen."""
        fetch_site = request.headers.get("sec-fetch-site")
        origin = request.headers.get("origin")
        if not allowed_origin(fetch_site, origin, request.headers.get("host", "")):
            return Response(status_code=403)
        source = network.quota_keys(network.client_ip(request, hooks.proxies))
        if not share_window.take(source):
            return RedirectResponse("/import", status_code=303)
        body = await request.body()
        files = tuple(
            (name, data)
            for name, data in parse_form(
                request.headers.get("content-type", ""), body, caps.files_per_upload
            )
            if len(data) <= caps.file_bytes
        )
        held = request.cookies.get(share_cookie)
        made = hooks.shares.put(files, widest(source), held) if files else None
        if made is None:
            return RedirectResponse("/import", status_code=303)
        token, browser = made
        response = RedirectResponse(f"/import#share={token}", status_code=303)
        response.set_cookie(
            share_cookie,
            browser,
            max_age=int(hooks.shares.ttl),
            httponly=True,
            secure=hooks.secure_cookie,
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/api/banks/requests", status_code=204)
    def post_bank_request(body: BankBody, request: Request) -> Response:
        current(request)
        if body.bank not in REQUESTABLE_BANKS:
            raise HTTPException(422, t("onboarding.unknown_bank"))
        if bank_window.take(mine(request)):
            hooks.store.count_bank_request(body.bank)
        return Response(status_code=204)

    @app.get("/api/onboarding")
    def get_onboarding(request: Request) -> OnboardingOut:
        current(request)
        with connection() as conn:
            state = onboarding.build_state(conn, load_flow(conn))
        checklist = state.checklist
        return OnboardingOut(
            open=state.open,
            landing=state.landing,
            first_review=state.first_review,
            checklist=ChecklistOut(
                months=checklist.months,
                accounts=checklist.accounts,
                more_months_done=checklist.more_months_done,
                other_account_done=checklist.other_account_done,
                missing=[MissingOut(**vars(m)) for m in checklist.missing],
                visible=checklist.visible,
                automate_done=checklist.automate_done,
            ),
        )

    def merchants_out(conn: sqlite3.Connection) -> list[MerchantOut]:
        found = onboarding.top_merchants(conn, load_flow(conn))
        return [
            MerchantOut(
                merchant=m.merchant,
                total=str(m.total.quantize(CENT)),
                count=m.count,
                category=m.category,
                category_id=m.category_id,
                fingerprint=m.fingerprint,
                status=onboarding.merchant_status(conn, m),  # type: ignore[arg-type]
            )
            for m in found
        ]

    @app.get("/api/onboarding/merchants")
    def get_merchants(request: Request) -> list[MerchantOut]:
        current(request)
        with connection() as conn:
            return merchants_out(conn)

    @app.put("/api/onboarding/merchants/review")
    def put_merchant_review(body: MerchantBody, request: Request) -> list[MerchantOut]:
        """The "Correct" button: every transaction of that merchant counts as reviewed."""
        current(request)
        with connection() as conn:
            found = onboarding.top_merchants(conn, load_flow(conn))
            chosen = next((m for m in found if m.merchant == body.merchant), None)
            if chosen is None:
                raise HTTPException(404, t("onboarding.unknown_merchant"))
            with (
                conn,
                changelog.track(
                    conn,
                    "reviewed",
                    "merchant",
                    chosen.merchant,
                    chosen.merchant,
                    before=t("web.to_review"),
                    after=t("web.review.reviewed"),
                    merchant=chosen.merchant,
                    fingerprints=chosen.fingerprints,
                ),
            ):
                onboarding.mark_reviewed(conn, chosen.fingerprints)
            return merchants_out(conn)

    @app.put("/api/onboarding/flags/{flag}", status_code=204)
    def put_flag(
        flag: Literal["first_review_closed", "checklist_dismissed"], request: Request
    ) -> Response:
        current(request)
        label = t(f"onboarding.log.{flag}")
        with (
            connection() as conn,
            conn,
            changelog.track(
                conn,
                "onboarding",
                # The log's target types are fixed by its schema; the cards are about the
                # categories of the top merchants, so they are filed under "category".
                "category",
                flag,
                label,
                before=t("onboarding.log.shown"),
                after=t("onboarding.log.hidden"),
            ),
        ):
            onboarding.set_flag(conn, flag)
        return Response(status_code=204)
