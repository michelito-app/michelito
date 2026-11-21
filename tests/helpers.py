"""Helpers shared by several tests (not tests themselves)."""

import sqlite3

from michelito import db, migrations_v23
from michelito.analysis import categories
from michelito.parsers.common import Statement
from tests.test_ingest import add_document


def shown_name(ref: str) -> str:
    """The name a system category is shown with: its reference, except the cash transfer one,
    which schema 23 renamed (`migrations_v23`)."""
    return migrations_v23.NEW_CATEGORY_NAME if ref == categories.CASH_BOX else ref


def store(conn: sqlite3.Connection, statement: Statement) -> None:
    """Store an already parsed statement under a new document, skipping ingestion."""
    name = f"doc-{conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]}.pdf"
    document_id = add_document(conn, name)
    with conn:
        db.store_statement(conn, document_id, statement)
