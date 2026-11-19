"""Ayudas compartidas por varias pruebas (no son pruebas)."""

import sqlite3

from finanzas import db
from finanzas.parsers.common import Statement
from tests.test_ingest import add_document


def store(conn: sqlite3.Connection, statement: Statement) -> None:
    """Guarda un estado ya interpretado con un documento nuevo, sin pasar por la ingesta."""
    name = f"doc-{conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]}.pdf"
    document_id = add_document(conn, name)
    with conn:
        db.store_statement(conn, document_id, statement)
