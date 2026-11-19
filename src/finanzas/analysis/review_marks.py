"""Lo marcado "Ya lo revisé" en «Para revisar», por huella y tipo (ver `analysis.review`).

Va aparte de `transactions` (como las correcciones), así sobrevive a `parse --retry`. Los
gastos únicos no van aquí: su "revisado" es el descarte de siempre (`one_off_dismissals`).
Nada aquí hace commit: quien llama envuelve la escritura en `with conn:`.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from finanzas.db import REVIEW_MARK_KINDS


def load(conn: sqlite3.Connection) -> frozenset[tuple[str, str]]:
    rows = conn.execute("SELECT fingerprint, kind FROM review_marks")
    return frozenset((str(row[0]), str(row[1])) for row in rows)


def set_reviewed(conn: sqlite3.Connection, fingerprint: str, kind: str, reviewed: bool) -> None:
    if kind not in REVIEW_MARK_KINDS:
        raise ValueError(f"tipo de revisión desconocido: {kind}")
    if not reviewed:
        conn.execute(
            "DELETE FROM review_marks WHERE fingerprint = ? AND kind = ?", (fingerprint, kind)
        )
        return
    conn.execute(
        "INSERT INTO review_marks (fingerprint, kind, reviewed_at) VALUES (?, ?, ?) "
        "ON CONFLICT(fingerprint, kind) DO NOTHING",
        (fingerprint, kind, datetime.now(UTC).isoformat(timespec="seconds")),
    )
