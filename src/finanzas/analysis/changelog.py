"""Bitácora de cambios (esquema 15): registrar, leer, escribir el motivo y deshacer.

Cada cambio hecho desde el board se registra con `track`, dentro de la misma transacción SQLite
que el cambio: o quedan los dos o ninguno. `track` instala (una vez por conexión) disparadores
temporales que copian a una tabla temporal cada fila insertada, cambiada o borrada en las tablas
de `TRACKED`, también las borradas en cascada; al salir del bloque sin error junta esas filas
(`Change`: antes y después) y guarda la entrada. Sin filas que cambien de verdad no hay entrada.

«Deshacer» (`undo`) vuelve cada fila al *antes* de la entrada y se registra como una entrada
propia (`undoes`). Solo se ofrece (`undo_state`) si: cada fila sigue como el *después*
(`changelog_rules.can_undo`); la madre a la que vuelve una fila (el vínculo o la categoría) es la
misma de entonces (`Change.parent`); y un ensayo dentro de un `SAVEPOINT` no choca con un índice
único, no toca filas que la entrada no tocó (una cascada sobre lo de otra entrada) y deja las
reglas de dominio en pie (`_domain_problem`). Si no, dice qué entrada posterior deshacer primero.

Nada aquí hace commit: quien llama envuelve todo en `with conn:`.
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

from finanzas.analysis import catalog, links
from finanzas.analysis.changelog_rules import (
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

AUTHORS = ("usuario", "claude")
REASON_MAX = 500
# El autor del pedido en curso (la cabecera `X-Finanzas-Autor`; ver `web.app`).
AUTHOR: ContextVar[str] = ContextVar("finanzas_autor", default="usuario")

# Las tablas que registra la bitácora, madres antes que hijas (en ese orden se reinsertan).
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
)
_CAPTURE = "changelog_capture"


class UndoBlocked(Exception):
    """No se puede deshacer: el mensaje explica por qué."""


@dataclass
class Draft:
    """Lo que se sabe de la entrada mientras se hace el cambio (se completa al terminar)."""

    kind: str
    target_type: str
    target: str
    subject: str
    before: str | None = None  # None: se describe sola a partir de las filas
    after: str | None = None
    merchant: str | None = None
    fingerprints: set[str] = field(default_factory=set)
    undoes: int | None = None
    entry_id: int | None = None  # la entrada guardada (None si no hubo cambio)


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
    undone: bool = False  # ya deshecha
    blocked_by: int | None = None  # la entrada posterior que hay que deshacer primero
    message: str = ""


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _primary_key(conn: sqlite3.Connection, table: str) -> list[str]:
    info = [row for row in conn.execute(f"PRAGMA table_info({table})") if row[5]]
    return [row[1] for row in sorted(info, key=lambda r: r[5])]


def _install(conn: sqlite3.Connection) -> None:
    """Disparadores temporales (de esta conexión) que copian cada fila tocada."""
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
    """Las filas tocadas desde que empezó `track`: la primera versión vista y la última."""
    keys = {table: _primary_key(conn, table) for table in TRACKED}
    seen: dict[tuple[str, str], list[Any]] = {}
    for tbl, old, new in conn.execute(f"SELECT tbl, old, new FROM {_CAPTURE} ORDER BY seq"):
        before = None if old is None else json.loads(old)
        after = None if new is None else json.loads(new)
        pk = keys[tbl]
        steps = [(before, after)]
        if before is not None and after is not None and any(before[c] != after[c] for c in pk):
            steps = [(before, None), (None, after)]  # cambió la clave: una sale y otra entra
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
    """La madre (tabla, id) a la que vuelve la fila al deshacer, si deshacer la pone."""
    ref = PARENT_COLUMNS.get(change.table)
    if ref is None or change.before is None:
        return None
    column, table = ref
    value = change.before.get(column)
    if value is None or not (change.after is None or column in change.columns):
        return None
    return table, int(value)


def _with_parents(conn: sqlite3.Connection, changes: list[Change]) -> list[Change]:
    """Anota en cada fila la identidad de la madre de su *antes* (la de la misma entrada si
    también cambió; si no, la de hoy, que es la misma de antes)."""
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
    """Las huellas que tocan las filas: las suyas, las de un movimiento a mano de la caja y las
    de todos los miembros de un vínculo que cambió (antes y ahora)."""
    found: set[str] = set()
    link_ids: set[int] = set()
    for change in changes:
        for row in (change.before, change.after):
            if row is None:
                continue
            if row.get("fingerprint"):
                found.add(str(row["fingerprint"]))
            if change.table == "cash_entries":
                found.add(f"caja-{row['id']}")
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
    """Registra lo que cambie dentro del bloque como una entrada (en la transacción de quien
    llama). Si el bloque falla, no se registra nada."""
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
    """Las entradas, la más reciente primero (con `fingerprint`, solo las que la tocan; con
    `kind`, solo las de ese tipo). Filtra en SQL."""
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
        raise LookupError(f"entrada desconocida: {entry_id}")
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
    """El motivo (sin espacios de más; vacío lo borra). No es un cambio: no se registra."""
    clean = (reason or "").strip()
    if len(clean) > REASON_MAX:
        raise ValueError(f"el motivo tiene más de {REASON_MAX} letras")
    cursor = conn.execute(
        "UPDATE change_log SET reason = ? WHERE id = ?", (clean or None, entry_id)
    )
    if cursor.rowcount == 0:
        raise LookupError(f"entrada desconocida: {entry_id}")


def _checked(conn: sqlite3.Connection, table: str, names: Iterable[str]) -> list[str]:
    """Los nombres de columna de una fila guardada, solo si son de la tabla (van en el SQL)."""
    if table not in TRACKED:
        raise ValueError(f"tabla desconocida: {table}")
    known = set(_columns(conn, table))
    wanted = list(names)
    if not set(wanted) <= known:
        raise ValueError(f"columnas desconocidas en {table}")
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
    """La entrada posterior más reciente y vigente (ni deshecha ni un «Deshacer» de otra
    posterior: esas dos se anulan) que tocó esas filas, esas huellas o esos vínculos."""
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
        return UndoState(False, message=f"{reason}; ya no se puede deshacer.")
    return UndoState(
        False,
        blocked_by=later,
        message=f"{reason}: primero deshaz la entrada posterior n.º {later}.",
    )


_PARENT_LABELS = {"links": "El vínculo", "categories": "La categoría"}


def _missing_parent(conn: sqlite3.Connection, entry: Entry) -> tuple[str, str] | None:
    """La madre (su clave y qué es) a la que volvería una fila y que ya no existe o es otra (su id
    lo heredó otra fila). None si todas siguen o las restaura la misma entrada."""
    restored = {c.row_key for c in entry.changes if c.before is not None}
    for change in entry.changes:
        key = change.parent.get("key")
        if not key or key in restored:
            continue
        table, raw_id = key.split(":", 1)
        parent_id = json.loads(raw_id)[0]
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (parent_id,)).fetchone()
        if row is None or identity(table, dict(row)) != change.parent.get("identity"):
            return key, f"{_PARENT_LABELS.get(table, 'La fila madre')} n.º {parent_id}"
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
    """Lo que el estado restaurado rompería (y el vínculo, si es de uno): una categoría que ya
    no existe o que solo pone su vínculo, puesta a mano; una inversión con un cobro anterior a
    su primer aporte (con `days`: el día de cada huella)."""
    known = catalog.load(conn)
    for change in entry.changes:
        if change.table not in ("transaction_notes", "merchant_categories"):
            continue
        value = None if change.before is None else change.before.get("category_id")
        if value is None or "category_id" not in change.columns:
            continue
        category = known.by_id(int(value))
        if category is None:
            return "La categoría de antes ya no existe", None
        try:
            catalog.check_choosable(category)
        except catalog.CategoryError:
            return f"«{category.name}» solo la pone su vínculo: no se pone a mano", None
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
                    f"La inversión quedaría con un cobro del {day.isoformat()} anterior a su "
                    f"primer aporte ({first.isoformat()})",
                    investment.id,
                )
    return None


_SAVEPOINT = "changelog_ensayo"


def _rehearse(
    conn: sqlite3.Connection, entry: Entry, done: frozenset[int], days: dict[str, date] | None
) -> UndoState | None:
    """Ensaya el deshacer dentro de un `SAVEPOINT` (y lo vuelve atrás): None si saldría bien; si
    no, por qué y qué entrada posterior deshacer primero."""
    _install(conn)
    own = {c.row_key for c in entry.changes}
    # Fuera de una transacción, el lock de escritura se toma de entrada (y se espera si otra
    # conexión escribe): un SAVEPOINT diferido que ya leyó y después quiere escribir choca al
    # instante («database is locked») con otra conexión que está escribiendo.
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
            return _blocked(
                "Lo de antes choca con algo de ahora (la transacción está en otro vínculo o hay "
                "otra categoría con ese nombre)",
                later,
            )
        extra = [c.row_key for c in _collect(conn) if c.row_key not in own]
        if extra:
            later = _latest_later(conn, entry, done, keys=extra)
            return _blocked("Deshacerla cambiaría también lo de una entrada posterior", later)
        problem = _domain_problem(conn, entry, days)
        if problem is not None:
            reason, link_id = problem
            later = _latest_later(conn, entry, done, link_ids=() if link_id is None else (link_id,))
            return _blocked(reason, later)
        return None
    except sqlite3.OperationalError as exc:  # la base ocupada por otra conexión: no es un 500
        if not _is_busy(exc):
            raise
        return UndoState(False, message=BUSY)
    finally:
        _end_rehearsal(conn, own_lock)


BUSY = "La base está ocupada; reintenta."


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def _end_rehearsal(conn: sqlite3.Connection, own_lock: bool, savepoint: bool = True) -> None:
    """Vuelve atrás el ensayo; si falla el `ROLLBACK TO`, igual cierra la transacción propia."""
    try:
        if savepoint:
            conn.execute(f"ROLLBACK TO {_SAVEPOINT}")
            conn.execute(f"RELEASE {_SAVEPOINT}")
    except sqlite3.OperationalError:
        pass
    finally:
        if own_lock and conn.in_transaction:
            conn.execute("ROLLBACK")


def undo_state(
    conn: sqlite3.Connection,
    entry: Entry,
    undone_set: frozenset[int] | None = None,
    days: dict[str, date] | None = None,
) -> UndoState:
    """Si se puede deshacer y, si no, por qué (y qué entrada posterior deshacer primero).
    `days`: el día de cada huella de hoy (para las reglas de las inversiones)."""
    done = undone(conn) if undone_set is None else undone_set
    if entry.id in done:
        return UndoState(False, undone=True, message="Ya está deshecha.")
    if not can_undo(entry.changes, current_rows(conn, entry.changes)):
        later = _latest_later(conn, entry, done, keys=[c.row_key for c in entry.changes])
        if later is None:
            return UndoState(
                False,
                message="Cambió después por algo que no queda en la bitácora; ya no se puede "
                "deshacer.",
            )
        return UndoState(
            False, blocked_by=later, message=f"Primero deshaz la entrada posterior n.º {later}."
        )
    missing = _missing_parent(conn, entry)
    if missing is not None:
        key, label = missing
        later = _latest_later(conn, entry, done, keys=[key])
        return _blocked(f"{label} al que volvería ya no existe o es otro", later)
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
    """Vuelve cada fila a su *antes*: borra lo nuevo (hijas primero) y reinserta o corrige lo
    demás (madres primero)."""
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
    """Deshace la entrada (en la transacción de quien llama) y devuelve la entrada nueva que lo
    registra. `UndoBlocked` si no se puede; `LookupError` si no existe."""
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
            raise UndoBlocked(
                "Otra entrada posterior usa lo que había antes (por ejemplo, la transacción está "
                "ahora en otro vínculo): deshazla primero."
            ) from None
        if any(c.row_key not in own for c in _collect(conn)):
            raise UndoBlocked(
                "Deshacerla cambiaría también lo de una entrada posterior: deshaz esa primero."
            )
    if draft.entry_id is None:  # no debería pasar: el estado era el *después*
        raise UndoBlocked("No había nada que deshacer.")
    return draft.entry_id


def category_edits(
    entries: Iterable[Entry],
    undone_set: frozenset[int],
    merchants: Mapping[str, str] | None = None,
) -> list[CategoryEdit]:
    """Las correcciones «solo esta» vigentes hechas por el usuario (sin las deshechas, los
    «Deshacer» ni las de Claude) y, de cualquier autor, las de un lote vigente (`counts=False`:
    solo contradicen). `merchants`: el comercio de cada huella de hoy, para los lotes (que no lo
    guardan); si falta, el de una corrección «solo esta» de la misma huella."""
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
        if entry.author != "usuario":  # la app aprende del usuario, no de lo que aplicó Claude
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
