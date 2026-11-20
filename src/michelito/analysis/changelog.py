"""Change log (schema 15): record, read, write the reason and undo.

Every change made from the board is recorded with `track`, inside the same SQLite transaction
as the change: either both stay or neither does. `track` installs (once per connection)
temporary triggers that copy into a temporary table every row inserted, updated or deleted in
the `TRACKED` tables, including cascade deletes; when the block exits without an error it
gathers those rows (`Change`: before and after) and saves the entry. No row that really changed
means no entry.

"Undo" (`undo`) puts every row back to the entry's *before* and is recorded as an entry of its
own (`undoes`). It is offered (`undo_state`) only if: every row is still the *after*
(`changelog_rules.can_undo`); the parent a row goes back to (the link or the category) is the
same as back then (`Change.parent`); and a rehearsal inside a `SAVEPOINT` does not hit a unique
index, does not touch rows the entry did not touch (a cascade over another entry's rows) and
leaves the domain rules standing (`_domain_problem`). Otherwise it says which later entry to
undo first.

Nothing here commits: the caller wraps everything in `with conn:`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

from michelito.analysis import catalog, links
from michelito.analysis.changelog_rules import (
    BATCH_KIND,
    CATEGORY_KIND,
    PARENT_COLUMNS,
    SOFT_DEFAULTS,
    CategoryEdit,
    Change,
    Row,
    can_undo,
    changed_columns,
    describe,
    identity,
    row_key,
    undone_ids,
)
from michelito.i18n import t

AUTHORS = ("user", "claude")
REASON_MAX = 500
# The author of the current request (the `X-Michelito-Author` header; see `web.app`).
AUTHOR: ContextVar[str] = ContextVar("log_author", default="user")

# The tables the change log records, parents before children (the order they are reinserted).
TRACKED = (
    "categories",
    "links",
    "link_members",
    "link_manual",
    "cash_entries",
    "transaction_notes",
    "merchant_categories",
    "category_keywords",
    "recurring_marks",
    "recurring_unions",
    "review_marks",
    "one_off_dismissals",
    "rule_dismissals",
    "budget_caps",
    "reserve_dismissals",
    # Hosted onboarding: "Correct" on a top merchant and the cards put off.
    "reviewed_fingerprints",
    "onboarding_flags",
    # The shared ledger (schema 19).
    "contacts",
    "contact_aliases",
    "ledger_groups",
    "ledger_members",
    "ledger_entries",
    "ledger_splits",
    "ledger_payments",
    "ledger_links",
    "ledger_settings",
    "provisional_decisions",
)
_CAPTURE = "changelog_capture"


class UndoBlocked(Exception):
    """It cannot be undone: the message says why."""


@dataclass
class Draft:
    """What is known about the entry while the change runs (completed at the end)."""

    kind: str
    target_type: str
    target: str
    subject: str
    before: str | None = None  # None: described from the rows
    after: str | None = None
    merchant: str | None = None
    fingerprints: set[str] = field(default_factory=set)
    undoes: int | None = None
    entry_id: int | None = None  # the saved entry (None if nothing changed)


@dataclass(frozen=True)
class Entry:
    id: int
    at: datetime
    author: str
    kind: str
    target_type: str
    target: str
    subject: str
    merchant: str | None
    before_text: str
    after_text: str
    changes: tuple[Change, ...]
    affected: int
    fingerprints: tuple[str, ...]
    reason: str | None
    undoes: int | None


@dataclass(frozen=True)
class UndoState:
    allowed: bool
    undone: bool = False  # already undone
    blocked_by: int | None = None  # the later entry that must be undone first
    message: str = ""


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _primary_key(conn: sqlite3.Connection, table: str) -> list[str]:
    info = [row for row in conn.execute(f"PRAGMA table_info({table})") if row[5]]
    return [row[1] for row in sorted(info, key=lambda r: r[5])]


def _install(conn: sqlite3.Connection) -> None:
    """Temporary triggers (of this connection) that copy every touched row."""
    found = conn.execute(
        "SELECT 1 FROM sqlite_temp_master WHERE type = 'table' AND name = ?", (_CAPTURE,)
    ).fetchone()
    if found is not None:
        return
    conn.execute(
        f"CREATE TEMP TABLE {_CAPTURE} (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "tbl TEXT NOT NULL, old TEXT, new TEXT)"
    )
    for table in TRACKED:
        columns = _columns(conn, table)

        def row(prefix: str, columns: list[str] = columns) -> str:
            return "json_object(" + ", ".join(f"'{c}', {prefix}.\"{c}\"" for c in columns) + ")"

        for event, old, new in (
            ("INSERT", "NULL", row("NEW")),
            ("UPDATE", row("OLD"), row("NEW")),
            ("DELETE", row("OLD"), "NULL"),
        ):
            conn.execute(
                f"CREATE TEMP TRIGGER changelog_{table}_{event.lower()} AFTER {event} "
                f"ON main.{table} BEGIN INSERT INTO {_CAPTURE} (tbl, old, new) "
                f"VALUES ('{table}', {old}, {new}); END"
            )


def _collect(conn: sqlite3.Connection) -> list[Change]:
    """The rows touched since `track` started: the first version seen and the last one."""
    keys = {table: _primary_key(conn, table) for table in TRACKED}
    seen: dict[tuple[str, str], list[Any]] = {}
    for tbl, old, new in conn.execute(f"SELECT tbl, old, new FROM {_CAPTURE} ORDER BY seq"):
        before = None if old is None else json.loads(old)
        after = None if new is None else json.loads(new)
        pk = keys[tbl]
        steps = [(before, after)]
        if before is not None and after is not None and any(before[c] != after[c] for c in pk):
            steps = [(before, None), (None, after)]  # the key changed: one leaves, another enters
        for first, last in steps:
            row: Row = first if first is not None else last  # type: ignore[assignment]
            key = {c: row[c] for c in pk}
            slot = (tbl, row_key(tbl, key))
            if slot not in seen:
                seen[slot] = [key, first, last]
            else:
                seen[slot][2] = last
    changes = []
    for (tbl, _), (key, before, after) in seen.items():
        columns = changed_columns(tbl, before, after)
        if columns:
            changes.append(Change(tbl, key, before, after, columns))
    return _with_parents(conn, changes)


def _parent_ref(change: Change) -> tuple[str, int] | None:
    """The parent (table, id) the row goes back to on undo, if undoing sets it."""
    ref = PARENT_COLUMNS.get(change.table)
    if ref is None or change.before is None:
        return None
    column, table = ref
    value = change.before.get(column)
    if value is None or not (change.after is None or column in change.columns):
        return None
    return table, int(value)


def _with_parents(conn: sqlite3.Connection, changes: list[Change]) -> list[Change]:
    """Note on each row the identity of its *before*'s parent (the same entry's one if it also
    changed; otherwise today's, which is the same as before)."""
    by_key = {c.row_key: c for c in changes}
    found = []
    for change in changes:
        ref = _parent_ref(change)
        if ref is None:
            found.append(change)
            continue
        table, parent_id = ref
        key = row_key(table, {"id": parent_id})
        own = by_key.get(key)
        if own is not None:
            row = own.before
        else:
            current = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (parent_id,)).fetchone()
            row = None if current is None else dict(current)
        mark = None if row is None else identity(table, row)
        found.append(replace(change, parent={"key": key, "identity": mark}))
    return found


