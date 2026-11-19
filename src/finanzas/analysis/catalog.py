"""Categorías editables: las del sistema (sembradas de `categories`) y las del usuario.

Cada categoría tiene un `id` (lo que guardan las correcciones y las palabras clave) y una
referencia (`ref`) que usa el análisis:
- una del sistema, la constante de `categories` (su nombre de nacimiento, vía `builtin_key`):
  la lógica (transferencias, préstamos, cargos del banco…) compara contra esas constantes,
  así renombrarla no la rompe;
- una del usuario, `user:<id>`.
El nombre que se muestra sale de la base (`name_of`). Las del sistema se pueden renombrar,
recolorear y ocultar, pero no borrar ni cambiar de tipo; las del usuario, todo. Una oculta
no se ofrece en los selectores, pero sus transacciones la conservan y cuentan.

Palabras clave: se guardan normalizadas como las descripciones (`categories.clean`) y valen
como palabra o frase entera. Si varias coinciden, gana la más larga; en empate, la de la
categoría con menor id.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import cached_property
from typing import get_args

from finanzas.analysis import categories
from finanzas.analysis.categories import Kind

KINDS: tuple[str, ...] = get_args(Kind)
NAME_MAX = 40
KEYWORD_MAX = 60
KEYWORDS_MAX = 50
_USER_PREFIX = "user:"
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
_BUILTIN_ORDER = {ref: index for index, ref in enumerate(categories.ALL)}
_KIND_ORDER = {"gasto": 0, "ingreso": 1, "transferencia": 2}


class CategoryError(ValueError):
    """Pedido inválido sobre una categoría (422 por defecto)."""


class NotFound(CategoryError):
    """La categoría no existe (404)."""


class DuplicateName(CategoryError):
    """Ya hay una categoría con ese nombre (409)."""


class Forbidden(CategoryError):
    """No se permite: borrar una del sistema, cambiarle el tipo o borrar sin destino (400)."""


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    kind: Kind
    color: str | None
    hidden: bool
    builtin_key: str | None
    keywords: tuple[str, ...] = ()

    @property
    def builtin(self) -> bool:
        return self.builtin_key is not None

    @property
    def ref(self) -> str:
        """Referencia estable para el análisis (ver el docstring del módulo)."""
        if self.builtin_key in categories.BUILTIN_KEYS:
            return categories.BUILTIN_KEYS[self.builtin_key]
        return f"{_USER_PREFIX}{self.id}"


@dataclass(frozen=True)
class KeywordHit:
    keyword: str
    category: Category


@dataclass(frozen=True)
class Catalog:
    items: tuple[Category, ...]

    def by_id(self, category_id: int) -> Category | None:
        return next((c for c in self.items if c.id == category_id), None)

    def by_ref(self, ref: str) -> Category | None:
        return self._refs.get(ref)

    @cached_property
    def _refs(self) -> Mapping[str, Category]:
        return {c.ref: c for c in self.items}

    def name_of(self, ref: str) -> str:
        found = self.by_ref(ref)
        return ref if found is None else found.name

    def kind_of(self, ref: str) -> Kind:
        found = self.by_ref(ref)
        return categories.kind_of(ref) if found is None else found.kind

    def kinds(self) -> dict[str, Kind]:
        return {c.ref: c.kind for c in self.items}

    def by_name(self, name: str) -> Category | None:
        """La categoría que hoy se llama así; si no, la que se llamó así antes.

        Antes: un nombre viejo de `categories.canonical` ("Efectivo y transferencias") o el
        nombre de nacimiento de una del sistema renombrada (un enlace viejo).
        """
        wanted = fold(name)
        exact = next((c for c in self.items if fold(c.name) == wanted), None)
        if exact is not None:
            return exact
        return self.by_ref(categories.canonical(name.strip()))

    def keyword_hits(self, text: str) -> list[KeywordHit]:
        """Palabras clave presentes en `text` (ya con `categories.clean`), la que gana primero."""
        padded = f" {text} "
        hits = [
            KeywordHit(word, c) for c in self.items for word in c.keywords if f" {word} " in padded
        ]
        return sorted(hits, key=lambda hit: (-len(hit.keyword), hit.category.id))

    def with_keywords(self, category_id: int, keywords: Iterable[str]) -> Catalog:
        """El mismo catálogo con otras palabras clave para una categoría (para previsualizar)."""
        words = normalize_keywords(keywords)
        found = self.by_id(category_id)
        if words and found is not None:
            check_choosable(found)
        return Catalog(
            tuple(replace(c, keywords=words) if c.id == category_id else c for c in self.items)
        )

    def selectable(self) -> tuple[Category, ...]:
        return tuple(c for c in self.items if not c.hidden)


def fold(text: str) -> str:
    """Para comparar nombres: sin acentos, sin mayúsculas, sin espacios de más."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.casefold().split())


