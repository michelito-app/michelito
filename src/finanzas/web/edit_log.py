"""Correcciones de una transacción con su entrada de bitácora (`analysis.changelog`).

`PATCH /api/transactions/{huella}` puede cambiar a la vez la nota, «gasto único» y la categoría
(solo esta o todo el comercio): cada una queda como su propia entrada, todas en la transacción
SQLite de quien llama. Aquí también los textos cortos de cada lado («Efectivo → Delivery»).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from finanzas.analysis import catalog, changelog
from finanzas.analysis.changelog_rules import CATEGORY_KIND
from finanzas.analysis.spending import Movement
from finanzas.web import transactions

NOTHING = "—"
_SHORT = 80


def subject(move: Movement) -> str:
    """Cómo se nombra la transacción en la bitácora: su comercio o, si no, su descripción."""
    return move.merchant or move.description


def short(text: str | None) -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return NOTHING
    return clean if len(clean) <= _SHORT else clean[: _SHORT - 1] + "…"


def yes_no(value: bool) -> str:
    return "sí" if value else "no"


def link_subject(conn: sqlite3.Connection, link_id: int) -> str:
    """El nombre de un vínculo en la bitácora: su nombre, «Con quién» o su número."""
    row = conn.execute(
        "SELECT kind, name, with_whom FROM links WHERE id = ?", (link_id,)
    ).fetchone()
    if row is None:
        return f"Vínculo n.º {link_id}"
    labels = {
        "shared": "Grupo",
        "exchange": "Cambio",
        "investment": "Inversión",
        "reserve": "Reserva",
    }
    return row["name"] or row["with_whom"] or f"{labels.get(row['kind'], 'Vínculo')} n.º {link_id}"


def _rule_name(conn: sqlite3.Connection, known: catalog.Catalog, merchant: str) -> str:
    row = conn.execute(
        "SELECT category_id FROM merchant_categories WHERE merchant = ?", (merchant,)
    ).fetchone()
    found = None if row is None else known.by_id(int(row[0]))
    return "sin regla" if found is None else found.name


def edit_transaction(
    conn: sqlite3.Connection,
    target: Movement,
    known: catalog.Catalog,
    chosen: int | None,
    one_off: bool | None,
    scope: transactions.Scope,
    note: str | None,
    flow: Sequence[Movement],
) -> None:
    """Nota, gasto único y categoría, cada uno con su entrada (sin cambio real, sin entrada)."""
    fp, name = target.fingerprint, subject(target)
    if note is not None:
        with changelog.track(
            conn,
            "nota",
            "transaccion",
            fp,
            name,
            before=short(target.note),
            after=short(note),
            merchant=target.merchant,
            fingerprints=[fp],
        ):
            transactions.apply_edit(conn, target, None, None, scope, note)
    if one_off is not None:
        with changelog.track(
            conn,
            "gasto_unico",
            "transaccion",
            fp,
            name,
            before=yes_no(target.one_off),
            after=yes_no(one_off),
            merchant=target.merchant,
            fingerprints=[fp],
        ):
            transactions.apply_edit(conn, target, None, one_off, scope)
    if chosen is None:
        return
    found = known.by_id(chosen)
    after = found.name if found is not None else str(chosen)
    if scope == "merchant":
        with changelog.track(
            conn,
            "regla",
            "comercio",
            target.merchant,
            target.merchant,
            before=_rule_name(conn, known, target.merchant),
            after=after,
            merchant=target.merchant,
            fingerprints=[m.fingerprint for m in flow if m.merchant == target.merchant],
        ):
            transactions.apply_edit(conn, target, chosen, None, scope)
        return
    with changelog.track(
        conn,
        CATEGORY_KIND,
        "transaccion",
        fp,
        name,
        before=target.category,
        after=after,
        merchant=target.merchant,
        fingerprints=[fp],
    ):
        transactions.apply_edit(conn, target, chosen, None, scope)