def _fingerprints(conn: sqlite3.Connection, changes: Iterable[Change]) -> set[str]:
    """The fingerprints the rows touch: their own, those of a manual cash box entry and those
    of every member of a link that changed (before and now)."""
    found: set[str] = set()
    link_ids: set[int] = set()
    for change in changes:
        for row in (change.before, change.after):
            if row is None:
                continue
            if row.get("fingerprint"):
                found.add(str(row["fingerprint"]))
            if change.table == "cash_entries":
                found.add(f"cash-{row['id']}")
            if change.table == "links":
                link_ids.add(int(row["id"]))
    for link_id in link_ids:
        rows = conn.execute("SELECT fingerprint FROM link_members WHERE link_id = ?", (link_id,))
        found.update(str(r[0]) for r in rows)
    return found


def _record(conn: sqlite3.Connection, draft: Draft, changes: Sequence[Change]) -> int:
    fingerprints = sorted(draft.fingerprints | _fingerprints(conn, changes))
    cursor = conn.execute(
        "INSERT INTO change_log (at, author, kind, target_type, target, subject, merchant, "
        "before_text, after_text, changes, affected, undoes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            now().isoformat(),
            AUTHOR.get(),
            draft.kind,
            draft.target_type,
            draft.target,
            draft.subject[:200],
            draft.merchant,
            draft.before if draft.before is not None else describe(changes, "before"),
            draft.after if draft.after is not None else describe(changes, "after"),
            json.dumps([c.to_json() for c in changes], ensure_ascii=False),
            len(fingerprints),
            draft.undoes,
        ),
    )
    entry_id = int(cursor.lastrowid or 0)
    conn.executemany(
        "INSERT OR IGNORE INTO change_log_rows (entry_id, row_key) VALUES (?, ?)",
        [(entry_id, c.row_key) for c in changes],
    )
    conn.executemany(
        "INSERT INTO change_log_fingerprints (entry_id, fingerprint) VALUES (?, ?)",
        [(entry_id, fp) for fp in fingerprints],
    )
    return entry_id


