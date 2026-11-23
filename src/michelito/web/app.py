"""The board's local JSON API. It only listens on 127.0.0.1; see `create_app` for the defense."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, closing, contextmanager
from dataclasses import replace as dc_replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from michelito import config, db, holders, migrations_v19
from michelito.analysis import accounts as account_data
from michelito.analysis import (
    cash_activation,
    cash_box,
    catalog,
    changelog,
    ledger_store,
    links,
    rates,
    review_marks,
    spending,
)
from michelito.analysis import exchanges as exchange_math
from michelito.analysis import one_off_dismissals as dismissals
from michelito.analysis import recurring_marks as marks
from michelito.analysis.categories import KIND_LABELS, Kind
from michelito.analysis.spending import Movement
from michelito.hosted import inbox_store
from michelito.i18n import t
from michelito.web import accounts as accounts_view
from michelito.web import (
    batch_routes,
    budget_routes,
    cash_box_routes,
    cash_routes,
    dossier_routes,
    edit_log,
    insight_routes,
    installment_pick_routes,
    installment_routes,
    investment_routes,
    ledger_routes,
    live_routes,
    log_routes,
    pace_routes,
    receipt_routes,
    recurring_routes,
    report_routes,
    reserve_routes,
    review_routes,
    summary,
    transactions,
)
from michelito.web import categories as categories_view
from michelito.web import installments as installments_view
from michelito.web import interest as interest_view
from michelito.web import links as links_view
from michelito.web import one_offs as one_offs_view
from michelito.web import pending as pending_view
from michelito.web import receipts as receipts_view
from michelito.web.flow_cache import FlowCache
from michelito.web.schemas import (
    AccountOut,
    CandidateOut,
    CategoryBody,
    CategoryOut,
    CategoryPatch,
    DismissBody,
    DismissOut,
    EditBody,
    ExchangeBody,
    ExchangeOut,
    ExchangePatch,
    InterestOut,
    LegsBody,
    MonthOptionOut,
    OneOffSuggestionOut,
    PendingOut,
    PreviewBody,
    PreviewOut,
    RateBody,
    SavedRateOut,
    SummaryOut,
    TransactionsOut,
    TxOut,
)
from michelito.web.workspace import CURRENT, FixedProvider, Mode, Workspace

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Every method that writes needs `X-Michelito: 1`; `X-Michelito-Author` says who makes the change.
WRITE_HEADER = "X-Michelito"
AUTHOR_HEADER = "X-Michelito-Author"
LOG = logging.getLogger(__name__)
_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
_RATE_QUANTUM = Decimal("0.0001")
_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]

Month = Annotated[str, PathParam(pattern=_MONTH_PATTERN)]
OptionalMonth = Annotated[str | None, Query(pattern=_MONTH_PATTERN)]
RequiredMonth = Annotated[str, Query(pattern=_MONTH_PATTERN)]
# Comma-separated account keys (`accounts.key`); missing or empty: all of them.
AccountKeys = Annotated[str | None, Query(max_length=2000)]
Selection = frozenset[str] | None


def parse_accounts(raw: str | None, infos: Sequence[account_data.AccountInfo]) -> Selection:
    """The requested accounts; None when none were requested or they are all. 422 if one does
    not exist."""
    keys = [key.strip() for key in (raw or "").split(",") if key.strip()]
    if not keys:
        return None
    known = {info.key for info in infos}
    unknown = sorted({key for key in keys if key not in known})
    if unknown:
        raise HTTPException(422, t("web.unknown_accounts", keys=", ".join(unknown)))
    return summary.selection(infos, keys)


def only(movements: Sequence[Movement], chosen: Selection) -> tuple[Movement, ...]:
    """The movements of the chosen accounts (all of them when `chosen` is None)."""
    if chosen is None:
        return tuple(movements)
    return tuple(m for m in movements if m.account in chosen)


def _conflict(exc: Exception) -> str:
    """The message of a 409: the `AlreadyLinked` one or, when the database's unique index stopped
    it (two requests at once), a generic one."""
    if isinstance(exc, links.AlreadyLinked):
        return str(exc)
    return t("web.already_linked")


def create_app(
    db_path: Path,
    static_dir: Path | None = None,
    today: Callable[[], date] | None = None,
    holders_path: Path | None = None,
    mode: Mode | None = None,
    flows: FlowCache | None = None,
) -> FastAPI:
    """FastAPI app over the database at `db_path`.

    Local defense: only loopback hosts are accepted (against DNS rebinding), every method that
    writes requires the `X-Michelito: 1` header (a form on another page cannot send it) and
    there is no CORS. Each request opens and closes its own connection.

    The holders (to detect transfers between my own accounts) are read from `holders_path` on
    every request, so editing the file needs no restart; by default, `holders.txt` next to the
    database (`config.Paths.holders`).

    `mode`: a mode other than the local one (the public demo, `michelito.demo.app`): where each
    request's database comes from (`web.workspace`), which hosts and authors are accepted and
    its own routes. Without it, the database is always `db_path`.

    `flows`: where the loaded flow is kept between requests (`flow_cache`); a mode that must
    drop it at given moments (the hosted app, when sessions end) passes its own.
    """
    # The user's local date (`config.local_today`), not the server's.
    today = today or (lambda: config.local_today())
    holders_file = holders_path or config.Paths(db_path.parent).holders
    mode = mode or local_mode(Workspace(db_path, holders_file))
    app = FastAPI(title="michelito", docs_url=None, redoc_url=None, openapi_url=None)
    flows = FlowCache() if flows is None else flows
    app.state.flows = flows

    @app.exception_handler(migrations_v19.MigrationMismatch)
    async def migration_mismatch(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        """The database could not be brought to schema 19 (it stayed as it was): say so."""
        return JSONResponse(
            {"detail": t("core.migration_mismatch", detail=str(exc))}, status_code=503
        )

    def workspace() -> Workspace:
        """This request's database; without one (no demo session) none is opened."""
        found = CURRENT.get()
        if found is None:
            raise HTTPException(401, t("web.no_session"))
        return found

    @contextmanager
    def connection() -> Iterator[sqlite3.Connection]:
        found = workspace()
        with closing(db.connect(found.database, found.key)) as conn:
            if mode.on_connect is not None:
                mode.on_connect(conn)
            _refresh_cash(conn)
            yield conn

    def _refresh_cash(conn: sqlite3.Connection) -> None:
        """The cash system pass (scheduled occurrences due, automatic withdrawals) before
        the request reads anything; outside the change log. A failure is logged and the request
        goes on with what is stored (nothing is half written: it runs in its own transaction)."""
        found = holders.of(workspace(), conn)
        signature = hashlib.sha256(repr(found).encode()).hexdigest()[:16]
        cash_activation.refresh_safely(conn, today(), load_flow, signature)

    @app.middleware("http")
    async def require_local_header(request: Request, call_next):  # noqa: ANN001, ANN202
        refusal = _refusal(request, mode)
        if refusal is not None:
            return refusal
        resolved = await mode.provider.resolve(request)
        try:
            if resolved.refusal is not None:
                return resolved.refusal
            # Who makes the change (the change log stores it): `X-Michelito-Author: claude` for
            # what Claude Code applies through the API; without the header, the user.
            token = changelog.AUTHOR.set(request.headers.get(AUTHOR_HEADER, "user"))
            place = CURRENT.set(resolved.workspace)
            try:
                stop = (
                    await run_in_threadpool(mode.guard, request, connection)
                    if mode.guard is not None
                    else None
                )
                response = stop if stop is not None else await call_next(request)
            finally:
                CURRENT.reset(place)
                changelog.AUTHOR.reset(token)
            if resolved.finish is not None:
                await run_in_threadpool(resolved.finish, response)
            return response
        finally:
            if resolved.release is not None:
                resolved.release()

    # Added last so it is the outermost layer: the host is checked first.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(mode.allowed_hosts))

    @app.get("/api/health")
    def get_health() -> dict[str, str]:
        """For deployment: answers without opening any database."""
        return {"status": "ok"}

    @app.get("/api/mode")
    def get_mode(request: Request) -> dict[str, str | bool]:
        """The server mode (local or demo) and whether the request already has its database;
        opens none."""
        return {
            "mode": mode.name,
            **(mode.info or {}),
            "session": mode.provider.has_session(request),
        }

    def load_flow(
        conn: sqlite3.Connection, known: catalog.Catalog | None = None
    ) -> tuple[Movement, ...]:
        """Every movement (expenses, income, transfers), with up-to-date holders.

        `known`: the category catalog (by default, the database's).

        The flow with the database's own catalog is kept between requests while its file is
        unchanged (`flow_cache`); never inside a transaction, whose rows may still be rolled
        back, and never with another catalog (a preview of keywords)."""
        found = holders.of(workspace(), conn)
        day = today()
        if conn.in_transaction or (known is not None and known != catalog.load(conn)):
            return spending.load_all(conn, found, known, day)
        return flows.get(
            workspace().database,
            (repr(found), day),
            lambda: spending.load_all(conn, found, known, day),
        )

    def load_spending(conn: sqlite3.Connection) -> tuple[Movement, ...]:
        """Only the expenses, with the same criteria as the Summary (holders included)."""
        return tuple(m for m in load_flow(conn) if m.kind == "expense")

    def default_month(options: list[summary.MonthOption]) -> str:
        if not options:
            raise HTTPException(404, t("web.no_data"))
        return next((o.month for o in options if not o.partial), options[0].month)

    @app.get("/api/months")
    def get_months(accounts: AccountKeys = None) -> list[MonthOptionOut]:
        with connection() as conn:
            infos = account_data.account_infos(conn)
            selected = parse_accounts(accounts, infos)
            options = summary.month_options(load_flow(conn), infos, selected, today())
        return [MonthOptionOut.of(o) for o in options]

    @app.get("/api/summary")
    def get_summary(month: OptionalMonth = None, accounts: AccountKeys = None) -> SummaryOut:
        with connection() as conn:
            movements = load_flow(conn)
            infos = account_data.account_infos(conn)
            selected = parse_accounts(accounts, infos)
            chosen = month or default_month(summary.month_options(movements, infos, selected))
            try:
                by_month = rates.load(conn)
                ctx = links_view.context(
                    movements,
                    links.load(conn),
                    infos,
                    by_month,
                    suggest=False,
                    book=ledger_store.load(conn),
                )
                built = summary.build_summary(
                    movements,
                    infos,
                    by_month,
                    chosen,
                    selected,
                    ctx.groups,
                    ctx.exchange_states,
                    today(),
                )
            except LookupError:
                raise HTTPException(404, t("web.no_data")) from None
        return SummaryOut.of(built)

    @app.get("/api/pending")
    def get_pending(accounts: AccountKeys = None) -> PendingOut:
        """Who owes you and whom you owe, across all months (see `web.pending`)."""
        with connection() as conn:
            movements = load_flow(conn)
            infos = account_data.account_infos(conn)
            selected = parse_accounts(accounts, infos)
            by_month = rates.load(conn)
            ctx = links_view.context(
                movements,
                links.load(conn),
                infos,
                by_month,
                suggest=False,
                book=ledger_store.load(conn),
            )
        found = pending_view.build_pending(
            ctx.movements,
            ctx.book,
            ctx.groups,
            ctx.exchange_states,
            ctx.labels,
            by_month,
            today(),
            selected,
        )
        return PendingOut.of(found)

    @app.get("/api/transactions")
    def get_transactions(
        month: OptionalMonth = None,
        account: str | None = None,
        category: str | None = None,
        q: str | None = None,
        kind: Kind | None = None,
        accounts: AccountKeys = None,
        category_id: int | None = None,
        shared: transactions.SharedFilter | None = None,
        provisional: bool = False,
    ) -> TransactionsOut:
        """`account` (one account) is the older filter and is still accepted; together with
        `accounts`, the rows that match both remain. The category goes by `category_id` or by
        name (`category`: the current one or an earlier one). `shared`: only shared expenses
        ("shared") or the ones with an amount pending ("pending"). `provisional`: only the ones
        from bank alerts still waiting for their statement."""
        with connection() as conn:
            known = catalog.load(conn)
            movements = load_flow(conn, known)
            infos = account_data.account_infos(conn)
            selected = parse_accounts(accounts, infos)
            chosen = month or default_month(summary.month_options(movements, infos, selected))
            views = tx_views(
                conn,
                known,
                movements,
                infos,
                transactions.Filters(
                    chosen,
                    account,
                    category,
                    q,
                    kind,
                    selected,
                    categories_view.filter_ref(known, category, category_id),
                    shared,
                    provisional,
                ),
                # The suggestions, with the same history as the Summary card.
                only(movements, selected),
            )
        items = [TxOut.of(v) for v in views]
        spent = [i for i in items if i.kind == "expense"]
        return TransactionsOut(
            items=items,
            count=len(items),
            total_cents=sum(i.amount_dop_cents or 0 for i in spent),
            income_cents=-sum(i.amount_dop_cents or 0 for i in items if i.kind == "income"),
            unconverted_usd_cents=sum(i.amount_cents for i in spent if i.amount_dop_cents is None),
        )

    def tx_views(
        conn: sqlite3.Connection,
        known: catalog.Catalog,
        movements: Sequence[Movement],
        infos: Sequence[account_data.AccountInfo],
        filters: transactions.Filters,
        history: Sequence[Movement] | None = None,
    ) -> list[transactions.TxView]:
        """Transactions rows with their suggestions and links. `history`: the movements that
        one-off expenses are judged against (by default, all of them)."""
        by_month = rates.load(conn)
        ctx = links_view.context(
            movements,
            links.load(conn),
            infos,
            by_month,
            reviewed=review_marks.load(conn),
            book=ledger_store.load(conn),
        )
        views = transactions.list_transactions(
            movements,
            infos,
            by_month,
            filters,
            suggested_reasons(
                conn, movements if history is None else history, by_month, (filters.month,)
            ),
            dismissals.load(conn),
            known,
            lambda fingerprints: links_view.row_links(ctx, fingerprints),
        )
        # Laid over the rows, never part of a movement: what entered because the person
        # approved it (hosted email forwarding) and the merchant receipts linked to each one.
        approved = inbox_store.approved_fingerprints(conn)
        linked = receipts_view.by_fingerprint(conn)
        plans = installments_view.tags(conn)
        if not approved and not linked and not plans:
            return views
        return [
            dc_replace(
                v,
                approved=v.fingerprint in approved,
                receipts=linked.get(v.fingerprint, ()),
                installment=plans.get(v.fingerprint),
            )
            for v in views
        ]

    def tx_out(conn: sqlite3.Connection, fingerprint: str, month: str) -> TxOut:
        """The up-to-date row after a change."""
        known = catalog.load(conn)
        infos = account_data.account_infos(conn)
        fresh = tx_views(conn, known, load_flow(conn, known), infos, transactions.Filters(month))
        return TxOut.of(next(v for v in fresh if v.fingerprint == fingerprint))

    def find_tx(conn: sqlite3.Connection, fingerprint: str) -> Movement:
        try:
            return transactions.find(load_flow(conn), fingerprint)
        except LookupError:
            raise HTTPException(404, t("web.unknown_transaction")) from None

    @app.get("/api/transactions/{fingerprint}")
    def get_transaction(fingerprint: str) -> TxOut:
        """A single row, the same one the list returns (with its links): a link's screen loads
        it without the list. 404 if it does not exist."""
        with connection() as conn:
            target = find_tx(conn, fingerprint)
            try:
                return tx_out(conn, fingerprint, target.month)
            except StopIteration:
                raise HTTPException(404, t("web.unknown_transaction")) from None

    @app.patch("/api/transactions/{fingerprint}")
    def patch_transaction(fingerprint: str, body: EditBody) -> TxOut:
        """Category, one-off flag and note in a single database transaction: an error leaves
        nothing half done. (Sharing goes through Shared: `web.ledger_routes`.)"""
        with connection() as conn:
            flow = load_flow(conn)
            target = find_tx(conn, fingerprint)
            known = catalog.load(conn)
            try:
                chosen = categories_view.edit_target(known, body.category, body.category_id)
                # A cash entry with a concept has it as its merchant (schema 23): its rule
                # applies; one without a concept still corrects only itself.
                if (
                    chosen is not None
                    and body.scope == "merchant"
                    and cash_box.is_manual(fingerprint)
                    and target.merchant == cash_box.MERCHANT
                ):
                    raise ValueError(t("web.cash_box_self_only"))
                found = None if chosen is None else known.by_id(chosen)
                problem = (
                    None
                    if found is None
                    else cash_box.manual_category_error(fingerprint, target.amount, found.kind)
                )
                if problem is not None:
                    raise ValueError(problem)
                with conn:
                    edit_log.edit_transaction(
                        conn, target, known, chosen, body.one_off, body.scope, body.note, flow
                    )
            except (links.AlreadyLinked, sqlite3.IntegrityError) as exc:
                raise HTTPException(409, _conflict(exc)) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return tx_out(conn, fingerprint, target.month)

    def track_tx(
        conn: sqlite3.Connection, kind: str, target: Movement
    ) -> AbstractContextManager[changelog.Draft]:
        """The change-log entry of a change to a transaction (its link, its mark)."""
        return changelog.track(
            conn,
            kind,
            "transaction",
            target.fingerprint,
            edit_log.subject(target),
            merchant=target.merchant,
            fingerprints=[target.fingerprint],
        )

    def track_link(
        conn: sqlite3.Connection, kind: str, link_id: int
    ) -> AbstractContextManager[changelog.Draft]:
        """The change-log entry of a change to a whole link (group, exchange)."""
        return changelog.track(
            conn, kind, "link", str(link_id), edit_log.link_subject(conn, link_id)
        )

    def link_context(conn: sqlite3.Connection) -> links_view.Context:
        return links_view.context(
            load_flow(conn),
            links.load(conn),
            account_data.account_infos(conn),
            rates.load(conn),
            suggest=False,
        )

    @contextmanager
    def link_errors() -> Iterator[None]:
        try:
            yield
        except links.AlreadyLinked as exc:
            raise HTTPException(409, str(exc)) from None
        except sqlite3.IntegrityError as exc:  # another tab linked it at the same time
            raise HTTPException(409, _conflict(exc)) from None
        except links.LinkError as exc:
            raise HTTPException(422, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc) or t("web.unknown_group")) from None

    # Shared (the ledger): see `web.ledger_routes`.
    ledger_routes.register(app, connection, load_flow, parse_accounts, today)

    def suggested_reasons(
        conn: sqlite3.Connection,
        movements: Sequence[Movement],
        by_month: dict[str, rates.Rate],
        months: Sequence[str],
    ) -> dict[str, tuple[str, ...]]:
        return one_offs_view.reasons_by_fingerprint(
            movements,
            by_month,
            months,
            dismissals.load(conn),
            marks.load_for(conn, movements),
            marks.load_unions(conn),
        )

    def exchange_out(conn: sqlite3.Connection, exchange_id: int) -> ExchangeOut:
        ctx = link_context(conn)
        state = ctx.exchange_states.get(exchange_id)
        if state is None:
            raise HTTPException(404, t("web.unknown_exchange"))
        return ExchangeOut.of(state, tuple(links_view.linked_tx(m, ctx.labels) for m in state.legs))

    def legs_of(conn: sqlite3.Connection, fingerprints: Sequence[str]) -> list[Movement]:
        flow = {m.fingerprint: m for m in load_flow(conn)}
        missing = [fp for fp in fingerprints if fp not in flow]
        if missing:
            raise HTTPException(404, t("web.unknown_transaction"))
        return [flow[fp] for fp in dict.fromkeys(fingerprints)]

    @app.get("/api/transactions/{fingerprint}/exchange-candidates")
    def get_exchange_candidates(fingerprint: str) -> list[CandidateOut]:
        """Possible legs, ranked and marked (`primary`): not in an exchange, in the other
        currency and the opposite direction (±30 days), by closeness to the month's rate; in an
        exchange with an amount pending, only the missing side and what fits in the pending
        amount (see `exchanges.candidates`)."""
        with connection() as conn:
            target = find_tx(conn, fingerprint)
            ctx = link_context(conn)
        found = ctx.links.exchange_for(fingerprint)
        current = None if found is None else ctx.exchange_states.get(found.id)
        if found is None and not exchange_math.is_eligible(target, ctx.links, ctx.banks):
            return []
        options = exchange_math.candidates(
            target,
            ctx.movements,
            ctx.links,
            ctx.banks,
            current,
            lambda month: rates.rate_for(ctx.rates, month),
        )
        return [
            CandidateOut.ranked(links_view.linked_tx(c.move, ctx.labels), c.primary)
            for c in options
        ]

    @app.post("/api/exchanges", status_code=201)
    def post_exchange(body: ExchangeBody) -> ExchangeOut:
        with connection() as conn:
            legs = legs_of(conn, body.fingerprints)
            try:
                links_view.check_legs(link_context(conn), legs)
                with conn, track_link(conn, "exchange", 0) as draft:
                    made = links.create_exchange(
                        conn, [m.fingerprint for m in legs], body.agreed_rate
                    )
                    draft.target, draft.subject = str(made), edit_log.subject(legs[0])
            except links.AlreadyLinked as exc:
                raise HTTPException(409, str(exc)) from None
            except links.LinkError as exc:
                raise HTTPException(422, str(exc)) from None
            return exchange_out(conn, made)

    def current_legs(ctx: links_view.Context, exchange_id: int) -> list[Movement]:
        state = ctx.exchange_states.get(exchange_id)
        if state is None:
            raise HTTPException(404, t("web.unknown_exchange"))
        return list(state.legs)

    @app.post("/api/exchanges/{exchange_id}/legs")
    def post_legs(exchange_id: int, body: LegsBody) -> ExchangeOut:
        with connection() as conn:
            ctx = link_context(conn)
            current = current_legs(ctx, exchange_id)
            new = legs_of(conn, body.fingerprints)
            try:
                links_view.check_legs(ctx, new, current)
                with conn, track_link(conn, "exchange", exchange_id):
                    links.add_legs(conn, exchange_id, [m.fingerprint for m in new])
            except links.AlreadyLinked as exc:
                raise HTTPException(409, str(exc)) from None
            except links.LinkError as exc:
                raise HTTPException(422, str(exc)) from None
            return exchange_out(conn, exchange_id)

    @app.patch("/api/exchanges/{exchange_id}")
    def patch_exchange(exchange_id: int, body: ExchangePatch) -> ExchangeOut:
        """Agreed rate (null: the implied one) and "exchange complete" (`closed`)."""
        rate = body.agreed_rate if "agreed_rate" in body.model_fields_set else ...
        with connection() as conn:
            current_legs(link_context(conn), exchange_id)
            try:
                with conn, track_link(conn, "exchange", exchange_id):
                    links.update_exchange(conn, exchange_id, agreed_rate=rate, closed=body.closed)
            except links.LinkError as exc:
                raise HTTPException(422, str(exc)) from None
            return exchange_out(conn, exchange_id)

    @app.delete("/api/exchanges/{exchange_id}/legs/{fingerprint}")
    def delete_leg(exchange_id: int, fingerprint: str) -> Response:
        """Removes a leg; if a currency is left without legs, the exchange is undone (204).
        It does not require the other legs to exist: a dormant exchange (missing a leg or no
        longer balanced) can also be taken apart from the remaining leg. If what remains does
        not form an exchange, it is undone too (204).
        """
        with connection() as conn:
            stored = stored_exchange(conn, exchange_id)
            if fingerprint not in stored.legs:
                raise HTTPException(404, t("web.not_a_leg"))
            flow = {m.fingerprint: m for m in load_flow(conn)}
            rest = [flow[leg] for leg in stored.legs if leg != fingerprint and leg in flow]
            with conn, track_link(conn, "exchange", exchange_id):
                try:
                    exchange_math.check_legs(rest)
                except links.LinkError:
                    links.delete_exchange(conn, exchange_id)
                    return Response(status_code=204)
                links.remove_leg(conn, exchange_id, fingerprint)
            return JSONResponse(exchange_out(conn, exchange_id).model_dump(mode="json"))

    def stored_exchange(conn: sqlite3.Connection, exchange_id: int) -> links.Exchange:
        found = links.load(conn).exchange(exchange_id)
        if found is None:
            raise HTTPException(404, t("web.unknown_exchange"))
        return found

    @app.delete("/api/exchanges/{exchange_id}", status_code=204)
    def delete_exchange(exchange_id: int) -> Response:
        """Undoes the exchange (its legs go back to their category); 404 if it does not exist."""
        with connection() as conn:
            stored_exchange(conn, exchange_id)
            with conn, track_link(conn, "exchange", exchange_id):
                links.delete_exchange(conn, exchange_id)
        return Response(status_code=204)

    @app.get("/api/one-off-suggestions")
    def get_one_off_suggestions(
        month: RequiredMonth, accounts: AccountKeys = None
    ) -> list[OneOffSuggestionOut]:
        with connection() as conn:
            infos = account_data.account_infos(conn)
            flow = load_flow(conn)
            # The rules look at the history of the same accounts: an unusual purchase on the
            # chosen card is judged against what is bought with it.
            views = one_offs_view.suggestions(
                only(flow, parse_accounts(accounts, infos)),
                infos,
                rates.load(conn),
                month,
                dismissals.load(conn),
                marks.load_for(conn, flow),
                marks.load_unions(conn),
            )
        return [OneOffSuggestionOut.of(v) for v in views]

    @app.put("/api/one-off-suggestions/{fingerprint}")
    def put_one_off_suggestion(fingerprint: str, body: DismissBody) -> DismissOut:
        with connection() as conn:
            try:
                target = transactions.find(load_flow(conn), fingerprint)
            except LookupError:
                raise HTTPException(404, t("web.unknown_transaction")) from None
            with conn, track_tx(conn, "reviewed", target) as draft:
                draft.before = t("web.to_review") if body.dismissed else t("web.not_one_off")
                draft.after = t("web.not_one_off") if body.dismissed else t("web.to_review")
                dismissals.set_dismissed(conn, fingerprint, body.dismissed)
        return DismissOut(fingerprint=fingerprint, dismissed=body.dismissed)

    @app.get("/api/accounts")
    def get_accounts() -> list[AccountOut]:
        with connection() as conn:
            views = accounts_view.account_views(conn, today())
        return [AccountOut.of(v) for v in views]

    @app.get("/api/interest")
    def get_interest(
        year: Annotated[int | None, Query(ge=2000, le=2100)] = None, accounts: AccountKeys = None
    ) -> InterestOut:
        now = today()
        with connection() as conn:
            selected = parse_accounts(accounts, account_data.account_infos(conn))
            result = interest_view.interest_year(
                conn, rates.load(conn), year or now.year, now, selected
            )
        return InterestOut.of(result)

    @app.get("/api/categories")
    def get_categories() -> list[CategoryOut]:
        """All of them, the hidden ones too (`hidden`): the pickers leave those out."""
        with connection() as conn:
            return categories_out(conn)

    def categories_out(conn: sqlite3.Connection) -> list[CategoryOut]:
        known = catalog.load(conn)
        views = categories_view.category_views(known, load_flow(conn, known), today().year)
        return [CategoryOut.of(v) for v in views]

    def category_out(conn: sqlite3.Connection, category_id: int) -> CategoryOut:
        return next(c for c in categories_out(conn) if c.id == category_id)

    def category_error(exc: catalog.CategoryError) -> HTTPException:
        return HTTPException(categories_view.http_status(exc), str(exc))

    @app.post("/api/categories", status_code=201)
    def post_category(body: CategoryBody) -> CategoryOut:
        with connection() as conn:
            try:
                with conn:
                    made = catalog.create(conn, body.name, body.kind, body.color)
                    with track_keywords(conn, made.id):
                        catalog.set_keywords(conn, made.id, body.keywords)
            except catalog.CategoryError as exc:
                raise category_error(exc) from None
            return category_out(conn, made.id)

    @contextmanager
    def track_keywords(conn: sqlite3.Connection, category_id: int) -> Iterator[None]:
        """A "keywords" entry: it affects the transactions that change category."""
        known = catalog.load(conn)
        current = known.by_id(category_id)
        before_flow = {m.fingerprint: m.ref for m in load_flow(conn, known)}
        with changelog.track(
            conn,
            "keywords",
            "category",
            str(category_id),
            current.name if current is not None else str(category_id),
            before=_words(current),
        ) as draft:
            yield
            now = catalog.load(conn)
            draft.after = _words(now.by_id(category_id))
            draft.fingerprints = {
                m.fingerprint
                for m in load_flow(conn, now)
                if before_flow.get(m.fingerprint, m.ref) != m.ref
            }

    def _words(category: catalog.Category | None) -> str:
        words = () if category is None else category.keywords
        return ", ".join(words) if words else edit_log.NOTHING

    def in_category(conn: sqlite3.Connection, category_id: int) -> set[str]:
        """The transactions that are in the category today."""
        known = catalog.load(conn)
        found = known.by_id(category_id)
        if found is None:
            return set()
        return {m.fingerprint for m in load_flow(conn, known) if m.ref == found.ref}

    @app.patch("/api/categories/{category_id}")
    def patch_category(category_id: int, body: CategoryPatch) -> CategoryOut:
        """What is missing does not change; all or nothing (an error leaves no half-done
        changes)."""
        color = body.color if "color" in body.model_fields_set else catalog.KEEP
        with connection() as conn:
            try:
                with conn:
                    current = catalog.load(conn).by_id(category_id)
                    with changelog.track(
                        conn,
                        "category_kind",
                        "category",
                        str(category_id),
                        current.name if current is not None else str(category_id),
                        before=None if current is None else KIND_LABELS[current.kind],
                        after=None if body.kind is None else KIND_LABELS[body.kind],
                        fingerprints=in_category(conn, category_id),
                    ):
                        catalog.update(
                            conn,
                            category_id,
                            name=body.name,
                            kind=body.kind,
                            color=color,
                            hidden=body.hidden,
                        )
                    if body.keywords is not None:
                        with track_keywords(conn, category_id):
                            catalog.set_keywords(conn, category_id, body.keywords)
            except catalog.CategoryError as exc:
                raise category_error(exc) from None
            return category_out(conn, category_id)

    @app.delete("/api/categories/{category_id}", status_code=204)
    def delete_category(category_id: int, reassign_to: int | None = None) -> Response:
        """Its corrections and keywords move to `reassign_to` (required when it has any)."""
        with connection() as conn:
            try:
                with conn:
                    known = catalog.load(conn)
                    current = known.by_id(category_id)
                    target = None if reassign_to is None else known.by_id(reassign_to)
                    with changelog.track(
                        conn,
                        "category_deleted",
                        "category",
                        str(category_id),
                        current.name if current is not None else str(category_id),
                        before=current.name if current is not None else None,
                        after=t("web.deleted_moved_to", name=target.name)
                        if target
                        else t("web.deleted"),
                        fingerprints=in_category(conn, category_id),
                    ):
                        catalog.delete(conn, category_id, reassign_to)
            except catalog.CategoryError as exc:
                raise category_error(exc) from None
        return Response(status_code=204)

    @app.post("/api/categories/{category_id}/preview")
    def preview_category(category_id: int, body: PreviewBody) -> PreviewOut:
        """What giving these keywords to the category would move; saves nothing."""
        with connection() as conn:
            known = catalog.load(conn)
            if known.by_id(category_id) is None:
                raise HTTPException(404, t("web.category.unknown", ref=category_id))
            try:
                proposed = known.with_keywords(category_id, body.keywords)
            except catalog.CategoryError as exc:
                raise category_error(exc) from None
            result = categories_view.preview(
                load_flow(conn, known),
                load_flow(conn, proposed),
                proposed,
                category_id,
                rates.load(conn),
            )
        return PreviewOut.of(result)

    @app.put("/api/rates/{month}")
    def put_rate(month: Month, body: RateBody) -> SavedRateOut:
        if body.value.quantize(_RATE_QUANTUM) <= 0:
            raise HTTPException(422, t("web.rate_not_positive"))
        with connection() as conn:
            with conn:
                rates.set_manual(conn, month, body.value)
            saved = rates.load(conn)[month]
        return SavedRateOut(
            month=month,
            value=str(saved.value.quantize(_RATE_QUANTUM)),
            month_used=saved.month_used,
            source=saved.source,
        )

    recurring_routes.register(app, connection, load_flow, parse_accounts, today)
    review_routes.register(app, connection, load_flow, parse_accounts)
    pace_routes.register(app, connection, load_flow, parse_accounts, today)
    live_routes.register(app, connection, load_flow)
    receipt_routes.register(app, connection, load_flow)
    installment_pick_routes.register(app, connection, load_flow)
    installment_routes.register(app, connection, load_flow)
    log_routes.register(app, connection, load_flow)
    batch_routes.register(app, connection, load_flow)
    investment_routes.register(app, connection, load_flow, parse_accounts, today)
    cash_box_routes.register(app, connection, load_flow, tx_out, today)
    cash_routes.register(app, connection, load_flow, today)
    report_routes.register(app, connection, load_flow, parse_accounts)
    budget_routes.register(app, connection, load_flow, parse_accounts, today)
    reserve_routes.register(app, connection, load_flow, parse_accounts, today)
    insight_routes.register(app, connection, load_flow, lambda: holders.of(workspace()))
    dossier_routes.register(app, connection, load_flow)
    if mode.register is not None:
        mode.register(app, connection, load_flow)

    @app.api_route("/api", methods=_ALL_METHODS)
    @app.api_route("/api/{rest:path}", methods=_ALL_METHODS)
    def unknown_api(rest: str = "") -> Response:
        return JSONResponse({"detail": t("web.not_found")}, status_code=404)

    if static_dir is not None:
        _mount_spa(app, static_dir, mode.landing)
    return app


