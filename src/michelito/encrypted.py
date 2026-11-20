"""Encrypted SQLite files (SQLCipher 4) behind the standard `sqlite3` interface.

Only hosted mode uses this (one encrypted database per account); the local board and the demo
keep plain `sqlite3`. The engine is the `sqlcipher3` binding (DB-API 2.0, SQLCipher compiled into
its wheel with OpenSSL): every page of the database **and of its journal** is encrypted with
AES-256 and authenticated with HMAC-SHA512, so a changed or foreign page is refused, not read.

`connect(path, key)` returns a connection the rest of the code can use exactly like a `sqlite3`
one, so `db.connect` and every schema migration run unchanged on it:

- the key is a raw 256-bit key given to SQLCipher as `x'…'` (no passphrase, so no key
  derivation on every request); a wrong key fails at once with `sqlite3.DatabaseError`;
- temporary tables and indexes stay in memory (`temp_store = MEMORY`), never in a temp file;
- errors are re-raised as the `sqlite3` exception of the same name (`sqlite3.IntegrityError`,
  `sqlite3.OperationalError`…), so the existing `except sqlite3.…` clauses keep working;
- `row_factory = sqlite3.Row` gives the binding's own `Row` (same interface).

Nothing here logs, prints or keeps the key.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any, cast

KEY_BYTES = 32
# The first 16 bytes of every plain SQLite file; an encrypted one starts with its random salt.
PLAIN_HEADER = b"SQLite format 3\x00"


def _engine() -> Any:
    from sqlcipher3 import dbapi2  # noqa: PLC0415 (only hosted mode loads the engine)

    return dbapi2


def _translated(error: Exception) -> Exception:
    """The `sqlite3` exception of the same kind, with the same message and error code."""
    kind = getattr(sqlite3, type(error).__name__, None)
    if not (isinstance(kind, type) and issubclass(kind, sqlite3.Error)):
        kind = sqlite3.DatabaseError
    twin = kind(*error.args)
    for name in ("sqlite_errorcode", "sqlite_errorname"):
        if hasattr(error, name):
            setattr(twin, name, getattr(error, name))
    return twin


def _guard(call: Callable[..., Any], wrap: Callable[[Any], Any]) -> Callable[..., Any]:
    def guarded(*args: Any, **kwargs: Any) -> Any:
        try:
            result = call(*args, **kwargs)
        except _engine().Error as error:
            raise _translated(error) from error
        return wrap(result)

    return guarded


class _Cursor:
    """A binding cursor that raises `sqlite3` exceptions."""

    __slots__ = ("_raw",)

    def __init__(self, raw: Any) -> None:
        object.__setattr__(self, "_raw", raw)

    def _wrap(self, result: Any) -> Any:
        return self if result is self._raw else result

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._raw, name)
        return _guard(value, self._wrap) if callable(value) else value

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._raw, name, value)

    def __iter__(self) -> Iterator[Any]:
        return self

    def __next__(self) -> Any:
        try:
            return next(self._raw)
        except _engine().Error as error:
            raise _translated(error) from error


class _Connection:
    """A binding connection that behaves like a `sqlite3.Connection` for this codebase."""

    __slots__ = ("_raw",)

    def __init__(self, raw: Any) -> None:
        object.__setattr__(self, "_raw", raw)

    def _wrap(self, result: Any) -> Any:
        if result is self._raw:
            return self
        if isinstance(result, _engine().Cursor):
            return _Cursor(result)
        return result

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._raw, name)
        return _guard(value, self._wrap) if callable(value) else value

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "row_factory" and value is sqlite3.Row:
            value = _engine().Row
        setattr(self._raw, name, value)

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *exc: object) -> bool:
        return bool(_guard(self._raw.__exit__, lambda result: result)(*exc))

    def __repr__(self) -> str:
        return "<encrypted sqlite3 connection>"


def _raw(path: Path | str) -> Any:
    """A binding connection with SQLCipher's own logging off: it would write to stderr (a wrong
    key, a failed HMAC) outside the app's logs; the error still reaches the caller."""
    raw = _engine().connect(str(path))
    try:
        raw.executescript("PRAGMA cipher_log_level = NONE;")
    except BaseException:
        raw.close()
        raise
    return raw


def _open(path: Path | str, key: bytes) -> _Connection:
    if len(key) != KEY_BYTES:
        raise ValueError("an encrypted database needs a 256-bit key")
    raw = _raw(path)
    try:
        # A raw key: SQLCipher uses it as is (no KDF) and keeps the file's random salt. Through
        # `executescript`, so the statement holding the key stays out of the statement cache.
        raw.executescript(f"PRAGMA key = \"x'{key.hex()}'\";")
        raw.execute("PRAGMA temp_store = MEMORY")
        # Reading the schema checks the key (and the HMAC of the first page) right away.
        raw.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except _engine().Error as error:
        raw.close()
        raise _translated(error) from None
    except BaseException:
        raw.close()
        raise
    return _Connection(raw)


def connect(path: Path | str, key: bytes) -> sqlite3.Connection:
    """The encrypted database at `path` (created if missing), opened with the raw `key`."""
    return cast(sqlite3.Connection, _open(path, key))


def is_plain(path: Path) -> bool:
    """Whether the file at `path` is an unencrypted SQLite database."""
    with path.open("rb") as handle:
        return handle.read(len(PLAIN_HEADER)) == PLAIN_HEADER


def encrypt_copy(plain: Path, target: Path, key: bytes) -> None:
    """Write at `target` an encrypted copy (schema, rows, `user_version`) of the plain database
    at `plain`, with SQLCipher's own export; `target` must not exist."""
    if target.exists():
        raise FileExistsError(target)
    raw = _raw(plain)  # no key: a plain database
    try:
        version = int(raw.execute("PRAGMA user_version").fetchone()[0])
        raw.execute("ATTACH DATABASE ? AS sealed KEY ?", (str(target), f"x'{key.hex()}'"))
        raw.execute("SELECT sqlcipher_export('sealed')").fetchone()
        raw.execute(f"PRAGMA sealed.user_version = {version}")
        raw.execute("DETACH DATABASE sealed")
    except _engine().Error as error:
        raise _translated(error) from None
    finally:
        raw.close()
    target.chmod(0o600)
    with closing(connect(target, key)) as check:  # readable with the key, or it fails here
        check.execute("SELECT count(*) FROM sqlite_master").fetchone()
    fd = os.open(target, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def snapshot(source: Path, target: Path, key: bytes) -> None:
    """A consistent copy of the encrypted database at `source` in the new file `target`, with
    SQLite's backup API: still encrypted with the same `key` (the pages are re-encrypted with a
    new random salt), so it is a backup that opens exactly like the original."""
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    origin = _open(source, key)
    try:
        copy = _open(target, key)
        try:
            origin._raw.backup(copy._raw)
        except _engine().Error as error:
            raise _translated(error) from None
        finally:
            copy.close()
    finally:
        origin.close()
    fd = os.open(target, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def problems(path: Path, key: bytes) -> list[str]:
    """What SQLCipher's page authentication (`cipher_integrity_check`) and SQLite's
    `integrity_check` find wrong in the encrypted database at `path` (empty: it is sound)."""
    with closing(_open(path, key)) as conn:
        found = [str(row[0]) for row in conn.execute("PRAGMA cipher_integrity_check")]
        found += [str(row[0]) for row in conn.execute("PRAGMA integrity_check") if row[0] != "ok"]
    return found