@contextmanager
def track(
    conn: sqlite3.Connection,
    kind: str,
    target_type: str,
    target: str,
    subject: str,
    *,
    before: str | None = None,
    after: str | None = None,
    merchant: str | None = None,
    fingerprints: Iterable[str] = (),
    undoes: int | None = None,
) -> Iterator[Draft]:
    """Record whatever changes inside the block as one entry (in the caller's transaction). If
    the block fails, nothing is recorded."""
    _install(conn)
    conn.execute(f"DELETE FROM {_CAPTURE}")
    draft = Draft(
        kind, target_type, target, subject, before, after, merchant, set(fingerprints), undoes
    )
    yield draft
    changes = _collect(conn)
    if changes:
        draft.entry_id = _record(conn, draft, changes)


def _entry(row: sqlite3.Row, fingerprints: Sequence[str]) -> Entry:
    return Entry(
        id=row["id"],
        at=datetime.fromisoformat(row["at"]),
        author=row["author"],
        kind=row["kind"],
        target_type=row["target_type"],
        target=row["target"],
        subject=row["subject"],
        merchant=row["merchant"],
        before_text=row["before_text"],
        after_text=row["after_text"],
        changes=tuple(Change.from_json(c) for c in json.loads(row["changes"])),
        affected=row["affected"],
        fingerprints=tuple(fingerprints),
        reason=row["reason"],
        undoes=row["undoes"],
    )


def load(
    conn: sqlite3.Connection, fingerprint: str | None = None, kind: str | None = None
) -> list[Entry]:
    """The entries, newest first (with `fingerprint`, only those touching it; with `kind`, only
    those of that kind). Filters in SQL."""
    where = ""
    args: tuple[str, ...] = ()
    if fingerprint is not None:
        where = "WHERE id IN (SELECT entry_id FROM change_log_fingerprints WHERE fingerprint = ?)"
        args = (fingerprint,)
    if kind is not None:
        where = f"{where} {'AND' if where else 'WHERE'} kind = ?"
        args = (*args, kind)
    rows = conn.execute(f"SELECT * FROM change_log {where} ORDER BY id DESC", args).fetchall()
    prints: dict[int, list[str]] = {}
    for entry_id, fp in conn.execute(
        "SELECT entry_id, fingerprint FROM change_log_fingerprints "
        f"WHERE entry_id IN (SELECT id FROM change_log {where}) ORDER BY fingerprint",
        args,
    ):
        prints.setdefault(entry_id, []).append(fp)
    return [_entry(row, prints.get(row["id"], ())) for row in rows]


