"""Remitentes de estados de cuenta del usuario: `fuentes.toml` en la carpeta de datos.

El archivo es opcional. Sin él, `sync` usa `config.DEFAULT_SOURCES`, igual que siempre; con él,
usa solo las fuentes que lista (no se mezclan con las de omisión). El formato está en
`fuentes.ejemplo.toml`, en la raíz del repositorio:

    [[fuente]]
    nombre = "banco"                         # carpeta en raw/ y nombre en `--source`
    consulta = "from:estados@banco.example"  # búsqueda de Gmail
    extensiones = [".pdf"]                   # adjuntos que se guardan
    interpretar = true                       # opcional; false: solo se archiva

Un archivo que no se entiende detiene el comando con un mensaje claro (`SourcesError`): nunca se
cae en silencio a las fuentes de omisión, porque eso bajaría correos que el usuario quitó.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from finanzas import importer
from finanzas.config import ARCHIVE_ONLY, DEFAULT_SOURCES, Source, archive_only

_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")  # va a una ruta: sin "/", "..", ni espacios
_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}")
_KEYS = frozenset({"nombre", "consulta", "extensiones", "interpretar"})
# Nombres que ya usa `finanzas importar` (fuente en la base y carpeta en raw/).
RESERVED_NAMES = frozenset({importer.SOURCE, importer.FOLDER})


class SourcesError(ValueError):
    """`fuentes.toml` existe pero no se puede usar; el mensaje dice qué corregir."""


def load_sources(path: Path) -> tuple[Source, ...]:
    """Las fuentes del archivo del usuario o, si no existe, las de omisión."""
    if not path.exists():
        return DEFAULT_SOURCES
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SourcesError(f"{path}: no se pudo leer ({exc})") from exc
    return parse_sources(data, str(path))


def parse_sources(data: dict[str, Any], origin: str) -> tuple[Source, ...]:
    """Valida el contenido ya leído de un `fuentes.toml`."""
    extra = set(data) - {"fuente"}
    if extra:
        raise SourcesError(f"{origin}: claves desconocidas {sorted(extra)}; se espera [[fuente]]")
    entries = data.get("fuente")
    if not isinstance(entries, list) or not entries:
        raise SourcesError(f"{origin}: no hay ninguna [[fuente]]")
    sources = tuple(_source(entry, f"{origin}, fuente {i}") for i, entry in enumerate(entries, 1))
    names = [s.name for s in sources]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise SourcesError(f"{origin}: nombres repetidos {repeated}")
    return sources


def archived_names(configured: tuple[Source, ...]) -> frozenset[str]:
    """Las fuentes cuyos documentos solo se archivan.

    Las del archivo con `interpretar = false` y, además, las de omisión que se archivan (las
    AFP): sus documentos ya descargados siguen sin interpretarse aunque el usuario las haya
    quitado de su `fuentes.toml`, salvo que las redefina con `interpretar = true`."""
    interpreted = {s.name for s in configured if s.interpret}
    return archive_only(configured) | (ARCHIVE_ONLY - interpreted)


def _source(entry: object, where: str) -> Source:
    if not isinstance(entry, dict):
        raise SourcesError(f"{where}: debe ser una tabla [[fuente]]")
    extra = set(entry) - _KEYS
    if extra:
        raise SourcesError(f"{where}: claves desconocidas {sorted(extra)}")
    name = entry.get("nombre")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise SourcesError(
            f"{where}: «nombre» debe ser minúsculas, dígitos, «-» o «_» (máx. 40), sin espacios"
        )
    if name in RESERVED_NAMES:
        raise SourcesError(f"{where}: «{name}» está reservado para `finanzas importar`")
    query = entry.get("consulta")
    if not isinstance(query, str) or not query.strip():
        raise SourcesError(f"{where} ({name}): falta «consulta», la búsqueda de Gmail")
    extensions = entry.get("extensiones")
    if (
        not isinstance(extensions, list)
        or not extensions
        or not all(isinstance(e, str) and _EXTENSION.fullmatch(e) for e in extensions)
    ):
        raise SourcesError(
            f'{where} ({name}): «extensiones» es una lista como [".pdf"], en minúsculas'
        )
    interpret = entry.get("interpretar", True)
    if not isinstance(interpret, bool):
        raise SourcesError(f"{where} ({name}): «interpretar» es true o false")
    return Source(name, query.strip(), tuple(extensions), interpret=interpret)
