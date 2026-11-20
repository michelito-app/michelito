"""Hosted mode's envelope encryption: wrapping with associated data, the master key file, the
start-up checks, batch 1's placeholders, crypto-shredding on deletion, orphan cleanup and master
key rotation. Throwaway keys in temporary folders and synthetic addresses only."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from michelito import cli, db, encrypted
from michelito.hosted import auth, keys, rotation
from michelito.hosted.app import SECRET_FILE_ENV, HostedStateError, Settings, create_hosted_app
from michelito.hosted.auth import KeyStateError
from michelito.hosted.keys import MasterKey, MasterKeyError
from michelito.hosted.lock import FolderBusyError, server_lock
from michelito.hosted.mailer import MemoryMailer
from michelito.hosted.store import FILENAME, Store
from tests.hosted_helpers import WRITE, Hosted, hosted, master_file

ALICE = "alice@example.com"
BOB = "bob@example.com"
MARKER = "QUOKKA-SYNTHETIC-NOTE-4410"


def _master() -> MasterKey:
    return MasterKey(keys.new_data_key())


def _folder(h: Hosted, email: str) -> Path:
    account = h.service.store.account_by_email(email)
    assert account is not None
    return h.data / "users" / account.folder


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    options: dict[str, object] = {
        "data": tmp_path / "hosted",
        "secure_cookie": False,
        "floor": 0.0,
        "background_mail": False,
        "master_key": master_file(tmp_path),
        **overrides,
    }
    return Settings(**options)  # type: ignore[arg-type]


def _label(email: str) -> str:
    return f"{MARKER} {email.partition('@')[0]}"


def _write_note(h: Hosted, email: str) -> None:
    """A category named with the marker, written through the API as that person."""
    client = h.sign_in(email)
    body = {"name": _label(email), "kind": "expense"}
    assert client.post("/api/categories", json=body, headers=WRITE).status_code == 201


def _names(h: Hosted, email: str) -> set[str]:
    return {c["name"] for c in h.sign_in(email).get("/api/categories").json()}


# Wrapping.


def test_a_wrapped_key_opens_only_for_its_account_folder_and_master() -> None:
    master, data_key = _master(), keys.new_data_key()
    wrapped = keys.wrap(master, data_key, 7, "a" * 32)
    assert keys.unwrap(master, wrapped, 7, "a" * 32) == data_key
    assert data_key not in wrapped
    with pytest.raises(keys.UnwrapError):
        keys.unwrap(master, wrapped, 8, "a" * 32)  # moved to another account
    with pytest.raises(keys.UnwrapError):
        keys.unwrap(master, wrapped, 7, "b" * 32)  # another folder
    with pytest.raises(keys.UnwrapError):
        keys.unwrap(_master(), wrapped, 7, "a" * 32)  # another master key
    altered = wrapped[:-1] + bytes([wrapped[-1] ^ 1])
    with pytest.raises(keys.UnwrapError):
        keys.unwrap(master, altered, 7, "a" * 32)
    with pytest.raises(keys.UnwrapError):
        keys.unwrap(master, b"\x02" + wrapped[1:], 7, "a" * 32)
    assert keys.wrap(master, data_key, 7, "a" * 32) != wrapped  # a fresh nonce every time


def test_moving_a_wrapped_key_to_another_account_does_not_open_its_database(
    tmp_path: Path,
) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    h.sign_in(BOB)
    store = h.service.store
    alice, bob = store.account_by_email(ALICE), store.account_by_email(BOB)
    assert alice and bob
    alice_key = store.data_key(alice.id)
    assert alice_key is not None
    with closing(sqlite3.connect(h.data / FILENAME)) as conn, conn:
        conn.execute(
            "UPDATE data_keys SET wrapped = ? WHERE account_id = ?", (alice_key.wrapped, bob.id)
        )
    session = store.sessions_of(bob.id)[0]
    with pytest.raises(keys.UnwrapError):
        h.service.workspace(session)


def test_a_database_does_not_open_with_another_accounts_key(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    _write_note(h, ALICE)
    h.sign_in(BOB)
    store = h.service.store
    bob = store.account_by_email(BOB)
    assert bob
    bob_key = h.service.workspace(store.sessions_of(bob.id)[0]).key
    alice_db = _folder(h, ALICE) / auth.DATABASE
    with pytest.raises(sqlite3.DatabaseError):
        db.connect(alice_db, bob_key)
    with pytest.raises(sqlite3.DatabaseError), closing(sqlite3.connect(alice_db)) as conn:
        conn.execute("SELECT * FROM categories").fetchall()


def test_no_plaintext_from_a_synthetic_write_in_the_account_folder(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    _write_note(h, ALICE)
    assert any(MARKER in name for name in _names(h, ALICE))
    folder = _folder(h, ALICE)
    files = [p for p in folder.rglob("*") if p.is_file()]
    assert files
    for path in files:
        content = path.read_bytes()
        assert MARKER.encode() not in content, path.name
        assert ALICE.encode() not in content, path.name


# The master key file.


def test_the_master_key_file_is_required_and_checked(tmp_path: Path) -> None:
    data = tmp_path / "hosted"
    data.mkdir()
    with pytest.raises(MasterKeyError, match="no master key"):
        keys.load_master(None, data)
    with pytest.raises(MasterKeyError, match="cannot read"):
        keys.load_master(tmp_path / "missing.key", data)
    inside = data / "master.key"
    keys.write_master(inside)
    with pytest.raises(MasterKeyError, match="data folder"):
        keys.load_master(inside, data)
    loose = tmp_path / "loose.key"
    keys.write_master(loose)
    loose.chmod(0o644)
    with pytest.raises(MasterKeyError, match="others"):
        keys.load_master(loose, data)
    short = tmp_path / "short.key"
    short.write_text("abcd\n")
    short.chmod(0o400)
    with pytest.raises(MasterKeyError, match="64 hexadecimal"):
        keys.load_master(short, data)
    raw = tmp_path / "raw.key"  # 32 raw bytes, like the code-hash secret: refused
    raw.write_bytes(os.urandom(32))
    raw.chmod(0o400)
    with pytest.raises(MasterKeyError, match="64 hexadecimal"):
        keys.load_master(raw, data)
    spaced = tmp_path / "spaced.key"
    spaced.write_text(" " + "ab" * 32 + "\n")
    spaced.chmod(0o400)
    with pytest.raises(MasterKeyError, match="64 hexadecimal"):
        keys.load_master(spaced, data)
    made = keys.write_master(tmp_path / "hex.key")
    assert keys.load_master(tmp_path / "hex.key", data) == made
    assert (tmp_path / "hex.key").stat().st_mode & 0o777 == 0o400
    with pytest.raises(FileExistsError):
        keys.write_master(tmp_path / "hex.key")


def test_an_unreadable_master_key_stops_the_app(tmp_path: Path) -> None:
    path = master_file(tmp_path)
    path.chmod(0o000)
    try:
        if os.access(path, os.R_OK):  # pragma: no cover - running as root
            pytest.skip("root reads any file")
        with pytest.raises(MasterKeyError, match="cannot read"):
            create_hosted_app(_settings(tmp_path), MemoryMailer())
    finally:
        path.chmod(0o400)


def test_the_app_does_not_start_without_a_master_key(tmp_path: Path) -> None:
    with pytest.raises(MasterKeyError):
        create_hosted_app(_settings(tmp_path, master_key=None), MemoryMailer())
    with pytest.raises(MasterKeyError):
        create_hosted_app(_settings(tmp_path, master_key=tmp_path / "nope.key"), MemoryMailer())


def test_the_master_key_must_not_be_the_code_hash_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    master = master_file(tmp_path)
    monkeypatch.setenv(SECRET_FILE_ENV, str(master))  # the same file for both
    with pytest.raises(MasterKeyError, match="code-hash secret"):
        create_hosted_app(_settings(tmp_path), MemoryMailer())
    copy = tmp_path / "secret-copy.key"
    copy.write_bytes(keys.load_master(master).secret)  # the same key, raw
    monkeypatch.setenv(SECRET_FILE_ENV, str(copy))
    with pytest.raises(MasterKeyError, match="code-hash secret"):
        create_hosted_app(_settings(tmp_path), MemoryMailer())


def test_a_missing_accounts_database_with_user_folders_stops_the_app(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    folder = _folder(h, ALICE)
    (h.data / FILENAME).rename(tmp_path / "lost-accounts.db")
    for suffix in ("-wal", "-shm"):
        (h.data / f"{FILENAME}{suffix}").unlink(missing_ok=True)
    with pytest.raises(HostedStateError, match="restore"):
        create_hosted_app(_settings(tmp_path), MemoryMailer())
    assert not (h.data / FILENAME).exists()  # no new, empty one was made
    assert folder.exists()


def test_the_app_does_not_start_with_another_master_key(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    other = master_file(tmp_path, "other.key")
    with pytest.raises(KeyStateError, match="another master key"):
        create_hosted_app(_settings(tmp_path, master_key=other), MemoryMailer())


def test_the_hosted_command_explains_a_missing_master_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(tmp_path / "local"))
    monkeypatch.delenv("MICHELITO_MASTER_KEY_FILE", raising=False)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(cli, "STATIC_DIR", static)
    data = str(tmp_path / "hosted")
    code = cli.main(["hosted", "--data", data, "--mailer", "outbox", "--port", "8661"])
    assert code == 2
    assert "master key" in capsys.readouterr().err


def test_no_key_appears_in_reprs_logs_or_responses(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    h = hosted(tmp_path)
    capfd.readouterr()
    client = h.sign_in(ALICE)
    _write_note(h, ALICE)
    master = keys.load_master(master_file(tmp_path), h.data)
    store = h.service.store
    account = store.account_by_email(ALICE)
    assert account
    workspace = h.service.workspace(store.sessions_of(account.id)[0])
    assert workspace.key
    secrets_ = {master.secret.hex(), workspace.key.hex(), master.secret.hex().upper()}
    texts = [repr(master), repr(workspace), repr(store.data_key(account.id)), repr(h.service)]
    for path in ("/api/auth/me", "/api/categories", "/api/mode", "/api/accounts", "/api/nope"):
        texts.append(client.get(path).text)
    with pytest.raises(sqlite3.DatabaseError):  # a wrong key: SQLCipher writes nothing itself
        db.connect(_folder(h, ALICE) / auth.DATABASE, keys.new_data_key())
    texts += [record.getMessage() for record in caplog.records]
    out, err = capfd.readouterr()
    assert err == ""
    texts += [out, err]
    for text in texts:
        for secret in secrets_:
            assert secret not in text
    assert master.secret.hex() not in str(keys.MasterKeyError("x"))


# Placeholders of batch 1.


def test_batch_one_placeholders_are_encrypted_at_start_up(tmp_path: Path) -> None:
    """An account made before this batch: a plain database and no data key."""
    data = tmp_path / "hosted"
    data.mkdir(mode=0o700)
    store = Store(data / FILENAME)
    folder = "c" * 32
    account = store.create_account(ALICE, folder, 1_800_000_000, None)
    place = data / "users" / folder
    place.mkdir(parents=True, mode=0o700)
    with closing(db.connect(place / auth.DATABASE)) as conn, conn:
        conn.execute("CREATE TABLE marker (text TEXT)")
        conn.execute("INSERT INTO marker VALUES (?)", (MARKER,))
    assert encrypted.is_plain(place / auth.DATABASE)
    h = hosted(tmp_path)  # starts the app on that folder
    assert not encrypted.is_plain(place / auth.DATABASE)
    assert MARKER.encode() not in (place / auth.DATABASE).read_bytes()
    stored = store.data_key(account.id)
    assert stored is not None
    master = keys.load_master(master_file(tmp_path), data)
    data_key = keys.unwrap(master, stored.wrapped, account.id, folder)
    with closing(db.connect(place / auth.DATABASE, data_key)) as conn:
        assert conn.execute("SELECT text FROM marker").fetchone()[0] == MARKER
    assert h.service.seal_placeholders() == 0  # idempotent
    assert _names(h, ALICE)  # and the person signs in to it as usual


def test_a_placeholder_interrupted_after_its_key_was_stored_is_finished(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    store = h.service.store
    account = store.account_by_email(ALICE)
    assert account
    place = _folder(h, ALICE)
    (place / auth.DATABASE).unlink()
    with closing(db.connect(place / auth.DATABASE)) as conn, conn:  # plain again, key kept
        conn.execute("CREATE TABLE marker (text TEXT)")
        conn.execute("INSERT INTO marker VALUES (?)", (MARKER,))
    (place / f"{auth.DATABASE}{auth.SEALING}").write_bytes(b"half written")
    assert h.service.seal_placeholders() == 1
    assert not (place / f"{auth.DATABASE}{auth.SEALING}").exists()
    with closing(db.connect(place / auth.DATABASE, h.service._data_key(account))) as conn:
        assert conn.execute("SELECT text FROM marker").fetchone()[0] == MARKER


# Deletion: crypto-shredding.


def _fresh_delete(h: Hosted, email: str) -> int:
    return h.sign_in(email).delete("/api/account", headers=WRITE).status_code


def test_deleting_an_account_destroys_its_key_then_its_files(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    _write_note(h, ALICE)
    _write_note(h, BOB)
    store = h.service.store
    alice = store.account_by_email(ALICE)
    assert alice
    alice_folder = _folder(h, ALICE)
    bob_files = {p: p.read_bytes() for p in _folder(h, BOB).rglob("*") if p.is_file()}
    assert _fresh_delete(h, ALICE) == 204
    assert store.account_by_email(ALICE) is None
    assert store.data_key(alice.id) is None
    assert not alice_folder.exists()
    with closing(sqlite3.connect(h.data / FILENAME)) as conn:
        for table in ("sessions", "known_devices", "data_keys"):
            count = conn.execute(f"SELECT count(*) FROM {table} WHERE account_id = ?", (alice.id,))
            assert count.fetchone()[0] == 0, table
        for table in ("login_codes", "invitations"):
            count = conn.execute(f"SELECT count(*) FROM {table} WHERE email = ?", (ALICE,))
            assert count.fetchone()[0] == 0, table
    assert {p: p.read_bytes() for p in bob_files} == bob_files  # Bob untouched
    assert any(MARKER in name for name in _names(h, BOB))


def test_no_trace_of_a_deleted_key_or_email_stays_in_the_accounts_folder(tmp_path: Path) -> None:
    """Deleted rows are zeroed (`secure_delete`) and the WAL is truncated, so neither the wrapped
    key nor the email survive in free pages, the WAL or any other file."""
    h = hosted(tmp_path)
    _write_note(h, ALICE)
    _write_note(h, BOB)
    store = h.service.store
    alice = store.account_by_email(ALICE)
    assert alice
    stored = store.data_key(alice.id)
    assert stored is not None
    needles = {"wrapped key": stored.wrapped, "email": ALICE.encode()}
    files = [p for p in h.data.rglob("*") if p.is_file()]
    assert any(stored.wrapped in p.read_bytes() for p in files)  # the check can see them
    assert _fresh_delete(h, ALICE) == 204
    for path in (p for p in h.data.rglob("*") if p.is_file()):
        content = path.read_bytes()
        for what, needle in needles.items():
            assert needle not in content, f"{what} in {path.name}"
    assert BOB.encode() in (h.data / FILENAME).read_bytes()  # Bob's account is still there


def test_a_backup_taken_after_the_deletion_cannot_open_the_old_database(tmp_path: Path) -> None:
    """The real claim: with an `accounts.db` taken after the deletion, a copy of the database
    made before it cannot be opened, even with the master key."""
    h = hosted(tmp_path)
    _write_note(h, ALICE)
    old_files = tmp_path / "backup-before"
    shutil.copytree(_folder(h, ALICE), old_files)
    account = h.service.store.account_by_email(ALICE)
    assert account
    assert _fresh_delete(h, ALICE) == 204
    later = tmp_path / "backup-after"
    later.mkdir()
    shutil.copy2(h.data / FILENAME, later / FILENAME)  # a checkpointed file: complete by itself
    copy = Store(later / FILENAME)
    assert copy.data_key(account.id) is None
    assert copy.account_by_email(ALICE) is None
    master = keys.load_master(master_file(tmp_path), h.data)
    # Every key that backup holds opens only its own account, never the deleted database.
    for stored in copy.data_keys():
        data_key = keys.unwrap(master, stored.wrapped, stored.account_id, stored.folder)
        with pytest.raises(sqlite3.DatabaseError):
            db.connect(old_files / auth.DATABASE, data_key)


def test_a_failed_file_removal_still_deletes_the_account_and_the_folder_is_cleaned_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = hosted(tmp_path)
    _write_note(h, ALICE)
    h.sign_in(BOB)
    folder = _folder(h, ALICE)

    def broken(path: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(auth.shutil, "rmtree", broken)
    assert _fresh_delete(h, ALICE) == 204  # the key is gone: the account is gone
    monkeypatch.undo()
    assert h.service.store.account_by_email(ALICE) is None
    assert folder.exists()  # tombstoned, unreadable without its key
    assert h.service.store.deleted_folders() == [folder.name]
    untombstoned = h.data / "users" / ("e" * 32)  # looks like ours, but no tombstone
    untombstoned.mkdir()
    stranger = h.data / "users" / "not-a-folder-of-ours"
    stranger.mkdir()
    hosted(tmp_path)  # the next start removes the tombstoned folder, and only it
    assert not folder.exists()
    assert h.service.store.deleted_folders() == []
    assert untombstoned.exists() and stranger.exists()
    assert _folder(h, BOB).exists()


def test_a_replaced_accounts_database_never_wipes_user_folders(tmp_path: Path) -> None:
    """An `accounts.db` that knows none of the folders (restored from elsewhere, or empty)
    leaves every folder without a tombstone alone."""
    h = hosted(tmp_path)
    _write_note(h, ALICE)
    folder = _folder(h, ALICE)
    other = tmp_path / "other"
    other.mkdir()
    hosted(other).sign_in("carol@example.com")  # a different, valid accounts database
    for suffix in ("", "-wal", "-shm"):
        (h.data / f"{FILENAME}{suffix}").unlink(missing_ok=True)
    shutil.copy2(other / "hosted" / FILENAME, h.data / FILENAME)
    with pytest.raises(KeyStateError):  # its keys are not under this master… or
        hosted(tmp_path)
    assert folder.exists()
    hosted(tmp_path, master_key=master_file(other))  # …with its own master key it starts
    assert folder.exists()  # and still removes nothing it did not delete itself


def test_a_lost_folder_is_made_again_on_the_first_request(tmp_path: Path) -> None:
    """A crash between the account's commit and its folder: the key exists, so the first
    request makes an empty encrypted database instead of failing."""
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    folder = _folder(h, ALICE)
    shutil.rmtree(folder)
    assert client.get("/api/categories").status_code == 200
    assert (folder / auth.DATABASE).is_file()
    assert not encrypted.is_plain(folder / auth.DATABASE)
    assert folder.stat().st_mode & 0o777 == 0o700


def test_a_crash_between_key_and_files_leaves_no_readable_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The key and the account go in one transaction, before any file is touched."""
    h = hosted(tmp_path)
    _write_note(h, ALICE)
    store = h.service.store
    account = store.account_by_email(ALICE)
    assert account
    calls: list[str] = []
    real = store.delete_account

    def recording(account_id: int, now: int):  # noqa: ANN202
        calls.append("key")
        return real(account_id, now)

    def crash(path: Path, *args: object, **kwargs: object) -> None:
        calls.append("files")
        raise SystemExit("power cut")

    monkeypatch.setattr(store, "delete_account", recording)
    monkeypatch.setattr(auth.shutil, "rmtree", crash)
    session = store.sessions_of(account.id)[0]
    with pytest.raises(SystemExit):
        h.service.delete_account(session)
    assert calls == ["key", "files"]
    assert store.account_by_email(ALICE) is None and store.data_key(account.id) is None


