"""Backups of the hosted folder to an S3 bucket (a fake one on loopback) and a local folder, and
`restore` onto an empty folder: the upload set (never the master key nor the code-hash secret),
checksums, rotation and the round trip. Synthetic data and throwaway keys only."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from michelito import db, holders
from michelito.hosted import auth, backup, keys, restore, s3
from michelito.hosted.keys import load_master
from michelito.hosted.store import FILENAME, Store
from tests.fake_s3 import ACCESS, SECRET, fake_s3
from tests.hosted_helpers import WRITE, hosted, master_file

MARKER = "ZEBRA-BACKUP-MARKER-4410"


# Signature Version 4 against AWS's published examples (S3 docs, "Signature Calculations for the
# Authorization Header"; example credentials, not real ones).
AWS_EXAMPLE = s3.Credentials("AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
AWS_HOST = "examplebucket.s3.amazonaws.com"
AWS_DATE = "20130524T000000Z"


def test_sigv4_matches_the_aws_get_object_example() -> None:
    headers = {
        "host": AWS_HOST,
        "range": "bytes=0-9",
        "x-amz-content-sha256": s3.EMPTY_SHA256,
        "x-amz-date": AWS_DATE,
    }
    found = s3.authorization(
        AWS_EXAMPLE, "us-east-1", "GET", "/test.txt", {}, headers, s3.EMPTY_SHA256, AWS_DATE
    )
    assert found.endswith(
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in found


def test_sigv4_matches_the_aws_list_objects_example() -> None:
    headers = {"host": AWS_HOST, "x-amz-content-sha256": s3.EMPTY_SHA256, "x-amz-date": AWS_DATE}
    query = {"max-keys": "2", "prefix": "J"}
    found = s3.authorization(
        AWS_EXAMPLE, "us-east-1", "GET", "/", query, headers, s3.EMPTY_SHA256, AWS_DATE
    )
    assert found.endswith(
        "Signature=34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7"
    )


def test_the_client_refuses_plain_http_beyond_loopback() -> None:
    bucket = s3.Bucket("http://r2.example.com", "b", s3.Credentials("a", "b"))
    with pytest.raises(s3.S3Error, match="https"):
        s3.Client(bucket)


def test_credentials_never_appear_in_repr_or_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(s3.ENDPOINT_ENV, "https://r2.example.com")
    monkeypatch.setenv(s3.BUCKET_ENV, "b")
    monkeypatch.setenv(s3.ACCESS_KEY_ENV, ACCESS)
    monkeypatch.setenv(s3.SECRET_KEY_ENV, SECRET)
    bucket = s3.bucket_from_environment()
    for text in (repr(bucket), repr(s3.Client(bucket)), repr(bucket.credentials)):
        assert ACCESS not in text and SECRET not in text
    monkeypatch.delenv(s3.SECRET_KEY_ENV)
    with pytest.raises(s3.S3Error) as error:
        s3.bucket_from_environment()
    assert SECRET not in str(error.value) and ACCESS not in str(error.value)


def test_credentials_can_come_from_secret_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "id").write_text(ACCESS + "\n")
    (tmp_path / "key").write_text(SECRET + "\n")
    monkeypatch.setenv(s3.ENDPOINT_ENV, "https://r2.example.com")
    monkeypatch.setenv(s3.BUCKET_ENV, "b")
    monkeypatch.setenv(f"{s3.ACCESS_KEY_ENV}_FILE", str(tmp_path / "id"))
    monkeypatch.setenv(f"{s3.SECRET_KEY_ENV}_FILE", str(tmp_path / "key"))
    bucket = s3.bucket_from_environment()
    assert bucket.credentials == s3.Credentials(ACCESS, SECRET)


def test_the_fake_rejects_a_wrong_secret() -> None:
    with fake_s3() as fake:
        bucket = s3.Bucket(fake.endpoint, "michelito-test", s3.Credentials(ACCESS, "wrong"))
        with pytest.raises(s3.S3Error, match="403 SignatureDoesNotMatch"):
            s3.Client(bucket).put("x", b"1")


def test_listing_follows_continuation_pages() -> None:
    with fake_s3() as fake:
        fake.page_size = 2
        client = s3.Client(fake.bucket)
        for n in range(5):
            client.put(f"p/{n}", b"x")
        assert client.list("p/") == [f"p/{n}" for n in range(5)]


# A hosted folder with two accounts holding synthetic data.


def _name(email: str) -> str:
    return f"{MARKER}-{email.split('@')[0]}"


def _two_accounts(tmp_path: Path):  # noqa: ANN202
    env = hosted(tmp_path)
    for email in ("alice@example.com", "bob@example.com"):
        made = env.sign_in(email).post(
            "/api/categories", json={"name": _name(email), "kind": "expense"}, headers=WRITE
        )
        assert made.status_code == 201, made.text
    service = env.service
    alice = service.store.account_by_email("alice@example.com")
    master = load_master(master_file(tmp_path), env.data)
    stored = service.store.data_key(alice.id)
    key = keys.unwrap(master, stored.wrapped, alice.id, alice.folder)
    with (
        closing(db.connect(env.data / auth.USERS / alice.folder / auth.DATABASE, key)) as conn,
        conn,
    ):
        holders.write(conn, "ALICE SYNTHETIC\n")
    (env.data / "outbox").mkdir(exist_ok=True)
    (env.data / "outbox" / "x.json").write_text("{}")
    return env, master


def _all_bytes(objects: dict[str, bytes]) -> bytes:
    return b"".join(objects.values())


def test_the_upload_set_is_the_databases_and_never_a_key(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    folders = sorted(env.service.store.folders())
    with fake_s3() as fake:
        done = backup.run_backup(env.data, master, s3.Client(fake.bucket), "2026-11-19")
        uploaded = set(fake.objects)
        everything = _all_bytes(fake.objects)
    expected = {
        "backups/2026-11-19/accounts.db.sealed",
        "backups/2026-11-19/manifest.json",
        *(f"backups/2026-11-19/users/{f}/michelito.db" for f in folders),
    }
    assert uploaded == expected
    assert {e.name for e in done.entries} | {"manifest.json"} == {
        k.split("/", 2)[2] for k in expected
    }
    secret = (env.data / "secret.key").read_bytes()
    for forbidden in (
        master.secret,
        master.secret.hex().encode(),
        secret,
        MARKER.encode(),
        b"alice@example.com",
        b"ALICE SYNTHETIC",
        b"SQLite format 3",
    ):
        assert forbidden not in everything
    assert not list(env.data.glob(f"{backup.STAGING}*"))  # the temporary snapshots are gone


def test_the_manifest_has_checksums_and_no_personal_data(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    with fake_s3() as fake:
        backup.run_backup(env.data, master, s3.Client(fake.bucket), "2026-11-19")
        manifest = json.loads(fake.objects["backups/2026-11-19/manifest.json"])
        objects = dict(fake.objects)
    assert manifest["master_id"] == master.id
    for entry in manifest["files"]:
        body = objects[f"backups/2026-11-19/{entry['name']}"]
        assert entry["size"] == len(body)
        assert entry["sha256"] == backup.sha256(body)
    assert b"example.com" not in json.dumps(manifest).encode()
    # Every PUT carried Content-MD5 and a signed payload hash.
    puts = [h for h in fake.headers_seen if "content-md5" in h]
    assert len(puts) == len(objects)


def test_a_backup_that_comes_back_different_fails(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    with fake_s3() as fake:
        fake.corrupt_reads = True
        with pytest.raises(backup.BackupError, match="came back different"):
            backup.run_backup(env.data, master, s3.Client(fake.bucket), "2026-11-19")
        assert not any(k.endswith("manifest.json") for k in fake.objects)


def test_an_upload_error_fails_without_leaking_credentials(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    with fake_s3() as fake:
        fake.fail_puts = True
        with pytest.raises(s3.S3Error) as error:
            backup.run_backup(env.data, master, s3.Client(fake.bucket), "2026-11-19")
    assert "500" in str(error.value)
    assert SECRET not in str(error.value) and ACCESS not in str(error.value)


def test_rotation_deletes_backups_older_than_thirty_days(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    with fake_s3() as fake:
        client = s3.Client(fake.bucket)
        for label in ("2026-10-01", "2026-10-19", "2026-10-20", "2026-11-19"):
            backup.run_backup(env.data, master, client, label)
        fake.objects["backups/2026-09-01/users/x/michelito.db"] = b"incomplete"
        fake.objects["unrelated/2020-01-01/file"] = b"kept"
        deleted = backup.rotate_by_age(client, date(2026, 11, 19))
        assert deleted == ("2026-09-01", "2026-10-01", "2026-10-19")
        assert backup.labels(client) == ["2026-10-20", "2026-11-19"]
        assert "unrelated/2020-01-01/file" in fake.objects


def test_a_second_backup_on_the_same_day_gets_its_own_label(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    noon = datetime(2026, 11, 24, 11, 53, 35, tzinfo=UTC).timestamp()
    with fake_s3() as fake:
        fake.object_lock = True  # the bucket refuses to overwrite: the label must be new
        client = s3.Client(fake.bucket)
        assert backup.free_label(client, "2026-11-24", lambda: noon) == "2026-11-24"
        backup.run_backup(env.data, master, client, "2026-11-24")
        second = backup.free_label(client, "2026-11-24", lambda: noon)
        assert second == "2026-11-24T115335Z"
        backup.run_backup(env.data, master, client, second)
        assert backup.labels(client) == ["2026-11-24", "2026-11-24T115335Z"]
        # Even an incomplete backup (no manifest) holds its label: its objects are locked too.
        fake.objects["backups/2026-11-25/accounts.db.sealed"] = b"partial"
        assert backup.free_label(client, "2026-11-25", lambda: noon) == "2026-11-25T115335Z"


def test_rotation_also_deletes_the_extra_backups_of_an_old_day(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    with fake_s3() as fake:
        client = s3.Client(fake.bucket)
        for label in ("2026-10-01", "2026-10-01T115335Z", "2026-11-19", "2026-11-19T080000Z"):
            backup.run_backup(env.data, master, client, label)
        deleted = backup.rotate_by_age(client, date(2026, 11, 19))
        assert deleted == ("2026-10-01", "2026-10-01T115335Z")
        assert backup.labels(client) == ["2026-11-19", "2026-11-19T080000Z"]


def test_a_local_folder_keeps_the_newest_backups(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    target = backup.FolderTarget(tmp_path / "deploy-backups")
    for n in range(4):
        backup.run_backup(env.data, master, target, f"2026111{n}T000000Z-abc", prefix="")
    assert backup.rotate_by_count(target, 2) == ("20261110T000000Z-abc", "20261111T000000Z-abc")
    assert backup.labels(target, "") == ["20261112T000000Z-abc", "20261113T000000Z-abc"]
    modes = {p.stat().st_mode & 0o777 for p in (tmp_path / "deploy-backups").rglob("*")}
    assert modes <= {0o600, 0o700}


# Restore.


def _restore_and_check(target: backup.Target, prefix: str, master, env, out: Path) -> None:  # noqa: ANN001
    done = restore.restore(target, master, out, "latest", prefix)
    assert done.accounts == 2
    store = Store(out / FILENAME)
    for email in ("alice@example.com", "bob@example.com"):
        account = store.account_by_email(email)
        stored = store.data_key(account.id)
        key = keys.unwrap(master, stored.wrapped, account.id, account.folder)
        with closing(db.connect(out / auth.USERS / account.folder / auth.DATABASE, key)) as conn:
            names = {r[0] for r in conn.execute("SELECT name FROM categories")}
            content = holders.read(conn)
        assert _name(email) in names
        assert content == ("ALICE SYNTHETIC\n" if email.startswith("alice") else "")
    assert not (out / "secret.key").exists()
    assert sorted(p.name for p in out.parent.iterdir() if ".restoring-" in p.name) == []


def test_restore_round_trip_from_the_fake_bucket(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    with fake_s3() as fake:
        client = s3.Client(fake.bucket)
        backup.run_backup(env.data, master, client, "2026-11-18")
        backup.run_backup(env.data, master, client, "2026-11-19")
        _restore_and_check(client, backup.R2_PREFIX, master, env, tmp_path / "clean")
        assert ("GET", "backups/2026-11-19/manifest.json") in fake.requests


def test_restore_round_trip_from_a_local_folder(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    target = backup.FolderTarget(tmp_path / "deploy-backups")
    backup.run_backup(env.data, master, target, "20261119T000000Z-abc", prefix="")
    _restore_and_check(target, "", master, env, tmp_path / "clean")


def test_the_restored_folder_serves_the_accounts(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    target = backup.FolderTarget(tmp_path / "b")
    backup.run_backup(env.data, master, target, "x1", prefix="")
    restore.restore(target, master, tmp_path / "clean", "x1", "")
    again = hosted(tmp_path, data=tmp_path / "clean")
    client = again.sign_in("alice@example.com")
    names = {c["name"] for c in client.get("/api/categories").json()}
    assert _name("alice@example.com") in names


def test_restore_refuses_a_folder_that_is_not_empty(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    target = backup.FolderTarget(tmp_path / "b")
    backup.run_backup(env.data, master, target, "x1", prefix="")
    with pytest.raises(restore.RestoreError, match="not empty"):
        restore.restore(target, master, env.data, "x1", "")


def test_restore_refuses_another_master_key(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    target = backup.FolderTarget(tmp_path / "b")
    backup.run_backup(env.data, master, target, "x1", prefix="")
    other = load_master(master_file(tmp_path, "other.key"))
    with pytest.raises(restore.RestoreError, match="another master key"):
        restore.restore(target, other, tmp_path / "clean", "x1", "")


def test_restore_refuses_a_damaged_object(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    target = backup.FolderTarget(tmp_path / "b")
    backup.run_backup(env.data, master, target, "x1", prefix="")
    victim = next((tmp_path / "b" / "x1" / "users").rglob(auth.DATABASE))
    content = bytearray(victim.read_bytes())
    content[5000] ^= 1
    victim.write_bytes(bytes(content))
    with pytest.raises(restore.RestoreError, match="checksum"):
        restore.restore(target, master, tmp_path / "clean", "x1", "")


def test_restore_refuses_a_manifest_naming_other_paths(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    target = backup.FolderTarget(tmp_path / "b")
    backup.run_backup(env.data, master, target, "x1", prefix="")
    manifest_path = tmp_path / "b" / "x1" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"].append({"name": "../../etc/evil", "size": 1, "sha256": "0"})
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(restore.RestoreError, match="not authentic"):
        restore.restore(target, master, tmp_path / "clean", "x1", "")
    # Even with a valid MAC (only possible with the master key) no other path is written.
    manifest["mac"] = backup.manifest_mac(master, manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(restore.RestoreError, match="unexpected file"):
        restore.restore(target, master, tmp_path / "clean", "x1", "")
    assert not (tmp_path / "clean").exists()


def test_restore_without_a_complete_backup(tmp_path: Path) -> None:
    master = load_master(master_file(tmp_path))
    with pytest.raises(restore.RestoreError, match="no complete backup"):
        restore.restore(
            backup.FolderTarget(tmp_path / "none"), master, tmp_path / "c", "latest", ""
        )


# End-to-end integrity: the manifest's MAC, the label in the seals, the temporary folder.


def _two_backups(tmp_path: Path):  # noqa: ANN202
    env, master = _two_accounts(tmp_path)
    root = tmp_path / "b"
    target = backup.FolderTarget(root)
    backup.run_backup(env.data, master, target, "x1", prefix="")
    backup.run_backup(env.data, master, target, "x2", prefix="")
    return env, master, target, root


def _clean_and_untouched(tmp_path: Path) -> None:
    assert not (tmp_path / "clean").exists()
    assert not [p for p in tmp_path.iterdir() if ".restoring-" in p.name]


def test_an_edited_manifest_is_refused_before_any_download(tmp_path: Path) -> None:
    _, master, target, root = _two_backups(tmp_path)
    path = root / "x2" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["created_at"] += 1
    path.write_text(json.dumps(manifest))
    seen: list[str] = []
    real_get = target.get

    class Spy(backup.FolderTarget):
        def get(self, key: str) -> bytes:
            seen.append(key)
            return real_get(key)

    with pytest.raises(restore.RestoreError, match="not authentic"):
        restore.restore(Spy(root), master, tmp_path / "clean", "x2", "")
    assert seen == ["x2/manifest.json"]
    _clean_and_untouched(tmp_path)


def test_an_object_swapped_from_another_backup_is_refused(tmp_path: Path) -> None:
    _, master, _, root = _two_backups(tmp_path)
    victim = next((root / "x2" / "users").rglob(auth.DATABASE))
    victim.write_bytes((root / "x1" / victim.relative_to(root / "x2")).read_bytes())
    with pytest.raises(restore.RestoreError, match="checksum"):
        restore.restore(backup.FolderTarget(root), master, tmp_path / "clean", "x2", "")
    _clean_and_untouched(tmp_path)


def test_a_sealed_object_does_not_open_under_another_label(tmp_path: Path) -> None:
    """Even a manifest re-signed with the master key cannot move x1's sealed accounts database
    into x2: the label is in the seal's associated data."""
    _, master, _, root = _two_backups(tmp_path)
    moved = (root / "x1" / backup.ACCOUNTS).read_bytes()
    (root / "x2" / backup.ACCOUNTS).write_bytes(moved)
    path = root / "x2" / "manifest.json"
    manifest = json.loads(path.read_text())
    for entry in manifest["files"]:
        if entry["name"] == backup.ACCOUNTS:
            entry["size"], entry["sha256"] = len(moved), backup.sha256(moved)
    manifest["mac"] = backup.manifest_mac(master, manifest)
    path.write_text(json.dumps(manifest))
    with pytest.raises(backup.BackupError, match="label"):
        restore.restore(backup.FolderTarget(root), master, tmp_path / "clean", "x2", "")
    _clean_and_untouched(tmp_path)


