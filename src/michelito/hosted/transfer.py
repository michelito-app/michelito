"""Moving the owner's local database into a hosted account (`lanzamiento.md`, "The owner's data").

- `export_account` (on the owner's machine) writes a **consistent snapshot** of the local
  database with SQLite's backup API (never a copy of a file that may be mid-write), plus a small
  `michelito_export` table: the format, the schema version, when, the holders file and the row
  count and digest of every table (to detect a file damaged on the way). Neither the PDF password
  nor the Gmail token is in the database (they live in the keyring): the export checks that no
  keyring secret and no secret-looking table or column ended up in it anyway. Mode `0600`.
- `import_account` (on the server) checks the file, encrypts it with a new data key
  (`encrypted.encrypt_copy`), runs the forward migrations on the encrypted copy, proves it equal
  to the source (`PRAGMA integrity_check`, SQLCipher's page check, and every table's row count
  and content digest against the source migrated in memory), and only then creates the account
  with its wrapped key and **removes the plaintext file** (`secure_delete`).

Nothing here logs or prints a value from the database.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import time
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from michelito import config, db, encrypted, holders
from michelito.hosted import auth, keys
from michelito.hosted.keys import MasterKey
from michelito.hosted.store import Account, Store

FORMAT = 1
MANIFEST = "michelito_export"
IMPORTING = ".importing"
# Table or column names that would mean a credential was stored in the database.
SECRET_NAMES = re.compile(r"password|passwd|token|secret|credential|api_?key", re.IGNORECASE)
# Shorter keyring values are not searched for in the file (they would match by chance).
MIN_SECRET = 6
# Columns that hold text printed by the bank (a description can quote the holder's ID number, which
# is often also the PDF password). A secret found only there is the bank's data, not a leak.
BANK_TEXT = frozenset(
    {"transactions.description", "transactions.raw_line", "transactions.reference"}
)
_CHUNK = 1 << 20


class TransferError(Exception):
    """The export or the import cannot go on (the message names no data)."""


@dataclass(frozen=True)
class TableDigest:
    rows: int
    sha256: str


@dataclass(frozen=True)
class Exported:
    path: Path
    schema_version: int
    tables: int
    size: int


@dataclass(frozen=True)
class Imported:
    account: Account
    replaced: bool
    schema_from: int
    schema_to: int
    tables: int
    removed: SecureDelete


@dataclass(frozen=True)
class SecureDelete:
    removed: tuple[str, ...]  # the file names that were overwritten and unlinked
    note: str  # what overwriting can and cannot promise


# Digests.


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name"
    )
    return [str(row[0]) for row in rows if row[0] != MANIFEST]


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def digest(conn: sqlite3.Connection, stamped: str | None = None) -> dict[str, TableDigest]:
    """Every table's row count and a digest of its content (rows in a fixed order).

    `stamped`: a "YYYY-MM-DDT" prefix; text values starting with it count as equal. A migration
    may stamp rows with the current time, so two runs of it differ by microseconds."""
    found: dict[str, TableDigest] = {}
    for table in _tables(conn):

        def same(value: object) -> object:
            if stamped and isinstance(value, str) and value.startswith(stamped):
                return "<now>"
            return value

        rows = sorted(
            repr(tuple(map(same, row))) for row in conn.execute(f"SELECT * FROM {_quoted(table)}")
        )
        hasher = hashlib.sha256()
        for row in rows:
            hasher.update(row.encode())
            hasher.update(b"\n")
        found[table] = TableDigest(len(rows), hasher.hexdigest())
    return found


def _stamp(version: int) -> str | None:
    """Today's prefix when the forward migrations run (see `digest`), else None."""
    if version >= db.SCHEMA_VERSION:
        return None
    return datetime.now(UTC).strftime("%Y-%m-%dT")


def _as_json(found: Mapping[str, TableDigest]) -> str:
    return json.dumps({k: [v.rows, v.sha256] for k, v in found.items()}, sort_keys=True)


def _from_json(text: str) -> dict[str, TableDigest]:
    raw = json.loads(text)
    return {str(k): TableDigest(int(v[0]), str(v[1])) for k, v in raw.items()}


# Export (the owner's machine).


def _secret_columns(conn: sqlite3.Connection) -> list[str]:
    found = []
    for table in _tables(conn):
        if SECRET_NAMES.search(table):
            found.append(table)
        for column in conn.execute(f"PRAGMA table_info({_quoted(table)})"):
            if SECRET_NAMES.search(str(column[1])):
                found.append(f"{table}.{column[1]}")
    return found


def _secret_values(secrets_found: Iterable[str]) -> list[bytes]:
    values: list[bytes] = []
    for value in secrets_found:
        candidates = [value]
        try:  # the Gmail token is a JSON document: look for each of its strings too
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            candidates += [v for v in parsed.values() if isinstance(v, str)]
        values += [c.encode() for c in candidates if len(c) >= MIN_SECRET]
    return values


