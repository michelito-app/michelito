"""Incremental download of emails and attachments from Gmail into the raw archive.

Each message is processed only once (its ID stays in `gmail_messages`), so running it several
times duplicates nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from michelito.alerts.common import AlertEmail
from michelito.analysis import live_match, live_store, receipt_match, receipt_store
from michelito.config import Source
from michelito.gmail import AttachmentRef, MailMessage
from michelito.i18n import t

_LOG = logging.getLogger(__name__)
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MESSAGE_ID = re.compile(r"[0-9A-Za-z_-]{1,64}")
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_RETRIES = 20  # failed alerts downloaded again in one sync
# The name of an attachment whose name has nothing usable (kept from the pre-rename release, so
# files already in raw/ keep matching).
_FALLBACK_NAME = "adjunto"  # spanish-data


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
    return cleaned or _FALLBACK_NAME


def unique_names(attachments: list[AttachmentRef]) -> list[str]:
    """Safe names, distinct within the same message."""
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
    """Write the file readable only by the user (0600), without following links."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def extract_source(
    conn: sqlite3.Connection, client: MailClient, source: Source, raw_root: Path
) -> ExtractStats:
    if source.alerts:
        return extract_alerts(conn, client, source)
    if source.receipts:
        return extract_receipts(conn, client, source)
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
        raise ValueError(f"unexpected message ID: {message.message_id!r}")
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
        reason = t("core.extract.too_large", megabytes=megabytes)
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
        return "duplicate", t("core.extract.same_file")
    if path.suffix.lower() == ".pdf":
        return "pending", None
    return "archived", t("core.extract.no_parser_format")


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


def extract_alerts(conn: sqlite3.Connection, client: MailClient, source: Source) -> ExtractStats:
    """Bank alerts (`michelito.alerts`): each message is parsed in memory and only its fields are
    stored (`live_store.record`); nothing is written to raw/. A message already stored is not
    downloaded again; a failed one only if it may succeed now (`live_store.known_message_ids`),
    at most MAX_RETRIES per sync. At the end, the alerts are reconciled with the cards and
    statements (`live_match.reconcile`)."""
    known = live_store.known_message_ids(conn)
    failed = {str(r[0]) for r in conn.execute("SELECT message_id FROM alerts")} - known
    new_messages = retries = 0
    for message_id in client.list_message_ids(source.query):
        if message_id in known:
            continue
        if message_id in failed:
            if retries >= MAX_RETRIES:
                continue
            retries += 1
        if not _MESSAGE_ID.fullmatch(message_id):
            raise ValueError(f"unexpected message ID: {message_id!r}")
        try:
            message = client.get_message(message_id)
            with conn:
                live_store.record(conn, alert_email(message), source.name, _now())
        except Exception as exc:  # noqa: BLE001 - one bad message must not stop the sync
            with conn:
                live_store.record_error(conn, message_id, source.name, type(exc).__name__, _now())
        known.add(message_id)
        new_messages += 1
    with conn:
        live_match.reconcile(conn, _now())
    _match_receipts(conn)  # a new provisional may be a receipt's
    return ExtractStats(source.name, new_messages, 0, 0)


def _match_receipts(conn: sqlite3.Connection) -> None:
    """Match the stored receipts in a transaction of their own: whatever goes wrong with them
    must never undo or stop what the bank's mail brought. The next sync does the same work."""
    try:
        with conn:
            receipt_match.reconcile_stored(conn, _now())
    except Exception as exc:  # noqa: BLE001 - receipts are an extra
        _LOG.warning("matching merchant receipts failed (%s)", type(exc).__name__)


def extract_receipts(conn: sqlite3.Connection, client: MailClient, source: Source) -> ExtractStats:
    """A merchant's receipts (`michelito.receipts`): each message is read in memory and only its
    fields are stored (`receipt_store.record`); nothing is written to raw/. A message already
    stored is not downloaded again; a failed one only if it may succeed now
    (`receipt_store.known_message_ids`), at most MAX_RETRIES per sync. At the end, the receipts
    are matched to the transactions (`receipt_match.reconcile_stored`)."""
    known = receipt_store.known_message_ids(conn)
    failed = {str(r[0]) for r in conn.execute("SELECT message_id FROM receipt_emails")} - known
    new_messages = retries = 0
    for message_id in client.list_message_ids(source.query):
        if message_id in known:
            continue
        if message_id in failed:
            if retries >= MAX_RETRIES:
                continue
            retries += 1
        if not _MESSAGE_ID.fullmatch(message_id):
            raise ValueError(f"unexpected message ID: {message_id!r}")
        try:
            message = client.get_message(message_id)
            with conn:
                receipt_store.record(conn, alert_email(message), source.name, _now())
        except Exception as exc:  # noqa: BLE001 - one bad message must not stop the sync
            with conn:
                receipt_store.record_error(
                    conn, message_id, source.name, type(exc).__name__, _now()
                )
        known.add(message_id)
        new_messages += 1
    _match_receipts(conn)
    return ExtractStats(source.name, new_messages, 0, 0)


def alert_email(message: MailMessage) -> AlertEmail:
    return AlertEmail(
        message_id=message.message_id,
        sender=message.sender,
        subject=message.subject,
        received_at=message.received_at,
        html=message.body_html,
        text=message.body_text,
        auth_results=message.auth_results,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
