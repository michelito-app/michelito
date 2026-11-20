"""Helpers for the live-sync tests: a synthetic Popular card that receives alerts, its
statements (balanced, stored through `ingest` so they reconcile) and the alerts themselves."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from michelito import ingest
from michelito.analysis import live_match, live_store
from michelito.parsers.common import Section, Statement, Transaction
from tests import alert_samples as samples
from tests.test_ingest import add_document

NOW = "2026-02-20T12:00:00+00:00"
ACCOUNT = "popular:credit_card"
Row = tuple[str, str, str] | tuple[str, str, str, str]  # (day, description, amount[, currency])


def row(item: Row) -> Transaction:
    day, description, amount = item[0], item[1], item[2]
    currency = item[3] if len(item) == 4 else "DOP"  # noqa: PLR2004
    posted = date.fromisoformat(day)
    return Transaction(
        transacted_on=posted,
        posted_on=posted,
        description=description,
        amount=Decimal(amount),
        direction="debit",
        currency=currency,
        reference=None,
        mcc=None,
        raw_line=f"{day} {description} {amount}",
    )


def card_statement(
    period_end: str, rows: Sequence[Row], card: str = samples.CARD, period_start: str | None = None
) -> Statement:
    """A balanced Popular card statement (one section per currency with rows; DOP always)."""
    items = [row(r) for r in rows]
    sections = []
    for currency in ("DOP", "USD"):
        mine = tuple(i for i in items if i.currency == currency)
        if not mine and currency == "USD":
            continue
        total = sum((i.amount for i in mine), Decimal(0))
        sections.append(
            Section(
                currency=currency,
                previous_balance=Decimal(0),
                closing_balance=total,
                minimum_payment=None,
                credit_limit=None,
                printed_debits=total,
                printed_credits=Decimal(0),
                transactions=mine,
            )
        )
    end = date.fromisoformat(period_end)
    return Statement(
        parser="popular_card",
        institution="popular",
        kind="credit_card",
        product="VISA ORO FICTICIA",
        identifier=card,
        period_end=end,
        due_date=None,
        sections=tuple(sections),
        period_start=None if period_start is None else date.fromisoformat(period_start),
    )


def ingest_card(conn: sqlite3.Connection, statement: Statement) -> str:
    """Store a statement as a document would (validated, then reconciled)."""
    name = f"card-{statement.period_end.isoformat()}-{statement.identifier}.pdf"
    document_id = add_document(conn, name)
    return ingest.ingest_statement(conn, document_id, statement.parser, statement)


def known_card(conn: sqlite3.Connection, card: str = samples.CARD) -> None:
    """A January statement, so the card (and its account) is known."""
    first = card_statement(
        "2026-01-31", [("2026-01-10", "LIBRERIA FICTICIA", "500.00")], card, "2026-01-01"
    )
    assert ingest_card(conn, first) == "parsed"


def alert(conn: sqlite3.Connection, message_id: str, **fields: str) -> str:
    """Record an alert and reconcile; returns the provisional's fingerprint (if one)."""
    email = samples.alert_email(message_id, **fields)
    with conn:
        live_store.record(conn, email, "popular_alerts", NOW)
        live_match.reconcile(conn, NOW)
    row = conn.execute("SELECT id FROM alerts WHERE message_id = ?", (message_id,)).fetchone()
    return live_store.fingerprint(int(row[0]))


def status(conn: sqlite3.Connection, mark: str) -> str:
    alert_id = live_store.alert_id(mark)
    return str(conn.execute("SELECT status FROM alerts WHERE id = ?", (alert_id,)).fetchone()[0])
