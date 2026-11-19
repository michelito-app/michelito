"""Opiniones y contadores de uso de la demo, en `opiniones.db` (aparte de las copias).

Las copias se borran a las 24 h; esto no. Por eso aquí **no** entra nada que identifique a un
visitante: ni IP, ni `demo_id`, ni la hora exacta de una visita. Una opinión guarda lo que el
visitante escribió (y su correo, solo si lo dio) más el contexto que manda la interfaz (página,
ancho de pantalla, versión, `ref`). El uso son solo conteos por día: visitas por pantalla, copias
creadas y eventos clave (`EVENTS`).
"""

from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from collections import Counter, deque
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

FILENAME = "opiniones.db"
TEXT_MAX = 2000
EMAIL_MAX = 254
PAGE_MAX = 200
VERSION_MAX = 40
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_REF = re.compile(r"[A-Za-z0-9_.-]{1,64}")
# Pantallas que se cuentan (el primer tramo de la ruta); otra cuenta como «otra».
SCREENS = frozenset(
    {
        "resumen",
        "presupuesto",
        "transacciones",
        "pendientes",
        "compartidos",
        "inversiones",
        "recurrentes",
        "reportes",
        "cuentas",
        "categorias",
        "bitacora",
        "importar",
    }
)
EVENTS = frozenset(
    {
        "activar_presupuesto",
        "crear_reserva",
        "estado_ejemplo",
        "seleccion_multiple",
        "deshacer",
        "copiar_claude",
    }
)
KINDS = ("visita", "copia", "evento")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opiniones (
    id INTEGER PRIMARY KEY,
    creada TEXT NOT NULL,
    texto TEXT NOT NULL,
    correo TEXT,
    pagina TEXT,
    ancho INTEGER,
    version TEXT,
    ref TEXT
);
CREATE TABLE IF NOT EXISTS uso (
    dia TEXT NOT NULL,
    tipo TEXT NOT NULL,
    clave TEXT NOT NULL,
    conteo INTEGER NOT NULL,
    PRIMARY KEY (dia, tipo, clave)
);
"""


class InvalidOpinion(ValueError):
    """La opinión no cumple los límites (texto vacío o largo, correo o `ref` mal formados)."""


@dataclass(frozen=True)
class Opinion:
    texto: str
    correo: str | None = None
    pagina: str | None = None
    ancho: int | None = None
    version: str | None = None
    ref: str | None = None


@dataclass(frozen=True)
class Stored(Opinion):
    id: int = 0
    creada: str = ""


def strip_controls(text: str, keep_newlines: bool = False) -> str:
    """Sin caracteres de control ni de formato (Unicode Cc y Cf: secuencias ANSI, marcas bidi
    como U+202E…), que en la terminal del operador podrían borrar la pantalla o disfrazar el
    texto. `keep_newlines`: el salto de línea se conserva (en el texto de la opinión)."""
    return "".join(
        char
        for char in text
        if (keep_newlines and char == "\n") or unicodedata.category(char) not in ("Cc", "Cf")
    )


def printable(text: str) -> str:
    """Para imprimir lo que escribió un visitante: los controles se ven como `\\u202e`, no
    actúan (el salto de línea queda)."""
    return "".join(
        char
        if char == "\n" or unicodedata.category(char) not in ("Cc", "Cf")
        else f"\\u{ord(char):04x}"
        for char in text
    )


def clean(opinion: Opinion) -> Opinion:
    """La opinión lista para guardar (sin caracteres de control); `InvalidOpinion` si algo no
    cumple."""
    text = strip_controls(opinion.texto.replace("\r\n", "\n"), keep_newlines=True).strip()
    if not text or len(text) > TEXT_MAX:
        raise InvalidOpinion(f"la opinión tiene que tener entre 1 y {TEXT_MAX:,} letras")
    email = strip_controls(opinion.correo or "").strip() or None
    if email is not None and (len(email) > EMAIL_MAX or not _EMAIL.fullmatch(email)):
        raise InvalidOpinion("el correo no parece válido")
    ref = strip_controls(opinion.ref or "").strip() or None
    if ref is not None and not _REF.fullmatch(ref):
        raise InvalidOpinion("ref inválido")
    page = strip_controls(opinion.pagina or "").split("?")[0][:PAGE_MAX] or None
    width = opinion.ancho if opinion.ancho is not None and 0 < opinion.ancho < 20000 else None
    version = strip_controls(opinion.version or "")[:VERSION_MAX] or None
    return Opinion(text, email, page, width, version, ref)


def screen(path: str) -> str:
    """La pantalla que se cuenta para una ruta de la interfaz («/» es «resumen»)."""
    first = path.strip("/").split("/")[0].split("?")[0]
    if not first:
        return "resumen"
    return first if first in SCREENS else "otra"


class FeedbackFull(Exception):
    """Se llegó a un tope global de opiniones (por minuto, por día o del archivo)."""


@dataclass(frozen=True)
class Caps:
    """Topes globales de opiniones (además del tope por copia, en `demo.app`)."""

    per_minute: int = 10
    per_day: int = 300
    rows: int = 10_000
    bytes: int = 20 * 1024 * 1024


class Feedback:
    """`opiniones.db` en `path`; cada operación abre y cierra su conexión.

    Los conteos de uso se juntan en memoria y se escriben de a tandas (`flush`, que corre el
    mantenimiento de fondo cada minuto, y antes de leerlos): una visita no escribe a disco."""

    def __init__(self, path: Path, caps: Caps = Caps()) -> None:
        self.path = path
        self.caps = caps
        self._pending: Counter[tuple[str, str, str]] = Counter()
        self._recent: deque[float] = deque()
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        path.chmod(0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    def save(self, opinion: Opinion, now: datetime | None = None) -> int:
        """Guarda la opinión ya limpia; `FeedbackFull` si se pasó un tope global."""
        ok = clean(opinion)
        moment = now or datetime.now(UTC)
        with self._lock:
            self._check_minute(moment.timestamp())
            with self._connect() as conn:
                self._check_totals(conn, moment.date())
                cursor = conn.execute(
                    "INSERT INTO opiniones (creada, texto, correo, pagina, ancho, version, ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        moment.isoformat(timespec="seconds"),
                        ok.texto,
                        ok.correo,
                        ok.pagina,
                        ok.ancho,
                        ok.version,
                        ok.ref,
                    ),
                )
            self._recent.append(moment.timestamp())
            return int(cursor.lastrowid or 0)

    def _check_minute(self, now: float) -> None:
        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        if len(self._recent) >= self.caps.per_minute:
            raise FeedbackFull("demasiadas opiniones en este minuto")

    def _check_totals(self, conn: sqlite3.Connection, day: date) -> None:
        today = conn.execute(
            "SELECT COUNT(*) FROM opiniones WHERE creada LIKE ?", (f"{day.isoformat()}%",)
        ).fetchone()[0]
        if today >= self.caps.per_day:
            raise FeedbackFull("ya llegaron muchas opiniones hoy")
        total = conn.execute("SELECT COUNT(*) FROM opiniones").fetchone()[0]
        if total >= self.caps.rows or self.path.stat().st_size >= self.caps.bytes:
            raise FeedbackFull("el buzón de opiniones está lleno")

    def count(self, kind: str, key: str, day: date | None = None) -> None:
        """Suma uno al conteo del día (`kind` de `KINDS`; la clave, ya normalizada). Queda en
        memoria hasta el próximo `flush`."""
        if kind not in KINDS:
            raise ValueError(f"tipo de uso desconocido: {kind}")
        when = (day or datetime.now(UTC).date()).isoformat()
        with self._lock:
            self._pending[(when, kind, key)] += 1

    def flush(self) -> None:
        """Escribe los conteos juntados; si falla, vuelven a la cola."""
        with self._lock:
            pending, self._pending = self._pending, Counter()
        if not pending:
            return
        try:
            with self._connect() as conn:
                conn.executemany(
                    "INSERT INTO uso (dia, tipo, clave, conteo) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(dia, tipo, clave) DO UPDATE SET conteo = conteo + excluded.conteo",
                    [(*key, amount) for key, amount in pending.items()],
                )
        except sqlite3.Error:
            with self._lock:
                self._pending.update(pending)
            raise

    def opinions(self) -> list[Stored]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM opiniones ORDER BY id DESC").fetchall()
        return [Stored(**dict(row)) for row in rows]

    def usage(self) -> list[dict[str, str | int]]:
        self.flush()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT dia, tipo, clave, conteo FROM uso ORDER BY dia DESC, tipo, clave"
            ).fetchall()
        return [dict(row) for row in rows]


def as_dict(opinion: Stored) -> dict[str, object]:
    return asdict(opinion)
