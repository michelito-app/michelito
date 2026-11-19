"""Descarga incremental de correos y adjuntos desde Gmail al archivo crudo.

Cada mensaje se procesa una sola vez (su ID queda en `gmail_messages`), así
que correrlo varias veces no duplica nada.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from finanzas.config import Source
from finanzas.gmail import AttachmentRef, MailMessage

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MESSAGE_ID = re.compile(r"[0-9A-Za-z_-]{1,64}")
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class MailClient(Protocol):
    def list_message_ids(self, query: str) -> Iterator[str]: ...

    def get_message(self, message_id: str) -> MailMessage: ...

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes: ...


@dataclass(frozen=True)
class ExtractStats:
    source: str
    new_messages: int
    saved_files: int
    duplicates: int


def safe_filename(name: str) -> str:
    cleaned = _UNSAFE.sub("_", Path(name).name).strip("._")
    return cleaned or "adjunto"


def unique_names(attachments: list[AttachmentRef]) -> list[str]:
    """Nombres seguros y distintos dentro de un mismo mensaje."""
    used: set[str] = set()
    names = []
    for index, attachment in enumerate(attachments):
        name = safe_filename(attachment.filename)
        if name in used:
            name = f"{index}_{name}"
        used.add(name)
        names.append(name)
    return names


def write_private(path: Path, data: bytes) -> None:
    """Escribe el archivo con permisos solo para el usuario (0600), sin seguir enlaces."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def extract_source(
    conn: sqlite3.Connection, client: MailClient, source: Source, raw_root: Path
) -> ExtractStats:
    known = {row[0] for row in conn.execute("SELECT message_id FROM gmail_messages")}
    new_messages = saved = duplicates = 0
    for message_id in client.list_message_ids(source.query):
        if message_id in known:
            continue
        message = client.get_message(message_id)
        message_saved, message_duplicates = _store_message(conn, client, source, raw_root, message)
        known.add(message_id)
        new_messages += 1
        saved += message_saved
        duplicates += message_duplicates
    return ExtractStats(source.name, new_messages, saved, duplicates)


def _store_message(
    conn: sqlite3.Connection,
    client: MailClient,
    source: Source,
    raw_root: Path,
    message: MailMessage,
) -> tuple[int, int]:
    if not _MESSAGE_ID.fullmatch(message.message_id):
        raise ValueError(f"ID de mensaje inesperado: {message.message_id!r}")
    folder = raw_root / source.name / message.received_at.strftime("%Y-%m") / message.message_id
    wanted = [a for a in message.attachments if a.filename.lower().endswith(source.extensions)]
    statuses: list[str] = []
    with conn:
        conn.execute(
            "INSERT INTO gmail_messages (message_id, source, sender, subject, received_at, "
            "attachments_saved, fetched_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (
                message.message_id,
                source.name,
                message.sender,
                message.subject,
                message.received_at.isoformat(),
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        for attachment, name in zip(wanted, unique_names(wanted), strict=True):
            statuses.append(
                _store_attachment(conn, client, source, folder, message, attachment, name)
            )
        saved = len(statuses) - statuses.count("error")
        conn.execute(
            "UPDATE gmail_messages SET attachments_saved = ? WHERE message_id = ?",
            (saved, message.message_id),
        )
        write_private(folder / "message.json", _metadata(message))
    return saved, statuses.count("duplicate")


def _store_attachment(
    conn: sqlite3.Connection,
    client: MailClient,
    source: Source,
    folder: Path,
    message: MailMessage,
    attachment: AttachmentRef,
    name: str,
) -> str:
    path = folder / name
    if attachment.size > MAX_ATTACHMENT_BYTES:
        megabytes = attachment.size // (1024 * 1024)
        reason = f"adjunto de {megabytes} MB supera el límite; no se descargó"
        _insert_document(conn, source, message, path, "", attachment.size, "error", reason)
        return "error"
    data = client.get_attachment(message.message_id, attachment.attachment_id)
    write_private(path, data)
    digest = hashlib.sha256(data).hexdigest()
    seen = conn.execute("SELECT 1 FROM documents WHERE sha256 = ?", (digest,)).fetchone()
    status, detail = _classify(bool(seen), path)
    _insert_document(conn, source, message, path, digest, len(data), status, detail)
    return status


def _classify(seen: bool, path: Path) -> tuple[str, str | None]:
    if seen:
        return "duplicate", "mismo archivo que otro documento ya guardado"
    if path.suffix.lower() == ".pdf":
        return "pending", None
    return "archived", "formato sin parser en la fase 1"


def _insert_document(
    conn: sqlite3.Connection,
    source: Source,
    message: MailMessage,
    path: Path,
    digest: str,
    size: int,
    status: str,
    detail: str | None,
) -> None:
    conn.execute(
        "INSERT INTO documents (message_id, source, filename, path, sha256, size, received_at, "
        "status, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(message_id, filename) DO NOTHING",
        (
            message.message_id,
            source.name,
            path.name,
            str(path),
            digest,
            size,
            message.received_at.isoformat(),
            status,
            detail,
        ),
    )


def _metadata(message: MailMessage) -> bytes:
    payload = {
        "message_id": message.message_id,
        "sender": message.sender,
        "subject": message.subject,
        "received_at": message.received_at.isoformat(),
        "body_text": message.body_text,
        "attachments": [{"filename": a.filename, "size": a.size} for a in message.attachments],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
