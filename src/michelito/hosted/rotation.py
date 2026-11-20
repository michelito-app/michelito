"""Master key rotation: re-wrap every account's data key under a new master key.

The database files are not touched (their data keys do not change). First a pre-flight pass
writes nothing: it refuses if any key is under neither master key, and opens every key still
under the old one (a key that does not open stops everything before the first write). Then each
account is one atomic update that only applies while its key is still under the old master key,
so the rotation can stop anywhere (a crash, Ctrl-C) and be run again: keys already under the new
master key are skipped. At the end the accounts database is compacted (`VACUUM`) and its WAL
truncated, so no old wrapping is left in free pages.

The server must be stopped meanwhile (`michelito rotate-master-key` takes the folder's lock, and
the server refuses to start with keys under two masters, `SignIn.check_keys`); once every key is
under the new one, point `MICHELITO_MASTER_KEY_FILE` at the new file and start it again.
"""

from __future__ import annotations

from dataclasses import dataclass

from michelito.hosted import keys
from michelito.hosted.keys import MasterKey
from michelito.hosted.store import Store, WrappedKey


class RotationError(Exception):
    """The rotation cannot run; nothing was written."""


@dataclass(frozen=True)
class Rotated:
    rewrapped: int  # moved to the new master key now
    already: int  # already under it (an earlier, interrupted run)


def _preflight(stored: list[WrappedKey], old: MasterKey, new: MasterKey) -> dict[int, bytes]:
    """Every pending account's data key, opened with the old master key; refuses (before any
    write) a key under neither master, or one that does not open."""
    unknown = [k for k in stored if k.master_id not in (old.id, new.id)]
    if unknown:
        raise RotationError(f"{len(unknown)} data key(s) are under neither master key")
    opened: dict[int, bytes] = {}
    for item in stored:
        if item.master_id != old.id:
            continue
        try:
            opened[item.account_id] = keys.unwrap(old, item.wrapped, item.account_id, item.folder)
        except keys.UnwrapError:
            raise RotationError(
                f"the data key of account {item.account_id} does not open with the old master "
                "key: nothing was changed"
            ) from None
    return opened


def rotate(store: Store, old: MasterKey, new: MasterKey) -> Rotated:
    if old.id == new.id:
        raise RotationError("the new master key is the current one")
    stored = store.data_keys()
    opened = _preflight(stored, old, new)
    rewrapped = 0
    for item in stored:
        data_key = opened.get(item.account_id)
        if data_key is None:
            continue  # already under the new master key
        wrapped = keys.wrap(new, data_key, item.account_id, item.folder)
        if store.rewrap(item.account_id, old.id, wrapped, new.id):
            rewrapped += 1
    store.compact()
    return Rotated(rewrapped, len(stored) - rewrapped)
