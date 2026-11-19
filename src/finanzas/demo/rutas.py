"""Rutas propias de la demo: sesión (crear la copia), estado de ejemplo, opiniones, uso y eventos.

Todas escriben, así que piden `X-Finanzas: 1` (lo revisa el middleware del board). Ninguna
guarda la IP ni el `demo_id`: la IP solo cuenta copias por día en memoria (`CopyStore`) y la
cookie solo elige la copia y los topes por copia (también en memoria).
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

from finanzas.demo import ejemplo, opiniones, red
from finanzas.demo.copias import CopyStore, DemoFull

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
log = logging.getLogger(__name__)
FULL = "La demo está llena por ahora: vuelve a intentarlo en un rato."
RESTARTS = (
    "Ya empezaste de nuevo hace poco (se puede una vez cada 5 minutos y unas pocas veces al día)."
)
COPY_FULL = (
    "Tu copia de la demo llegó a su límite de tamaño; se reinicia en 24 h o desde «Empezar de "
    "nuevo»."
)
TOO_MANY = (
    "Ya se crearon varias copias de la demo desde tu conexión hoy: vuelve mañana o usa la que "
    "ya tienes."
)
# Eventos clave que se cuentan (por día, sin nada del visitante): método, ruta y su nombre.
_EVENTS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("POST", re.compile(r"/api/budget/activate"), "activar_presupuesto"),
    ("POST", re.compile(r"/api/reserves"), "crear_reserva"),
    ("PATCH", re.compile(r"/api/transactions"), "seleccion_multiple"),
    ("POST", re.compile(r"/api/log/\d+/undo"), "deshacer"),
)


def event_of(method: str, path: str, status: int) -> str | None:
    """El evento clave de una petición que salió bien, si es uno."""
    if not 200 <= status < 300:
        return None
    return next((name for m, rx, name in _EVENTS if m == method and rx.fullmatch(path)), None)


@dataclass(frozen=True)
class Hooks:
    """Lo que las rutas de la demo necesitan de `demo.app`."""

    provider: Any  # DemoProvider (sin importarlo: evita el ciclo)
    store: CopyStore
    feedback: opiniones.Feedback
    opinions: Any  # PerCopy
    samples: Any  # PerCopy
    visits: Any  # PerCopy
    events: Any  # PerCopy (eventos de la interfaz, aparte de las visitas)
    today: Callable[[], date]
    proxies: tuple[red.Network, ...] = ()


class OpinionBody(BaseModel):
    texto: str = Field(max_length=opiniones.TEXT_MAX)
    correo: str | None = Field(default=None, max_length=opiniones.EMAIL_MAX)
    pagina: str | None = Field(default=None, max_length=opiniones.PAGE_MAX)
    ancho: int | None = None
    version: str | None = Field(default=None, max_length=opiniones.VERSION_MAX)
    ref: str | None = Field(default=None, max_length=64)


class VisitBody(BaseModel):
    pantalla: str = Field(max_length=opiniones.PAGE_MAX)


# Eventos que solo ve la interfaz (p. ej. copiar al portapapeles no llega al servidor).
CLIENT_EVENTS = frozenset({"copiar_claude"})


class EventBody(BaseModel):
    evento: str = Field(max_length=40)


class SampleOut(BaseModel):
    cuadra: bool
    estado: str
    detalle: str | None
    transacciones: int
    cuenta: str
    desde: str
    hasta: str
    meses: list[str]


def _copy_id(request: Request, hooks: Hooks) -> str:
    """La copia de la petición; 401 si no tiene (sin sesión no se escribe nada)."""
    copy_id = request.cookies.get(hooks.provider.cookie)
    if copy_id is None or hooks.store.workspace(copy_id) is None:
        raise HTTPException(401, "no hay sesión de la demo: recarga la página")
    return copy_id


def _count(hooks: Hooks, kind: str, key: str) -> None:
    """Un contador nunca tumba la respuesta."""
    try:
        hooks.feedback.count(kind, key)
    except Exception:
        log.exception("no se pudo contar %s %s", kind, key)


def _refused(exc: DemoFull) -> JSONResponse:
    if exc.reason == "llena":
        return JSONResponse({"detail": FULL}, status_code=503)
    detail = RESTARTS if exc.reason == "reinicio" else TOO_MANY
    return JSONResponse({"detail": detail}, status_code=429)


def register(app: FastAPI, connection: Connection, hooks: Hooks) -> None:
    @app.exception_handler(sqlite3.OperationalError)
    def database_error(request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        """La copia llegó a su tope de tamaño (`PRAGMA max_page_count`): 507 con salida."""
        if "full" in str(exc):
            return JSONResponse({"detail": COPY_FULL}, status_code=507)
        log.exception("error de la base en %s", request.url.path, exc_info=exc)
        return JSONResponse({"detail": "error interno"}, status_code=500)

    @app.post("/api/demo/sesion")
    def post_session(request: Request) -> Response:
        """Crea la copia del visitante (si no tiene una viva) y le pone la cookie."""
        if hooks.provider.has_session(request):
            return JSONResponse({"creada": False})
        red.warn_unconfigured_proxy(request, hooks.proxies)
        quotas = red.quota_keys(red.client_ip(request, hooks.proxies))
        try:
            copy_id = hooks.store.create(quotas)
        except DemoFull as exc:
            return _refused(exc)
        response = JSONResponse({"creada": True}, status_code=201)
        hooks.provider.set_cookie(response, copy_id)
        _count(hooks, "copia", "creada")
        return response

    @app.post("/api/demo/reiniciar")
    def post_restart(request: Request) -> Response:
        """«Empezar de nuevo»: reemplaza la copia del visitante por una nueva de la plantilla."""
        copy_id = _copy_id(request, hooks)
        quotas = red.quota_keys(red.client_ip(request, hooks.proxies))
        try:
            fresh = hooks.store.restart(copy_id, quotas)
        except DemoFull as exc:
            return _refused(exc)
        for limits in (hooks.opinions, hooks.samples, hooks.visits, hooks.events):
            limits.transfer(copy_id, fresh)
        response = JSONResponse({"creada": True}, status_code=201)
        hooks.provider.set_cookie(response, fresh)
        return response

    @app.post("/api/demo/estado-ejemplo")
    def post_sample(request: Request) -> SampleOut:
        """Importa el corte siguiente de la tarjeta de ejemplo (ver `demo.ejemplo`)."""
        copy_id = _copy_id(request, hooks)
        if not hooks.samples.take(copy_id):
            raise HTTPException(429, "ya probaste varios estados de ejemplo en esta copia")
        with connection() as conn:
            result = ejemplo.import_next(conn, hooks.today())
        _count(hooks, "evento", "estado_ejemplo")
        return SampleOut(
            cuadra=result.balanced,
            estado=result.status,
            detalle=result.detail,
            transacciones=result.transactions,
            cuenta=result.account,
            desde=result.period_start.isoformat(),
            hasta=result.period_end.isoformat(),
            meses=result.months,
        )

    @app.post("/api/opiniones", status_code=201)
    def post_opinion(request: Request, body: OpinionBody) -> dict[str, bool]:
        copy_id = _copy_id(request, hooks)
        opinion = opiniones.Opinion(
            body.texto, body.correo, body.pagina, body.ancho, body.version, body.ref
        )
        try:
            cleaned = opiniones.clean(opinion)
        except opiniones.InvalidOpinion as exc:
            raise HTTPException(422, str(exc)) from None
        if not hooks.opinions.take(copy_id):
            raise HTTPException(429, "ya enviaste varias opiniones desde esta copia: ¡gracias!")
        try:
            hooks.feedback.save(cleaned)
        except opiniones.FeedbackFull as exc:
            raise HTTPException(503, f"{exc}: vuelve a intentarlo más tarde") from None
        return {"guardada": True}

    @app.post("/api/uso", status_code=204)
    def post_visit(request: Request, body: VisitBody) -> Response:
        """Cuenta una visita a una pantalla (solo pantalla y día; queda en memoria hasta el
        próximo volcado). Pasado el tope por copia, se ignora en silencio."""
        copy_id = _copy_id(request, hooks)
        if hooks.visits.take(copy_id):
            _count(hooks, "visita", opiniones.screen(body.pantalla))
        return Response(status_code=204)

    @app.post("/api/demo/evento", status_code=204)
    def post_event(request: Request, body: EventBody) -> Response:
        """Cuenta un evento de la interfaz (`CLIENT_EVENTS`; solo el nombre y el día). Pasado el
        tope por copia (`events`), se ignora en silencio."""
        if body.evento not in CLIENT_EVENTS:
            raise HTTPException(422, "evento desconocido")
        copy_id = _copy_id(request, hooks)
        if hooks.events.take(copy_id):
            _count(hooks, "evento", body.evento)
        return Response(status_code=204)