def get(conn: sqlite3.Connection, entry_id: int) -> Entry:
    row = conn.execute("SELECT * FROM change_log WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise LookupError(t("analysis.changelog.unknown_entry", id=entry_id))
    prints = [
        r[0]
        for r in conn.execute(
            "SELECT fingerprint FROM change_log_fingerprints WHERE entry_id = ? "
            "ORDER BY fingerprint",
            (entry_id,),
        )
    ]
    return _entry(row, prints)


def undone(conn: sqlite3.Connection) -> frozenset[int]:
    rows = conn.execute("SELECT id, undoes FROM change_log WHERE undoes IS NOT NULL")
    return undone_ids({int(r[0]): int(r[1]) for r in rows})


def set_reason(conn: sqlite3.Connection, entry_id: int, reason: str | None) -> None:
    """The reason (without extra spaces; empty clears it). Not a change: it is not logged."""
    clean = (reason or "").strip()
    if len(clean) > REASON_MAX:
        raise ValueError(t("analysis.changelog.reason_too_long", max=REASON_MAX))
    cursor = conn.execute(
        "UPDATE change_log SET reason = ? WHERE id = ?", (clean or None, entry_id)
    )
    if cursor.rowcount == 0:
        raise LookupError(t("analysis.changelog.unknown_entry", id=entry_id))


def _checked(conn: sqlite3.Connection, table: str, names: Iterable[str]) -> list[str]:
    """The column names of a stored row, only if they belong to the table (they go into SQL)."""
    if table not in TRACKED:
        raise ValueError(f"unknown table: {table}")
    known = set(_columns(conn, table))
    wanted = list(names)
    if not set(wanted) <= known:
        raise ValueError(f"unknown columns in {table}")
    return wanted


def _where(conn: sqlite3.Connection, table: str, key: Row) -> tuple[str, list[Any]]:
    columns = _checked(conn, table, key)
    return " AND ".join(f'"{c}" = ?' for c in columns), [key[c] for c in columns]


def _current(conn: sqlite3.Connection, change: Change) -> Row | None:
    where, args = _where(conn, change.table, change.key)
    row = conn.execute(f"SELECT * FROM {change.table} WHERE {where}", args).fetchone()
    return None if row is None else dict(row)


def current_rows(conn: sqlite3.Connection, changes: Iterable[Change]) -> dict[str, Row | None]:
    return {c.row_key: _current(conn, c) for c in changes}


def _latest_later(
    conn: sqlite3.Connection,
    entry: Entry,
    done: frozenset[int],
    keys: Iterable[str] = (),
    fingerprints: Iterable[str] = (),
    link_ids: Iterable[int] = (),
) -> int | None:
    """The newest later entry still in effect (neither undone nor an "Undo" of another later one:
    those two cancel out) that touched those rows, fingerprints or links."""
    candidates: set[int] = set()
    wanted = list(dict.fromkeys(keys))
    if wanted:
        marks = ", ".join("?" * len(wanted))
        rows = conn.execute(
            f"SELECT entry_id FROM change_log_rows WHERE entry_id > ? AND row_key IN ({marks})",
            (entry.id, *wanted),
        )
        candidates.update(int(r[0]) for r in rows)
    for link_id in dict.fromkeys(link_ids):
        rows = conn.execute(
            "SELECT entry_id FROM change_log_rows WHERE entry_id > ? "
            "AND (row_key = ? OR row_key LIKE ?)",
            (entry.id, row_key("links", {"id": link_id}), f"link_members:[{link_id}, %"),
        )
        candidates.update(int(r[0]) for r in rows)
    prints = list(dict.fromkeys(fingerprints))
    if prints:
        marks = ", ".join("?" * len(prints))
        rows = conn.execute(
            "SELECT entry_id FROM change_log_fingerprints "
            f"WHERE entry_id > ? AND fingerprint IN ({marks})",
            (entry.id, *prints),
        )
        candidates.update(int(r[0]) for r in rows)
    if not candidates:
        return None
    marks = ", ".join("?" * len(candidates))
    for later, undoes in conn.execute(
        f"SELECT id, undoes FROM change_log WHERE id IN ({marks}) ORDER BY id DESC",
        tuple(candidates),
    ):
        if later in done or (undoes is not None and undoes > entry.id):
            continue
        return int(later)
    return None


def _blocked(reason: str, later: int | None) -> UndoState:
    if later is None:
        return UndoState(False, message=t("analysis.changelog.blocked", reason=reason))
    return UndoState(
        False,
        blocked_by=later,
        message=t("analysis.changelog.blocked_by", reason=reason, id=later),
    )


_PARENT_LABELS = {
    "links": t("analysis.changelog.parent_link"),
    "categories": t("analysis.changelog.parent_category"),
    "ledger_groups": t("analysis.changelog.parent_group"),
    "ledger_entries": t("analysis.changelog.parent_entry"),
    "contacts": t("analysis.changelog.parent_contact"),
}


def _missing_parent(conn: sqlite3.Connection, entry: Entry) -> tuple[str, str] | None:
    """The parent (its key and what it is) a row would go back to that no longer exists or is a
    different one (another row inherited its id). None if all remain or the same entry restores
    them."""
    restored = {c.row_key for c in entry.changes if c.before is not None}
    for change in entry.changes:
        key = change.parent.get("key")
        if not key or key in restored:
            continue
        table, raw_id = key.split(":", 1)
        parent_id = json.loads(raw_id)[0]
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (parent_id,)).fetchone()
        if row is None or identity(table, dict(row)) != change.parent.get("identity"):
            label = _PARENT_LABELS.get(table, t("analysis.changelog.parent_row"))
            return key, t("analysis.changelog.parent_number", label=label, id=parent_id)
    return None


