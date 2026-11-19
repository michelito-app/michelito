"""Schema 18: every stored value moves from the pre-rename Spanish vocabulary to English.

The old -> new maps live in `legacy`. The migration runs first in `db`'s migration transaction
(so the older steps already see English values) and has two parts:

- `rebuild`: the tables whose CHECK lists old values (`categories.kind`, `review_marks.kind`,
  `recurring_marks.cadence`, `change_log.author` and `change_log.target_type`) are rebuilt with
  the English list, translating those columns while copying (SQLite cannot change a CHECK in
  place). It needs foreign keys off, like the other rebuilds (`needs_rebuild`).
- `translate`: every other column that can hold an old value is updated in place, including the
  change log's JSON (`changes`), its row keys (`change_log_rows`, format
  `table:<json list of primary-key values>`) and its fingerprints, so entries recorded before
  the migration can still be undone. It runs once (`user_version` below 18).

Statement parser names are translated separately (`translate_parsers`), before `db` recreates
the partial unique indexes whose `WHERE` lists them.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from michelito import legacy

VERSION = 18

Translate = Callable[[Any], Any]
# Rebuilds `table` from `sql` (its new CREATE statement), copying each column through the SQL
# expression in `select` (column -> expression; a missing column is copied as is).
Rebuild = Callable[[sqlite3.Connection, str, str, Mapping[str, str]], None]

_ENUMS: Mapping[str, Mapping[str, str]] = {
    "category_kind": legacy.CATEGORY_KINDS,
    "review_kind": legacy.REVIEW_KINDS,
    "cadence": legacy.CADENCES,
    "group": legacy.RECURRING_GROUPS,
    "author": legacy.LOG_AUTHORS,
    "target_type": legacy.LOG_TARGET_TYPES,
    "log_kind": legacy.LOG_KINDS,
    "source": legacy.DOCUMENT_SOURCES,
    "sender": legacy.MESSAGE_SENDERS,
    "parser": legacy.PARSER_NAMES,
}

# Tables with a CHECK over old values: column -> enum (the CHECK list and the column use it).
_CHECKED: Mapping[str, Mapping[str, str]] = {
    "categories": {"kind": "category_kind"},
    "review_marks": {"kind": "review_kind"},
    "recurring_marks": {"cadence": "cadence"},
    "change_log": {"author": "author", "target_type": "target_type"},
}


def _enum(name: str) -> Translate:
    values = _ENUMS[name]
    return lambda value: values.get(value, value) if isinstance(value, str) else value


def _key(value: Any) -> Any:
    return legacy.translate_key(value) if isinstance(value, str) else value


# What each column of the tables the change log tracks may hold, so the same translation applies
# to the table, to the rows stored in `change_log.changes` and to the row keys.
_TRACKED_COLUMNS: Mapping[str, Mapping[str, Translate]] = {
    "categories": {"kind": _enum("category_kind")},
    "review_marks": {"kind": _enum("review_kind"), "fingerprint": _key},
    "recurring_marks": {"cadence": _enum("cadence"), "group_key": _enum("group"), "merchant": _key},
    "recurring_unions": {"merchant": _key, "target": _key},
    "transaction_notes": {"fingerprint": _key},
    "link_members": {"fingerprint": _key},
    "one_off_dismissals": {"fingerprint": _key},
    "links": {"account_key": _key, "source": _key},
    "cash_entries": {"account_key": _key},
    "reserve_dismissals": {"key": _key},
}


def _accounts(value: Any) -> Any:
    """`insights.accounts`: account keys joined by commas."""
    if not isinstance(value, str):
        return value
    return ",".join(legacy.translate_key(part) for part in value.split(","))


def _log_target(target_type: Any, target: Any) -> Any:
    """`change_log.target` by its (already English) `target_type`."""
    if not isinstance(target, str):
        return target
    if target_type in ("transaction", "cash_box", "link"):
        return legacy.translate_key(target)
    if target_type == "recurring":
        return legacy.translate_series_text(target)
    if target_type == "category":
        return legacy.LOG_TARGETS.get(target, target)
    return target


def _log_subject(target_type: Any, target: Any, subject: Any) -> Any:
    """`change_log.subject`: display text, left as it is, except when it repeats the target's
    machine key (a dismissed reserve suggestion), which is translated like the target."""
    if isinstance(subject, str) and subject == target:
        return _log_target(target_type, subject)
    return subject


# Columns translated in place: (table, column, translation). The `_CHECKED` columns are done by
# the rebuild; the change log's target, subject, JSON and row keys have their own functions.
_PLAIN: tuple[tuple[str, str, Translate], ...] = (
    *(
        (table, column, translate)
        for table, columns in _TRACKED_COLUMNS.items()
        for column, translate in columns.items()
        if column not in _CHECKED.get(table, {})
    ),
    ("accounts", "key", _key),
    ("account_currency", "account_key", _key),
    ("reviewed_fingerprints", "fingerprint", _key),
    ("change_log_fingerprints", "fingerprint", _key),
    ("change_log", "kind", _enum("log_kind")),
    ("change_log", "merchant", _key),
    ("insights", "accounts", _accounts),
    ("gmail_messages", "source", _enum("source")),
    ("gmail_messages", "sender", _enum("sender")),
    ("documents", "source", _enum("source")),
    ("documents", "parser", _enum("parser")),
)


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return found is not None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]


def _table_sql(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return None if row is None else str(row[0])


_LITERAL = re.compile(r"'([^']*)'")


def _checked_values(table: str) -> Mapping[str, str]:
    found: dict[str, str] = {}
    for enum in _CHECKED[table].values():
        found.update(_ENUMS[enum])
    return found


def _english_sql(table: str, sql: str) -> str:
    values = _checked_values(table)
    return _LITERAL.sub(lambda m: f"'{values.get(m.group(1), m.group(1))}'", sql)


def _outdated(conn: sqlite3.Connection) -> list[str]:
    """The tables whose CHECK still lists an old value."""
    found = []
    for table in _CHECKED:
        sql = _table_sql(conn, table)
        if sql is not None and _english_sql(table, sql) != sql:
            found.append(table)
    return found


def needs_rebuild(conn: sqlite3.Connection) -> bool:
    return bool(_outdated(conn))


def _register(conn: sqlite3.Connection) -> None:
    for name in _ENUMS:
        conn.create_function(f"v18_{name}", 1, _enum(name), deterministic=True)


def rebuild(conn: sqlite3.Connection, rebuild_table: Rebuild) -> list[str]:
    """Rebuilds the tables with old CHECK lists (translating the checked columns); returns them
    and the tables that point to them (for the foreign-key check)."""
    _register(conn)
    rebuilt = []
    for table in _outdated(conn):
        sql = str(_table_sql(conn, table))
        select = {column: f'v18_{enum}("{column}")' for column, enum in _CHECKED[table].items()}
        rebuild_table(conn, table, _english_sql(table, sql), select)
        rebuilt.append(table)
    return [*rebuilt, *_children(conn, rebuilt)]


def _children(conn: sqlite3.Connection, parents: Iterable[str]) -> list[str]:
    wanted = set(parents)
    tables = [
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        if not str(row[0]).startswith("sqlite_")
    ]
    return [
        table
        for table in tables
        if any(fk[2] in wanted for fk in conn.execute(f"PRAGMA foreign_key_list({table})"))
    ]


def translate_parsers(conn: sqlite3.Connection) -> None:
    """Statement parser names (before the indexes that list them are recreated)."""
    if not _exists(conn, "statements"):
        return
    for old, new in legacy.PARSER_NAMES.items():
        conn.execute("UPDATE statements SET parser = ? WHERE parser = ?", (new, old))


def translate(conn: sqlite3.Connection) -> None:
    """Every other stored old value (once: only below schema 18)."""
    if int(conn.execute("PRAGMA user_version").fetchone()[0]) >= VERSION:
        return
    for table, column, function in _PLAIN:
        _update(conn, table, (column,), _single(function))
    _update(
        conn,
        "change_log",
        ("target_type", "target", "subject", "changes"),
        lambda row: (
            row[0],
            _log_target(row[0], row[1]),
            _log_subject(row[0], row[1], row[2]),
            _changes(conn, row[3]),
        ),
    )
    _update(conn, "change_log_rows", ("row_key",), lambda row: (_row_key(conn, row[0]),))


def _single(function: Translate) -> Callable[[tuple[Any, ...]], tuple[Any, ...]]:
    return lambda row: (function(row[0]),)


def _update(
    conn: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    function: Callable[[tuple[Any, ...]], tuple[Any, ...]],
) -> None:
    if not _exists(conn, table) or not set(columns) <= set(_columns(conn, table)):
        return
    names = ", ".join(f'"{c}"' for c in columns)
    sets = ", ".join(f'"{c}" = ?' for c in columns)
    rows = conn.execute(f"SELECT rowid, {names} FROM {table}").fetchall()
    for rowid, *values in rows:
        new = function(tuple(values))
        if new != tuple(values):
            conn.execute(f"UPDATE {table} SET {sets} WHERE rowid = ?", (*new, rowid))


def _row(table: str, row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    columns = _TRACKED_COLUMNS.get(table, {})
    return {c: columns[c](v) if c in columns else v for c, v in row.items()}


def _primary_key(conn: sqlite3.Connection, table: str) -> list[str]:
    info = [row for row in conn.execute(f"PRAGMA table_info({table})") if row[5]]
    return [str(row[1]) for row in sorted(info, key=lambda r: r[5])]


def _row_key(conn: sqlite3.Connection, value: Any) -> Any:
    """`table:<json list of primary-key values>`, with the values translated (same format as
    `changelog_rules.row_key`)."""
    if not isinstance(value, str) or ":" not in value:
        return value
    table, raw = value.split(":", 1)
    columns = _TRACKED_COLUMNS.get(table)
    if columns is None or not _exists(conn, table):
        return value
    try:
        values = json.loads(raw)
    except ValueError:
        return value
    names = _primary_key(conn, table)
    if not isinstance(values, list) or len(values) != len(names):
        return value
    translated = [columns[n](v) if n in columns else v for n, v in zip(names, values, strict=True)]
    if translated == values:
        return value
    return f"{table}:{json.dumps(translated, ensure_ascii=False)}"


def _changes(conn: sqlite3.Connection, value: Any) -> Any:
    """`change_log.changes`: each changed row's key, before and after, and its parent's key."""
    if not isinstance(value, str):
        return value
    changes = json.loads(value)
    translated = []
    for change in changes:
        table = str(change.get("table"))
        item = {
            **change,
            "key": _row(table, change.get("key")),
            "before": _row(table, change.get("before")),
            "after": _row(table, change.get("after")),
        }
        parent = change.get("parent")
        if isinstance(parent, dict) and parent.get("key"):
            item["parent"] = {**parent, "key": _row_key(conn, parent["key"])}
        translated.append(item)
    if translated == changes:
        return value
    return json.dumps(translated, ensure_ascii=False)
