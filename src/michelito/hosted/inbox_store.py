"""The forwarding inbox inside each account's **encrypted** database (hosted mode only).

The tables are created on first use (`ensure`), so local and demo databases never get them:

- `forwarding_address`: the account's current forwarding token (one row), to show the address;
  the accounts database only has its hash (`store.forwarding_addresses`);
- `inbox_messages`: the hash of every forwarded Message-ID already handled (idempotency);
- `inbox_waiting`: statement PDFs waiting to be read: `queued` (just arrived) or `password`
  (locked, no stored password or a wrong one), with the bank they came from;
- `inbox_quarantine`: messages from an unknown sender or that did not authenticate: only the
  sender's domain, the date and the attachment count are readable; the message itself is
  sealed and never opened until the person approves it;
- `inbox_confirmations`: Gmail's forwarding confirmation code and link, to show them;
- `inbox_passwords`: a bank's PDF password, only if the person chose to store it;
- `inbox_events`: what arrived and how it ended (kind, bank, outcome; no amounts, no names);
- `inbox_notices`: which problem emails went out (one per kind and key), so none repeats.

**Sealing.** Every PDF, message and password is stored as AES-256-GCM ciphertext under a key
derived from the account's data key (HKDF, `SEAL_INFO`), with its table and a random row uid as
associated data, *inside* the SQLCipher-encrypted database: two layers, the same key at the
root, so deleting the account (crypto-shredding) makes both unreadable at once. A sealed blob
copied to another row or another account does not open. Deleted rows are zeroed
(`secure_delete`).
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from michelito.analysis import spending

SEAL_INFO = b"michelito inbox seal v1"
SEAL_VERSION = b"\x01"
NONCE_BYTES = 12
QUARANTINE_DAYS = 30
WAITING_DAYS = 90
EVENTS_KEPT = 200
MAX_WAITING = 40
MAX_QUARANTINE = 40

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS forwarding_address (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    token TEXT NOT NULL,
    created_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS inbox_messages (
    message_key TEXT PRIMARY KEY,
    received_at TEXT NOT NULL,
    route TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS inbox_waiting (
    id INTEGER PRIMARY KEY,
    uid TEXT NOT NULL UNIQUE,
    bank TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'password', 'approval')),
    reason TEXT NOT NULL DEFAULT ''
        CHECK (reason IN ('', 'missing', 'wrong', 'new_account')),
    approved INTEGER NOT NULL DEFAULT 0,
    sender_domain TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    sealed BLOB NOT NULL,
    pages BLOB,
    created_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS inbox_quarantine (
    id INTEGER PRIMARY KEY,
    uid TEXT NOT NULL UNIQUE,
    sender_domain TEXT NOT NULL,
    received_at TEXT NOT NULL,
    attachments INTEGER NOT NULL,
    reason TEXT NOT NULL
        CHECK (reason IN ('unknown_sender', 'unauthenticated', 'unknown_card')),
    claims_bank INTEGER NOT NULL DEFAULT 0,
    seen_key TEXT NOT NULL,
    sealed BLOB NOT NULL,
    created_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS inbox_confirmations (
    id INTEGER PRIMARY KEY,
    code TEXT,
    link TEXT,
    requester TEXT,
    received_at TEXT NOT NULL
)""",
    # What entered by the person's approval (a statement's document or an alert), so it is
    # marked as such and can be taken back.
    """CREATE TABLE IF NOT EXISTS inbox_approvals (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('statement', 'alert')),
    ref TEXT NOT NULL,
    sender_domain TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    UNIQUE (kind, ref)
)""",
    """CREATE TABLE IF NOT EXISTS inbox_passwords (
    bank TEXT PRIMARY KEY,
    uid TEXT NOT NULL UNIQUE,
    sealed BLOB NOT NULL,
    stored_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS inbox_events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    bank TEXT,
    outcome TEXT NOT NULL,
    month TEXT,
    identifier TEXT,
    account_kind TEXT
)""",
    """CREATE TABLE IF NOT EXISTS inbox_notices (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (kind, key)
)""",
)


