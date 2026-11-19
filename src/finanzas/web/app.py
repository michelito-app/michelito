"""API JSON local del board. Solo escucha en 127.0.0.1; ver `create_app` por la defensa."""

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

from finanzas import db
from finanzas.analysis import accounts as account_data
from finanzas.analysis import (
    cash_box,
    catalog,
    changelog,
    links,
    rates,
    review_marks,
    spending,
    transfers,
)
from finanzas.analysis import exchanges as exchange_math
from finanzas.analysis import one_off_dismissals as dismissals
from finanzas.analysis import recurring_marks as marks
from finanzas.analysis import shared as shared_math
from finanzas.analysis.categories import Kind
from finanzas.analysis.spending import Movement
from finanzas.web import accounts as accounts_view
from finanzas.web import (
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
from finanzas.web import categories as categories_view
from finanzas.web import interest as interest_view
from finanzas.web import links as links_view
from finanzas.web import one_offs as one_offs_view
from finanzas.web import pending as pending_view
from finanzas.web.schemas import (
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
from finanzas.web.workspace import CURRENT, FixedProvider, Mode, Workspace

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
_RATE_QUANTUM = Decimal("0.0001")
_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]

Month = Annotated[str, PathParam(pattern=_MONTH_PATTERN)]
OptionalMonth = Annotated[str | None, Query(pattern=_MONTH_PATTERN)]
RequiredMonth = Annotated[str, Query(pattern=_MONTH_PATTERN)]
# Claves de cuentas separadas por coma (`accounts.key`); ausente o vacío: todas.
AccountKeys = Annotated[str | None, Query(max_length=2000)]
Selection = frozenset[str] | None


def parse_accounts(raw: str | None, infos: Sequence[account_data.AccountInfo]) -> Selection:
    """Las cuentas pedidas; None si no se pidió ninguna o son todas. 422 si alguna no existe."""
    keys = [key.strip() for key in (raw or "").split(",") if key.strip()]
    if not keys:
        return None
    known = {info.key for info in infos}
    unknown = sorted({key for key in keys if key not in known})
    if unknown:
        raise HTTPException(422, f"cuentas desconocidas: {', '.join(unknown)}")
    return summary.selection(infos, keys)


def only(movements: Sequence[Movement], chosen: Selection) -> tuple[Movement, ...]:
    """Los movimientos de las cuentas elegidas (todos si `chosen` es None)."""
    if chosen is None:
        return tuple(movements)
    return tuple(m for m in movements if m.account in chosen)


def _conflict(exc: Exception) -> str:
    """El mensaje de un 409: el de `AlreadyLinked` o, si el índice único de la base lo frenó (dos
    pedidos a la vez), uno genérico."""
    if isinstance(exc, links.AlreadyLinked):
        return str(exc)
    return "la transacción ya está en otro vínculo"


def create_app(
    db_path: Path,
    static_dir: Path | None = None,
    today: Callable[[], date] = date.today,
    holders_path: Path | None = None,
    mode: Mode | None = None,
) -> FastAPI:
    """App FastAPI sobre la base en `db_path`.

    Defensa local: solo se aceptan los hosts de loopback (contra DNS rebinding), todo
    método que escribe exige la cabecera `X-Finanzas: 1` (un formulario de otra página no
    puede enviarla) y no hay CORS. Cada petición abre y cierra su propia conexión.

    Los titulares (para detectar transferencias entre mis cuentas) se leen de `holders_path`
    en cada petición, así editar el archivo no pide reiniciar; por defecto, `titulares.txt`
    junto a la base.

    `mode`: otro modo que el local (la demo pública, `finanzas.demo.app`): de dónde sale la base
    de cada petición (`web.workspace`), qué hosts y autores se aceptan y sus rutas propias. Sin
    él, la base es siempre `db_path`.
    """
    holders_file = holders_path or db_path.parent / "titulares.txt"
    mode = mode or local_mode(Workspace(db_path, holders_file))
    app = FastAPI(title="finanzas", docs_url=None, redoc_url=None, openapi_url=None)

    def workspace() -> Workspace:
        """La base de esta petición; sin ella (sin sesión de la demo) no se abre ninguna."""
        found = CURRENT.get()
        if found is None:
            raise HTTPException(401, "no hay sesión de la demo: recarga la página")
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
            # Quién hace el cambio (la bitácora lo guarda): `X-Finanzas-Autor: claude` para lo
            # que aplica Claude Code por la API; sin cabecera, el usuario.
            token = changelog.AUTHOR.set(request.headers.get("x-finanzas-autor", "usuario"))
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

    # Se agrega al final para quedar como capa más externa: el host se revisa primero.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(mode.allowed_hosts))

    @app.get("/api/health")
    def get_health() -> dict[str, str]:
        """Para el despliegue: responde sin abrir ninguna base."""
        return {"estado": "ok"}

    @app.get("/api/modo")
    def get_mode(request: Request) -> dict[str, str | bool]:
        """Modo del servidor (local o demo) y si la petición ya tiene su base; no abre ninguna."""
        return {
            "modo": mode.name,
            **(mode.info or {}),
            "sesion": mode.provider.has_session(request),
        }

    def load_flow(
        conn: sqlite3.Connection, known: catalog.Catalog | None = None
    ) -> tuple[Movement, ...]:
        """Todos los movimientos (gastos, ingresos, transferencias), con titulares al día.

        `known`: el catálogo de categorías (por defecto, el de la base)."""
        return spending.load_all(conn, transfers.load_holders(workspace().holders), known)

    def load_spending(conn: sqlite3.Connection) -> tuple[Movement, ...]:
        """Solo los gastos, con el mismo criterio que el Resumen (titulares incluidos)."""
        return tuple(m for m in load_flow(conn) if m.kind == "gasto")

    def default_month(options: list[summary.MonthOption]) -> str:
        if not options:
            raise HTTPException(404, "mes sin datos")
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
                raise HTTPException(404, "mes sin datos") from None
        return SummaryOut.of(built)

    @app.get("/api/pending")
    def get_pending(accounts: AccountKeys = None) -> PendingOut:
        """Quién te debe y a quién debes, de todos los meses (ver `web.pending`)."""
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
        """`account` (una cuenta) es el filtro de antes y se sigue aceptando; con `accounts`
        también, quedan las filas que cumplen los dos. La categoría va por `category_id` o por
        nombre (`category`: el de hoy o uno anterior). `shared`: solo los gastos compartidos
        ("shared") o los que tienen pendiente ("pending")."""
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
                # Las sugerencias, con la misma historia que la tarjeta del Resumen.
                only(movements, selected),
            )
        items = [TxOut.of(v) for v in views]
        spent = [i for i in items if i.kind == "gasto"]
        return TransactionsOut(
            items=items,
            count=len(items),
            total_cents=sum(i.amount_dop_cents or 0 for i in spent),
            income_cents=-sum(i.amount_dop_cents or 0 for i in items if i.kind == "ingreso"),
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
        """Filas de Transacciones con sus sugerencias y sus vínculos. `history`: los movimientos
        con que se juzgan los gastos únicos (por defecto, todos)."""
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
        """La fila al día después de un cambio."""
        known = catalog.load(conn)
        infos = account_data.account_infos(conn)
        fresh = tx_views(conn, known, load_flow(conn, known), infos, transactions.Filters(month))
        return TxOut.of(next(v for v in fresh if v.fingerprint == fingerprint))

    def find_tx(conn: sqlite3.Connection, fingerprint: str) -> Movement:
        try:
            return transactions.find(load_flow(conn), fingerprint)
        except LookupError:
            raise HTTPException(404, "transacción desconocida") from None

    @app.get("/api/transactions/{fingerprint}")
    def get_transaction(fingerprint: str) -> TxOut:
        """Una sola fila, la misma que trae la lista (con sus vínculos): la pantalla de un
        vínculo la carga sin la lista. 404 si no existe."""
        with connection() as conn:
            target = find_tx(conn, fingerprint)
            try:
                return tx_out(conn, fingerprint, target.month)
            except StopIteration:
                raise HTTPException(404, "transacción desconocida") from None

    @app.patch("/api/transactions/{fingerprint}")
    def patch_transaction(fingerprint: str, body: EditBody) -> TxOut:
        """Categoría, gasto único, nota y reparto (`shared`; null lo quita) en una sola
        transacción de base de datos: un error no deja nada a medias."""
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
                    raise ValueError("un movimiento de la caja fuerte se corrige solo a sí mismo")
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
                        with track_tx(conn, "compartido", target):
                            apply_shared(conn, target, body.shared)
                    if body.written_off is not None:
                        group = links.group_of(conn, fingerprint)
                        with track_link(conn, "compartido", group):
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
        """La entrada de bitácora de un cambio sobre una transacción (su vínculo, su marca)."""
        return changelog.track(
            conn,
            kind,
            "transaccion",
            target.fingerprint,
            edit_log.subject(target),
            merchant=target.merchant,
            fingerprints=[target.fingerprint],
        )

    def track_link(
        conn: sqlite3.Connection, kind: str, link_id: int
    ) -> AbstractContextManager[changelog.Draft]:
        """La entrada de bitácora de un cambio sobre un vínculo entero (grupo, cambio)."""
        return changelog.track(
            conn, kind, "vinculo", str(link_id), edit_log.link_subject(conn, link_id)
        )

    def apply_shared(conn: sqlite3.Connection, target: Movement, body: SharedBody | None) -> None:
        """`body`: el reparto (crea un grupo, suma el gasto a `link_id` o cambia su reparto);
        None quita el gasto de su grupo (el último gasto borra el grupo)."""
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
            raise links.AlreadyLinked("el gasto ya está en otro grupo: quítalo de ese primero")
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
            raise HTTPException(404, "grupo desconocido") from None

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
        """Enlaza un crédito o anota uno a mano en el grupo (dentro de la transacción)."""
        if body.credit is not None:
            credit = find_tx(conn, body.credit)
            links_view.check_reimbursement(ctx, link_id, credit)
            links.add_reimbursement(conn, link_id, credit.fingerprint)
            return
        entry = body.manual
        if entry is None:
            raise HTTPException(422, "manda un crédito (`credit`) o uno a mano (`manual`)")
        state = ctx.groups.get(link_id)
        if state is None:
            raise links.LinkError("el grupo no tiene gastos presentes")
        if entry.day < state.first.day:
            raise links.LinkError("el reembolso no puede ser antes del gasto")
        links.add_manual(
            conn,
            link_id,
            Decimal(entry.amount_cents) / 100,
            entry.day,
            entry.currency or state.first.currency,  # sin moneda: la del gasto más viejo, hoy
            entry.person,
            entry.place,
        )

    @contextmanager
    def link_errors() -> Iterator[None]:
        try:
            yield
        except links.AlreadyLinked as exc:
            raise HTTPException(409, str(exc)) from None
        except sqlite3.IntegrityError as exc:  # otra pestaña lo enlazó a la vez
            raise HTTPException(409, _conflict(exc)) from None
        except links.LinkError as exc:
            raise HTTPException(422, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc) or "grupo desconocido") from None

    @app.post("/api/transactions/{fingerprint}/reimbursements")
    def post_reimbursement(fingerprint: str, body: ReimbursementBody) -> TxOut:
        """Enlaza un crédito importado o anota uno a mano en el grupo del gasto; devuelve el
        gasto al día."""
        if (body.credit is None) == (body.manual is None):
            raise HTTPException(422, "manda un crédito (`credit`) o uno a mano (`manual`)")
        with connection() as conn:
            expense = find_tx(conn, fingerprint)
            ctx = link_context(conn)
            with link_errors(), conn:
                group = links.group_of(conn, fingerprint)
                with track_link(conn, "compartido", group):
                    add_refund(conn, group, body, ctx)
            return tx_out(conn, fingerprint, expense.month)

    @app.delete("/api/transactions/{fingerprint}/reimbursements/manual/{entry_id}")
    def delete_manual(fingerprint: str, entry_id: int) -> TxOut:
        with connection() as conn:
            expense = find_tx(conn, fingerprint)
            with link_errors(), conn:
                group = links.group_of(conn, fingerprint)
                with track_link(conn, "compartido", group):
                    links.remove_manual(conn, group, entry_id)
            return tx_out(conn, fingerprint, expense.month)

    @app.delete("/api/transactions/{fingerprint}/reimbursements/{credit}")
    def delete_reimbursement(fingerprint: str, credit: str) -> TxOut:
        with connection() as conn:
            expense = find_tx(conn, fingerprint)
            with link_errors(), conn:
                group = links.group_of(conn, fingerprint)
                with track_link(conn, "compartido", group):
                    links.remove_reimbursement(conn, group, credit)
            return tx_out(conn, fingerprint, expense.month)

    @app.delete("/api/reimbursements/{credit}", status_code=204)
    def delete_reimbursement_of_credit(credit: str) -> Response:
        """Desenlaza un crédito desde su lado, por su vínculo: sirve aunque el grupo no tenga
        gastos presentes (vínculo dormido). 404 si el crédito no es un reembolso."""
        with connection() as conn:
            owner = links.load(conn).reimbursed(credit)
            if owner is None:
                raise HTTPException(404, "ese crédito no es un reembolso")
            with conn, track_link(conn, "compartido", owner.id):
                links.remove_reimbursement(conn, owner.id, credit)
        return Response(status_code=204)

    @app.get("/api/transactions/{fingerprint}/reimbursement-candidates")
    def get_reimbursement_candidates(fingerprint: str) -> CandidatesOut:
        """Para un gasto compartido, los créditos que pueden reembolsar su grupo; para un
        crédito, los grupos con pendiente que puede reembolsar."""
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

    # --- Grupos compartidos (por id) ---------------------------------------------------------

    def group_out(conn: sqlite3.Connection, link_id: int) -> SharedOut:
        view = link_context(conn).group_view(link_id)
        if view is None:
            raise HTTPException(404, "grupo desconocido")
        return SharedOut.of(view)

    # Antes de `/api/shared/{link_id}`: `/api/shared/new-candidates` no es un id.
    shared_routes.register(app, connection, load_flow, parse_accounts, today)

    @app.get("/api/shared/open")
    def get_open_groups() -> list[GroupRefOut]:
        """Grupos con pendiente, los más recientes primero («Sumarlo a un grupo»)."""
        with connection() as conn:
            ctx = link_context(conn)
        return [GroupRefOut.ref(g) for g in shared_math.open_groups(ctx.groups)]

    @app.get("/api/shared/{link_id}")
    def get_group(link_id: int) -> SharedOut:
        with connection() as conn:
            return group_out(conn, link_id)

    @app.patch("/api/shared/{link_id}")
    def patch_group(link_id: int, body: GroupPatch) -> SharedOut:
        """Nombre, «Con quién» y "No me lo van a pagar" del grupo."""
        given = body.model_fields_set
        with connection() as conn:
            with link_errors(), conn, track_link(conn, "compartido", link_id):
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
        """Suma un gasto sin vínculo al grupo, con su reparto."""
        with connection() as conn:
            target = find_tx(conn, body.fingerprint)
            with link_errors(), conn, track_link(conn, "compartido", link_id):
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
        """Cambia el reparto de un gasto del grupo."""
        with connection() as conn:
            target = find_tx(conn, fingerprint)
            owner = links.load(conn).shared_for(fingerprint)
            if owner is None or owner.id != link_id:
                raise HTTPException(404, "ese gasto no está en el grupo")
            with link_errors(), conn, track_link(conn, "compartido", link_id):
                links.set_shared(conn, fingerprint, shared_math.gross(target), **split_args(body))
            return group_out(conn, link_id)

    @app.delete("/api/shared/{link_id}/expenses/{fingerprint}")
    def delete_group_expense(link_id: int, fingerprint: str) -> Response:
        """Quita el gasto del grupo (los reembolsos se quedan). Con el último gasto se borra el
        grupo y sus reembolsos quedan libres: 204. Si no, el grupo al día."""
        with connection() as conn:
            owner = links.load(conn).shared_for(fingerprint)
            if owner is None or owner.id != link_id:
                raise HTTPException(404, "ese gasto no está en el grupo")
            with conn, track_link(conn, "compartido", link_id):
                deleted = links.unshare(conn, fingerprint)
            if deleted:
                return Response(status_code=204)
            return JSONResponse(group_out(conn, link_id).model_dump())

    @app.get("/api/shared/{link_id}/expense-candidates")
    def get_group_expense_candidates(link_id: int) -> list[CandidateOut]:
        """«Agregar otro gasto»: gastos sin vínculo a ±120 días, ordenados y marcados."""
        with connection() as conn:
            ctx = link_context(conn)
        state = ctx.groups.get(link_id)
        if state is None:
            raise HTTPException(404, "grupo desconocido")
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
            raise HTTPException(404, "grupo desconocido")
        return credit_candidates(ctx, link_id, places)

    @app.post("/api/shared/{link_id}/reimbursements")
    def post_group_reimbursement(link_id: int, body: ReimbursementBody) -> SharedOut:
        if (body.credit is None) == (body.manual is None):
            raise HTTPException(422, "manda un crédito (`credit`) o uno a mano (`manual`)")
        with connection() as conn:
            ctx = link_context(conn)
            with link_errors(), conn, track_link(conn, "compartido", link_id):
                if ctx.links.group(link_id) is None:
                    raise LookupError(link_id)
                add_refund(conn, link_id, body, ctx)
            return group_out(conn, link_id)

    @app.delete("/api/shared/{link_id}/reimbursements/{credit}")
    def delete_group_reimbursement(link_id: int, credit: str) -> SharedOut:
        with connection() as conn:
            with link_errors(), conn, track_link(conn, "compartido", link_id):
                links.remove_reimbursement(conn, link_id, credit)
            return group_out(conn, link_id)

    @app.delete("/api/shared/{link_id}/manual/{entry_id}")
    def delete_group_manual(link_id: int, entry_id: int) -> SharedOut:
        with connection() as conn:
            with link_errors(), conn, track_link(conn, "compartido", link_id):
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
            raise HTTPException(404, "cambio desconocido")
        return ExchangeOut.of(state, tuple(links_view.linked_tx(m, ctx.labels) for m in state.legs))

    def legs_of(conn: sqlite3.Connection, fingerprints: Sequence[str]) -> list[Movement]:
        flow = {m.fingerprint: m for m in load_flow(conn)}
        missing = [fp for fp in fingerprints if fp not in flow]
        if missing:
            raise HTTPException(404, "transacción desconocida")
        return [flow[fp] for fp in dict.fromkeys(fingerprints)]

    @app.get("/api/transactions/{fingerprint}/exchange-candidates")
    def get_exchange_candidates(fingerprint: str) -> list[CandidateOut]:
        """Patas posibles, ordenadas y marcadas (`primary`): sin cambio, de la otra moneda y en
        dirección contraria (±30 días), por cercanía a la tasa del mes; en un cambio con
        pendiente, solo el lado que falta y lo que cabe en el pendiente (ver
        `exchanges.candidates`)."""
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
                with conn, track_link(conn, "cambio", 0) as draft:
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
            raise HTTPException(404, "cambio desconocido")
        return list(state.legs)

    @app.post("/api/exchanges/{exchange_id}/legs")
    def post_legs(exchange_id: int, body: LegsBody) -> ExchangeOut:
        with connection() as conn:
            ctx = link_context(conn)
            current = current_legs(ctx, exchange_id)
            new = legs_of(conn, body.fingerprints)
            try:
                links_view.check_legs(ctx, new, current)
                with conn, track_link(conn, "cambio", exchange_id):
                    links.add_legs(conn, exchange_id, [m.fingerprint for m in new])
            except links.AlreadyLinked as exc:
                raise HTTPException(409, str(exc)) from None
            except links.LinkError as exc:
                raise HTTPException(422, str(exc)) from None
            return exchange_out(conn, exchange_id)

    @app.patch("/api/exchanges/{exchange_id}")
    def patch_exchange(exchange_id: int, body: ExchangePatch) -> ExchangeOut:
        """Tasa acordada (null: la implícita) y «Cambio completo» (`closed`)."""
        rate = body.agreed_rate if "agreed_rate" in body.model_fields_set else ...
        with connection() as conn:
            current_legs(link_context(conn), exchange_id)
            try:
                with conn, track_link(conn, "cambio", exchange_id):
                    links.update_exchange(conn, exchange_id, agreed_rate=rate, closed=body.closed)
            except links.LinkError as exc:
                raise HTTPException(422, str(exc)) from None
            return exchange_out(conn, exchange_id)

    @app.delete("/api/exchanges/{exchange_id}/legs/{fingerprint}")
    def delete_leg(exchange_id: int, fingerprint: str) -> Response:
        """Quita una pata; si una moneda se queda sin patas, el cambio se deshace (204).
        No pide que las demás patas existan: un cambio dormido (le falta una pata o ya no
        cuadra) también se puede desarmar desde la pata que queda. Si lo que queda no forma un
        cambio, también se deshace (204).
        """
        with connection() as conn:
            stored = stored_exchange(conn, exchange_id)
            if fingerprint not in stored.legs:
                raise HTTPException(404, "esa transacción no es una pata del cambio")
            flow = {m.fingerprint: m for m in load_flow(conn)}
            rest = [flow[leg] for leg in stored.legs if leg != fingerprint and leg in flow]
            with conn, track_link(conn, "cambio", exchange_id):
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
            raise HTTPException(404, "cambio desconocido")
        return found

    @app.delete("/api/exchanges/{exchange_id}", status_code=204)
    def delete_exchange(exchange_id: int) -> Response:
        """Deshace el cambio (sus patas vuelven a su categoría); 404 si no existe."""
        with connection() as conn:
            stored_exchange(conn, exchange_id)
            with conn, track_link(conn, "cambio", exchange_id):
                links.delete_exchange(conn, exchange_id)
        return Response(status_code=204)

    @app.get("/api/one-off-suggestions")
    def get_one_off_suggestions(
        month: RequiredMonth, accounts: AccountKeys = None
    ) -> list[OneOffSuggestionOut]:
        with connection() as conn:
            infos = account_data.account_infos(conn)
            flow = load_flow(conn)
            # Las reglas miran la historia de las mismas cuentas: una compra rara en la
            # tarjeta elegida se juzga contra lo que se compra con ella.
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
                raise HTTPException(404, "transacción desconocida") from None
            with conn, track_tx(conn, "revisado", target) as draft:
                draft.before = "por revisar" if body.dismissed else "no es único"
                draft.after = "no es único" if body.dismissed else "por revisar"
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
        """Todas, también las ocultas (`hidden`): los selectores las dejan fuera."""
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
        """Entrada «palabras clave»: afecta a las transacciones que cambian de categoría."""
        known = catalog.load(conn)
        current = known.by_id(category_id)
        before_flow = {m.fingerprint: m.ref for m in load_flow(conn, known)}
        with changelog.track(
            conn,
            "palabras_clave",
            "categoria",
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
        """Las transacciones que hoy están en la categoría."""
        known = catalog.load(conn)
        found = known.by_id(category_id)
        if found is None:
            return set()
        return {m.fingerprint for m in load_flow(conn, known) if m.ref == found.ref}

    @app.patch("/api/categories/{category_id}")
    def patch_category(category_id: int, body: CategoryPatch) -> CategoryOut:
        """Lo ausente no cambia; todo o nada (un error no deja cambios a medias)."""
        color = body.color if "color" in body.model_fields_set else catalog.KEEP
        with connection() as conn:
            try:
                with conn:
                    current = catalog.load(conn).by_id(category_id)
                    with changelog.track(
                        conn,
                        "categoria_tipo",
                        "categoria",
                        str(category_id),
                        current.name if current is not None else str(category_id),
                        before=None if current is None else current.kind,
                        after=body.kind,
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
        """Sus correcciones y palabras clave pasan a `reassign_to` (obligatorio si las tiene)."""
        with connection() as conn:
            try:
                with conn:
                    known = catalog.load(conn)
                    current = known.by_id(category_id)
                    target = None if reassign_to is None else known.by_id(reassign_to)
                    with changelog.track(
                        conn,
                        "categoria_borrada",
                        "categoria",
                        str(category_id),
                        current.name if current is not None else str(category_id),
                        before=current.name if current is not None else None,
                        after=f"borrada (pasa a {target.name})" if target else "borrada",
                        fingerprints=in_category(conn, category_id),
                    ):
                        catalog.delete(conn, category_id, reassign_to)
            except catalog.CategoryError as exc:
                raise category_error(exc) from None
        return Response(status_code=204)

    @app.post("/api/categories/{category_id}/preview")
    def preview_category(category_id: int, body: PreviewBody) -> PreviewOut:
        """Qué movería dar estas palabras clave a la categoría; no guarda nada."""
        with connection() as conn:
            known = catalog.load(conn)
            if known.by_id(category_id) is None:
                raise HTTPException(404, f"categoría desconocida: {category_id}")
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
            raise HTTPException(422, "la tasa debe ser mayor que cero")
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
        return JSONResponse({"detail": "no existe"}, status_code=404)

    if static_dir is not None:
        _mount_spa(app, static_dir)
    return app


def local_mode(fixed: Workspace) -> Mode:
    """El board de siempre: solo loopback, la misma base en cada petición, cualquier autor."""
    return Mode(
        name="local",
        provider=FixedProvider(fixed),
        allowed_hosts=tuple(ALLOWED_HOSTS),
        authors=changelog.AUTHORS,
    )


def _refusal(request: Request, mode: Mode) -> Response | None:
    """La respuesta que corta la petición antes de su ruta, si la hay: falta `X-Finanzas` en un
    método que escribe, autor no aceptado, ruta bloqueada en el modo o cuerpo demasiado grande."""
    if request.method not in SAFE_METHODS and request.headers.get("x-finanzas") != "1":
        return JSONResponse({"detail": "falta la cabecera X-Finanzas"}, status_code=403)
    author = request.headers.get("x-finanzas-autor", "usuario")
    if author not in changelog.AUTHORS:
        return JSONResponse({"detail": "autor desconocido"}, status_code=400)
    if author not in mode.authors:
        return JSONResponse({"detail": f"autor no aceptado en modo {mode.name}"}, status_code=403)
    path = request.url.path
    if any(path == prefix or path.startswith(f"{prefix}/") for prefix in mode.blocked):
        return JSONResponse({"detail": f"no disponible en modo {mode.name}"}, status_code=403)
    if mode.max_body is not None and request.method not in SAFE_METHODS:
        return _body_refusal(request, mode.max_body)
    return None


def _body_refusal(request: Request, limit: int) -> Response | None:
    """413 si el cuerpo declarado pasa de `limit`; 411 si se manda por partes sin largo."""
    length = request.headers.get("content-length")
    if length is None:
        if request.headers.get("transfer-encoding"):
            return JSONResponse({"detail": "falta Content-Length"}, status_code=411)
        return None
    if not (length.isascii() and length.isdigit()) or int(length) > limit:
        return JSONResponse({"detail": "el cuerpo es demasiado grande"}, status_code=413)
    return None


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    root = static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        try:
            candidate = (root / path).resolve()
        except ValueError:  # p. ej. byte nulo en la ruta
            return FileResponse(root / "index.html")
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
