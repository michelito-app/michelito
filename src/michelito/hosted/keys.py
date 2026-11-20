"""Envelope encryption of the per-account databases (`onboarding.md`, decision 2).

- Each account has a random 256-bit **data key**; its database file is encrypted with it
  (`michelito.encrypted`). The data key is stored only **wrapped**, in the accounts database:
  AES-256-GCM under the server's **master key**, with the account's id and folder as associated
  data, so a wrapped key copied to another account's row does not open.
- The **master key** is read from a file whose path is configured (a Docker secret in
  production, `0400`): never inside the data folder, never in a database, never logged. A
  missing, unreadable, malformed or too widely readable file stops the server
  (`MasterKeyError`, with a message that names the path, never the content).
- Each wrapped key records which master key wrapped it (`MasterKey.id`, a fingerprint that
  reveals nothing about the key), so a rotation can be resumed (`hosted.rotation`).

Raw keys only live in memory, as `bytes`, for as long as a request needs them.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from michelito.encrypted import KEY_BYTES

MASTER_FILE_ENV = "MICHELITO_MASTER_KEY_FILE"
NONCE_BYTES = 12
WRAP_VERSION = b"\x01"  # first byte of a wrapped key: the format (nonce, ciphertext and tag)
_ID_LABEL = b"michelito master key id v1"
_AAD_LABEL = "michelito data key v1"


class MasterKeyError(Exception):
    """The master key cannot be used (the message says why and names only the path)."""


class UnwrapError(Exception):
    """A wrapped data key did not open: another master key, another account or altered."""


@dataclass(frozen=True)
class MasterKey:
    """The server's master key. Its bytes never appear in `repr` or in any message."""

    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if len(self.secret) != KEY_BYTES:
            raise MasterKeyError("the master key must be 256 bits")

    @property
    def id(self) -> str:
        """A fingerprint to tell master keys apart (a keyed hash: it does not reveal the key)."""
        return hmac.new(self.secret, _ID_LABEL, hashlib.sha256).hexdigest()[:16]


_HEX = re.compile(rb"[0-9a-fA-F]{%d}" % (2 * KEY_BYTES))


def _parse(content: bytes) -> bytes | None:
    """64 hexadecimal characters (and an optional final newline); nothing else."""
    text = content.rstrip(b"\r\n")
    return bytes.fromhex(text.decode("ascii")) if _HEX.fullmatch(text) else None


def load_master(path: Path | str | None, data: Path | None = None) -> MasterKey:
    """The master key in the file at `path`: exactly 64 hexadecimal characters (what
    `openssl rand -hex 32` writes). Refused when missing, unreadable, malformed, readable or
    writable by the group or others, or inside the data folder `data`. (Raw bytes are refused,
    so the code-hash secret file can never be mistaken for it.)"""
    if path is None or not str(path).strip():
        raise MasterKeyError(
            f"no master key: set {MASTER_FILE_ENV} (or --master-key) to the key file's path"
        )
    place = Path(path).expanduser()
    if data is not None:
        resolved = place.resolve()
        folder = data.resolve()
        if resolved == folder or folder in resolved.parents:
            raise MasterKeyError(f"the master key {place} must not live in the data folder")
    try:
        mode = place.stat().st_mode
        content = place.read_bytes()
    except OSError as error:
        reason = error.strerror or "unreadable"
        raise MasterKeyError(f"cannot read the master key {place}: {reason}") from None
    if not stat.S_ISREG(mode):
        raise MasterKeyError(f"the master key {place} is not a regular file")
    if mode & 0o077:
        raise MasterKeyError(
            f"the master key {place} is readable or writable by others: chmod 0400 it"
        )
    secret = _parse(content)
    if secret is None:
        raise MasterKeyError(
            f"the master key {place} must hold 64 hexadecimal characters (openssl rand -hex 32)"
        )
    return MasterKey(secret)


def write_master(path: Path) -> MasterKey:
    """A new random master key in a new file (0400, hexadecimal); never overwrites one."""
    key = MasterKey(secrets.token_bytes(KEY_BYTES))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(key.secret.hex() + "\n")
    return key


def new_data_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def _aad(account_id: int, folder: str) -> bytes:
    return f"{_AAD_LABEL}\0{account_id}\0{folder}".encode()


def wrap(master: MasterKey, data_key: bytes, account_id: int, folder: str) -> bytes:
    """The data key sealed for that account (and only that one) under the master key."""
    if len(data_key) != KEY_BYTES:
        raise ValueError("a data key must be 256 bits")
    nonce = secrets.token_bytes(NONCE_BYTES)
    sealed = AESGCM(master.secret).encrypt(nonce, data_key, _aad(account_id, folder))
    return WRAP_VERSION + nonce + sealed


def unwrap(master: MasterKey, wrapped: bytes, account_id: int, folder: str) -> bytes:
    """The data key of that account; `UnwrapError` if the master key, the account or the
    folder are not the ones it was wrapped for, or the bytes were altered."""
    if len(wrapped) < 1 + NONCE_BYTES or wrapped[:1] != WRAP_VERSION:
        raise UnwrapError("unknown wrapped key format")
    nonce = wrapped[1 : 1 + NONCE_BYTES]
    try:
        key = AESGCM(master.secret).decrypt(
            nonce, wrapped[1 + NONCE_BYTES :], _aad(account_id, folder)
        )
    except InvalidTag:
        raise UnwrapError("the data key does not open with this master key") from None
    if len(key) != KEY_BYTES:
        raise UnwrapError("the data key has the wrong size")
    return key
