"""Tags as stored (schema 30, `migrations_v30`): create, rename, delete, tag and untag.

A manual tag has a name unique once folded (like category names). A group tag (`group_id`)
belongs to a shared group: `sync_group` creates or renames it with the group, the database
deletes it with the group, and it cannot be renamed or deleted on its own (`GroupTag`).

Nothing here commits: the caller wraps each change in `with conn:` and the change log.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from michelito.analysis.catalog import fold
from michelito.i18n import t
from michelito.migrations_v30 import NAME_MAX

TARGET_KINDS = ("loan", "installment")


class TagError(Exception):
    """A tag change that cannot be made (400)."""


class DuplicateTag(TagError):
    """A tag with that name already exists (409)."""


class GroupTag(TagError):
    """A group's tag is renamed and deleted with its group (400)."""


@dataclass(frozen=True)
class Tag:
    id: int
    name: str
    group_id: int | None
    color: str | None
    created_at: str


def _tag(row: sqlite3.Row | tuple) -> Tag:
    return Tag(
        id=int(row[0]),
        name=str(row[1]),
        group_id=None if row[2] is None else int(row[2]),
        color=None if row[3] is None else str(row[3]),
        created_at=str(row[4]),
    )


_COLUMNS = "id, name, group_id, color, created_at"


def load(conn: sqlite3.Connection) -> list[Tag]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM tags ORDER BY id").fetchall()
    return [_tag(r) for r in rows]


def get(conn: sqlite3.Connection, tag_id: int) -> Tag:
    row = conn.execute(f"SELECT {_COLUMNS} FROM tags WHERE id = ?", (tag_id,)).fetchone()
    if row is None:
        raise KeyError(tag_id)
    return _tag(row)


def _clean(name: str) -> str:
    text = " ".join(name.split())
    if not text:
        raise TagError(t("analysis.tags.name_empty"))
    if len(text) > NAME_MAX:
        raise TagError(t("analysis.tags.name_too_long", max=NAME_MAX))
    return text


def _check_free(conn: sqlite3.Connection, name: str, tag_id: int | None = None) -> None:
    """A manual tag cannot take a name any tag already has (group tags included)."""
    for other_id, other in conn.execute("SELECT id, name FROM tags"):
        if other_id != tag_id and fold(other) == fold(name):
            raise DuplicateTag(t("analysis.tags.duplicate", name=other))


def _manual(conn: sqlite3.Connection, tag_id: int) -> Tag:
    tag = get(conn, tag_id)
    if tag.group_id is not None:
        raise GroupTag(t("analysis.tags.group_tag"))
    return tag


def create(conn: sqlite3.Connection, name: str, color: str | None, now: str) -> Tag:
    text = _clean(name)
    _check_free(conn, text)
    cursor = conn.execute(
        "INSERT INTO tags (name, folded, color, created_at) VALUES (?, ?, ?, ?)",
        (text, fold(text), color, now),
    )
    return get(conn, int(cursor.lastrowid or 0))


def rename(conn: sqlite3.Connection, tag_id: int, name: str) -> None:
    _manual(conn, tag_id)
    text = _clean(name)
    _check_free(conn, text, tag_id)
    conn.execute("UPDATE tags SET name = ?, folded = ? WHERE id = ?", (text, fold(text), tag_id))


def set_color(conn: sqlite3.Connection, tag_id: int, color: str | None) -> None:
    get(conn, tag_id)
    conn.execute("UPDATE tags SET color = ? WHERE id = ?", (color, tag_id))


def delete(conn: sqlite3.Connection, tag_id: int) -> None:
    _manual(conn, tag_id)
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))


def manual(conn: sqlite3.Connection) -> dict[int, set[str]]:
    found: dict[int, set[str]] = {}
    for tag_id, fingerprint in conn.execute("SELECT tag_id, fingerprint FROM transaction_tags"):
        found.setdefault(int(tag_id), set()).add(str(fingerprint))
    return found


def add(conn: sqlite3.Connection, tag_id: int, fingerprints: Iterable[str], now: str) -> int:
    get(conn, tag_id)
    added = 0
    for fingerprint in dict.fromkeys(fingerprints):
        cursor = conn.execute(
            "INSERT OR IGNORE INTO transaction_tags (tag_id, fingerprint, added_at) "
            "VALUES (?, ?, ?)",
            (tag_id, fingerprint, now),
        )
        added += cursor.rowcount
    return added


def remove(conn: sqlite3.Connection, tag_id: int, fingerprints: Iterable[str]) -> int:
    removed = 0
    for fingerprint in dict.fromkeys(fingerprints):
        cursor = conn.execute(
            "DELETE FROM transaction_tags WHERE tag_id = ? AND fingerprint = ?",
            (tag_id, fingerprint),
        )
        removed += cursor.rowcount
    return removed


def targets(conn: sqlite3.Connection) -> dict[int, set[tuple[str, int]]]:
    found: dict[int, set[tuple[str, int]]] = {}
    for tag_id, kind, target_id in conn.execute("SELECT tag_id, kind, target_id FROM tag_targets"):
        found.setdefault(int(tag_id), set()).add((str(kind), int(target_id)))
    return found


def _check_kind(kind: str) -> None:
    if kind not in TARGET_KINDS:
        raise TagError(t("analysis.tags.bad_target"))


def add_target(conn: sqlite3.Connection, tag_id: int, kind: str, target_id: int, now: str) -> None:
    get(conn, tag_id)
    _check_kind(kind)
    conn.execute(
        "INSERT OR IGNORE INTO tag_targets (tag_id, kind, target_id, added_at) VALUES (?, ?, ?, ?)",
        (tag_id, kind, target_id, now),
    )


def remove_target(conn: sqlite3.Connection, tag_id: int, kind: str, target_id: int) -> None:
    _check_kind(kind)
    conn.execute(
        "DELETE FROM tag_targets WHERE tag_id = ? AND kind = ? AND target_id = ?",
        (tag_id, kind, target_id),
    )


def group_tag(conn: sqlite3.Connection, group_id: int) -> int:
    row = conn.execute("SELECT id FROM tags WHERE group_id = ?", (group_id,)).fetchone()
    if row is None:
        raise KeyError(group_id)
    return int(row[0])


def sync_group(conn: sqlite3.Connection, group_id: int, name: str, now: str) -> None:
    """The group's tag, created or renamed to the group's name (unchanged, not unique).
    Before schema 30 (an older migration creating groups) there is no tag table yet: nothing
    to do, the schema 30 backfill gives those groups their tag."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'tags'").fetchone() is None:
        return
    row = conn.execute("SELECT id FROM tags WHERE group_id = ?", (group_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO tags (name, folded, group_id, created_at) VALUES (?, ?, ?, ?)",
            (name, fold(name), group_id, now),
        )
    else:
        conn.execute(
            "UPDATE tags SET name = ?, folded = ? WHERE id = ?", (name, fold(name), int(row[0]))
        )
