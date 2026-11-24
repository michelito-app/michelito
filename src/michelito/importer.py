"""Manual import of statements downloaded from the bank's website.

It follows the same path as a Gmail attachment: it is copied into the raw archive (0600),
registered as a document and parsed by `ingest`. The same file (same sha256) is not registered
twice; a repeated statement ends up as `duplicate`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from michelito.config import ensure_private_dir
from michelito.extract import MAX_ATTACHMENT_BYTES, safe_filename, write_private

SOURCE = "imported"
# Statements the demo generates (`michelito.demo`): no PDF and no raw file.
GENERATED = "generated"
# Statements uploaded in hosted mode (`michelito.hosted.uploads`): read in memory, no raw file.
UPLOADED = "uploaded"
# Statements an AI connector read and the person approved (`web.imports`): no file either.
AI = "ai"
FOLDER = "imported"
_SENDER = "manual import"
_PDF_MAGIC = b"%PDF"
# `documents` requires a message; each import gets its own, which never clashes with Gmail.
_MESSAGE_PREFIX = "imported-"


class ImportRejected(ValueError):
    """The file cannot be imported (it does not exist, is not a PDF or is too big)."""


@dataclass(frozen=True)
class Registered:
    document_id: int
    new: bool  # False: the same file was already registered


def register(conn: sqlite3.Connection, source: Path, raw_root: Path, now: datetime) -> Registered:
    """Copy the PDF to raw/imported/<year-month>/ and leave it pending to be parsed."""
    data = _read_pdf(source)
    digest = hashlib.sha256(data).hexdigest()
    known = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ? ORDER BY id", (digest,)
    ).fetchone()
    if known is not None:
        return Registered(known[0], new=False)
    ensure_private_dir(raw_root)
    ensure_private_dir(raw_root / FOLDER)
    folder = ensure_private_dir(raw_root / FOLDER / now.strftime("%Y-%m"))
    target = _free_path(folder, safe_filename(source.name), digest)
    message_id = f"{_MESSAGE_PREFIX}{digest[:32]}"
    stamp = now.isoformat(timespec="seconds")
    # The copy is written inside the transaction: if the registration fails no orphan copy is
    # left, and if the copy fails the registration is rolled back. A copy that was already there
    # (the same one, by the sha256 in its name) is neither rewritten nor deleted.
    created = not target.exists()
    try:
        with conn:
            document_id = _record(
                conn,
                SOURCE,
                message_id,
                source.name,
                target.name,
                str(target),
                digest,
                len(data),
                stamp,
            )
            if created:
                write_private(target, data)
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise
    return Registered(document_id, new=True)


def register_generated(
    conn: sqlite3.Connection, name: str, content: bytes, now: datetime
) -> Registered:
    """Register a generated statement (the demo: there is no PDF nor raw file) as a pending
    document, with the same records as an imported PDF; `content` gives its sha256 (the same
    content is not registered twice). The caller parses it with `ingest.ingest_statement`."""
    return _register_without_file(conn, GENERATED, name, content, now)


def register_ai(conn: sqlite3.Connection, name: str, content: bytes, now: datetime) -> Registered:
    """Register a statement an AI read and the person approved (`web.imports`), like a generated
    one: no file, `content` (the approved reading) gives its sha256."""
    return _register_without_file(conn, AI, name, content, now)


def _register_without_file(
    conn: sqlite3.Connection, source: str, name: str, content: bytes, now: datetime
) -> Registered:
    digest = hashlib.sha256(content).hexdigest()
    known = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (digest,)).fetchone()
    if known is not None:
        return Registered(known[0], new=False)
    stamp = now.isoformat(timespec="seconds")
    message_id = f"{source}-{digest[:32]}"
    path = f"{source}:{name}"
    with conn:
        document_id = _record(
            conn, source, message_id, name, name, path, digest, len(content), stamp
        )
    return Registered(document_id, new=True)


def register_upload(
    conn: sqlite3.Connection, name: str, content: bytes, now: datetime
) -> Registered:
    """Register an uploaded PDF (hosted mode) as a pending document **without writing it
    anywhere**: the path only names it (`uploaded:<sha256>`) and the caller parses the bytes it
    holds in memory. The same file (same sha256) is not registered twice."""
    digest = hashlib.sha256(content).hexdigest()
    known = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ? ORDER BY id", (digest,)
    ).fetchone()
    if known is not None:
        return Registered(known[0], new=False)
    stamp = now.isoformat(timespec="seconds")
    message_id = f"{UPLOADED}-{digest[:32]}"
    filename = safe_filename(name) or f"{digest[:12]}.pdf"
    with conn:
        document_id = _record(
            conn,
            UPLOADED,
            message_id,
            filename,
            filename,
            f"{UPLOADED}:{digest}",
            digest,
            len(content),
            stamp,
        )
    return Registered(document_id, new=True)


def _record(
    conn: sqlite3.Connection,
    source: str,
    message_id: str,
    subject: str,
    filename: str,
    path: str,
    digest: str,
    size: int,
    stamp: str,
) -> int:
    """The message (if missing) and the pending document; returns the document id."""
    conn.execute(
        "INSERT INTO gmail_messages (message_id, source, sender, subject, received_at, "
        "attachments_saved, fetched_at) VALUES (?, ?, ?, ?, ?, 1, ?) "
        "ON CONFLICT(message_id) DO NOTHING",
        (message_id, source, _SENDER, subject, stamp, stamp),
    )
    cursor = conn.execute(
        "INSERT INTO documents (message_id, source, filename, path, sha256, size, "
        "received_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
        (message_id, source, filename, path, digest, size, stamp),
    )
    if cursor.lastrowid is None:  # pragma: no cover - sqlite always sets it after an INSERT
        raise RuntimeError("could not register the document")
    return cursor.lastrowid


def _read_pdf(source: Path) -> bytes:
    if not source.is_file():
        raise ImportRejected(f"{source}: does not exist or is not a file")
    if source.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise ImportRejected(f"{source}: exceeds the {MAX_ATTACHMENT_BYTES}-byte limit")
    data = source.read_bytes()
    if not data.startswith(_PDF_MAGIC):
        raise ImportRejected(f"{source}: is not a PDF")
    return data


def _free_path(folder: Path, name: str, digest: str) -> Path:
    """The path for the copy; if the name is taken, part of the sha256 is prepended."""
    target = folder / name
    return target if not target.exists() else folder / f"{digest[:12]}_{name}"
