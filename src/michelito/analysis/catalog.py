"""Editable categories: the system ones (seeded from `categories`) and the user's.

Each category has an `id` (what corrections and keywords store) and a reference (`ref`) the
analysis uses:
- a system one, the `categories` constant (its birth name, via `builtin_key`): the logic
  (transfers, loans, bank charges...) compares against those constants, so renaming it does
  not break it;
- a user one, `user:<id>`.
The displayed name comes from the database (`name_of`). System categories can be renamed,
recolored and hidden, but not deleted nor have their kind changed; user ones, everything. A
hidden one is not offered in the pickers, but its transactions keep it and still count.

Keywords: stored normalized like descriptions (`categories.clean`) and they match as a whole
word or phrase. When several match, the longest wins; on a tie, the one of the category with
the lowest id.
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

from michelito.analysis import categories
from michelito.analysis.categories import Kind
from michelito.i18n import t

KINDS: tuple[str, ...] = get_args(Kind)
NAME_MAX = 40
KEYWORD_MAX = 60
KEYWORDS_MAX = 50
_USER_PREFIX = "user:"
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
_BUILTIN_ORDER = {ref: index for index, ref in enumerate(categories.ALL)}
_KIND_ORDER = {"expense": 0, "income": 1, "transfer": 2}


class CategoryError(ValueError):
    """Invalid request about a category (422 by default)."""


class NotFound(CategoryError):
    """The category does not exist (404)."""


class DuplicateName(CategoryError):
    """A category with that name already exists (409)."""


class Forbidden(CategoryError):
    """Not allowed: deleting a system one, changing its kind or deleting without a target (400)."""


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
        """Stable reference for the analysis (see the module docstring)."""
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
        """The category called that today; otherwise the one called that before.

        Before: a former name from `categories.canonical` (`categories._LEGACY_NAMES`) or the
        birth name of a renamed system category (an old link).
        """
        wanted = fold(name)
        exact = next((c for c in self.items if fold(c.name) == wanted), None)
        if exact is not None:
            return exact
        return self.by_ref(categories.canonical(name.strip()))

    def keyword_hits(self, text: str) -> list[KeywordHit]:
        """Keywords present in `text` (already through `categories.clean`), the winner first."""
        padded = f" {text} "
        hits = [
            KeywordHit(word, c) for c in self.items for word in c.keywords if f" {word} " in padded
        ]
        return sorted(hits, key=lambda hit: (-len(hit.keyword), hit.category.id))

    def with_keywords(self, category_id: int, keywords: Iterable[str]) -> Catalog:
        """The same catalog with other keywords for one category (for previews)."""
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
    """For comparing names: no accents, no upper case, no extra spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.casefold().split())


def normalize_keyword(keyword: str) -> str:
    return categories.clean(keyword)


def normalize_keywords(keywords: Iterable[str]) -> tuple[str, ...]:
    """Normalized, without empty or repeated ones, in the given order. Error if one is invalid."""
    words: list[str] = []
    for raw in keywords:
        if len(raw) > KEYWORD_MAX:
            raise CategoryError(t("analysis.catalog.keyword_too_long", keyword=raw[:KEYWORD_MAX]))
        word = normalize_keyword(raw)
        if not word:
            raise CategoryError(t("analysis.catalog.keyword_empty", keyword=repr(raw)))
        if word not in words:
            words.append(word)
    if len(words) > KEYWORDS_MAX:
        raise CategoryError(t("analysis.catalog.too_many_keywords", max=KEYWORDS_MAX))
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
    """Add the missing system categories (idempotent; leaves the existing ones alone).

    If the user already uses the name of a new one, the system one gets a suffix
    (`analysis.catalog.system_suffix`).
    """
    present = {row[0] for row in conn.execute("SELECT builtin_key FROM categories")}
    taken = {fold(row[0]) for row in conn.execute("SELECT name FROM categories")}
    for key, ref in categories.BUILTIN_KEYS.items():
        if key in present:
            continue
        name = ref if fold(ref) not in taken else t("analysis.catalog.system_suffix", name=ref)
        conn.execute(
            "INSERT INTO categories (name, kind, color, hidden, builtin, builtin_key, created_at) "
            "VALUES (?, ?, NULL, 0, 1, ?, ?)",
            (name, categories.kind_of(ref), key, _now()),
        )
        taken.add(fold(name))


