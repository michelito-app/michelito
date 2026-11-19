"""Helpers shared by several tests (not tests themselves)."""

import sqlite3

from michelito import db
from michelito.parsers.common import Statement
from tests.test_ingest import add_document


def store(conn: sqlite3.Connection, statement: Statement) -> None:
    """Store an already parsed statement under a new document, skipping ingestion."""
    name = f"doc-{conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]}.pdf"
    document_id = add_document(conn, name)
    with conn:
        db.store_statement(conn, document_id, statement)