def normalize_keyword(keyword: str) -> str:
    return categories.clean(keyword)


def normalize_keywords(keywords: Iterable[str]) -> tuple[str, ...]:
    """Normalizadas, sin vacías ni repetidas, en el orden dado. Error si alguna es inválida."""
    words: list[str] = []
    for raw in keywords:
        if len(raw) > KEYWORD_MAX:
            raise CategoryError(f"palabra clave demasiado larga: {raw[:KEYWORD_MAX]}…")
        word = normalize_keyword(raw)
        if not word:
            raise CategoryError(f"palabra clave sin letras ni números: {raw!r}")
        if word not in words:
            words.append(word)
    if len(words) > KEYWORDS_MAX:
        raise CategoryError(f"a lo sumo {KEYWORDS_MAX} palabras clave por categoría")
    return tuple(words)


def _sort_key(item: Category) -> tuple[int, int, str]:
    return (
        _KIND_ORDER[item.kind],
        _BUILTIN_ORDER.get(item.ref, len(_BUILTIN_ORDER)),
        fold(item.name),
    )


def load(conn: sqlite3.Connection) -> Catalog:
    words: dict[int, list[str]] = {}
    for row in conn.execute(
        "SELECT category_id, keyword FROM category_keywords ORDER BY category_id, rowid"
    ):
        words.setdefault(row[0], []).append(row[1])
    items = [
        Category(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            color=row["color"],
            hidden=bool(row["hidden"]),
            builtin_key=row["builtin_key"],
            keywords=tuple(words.get(row["id"], ())),
        )
        for row in conn.execute("SELECT id, name, kind, color, hidden, builtin_key FROM categories")
    ]
    return Catalog(tuple(sorted(items, key=_sort_key)))


def seed_builtins(conn: sqlite3.Connection) -> None:
    """Agrega las categorías del sistema que falten (idempotente; no toca las que están).

    Si el usuario ya usa el nombre de una nueva, la del sistema lleva " (sistema)".
    """
    present = {row[0] for row in conn.execute("SELECT builtin_key FROM categories")}
    taken = {fold(row[0]) for row in conn.execute("SELECT name FROM categories")}
    for key, ref in categories.BUILTIN_KEYS.items():
        if key in present:
            continue
        name = ref if fold(ref) not in taken else f"{ref} (sistema)"
        conn.execute(
            "INSERT INTO categories (name, kind, color, hidden, builtin, builtin_key, created_at) "
            "VALUES (?, ?, NULL, 0, 1, ?, ?)",
            (name, categories.kind_of(ref), key, _now()),
        )
        taken.add(fold(name))


def check_choosable(category: Category) -> None:
    """CategoryError si la categoría solo la pone su vínculo (`categories.LINK_ONLY`)."""
    if category.ref in categories.LINK_ONLY:
        raise CategoryError(
            f"«{category.name}» la pone su vínculo: márcalo desde el detalle de la transacción"
        )


def resolve_ref(conn: sqlite3.Connection, category: str | int) -> int:
    """Id de una categoría dada por id o por referencia del análisis; ValueError si no existe."""
    found = (
        load(conn).by_id(category)
        if isinstance(category, int)
        else load(conn).by_ref(categories.canonical(category))
    )
    if found is None:
        raise CategoryError(f"categoría desconocida: {category}")
    return found.id


def create(conn: sqlite3.Connection, name: str, kind: str, color: str | None = None) -> Category:
    clean_name = _check_name(conn, name, None)
    _check_kind(kind)
    _check_color(color)
    cursor = conn.execute(
        "INSERT INTO categories (name, kind, color, hidden, builtin, builtin_key, created_at) "
        "VALUES (?, ?, ?, 0, 0, NULL, ?)",
        (clean_name, kind, color, _now()),
    )
    return _get(conn, int(cursor.lastrowid or 0))


class _Keep:
    """Valor por defecto de `update`: el campo no se toca."""


KEEP = _Keep()


