"""La demo pública: el mismo FastAPI del board, con una copia de la base por visitante.

`create_demo_app(settings)` genera la plantilla (una vez, al arrancar), abre el almacén de copias
(`copias.CopyStore`) y `opiniones.db`, y arma el `Mode` de la demo para `create_app`:

- base: la copia del visitante según la cookie `demo_id` (`DemoProvider`); sin cookie válida no se
  abre ninguna. La copia se crea con `POST /api/demo/sesion` (la interfaz lo pide al cargar);
- hosts: el público (`--host-publico`) y loopback (la revisión de salud y las pruebas locales);
- autores: solo el usuario (`X-Finanzas-Autor: claude` se rechaza); `X-Finanzas` sigue exigido;
- cuerpo de hasta `max_body` bytes; rutas del sistema (sync, Gmail, secretos, importar archivos)
  responden 403;
- rutas propias (`demo.rutas`): sesión, «Empezar de nuevo», estado de ejemplo, opiniones, uso y
  eventos de la interfaz («copiar para Claude»);
- trabajo acotado: una petición a la vez por copia, `workers` a la vez en total (con espera
  acotada), un presupuesto de costo por minuto por copia (`COSTS`: las rutas caras cuentan más)
  y un tope de tamaño por copia (`PRAGMA max_page_count`; al llenarse, 507);
- mantenimiento en un hilo de fondo (`Maintenance`): barrido de copias, volcado de los conteos
  de uso, poda de los topes en memoria y plantilla nueva al cambiar de mes.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from importlib import metadata
from pathlib import Path

import anyio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from finanzas.demo import generar, opiniones, red, rutas
from finanzas.demo.copias import CopyStore, Limits, valid_id
from finanzas.web.app import create_app
from finanzas.web.workspace import Mode, Resolution

PRODUCT = "Michelito"
DEFAULT_HOST = "demo.michelito.app"
NOTICE = "Demo con datos inventados · tus cambios se borran en 24 h"
LOOPBACK = ("127.0.0.1", "localhost")
# Rutas del sistema: no existen en la API de hoy, pero si alguna llega, en la demo no se sirve.
BLOCKED = ("/api/sync", "/api/gmail", "/api/secretos", "/api/importar", "/api/sistema")
# Nombre de la cookie: con `Secure`, el prefijo `__Host-` obliga al navegador a que vaya solo por
# HTTPS, sin `Domain` y con `Path=/`; sin `Secure` (pruebas por http) el prefijo no se acepta.
SECURE_COOKIE = "__Host-demo_id"
PLAIN_COOKIE = "demo_id"
# Costo de una petición en el presupuesto por minuto de la copia (por omisión, 1). Medido sobre la
# plantilla en una laptop: compare ≈ 0.95 s, review/history ≈ 0.3 s, dossier ≈ 0.15 s, summary
# ≈ 0.13 s, el resto ≈ 0.05 s; el costo es ≈ lo que tarda en unidades de 50 ms (redondeado hacia
# arriba en el dossier: arma el Resumen y «Para revisar» del mes).
COSTS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"/api/reports/compare"), 20),
    (re.compile(r"/api/review/history"), 6),
    (re.compile(r"/api/insights/.+"), 5),
    (re.compile(r"/api/dossier"), 4),
    (re.compile(r"/api/summary"), 3),
    (re.compile(r"/api/demo/estado-ejemplo"), 3),
)
# Sin base ni trabajo: no esperan turno ni gastan presupuesto.
FREE = frozenset({"/api/health", "/api/modo"})
log = logging.getLogger(__name__)


def cost_of(path: str) -> int:
    return next((cost for rx, cost in COSTS if rx.fullmatch(path)), 1)


@dataclass(frozen=True)
class Settings:
    """Configuración de la demo (ver `finanzas demo --help`)."""

    data: Path  # carpeta de la demo: plantilla, copias y opiniones.db (nunca la de datos reales)
    public_host: str = DEFAULT_HOST
    secure_cookie: bool = True  # False solo para probar por http en la máquina
    repo: str = ""
    limits: Limits = field(default_factory=Limits)
    max_body: int = 64 * 1024
    opinions_per_copy: int = 10
    samples_per_copy: int = 6
    visits_per_copy: int = 500
    events_per_copy: int = 50  # eventos de la interfaz («copiar para Claude»)
    proxies: tuple[str, ...] = ()  # proxies confiables (IP o red); sin ellos no se mira XFF
    copy_extra: int = 5 * 1024 * 1024  # lo que puede crecer una copia sobre la plantilla
    workers: int = 4  # peticiones con base a la vez, entre todas las copias
    copy_wait: float = 15.0  # segundos máximos esperando el turno de la copia (luego 429)
    global_wait: float = 10.0  # segundos máximos esperando un turno global (luego 503)
    feedback_caps: opiniones.Caps = field(default_factory=opiniones.Caps)
    background: bool = True  # hilo de mantenimiento (las pruebas lo corren a mano)

    @property
    def template(self) -> Path:
        return self.data / "plantilla"

    @property
    def copies(self) -> Path:
        return self.data / "copias"

    @property
    def feedback(self) -> Path:
        return self.data / opiniones.FILENAME


class PerCopy:
    """Topes por copia que viven en memoria (opiniones, estados de ejemplo, visitas)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def take(self, copy_id: str) -> bool:
        with self._lock:
            used = self._counts.get(copy_id, 0)
            if used >= self.limit:
                return False
            self._counts[copy_id] = used + 1
            return True

    def transfer(self, old: str, new: str) -> None:
        """Lo usado por `old` pasa a `new` («Empezar de nuevo» no limpia los topes)."""
        with self._lock:
            if old in self._counts:
                self._counts[new] = self._counts.pop(old)

    def prune(self, alive: Iterable[str]) -> None:
        """Olvida las copias que ya no existen."""
        keep = set(alive)
        with self._lock:
            self._counts = {k: v for k, v in self._counts.items() if k in keep}


