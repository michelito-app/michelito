"""Corrections made by hand from the board.

- Category of a merchant: applies to all its transactions, past and future. On a bank
  account only if it fits the direction: a credit accepts income and transfers; a debit,
  expenses and transfers.
- Category of a transaction: only that one; it wins over the merchant's.
- One-off expense: the transaction counts in the total, but not in the averages.
- Note: the user's free text about the transaction (up to NOTE_MAX characters).

The category id is stored (`catalog`): renaming the category does not touch corrections.
Here they are read and written with the analysis reference (`catalog.Category.ref`) or the id.

A transaction is identified by its fingerprint (account, date, description, amount,
direction, currency and how many identical ones precede it), not by its `id`: the
`transactions` rows are recreated when a statement is reprocessed.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from michelito.analysis import catalog, categories
from michelito.i18n import t

NOTE_MAX = 500


@dataclass(frozen=True)
class Note:
    category: str | None
    one_off: bool
    text: str = ""  # the user's free note


@dataclass(frozen=True)
class Corrections:
    merchants: dict[str, str]  # merchant -> category reference
    transactions: dict[str, Note]
    kinds: Mapping[str, categories.Kind] = field(default_factory=dict)  # of the user's categories

    def category_for(
        self,
        fingerprint: str,
        merchant: str,
        kinds: Collection[categories.Kind] | None = None,
        legacy: str | Sequence[str] | None = None,
    ) -> str | None:
        """Category set by hand: the transaction's wins; otherwise the merchant's.

        With `kinds`, the merchant rule only applies if its category is of one of those kinds
        (so a "PAGO DE" -> salary rule does not turn "PAGO DE ..." debits into income).
        `legacy`: earlier keys of the merchant, in order (for a bank, the bank key from before
        Banreservas and the `merchant_key` one); a rule on one of them applies only if there is
        none on the current key nor on the keys before it in the list.
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
        """Category set by hand on that single transaction (no merchant rules)."""
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
    """`category`: analysis reference or id; `None` deletes the rule."""
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
    """Stores the note (stripped); empty or `None` deletes it."""
    clean = (text or "").strip()
    if len(clean) > NOTE_MAX:
        raise ValueError(t("analysis.corrections.note_too_long", max=NOTE_MAX))
    _upsert_note(conn, fingerprint, "note", clean or None)


def _upsert_note(
    conn: sqlite3.Connection, fingerprint: str, column: str, value: str | int | None
) -> None:
    if column not in ("category_id", "one_off", "note"):  # the name goes into the SQL: closed list
        raise ValueError(f"unknown column: {column}")
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