def test_deleting_needs_a_fresh_step_up(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.sign_in(ALICE)
    h.clock.advance(11 * 60)
    assert client.delete("/api/account", headers=WRITE).status_code == 403
    assert h.service.store.account_by_email(ALICE) is not None
    assert _folder(h, ALICE).exists()


# Rotation.


def _opened(store: Store, master: MasterKey) -> dict[int, bytes]:
    return {
        k.account_id: keys.unwrap(master, k.wrapped, k.account_id, k.folder)
        for k in store.data_keys()
    }


def test_rotation_rewraps_every_key_resumably_and_data_stays_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = hosted(tmp_path)
    people = [f"person{n}@example.com" for n in range(4)]
    for email in people:
        _write_note(h, email)
    store = h.service.store
    old = keys.load_master(master_file(tmp_path), h.data)
    new_path = master_file(tmp_path, "new.key")
    new = keys.load_master(new_path, h.data)
    before = _opened(store, old)
    files = {p: p.read_bytes() for p in (h.data / "users").rglob("*") if p.is_file()}
    real = store.rewrap
    done: list[int] = []

    def interrupted(account_id: int, *args: object) -> bool:
        if len(done) == 2:
            raise KeyboardInterrupt  # stopped half way
        done.append(account_id)
        return real(account_id, *args)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "rewrap", interrupted)
    with pytest.raises(KeyboardInterrupt):
        rotation.rotate(store, old, new)
    monkeypatch.undo()
    assert sorted(k.master_id for k in store.data_keys()) == sorted([new.id] * 2 + [old.id] * 2)
    with pytest.raises(KeyStateError):  # half rotated: the server refuses to start
        create_hosted_app(_settings(tmp_path), MemoryMailer())
    result = rotation.rotate(store, old, new)  # resumed
    assert (result.rewrapped, result.already) == (2, 2)
    assert {k.master_id for k in store.data_keys()} == {new.id}
    after = _opened(store, new)
    assert after == before  # the data keys did not change…
    assert {p: p.read_bytes() for p in files} == files  # …nor did any file
    for stored in store.data_keys():
        with pytest.raises(keys.UnwrapError):
            keys.unwrap(old, stored.wrapped, stored.account_id, stored.folder)
    h2 = hosted(tmp_path, master_key=new_path)
    for email in people:
        assert _label(email) in _names(h2, email)
    with pytest.raises(rotation.RotationError):
        rotation.rotate(store, new, new)


