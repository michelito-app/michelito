"""Schema 31: crypto <-> fiat is neutral, like a currency exchange.

Self-contained like `migrations_v27`: `db` calls `apply` as one more step of its migration
transaction and takes `VERSION` as the schema version. Idempotent.

The built-in category "Cripto" (`categories.CRYPTO`) was an income kind: selling crypto read as
income and buying it, when categorized, as spending. Buying or selling crypto is the user's own
money changing form, so it becomes a transfer kind (neither income nor spending, and it does not
move what you kept: only third-party transfers do among transfer kinds). A built-in category's
kind cannot be changed from the app, hence this step.
"""

from __future__ import annotations

import sqlite3

VERSION = 31


def apply(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE categories SET kind = 'transfer' WHERE builtin_key = 'CRYPTO'")
