"""Importación manual de estados descargados del portal del banco.

Sigue el mismo camino que un adjunto de Gmail: se copia al archivo crudo (0600),
se registra como documento y lo interpreta `ingest`. El mismo archivo (mismo
sha256) no se registra dos veces; un estado repetido queda como `duplicate`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from finanzas.config import ensure_private_dir
from finanzas.extract import MAX_ATTACHMENT_BYTES, safe_filename, write_private

SOURCE = "importado"
# Estados que genera la demo (`finanzas.demo`): sin PDF ni archivo crudo.
GENERATED = "generado"
FOLDER = "importados"
_SENDER = "importación manual"
_PDF_MAGIC = b"%PDF"
# `documents` exige un mensaje; cada importación tiene uno propio que no choca con Gmail.
_MESSAGE_PREFIX = "importado-"


class ImportRejected(ValueError):
    """El archivo no se puede importar (no existe, no es PDF o es demasiado grande)."""


@dataclass(frozen=True)
class Registered:
    document_id: int
    new: bool  # False: el mismo archivo ya estaba registrado


def register(conn: sqlite3.Connection, source: Path, raw_root: Path, now: datetime) -> Registered:
    """Copia el PDF a raw/importados/<año-mes>/ y lo deja pendiente de interpretar."""
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
    # La copia se escribe dentro de la transacción: si el registro falla no queda una copia
    # huérfana, y si la copia falla el registro se deshace. Una copia que ya estaba (la
    # misma, por su sha256 en el nombre) no se reescribe ni se borra.
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
    """Registra un estado generado (la demo: no hay PDF ni archivo crudo) como documento
    pendiente, con el mismo registro que un PDF importado; `content` da su sha256 (el mismo
    contenido no se registra dos veces). Quien llama lo interpreta con
    `ingest.ingest_statement`."""
    digest = hashlib.sha256(content).hexdigest()
    known = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (digest,)).fetchone()
    if known is not None:
        return Registered(known[0], new=False)
    stamp = now.isoformat(timespec="seconds")
    message_id = f"{GENERATED}-{digest[:32]}"
    path = f"{GENERATED}:{name}"
    with conn:
        document_id = _record(
            conn, GENERATED, message_id, name, name, path, digest, len(content), stamp
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
    """El mensaje (si falta) y el documento pendiente; devuelve el id del documento."""
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
    if cursor.lastrowid is None:  # pragma: no cover - sqlite siempre lo da tras un INSERT
        raise RuntimeError("no se pudo registrar el documento")
    return cursor.lastrowid


def _read_pdf(source: Path) -> bytes:
    if not source.is_file():
        raise ImportRejected(f"{source}: no existe o no es un archivo")
    if source.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise ImportRejected(f"{source}: supera el límite de {MAX_ATTACHMENT_BYTES} bytes")
    data = source.read_bytes()
    if not data.startswith(_PDF_MAGIC):
        raise ImportRejected(f"{source}: no es un PDF")
    return data


def _free_path(folder: Path, name: str, digest: str) -> Path:
    """Ruta para la copia; si el nombre ya está ocupado se antepone parte del sha256."""
    target = folder / name
    return target if not target.exists() else folder / f"{digest[:12]}_{name}"
