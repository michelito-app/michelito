"""Correcciones hechas a mano desde el board.

- Categoría de un comercio: aplica a todas sus transacciones, pasadas y futuras. En una
  cuenta bancaria solo si encaja con la dirección: un crédito acepta ingresos y
  transferencias; un débito, gastos y transferencias.
- Categoría de una transacción: solo esa; gana sobre la del comercio.
- Gasto único: la transacción cuenta en el total, pero no en los promedios.
- Nota: texto libre del usuario sobre la transacción (hasta NOTE_MAX letras).

Se guarda el id de la categoría (`catalog`): renombrarla no toca las correcciones. Aquí se
leen y escriben con la referencia del análisis (`catalog.Category.ref`) o el id.

Una transacción se identifica por su huella (cuenta, fecha, descripción, monto,
dirección, moneda y cuántas iguales la preceden), no por su `id`: las filas de
`transactions` se recrean al reprocesar un estado.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from finanzas.analysis import catalog, categories

NOTE_MAX = 500


@dataclass(frozen=True)
class Note:
    category: str | None
    one_off: bool
    text: str = ""  # nota libre del usuario


@dataclass(frozen=True)
class Corrections:
    merchants: dict[str, str]  # comercio -> referencia de la categoría
    transactions: dict[str, Note]
    kinds: Mapping[str, categories.Kind] = field(default_factory=dict)  # de las del usuario

    def category_for(
        self,
        fingerprint: str,
        merchant: str,
        kinds: Collection[categories.Kind] | None = None,
        legacy: str | Sequence[str] | None = None,
    ) -> str | None:
        """Categoría puesta a mano: la de la transacción gana; si no, la del comercio.

        Con `kinds`, la regla del comercio solo aplica si su categoría es de uno de esos
        tipos (así "PAGO DE → Salario" no convierte en ingreso los débitos "PAGO DE …").
        `legacy`: claves anteriores del comercio, en orden (en un banco, la bancaria de
        antes de Banreservas y la de `merchant_key`); la regla de una aplica solo si no hay
        una con la clave actual ni con las anteriores a ella en la lista.
        """
        note = self.transactions.get(fingerprint)
        if note is not None and note.category is not None:
            return note.category
        fallbacks = (legacy,) if isinstance(legacy, str) else tuple(legacy or ())
        chosen = next(
            (
                found
                for key in (merchant, *fallbacks)
                if (found := self.merchants.get(key)) is not None
            ),
            None,
        )
        if chosen is not None and kinds is not None and self.kind_of(chosen) not in kinds:
            return None
        return chosen

    def kind_of(self, ref: str) -> categories.Kind:
        return self.kinds.get(ref) or categories.kind_of(ref)

    def transaction_category(self, fingerprint: str) -> str | None:
        """Categoría puesta a mano a esa transacción sola (sin reglas de comercio)."""
        note = self.transactions.get(fingerprint)
        return None if note is None else note.category

    def is_one_off(self, fingerprint: str) -> bool:
        note = self.transactions.get(fingerprint)
        return note is not None and note.one_off

    def note_for(self, fingerprint: str) -> str:
        note = self.transactions.get(fingerprint)
        return "" if note is None else note.text


NONE = Corrections({}, {})


def fingerprint(
    account: str,
    day: date,
    description: str,
    amount_cents: int,
    direction: str,
    currency: str,
    occurrence: int,
) -> str:
    parts = (account, day.isoformat(), description, str(amount_cents), direction, currency)
    text = "\x1f".join((*parts, str(occurrence)))
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def load(conn: sqlite3.Connection, known: catalog.Catalog | None = None) -> Corrections:
    found = known or catalog.load(conn)

    def ref(category_id: int | None) -> str | None:
        item = None if category_id is None else found.by_id(category_id)
        return None if item is None else item.ref

    merchants = {
        row["merchant"]: name
        for row in conn.execute("SELECT merchant, category_id FROM merchant_categories")
        if (name := ref(row["category_id"])) is not None
    }
    notes = {
        row["fingerprint"]: Note(ref(row["category_id"]), bool(row["one_off"]), row["note"] or "")
        for row in conn.execute(
            "SELECT fingerprint, category_id, one_off, note FROM transaction_notes"
        )
    }
    return Corrections(merchants, notes, found.kinds())


def set_merchant_category(
    conn: sqlite3.Connection, merchant: str, category: str | int | None
) -> None:
    """`category`: referencia del análisis o id; `None` borra la regla."""
    if category is None:
        conn.execute("DELETE FROM merchant_categories WHERE merchant = ?", (merchant,))
        return
    category_id = catalog.resolve_ref(conn, category)
    conn.execute(
        "INSERT INTO merchant_categories (merchant, category_id, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(merchant) DO UPDATE SET category_id = excluded.category_id, "
        "updated_at = excluded.updated_at",
        (merchant, category_id, _now()),
    )


def set_transaction_category(
    conn: sqlite3.Connection, fingerprint: str, category: str | int | None
) -> None:
    category_id = None if category is None else catalog.resolve_ref(conn, category)
    _upsert_note(conn, fingerprint, "category_id", category_id)


def set_one_off(conn: sqlite3.Connection, fingerprint: str, one_off: bool) -> None:
    _upsert_note(conn, fingerprint, "one_off", int(one_off))


def set_note(conn: sqlite3.Connection, fingerprint: str, text: str | None) -> None:
    """Guarda la nota (sin espacios de más a los lados); vacía o `None` la borra."""
    clean = (text or "").strip()
    if len(clean) > NOTE_MAX:
        raise ValueError(f"la nota tiene más de {NOTE_MAX} letras")
    _upsert_note(conn, fingerprint, "note", clean or None)


def _upsert_note(
    conn: sqlite3.Connection, fingerprint: str, column: str, value: str | int | None
) -> None:
    if column not in ("category_id", "one_off", "note"):  # el nombre va en el SQL: lista cerrada
        raise ValueError(f"columna desconocida: {column}")
    conn.execute(
        f"INSERT INTO transaction_notes (fingerprint, {column}, updated_at) VALUES (?, ?, ?) "
        f"ON CONFLICT(fingerprint) DO UPDATE SET {column} = excluded.{column}, "
        "updated_at = excluded.updated_at",
        (fingerprint, value, _now()),
    )
    conn.execute(
        "DELETE FROM transaction_notes "
        "WHERE fingerprint = ? AND category_id IS NULL AND one_off = 0 AND note IS NULL",
        (fingerprint,),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
