"""Open every account's database once, right after a deploy (`michelito check-accounts`).

An account's database is migrated the first time it is opened, so a migration that fails on
someone's data would otherwise show up only when that person comes back: the server starts,
`/api/health` answers and the deploy looks fine. Opening them all here migrates them at once and
names the accounts that could not be opened. Each migration is one transaction, so a database
that fails is left as it was.

Nothing about an account is printed or logged beyond its number and the class of the error.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from michelito import db
from michelito.hosted import auth, keys
from michelito.hosted.keys import MasterKey
from michelito.hosted.store import Store, WrappedKey

log = logging.getLogger(__name__)
BUSY_ATTEMPTS = 3  # each one already waits SQLite's own timeout for a writer


@dataclass(frozen=True)
class Failure:
    account_id: int
    error: str  # the class of the exception, never its text


@dataclass(frozen=True)
class Checked:
    opened: int
    failures: tuple[Failure, ...]


def _open(root: Path, master: MasterKey, item: WrappedKey) -> bool:
    """Open (and so migrate) that account's database; False when it has none yet."""
    path = root / auth.USERS / item.folder / auth.DATABASE
    if not path.is_file():
        return False
    data_key = keys.unwrap(master, item.wrapped, item.account_id, item.folder)
    for _ in range(BUSY_ATTEMPTS - 1):
        try:
            with closing(db.connect(path, data_key)):
                return True
        except sqlite3.OperationalError:
            # The server is running: a request may hold the write lock past SQLite's wait.
            continue
    with closing(db.connect(path, data_key)):
        return True


def check_accounts(store: Store, master: MasterKey, root: Path) -> Checked:
    """Open the database of every account that has a data key. One that fails never stops the
    others."""
    opened = 0
    failures: list[Failure] = []
    for item in store.data_keys():
        try:
            opened += _open(root, master, item)
        except Exception as exc:  # noqa: BLE001 - reported per account; the rest still open
            log.error(
                "the database of account %d could not be opened: %s",
                item.account_id,
                type(exc).__name__,
            )
            failures.append(Failure(item.account_id, type(exc).__name__))
    return Checked(opened, tuple(failures))