def _only_in_bank_text(conn: sqlite3.Connection, value: str) -> bool:
    """Whether `value` appears in the database, and only inside columns of `BANK_TEXT`."""
    places: set[str] = set()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    for table in tables:
        for column in [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]:
            query = f'SELECT 1 FROM "{table}" WHERE instr(CAST("{column}" AS TEXT), ?) > 0 LIMIT 1'
            if conn.execute(query, (value,)).fetchone():
                places.add(f"{table}.{column}")
    return bool(places) and places <= BANK_TEXT


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def export_account(
    database: Path,
    out: Path,
    holders: Path | None = None,
    keyring_secrets: Iterable[str] = (),
    clock: float | None = None,
) -> Exported:
    """Write the export of the local `database` (and its `holders` file) to the new file `out`.
    `keyring_secrets`: the PDF password and Gmail token, only to prove they are not in it."""
    if not database.is_file():
        raise TransferError(f"there is no database at {database}")
    if out.exists():
        raise TransferError(f"{out} already exists: choose a new file")
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f".{out.name}.{secrets.token_hex(4)}.partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with (
            closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as src,
            closing(sqlite3.connect(partial)) as dst,
        ):
            src.backup(dst)
            dst.execute("PRAGMA journal_mode = DELETE")
            version = int(dst.execute("PRAGMA user_version").fetchone()[0])
            if problems := _integrity(dst):
                raise TransferError(f"the local database is damaged: {problems[0]}")
            if leaked := _secret_columns(dst):
                raise TransferError(f"a secret-looking column is in the database: {leaked[0]}")
            found = digest(dst)
            holders_text = (
                holders.read_text(encoding="utf-8") if holders and holders.is_file() else ""
            )
            meta = {
                "format": str(FORMAT),
                "schema_version": str(version),
                "exported_at": str(int(clock if clock is not None else time.time())),
                "holders": holders_text,
                "tables": _as_json(found),
            }
            with dst:
                dst.execute(f"CREATE TABLE {MANIFEST} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                dst.executemany(f"INSERT INTO {MANIFEST} VALUES (?, ?)", meta.items())
            dst.execute("VACUUM")  # no freed page keeps anything
            values = _secret_values(keyring_secrets)
            in_bank_text = {v for v in values if _only_in_bank_text(dst, v.decode())}
        content = partial.read_bytes()
        if any(value in content for value in values if value not in in_bank_text):
            raise TransferError("a keyring secret appears in the export: not writing it")
        partial.chmod(0o600)
        _fsync(partial)
        os.replace(partial, out)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return Exported(out, version, len(found), out.stat().st_size)


def _integrity(conn: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in conn.execute("PRAGMA integrity_check") if row[0] != "ok"]


# Import (the server).


@dataclass(frozen=True)
class _Source:
    schema_version: int
    holders: str
    tables: dict[str, TableDigest]
    expected: dict[str, TableDigest]  # after the forward migrations and the holders


def _read_source(path: Path) -> _Source:
    """Check the export at `path` and what it should become once migrated (computed on a copy
    in memory: the plaintext is never written anywhere else)."""
    if path.is_symlink():
        raise TransferError(f"{path} is a symbolic link: give the file itself")
    if not path.is_file():
        raise TransferError(f"there is no file at {path}")
    if not encrypted.is_plain(path):
        raise TransferError(f"{path} is not an unencrypted SQLite file from export-account")
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as src:
            return _check_source(src)
    except (KeyError, ValueError, TypeError, IndexError, sqlite3.Error) as error:
        raise TransferError(f"the export is not valid ({type(error).__name__})") from None


def _check_source(src: sqlite3.Connection) -> _Source:
    if problems := _integrity(src):
        raise TransferError(f"the export is damaged: {problems[0]}")
    try:
        meta = dict(src.execute(f"SELECT key, value FROM {MANIFEST}").fetchall())
    except sqlite3.OperationalError:
        raise TransferError("the file was not made by `michelito export-account`") from None
    if meta.get("format") != str(FORMAT):
        raise TransferError("the export's format is not one this version reads")
    version = int(meta["schema_version"])
    if version > db.SCHEMA_VERSION:
        raise TransferError(
            f"the export has schema {version}, newer than the server's "
            f"{db.SCHEMA_VERSION}: deploy the new version first"
        )
    tables = digest(src)
    if tables != _from_json(meta["tables"]):
        raise TransferError("the export does not match its own manifest (damaged on the way)")
    text = str(meta.get("holders", ""))
    with closing(sqlite3.connect(":memory:")) as memory:
        src.backup(memory)
        memory.execute(f"DROP TABLE {MANIFEST}")
        db.upgrade(memory)
        if text:
            with memory:
                holders.write(memory, text)
        expected = digest(memory, _stamp(version))
    return _Source(version, text, tables, expected)


class PlaintextNotRemoved(TransferError):
    """The account was imported, but the plaintext export could not be removed."""

    def __init__(self, imported: Imported, path: Path, reason: str) -> None:
        super().__init__(f"the plaintext export {path} could not be removed: {reason}")
        self.imported = imported
        self.path = path


def _encrypted_copy(
    source: Path, staging: Path, data_key: bytes, found: _Source
) -> tuple[int, int]:
    """Encrypt, migrate, add the holders and prove the copy equal to the expected result;
    returns (schema version, tables)."""
    encrypted.encrypt_copy(source, staging, data_key)
    with closing(db.connect(staging, data_key)) as conn:
        with conn:
            conn.execute(f"DROP TABLE {MANIFEST}")
            if found.holders:
                holders.write(conn, found.holders)
        conn.execute("VACUUM")
        migrated = digest(conn, _stamp(found.schema_version))
        schema_to = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if problems := encrypted.problems(staging, data_key):
        raise TransferError(f"the encrypted copy failed its integrity check: {problems[0]}")
    if migrated != found.expected:
        different = sorted(
            t
            for t in set(migrated) | set(found.expected)
            if migrated.get(t) != found.expected.get(t)
        )
        raise TransferError(f"the encrypted copy differs from the export in: {different[0]}")
    return schema_to, len(migrated)


def import_account(
    store: Store,
    master: MasterKey,
    root: Path,
    email: str,
    source: Path,
    replace: bool = False,
    clock: float | None = None,
) -> Imported:
    """Create the hosted account `email` from the export at `source` (see the module). An
    existing account is refused unless `replace`: then the old account (and its data key) is
    deleted and the new one created in the same transaction. The plaintext `source` is removed
    only after everything checked out (`PlaintextNotRemoved` if that last step fails)."""
    email = auth.normalize(email)
    if not auth.valid_email(email):
        raise TransferError("that does not look like an email address")
    existing = store.account_by_email(email)
    if existing is not None and not replace:
        raise TransferError("that email already has an account (see --replace)")
    found = _read_source(source)
    folder = secrets.token_hex(16)
    data_key = keys.new_data_key()
    place = config.ensure_private_dir(root / auth.USERS / folder)
    staging = place / f"{auth.DATABASE}{IMPORTING}"

    def seal(account_id: int) -> tuple[bytes, str]:
        return keys.wrap(master, data_key, account_id, folder), master.id

    try:
        try:
            schema_to, tables = _encrypted_copy(source, staging, data_key, found)
        except sqlite3.Error as error:
            raise TransferError(f"the encrypted copy could not be made ({error})") from None
        os.replace(staging, place / auth.DATABASE)
        now = int(clock if clock is not None else time.time())
        try:
            if existing is not None:
                account = store.replace_account(existing.id, email, folder, now, seal)
            else:
                account = store.create_account(email, folder, now, None, seal)
        except LookupError:
            raise TransferError("the account changed meanwhile: nothing imported") from None
    except BaseException:
        shutil.rmtree(place, ignore_errors=True)
        raise
    if existing is not None:  # only after the commit: its key is gone and it has a tombstone
        old_place = root / auth.USERS / existing.folder
        shutil.rmtree(old_place, ignore_errors=True)
        if not old_place.exists():  # otherwise the server's next start removes it
            store.forget_deleted_folder(existing.folder)
    done = Imported(
        account,
        existing is not None,
        found.schema_version,
        schema_to,
        tables,
        SecureDelete((), OVERWRITE_NOTE),
    )
    try:
        removed = secure_delete(source)
    except OSError as error:
        raise PlaintextNotRemoved(done, source, error.strerror or "error") from None
    if source.exists() or source.is_symlink():
        raise PlaintextNotRemoved(done, source, "it is still there")
    return Imported(account, done.replaced, done.schema_from, schema_to, tables, removed)


# Removing the plaintext.

OVERWRITE_NOTE = (
    "overwritten with zeros and removed; on an SSD, a journaling or copy-on-write file system "
    "or with snapshots, old copies of its blocks may survive: keep the import folder on an "
    "encrypted disk and the file there for as short as possible"
)


def _overwrite(path: Path) -> None:
    size = path.stat().st_size
    zeros = bytes(min(size, _CHUNK) or 1)
    with path.open("r+b", buffering=0) as handle:
        left = size
        while left > 0:
            left -= handle.write(zeros[: min(left, len(zeros))])
        os.fsync(handle.fileno())


def secure_delete(path: Path) -> SecureDelete:
    """Overwrite (best effort) and unlink `path` and the journal files SQLite may have left next
    to it, then sync the folder. Honest about the limits (`OVERWRITE_NOTE`)."""
    removed = []
    for candidate in (path, *(path.with_name(path.name + s) for s in ("-journal", "-wal", "-shm"))):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        _overwrite(candidate)
        candidate.unlink()
        removed.append(candidate.name)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return SecureDelete(tuple(removed), OVERWRITE_NOTE)
