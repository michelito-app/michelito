"""The board's local JSON API. It only listens on 127.0.0.1; see `create_app` for the defense."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, closing, contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from michelito import config, db
from michelito.analysis import accounts as account_data
from michelito.analysis import (
    cash_box,
    catalog,
    changelog,
    links,
    rates,
    review_marks,
    spending,
    transfers,
)
from michelito.analysis import exchanges as exchange_math
from michelito.analysis import one_off_dismissals as dismissals
from michelito.analysis import recurring_marks as marks
from michelito.analysis import shared as shared_math
from michelito.analysis.categories import KIND_LABELS, Kind
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import accounts as accounts_view
from michelito.web import (
    batch_routes,
    budget_routes,
    cash_box_routes,
    dossier_routes,
    edit_log,
    insight_routes,
    investment_routes,
    log_routes,
    recurring_routes,
    report_routes,
    reserve_routes,
    review_routes,
    shared_routes,
    summary,
    transactions,
)
from michelito.web import categories as categories_view
from michelito.web import interest as interest_view
from michelito.web import links as links_view
from michelito.web import one_offs as one_offs_view
from michelito.web import pending as pending_view
from michelito.web.schemas import (
    AccountOut,
    CandidateOut,
    CandidatesOut,
    CategoryBody,
    CategoryOut,
    CategoryPatch,
    DismissBody,
    DismissOut,
    EditBody,
    ExchangeBody,
    ExchangeOut,
    ExchangePatch,
    GroupCandidateOut,
    GroupExpenseBody,
    GroupPatch,
    GroupRefOut,
    InterestOut,
    LegsBody,
    MonthOptionOut,
    OneOffSuggestionOut,
    PendingOut,
    PreviewBody,
    PreviewOut,
    RateBody,
    ReimbursementBody,
    SavedRateOut,
    SharedBody,
    SharedOut,
    SplitBody,
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
    today: Callable[[], date] = date.today,
    holders_path: Path | None = None,
    mode: Mode | None = None,
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
    """
    holders_file = holders_path or config.Paths(db_path.parent).holders
    mode = mode or local_mode(Workspace(db_path, holders_file))
    app = FastAPI(title="michelito", docs_url=None, redoc_url=None, openapi_url=None)

    def workspace() -> Workspace:
        """This request's database; without one (no demo session) none is opened."""
        found = CURRENT.get()
        if found is None:
            raise HTTPException(401, t("web.no_session"))
        return found

    @contextmanager
    def connection() -> Iterator[sqlite3.Connection]:
        with closing(db.connect(workspace().database)) as conn:
            if mode.on_connect is not None:
                mode.on_connect(conn)
            yield conn

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
                response = await call_next(request)
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

        `known`: the category catalog (by default, the database's)."""
        return spending.load_all(conn, transfers.load_holders(workspace().holders), known)

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
            options = summary.month_options(load_flow(conn), infos, selected)
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
                    movements, links.load(conn), infos, by_month, suggest=False
                )
                built = summary.build_summary(
                    movements,
                    infos,
                    by_month,
                    chosen,
                    selected,
                    ctx.expense_states,
                    ctx.exchange_states,
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
            ctx = links_view.context(movements, links.load(conn), infos, by_month, suggest=False)
        found = pending_view.build_pending(
            ctx.movements,
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
    ) -> TransactionsOut:
        """`account` (one account) is the older filter and is still accepted; together with
        `accounts`, the rows that match both remain. The category goes by `category_id` or by
        name (`category`: the current one or an earlier one). `shared`: only shared expenses
        ("shared") or the ones with an amount pending ("pending")."""
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
            movements, links.load(conn), infos, by_month, reviewed=review_marks.load(conn)
        )
        return transactions.list_transactions(
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
        """Category, one-off flag, note and split (`shared`; null removes it) in a single
        database transaction: an error leaves nothing half done."""
        with connection() as conn:
            flow = load_flow(conn)
            target = find_tx(conn, fingerprint)
            known = catalog.load(conn)
            try:
                chosen = categories_view.edit_target(known, body.category, body.category_id)
                if (
                    chosen is not None
                    and body.scope == "merchant"
                    and cash_box.is_manual(fingerprint)
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
                    if "shared" in body.model_fields_set:
                        with track_tx(conn, "shared", target):
                            apply_shared(conn, target, body.shared)
                    if body.written_off is not None:
                        group = links.group_of(conn, fingerprint)
                        with track_link(conn, "shared", group):
                            links.set_written_off(conn, group, body.written_off)
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

    def apply_shared(conn: sqlite3.Connection, target: Movement, body: SharedBody | None) -> None:
        """`body`: the split (creates a group, adds the expense to `link_id` or changes its
        split); None removes the expense from its group (the last expense deletes the group)."""
        if body is None:
            links.unshare(conn, target.fingerprint)
            return
        found = links.load(conn)
        split = split_args(body)
        current = found.shared_for(target.fingerprint)
        if body.link_id is not None and current is None:
            check_join(conn, body.link_id, target)
            links.add_expense(
                conn, body.link_id, target.fingerprint, shared_math.gross(target), **split
            )
            return
        if body.link_id is not None and current is not None and current.id != body.link_id:
            raise links.AlreadyLinked(t("web.expense_in_other_group"))
        links_view.check_shareable(found, target)
        links.set_shared(
            conn, target.fingerprint, shared_math.gross(target), with_whom=body.with_whom, **split
        )

    def split_args(body: SplitBody) -> dict:
        return {
            "people": body.people,
            "my_share": None if body.my_share_cents is None else Decimal(body.my_share_cents) / 100,
            "for_other": body.for_other,
        }

    def check_join(conn: sqlite3.Connection, link_id: int, target: Movement) -> None:
        try:
            links_view.check_joinable(link_context(conn), link_id, target)
        except LookupError:
            raise HTTPException(404, t("web.unknown_group")) from None

    def link_context(conn: sqlite3.Connection) -> links_view.Context:
        return links_view.context(
            load_flow(conn),
            links.load(conn),
            account_data.account_infos(conn),
            rates.load(conn),
            suggest=False,
        )

    def add_refund(
        conn: sqlite3.Connection, link_id: int, body: ReimbursementBody, ctx: links_view.Context
    ) -> None:
        """Links a credit or records a manual one in the group (inside the transaction)."""
        if body.credit is not None:
            credit = find_tx(conn, body.credit)
            links_view.check_reimbursement(ctx, link_id, credit)
            links.add_reimbursement(conn, link_id, credit.fingerprint)
            return
        entry = body.manual
        if entry is None:
            raise HTTPException(422, t("web.credit_or_manual"))
        state = ctx.groups.get(link_id)
        if state is None:
            raise links.LinkError(t("web.group_without_expenses"))
        if entry.day < state.first.day:
            raise links.LinkError(t("web.refund_before_expense"))
        links.add_manual(
            conn,
            link_id,
            Decimal(entry.amount_cents) / 100,
            entry.day,
            entry.currency or state.first.currency,  # no currency: the oldest expense's, today
            entry.person,
            entry.place,
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

    @app.post("/api/transactions/{fingerprint}/reimbursements")
    def post_reimbursement(fingerprint: str, body: ReimbursementBody) -> TxOut:
        """Links an imported credit or records a manual one in the expense's group; returns the
        up-to-date expense."""
        if (body.credit is None) == (body.manual is None):
            raise HTTPException(422, t("web.credit_or_manual"))
        with connection() as conn:
            expense = find_tx(conn, fingerprint)
            ctx = link_context(conn)
            with link_errors(), conn:
                group = links.group_of(conn, fingerprint)
                with track_link(conn, "shared", group):
                    add_refund(conn, group, body, ctx)
            return tx_out(conn, fingerprint, expense.month)

    @app.delete("/api/transactions/{fingerprint}/reimbursements/manual/{entry_id}")
    def delete_manual(fingerprint: str, entry_id: int) -> TxOut:
        with connection() as conn:
            expense = find_tx(conn, fingerprint)
            with link_errors(), conn:
                group = links.group_of(conn, fingerprint)
                with track_link(conn, "shared", group):
                    links.remove_manual(conn, group, entry_id)
            return tx_out(conn, fingerprint, expense.month)

    @app.delete("/api/transactions/{fingerprint}/reimbursements/{credit}")
    def delete_reimbursement(fingerprint: str, credit: str) -> TxOut:
        with connection() as conn:
            expense = find_tx(conn, fingerprint)
            with link_errors(), conn:
                group = links.group_of(conn, fingerprint)
                with track_link(conn, "shared", group):
                    links.remove_reimbursement(conn, group, credit)
            return tx_out(conn, fingerprint, expense.month)

    @app.delete("/api/reimbursements/{credit}", status_code=204)
    def delete_reimbursement_of_credit(credit: str) -> Response:
        """Unlinks a credit from its own side, through its link: works even when the group has
        no expenses present (dormant link). 404 if the credit is not a reimbursement."""
        with connection() as conn:
            owner = links.load(conn).reimbursed(credit)
            if owner is None:
                raise HTTPException(404, t("web.not_a_reimbursement"))
            with conn, track_link(conn, "shared", owner.id):
                links.remove_reimbursement(conn, owner.id, credit)
        return Response(status_code=204)

    @app.get("/api/transactions/{fingerprint}/reimbursement-candidates")
    def get_reimbursement_candidates(fingerprint: str) -> CandidatesOut:
        """For a shared expense, the credits that can reimburse its group; for a credit, the
        groups with an amount pending that it can reimburse."""
        with connection() as conn:
            target = find_tx(conn, fingerprint)
            ctx = link_context(conn)
            places = links.places(conn)
        owner = ctx.links.shared_for(fingerprint)
        if owner is not None and owner.id in ctx.groups:
            return credit_candidates(ctx, owner.id, places)
        groups: list[shared_math.GroupCandidate] = []
        if shared_math.is_eligible_credit(target, ctx.links):
            groups = shared_math.pick_groups(target, ctx.groups, ctx.rates)
        return CandidatesOut(
            credits=[],
            groups=[
                GroupCandidateOut(**GroupRefOut.ref(c.state).model_dump(), primary=c.primary)
                for c in groups
            ],
            places=places,
        )

    def credit_candidates(
        ctx: links_view.Context, link_id: int, places: list[str]
    ) -> CandidatesOut:
        state = ctx.groups[link_id]
        credits = shared_math.pick_credits(state, ctx.movements, ctx.links, ctx.rates)
        currency = state.first.currency
        return CandidatesOut(
            credits=[
                CandidateOut.ranked(ctx.credit_for(c.move, currency), c.primary) for c in credits
            ],
            groups=[],
            places=places,
        )

    # --- Shared groups (by id) --------------------------------------------------------------

    def group_out(conn: sqlite3.Connection, link_id: int) -> SharedOut:
        view = link_context(conn).group_view(link_id)
        if view is None:
            raise HTTPException(404, t("web.unknown_group"))
        return SharedOut.of(view)

    # Before `/api/shared/{link_id}`: `/api/shared/new-candidates` is not an id.
    shared_routes.register(app, connection, load_flow, parse_accounts, today)

    @app.get("/api/shared/open")
    def get_open_groups() -> list[GroupRefOut]:
        """Groups with an amount pending, most recent first ("add it to a group")."""
        with connection() as conn:
            ctx = link_context(conn)
        return [GroupRefOut.ref(g) for g in shared_math.open_groups(ctx.groups)]

    @app.get("/api/shared/{link_id}")
    def get_group(link_id: int) -> SharedOut:
        with connection() as conn:
            return group_out(conn, link_id)

    @app.patch("/api/shared/{link_id}")
    def patch_group(link_id: int, body: GroupPatch) -> SharedOut:
        """The group's name, "with whom" and "they won't pay me back"."""
        given = body.model_fields_set
        with connection() as conn:
            with link_errors(), conn, track_link(conn, "shared", link_id):
                if "name" in given or "with_whom" in given:
                    links.set_group(
                        conn,
                        link_id,
                        name=body.name if "name" in given else ...,
                        with_whom=body.with_whom if "with_whom" in given else ...,
                    )
                if body.written_off is not None:
                    links.set_written_off(conn, link_id, body.written_off)
            return group_out(conn, link_id)

    @app.post("/api/shared/{link_id}/expenses")
    def post_group_expense(link_id: int, body: GroupExpenseBody) -> SharedOut:
        """Adds an unlinked expense to the group, with its split."""
        with connection() as conn:
            target = find_tx(conn, body.fingerprint)
            with link_errors(), conn, track_link(conn, "shared", link_id):
                check_join(conn, link_id, target)
                links.add_expense(
                    conn,
                    link_id,
                    target.fingerprint,
                    shared_math.gross(target),
                    **split_args(body.split),
                )
            return group_out(conn, link_id)

    @app.put("/api/shared/{link_id}/expenses/{fingerprint}")
    def put_group_expense(link_id: int, fingerprint: str, body: SplitBody) -> SharedOut:
        """Changes the split of one of the group's expenses."""
        with connection() as conn:
            target = find_tx(conn, fingerprint)
            owner = links.load(conn).shared_for(fingerprint)
            if owner is None or owner.id != link_id:
                raise HTTPException(404, t("web.expense_not_in_group"))
            with link_errors(), conn, track_link(conn, "shared", link_id):
                links.set_shared(conn, fingerprint, shared_math.gross(target), **split_args(body))
            return group_out(conn, link_id)

    @app.delete("/api/shared/{link_id}/expenses/{fingerprint}")
    def delete_group_expense(link_id: int, fingerprint: str) -> Response:
        """Removes the expense from the group (the reimbursements stay). With the last expense
        the group is deleted and its reimbursements become free: 204. Otherwise, the up-to-date
        group."""
        with connection() as conn:
            owner = links.load(conn).shared_for(fingerprint)
            if owner is None or owner.id != link_id:
                raise HTTPException(404, t("web.expense_not_in_group"))
            with conn, track_link(conn, "shared", link_id):
                deleted = links.unshare(conn, fingerprint)
            if deleted:
                return Response(status_code=204)
            return JSONResponse(group_out(conn, link_id).model_dump())

    @app.get("/api/shared/{link_id}/expense-candidates")
    def get_group_expense_candidates(link_id: int) -> list[CandidateOut]:
        """The "add another expense" list: unlinked expenses within ±120 days, ranked and marked."""
        with connection() as conn:
            ctx = link_context(conn)
        state = ctx.groups.get(link_id)
        if state is None:
            raise HTTPException(404, t("web.unknown_group"))
        found = shared_math.pick_expenses(state, ctx.movements, ctx.links, ctx.rates)
        return [
            CandidateOut.ranked(links_view.linked_tx(c.move, ctx.labels), c.primary) for c in found
        ]

    @app.get("/api/shared/{link_id}/credit-candidates")
    def get_group_credit_candidates(link_id: int) -> CandidatesOut:
        with connection() as conn:
            ctx = link_context(conn)
            places = links.places(conn)
        if link_id not in ctx.groups:
            raise HTTPException(404, t("web.unknown_group"))
        return credit_candidates(ctx, link_id, places)

    @app.post("/api/shared/{link_id}/reimbursements")
    def post_group_reimbursement(link_id: int, body: ReimbursementBody) -> SharedOut:
        if (body.credit is None) == (body.manual is None):
            raise HTTPException(422, t("web.credit_or_manual"))
        with connection() as conn:
            ctx = link_context(conn)
            with link_errors(), conn, track_link(conn, "shared", link_id):
                if ctx.links.group(link_id) is None:
                    raise LookupError(link_id)
                add_refund(conn, link_id, body, ctx)
            return group_out(conn, link_id)

    @app.delete("/api/shared/{link_id}/reimbursements/{credit}")
    def delete_group_reimbursement(link_id: int, credit: str) -> SharedOut:
        with connection() as conn:
            with link_errors(), conn, track_link(conn, "shared", link_id):
                links.remove_reimbursement(conn, link_id, credit)
            return group_out(conn, link_id)

    @app.delete("/api/shared/{link_id}/manual/{entry_id}")
    def delete_group_manual(link_id: int, entry_id: int) -> SharedOut:
        with connection() as conn:
            with link_errors(), conn, track_link(conn, "shared", link_id):
                links.remove_manual(conn, link_id, entry_id)
            return group_out(conn, link_id)

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
    log_routes.register(app, connection, load_flow)
    batch_routes.register(app, connection, load_flow)
    investment_routes.register(app, connection, load_flow, parse_accounts, today)
    cash_box_routes.register(app, connection, load_flow, tx_out, today)
    report_routes.register(app, connection, load_flow, parse_accounts)
    budget_routes.register(app, connection, load_flow, parse_accounts, today)
    reserve_routes.register(app, connection, load_flow, parse_accounts, today)
    insight_routes.register(
        app, connection, load_flow, lambda: transfers.load_holders(workspace().holders)
    )
    dossier_routes.register(app, connection, load_flow)
    if mode.register is not None:
        mode.register(app, connection, load_flow)

    @app.api_route("/api", methods=_ALL_METHODS)
    @app.api_route("/api/{rest:path}", methods=_ALL_METHODS)
    def unknown_api(rest: str = "") -> Response:
        return JSONResponse({"detail": t("web.not_found")}, status_code=404)

    if static_dir is not None:
        _mount_spa(app, static_dir)
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
    if request.method not in SAFE_METHODS and request.headers.get(WRITE_HEADER) != "1":
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
    path = request.url.path
    if any(path == prefix or path.startswith(f"{prefix}/") for prefix in mode.blocked):
        return JSONResponse(
            {"detail": t("web.unavailable_in_mode", mode=mode.name)}, status_code=403
        )
    if mode.max_body is not None and request.method not in SAFE_METHODS:
        return _body_refusal(request, mode.max_body)
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


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    root = static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        try:
            candidate = (root / path).resolve()
        except ValueError:  # e.g. a null byte in the path
            return FileResponse(root / "index.html")
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