def _touched_links(entry: Entry) -> set[int]:
    found: set[int] = set()
    for change in entry.changes:
        for row in (change.before, change.after):
            if row is None:
                continue
            if change.table == "links":
                found.add(int(row["id"]))
            elif change.table in ("link_members", "link_manual"):
                found.add(int(row["link_id"]))
    return found


def _domain_problem(
    conn: sqlite3.Connection, entry: Entry, days: dict[str, date] | None
) -> tuple[str, int | None] | None:
    """What the restored state would break (and the link, if it belongs to one): a category set by
    hand that no longer exists or that only its link sets; an investment with a payout earlier
    than its first contribution (with `days`: the day of each fingerprint)."""
    known = catalog.load(conn)
    for change in entry.changes:
        if change.table not in ("transaction_notes", "merchant_categories"):
            continue
        value = None if change.before is None else change.before.get("category_id")
        if value is None or "category_id" not in change.columns:
            continue
        category = known.by_id(int(value))
        if category is None:
            return t("analysis.changelog.category_gone"), None
        try:
            catalog.check_choosable(category)
        except catalog.CategoryError:
            return t("analysis.changelog.category_link_only", name=category.name), None
    if days is None:
        return None
    touched = _touched_links(entry)
    for investment in links.load(conn).investments:
        if investment.id not in touched:
            continue
        starts = [days[fp] for fp in investment.contributions if fp in days]
        if not starts:
            continue
        first = min(starts)
        for member in investment.members:
            day = days.get(member.fingerprint)
            if member.role != "contribution" and day is not None and day < first:
                return (
                    t(
                        "analysis.changelog.investment_order",
                        day=day.isoformat(),
                        first=first.isoformat(),
                    ),
                    investment.id,
                )
    return None


_SAVEPOINT = "changelog_rehearsal"


def _rehearse(
    conn: sqlite3.Connection, entry: Entry, done: frozenset[int], days: dict[str, date] | None
) -> UndoState | None:
    """Rehearse the undo inside a `SAVEPOINT` (and roll it back): None if it would work;
    otherwise why, and which later entry to undo first."""
    _install(conn)
    own = {c.row_key for c in entry.changes}
    # Outside a transaction, the write lock is taken up front (waiting if another connection is
    # writing): a deferred SAVEPOINT that has already read and then wants to write fails at once
    # ("database is locked") against another connection that is writing.
    own_lock = not conn.in_transaction
    try:
        if own_lock:
            conn.execute("BEGIN IMMEDIATE")
        conn.execute(f"SAVEPOINT {_SAVEPOINT}")
    except sqlite3.OperationalError as exc:
        _end_rehearsal(conn, own_lock, savepoint=False)
        if not _is_busy(exc):
            raise
        return UndoState(False, message=BUSY)
    try:
        conn.execute(f"DELETE FROM {_CAPTURE}")
        try:
            _restore(conn, entry.changes)
        except sqlite3.IntegrityError:
            later = _latest_later(conn, entry, done, fingerprints=entry.fingerprints)
            return _blocked(t("analysis.changelog.conflict"), later)
        extra = [c.row_key for c in _collect(conn) if c.row_key not in own]
        if extra:
            later = _latest_later(conn, entry, done, keys=extra)
            return _blocked(t("analysis.changelog.would_change_later"), later)
        problem = _domain_problem(conn, entry, days)
        if problem is not None:
            reason, link_id = problem
            later = _latest_later(conn, entry, done, link_ids=() if link_id is None else (link_id,))
            return _blocked(reason, later)
        return None
    except sqlite3.OperationalError as exc:  # database busy with another connection: not a 500
        if not _is_busy(exc):
            raise
        return UndoState(False, message=BUSY)
    finally:
        _end_rehearsal(conn, own_lock)


