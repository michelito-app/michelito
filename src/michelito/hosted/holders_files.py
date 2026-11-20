"""Start-up step: holders files left in hosted account folders move into the encrypted databases.

An earlier version of `import-account` wrote the owner's holders as a plaintext `holders.txt`
next to the account's database. At start-up every such file is copied into that account's
encrypted database (`michelito.holders`), read back, and only then overwritten and removed.
"""

from __future__ import annotations

from contextlib import closing

from michelito import db, holders
from michelito.hosted import auth, keys, transfer
from michelito.hosted.keys import MasterKey
from michelito.hosted.store import Store


def absorb(store: Store, master: MasterKey, root) -> int:  # noqa: ANN001 (a Path)
    """Move every account's `holders.txt` into its database; returns how many moved."""
    moved = 0
    for stored in store.data_keys():
        place = root / auth.USERS / stored.folder
        path = place / auth.HOLDERS
        database = place / auth.DATABASE
        if path.is_symlink() or not path.is_file() or not database.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        key = keys.unwrap(master, stored.wrapped, stored.account_id, stored.folder)
        with closing(db.connect(database, key)) as conn:
            with conn:
                holders.write(conn, content)
            if holders.read(conn) != content:
                raise RuntimeError("the holders did not reach the encrypted database")
        transfer.secure_delete(path)
        moved += 1
    return moved
