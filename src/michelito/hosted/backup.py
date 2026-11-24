"""Backups of the hosted folder: every account's database **as it is (encrypted)** plus the
accounts database, to Cloudflare R2 every night (and to a local folder before every deploy).

One backup is a set of objects under `<prefix>/<label>/` (the label is the UTC date for the
nightly ones; a second backup on the same day gets `<date>T<HHMMSS>Z`, because the bucket's object
lock refuses to overwrite the first one's objects):

- `users/<folder>/michelito.db`: a consistent snapshot of the account's SQLCipher file, taken
  with SQLite's backup API into a temporary file inside the data folder; still encrypted with
  the account's data key (which is itself only stored wrapped by the master key);
- `accounts.db.sealed`: a snapshot of the accounts database (emails, wrapped keys), **sealed**
  with AES-256-GCM under a key derived from the master key, with `<label>/<name>` as associated
  data (a sealed object moved to another backup does not open), so the storage provider reads
  nothing in it either;
- `manifest.json`, uploaded last (a backup without it is incomplete): its label, the size and
  SHA-256 of every object and the fingerprint of the master key (never the key), **authenticated
  with an HMAC** under another key derived from the master key. `restore` checks the HMAC before
  downloading anything else, so neither the manifest nor any object (whose SHA-256 it lists)
  can be edited, swapped with another backup's or renamed without the master key.

(The holders live inside each encrypted database: there is no separate holders object.)

Every object is read back after uploading and its SHA-256 compared. Never uploaded: the master
key, the code-hash secret (`secret.key`), the operations state, the mail outbox or anything else
in the folder: the set of objects is built from the accounts, not by walking the folder.
Backups older than the retention (30 days by default) are deleted after a successful one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from michelito import config, encrypted
from michelito.hosted import auth, keys
from michelito.hosted.keys import MasterKey
from michelito.hosted.store import FILENAME, FOLDER, Store

FORMAT = 2  # 2: authenticated manifest, label in every seal
MANIFEST = "manifest.json"
ACCOUNTS = f"{FILENAME}.sealed"
SEALED = ".sealed"
R2_PREFIX = "backups"
RETENTION_DAYS = 30
STAGING = ".backup-staging-"
_SEAL_INFO = b"michelito backup seal v1"
_MAC_INFO = b"michelito backup manifest v1"
_SEAL_VERSION = b"\x01"
_NONCE = 12
LABEL = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")
DATE_LABEL = re.compile(r"(\d{4}-\d{2}-\d{2})(T\d{6}Z)?")  # a day, or a later run that day
# The only object names a backup has (a tampered manifest cannot name anything else).
NAMES = re.compile(rf"{re.escape(ACCOUNTS)}|users/{FOLDER.pattern}/{re.escape(auth.DATABASE)}")


class BackupError(Exception):
    """The backup could not be completed (the message names no data and no credential)."""


class Target(Protocol):
    """Where backups go: an S3 bucket (`s3.Client`) or a local folder (`FolderTarget`)."""

    def put(self, key: str, body: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def list(self, prefix: str) -> list[str]: ...


@dataclass(frozen=True)
class FolderTarget:
    """Backups in a local folder (before a deploy): keys are paths under `root`."""

    root: Path

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise BackupError("a key outside the backup folder")
        return path

    def put(self, key: str, body: bytes) -> None:
        path = self._path(key)
        config.ensure_private_dir(self.root)
        for folder in reversed(path.parent.relative_to(self.root.resolve()).parents[:-1]):
            config.ensure_private_dir(self.root / folder)
        config.ensure_private_dir(path.parent)
        partial = path.with_name(f".{path.name}.partial")
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            raise BackupError(f"{key} is not in the backup folder") from None

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        for parent in path.parents:
            if parent == self.root.resolve():
                break
            try:
                parent.rmdir()
            except OSError:
                break

    def list(self, prefix: str) -> list[str]:
        if not self.root.is_dir():
            return []
        found = [
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and not p.name.startswith(".")
        ]
        return sorted(k for k in found if k.startswith(prefix))


# Sealing (the accounts database) and the manifest's MAC.


def derived(master: MasterKey, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master.secret)


def _aad(label: str, name: str) -> bytes:
    return f"{label}/{name}".encode()


def seal(master: MasterKey, label: str, name: str, content: bytes) -> bytes:
    nonce = secrets.token_bytes(_NONCE)
    sealed = AESGCM(derived(master, _SEAL_INFO)).encrypt(nonce, content, _aad(label, name))
    return _SEAL_VERSION + nonce + sealed


def unseal(master: MasterKey, label: str, name: str, sealed: bytes) -> bytes:
    if sealed[:1] != _SEAL_VERSION or len(sealed) < 1 + _NONCE:
        raise BackupError(f"{name} is not a sealed backup file")
    nonce = sealed[1 : 1 + _NONCE]
    key = derived(master, _SEAL_INFO)
    try:
        return AESGCM(key).decrypt(nonce, sealed[1 + _NONCE :], _aad(label, name))
    except InvalidTag:
        raise BackupError(f"{name} does not open with this master key and label") from None


def _canonical(manifest: dict[str, object]) -> bytes:
    body = {k: v for k, v in manifest.items() if k != "mac"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def manifest_mac(master: MasterKey, manifest: dict[str, object]) -> str:
    """The HMAC-SHA256 of the canonical manifest (everything but its `mac`)."""
    return hmac.new(derived(master, _MAC_INFO), _canonical(manifest), hashlib.sha256).hexdigest()


def authentic(master: MasterKey, manifest: dict[str, object]) -> bool:
    given = manifest.get("mac")
    return isinstance(given, str) and hmac.compare_digest(given, manifest_mac(master, manifest))


# Backing up.


@dataclass(frozen=True)
class Entry:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class BackupResult:
    label: str
    entries: tuple[Entry, ...]
    deleted: tuple[str, ...] = ()  # labels removed by the rotation
    missing: int = 0  # accounts whose database file was not there


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _key(prefix: str, label: str, name: str) -> str:
    return "/".join(part for part in (prefix, label, name) if part)


def _upload(target: Target, key: str, body: bytes) -> None:
    """Put `body` and read it back: the stored object must have the same SHA-256."""
    target.put(key, body)
    if sha256(target.get(key)) != sha256(body):
        raise BackupError(f"{key.rsplit('/', 1)[-1]} came back different after uploading")


def _snapshot_accounts(source: Path, staging: Path) -> bytes:
    copy = staging / FILENAME
    with (
        closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(copy)) as dst,
    ):
        src.backup(dst)
        dst.execute("PRAGMA journal_mode = DELETE")
    return copy.read_bytes()


@dataclass
class _Run:
    target: Target
    prefix: str
    label: str
    entries: list[Entry] = field(default_factory=list)

    def add(self, name: str, body: bytes) -> None:
        _upload(self.target, _key(self.prefix, self.label, name), body)
        self.entries.append(Entry(name, len(body), sha256(body)))


def run_backup(
    data: Path,
    master: MasterKey,
    target: Target,
    label: str,
    prefix: str = R2_PREFIX,
    clock: Callable[[], float] = time.time,
) -> BackupResult:
    """Back up the hosted folder `data` to `target` under `<prefix>/<label>/` (see the module).
    `BackupError` if any account's database could not be backed up (the rest still is, and the
    manifest records what is there)."""
    if not LABEL.fullmatch(label):
        raise BackupError("a backup label is letters, digits, dots and dashes")
    accounts = data / FILENAME
    if not accounts.is_file():
        raise BackupError(f"no accounts database in {data}")
    store = Store(accounts)
    staging = Path(os.path.realpath(data)) / f"{STAGING}{secrets.token_hex(4)}"
    staging.mkdir(mode=0o700)
    run = _Run(target, prefix, label)
    missing = 0
    try:
        run.add(ACCOUNTS, seal(master, label, ACCOUNTS, _snapshot_accounts(accounts, staging)))
        for stored in store.data_keys():
            place = data / auth.USERS / stored.folder
            database = place / auth.DATABASE
            if not database.is_file():
                missing += 1
                continue
            data_key = keys.unwrap(master, stored.wrapped, stored.account_id, stored.folder)
            copy = staging / f"{stored.folder}.db"
            encrypted.snapshot(database, copy, data_key)
            run.add(f"{auth.USERS}/{stored.folder}/{auth.DATABASE}", copy.read_bytes())
            copy.unlink()
        manifest: dict[str, object] = {
            "format": FORMAT,
            "label": label,
            "created_at": int(clock()),
            "master_id": master.id,
            "files": [e.__dict__ for e in run.entries],
        }
        manifest["mac"] = manifest_mac(master, manifest)
        _upload(target, _key(prefix, label, MANIFEST), json.dumps(manifest, indent=1).encode())
    except keys.UnwrapError:
        raise BackupError("a data key does not open with this master key") from None
    except sqlite3.Error as error:
        raise BackupError(f"a database could not be read: {error}") from None
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if missing:
        raise BackupError(f"{missing} account(s) have no database file")
    return BackupResult(label, tuple(run.entries), missing=missing)


# Listing and rotation.


def labels(target: Target, prefix: str = R2_PREFIX) -> list[str]:
    """The complete backups (with a manifest), oldest first."""
    start = f"{prefix}/" if prefix else ""
    found = set()
    for key in target.list(start):
        rest = key[len(start) :]
        label, _, name = rest.partition("/")
        if name == MANIFEST and LABEL.fullmatch(label):
            found.add(label)
    return sorted(found)


def _remove(target: Target, prefix: str, label: str) -> None:
    start = _key(prefix, label, "") + "/"
    keys_found = target.list(start)
    # The manifest first: a half-deleted backup is never taken for a complete one.
    for key in sorted(keys_found, key=lambda k: not k.endswith(f"/{MANIFEST}")):
        target.delete(key)


def rotate_by_age(
    target: Target, today: date, days: int = RETENTION_DAYS, prefix: str = R2_PREFIX
) -> tuple[str, ...]:
    """Delete the dated backups older than `days` (and the incomplete ones of those days)."""
    oldest = today - timedelta(days=days)
    start = f"{prefix}/" if prefix else ""
    every = {k[len(start) :].partition("/")[0] for k in target.list(start)}
    old = sorted(label for label in every if (day := label_day(label)) and day < oldest)
    for label in old:
        _remove(target, prefix, label)
    return tuple(old)


def rotate_by_count(target: Target, keep: int, prefix: str = "") -> tuple[str, ...]:
    """Keep only the `keep` newest complete backups (labels sort by time)."""
    old = labels(target, prefix)[:-keep] if keep > 0 else []
    for label in old:
        _remove(target, prefix, label)
    return tuple(old)


def label_day(label: str) -> date | None:
    """The day of a dated label (`<date>` or `<date>T<HHMMSS>Z`); None for any other."""
    found = DATE_LABEL.fullmatch(label)
    return date.fromisoformat(found.group(1)) if found else None


def free_label(
    target: Target, day: str, clock: Callable[[], float] = time.time, prefix: str = R2_PREFIX
) -> str:
    """`day` if no object is stored under it yet, else `<day>T<HHMMSS>Z`: an object-locked
    bucket refuses to overwrite even an incomplete backup's objects."""
    if not target.list(_key(prefix, day, "") + "/"):
        return day
    return f"{day}T{datetime.fromtimestamp(clock(), UTC).strftime('%H%M%SZ')}"


def today_label(clock: Callable[[], float] = time.time) -> str:
    return datetime.fromtimestamp(clock(), UTC).strftime("%Y-%m-%d")


def stamp_label(suffix: str = "", clock: Callable[[], float] = time.time) -> str:
    stamp = datetime.fromtimestamp(clock(), UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{suffix}" if suffix else stamp