BUSY = t("analysis.changelog.busy")


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def _end_rehearsal(conn: sqlite3.Connection, own_lock: bool, savepoint: bool = True) -> None:
    """Roll the rehearsal back; if `ROLLBACK TO` fails, still close our own transaction."""
    try:
        if savepoint:
            conn.execute(f"ROLLBACK TO {_SAVEPOINT}")
            conn.execute(f"RELEASE {_SAVEPOINT}")
    except sqlite3.OperationalError:
        pass
    finally:
        if own_lock and conn.in_transaction:
            conn.execute("ROLLBACK")


# The roles of `link_members` that only old shared groups had (schema 18 and before).
_OLD_SHARED_ROLES = frozenset({"expense", "reimbursement"})


def touches_old_shared(changes: Iterable[Change]) -> bool:
    """The entry touched an old shared group (a `links` row of kind `shared`, its members or a
    manual reimbursement): schema 19 moved those to the ledger, so it cannot be undone (it would
    bring back rows nothing reads)."""
    for change in changes:
        rows = [r for r in (change.before, change.after) if r is not None]
        if change.table == "link_manual":
            return True
        if change.table == "links" and any(r.get("kind") == "shared" for r in rows):
            return True
        if change.table == "link_members" and any(r.get("role") in _OLD_SHARED_ROLES for r in rows):
            return True
    return False


def undo_state(
    conn: sqlite3.Connection,
    entry: Entry,
    undone_set: frozenset[int] | None = None,
    days: dict[str, date] | None = None,
) -> UndoState:
    """Whether it can be undone and, if not, why (and which later entry to undo first).
    `days`: the day of each of today's fingerprints (for the investment rules)."""
    done = undone(conn) if undone_set is None else undone_set
    if entry.id in done:
        return UndoState(False, undone=True, message=t("analysis.changelog.already_undone"))
    if touches_old_shared(entry.changes):
        return UndoState(False, message=t("analysis.changelog.old_shared"))
    if not can_undo(entry.changes, current_rows(conn, entry.changes)):
        later = _latest_later(conn, entry, done, keys=[c.row_key for c in entry.changes])
        if later is None:
            return UndoState(False, message=t("analysis.changelog.changed_outside"))
        return UndoState(
            False, blocked_by=later, message=t("analysis.changelog.undo_later_first", id=later)
        )
    missing = _missing_parent(conn, entry)
    if missing is not None:
        key, label = missing
        later = _latest_later(conn, entry, done, keys=[key])
        return _blocked(t("analysis.changelog.parent_gone", label=label), later)
    return _rehearse(conn, entry, done, days) or UndoState(True)


def _restore_soft(conn: sqlite3.Connection, change: Change) -> None:
    defaults = SOFT_DEFAULTS[change.table]
    current = _current(conn, change) or {**change.key, **defaults}
    source = change.before or defaults
    target = {**current, **{c: source.get(c, defaults[c]) for c in change.columns}}
    where, args = _where(conn, change.table, change.key)
    if all(target.get(c, d) == d for c, d in defaults.items()):
        conn.execute(f"DELETE FROM {change.table} WHERE {where}", args)
        return
    keys = _checked(conn, change.table, change.key)
    soft = _checked(conn, change.table, defaults)
    names = [*keys, *soft, "updated_at"]
    values = [*(change.key[c] for c in keys), *(target.get(c) for c in soft), now().isoformat()]
    updates = ", ".join(f'"{c}" = excluded."{c}"' for c in [*soft, "updated_at"])
    conn.execute(
        f"INSERT INTO {change.table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))}) "
        f"ON CONFLICT({', '.join(keys)}) DO UPDATE SET {updates}",
        values,
    )