def test_rotation_refuses_keys_under_an_unknown_master(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    with pytest.raises(rotation.RotationError, match="neither"):
        rotation.rotate(h.service.store, _master(), _master())


def _wrapped(store: Store) -> list[tuple[int, bytes, str]]:
    return [(k.account_id, k.wrapped, k.master_id) for k in store.data_keys()]


def test_rotation_refuses_before_any_write_when_one_key_is_foreign(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    for email in (ALICE, BOB, "carol@example.com"):
        h.sign_in(email)
    store = h.service.store
    old = keys.load_master(master_file(tmp_path), h.data)
    stranger = _master()
    last = store.data_keys()[-1]
    with closing(sqlite3.connect(h.data / FILENAME)) as conn, conn:  # the last key: foreign
        conn.execute(
            "UPDATE data_keys SET master_id = ? WHERE account_id = ?",
            (stranger.id, last.account_id),
        )
    before = _wrapped(store)
    with pytest.raises(rotation.RotationError, match="neither"):
        rotation.rotate(store, old, _master())
    assert _wrapped(store) == before  # not even the first accounts were re-wrapped


def test_rotation_refuses_before_any_write_when_one_key_does_not_open(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    for email in (ALICE, BOB, "carol@example.com"):
        h.sign_in(email)
    store = h.service.store
    old = keys.load_master(master_file(tmp_path), h.data)
    last = store.data_keys()[-1]
    with closing(sqlite3.connect(h.data / FILENAME)) as conn, conn:  # altered bytes
        conn.execute(
            "UPDATE data_keys SET wrapped = ? WHERE account_id = ?",
            (last.wrapped[:-1] + bytes([last.wrapped[-1] ^ 1]), last.account_id),
        )
    before = _wrapped(store)
    with pytest.raises(rotation.RotationError, match="does not open"):
        rotation.rotate(store, old, _master())
    assert _wrapped(store) == before


def test_no_old_wrapping_stays_in_the_accounts_folder_after_rotation(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    for email in (ALICE, BOB):
        h.sign_in(email)
    store = h.service.store
    old_wrappings = [k.wrapped for k in store.data_keys()]
    old = keys.load_master(master_file(tmp_path), h.data)
    rotation.rotate(store, old, keys.load_master(master_file(tmp_path, "new.key"), h.data))
    for path in (p for p in h.data.rglob("*") if p.is_file()):
        content = path.read_bytes()
        for wrapped in old_wrappings:
            assert wrapped not in content, path.name


def test_the_folder_lock_admits_one_process(tmp_path: Path) -> None:
    with server_lock(tmp_path), pytest.raises(FolderBusyError), server_lock(tmp_path):
        pass  # pragma: no cover - the second lock is refused
    with server_lock(tmp_path):  # released: free again
        pass


def test_rotation_is_refused_while_the_server_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(tmp_path / "local"))
    monkeypatch.setenv("MICHELITO_MASTER_KEY_FILE", str(master_file(tmp_path)))
    new_path = master_file(tmp_path, "new.key")
    before = _wrapped(h.service.store)
    args = ["rotate-master-key", "--new", str(new_path), "--data", str(h.data)]
    with server_lock(h.data):  # what `michelito hosted` holds while it serves
        assert cli.main(args) == 1
    assert "stop the server" in capsys.readouterr().err
    assert _wrapped(h.service.store) == before


def test_the_rotate_command_explains_a_key_that_does_not_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    h = hosted(tmp_path)
    h.sign_in(ALICE)
    account = h.service.store.account_by_email(ALICE)
    assert account
    with closing(sqlite3.connect(h.data / FILENAME)) as conn, conn:
        conn.execute(
            "UPDATE data_keys SET wrapped = ? WHERE account_id = ?", (b"\x01" * 60, account.id)
        )
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(tmp_path / "local"))
    monkeypatch.setenv("MICHELITO_MASTER_KEY_FILE", str(master_file(tmp_path)))
    args = [
        "rotate-master-key",
        "--new",
        str(master_file(tmp_path, "new.key")),
        "--data",
        str(h.data),
    ]
    assert cli.main(args) == 1
    assert "does not open" in capsys.readouterr().err


def test_the_rotate_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    h = hosted(tmp_path)
    _write_note(h, ALICE)
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(tmp_path / "local"))
    monkeypatch.setenv("MICHELITO_MASTER_KEY_FILE", str(master_file(tmp_path)))
    new_path = master_file(tmp_path, "new.key")
    args = ["rotate-master-key", "--new", str(new_path), "--data", str(h.data)]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "Re-wrapped 1" in out
    assert cli.main(args) == 0  # again: nothing left to do
    assert "Re-wrapped 0" in capsys.readouterr().out
    for secret in (
        keys.load_master(new_path, h.data).secret.hex(),
        keys.load_master(master_file(tmp_path), h.data).secret.hex(),
    ):
        assert secret not in out
    h2 = hosted(tmp_path, master_key=new_path)
    assert _label(ALICE) in _names(h2, ALICE)
    monkeypatch.setenv("MICHELITO_MASTER_KEY_FILE", str(tmp_path / "missing.key"))
    assert cli.main(args) == 1
    assert "cannot read" in capsys.readouterr().err