def check_choosable(category: Category) -> None:
    """CategoryError if only its link sets the category (`categories.LINK_ONLY`)."""
    if category.ref in categories.LINK_ONLY:
        raise CategoryError(t("analysis.catalog.link_only", name=category.name))


def resolve_ref(conn: sqlite3.Connection, category: str | int) -> int:
    """Id of a category given by id or by analysis reference; ValueError if it does not exist."""
    found = (
        load(conn).by_id(category)
        if isinstance(category, int)
        else load(conn).by_ref(categories.canonical(category))
    )
    if found is None:
        raise CategoryError(t("analysis.catalog.unknown", category=category))
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
    """Default value for `update`: the field is left alone."""


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
    """Edit what was asked; `color=None` goes back to the automatic color. Errors write nothing."""
    current = _get(conn, category_id)
    values: dict[str, object] = {}
    if name is not None:
        values["name"] = _check_name(conn, name, category_id)
    if kind is not None and kind != current.kind:
        if current.builtin:
            raise Forbidden(t("analysis.catalog.builtin_kind"))
        _check_kind(kind)
        values["kind"] = kind
    if not isinstance(color, _Keep):
        _check_color(color)
        values["color"] = color
    if hidden is not None:
        values["hidden"] = int(hidden)
    for column, value in values.items():  # names from a closed list
        conn.execute(f"UPDATE categories SET {column} = ? WHERE id = ?", (value, category_id))
    return _get(conn, category_id)


def in_use(conn: sqlite3.Connection, category_id: int) -> bool:
    """It has corrections or keywords: deleting it would move transactions."""
    for table in ("merchant_categories", "transaction_notes", "category_keywords"):
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE category_id = ? LIMIT 1", (category_id,)
        ).fetchone()
        if row is not None:
            return True
    # A reserve (schema 17) of that category.
    row = conn.execute(
        "SELECT 1 FROM links WHERE kind = 'reserve' AND category_id = ? LIMIT 1", (category_id,)
    ).fetchone()
    return row is not None


def delete(conn: sqlite3.Connection, category_id: int, reassign_to: int | None) -> None:
    """Delete a user category; whatever used it (corrections, keywords, reserves) moves to
    `reassign_to`; its budget cap is deleted with it (cascade).

    Without a target it is only allowed when nothing uses it. Runs in the caller's transaction.
    """
    current = _get(conn, category_id)
    if current.builtin:
        raise Forbidden(t("analysis.catalog.builtin_delete"))
    if reassign_to is None:
        if in_use(conn, category_id):
            raise Forbidden(t("analysis.catalog.in_use"))
    else:
        if reassign_to == category_id:
            raise Forbidden(t("analysis.catalog.same_target"))
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
        raise NotFound(t("analysis.catalog.unknown", category=category_id))
    return found


def _check_name(conn: sqlite3.Connection, name: str, own_id: int | None) -> str:
    clean_name = " ".join(name.split())
    if not clean_name:
        raise CategoryError(t("analysis.catalog.name_empty"))
    if len(clean_name) > NAME_MAX:
        raise CategoryError(t("analysis.catalog.name_too_long", max=NAME_MAX))
    wanted = fold(clean_name)
    for row in conn.execute("SELECT id, name FROM categories"):
        if row[0] != own_id and fold(row[1]) == wanted:
            raise DuplicateName(t("analysis.catalog.duplicate_name", name=row[1]))
    return clean_name


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise CategoryError(t("analysis.catalog.unknown_kind", kind=kind))


def _check_color(color: str | None) -> None:
    if color is not None and not _COLOR.fullmatch(color):
        raise CategoryError(t("analysis.catalog.invalid_color", color=color))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