def update(
    conn: sqlite3.Connection,
    category_id: int,
    *,
    name: str | None = None,
    kind: str | None = None,
    color: str | None | _Keep = KEEP,
    hidden: bool | None = None,
) -> Category:
    """Edita lo pedido; `color=None` vuelve al color automático. Error sin escribir nada."""
    current = _get(conn, category_id)
    values: dict[str, object] = {}
    if name is not None:
        values["name"] = _check_name(conn, name, category_id)
    if kind is not None and kind != current.kind:
        if current.builtin:
            raise Forbidden("el tipo de una categoría del sistema no se puede cambiar")
        _check_kind(kind)
        values["kind"] = kind
    if not isinstance(color, _Keep):
        _check_color(color)
        values["color"] = color
    if hidden is not None:
        values["hidden"] = int(hidden)
    for column, value in values.items():  # nombres de una lista cerrada
        conn.execute(f"UPDATE categories SET {column} = ? WHERE id = ?", (value, category_id))
    return _get(conn, category_id)


def in_use(conn: sqlite3.Connection, category_id: int) -> bool:
    """Tiene correcciones o palabras clave: borrarla movería transacciones."""
    for table in ("merchant_categories", "transaction_notes", "category_keywords"):
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE category_id = ? LIMIT 1", (category_id,)
        ).fetchone()
        if row is not None:
            return True
    # Una reserva (esquema 17) de esa categoría.
    row = conn.execute(
        "SELECT 1 FROM links WHERE kind = 'reserve' AND category_id = ? LIMIT 1", (category_id,)
    ).fetchone()
    return row is not None


def delete(conn: sqlite3.Connection, category_id: int, reassign_to: int | None) -> None:
    """Borra una del usuario; lo que la usaba (correcciones, palabras clave, reservas) pasa a
    `reassign_to`; su tope del presupuesto se borra con ella (en cascada).

    Sin destino solo se puede si nada la usa. Se hace en la transacción de quien llama.
    """
    current = _get(conn, category_id)
    if current.builtin:
        raise Forbidden("una categoría del sistema no se puede borrar (se puede ocultar)")
    if reassign_to is None:
        if in_use(conn, category_id):
            raise Forbidden("la categoría tiene transacciones: elige a cuál pasan")
    else:
        if reassign_to == category_id:
            raise Forbidden("el destino tiene que ser otra categoría")
        check_choosable(_get(conn, reassign_to))
        for table in ("merchant_categories", "transaction_notes"):
            conn.execute(
                f"UPDATE {table} SET category_id = ? WHERE category_id = ?",
                (reassign_to, category_id),
            )
        conn.execute(
            "UPDATE links SET category_id = ? WHERE kind = 'reserve' AND category_id = ?",
            (reassign_to, category_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO category_keywords (category_id, keyword) "
            "SELECT ?, keyword FROM category_keywords WHERE category_id = ?",
            (reassign_to, category_id),
        )
    conn.execute("DELETE FROM category_keywords WHERE category_id = ?", (category_id,))
    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def set_keywords(conn: sqlite3.Connection, category_id: int, keywords: Sequence[str]) -> Category:
    current = _get(conn, category_id)
    words = normalize_keywords(keywords)
    if words:
        check_choosable(current)
    conn.execute("DELETE FROM category_keywords WHERE category_id = ?", (category_id,))
    conn.executemany(
        "INSERT INTO category_keywords (category_id, keyword) VALUES (?, ?)",
        [(category_id, word) for word in words],
    )
    return _get(conn, category_id)


def _get(conn: sqlite3.Connection, category_id: int) -> Category:
    found = load(conn).by_id(category_id)
    if found is None:
        raise NotFound(f"categoría desconocida: {category_id}")
    return found


def _check_name(conn: sqlite3.Connection, name: str, own_id: int | None) -> str:
    clean_name = " ".join(name.split())
    if not clean_name:
        raise CategoryError("el nombre no puede quedar vacío")
    if len(clean_name) > NAME_MAX:
        raise CategoryError(f"el nombre tiene más de {NAME_MAX} letras")
    wanted = fold(clean_name)
    for row in conn.execute("SELECT id, name FROM categories"):
        if row[0] != own_id and fold(row[1]) == wanted:
            raise DuplicateName(f"ya hay una categoría «{row[1]}»")
    return clean_name


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise CategoryError(f"tipo desconocido: {kind}")


def _check_color(color: str | None) -> None:
    if color is not None and not _COLOR.fullmatch(color):
        raise CategoryError(f"color inválido (se espera #RRGGBB): {color}")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
