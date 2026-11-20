"""`michelito restore`: a backup (`hosted.backup`) back onto an **empty** hosted folder.

Given the master key file, it downloads the backup's manifest and every object it lists, checks
each one's size and SHA-256, unseals the accounts database, writes the
encrypted databases as they are, and then proves the result usable: every account's data key
unwraps, every database opens with it and passes SQLCipher's page check and SQLite's
`integrity_check`, and every account has exactly its database (no more, no less).

The code-hash secret is not in backups: the restored server makes a new one (or uses its Docker
secret), which only invalidates the sign-in codes in flight.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from michelito import config, encrypted
from michelito.hosted import auth, keys
from michelito.hosted.backup import (
    ACCOUNTS,
    FORMAT,
    MANIFEST,
    NAMES,
    R2_PREFIX,
    SEALED,
    BackupError,
    Target,
    authentic,
    labels,
    sha256,
    unseal,
)
from michelito.hosted.keys import MasterKey
from michelito.hosted.store import FILENAME, Store


class RestoreError(BackupError):
    """The backup could not be restored or did not check out (names no data)."""


@dataclass(frozen=True)
class Restored:
    label: str
    accounts: int
    files: int
    newest: str  # the newest complete backup (a warning when it is not `label`)

    @property
    def older(self) -> bool:
        return self.label != self.newest


def _empty(data: Path) -> None:
    if data.exists() and (not data.is_dir() or any(data.iterdir())):
        raise RestoreError(f"{data} is not empty: restore only onto an empty folder")


def _write(path: Path, body: bytes) -> None:
    config.ensure_private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def _manifest(target: Target, prefix: str, label: str, master: MasterKey) -> dict[str, object]:
    key = "/".join(p for p in (prefix, label, MANIFEST) if p)
    try:
        manifest = json.loads(target.get(key))
    except ValueError:
        raise RestoreError("the backup's manifest is not valid") from None
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise RestoreError("the backup's manifest has an unknown format")
    if manifest.get("master_id") != master.id:
        raise RestoreError("the backup was made with another master key")
    # Before anything else is downloaded: only the master key can make this MAC, and it covers
    # the label and every object's size and SHA-256.
    if not authentic(master, manifest):
        raise RestoreError("the backup's manifest is not authentic (edited or not ours)")
    if manifest.get("label") != label:
        raise RestoreError("the manifest belongs to another backup")
    return manifest


def choose(target: Target, prefix: str, wanted: str) -> str:
    """The label to restore: `wanted`, or the newest complete backup for "latest"."""
    found = labels(target, prefix)
    if wanted == "latest":
        if not found:
            raise RestoreError("there is no complete backup")
        return found[-1]
    if wanted not in found:
        raise RestoreError(f"there is no complete backup labeled {wanted}")
    return wanted


def _download(target: Target, prefix: str, label: str, master: MasterKey, data: Path) -> int:
    manifest = _manifest(target, prefix, label, master)
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RestoreError("the backup's manifest lists no files")
    names = [str(entry.get("name", "")) for entry in files if isinstance(entry, dict)]
    if ACCOUNTS not in names:
        raise RestoreError("the backup has no accounts database")
    for entry in files:
        name = str(entry.get("name", ""))
        if not NAMES.fullmatch(name):
            raise RestoreError("the manifest names an unexpected file")
        body = target.get("/".join(p for p in (prefix, label, name) if p))
        if len(body) != entry.get("size") or sha256(body) != entry.get("sha256"):
            raise RestoreError(f"{name} does not match its checksum")
        if name.endswith(SEALED):
            body = unseal(master, label, name, body)
            name = name[: -len(SEALED)]
        _write(data / name, body)
    return len(files)


def _verify(data: Path, master: MasterKey) -> int:
    accounts = data / FILENAME
    with closing(sqlite3.connect(accounts)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise RestoreError("the accounts database failed its integrity check")
    store = Store(accounts)
    known = store.folders()
    stored_keys = store.data_keys()
    if len(stored_keys) != len(known):
        raise RestoreError("some account has no data key")
    users = data / auth.USERS
    present = {p.name for p in users.iterdir()} if users.is_dir() else set()
    if present != known:
        raise RestoreError("the databases in the backup do not match its accounts")
    for stored in stored_keys:
        try:
            key = keys.unwrap(master, stored.wrapped, stored.account_id, stored.folder)
        except keys.UnwrapError:
            raise RestoreError("a data key does not open with this master key") from None
        database = users / stored.folder / auth.DATABASE
        if not database.is_file():
            raise RestoreError("an account's database is missing from the backup")
        try:
            found = encrypted.problems(database, key)
        except sqlite3.DatabaseError:
            raise RestoreError("an account's database does not open with its key") from None
        if found:
            raise RestoreError("an account's database failed its integrity check")
    return len(stored_keys)


def restore(
    target: Target,
    master: MasterKey,
    data: Path,
    label: str = "latest",
    prefix: str = R2_PREFIX,
) -> Restored:
    """Restore the backup `label` ("latest": the newest complete one) into the empty `data`:
    everything goes into a temporary folder next to it, is verified there, and only then takes
    the place of `data` (on any error the temporary folder is removed and `data` is untouched)."""
    _empty(data)
    chosen = choose(target, prefix, label)
    newest = labels(target, prefix)[-1]
    data.parent.mkdir(parents=True, exist_ok=True)
    work = data.parent / f".{data.name}.restoring-{secrets.token_hex(4)}"
    config.ensure_private_dir(work)
    try:
        files = _download(target, prefix, chosen, master, work)
        accounts = _verify(work, master)
        _empty(data)
        if data.exists():
            data.rmdir()
        os.replace(work, data)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return Restored(chosen, accounts, files, newest)