def _restore(conn: sqlite3.Connection, changes: Sequence[Change]) -> None:
    """Put every row back to its *before*: delete what is new (children first) and reinsert or
    fix the rest (parents first)."""
    order = {table: i for i, table in enumerate(TRACKED)}
    created = [c for c in changes if c.before is None and c.table not in SOFT_DEFAULTS]
    for change in sorted(created, key=lambda c: -order[c.table]):
        where, args = _where(conn, change.table, change.key)
        conn.execute(f"DELETE FROM {change.table} WHERE {where}", args)
    rest = [c for c in changes if not (c.before is None and c.table not in SOFT_DEFAULTS)]
    for change in sorted(rest, key=lambda c: order[c.table]):
        if change.table in SOFT_DEFAULTS:
            _restore_soft(conn, change)
        elif change.after is None and change.before is not None:
            names = _checked(conn, change.table, change.before)
            conn.execute(
                f"INSERT INTO {change.table} ({', '.join(chr(34) + n + chr(34) for n in names)}) "
                f"VALUES ({', '.join('?' * len(names))})",
                [change.before[n] for n in names],
            )
        elif change.before is not None:
            names = _checked(conn, change.table, change.columns)
            where, args = _where(conn, change.table, change.key)
            sets = ", ".join(f'"{n}" = ?' for n in names)
            conn.execute(
                f"UPDATE {change.table} SET {sets} WHERE {where}",
                [*(change.before[n] for n in names), *args],
            )


def undo(conn: sqlite3.Connection, entry_id: int, days: dict[str, date] | None = None) -> int:
    """Undo the entry (in the caller's transaction) and return the new entry that records it.
    `UndoBlocked` if it cannot be undone; `LookupError` if it does not exist."""
    entry = get(conn, entry_id)
    state = undo_state(conn, entry, days=days)
    if not state.allowed:
        raise UndoBlocked(state.message)
    own = {c.row_key for c in entry.changes}
    with track(
        conn,
        entry.kind,
        entry.target_type,
        entry.target,
        entry.subject,
        before=entry.after_text,
        after=entry.before_text,
        merchant=entry.merchant,
        fingerprints=entry.fingerprints,
        undoes=entry.id,
    ) as draft:
        try:
            _restore(conn, entry.changes)
        except sqlite3.IntegrityError:
            raise UndoBlocked(t("analysis.changelog.later_uses_before")) from None
        if any(c.row_key not in own for c in _collect(conn)):
            raise UndoBlocked(t("analysis.changelog.would_change_later_undo"))
    if draft.entry_id is None:  # should not happen: the state was the *after*
        raise UndoBlocked(t("analysis.changelog.nothing_to_undo"))
    return draft.entry_id


def category_edits(
    entries: Iterable[Entry],
    undone_set: frozenset[int],
    merchants: Mapping[str, str] | None = None,
) -> list[CategoryEdit]:
    """The "only this one" corrections still in effect made by the user (without undone ones,
    "Undo"s or Claude's) and, from any author, those of a batch still in effect (`counts=False`:
    they only contradict). `merchants`: the merchant of each of today's fingerprints, for batches
    (which do not store it); if missing, that of an "only this one" correction of the same
    fingerprint."""
    found = []
    batches = []
    for entry in entries:
        if entry.undoes is not None or entry.id in undone_set:
            continue
        if entry.kind == BATCH_KIND:
            batches.append(entry)
            continue
        if entry.kind != CATEGORY_KIND:
            continue
        if entry.author != "user":  # the app learns from the user, not from what Claude applied
            continue
        note = next((c for c in entry.changes if c.table == "transaction_notes"), None)
        if note is None or entry.merchant is None:
            continue
        after = note.after or {}
        found.append(CategoryEdit(entry.id, entry.merchant, entry.target, after.get("category_id")))
    known = {**{e.fingerprint: e.merchant for e in found}, **(merchants or {})}
    for entry in batches:
        for change in entry.changes:
            fingerprint = str(change.key.get("fingerprint", ""))
            merchant = known.get(fingerprint)
            if change.table != "transaction_notes" or not merchant:
                continue
            after = change.after or {}
            found.append(
                CategoryEdit(entry.id, merchant, fingerprint, after.get("category_id"), False)
            )
    return found


def rule_dismissals(conn: sqlite3.Connection) -> set[tuple[str, int]]:
    return {
        (r[0], int(r[1])) for r in conn.execute("SELECT merchant, category_id FROM rule_dismissals")
    }


def dismiss_rule(conn: sqlite3.Connection, merchant: str, category_id: int) -> None:
    conn.execute(
        "INSERT INTO rule_dismissals (merchant, category_id, dismissed_at) VALUES (?, ?, ?) "
        "ON CONFLICT(merchant, category_id) DO NOTHING",
        (merchant, category_id, now().isoformat()),
    )


def merchant_rules(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        r[0]: int(r[1])
        for r in conn.execute("SELECT merchant, category_id FROM merchant_categories")
    }
