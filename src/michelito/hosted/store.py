"""The central accounts database: who exists and how they sign in. **Nothing financial.**

A separate SQLite file (`accounts.db` in the hosted data folder) with its own schema and forward
migrations (`MIGRATIONS`, applied in order and recorded in `PRAGMA user_version`). It holds:

- `accounts`: email, when it was created, status and the opaque name of its data folder;
- `login_codes`: one-time sign-in codes, **only their keyed hash** (and that of the optional
  desktop link), with expiry, wrong attempts and when they were used;
- `sessions`: the **hash** of each session token, created / last seen / last verified, and the
  approximate browser and system (no IP);
- `invitations`: single-use, bound to an email;
- `passkeys`: a placeholder for WebAuthn credentials (not used yet);
- `known_devices`: browsers that signed in (the hash of a random cookie, with an expiry);
- `mail_days`: how many emails went out each UTC day (the provider's daily cap);
- `data_keys`: each account's database key, **only wrapped** by the master key (`hosted.keys`),
  with the fingerprint of the master key that wrapped it. Deleting the row destroys the key;
- `deleted_folders`: tombstones of deleted accounts' data folders, until their files are gone
  (the only folders the cleanup ever removes);
- `bank_requests`: "notify me when it is supported" as one counter per bank name (from a fixed
  list): no account, no email, no date of who asked;
- `forwarding_addresses`: the **SHA-256** of each account's forwarding token (the address
  itself is shown from the account's encrypted database); replacing the row makes the old
  address stop working at once;
- `inbound_nonces`: the nonces of signed inbound-email requests, until their time window passes
  (replay protection).
- `extension_codes` and `extension_tokens`: the browser extension's one-time link code (only its
  keyed hash, with expiry) and its token (only its SHA-256), one of each per account
  (`hosted.extension`).
- `connector_clients`, `connector_requests`, `connector_codes` and `connector_grants`: the AI
  connector's OAuth clients, pending requests and codes (only their SHA-256), and each account's
  connections with only the SHA-256 of their tokens (`hosted.connector`).

`secure_delete` is on: deleted rows (a wrapped key, an email) are overwritten with zeros, and
after a deletion or a re-wrap the write-ahead log is checkpointed and truncated, so the old
bytes do not linger in free pages or in the WAL.

Times are whole seconds since the epoch. Each call opens and closes its own connection, so the
store can be used from any thread.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

FILENAME = "accounts.db"
FOLDER = re.compile(r"[0-9a-f]{32}")

MIGRATIONS: tuple[str, ...] = (
    # 1: accounts, codes, sessions, invitations and the passkey placeholder.
    """
    CREATE TABLE accounts (
        id INTEGER PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
        folder TEXT NOT NULL UNIQUE
    );
    CREATE TABLE invitations (
        id INTEGER PRIMARY KEY,
        email TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        used_at INTEGER,
        invited_by INTEGER REFERENCES accounts(id) ON DELETE SET NULL
    );
    CREATE INDEX invitations_email ON invitations(email);
    CREATE TABLE login_codes (
        id INTEGER PRIMARY KEY,
        email TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK (purpose IN ('login', 'invitation')),
        code_hash TEXT NOT NULL,
        link_hash TEXT UNIQUE,
        invitation_id INTEGER REFERENCES invitations(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        used_at INTEGER
    );
    CREATE INDEX login_codes_email ON login_codes(email);
    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL,
        last_seen_at INTEGER NOT NULL,
        verified_at INTEGER NOT NULL,
        browser TEXT NOT NULL DEFAULT '',
        os TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX sessions_account ON sessions(account_id);
    CREATE TABLE passkeys (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        credential_id BLOB NOT NULL UNIQUE,
        public_key BLOB NOT NULL,
        sign_count INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        last_used_at INTEGER
    );
    """,
    # 2: known devices (a browser that signed in; only the hash of its cookie is stored).
    """
    CREATE TABLE known_devices (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    );
    CREATE INDEX known_devices_account ON known_devices(account_id);
    """,
    # 3: emails sent per UTC day (shared by the server and `michelito invite`).
    """
    CREATE TABLE mail_days (
        day TEXT PRIMARY KEY,
        sent INTEGER NOT NULL DEFAULT 0,
        capped INTEGER NOT NULL DEFAULT 0
    );
    """,
    # 4: step-up codes, bound to the session that asked (the table is rebuilt for the CHECK).
    """
    CREATE TABLE login_codes_new (
        id INTEGER PRIMARY KEY,
        email TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK (purpose IN ('login', 'invitation', 'step_up')),
        code_hash TEXT NOT NULL,
        link_hash TEXT UNIQUE,
        invitation_id INTEGER REFERENCES invitations(id) ON DELETE CASCADE,
        session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        used_at INTEGER,
        CHECK ((purpose = 'step_up') = (session_id IS NOT NULL))
    );
    INSERT INTO login_codes_new (id, email, purpose, code_hash, link_hash, invitation_id,
        created_at, expires_at, attempts, used_at)
        SELECT id, email, purpose, code_hash, link_hash, invitation_id, created_at, expires_at,
        attempts, used_at FROM login_codes;
    DROP TABLE login_codes;
    ALTER TABLE login_codes_new RENAME TO login_codes;
    CREATE INDEX login_codes_email ON login_codes(email);
    """,
    # 5: the wrapped data key of each account's encrypted database.
    """
    CREATE TABLE data_keys (
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
        wrapped BLOB NOT NULL,
        master_id TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX data_keys_master ON data_keys(master_id);
    """,
    # 6: tombstones of deleted accounts' folders (written with the key's deletion).
    """
    CREATE TABLE deleted_folders (
        folder TEXT PRIMARY KEY,
        deleted_at INTEGER NOT NULL
    );
    """,
    # 7: requests for unsupported banks, one counter per bank (nothing about who asked).
    """
    CREATE TABLE bank_requests (
        bank TEXT PRIMARY KEY CHECK (length(bank) BETWEEN 1 AND 40),
        requests INTEGER NOT NULL DEFAULT 0
    );
    """,
    # 8: email forwarding: the hash of each account's address token, and the nonces of signed
    # inbound requests (replay protection).
    """
    CREATE TABLE forwarding_addresses (
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL
    );
    CREATE TABLE inbound_nonces (
        nonce TEXT PRIMARY KEY,
        expires_at INTEGER NOT NULL
    );
    CREATE INDEX inbound_nonces_expiry ON inbound_nonces(expires_at);
    """,
    # 9: the browser extension (`hosted.extension`): the keyed hash of each account's one-time
    # link code, and the SHA-256 of its extension token (one of each per account).
    """
    CREATE TABLE extension_codes (
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
        code_hash TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    );
    CREATE TABLE extension_tokens (
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL,
        last_used_at INTEGER
    );
    """,
    # 10: the AI connector (`hosted.connector`): the OAuth clients that registered themselves,
    # pending authorization requests and one-time codes (only their SHA-256), and each account's
    # connections with the SHA-256 of their current access and refresh tokens.
    """
    CREATE TABLE connector_clients (
        client_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        redirect_uris TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE TABLE connector_requests (
        request_hash TEXT PRIMARY KEY,
        client_id TEXT NOT NULL REFERENCES connector_clients(client_id) ON DELETE CASCADE,
        redirect_uri TEXT NOT NULL,
        state TEXT NOT NULL,
        code_challenge TEXT NOT NULL,
        scope TEXT NOT NULL,
        expires_at INTEGER NOT NULL
    );
    CREATE TABLE connector_codes (
        code_hash TEXT PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        client_id TEXT NOT NULL REFERENCES connector_clients(client_id) ON DELETE CASCADE,
        redirect_uri TEXT NOT NULL,
        code_challenge TEXT NOT NULL,
        scope TEXT NOT NULL,
        expires_at INTEGER NOT NULL
    );
    CREATE TABLE connector_grants (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        client_id TEXT NOT NULL REFERENCES connector_clients(client_id) ON DELETE CASCADE,
        client_name TEXT NOT NULL,
        scope TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        last_used_at INTEGER NOT NULL,
        access_hash TEXT NOT NULL UNIQUE,
        access_expires_at INTEGER NOT NULL,
        refresh_hash TEXT NOT NULL UNIQUE
    );
    CREATE INDEX connector_grants_account ON connector_grants(account_id);
    CREATE INDEX connector_requests_expiry ON connector_requests(expires_at);
    CREATE INDEX connector_codes_expiry ON connector_codes(expires_at);
    """,
)

# Seals a new account's data key: given the account's id, its wrapped key and master id.
Seal = Callable[[int], tuple[bytes, str]]


@dataclass(frozen=True)
class Account:
    id: int
    email: str
    created_at: int
    status: str
    folder: str


@dataclass(frozen=True)
class WrappedKey:
    """An account's data key as stored: sealed under the master key `master_id`."""

    account_id: int
    folder: str
    wrapped: bytes = field(repr=False)
    master_id: str


@dataclass(frozen=True)
class Code:
    id: int
    email: str
    purpose: str
    code_hash: str
    invitation_id: int | None
    expires_at: int


@dataclass(frozen=True)
class Session:
    id: int
    account: Account
    created_at: int
    last_seen_at: int
    verified_at: int
    browser: str
    os: str


def migrate(conn: sqlite3.Connection) -> int:
    """Apply the migrations the database does not have yet (each one atomic, with its version
    number); returns the resulting version."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for number, script in enumerate(MIGRATIONS[current:], start=current + 1):
        conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {number}; COMMIT;")
        current = number
    return current


_CODE_COLUMNS = "id, email, purpose, code_hash, invitation_id, expires_at"
_SESSION_SELECT = (
    "SELECT s.id, s.created_at, s.last_seen_at, s.verified_at, s.browser, s.os, "
    "a.id AS account_id, a.email, a.created_at AS account_created_at, a.status, a.folder "
    "FROM sessions s JOIN accounts a ON a.id = s.account_id"
)


_KEY_SELECT = (
    "SELECT k.account_id, a.folder, k.wrapped, k.master_id "
    "FROM data_keys k JOIN accounts a ON a.id = k.account_id"
)


class Store:
    """The accounts database at `path` (created and migrated on first use)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            migrate(conn)
        path.chmod(0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA secure_delete = ON")  # deleted rows are zeroed, not just freed
            yield conn

    def _flush(self) -> None:
        """Move the WAL into the database and truncate it: no old page versions stay in it."""
        with self.connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()

    def compact(self) -> None:
        """Rewrite the whole file (no free pages left) and truncate the WAL."""
        with self.connect() as conn:
            conn.execute("VACUUM")
        self._flush()

    # Accounts.

    def account_by_email(self, email: str) -> Account | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
        return _account(row) if row else None

    def create_account(
        self,
        email: str,
        folder: str,
        now: int,
        invitation_id: int | None,
        seal: Seal | None = None,
    ) -> Account:
        """A new account; the invitation it came with (if any) is used up and its codes are
        deleted in the same step, and so is its wrapped data key stored (`seal`, given the new
        id): an account never exists without its key. `LookupError` if the invitation was used
        or the account was created meanwhile."""
        if not FOLDER.fullmatch(folder):
            raise ValueError("bad folder name")
        try:
            with self.connect() as conn, conn:
                if invitation_id is not None:
                    used = conn.execute(
                        "UPDATE invitations SET used_at = ? WHERE id = ? AND used_at IS NULL",
                        (now, invitation_id),
                    )
                    if used.rowcount != 1:
                        raise LookupError("invitation already used")
                cursor = conn.execute(
                    "INSERT INTO accounts (email, created_at, folder) VALUES (?, ?, ?)",
                    (email, now, folder),
                )
                account_id = cursor.lastrowid
                if seal is not None:
                    assert account_id is not None
                    wrapped, master_id = seal(account_id)
                    conn.execute(
                        "INSERT INTO data_keys (account_id, wrapped, master_id, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (account_id, wrapped, master_id, now),
                    )
                # Invitation codes only work while there is no account.
                conn.execute(
                    "DELETE FROM login_codes WHERE email = ? AND purpose = 'invitation'",
                    (email,),
                )
        except sqlite3.IntegrityError:  # the same email, created at the same moment
            raise LookupError("account already exists") from None
        assert account_id is not None
        return Account(account_id, email, now, "active", folder)

    def delete_account(self, account_id: int, now: int) -> Account | None:
        """Destroy the account's wrapped data key and, in the same transaction, the account
        (its sessions, known devices and passkeys go with it) and the codes and invitations of
        its email, leaving a tombstone for its folder. Once this commits the data is unreadable,
        whatever happens to its files; the zeroed rows are then flushed out of the WAL.
        Returns the deleted account (None if there was none)."""
        with self.connect() as conn, conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM data_keys WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.execute("DELETE FROM login_codes WHERE email = ?", (row["email"],))
            conn.execute("DELETE FROM invitations WHERE email = ?", (row["email"],))
            conn.execute(
                "INSERT OR REPLACE INTO deleted_folders (folder, deleted_at) VALUES (?, ?)",
                (row["folder"], now),
            )
        self._flush()
        return _account(row)

    def replace_account(
        self, old_id: int, email: str, folder: str, now: int, seal: Seal
    ) -> Account:
        """In **one** transaction: delete the account `old_id` (its wrapped data key, sessions,
        codes and invitations, like `delete_account`) and create `email` anew in `folder` with
        the key `seal` gives. If anything fails nothing changes: the old account stays intact.
        `LookupError` if the old account is gone or the email is taken meanwhile."""
        if not FOLDER.fullmatch(folder):
            raise ValueError("bad folder name")
        try:
            with self.connect() as conn, conn:
                row = conn.execute("SELECT * FROM accounts WHERE id = ?", (old_id,)).fetchone()
                if row is None or row["email"] != email:
                    raise LookupError("the account to replace is gone")
                conn.execute("DELETE FROM data_keys WHERE account_id = ?", (old_id,))
                conn.execute("DELETE FROM accounts WHERE id = ?", (old_id,))
                conn.execute("DELETE FROM login_codes WHERE email = ?", (email,))
                conn.execute("DELETE FROM invitations WHERE email = ?", (email,))
                conn.execute(
                    "INSERT OR REPLACE INTO deleted_folders (folder, deleted_at) VALUES (?, ?)",
                    (row["folder"], now),
                )
                cursor = conn.execute(
                    "INSERT INTO accounts (email, created_at, folder) VALUES (?, ?, ?)",
                    (email, now, folder),
                )
                account_id = cursor.lastrowid
                assert account_id is not None
                wrapped, master_id = seal(account_id)
                conn.execute(
                    "INSERT INTO data_keys (account_id, wrapped, master_id, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (account_id, wrapped, master_id, now),
                )
        except sqlite3.IntegrityError:
            raise LookupError("account already exists") from None
        self._flush()  # the old wrapped key does not stay behind in the WAL
        return Account(account_id, email, now, "active", folder)

    def folders(self) -> set[str]:
        """The data folder of every account."""
        with self.connect() as conn:
            return {row["folder"] for row in conn.execute("SELECT folder FROM accounts")}

    def deleted_folders(self) -> list[str]:
        """The folders of deleted accounts whose files may still be on disk."""
        with self.connect() as conn:
            rows = conn.execute("SELECT folder FROM deleted_folders ORDER BY folder").fetchall()
        return [row["folder"] for row in rows]

    def forget_deleted_folder(self, folder: str) -> None:
        """The folder's files are gone: drop its tombstone."""
        with self.connect() as conn, conn:
            conn.execute("DELETE FROM deleted_folders WHERE folder = ?", (folder,))

    # Data keys.

    def data_key(self, account_id: int) -> WrappedKey | None:
        with self.connect() as conn:
            row = conn.execute(f"{_KEY_SELECT} WHERE k.account_id = ?", (account_id,)).fetchone()
        return _wrapped_key(row) if row else None

    def data_keys(self) -> list[WrappedKey]:
        with self.connect() as conn:
            rows = conn.execute(f"{_KEY_SELECT} ORDER BY k.account_id").fetchall()
        return [_wrapped_key(row) for row in rows]

    def accounts_without_key(self) -> list[Account]:
        """Accounts made before per-account encryption (development placeholders)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT a.* FROM accounts a LEFT JOIN data_keys k ON k.account_id = a.id "
                "WHERE k.account_id IS NULL ORDER BY a.id"
            ).fetchall()
        return [_account(row) for row in rows]

    def add_data_key(self, account_id: int, wrapped: bytes, master_id: str, now: int) -> bool:
        """Give a key to an account that has none; False if it already has one."""
        with self.connect() as conn, conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO data_keys (account_id, wrapped, master_id, created_at) "
                "SELECT id, ?, ?, ? FROM accounts WHERE id = ?",
                (wrapped, master_id, now, account_id),
            )
        return cursor.rowcount == 1

    def rewrap(self, account_id: int, old_master: str, wrapped: bytes, new_master: str) -> bool:
        """Replace the account's wrapped key, only if it is still under `old_master` (one
        atomic statement per account, so a rotation can stop and resume anywhere)."""
        with self.connect() as conn, conn:
            cursor = conn.execute(
                "UPDATE data_keys SET wrapped = ?, master_id = ? "
                "WHERE account_id = ? AND master_id = ?",
                (wrapped, new_master, account_id, old_master),
            )
        self._flush()  # the old wrapping does not stay behind in the WAL
        return cursor.rowcount == 1

    # Invitations.

    def create_invitation(
        self, email: str, now: int, expires_at: int, invited_by: int | None = None
    ) -> int:
        with self.connect() as conn, conn:
            cursor = conn.execute(
                "INSERT INTO invitations (email, created_at, expires_at, invited_by) "
                "VALUES (?, ?, ?, ?)",
                (email, now, expires_at, invited_by),
            )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def open_invitation(self, email: str, now: int) -> int | None:
        """The id of an unused, unexpired invitation for that email."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM invitations WHERE email = ? AND used_at IS NULL "
                "AND expires_at > ? ORDER BY id DESC LIMIT 1",
                (email, now),
            ).fetchone()
        return int(row["id"]) if row else None

    # Codes.

    def add_code(
        self,
        email: str,
        purpose: str,
        code_hash: str,
        link_hash: str | None,
        now: int,
        expires_at: int,
        invitation_id: int | None = None,
        session_id: int | None = None,
    ) -> None:
        """A new code for the email. The older unused ones **of the same purpose** (and, for a
        step-up, of the same session) stop working; others are left alone, so asking for a
        sign-in code never cancels an invitation or someone's step-up."""
        with self.connect() as conn, conn:
            conn.execute(
                "UPDATE login_codes SET used_at = ? WHERE email = ? AND purpose = ? "
                "AND session_id IS ? AND used_at IS NULL",
                (now, email, purpose, session_id),
            )
            conn.execute(
                "INSERT INTO login_codes (email, purpose, code_hash, link_hash, invitation_id, "
                "session_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (email, purpose, code_hash, link_hash, invitation_id, session_id, now, expires_at),
            )

    def reserve_attempt(
        self,
        email: str,
        now: int,
        max_attempts: int,
        purposes: tuple[str, ...],
        session_id: int | None = None,
    ) -> Code | None:
        """Count one attempt on the newest live code of the email among `purposes` (and of
        that session: None for sign-in codes, the session's id for a step-up) **before** it is
        compared, in a single statement, and return it; None when there is none or it already
        had `max_attempts` (then nobody compares against it, however many requests arrive at
        once)."""
        marks = ",".join("?" * len(purposes))
        with self.connect() as conn, conn:
            row = conn.execute(
                "UPDATE login_codes SET attempts = attempts + 1 WHERE id = ("
                f"  SELECT id FROM login_codes WHERE email = ? AND purpose IN ({marks})"
                "  AND session_id IS ? AND used_at IS NULL AND expires_at > ?"
                "  ORDER BY id DESC LIMIT 1"
                f") AND attempts < ? RETURNING {_CODE_COLUMNS}",
                (email, *purposes, session_id, now, max_attempts),
            ).fetchone()
        return Code(**dict(row)) if row else None

    def code_by_link(self, link_hash: str, now: int) -> Code | None:
        """The unused, unexpired code of that link (wrong attempts at the code do not matter:
        the link's token cannot be guessed)."""
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT {_CODE_COLUMNS} FROM login_codes WHERE link_hash = ? "
                "AND used_at IS NULL AND expires_at > ?",
                (link_hash, now),
            ).fetchone()
        return Code(**dict(row)) if row else None

    def newest_code_at(
        self, email: str, now: int, purposes: tuple[str, ...], session_id: int | None = None
    ) -> int | None:
        """When the newest unused, unexpired code of that email (among `purposes`, of that
        session) was created."""
        marks = ",".join("?" * len(purposes))
        with self.connect() as conn:
            row = conn.execute(
                "SELECT max(created_at) FROM login_codes WHERE email = ? "
                f"AND purpose IN ({marks}) AND session_id IS ? AND used_at IS NULL "
                "AND expires_at > ?",
                (email, *purposes, session_id, now),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def use_code(self, code_id: int, now: int) -> bool:
        """Mark the code used; False if someone else used it first (single use)."""
        with self.connect() as conn, conn:
            cursor = conn.execute(
                "UPDATE login_codes SET used_at = ? WHERE id = ? AND used_at IS NULL",
                (now, code_id),
            )
        return cursor.rowcount == 1

    def prune_codes(self, now: int) -> None:
        """Forget codes that can no longer be used (expired or used more than a day ago)."""
        day_ago = now - 86400
        with self.connect() as conn, conn:
            conn.execute(
                "DELETE FROM login_codes WHERE expires_at <= ? OR used_at <= ?",
                (day_ago, day_ago),
            )
            conn.execute("DELETE FROM known_devices WHERE expires_at <= ?", (now,))

    # Mail.

    def take_mail(self, day: str, limit: int) -> bool:
        """Count one email for that UTC day if the day is under `limit` and not capped."""
        with self.connect() as conn, conn:
            conn.execute("INSERT OR IGNORE INTO mail_days (day) VALUES (?)", (day,))
            cursor = conn.execute(
                "UPDATE mail_days SET sent = sent + 1 WHERE day = ? AND sent < ? AND capped = 0",
                (day, limit),
            )
        return cursor.rowcount == 1

    def mail_available(self, day: str, limit: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT sent, capped FROM mail_days WHERE day = ?", (day,)
            ).fetchone()
        return row is None or (row["sent"] < limit and not row["capped"])

    def cap_mail(self, day: str) -> None:
        """The provider said its daily quota is used up."""
        with self.connect() as conn, conn:
            conn.execute(
                "INSERT INTO mail_days (day, capped) VALUES (?, 1) "
                "ON CONFLICT(day) DO UPDATE SET capped = 1",
                (day,),
            )

    # Unsupported banks.

    def count_bank_request(self, bank: str) -> None:
        with self.connect() as conn, conn:
            conn.execute(
                "INSERT INTO bank_requests (bank, requests) VALUES (?, 1) "
                "ON CONFLICT(bank) DO UPDATE SET requests = requests + 1",
                (bank,),
            )

    def bank_requests(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT bank, requests FROM bank_requests ORDER BY bank")
            return {str(row["bank"]): int(row["requests"]) for row in rows}

    # Email forwarding.

    def set_forwarding(self, account_id: int, token_hash: str, now: int) -> None:
        """The account's forwarding token is now this one (hash only): an older one, if any, is
        replaced in the same statement, so it stops working at once."""
        with self.connect() as conn, conn:
            conn.execute(
                "INSERT INTO forwarding_addresses (account_id, token_hash, created_at) "
                "VALUES (?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET "
                "token_hash = excluded.token_hash, created_at = excluded.created_at",
                (account_id, token_hash, now),
            )
        self._flush()  # the old hash does not linger in the WAL

    def forwarding_hash(self, account_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT token_hash FROM forwarding_addresses WHERE account_id = ?", (account_id,)
            ).fetchone()
        return str(row["token_hash"]) if row else None

    def account_by_forwarding(self, token_hash: str) -> Account | None:
        """The active account whose forwarding token has this hash."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT a.* FROM forwarding_addresses f JOIN accounts a ON a.id = f.account_id "
                "WHERE f.token_hash = ? AND a.status = 'active'",
                (token_hash,),
            ).fetchone()
        return _account(row) if row else None

    def forwarding_accounts(self) -> list[Account]:
        """Every active account with a forwarding address (the daily notices walk them)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT a.* FROM forwarding_addresses f JOIN accounts a ON a.id = f.account_id "
                "WHERE a.status = 'active' ORDER BY a.id"
            ).fetchall()
        return [_account(row) for row in rows]

    def active_accounts(self) -> list[Account]:
        """Every active account (the hourly read of connected mailboxes walks them)."""
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM accounts WHERE status = 'active' ORDER BY id")
            found = rows.fetchall()
        return [_account(row) for row in found]

    def take_nonce(self, nonce: str, now: int, expires_at: int) -> bool:
        """Record a signed request's nonce; False if it was already seen (a replay). Nonces
        whose window has passed are forgotten first."""
        with self.connect() as conn, conn:
            conn.execute("DELETE FROM inbound_nonces WHERE expires_at <= ?", (now,))
            cursor = conn.execute(
                "INSERT OR IGNORE INTO inbound_nonces (nonce, expires_at) VALUES (?, ?)",
                (nonce, expires_at),
            )
        return cursor.rowcount == 1

    # Sessions.

    def add_session(self, account_id: int, token_hash: str, now: int, browser: str, os: str) -> int:
        with self.connect() as conn, conn:
            cursor = conn.execute(
                "INSERT INTO sessions (account_id, token_hash, created_at, last_seen_at, "
                "verified_at, browser, os) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (account_id, token_hash, now, now, now, browser, os),
            )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def session_by_token(self, token_hash: str) -> Session | None:
        with self.connect() as conn:
            row = conn.execute(
                f"{_SESSION_SELECT} WHERE s.token_hash = ?", (token_hash,)
            ).fetchone()
        return _session(row) if row else None

    def sessions_of(self, account_id: int) -> list[Session]:
        with self.connect() as conn:
            rows = conn.execute(
                f"{_SESSION_SELECT} WHERE s.account_id = ? ORDER BY s.last_seen_at DESC, s.id DESC",
                (account_id,),
            ).fetchall()
        return [_session(row) for row in rows]

    def touch_session(self, session_id: int, now: int) -> None:
        with self.connect() as conn, conn:
            conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now, session_id))

    def mark_verified(self, session_id: int, now: int) -> None:
        with self.connect() as conn, conn:
            conn.execute("UPDATE sessions SET verified_at = ? WHERE id = ?", (now, session_id))

    def delete_session(self, session_id: int) -> None:
        with self.connect() as conn, conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # Known devices.

    def add_known_device(self, account_id: int, token_hash: str, now: int, expires_at: int) -> None:
        with self.connect() as conn, conn:
            conn.execute(
                "INSERT INTO known_devices (account_id, token_hash, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (account_id, token_hash, now, expires_at),
            )

    def known_device(self, token_hash: str, now: int) -> Account | None:
        """The account of that unexpired known device."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT a.* FROM known_devices d JOIN accounts a ON a.id = d.account_id "
                "WHERE d.token_hash = ? AND d.expires_at > ?",
                (token_hash, now),
            ).fetchone()
        return _account(row) if row else None

    def delete_known_devices_of(self, account_id: int) -> None:
        with self.connect() as conn, conn:
            conn.execute("DELETE FROM known_devices WHERE account_id = ?", (account_id,))

    def delete_sessions_of(self, account_id: int) -> int:
        """Every session of the account, and its known devices, browser-extension link and AI
        connections with them (signing out everywhere also cuts a token copied from a lost
        computer)."""
        with self.connect() as conn, conn:
            cursor = conn.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM known_devices WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM extension_tokens WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM extension_codes WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM connector_grants WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM connector_codes WHERE account_id = ?", (account_id,))
        return cursor.rowcount


def _account(row: sqlite3.Row) -> Account:
    return Account(row["id"], row["email"], row["created_at"], row["status"], row["folder"])


def _session(row: sqlite3.Row) -> Session:
    account = Account(
        row["account_id"], row["email"], row["account_created_at"], row["status"], row["folder"]
    )
    return Session(
        row["id"],
        account,
        row["created_at"],
        row["last_seen_at"],
        row["verified_at"],
        row["browser"],
        row["os"],
    )


def _wrapped_key(row: sqlite3.Row) -> WrappedKey:
    return WrappedKey(row["account_id"], row["folder"], bytes(row["wrapped"]), row["master_id"])
