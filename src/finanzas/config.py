"""Rutas, fuentes de Gmail y constantes del proyecto."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DATA_DIR_ENV = "FINANZAS_DATA_DIR"
DEFAULT_DATA_DIR = "~/finanzas-data"

# Desde esta fecha la fase 1 se compromete a tener todo interpretado y validado.
COMMIT_FROM = date(2024, 1, 1)
# Días sin un estado nuevo antes de avisar que algo no llegó.
OVERDUE_DAYS = 45
# Ventana para listar correos que llegaron sin adjunto (avisos).
NOTICE_LOOKBACK_DAYS = 60


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def database(self) -> Path:
        return self.root / "finanzas.db"

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def holders(self) -> Path:
        """Titulares de las cuentas, uno por línea; vive solo en la carpeta de datos."""
        return self.root / "titulares.txt"

    @property
    def sources(self) -> Path:
        """Remitentes propios (opcional); sin este archivo se usan `DEFAULT_SOURCES`."""
        return self.root / "fuentes.toml"


@dataclass(frozen=True)
class Source:
    """Un remitente de estados de cuenta y qué adjuntos guardar de él."""

    name: str
    query: str
    extensions: tuple[str, ...]
    interpret: bool = True  # False: se archiva sin intentar interpretarlo


# Remitentes por omisión: los que `sync` usa si no existe `fuentes.toml` en la carpeta de
# datos (ver `fuentes.ejemplo.toml` y `finanzas.sources`).
DEFAULT_SOURCES: tuple[Source, ...] = (
    Source("popular", "from:estados@popularenlinea.com", (".pdf",)),
    Source(
        "bhd",
        "from:servicios@bhd.com.do subject:(estado OR estados) subject:cuenta",
        (".pdf",),
    ),
    Source(
        "afp_reservas",
        "from:estadoscta@afpreservas.com.do",
        (".pdf", ".jpg", ".jpeg"),
        interpret=False,
    ),
    Source("afp_siembra", "from:estadodecuenta@afpsiembra.com", (".pdf",), interpret=False),
    Source("afp_crecer", "from:info@afpcrecer.com.do subject:cuenta", (".pdf",), interpret=False),
)


def archive_only(sources: Iterable[Source]) -> frozenset[str]:
    """Las fuentes que se guardan en el archivo crudo sin interpretarse (las AFP en la fase 1)."""
    return frozenset(s.name for s in sources if not s.interpret)


ARCHIVE_ONLY = archive_only(DEFAULT_SOURCES)


def find_source(name: str, sources: Iterable[Source] = DEFAULT_SOURCES) -> Source:
    for source in sources:
        if source.name == name:
            return source
    raise KeyError(f"fuente desconocida: {name}")


def default_paths() -> Paths:
    return Paths(Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR)).expanduser())


def ensure_private_dir(path: Path) -> Path:
    """Crea la carpeta (si falta) y la deja accesible solo para el usuario."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path
