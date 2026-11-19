"""Cambiar la categoría de varias transacciones a la vez (selección múltiple de Transacciones).

- `plan` (lógica pura): qué huellas se cambian y cuáles se omiten, con su motivo. Se omite una
  transacción cuyo vínculo fija su categoría (caja fuerte, inversión, reembolso, cambio de
  divisas: lo que pone `spending.with_links`), un movimiento a mano de la caja fuerte que no
  encaja (una entrada solo va a un ingreso y una salida a un gasto, como al anotarlo), un
  débito que iría a una categoría de ingreso (un débito no es ingreso), la que ya está en esa
  categoría y una huella que no existe.
  «Ya está» mira la categoría que se ve, venga de donde venga (regla del comercio, palabra
  clave, automática): no se le pone una corrección propia, así que si después cambia la regla
  del comercio, esa transacción la sigue (decidido: el lote no «congela» lo que ya estaba).
- `apply`: guarda «solo esta» en cada una (nunca una regla por comercio) dentro de la
  transacción SQLite de quien llama, como UNA entrada de bitácora (`categoria_lote`) con las
  huellas que cambiaron y el motivo común. «Deshacer» vuelve cada una a su corrección anterior
  exacta (también «sin corrección»), sin tocar su nota ni «gasto único».
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from finanzas.analysis import cash_box, catalog, changelog, changelog_rules, corrections
from finanzas.analysis.spending import Movement

BATCH_KIND = changelog_rules.BATCH_KIND
BATCH_MAX = 500
# Los vínculos que ponen la categoría de sus transacciones (un gasto compartido no la cambia).
FIXED_BY_LINK = frozenset({"cash_box", "investment", "reimbursement", "exchange"})
# Cuántas categorías de antes se nombran en la línea de la bitácora; más, «varias categorías».
_BEFORE_NAMES = 3

SkipReason = Literal["vinculo", "caja", "direccion", "sin_cambio", "desconocida"]
SKIP_MESSAGES: dict[str, str] = {
    "vinculo": "está en un vínculo que fija su categoría",
    "caja": "es de la caja fuerte: una entrada va a un ingreso y una salida a un gasto",
    "direccion": "es un débito: no puede ser ingreso",
    "sin_cambio": "ya estaba en esa categoría",
    "desconocida": "no existe",
}


@dataclass(frozen=True)
class Skipped:
    fingerprint: str
    reason: SkipReason

    @property
    def message(self) -> str:
        return SKIP_MESSAGES[self.reason]


@dataclass(frozen=True)
class Plan:
    chosen: tuple[Movement, ...]  # las que cambian, en el orden pedido
    skipped: tuple[Skipped, ...]


def fits(move: Movement, kind: str) -> bool:
    """¿La categoría de ese tipo le cabe a la transacción? Un débito (monto positivo) no puede
    ser ingreso; un crédito sí puede ir a un gasto (una devolución resta de su categoría)."""
    return not (kind == "ingreso" and move.amount > 0)


def plan(
    movements: Sequence[Movement], fingerprints: Iterable[str], target: catalog.Category
) -> Plan:
    """Qué se cambia y qué no (sin repetir huellas)."""
    by_fp = {m.fingerprint: m for m in movements}
    chosen: list[Movement] = []
    skipped: list[Skipped] = []
    for fp in dict.fromkeys(fingerprints):
        move = by_fp.get(fp)
        reason = _skip_reason(move, target)
        if reason is not None:
            skipped.append(Skipped(fp, reason))
        elif move is not None:
            chosen.append(move)
    return Plan(tuple(chosen), tuple(skipped))


def _skip_reason(move: Movement | None, target: catalog.Category) -> SkipReason | None:
    if move is None:
        return "desconocida"
    if move.link in FIXED_BY_LINK:
        return "vinculo"
    if cash_box.manual_category_error(move.fingerprint, move.amount, target.kind) is not None:
        return "caja"
    if not fits(move, target.kind):
        return "direccion"
    if move.ref == target.ref:
        return "sin_cambio"
    return None


def count_text(count: int) -> str:
    return "1 transacción" if count == 1 else f"{count} transacciones"


def before_text(moves: Sequence[Movement]) -> str:
    """Lo de antes en la bitácora: la categoría (o las de más a menos frecuente, hasta tres)."""
    names = [name for name, _ in Counter(m.category for m in moves).most_common()]
    if len(names) > _BEFORE_NAMES:
        return "varias categorías"
    return ", ".join(names)


def apply(
    conn: sqlite3.Connection, chosen: Sequence[Movement], target: catalog.Category, reason: str
) -> int | None:
    """Pone `target` en cada una (en la transacción de quien llama) y devuelve la entrada de la
    bitácora (None si no hubo nada que cambiar). Un error deja todo como estaba."""
    if not chosen:
        return None
    fingerprints = [m.fingerprint for m in chosen]
    with changelog.track(
        conn,
        BATCH_KIND,
        "categoria",  # el objetivo es la categoría a la que pasan (sin migrar `change_log`)
        str(target.id),
        count_text(len(chosen)),
        before=before_text(chosen),
        after=target.name,
        fingerprints=fingerprints,
    ) as draft:
        for fp in fingerprints:
            corrections.set_transaction_category(conn, fp, target.id)
    if draft.entry_id is not None and reason.strip():
        changelog.set_reason(conn, draft.entry_id, reason)
    return draft.entry_id
