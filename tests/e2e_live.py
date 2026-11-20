"""Live sync in the e2e test server (`tests.e2e_server --live`, made-up data only).

The base e2e data plus three made-up provisional purchases on the synthetic Popular card (its
last statement closes on January 13) and two test-only routes the Playwright specs call:

- `POST /e2e/live/statement`: stores a synthetic Popular statement (January 14 to February 13)
  through ingestion, as a downloaded statement would be. It has the colmado purchase (so that
  provisional is confirmed) and not the shoe store's (so it becomes a To review item); the
  bookstore one stays pending (its window is not covered yet).
- `POST /e2e/live/reset`: rebuilds the database, so each spec starts from the same state.

Both exist only in this server; the board never has them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI

from michelito import db
from michelito.analysis import live_store
from tests.live_helpers import card_statement, ingest_card

ACCOUNT = "popular:credit_card"
CARD = "1234"  # the synthetic Popular card of `tests.samples`
NOW = "2026-02-19T12:00:00+00:00"
# spanish-data: begin (synthetic merchants, upper case like bank text)
CONFIRMED = ("2026-02-08", "COLMADO FICTICIO", "845.00")
CONFIRMED_ROW = ("2026-02-09", "COLMADO FICTICIO SANTO DOMINGO", "845.00")
PENDING = ("2026-02-16", "LIBRERIA FICTICIA", "1230.00")
VANISHED = ("2026-02-04", "ZAPATERIA FICTICIA", "990.00")
OTHER_ROW = ("2026-01-20", "FERRETERIA FICTICIA", "410.00")
# spanish-data: end


def add_provisionals(conn: sqlite3.Connection) -> None:
    with conn:
        for number, (day, merchant, amount) in enumerate((CONFIRMED, PENDING, VANISHED), 1):
            made = live_store.Made(
                message_id=f"e2e-alert-{number}",
                account=ACCOUNT,
                last4=CARD,
                day=date.fromisoformat(day),
                amount_cents=int(Decimal(amount) * 100),
                currency="DOP",
                merchant=merchant,
            )
            live_store.add_made_up(conn, made, NOW)


def register(app: FastAPI, path: Path, build: Callable[[Path], None]) -> None:
    @app.post("/e2e/live/statement")
    def post_statement() -> dict[str, str]:
        statement = card_statement("2026-02-13", [OTHER_ROW, CONFIRMED_ROW], CARD, "2026-01-14")
        with closing(db.connect(path)) as conn:
            return {"status": ingest_card(conn, statement)}

    @app.post("/e2e/live/reset")
    def post_reset() -> dict[str, str]:
        for leftover in path.parent.glob(f"{path.name}*"):
            leftover.unlink()
        build(path)
        return {"status": "ok"}
