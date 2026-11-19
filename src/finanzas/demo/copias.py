"""Una copia de la base por visitante de la demo, elegida por la cookie `demo_id`.

- La cookie es aleatoria (128 bits, 32 letras hexadecimales) y se valida **por su forma** antes de
  usarla en una ruta: nada que no sea `[0-9a-f]{32}` llega al sistema de archivos.
- Cada copia es una carpeta `<copias>/<id>/` con `finanzas.db` y `titulares.txt`, copiados de la
  plantilla. Se crea en una carpeta temporal y se publica con un `rename` atómico: ninguna
  petición ve una copia a medias, y dos que crean a la vez no se pisan.
- El último uso es la fecha de modificación de la carpeta (se toca a lo más una vez por minuto).
  Las que llevan más de `ttl` sin uso se borran al arrancar y en el mantenimiento de fondo
  (`demo.app`): primero se renombran, así ninguna petición nueva las encuentra; una conexión ya
  abierta sigue sobre el archivo borrado hasta cerrarse.
- Límites: `per_ip` copias nuevas por IP al día (la IP vive **solo en memoria** y se olvida al
  cambiar el día; ver `demo.red` para cuál IP y sus claves), `per_minute_new` copias nuevas por
  minuto entre todos, `max_live` copias vivas (llena, se desaloja la que lleva más de
  `evict_after` sin uso), `min_free` bytes libres en el disco y `per_minute` unidades de costo por
  minuto por copia (`allow_request`: una ruta cara cuesta más).

Un solo proceso: los contadores y el candado viven en memoria (ver README, «Demo»).
"""

from __future__ import annotations

import math
import os
import re
import secrets
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from finanzas.demo import generar
from finanzas.web.workspace import Workspace

COOKIE = "demo_id"
_ID = re.compile(r"[0-9a-f]{32}")
_TOUCH_EVERY = 60.0
_TRASH = ".borrar-"
_WORK = ".nueva-"