def local_mode(fixed: Workspace) -> Mode:
    """The usual board: loopback only, the same database on every request, any author."""
    return Mode(
        name="local",
        provider=FixedProvider(fixed),
        allowed_hosts=tuple(ALLOWED_HOSTS),
        authors=changelog.AUTHORS,
    )


def _refusal(request: Request, mode: Mode) -> Response | None:
    """The response that stops the request before its route, if any: `X-Michelito` missing on a
    method that writes, author not accepted, route blocked in the mode or body too large."""
    path = request.url.path
    if (
        request.method not in SAFE_METHODS
        and request.headers.get(WRITE_HEADER) != "1"
        and path not in mode.open_writes
    ):
        return JSONResponse(
            {"detail": t("web.missing_header", header=WRITE_HEADER)}, status_code=403
        )
    author = request.headers.get(AUTHOR_HEADER, "user")
    if author not in changelog.AUTHORS:
        return JSONResponse({"detail": t("web.unknown_author")}, status_code=400)
    if author not in mode.authors:
        return JSONResponse(
            {"detail": t("web.author_not_accepted", mode=mode.name)}, status_code=403
        )
    if any(path == prefix or path.startswith(f"{prefix}/") for prefix in mode.blocked):
        return JSONResponse(
            {"detail": t("web.unavailable_in_mode", mode=mode.name)}, status_code=403
        )
    if mode.max_body is not None and request.method not in SAFE_METHODS:
        limit = next((size for exact, size in mode.body_limits if path == exact), mode.max_body)
        return _body_refusal(request, limit)
    return None


