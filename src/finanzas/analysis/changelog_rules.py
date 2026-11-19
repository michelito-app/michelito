"""Bitácora: la lógica pura (sin base ni HTTP).

- `Change`: una fila tocada por un cambio, con lo que había antes y lo que quedó después.
- `changed_columns` y `can_undo`: qué cuenta como cambio y cuándo se puede deshacer (el estado
  actual de esas columnas sigue siendo el *después* de la entrada).
- `sessions`: las entradas agrupadas por sesión de edición (corte tras `SESSION_GAP` sin cambios).
- `undone_ids`: qué entradas quedaron deshechas (un «Deshacer» que a su vez se deshizo no cuenta).
- `rule_suggestions`: las reglas por comercio que se proponen (`regla_posible`).
- `describe`: la línea legible de un lado (antes o después) cuando quien registra no la da.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from finanzas.analysis.providers import display_name
from finanzas.analysis.recurring import GROUPS

Row = dict[str, Any]

SESSION_GAP = timedelta(minutes=30)
RULE_MIN_TIMES = 2  # «solo esta» con la misma categoría en tantas transacciones del comercio
CATEGORY_KIND = "categoria"
# Cambio de categoría de varias a la vez (`web.batch_edit`): no enseña reglas, pero sí las
# contradice.
BATCH_KIND = "categoria_lote"

# Columnas que no cuentan como cambio (marcas de tiempo) y, por tabla, las que se editan sin
# bitácora (el nombre, el color y «oculta» de una categoría).
IGNORED_COLUMNS = frozenset({"updated_at", "added_at", "reviewed_at", "created_at", "dismissed_at"})
IGNORED_BY_TABLE: Mapping[str, frozenset[str]] = {
    "categories": frozenset({"name", "color", "hidden"}),
}
# Tablas donde no tener fila es lo mismo que tenerla con estos valores (`transaction_notes`
# borra la fila que queda vacía): se comparan columna por columna, nunca la fila entera.
SOFT_DEFAULTS: Mapping[str, Mapping[str, Any]] = {
    "transaction_notes": {"category_id": None, "one_off": 0, "note": None},
}


# Las hijas que apuntan a una madre (columna, tabla madre) y lo que identifica a cada madre más
# allá de su id (por si un id se reusara: bases de antes del esquema 15 o filas a mano).
PARENT_COLUMNS: Mapping[str, tuple[str, str]] = {
    "link_members": ("link_id", "links"),
    "link_manual": ("link_id", "links"),
    "transaction_notes": ("category_id", "categories"),
    "merchant_categories": ("category_id", "categories"),
    "category_keywords": ("category_id", "categories"),
    "budget_caps": ("category_id", "categories"),
}
PARENT_IDENTITY: Mapping[str, tuple[str, ...]] = {
    "links": ("kind", "created_at"),
    "categories": ("builtin_key", "created_at"),
}


@dataclass(frozen=True)
class Change:
    table: str
    key: Row  # la clave primaria de la fila
    before: Row | None  # None: no existía
    after: Row | None  # None: se borró
    columns: tuple[str, ...]  # lo que cambió (para una fila nueva o borrada: toda la fila)
    # La madre a la que apunta el *antes* (`links` o `categories`): su clave (`row_key`) y su
    # identidad entonces (`PARENT_IDENTITY`); vacío si no apunta a ninguna.
    parent: Row = field(default_factory=dict)

    @property
    def row_key(self) -> str:
        return row_key(self.table, self.key)

    def to_json(self) -> Row:
        return {
            "table": self.table,
            "key": self.key,
            "before": self.before,
            "after": self.after,
            "columns": list(self.columns),
            "parent": self.parent,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Change:
        return cls(
            table=str(data["table"]),
            key=dict(data["key"]),
            before=None if data["before"] is None else dict(data["before"]),
            after=None if data["after"] is None else dict(data["after"]),
            columns=tuple(str(c) for c in data["columns"]),
            parent=dict(data.get("parent") or {}),
        )


def row_key(table: str, key: Mapping[str, Any]) -> str:
    return f"{table}:{json.dumps(list(key.values()), ensure_ascii=False)}"


def identity(table: str, row: Mapping[str, Any]) -> Row:
    return {c: row.get(c) for c in PARENT_IDENTITY[table]}


def changed_columns(table: str, before: Row | None, after: Row | None) -> tuple[str, ...]:
    """Las columnas que cambiaron de verdad (sin marcas de tiempo ni lo que no se registra)."""
    soft = SOFT_DEFAULTS.get(table)
    if soft is not None:
        old, new = before or soft, after or soft
        return tuple(c for c in soft if old.get(c, soft[c]) != new.get(c, soft[c]))
    ignored = IGNORED_COLUMNS | IGNORED_BY_TABLE.get(table, frozenset())
    if before is None or after is None:
        row = after if before is None else before
        return tuple(c for c in (row or {}) if c not in ignored)
    return tuple(c for c in after if c not in ignored and before.get(c) != after.get(c))


def _matches(change: Change, current: Row | None) -> bool:
    soft = SOFT_DEFAULTS.get(change.table)
    if soft is not None:
        now, after = current or soft, change.after or soft
        return all(now.get(c, soft[c]) == after.get(c, soft[c]) for c in change.columns)
    if change.after is None:
        return current is None
    if current is None:
        return False
    return all(current.get(c) == change.after.get(c) for c in change.columns)


def can_undo(changes: Sequence[Change], current: Mapping[str, Row | None]) -> bool:
    """Se puede deshacer si cada fila tocada sigue como la dejó la entrada (`current`: la fila de
    hoy por `row_key`, None si no existe)."""
    return bool(changes) and all(_matches(c, current.get(c.row_key)) for c in changes)


@dataclass(frozen=True)
class Session:
    start: datetime
    end: datetime
    count: int
    ids: tuple[int, ...]  # de la más reciente a la más vieja


def sessions(stamps: Sequence[tuple[int, datetime]], gap: timedelta = SESSION_GAP) -> list[Session]:
    """Agrupa (id, instante) en sesiones: una nueva tras más de `gap` sin cambios. La más reciente
    primero; dentro, de la más reciente a la más vieja."""
    ordered = sorted(stamps, key=lambda s: (s[1], s[0]), reverse=True)
    found: list[list[tuple[int, datetime]]] = []
    for item in ordered:
        if found and found[-1][-1][1] - item[1] <= gap:
            found[-1].append(item)
        else:
            found.append([item])
    return [
        Session(start=g[-1][1], end=g[0][1], count=len(g), ids=tuple(i for i, _ in g))
        for g in found
    ]


def undone_ids(undoes: Mapping[int, int]) -> frozenset[int]:
    """Las entradas deshechas. `undoes`: id de cada «Deshacer» -> la entrada que deshace. Un
    «Deshacer» que luego se deshizo no cuenta (lo más nuevo manda)."""
    undone: set[int] = set()
    for undo_id in sorted(undoes, reverse=True):
        if undo_id not in undone:
            undone.add(undoes[undo_id])
    return frozenset(undone)


@dataclass(frozen=True)
class CategoryEdit:
    """Una corrección «solo esta» de la bitácora (ya sin las deshechas ni los «Deshacer»)."""

    entry_id: int
    merchant: str
    fingerprint: str
    category_id: int | None  # None: volvió a la automática
    # False: de un lote; cuenta como corrección contraria, pero no para llegar a proponer.
    counts: bool = True


@dataclass(frozen=True)
class RuleSuggestion:
    merchant: str
    category_id: int
    fingerprints: tuple[str, ...]  # las transacciones corregidas, la más reciente primero

    @property
    def count(self) -> int:
        return len(self.fingerprints)


def rule_suggestions(
    edits: Iterable[CategoryEdit],
    rules: Mapping[str, int],
    dismissed: Iterable[tuple[str, int]],
) -> list[RuleSuggestion]:
    """Comercios que recibieron a mano «solo esta» la misma categoría en al menos
    `RULE_MIN_TIMES` transacciones y ninguna corrección contraria (otra categoría, o volver a la
    automática; también la de un lote, que no cuenta para llegar al mínimo). No se propone si la
    regla del comercio ya es esa (`rules`) ni si se descartó
    (`dismissed`: pares comercio y categoría). Nunca se aplica sola."""
    skip = set(dismissed)
    by_merchant: dict[str, list[CategoryEdit]] = {}
    for edit in sorted(edits, key=lambda e: e.entry_id):
        if edit.merchant:
            by_merchant.setdefault(edit.merchant, []).append(edit)
    found: list[RuleSuggestion] = []
    for merchant, items in by_merchant.items():
        chosen = {e.category_id for e in items}
        if len(chosen) != 1:
            continue
        category = next(iter(chosen))
        if category is None or rules.get(merchant) == category or (merchant, category) in skip:
            continue
        fingerprints = tuple(dict.fromkeys(e.fingerprint for e in reversed(items) if e.counts))
        if len(fingerprints) >= RULE_MIN_TIMES:
            found.append(RuleSuggestion(merchant, category, fingerprints))
    return sorted(found, key=lambda s: s.merchant)


ROLE_LABELS = {
    "expense": "gasto compartido",
    "reimbursement": "reembolso",
    "leg": "pata de un cambio",
    "contribution": "aporte",
    "return": "rendimiento",
    "capital": "devolución de capital",
    "mixed": "cobro mixto",
    "stored": "guardado en la caja",
    "deposit": "depósito de la caja",
    "reserved": "cubierto por la reserva",
}
LINK_LABELS = {
    "shared": "grupo compartido",
    "exchange": "cambio",
    "investment": "inversión",
    "cash_box": "caja fuerte",
    "reserve": "reserva",
}
_ENTRY_LABELS = {"initial": "saldo inicial", "income": "entrada", "expense": "salida"}
_MARK_LABELS = {
    "confirmed": "es recurrente",
    "dismissed": "no es recurrente",
    "cancelled": "cancelada",
}
_NOTHING = "—"


def _money(cents: Any, currency: Any) -> str:
    value = int(cents or 0)
    prefix = "US$" if currency == "USD" else "RD$"
    return f"{prefix} {value // 100:,}.{value % 100:02d}"


def _row_text(table: str, row: Row, columns: Sequence[str], whole: bool) -> str:  # noqa: PLR0911
    if table == "link_members":
        return ROLE_LABELS.get(str(row.get("role")), str(row.get("role")))
    if table == "links":
        label = LINK_LABELS.get(str(row.get("kind")), "vínculo")
        if not whole:
            parts = [f"{c}: {row.get(c) if row.get(c) is not None else _NOTHING}" for c in columns]
            return f"{label} ({', '.join(parts)})"
        return label + (f" «{row['name']}»" if row.get("name") else "")
    if table == "link_manual":
        return f"reembolso a mano {_money(row.get('amount_cents'), row.get('currency'))}"
    if table == "cash_entries":
        kind = _ENTRY_LABELS.get(str(row.get("kind")), "movimiento")
        return f"{kind} {_money(row.get('amount_cents'), row.get('currency'))} el {row.get('day')}"
    if table == "recurring_marks":
        status = _MARK_LABELS.get(str(row.get("status")), "sin marca")
        extra = [str(row["cadence"])] if row.get("cadence") else []
        if row.get("group_key"):
            extra.append(f"en {GROUPS.get(str(row['group_key']), row['group_key'])}")
        left = row.get("installments_left")
        if left is not None:
            extra.append(f"{left} cuotas")
        return ", ".join([status, *extra])
    if table == "recurring_unions":
        if row.get("target") == row.get("merchant"):
            return "por separado"
        return f"con {display_name(str(row.get('target')))}"
    if table in ("review_marks", "one_off_dismissals", "rule_dismissals"):
        return "revisado"
    if table == "reserve_dismissals":
        return "sugerencia descartada"
    if table == "budget_caps":
        return cap_text(row.get("cap_cents"))
    if table == "category_keywords":
        return f"«{row.get('keyword')}»"
    if table == "categories":
        return f"{row.get('name')} ({row.get('kind')})"
    if table == "transaction_notes":
        return ", ".join(_note_text(c, row.get(c)) for c in columns) or _NOTHING
    return ", ".join(f"{c}: {row.get(c)}" for c in columns) or _NOTHING


def cap_text(cents: Any) -> str:
    """«tope RD$ 16,500» o «sin presupuesto»."""
    if cents is None:
        return "sin presupuesto"
    return f"tope RD$ {int(cents) // 100:,}"


def _note_text(column: str, value: Any) -> str:
    if column == "note":
        return str(value) if value else "sin nota"
    if column == "one_off":
        return "gasto único" if value else "no es gasto único"
    return "categoría automática" if value is None else f"categoría n.º {value}"


def describe(changes: Sequence[Change], side: str) -> str:
    """Una línea corta de un lado (`before` o `after`) de las filas tocadas."""
    parts: list[str] = []
    for change in changes:
        row = change.before if side == "before" else change.after
        if row is None:
            continue
        whole = change.before is None or change.after is None
        text = _row_text(change.table, row, change.columns, whole)
        if text not in parts:
            parts.append(text)
    if not parts:
        return _NOTHING
    shown = ", ".join(parts[:3])
    return shown if len(parts) <= 3 else f"{shown} y {len(parts) - 3} más"
