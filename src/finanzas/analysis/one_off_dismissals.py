"""Sugerencias de gasto único que el usuario descartó ("No es único"), por huella.

Van aparte de `transactions` (como las correcciones), así que sobreviven a
`parse --retry`. Nada aquí hace commit: quien llama envuelve la escritura en `with conn:`.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


def load(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(row[0] for row in conn.execute("SELECT fingerprint FROM one_off_dismissals"))


def set_dismissed(conn: sqlite3.Connection, fingerprint: str, dismissed: bool) -> None:
    if not dismissed:
        conn.execute("DELETE FROM one_off_dismissals WHERE fingerprint = ?", (fingerprint,))
        return
    conn.execute(
        "INSERT INTO one_off_dismissals (fingerprint, updated_at) VALUES (?, ?) "
        "ON CONFLICT(fingerprint) DO NOTHING",
        (fingerprint, datetime.now(UTC).isoformat(timespec="seconds")),
    )