def test_a_manifest_moved_to_another_label_is_refused(tmp_path: Path) -> None:
    _, master, _, root = _two_backups(tmp_path)
    (root / "x2" / "manifest.json").write_bytes((root / "x1" / "manifest.json").read_bytes())
    with pytest.raises(restore.RestoreError, match="another backup"):
        restore.restore(backup.FolderTarget(root), master, tmp_path / "clean", "x2", "")
    _clean_and_untouched(tmp_path)


def test_restoring_an_older_backup_is_flagged(tmp_path: Path) -> None:
    _, master, target, _ = _two_backups(tmp_path)
    done = restore.restore(target, master, tmp_path / "clean", "x1", "")
    assert done.older and done.newest == "x2"
    again = restore.restore(target, master, tmp_path / "clean2", "latest", "")
    assert not again.older


def test_restore_onto_an_existing_empty_folder_replaces_it(tmp_path: Path) -> None:
    _, master, target, _ = _two_backups(tmp_path)
    (tmp_path / "clean").mkdir()
    restore.restore(target, master, tmp_path / "clean", "latest", "")
    assert (tmp_path / "clean" / FILENAME).is_file()
    assert (tmp_path / "clean").stat().st_mode & 0o777 == 0o700


def test_the_s3_client_never_follows_a_redirect() -> None:
    with fake_s3() as fake:
        fake.redirect_to = "http://127.0.0.1:9/elsewhere"
        client = s3.Client(fake.bucket)
        for call in (lambda: client.get("k"), lambda: client.put("k", b"x")):
            with pytest.raises(s3.S3Error, match="redirected"):
                call()
        assert len(fake.requests) == 2  # nothing reached the other address


def test_holders_files_move_into_the_encrypted_database_at_start(tmp_path: Path) -> None:
    env, master = _two_accounts(tmp_path)
    bob = env.service.store.account_by_email("bob@example.com")
    path = env.data / auth.USERS / bob.folder / auth.HOLDERS
    path.write_text("BOB SYNTHETIC\n")
    hosted(tmp_path)  # the next start
    assert not path.exists()
    stored = env.service.store.data_key(bob.id)
    key = keys.unwrap(master, stored.wrapped, bob.id, bob.folder)
    with closing(db.connect(env.data / auth.USERS / bob.folder / auth.DATABASE, key)) as conn:
        assert holders.read(conn) == "BOB SYNTHETIC\n"
