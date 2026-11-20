"""The user's statement senders: `sources.toml` in the data folder.

The file is optional. Without it, `sync` uses `config.DEFAULT_SOURCES`, as always; with it, it
uses only the sources it lists (they are not merged with the defaults). The format is in
`sources.example.toml`, at the root of the repository:

    [[source]]
    name = "bank"                           # folder in raw/ and the value of `--source`
    query = "from:statements@bank.example"  # Gmail search
    extensions = [".pdf"]                   # attachments that are saved
    parse = true                            # optional; false: only archived
    alerts = false                          # optional; true: bank alerts (no extensions)

An install from before the English rename may still have the old file (`legacy.SOURCES_FILE`)
with the old Spanish keys: while there is no `sources.toml`, that one is read, with its keys
translated (`legacy.sources_data`).

A file that cannot be understood stops the command with a clear message (`SourcesError`): it never
falls back silently to the defaults, because that would download emails the user removed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from michelito import importer, legacy
from michelito.config import ARCHIVE_ONLY, DEFAULT_SOURCES, Source, archive_only

_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")  # it goes into a path: no "/", "..", nor spaces
_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}")
_TABLE = "source"
_KEYS = frozenset({"name", "query", "extensions", "parse", "alerts"})
# Names that `michelito import` already uses (source in the database and folder in raw/).
# The pre-rename names stay reserved: existing raw folders and documents still use them.
RESERVED_NAMES = frozenset(
    {importer.SOURCE, importer.FOLDER, legacy.IMPORT_SOURCE, legacy.IMPORT_FOLDER}
)


class SourcesError(ValueError):
    """`sources.toml` exists but cannot be used; the message says what to fix."""


def load_sources(path: Path) -> tuple[Source, ...]:
    """The sources in the user's file or, if it does not exist, the defaults."""
    if not path.exists():
        return DEFAULT_SOURCES
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SourcesError(f"{path}: could not be read ({exc})") from exc
    if path.name == legacy.SOURCES_FILE:
        data = legacy.sources_data(data)
    return parse_sources(data, str(path))


def parse_sources(data: dict[str, Any], origin: str) -> tuple[Source, ...]:
    """Validate the already parsed content of a `sources.toml`."""
    extra = set(data) - {_TABLE}
    if extra:
        raise SourcesError(f"{origin}: unknown keys {sorted(extra)}; expected [[source]]")
    entries = data.get(_TABLE)
    if not isinstance(entries, list) or not entries:
        raise SourcesError(f"{origin}: there is no [[source]]")
    sources = tuple(_source(entry, f"{origin}, source {i}") for i, entry in enumerate(entries, 1))
    names = [s.name for s in sources]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise SourcesError(f"{origin}: repeated names {repeated}")
    return sources


def archived_names(configured: tuple[Source, ...]) -> frozenset[str]:
    """The sources whose documents are only archived.

    Those in the file with `parse = false` and, also, the default ones that are archived (the
    AFPs): their already downloaded documents stay unparsed even if the user removed them from
    their `sources.toml`, unless they redefine them with `parse = true`."""
    interpreted = {s.name for s in configured if s.interpret}
    return archive_only(configured) | (ARCHIVE_ONLY - interpreted)


def _source(entry: object, where: str) -> Source:
    if not isinstance(entry, dict):
        raise SourcesError(f"{where}: must be a [[source]] table")
    extra = set(entry) - _KEYS
    if extra:
        raise SourcesError(f"{where}: unknown keys {sorted(extra)}")
    name = entry.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise SourcesError(
            f"{where}: 'name' must be lowercase letters, digits, '-' or '_' (max. 40), no spaces"
        )
    if name in RESERVED_NAMES:
        raise SourcesError(f"{where}: '{name}' is reserved for `michelito import`")
    query = entry.get("query")
    if not isinstance(query, str) or not query.strip():
        raise SourcesError(f"{where} ({name}): 'query', the Gmail search, is missing")
    alerts = entry.get("alerts", False)
    if not isinstance(alerts, bool):
        raise SourcesError(f"{where} ({name}): 'alerts' is true or false")
    if alerts:
        return Source(name, query.strip(), (), alerts=True)
    extensions = entry.get("extensions")
    if (
        not isinstance(extensions, list)
        or not extensions
        or not all(isinstance(e, str) and _EXTENSION.fullmatch(e) for e in extensions)
    ):
        raise SourcesError(f"{where} ({name}): 'extensions' is a lowercase list such as [\".pdf\"]")
    interpret = entry.get("parse", True)
    if not isinstance(interpret, bool):
        raise SourcesError(f"{where} ({name}): 'parse' is true or false")
    return Source(name, query.strip(), tuple(extensions), interpret=interpret)