def _body_refusal(request: Request, limit: int) -> Response | None:
    """413 if the declared body is over `limit`; 411 if it is sent in chunks without a length."""
    length = request.headers.get("content-length")
    if length is None:
        if request.headers.get("transfer-encoding"):
            return JSONResponse({"detail": t("web.missing_content_length")}, status_code=411)
        return None
    if not (length.isascii() and length.isdigit()) or int(length) > limit:
        return JSONResponse({"detail": t("web.body_too_large")}, status_code=413)
    return None


_ROOT_DIV = '<div id="root"></div>'


def _mount_spa(app: FastAPI, static_dir: Path, landing: str | None) -> None:
    """The built interface. `HEAD` answers too: some checkers (Google's) ask it first."""
    root = static_dir.resolve()

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str) -> Response:
        if not path and landing is not None:
            return _home(root / "index.html", landing)
        try:
            candidate = (root / path).resolve()
        except ValueError:  # e.g. a null byte in the path
            return FileResponse(root / "index.html")
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


def _home(index: Path, landing: str) -> Response:
    """The index with `landing` inside its empty `#root`; the plain index if it has none."""
    text = index.read_text(encoding="utf-8")
    if _ROOT_DIV not in text:
        LOG.warning("index.html has no empty #root; the home page goes without its landing")
        return FileResponse(index)
    return HTMLResponse(text.replace(_ROOT_DIV, f'<div id="root">{landing}</div>', 1))