class SealError(Exception):
    """A sealed blob did not open (another key, another row, altered)."""


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA secure_delete = ON")
    for statement in SCHEMA:
        conn.execute(statement)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Sealer:
    """Seals and opens the inbox's blobs with a key derived from the account's data key."""

    key: bytes = field(repr=False)

    @classmethod
    def of(cls, data_key: bytes) -> Sealer:
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=SEAL_INFO)
        return cls(derived.derive(data_key))

    def seal(self, table: str, uid: str, content: bytes) -> bytes:
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = AESGCM(self.key).encrypt(nonce, content, f"{table}/{uid}".encode())
        return SEAL_VERSION + nonce + sealed

    def open(self, table: str, uid: str, sealed: bytes) -> bytes:
        if sealed[:1] != SEAL_VERSION or len(sealed) < 1 + NONCE_BYTES:
            raise SealError("unknown seal format")
        nonce, body = sealed[1 : 1 + NONCE_BYTES], sealed[1 + NONCE_BYTES :]
        try:
            return AESGCM(self.key).decrypt(nonce, body, f"{table}/{uid}".encode())
        except InvalidTag:
            raise SealError("the sealed item did not open") from None


def _uid() -> str:
    return secrets.token_hex(16)


# The address.


def token(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT token FROM forwarding_address WHERE id = 1").fetchone()
    return str(row[0]) if row else None


def set_token(conn: sqlite3.Connection, value: str) -> None:
    conn.execute(
        "INSERT INTO forwarding_address (id, token, created_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET token = excluded.token, created_at = excluded.created_at",
        (value, _now()),
    )


# Idempotency.


def seen(conn: sqlite3.Connection, message_key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM inbox_messages WHERE message_key = ?", (message_key,)
    ).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, message_key: str, route: str) -> bool:
    """False if another request recorded it first."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO inbox_messages (message_key, received_at, route) VALUES (?, ?, ?)",
        (message_key, _now(), route),
    )
    return cursor.rowcount == 1


# Waiting statements.


@dataclass(frozen=True)
class Waiting:
    id: int
    uid: str
    bank: str
    state: str  # queued, password (locked) or approval (an account not known yet)
    reason: str
    received_at: str
    sealed: bytes = field(repr=False)
    approved: bool = False  # the person approved it (an unknown account, a quarantined email)
    sender_domain: str = ""
    # Held for approval: the pages already read (sealed), so a password typed before is not
    # needed again.
    pages: bytes | None = field(default=None, repr=False)


def add_waiting(
    conn: sqlite3.Connection,
    sealer: Sealer,
    bank: str,
    received: datetime,
    pdf: bytes,
    approved: bool = False,
    sender_domain: str = "",
) -> bool:
    """Queue a PDF to be read; False (nothing stored) when the queue is full."""
    count = conn.execute("SELECT COUNT(*) FROM inbox_waiting").fetchone()[0]
    if count >= MAX_WAITING:
        return False
    uid = _uid()
    conn.execute(
        "INSERT INTO inbox_waiting (uid, bank, state, approved, sender_domain, received_at, "
        "sealed, created_at) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)",
        (
            uid,
            bank,
            int(approved),
            sender_domain[:253],
            received.isoformat(timespec="seconds"),
            sealer.seal("waiting", uid, pdf),
            _now(),
        ),
    )
    return True


_WAITING = (
    "SELECT id, uid, bank, state, reason, received_at, sealed, approved, sender_domain, pages "
    "FROM inbox_waiting"
)


def waiting(
    conn: sqlite3.Connection,
    state: str | None = None,
    bank: str | None = None,
    item_id: int | None = None,
) -> list[Waiting]:
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (("state", state), ("bank", bank), ("id", item_id)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    query = _WAITING + (" WHERE " + " AND ".join(clauses) if clauses else "")
    rows = conn.execute(f"{query} ORDER BY id", params).fetchall()
    return [
        Waiting(
            r[0],
            r[1],
            r[2],
            r[3],
            r[4],
            r[5],
            bytes(r[6]),
            bool(r[7]),
            r[8],
            None if r[9] is None else bytes(r[9]),
        )
        for r in rows
    ]


def lock_waiting(conn: sqlite3.Connection, item_id: int, reason: str) -> None:
    conn.execute(
        "UPDATE inbox_waiting SET state = 'password', reason = ? WHERE id = ?", (reason, item_id)
    )


def hold_waiting(conn: sqlite3.Connection, sealer: Sealer, item: Waiting, pages: bytes) -> None:
    """A statement of an account the person does not have yet: it waits for their approval,
    with the pages already read (sealed), so a typed password is not asked again."""
    conn.execute(
        "UPDATE inbox_waiting SET state = 'approval', reason = 'new_account', pages = ? "
        "WHERE id = ?",
        (sealer.seal("pages", item.uid, pages), item.id),
    )


def held_pages(sealer: Sealer, item: Waiting) -> bytes | None:
    return None if item.pages is None else sealer.open("pages", item.uid, item.pages)


def approve_waiting(conn: sqlite3.Connection, item_id: int) -> bool:
    """The person approved a held statement: it is read again, and stored even if new."""
    cursor = conn.execute(
        "UPDATE inbox_waiting SET state = 'queued', reason = '', approved = 1 "
        "WHERE id = ? AND state = 'approval'",
        (item_id,),
    )
    return cursor.rowcount == 1


def drop_waiting(conn: sqlite3.Connection, item_id: int) -> bool:
    return conn.execute("DELETE FROM inbox_waiting WHERE id = ?", (item_id,)).rowcount == 1


# Quarantine.


@dataclass(frozen=True)
class Quarantined:
    id: int
    uid: str
    sender_domain: str
    received_at: str
    attachments: int
    reason: str
    sealed: bytes = field(repr=False)
    claims_bank: bool = False  # the From address is one of the banks' senders
    seen_key: str = field(default="", repr=False)


def add_quarantine(
    conn: sqlite3.Connection,
    sealer: Sealer,
    sender_domain: str,
    received: datetime,
    attachments: int,
    reason: str,
    raw: bytes,
    claims_bank: bool = False,
    seen_key: str = "",
) -> bool:
    count = conn.execute("SELECT COUNT(*) FROM inbox_quarantine").fetchone()[0]
    if count >= MAX_QUARANTINE:
        return False
    uid = _uid()
    conn.execute(
        "INSERT INTO inbox_quarantine (uid, sender_domain, received_at, attachments, reason, "
        "claims_bank, seen_key, sealed, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            uid,
            sender_domain[:253],
            received.isoformat(timespec="seconds"),
            attachments,
            reason,
            int(claims_bank),
            seen_key,
            sealer.seal("quarantine", uid, raw),
            _now(),
        ),
    )
    return True


def quarantined(conn: sqlite3.Connection, item_id: int | None = None) -> list[Quarantined]:
    query = (
        "SELECT id, uid, sender_domain, received_at, attachments, reason, sealed, claims_bank, "
        "seen_key FROM inbox_quarantine"
    )
    rows = (
        conn.execute(f"{query} WHERE id = ?", (item_id,)).fetchall()
        if item_id is not None
        else conn.execute(f"{query} ORDER BY id DESC").fetchall()
    )
    return [
        Quarantined(r[0], r[1], r[2], r[3], r[4], r[5], bytes(r[6]), bool(r[7]), r[8]) for r in rows
    ]


def drop_quarantine(conn: sqlite3.Connection, item_id: int, forget: bool = True) -> bool:
    """Delete the item and, with `forget`, its idempotency key (the same message may then be
    received again)."""
    row = conn.execute("SELECT seen_key FROM inbox_quarantine WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return False
    conn.execute("DELETE FROM inbox_quarantine WHERE id = ?", (item_id,))
    if forget and row[0]:
        conn.execute("DELETE FROM inbox_messages WHERE message_key = ?", (row[0],))
    return True


# Gmail's confirmation.


@dataclass(frozen=True)
class ConfirmationRow:
    id: int
    code: str | None
    link: str | None
    received_at: str
    requester: str | None = None


def add_confirmation(
    conn: sqlite3.Connection,
    code: str | None,
    link: str | None,
    received: datetime,
    requester: str | None = None,
) -> None:
    conn.execute("DELETE FROM inbox_confirmations")  # only the newest one is useful
    conn.execute(
        "INSERT INTO inbox_confirmations (code, link, requester, received_at) VALUES (?, ?, ?, ?)",
        (code, link, requester, received.isoformat(timespec="seconds")),
    )


def confirmation(conn: sqlite3.Connection) -> ConfirmationRow | None:
    row = conn.execute(
        "SELECT id, code, link, received_at, requester FROM inbox_confirmations "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return ConfirmationRow(row[0], row[1], row[2], row[3], row[4]) if row else None


def drop_confirmation(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM inbox_confirmations")


# What entered by approval.


@dataclass(frozen=True)
class Approval:
    id: int
    kind: str  # statement (ref: the document's sha256) or alert (ref: its message id)
    ref: str
    sender_domain: str
    approved_at: str


def add_approval(conn: sqlite3.Connection, kind: str, ref: str, sender_domain: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO inbox_approvals (kind, ref, sender_domain, approved_at) "
        "VALUES (?, ?, ?, ?)",
        (kind, ref, sender_domain[:253], _now()),
    )


def approvals(conn: sqlite3.Connection, item_id: int | None = None) -> list[Approval]:
    query = "SELECT id, kind, ref, sender_domain, approved_at FROM inbox_approvals"
    rows = (
        conn.execute(f"{query} WHERE id = ?", (item_id,)).fetchall()
        if item_id is not None
        else conn.execute(f"{query} ORDER BY id DESC").fetchall()
    )
    return [Approval(*row) for row in rows]


def drop_approval(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM inbox_approvals WHERE id = ?", (item_id,))


def approved_fingerprints(conn: sqlite3.Connection) -> frozenset[str]:
    """The fingerprints of every movement that entered by approval (none outside hosted mode:
    the table only exists once forwarding was used)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inbox_approvals'"
    ).fetchone()
    if exists is None:
        return frozenset()
    statements = conn.execute(
        "SELECT s.id FROM inbox_approvals p JOIN documents d ON d.sha256 = p.ref "
        "JOIN statements s ON s.document_id = d.id WHERE p.kind = 'statement'"
    ).fetchall()
    found = set(spending.statement_fingerprints(conn, {int(row[0]) for row in statements}))
    alerts = conn.execute(
        "SELECT a.id FROM inbox_approvals p JOIN alerts a ON a.message_id = p.ref "
        "WHERE p.kind = 'alert'"
    ).fetchall()
    found |= {f"alert-{row[0]}" for row in alerts}
    return frozenset(found)