class DemoFull(Exception):
    """No se puede crear otra copia ahora (`reason`: «llena», «ip» o «reinicio»)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Limits:
    per_ip: int = 3
    max_live: int = 200
    per_minute_new: int = 20  # copias nuevas por minuto entre todos (un rango no llena la demo)
    per_minute: int = 120  # unidades de costo por minuto por copia (ver `demo.app.COSTS`)
    ttl: float = 24 * 3600.0
    sweep_every: float = 600.0
    evict_after: float = 3600.0  # con la demo llena, se desaloja la más vieja si pasó esto
    min_free: int = 200 * 1024 * 1024  # bytes libres en el disco para crear otra copia
    restart_cooldown: float = 300.0  # «Empezar de nuevo»: uno cada tanto por copia
    restarts_per_day: int = 10  # por clave de IP (en IPv6, más ancho en /56 y /48)
    restarts_per_minute: int = 20  # entre todos


def valid_id(text: str | None) -> bool:
    return text is not None and _ID.fullmatch(text) is not None


class CopyStore:
    """Las copias de la demo bajo `root`, hechas desde la plantilla en `template`."""

    def __init__(
        self,
        root: Path,
        template: Path,
        limits: Limits = Limits(),
        clock: Callable[[], float] = time.time,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.root = root
        self.template = template
        self.limits = limits
        self.clock = clock
        self.today = today
        self._lock = threading.Lock()  # crear, barrer y cambiar la plantilla
        self._rate_lock = threading.Lock()  # contadores por minuto de cada copia
        self._by_ip: dict[str, int] = {}
        self._recent: deque[float] = deque()  # cuándo se crearon las últimas copias
        self._recent_restarts: deque[float] = deque()  # cuándo fueron los últimos reinicios
        self._restarts_by_ip: dict[str, int] = {}
        self._restarted: dict[str, float] = {}  # id -> cuándo nació de un reinicio
        self._ip_day: date | None = None
        self._requests: dict[str, tuple[int, int]] = {}  # id -> (minuto, peticiones)
        self._touched: dict[str, float] = {}
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        self.sweep()

    def workspace(self, copy_id: str | None) -> Workspace | None:
        """La copia de esa cookie, si es válida y existe (la marca como usada). Toca el disco:
        desde el bucle de eventos se llama en un hilo."""
        if not valid_id(copy_id):
            return None
        assert copy_id is not None
        folder = self.root / copy_id
        if not folder.is_dir():
            return None
        self._touch(copy_id, folder)
        return Workspace(folder / generar.DATABASE, folder / generar.HOLDERS)

    def create(self, quotas: Sequence[tuple[str, int]]) -> str:
        """Una copia nueva desde la plantilla; devuelve su id. `DemoFull` si no se puede.
        `quotas`: los cupos en que cuenta (`red.quota_keys`; solo viven en memoria)."""
        with self._lock:
            self._check_ip(quotas)
            self._check_window(self._recent, self.limits.per_minute_new, "llena")
            self._check_disk()
            if self.live() >= self.limits.max_live:
                self.sweep_locked()
                if self.live() >= self.limits.max_live and not self._evict_oldest():
                    raise DemoFull("llena")
            copy_id = self._copy_template()
            for key, _ in quotas:
                self._by_ip[key] = self._by_ip.get(key, 0) + 1
            self._recent.append(self.clock())
            return copy_id

    def restart(self, old: str, quotas: Sequence[tuple[str, int]]) -> str:
        """«Empezar de nuevo»: cambia la copia `old` por una nueva de la plantilla.

        Tiene sus propios topes, aparte de las copias nuevas (no gasta su cupo): uno cada
        `restart_cooldown` segundos por copia (la nueva hereda la espera), `restarts_per_day` por
        clave de IP y `restarts_per_minute` entre todos. El presupuesto del minuto pasa del id
        viejo al nuevo (los demás topes por copia los traslada `demo.app`). `DemoFull("reinicio")`
        si no se puede."""
        with self._lock:
            if not valid_id(old) or not (self.root / old).is_dir():
                raise DemoFull("reinicio")
            now = self.clock()
            if now - self._restarted.get(old, -math.inf) < self.limits.restart_cooldown:
                raise DemoFull("reinicio")
            self._roll_day()
            for key, factor in quotas:
                if self._restarts_by_ip.get(key, 0) >= self.limits.restarts_per_day * factor:
                    raise DemoFull("reinicio")
            self._check_window(self._recent_restarts, self.limits.restarts_per_minute, "llena")
            self._check_disk()
            copy_id = self._copy_template()
            self._remove(old)
            for key, _ in quotas:
                self._restarts_by_ip[key] = self._restarts_by_ip.get(key, 0) + 1
            self._recent_restarts.append(now)
            self._restarted.pop(old, None)
            self._restarted[copy_id] = now
        with self._rate_lock:
            if old in self._requests:
                self._requests[copy_id] = self._requests.pop(old)
        return copy_id

    def _copy_template(self) -> str:
        copy_id = secrets.token_hex(16)
        work = self.root / f"{_WORK}{copy_id}"
        work.mkdir(mode=0o700)
        try:
            for name in (generar.DATABASE, generar.HOLDERS):
                shutil.copyfile(self.template / name, work / name)
                (work / name).chmod(0o600)
            now = self.clock()
            os.utime(work, (now, now))  # el último uso: ahora
            os.rename(work, self.root / copy_id)
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
        return copy_id

    def while_locked(self, action: Callable[[], object]) -> None:
        """Corre `action` sin que se cree ninguna copia a la vez (cambiar la plantilla)."""
        with self._lock:
            action()

    def allow_request(self, copy_id: str, cost: int = 1) -> bool:
        """Cobra `cost` unidades a la copia en este minuto; False (sin cobrar) si no le
        alcanzan."""
        minute = int(self.clock() // 60)
        with self._rate_lock:
            seen, used = self._requests.get(copy_id, (minute, 0))
            used = used if seen == minute else 0
            if used + cost > self.limits.per_minute:
                return False
            self._requests[copy_id] = (minute, used + cost)
            if len(self._requests) > 4 * self.limits.max_live:
                self._requests = {k: v for k, v in self._requests.items() if v[0] == minute}
        return True

    def live(self) -> int:
        return len(self.live_ids())

    def live_ids(self) -> set[str]:
        return {entry.name for entry in os.scandir(self.root) if valid_id(entry.name)}

    def sweep(self) -> int:
        with self._lock:
            return self.sweep_locked()

    def sweep_locked(self) -> int:
        """Borra las copias sin uso por más de `ttl` y lo que quedó a medias; cuántas borró."""
        now = self.clock()
        removed = 0
        for entry in os.scandir(self.root):
            name = entry.name
            stale = now - entry.stat().st_mtime > self.limits.ttl
            if valid_id(name) and stale:
                self._remove(name)
                removed += 1
            elif name.startswith((_TRASH, _WORK)) and (name.startswith(_TRASH) or stale):
                shutil.rmtree(entry.path, ignore_errors=True)
        return removed

    def _remove(self, name: str) -> None:
        """Borra una copia: primero la renombra (nadie la encuentra más) y luego la borra."""
        trash = self.root / f"{_TRASH}{name}"
        try:
            os.rename(self.root / name, trash)
        except FileNotFoundError:
            return
        shutil.rmtree(trash, ignore_errors=True)
        self._touched.pop(name, None)
        self._restarted.pop(name, None)

    def _evict_oldest(self) -> bool:
        """Con la demo llena: desaloja la copia más tiempo sin uso si pasó `evict_after`."""
        entries = [e for e in os.scandir(self.root) if valid_id(e.name)]
        if not entries:
            return False
        oldest = min(entries, key=lambda e: e.stat().st_mtime)
        if self.clock() - oldest.stat().st_mtime <= self.limits.evict_after:
            return False
        self._remove(oldest.name)
        return True

    def _touch(self, copy_id: str, folder: Path) -> None:
        now = self.clock()
        if now - self._touched.get(copy_id, 0.0) < _TOUCH_EVERY:
            return
        self._touched[copy_id] = now
        try:
            os.utime(folder, (now, now))
        except FileNotFoundError:  # la borró el barrido entre tanto
            self._touched.pop(copy_id, None)

    def _check_window(self, recent: deque[float], limit: int, reason: str) -> None:
        """Tope de cuántas veces por minuto (entre todos)."""
        now = self.clock()
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= limit:
            raise DemoFull(reason)

    def _roll_day(self) -> None:
        today = self.today()
        if self._ip_day != today:  # un día nuevo: se olvidan todas las IP
            self._ip_day = today
            self._by_ip = {}
            self._restarts_by_ip = {}

    def _check_disk(self) -> None:
        if shutil.disk_usage(self.root).free < self.limits.min_free:
            raise DemoFull("llena")

    def _check_ip(self, quotas: Iterable[tuple[str, int]]) -> None:
        self._roll_day()
        for key, factor in quotas:
            if self._by_ip.get(key, 0) >= self.limits.per_ip * factor:
                raise DemoFull("ip")
