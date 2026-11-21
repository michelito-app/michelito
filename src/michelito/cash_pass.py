"""The cash account's system pass for the CLI (`cash_activation.refresh`): every command that
opens the database runs it first, so `report`, `spending`, `insights` and `log` see the same
figures as the board (scheduled occurrences due, automatic withdrawals). Never breaks the
command: a failure is logged and the stored data is used."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from michelito import config
from michelito.analysis import cash_activation, spending, transfers


def run(conn: sqlite3.Connection, holders_path: Path) -> None:
    holders = transfers.load_holders(holders_path)
    today = config.local_today()
    signature = hashlib.sha256(repr(holders).encode()).hexdigest()[:16]
    cash_activation.refresh_safely(
        conn, today, lambda c: spending.load_all(c, holders, None, today), signature
    )