# Stored PDF passwords.


def store_password(conn: sqlite3.Connection, sealer: Sealer, bank: str, password: str) -> None:
    uid = _uid()
    conn.execute(
        "INSERT INTO inbox_passwords (bank, uid, sealed, stored_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(bank) DO UPDATE SET uid = excluded.uid, sealed = excluded.sealed, "
        "stored_at = excluded.stored_at",
        (bank, uid, sealer.seal("password", f"{bank}/{uid}", password.encode("utf-8")), _now()),
    )


def password(conn: sqlite3.Connection, sealer: Sealer, bank: str) -> str | None:
    row = conn.execute("SELECT uid, sealed FROM inbox_passwords WHERE bank = ?", (bank,)).fetchone()
    if row is None:
        return None
    return sealer.open("password", f"{bank}/{row[0]}", bytes(row[1])).decode("utf-8")


def stored_banks(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(str(r[0]) for r in conn.execute("SELECT bank FROM inbox_passwords"))


def forget_password(conn: sqlite3.Connection, bank: str) -> bool:
    return conn.execute("DELETE FROM inbox_passwords WHERE bank = ?", (bank,)).rowcount == 1


# Events and notices.


@dataclass(frozen=True)
class Event:
    at: str
    kind: str
    bank: str | None
    outcome: str
    month: str | None
    identifier: str | None
    account_kind: str | None = None


def add_event(
    conn: sqlite3.Connection,
    kind: str,
    outcome: str,
    bank: str | None = None,
    month: str | None = None,
    identifier: str | None = None,
    account_kind: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO inbox_events (at, kind, bank, outcome, month, identifier, account_kind) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (_now(), kind, bank, outcome, month, identifier, account_kind),
    )
    conn.execute(
        "DELETE FROM inbox_events WHERE id NOT IN "
        "(SELECT id FROM inbox_events ORDER BY id DESC LIMIT ?)",
        (EVENTS_KEPT,),
    )


def events(conn: sqlite3.Connection, limit: int = 20) -> list[Event]:
    rows = conn.execute(
        "SELECT at, kind, bank, outcome, month, identifier, account_kind FROM inbox_events "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [Event(*row) for row in rows]


def has_arrivals(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT EXISTS (SELECT 1 FROM inbox_messages)").fetchone()
    return bool(row[0])


def take_notice(conn: sqlite3.Connection, kind: str, key: str) -> bool:
    """Record that this notice goes out now; False if it already did."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO inbox_notices (kind, key, sent_at) VALUES (?, ?, ?)",
        (kind, key, _now()),
    )
    return cursor.rowcount == 1


def prune(conn: sqlite3.Connection, today: date) -> None:
    """Forget quarantined messages and waiting statements past their time, and old notices."""
    quarantine_before = (today - timedelta(days=QUARANTINE_DAYS)).isoformat()
    waiting_before = (today - timedelta(days=WAITING_DAYS)).isoformat()
    conn.execute("DELETE FROM inbox_quarantine WHERE created_at < ?", (quarantine_before,))
    conn.execute(
        "DELETE FROM inbox_waiting WHERE state IN ('password', 'approval') AND created_at < ?",
        (waiting_before,),
    )
    conn.execute("DELETE FROM inbox_notices WHERE sent_at < ?", (waiting_before,))
