"""Backend user-facing text: the Spanish catalog and `t(key, **params)`.

Text the backend produces for people (dossier Markdown, demo notices, API `detail` messages)
lives in catalog modules named `es_<area>.py` next to this file, each defining
`MESSAGES: dict[str, str]` with English dotted keys and `str.format` placeholders. The modules
are discovered on import; a key defined in two modules raises `DuplicateKey`, and an unknown key
raises `KeyError` (so a typo fails loudly in tests instead of showing a key to the user).
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable, Mapping
from types import MappingProxyType

CATALOG_PREFIX = "es_"


class DuplicateKey(ValueError):
    """The same key is defined in more than one catalog module."""


def merge(catalogs: Iterable[tuple[str, Mapping[str, str]]]) -> Mapping[str, str]:
    """One read-only catalog from `(module name, messages)` pairs; `DuplicateKey` on a clash."""
    merged: dict[str, str] = {}
    origin: dict[str, str] = {}
    for name, messages in catalogs:
        for key, text in messages.items():
            if key in merged:
                raise DuplicateKey(f"message key {key!r} is defined in {origin[key]} and {name}")
            merged[key] = text
            origin[key] = name
    return MappingProxyType(merged)


def _discover() -> Mapping[str, str]:
    found = []
    for module in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if module.name.startswith(CATALOG_PREFIX):
            loaded = importlib.import_module(f"{__name__}.{module.name}")
            found.append((module.name, loaded.MESSAGES))
    return merge(found)


MESSAGES: Mapping[str, str] = _discover()


def t(key: str, **params: object) -> str:
    """The Spanish text for `key`, with `params` filled in (`str.format`, so a literal brace is
    written `{{` in the catalog). `KeyError` if the key is not in the catalog or a placeholder
    has no parameter."""
    return MESSAGES[key].format(**params)