class SizeCap:
    """El tope de páginas de cada conexión a una copia: plantilla + `extra` bytes."""

    def __init__(self, template: Path, extra: int) -> None:
        self.template = template
        self.extra = extra
        self.pages = 0
        self.measure()

    def measure(self) -> None:
        with sqlite3.connect(self.template / generar.DATABASE) as conn:
            size = conn.execute("PRAGMA page_size").fetchone()[0]
        total = (self.template / generar.DATABASE).stat().st_size + self.extra
        self.pages = math.ceil(total / size)

    def __call__(self, conn: sqlite3.Connection) -> None:
        conn.execute(f"PRAGMA max_page_count = {int(self.pages)}")


class Turns:
    """Una petición a la vez por copia y `workers` a la vez en total, con espera acotada. Vive
    en el bucle de eventos (primitivas de anyio): esperar no ocupa hilos."""

    def __init__(self, workers: int, copy_wait: float, global_wait: float) -> None:
        self.workers = workers
        self.copy_wait = copy_wait
        self.global_wait = global_wait
        self._global: anyio.Semaphore | None = None
        # Un semáforo de 1 por copia (no un Lock: lo suelta quien sea, no solo quien lo tomó).
        self._copies: dict[str, anyio.Semaphore] = {}

    async def take(self, copy_id: str) -> Callable[[], None] | Response:
        """Un turno (devuelve con qué soltarlo) o la respuesta 429/503 si no llegó a tiempo."""
        if self._global is None:
            self._global = anyio.Semaphore(self.workers)
        if len(self._copies) > 1000:  # poda: las que nadie tiene tomadas
            self._copies = {k: v for k, v in self._copies.items() if v.value == 0}
        lock = self._copies.setdefault(copy_id, anyio.Semaphore(1))
        if not await _within(lock.acquire, self.copy_wait):
            return _busy(429, "tu copia de la demo está ocupada: vuelve a intentarlo")
        semaphore = self._global
        if not await _within(semaphore.acquire, self.global_wait):
            lock.release()
            return _busy(503, "la demo está ocupada: vuelve a intentarlo en unos segundos")

        def release() -> None:
            semaphore.release()
            lock.release()

        return release


async def _within(acquire: Callable[[], Awaitable[None]], seconds: float) -> bool:
    """Espera `acquire` como mucho `seconds`; True si lo consiguió."""
    with anyio.move_on_after(seconds):
        await acquire()
        return True
    return False


def _busy(status: int, detail: str) -> Response:
    return JSONResponse({"detail": detail}, status_code=status, headers={"Retry-After": "5"})


@dataclass(frozen=True)
class DemoProvider:
    """La base de cada petición: la copia de su cookie (si es válida y existe)."""

    store: CopyStore
    feedback: opiniones.Feedback
    secure_cookie: bool
    turns: Turns

    @property
    def cookie(self) -> str:
        return SECURE_COOKIE if self.secure_cookie else PLAIN_COOKIE

    async def resolve(self, request: Request) -> Resolution:
        path = request.url.path
        copy_id = request.cookies.get(self.cookie)
        if not path.startswith("/api/") or not valid_id(copy_id):
            return Resolution(None)
        assert copy_id is not None
        workspace = await anyio.to_thread.run_sync(self.store.workspace, copy_id)
        if workspace is None:
            return Resolution(None)
        finish = self._finisher(request)
        if path in FREE:
            return Resolution(workspace, finish=finish)
        if not self.store.allow_request(copy_id, cost_of(path)):
            refusal = _busy(429, "demasiadas peticiones: espera un minuto")
            return Resolution(None, refusal=refusal)
        turn = await self.turns.take(copy_id)
        if isinstance(turn, Response):
            return Resolution(None, refusal=turn)
        return Resolution(workspace, finish=finish, release=turn)

    def has_session(self, request: Request) -> bool:
        return self.store.workspace(request.cookies.get(self.cookie)) is not None

    def set_cookie(self, response: Response, copy_id: str) -> None:
        response.set_cookie(
            self.cookie,
            copy_id,
            max_age=int(self.store.limits.ttl),
            httponly=True,
            secure=self.secure_cookie,
            samesite="lax",
            path="/",
        )

    def _finisher(self, request: Request) -> Callable[[Response], None]:
        def finish(response: Response) -> None:  # corre en un hilo (ver `create_app`)
            if request.url.path == "/api/modo":  # la cookie dura lo que la copia
                self.set_cookie(response, request.cookies.get(self.cookie, ""))
            event = rutas.event_of(request.method, request.url.path, response.status_code)
            if event is not None:
                try:
                    self.feedback.count("evento", event)
                except Exception:  # un contador no debe tumbar la respuesta
                    log.exception("no se pudo contar el evento %s", event)

        return finish


class Maintenance:
    """Lo que corre de fondo: barrido, volcado de conteos, poda y plantilla del mes."""

    def __init__(
        self,
        settings: Settings,
        store: CopyStore,
        feedback: opiniones.Feedback,
        per_copy: Iterable[PerCopy],
        size: SizeCap,
        today: Callable[[], date],
    ) -> None:
        self.settings = settings
        self.store = store
        self.feedback = feedback
        self.per_copy = tuple(per_copy)
        self.size = size
        self.today = today
        self.month = today().strftime("%Y-%m")
        self._stop = threading.Event()

    def run_once(self) -> None:
        for step in (self.feedback.flush, self.sweep, self.refresh_template):
            try:
                step()
            except Exception:  # el mantenimiento sigue aunque un paso falle
                log.exception("falló el mantenimiento de la demo (%s)", step.__name__)

    def sweep(self) -> None:
        self.store.sweep()
        alive = self.store.live_ids()
        for limits in self.per_copy:
            limits.prune(alive)

    def refresh_template(self) -> None:
        """Mes nuevo: plantilla nueva (atómica, sin crear copias a la vez). Las copias vivas
        conservan la suya."""
        today = self.today()
        month = today.strftime("%Y-%m")
        if month == self.month:
            return
        self.store.while_locked(lambda: generar.build_template(self.settings.template, today))
        self.size.measure()
        self.month = month
        log.info("plantilla nueva para %s", month)

    def start(self) -> None:
        def loop() -> None:
            beat = 60.0
            ticks = 0
            while not self._stop.wait(beat):
                ticks += 1
                self.flush()
                if ticks * beat >= self.settings.limits.sweep_every:
                    ticks = 0
                    self.run_once()

        threading.Thread(target=loop, name="demo-mantenimiento", daemon=True).start()

    def flush(self) -> None:
        try:
            self.feedback.flush()
        except Exception:
            log.exception("no se pudieron volcar los conteos de uso")

    def stop(self) -> None:
        self._stop.set()
        self.flush()


def version() -> str:
    try:
        return metadata.version("finanzas")
    except metadata.PackageNotFoundError:  # pragma: no cover - siempre está instalado
        return "0"


def create_demo_app(
    settings: Settings,
    static_dir: Path | None = None,
    today: Callable[[], date] = date.today,
) -> FastAPI:
    """La app de la demo; genera la plantilla antes de servir."""
    generar.use_demo_providers()
    built = generar.build_template(settings.template, today())
    log.info("plantilla generada en %.2f s", built.seconds)
    store = CopyStore(settings.copies, settings.template, settings.limits, today=today)
    feedback = opiniones.Feedback(settings.feedback, settings.feedback_caps)
    turns = Turns(settings.workers, settings.copy_wait, settings.global_wait)
    provider = DemoProvider(store, feedback, settings.secure_cookie, turns)
    size = SizeCap(settings.template, settings.copy_extra)
    hooks = rutas.Hooks(
        provider=provider,
        store=store,
        feedback=feedback,
        opinions=PerCopy(settings.opinions_per_copy),
        samples=PerCopy(settings.samples_per_copy),
        visits=PerCopy(settings.visits_per_copy),
        events=PerCopy(settings.events_per_copy),
        today=today,
        proxies=red.networks(settings.proxies),
    )
    mode = Mode(
        name="demo",
        provider=provider,
        allowed_hosts=(settings.public_host, *LOOPBACK),
        authors=("usuario",),
        blocked=BLOCKED,
        max_body=settings.max_body,
        info={"nombre": PRODUCT, "version": version(), "repo": settings.repo, "aviso": NOTICE},
        register=lambda app, connection, load_flow: rutas.register(app, connection, hooks),
        on_connect=size,
    )
    app = create_app(built.database, static_dir, today, built.holders, mode=mode)
    maintenance = Maintenance(
        settings,
        store,
        feedback,
        (hooks.opinions, hooks.samples, hooks.visits, hooks.events),
        size,
        today,
    )
    if settings.background:
        maintenance.start()
    app.state.template_seconds = built.seconds
    app.state.maintenance = maintenance
    app.state.store = store
    return app
