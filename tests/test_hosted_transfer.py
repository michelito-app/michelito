"""`export-account` and `import-account`: a consistent export without secrets, and an import that
encrypts, migrates, verifies and removes the plaintext; `verify-import` figures equal on both
sides. Synthetic data (the demo generator and the schema fixtures) and throwaway keys only."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from michelito import db, encrypted, holders
from michelito.analysis.transfers import parse_holders
from michelito.demo import generate
from michelito.hosted import auth, figures, keys, transfer
from michelito.hosted.keys import load_master
from michelito.hosted.store import FILENAME, Store
from michelito.web.workspace import Workspace
from tests.hosted_helpers import master_file

TODAY = date(2026, 11, 19)
FIXTURES = Path(__file__).parent / "fixtures"
PDF_PASSWORD = "synthetic-pdf-password-31337"
GMAIL_TOKEN = '{"token": "ya29.synthetic-access-token", "refresh_token": "1//synthetic-refresh"}'
HOLDERS = generate.HOLDERS_TEXT


@pytest.fixture(scope="module")
def local(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A local data folder with the demo's synthetic statements, links and shared groups."""
    folder = tmp_path_factory.mktemp("local")
    generate.fill(folder / "michelito.db", TODAY)
    (folder / "holders.txt").write_text(HOLDERS, encoding="utf-8")
    return folder


def _export(local: Path, out: Path) -> transfer.Exported:
    return transfer.export_account(
        local / "michelito.db", out, local / "holders.txt", [PDF_PASSWORD, GMAIL_TOKEN]
    )


def _server(tmp_path: Path) -> tuple[Store, keys.MasterKey, Path]:
    root = tmp_path / "hosted"
    root.mkdir()
    master = load_master(master_file(tmp_path), root)
    return Store(root / FILENAME), master, root


# Export.


def test_export_is_a_private_consistent_snapshot_with_its_schema(
    local: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out" / "michelito-export.db"
    done = _export(local, out)
    assert out.stat().st_mode & 0o777 == 0o600
    assert done.schema_version == db.SCHEMA_VERSION
    assert encrypted.is_plain(out)
    with closing(sqlite3.connect(out)) as conn:
        meta = dict(conn.execute("SELECT key, value FROM michelito_export"))
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        exported = transfer.digest(conn)
    assert meta["schema_version"] == str(db.SCHEMA_VERSION)
    assert meta["holders"] == HOLDERS
    with closing(sqlite3.connect(local / "michelito.db")) as source:
        assert exported == transfer.digest(source)
    assert not list(out.parent.glob(".*partial"))


def test_export_has_no_keyring_secret(local: Path, tmp_path: Path) -> None:
    out = tmp_path / "e.db"
    _export(local, out)
    content = out.read_bytes()
    for needle in (PDF_PASSWORD, "ya29.synthetic-access-token", "1//synthetic-refresh"):
        assert needle.encode() not in content


def test_export_refuses_a_file_where_a_secret_appears(tmp_path: Path) -> None:
    source = tmp_path / "michelito.db"
    with closing(db.connect(source)) as conn, conn:
        conn.execute("CREATE TABLE extra (note TEXT)")
        conn.execute("INSERT INTO extra VALUES (?)", (f"x{PDF_PASSWORD}x",))
    with pytest.raises(transfer.TransferError, match="keyring secret"):
        transfer.export_account(source, tmp_path / "e.db", None, [PDF_PASSWORD])
    assert not (tmp_path / "e.db").exists()
    assert not list(tmp_path.glob(".*partial"))


def test_a_secret_printed_by_the_bank_is_its_data(tmp_path: Path) -> None:
    source = tmp_path / "michelito.db"
    generate.fill(source, TODAY)
    # A description can quote the holder's ID number, which is often also the PDF password.
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute(
            "UPDATE transactions SET description = description || ?"
            " WHERE id = (SELECT MIN(id) FROM transactions)",
            (f" REF {PDF_PASSWORD}",),
        )
    done = transfer.export_account(source, tmp_path / "e.db", None, [PDF_PASSWORD])
    assert done.path.is_file()


def test_a_secret_in_bank_text_and_elsewhere_is_still_refused(tmp_path: Path) -> None:
    source = tmp_path / "michelito.db"
    generate.fill(source, TODAY)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute(
            "UPDATE transactions SET description = description || ?"
            " WHERE id = (SELECT MIN(id) FROM transactions)",
            (f" REF {PDF_PASSWORD}",),
        )
        conn.execute("CREATE TABLE extra (note TEXT)")
        conn.execute("INSERT INTO extra VALUES (?)", (PDF_PASSWORD,))
    with pytest.raises(transfer.TransferError, match="keyring secret"):
        transfer.export_account(source, tmp_path / "e.db", None, [PDF_PASSWORD])
    assert not (tmp_path / "e.db").exists()


def test_export_refuses_a_secret_looking_column(tmp_path: Path) -> None:
    source = tmp_path / "michelito.db"
    with closing(db.connect(source)) as conn, conn:
        conn.execute("CREATE TABLE extra (gmail_token TEXT)")
    with pytest.raises(transfer.TransferError, match="secret-looking"):
        transfer.export_account(source, tmp_path / "e.db")


def test_export_never_overwrites(local: Path, tmp_path: Path) -> None:
    out = tmp_path / "e.db"
    out.write_text("keep")
    with pytest.raises(transfer.TransferError, match="already exists"):
        _export(local, out)
    assert out.read_text() == "keep"


# Import.


def _key_of(store: Store, master: keys.MasterKey, email: str) -> tuple[Path, bytes]:
    account = store.account_by_email(email)
    assert account is not None
    stored = store.data_key(account.id)
    assert stored is not None and stored.folder == account.folder
    return Path(account.folder), keys.unwrap(master, stored.wrapped, account.id, account.folder)


def test_import_encrypts_verifies_and_removes_the_plaintext(local: Path, tmp_path: Path) -> None:
    export = tmp_path / "import" / "michelito-export.db"
    _export(local, export)
    store, master, root = _server(tmp_path)
    done = transfer.import_account(store, master, root, "Owner@Example.com", export)
    assert not export.exists() and not list(export.parent.iterdir())
    assert done.removed.removed == ("michelito-export.db",)
    assert "may survive" in done.removed.note
    folder, key = _key_of(store, master, "owner@example.com")
    assert done.account.folder == str(folder)
    place = root / auth.USERS / folder
    database = place / auth.DATABASE
    assert not encrypted.is_plain(database)
    assert database.stat().st_mode & 0o777 == 0o600
    assert encrypted.problems(database, key) == []
    with closing(db.connect(database, key)) as conn:
        imported = transfer.digest(conn)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert holders.read(conn) == HOLDERS  # inside the encrypted database
    with closing(sqlite3.connect(local / "michelito.db")) as source:
        original = transfer.digest(source)
    assert {t: d for t, d in imported.items() if t != "holders"} == {
        t: d for t, d in original.items() if t != "holders"
    }
    assert imported["holders"].rows == 1
    assert "michelito_export" not in tables
    # Nothing but the encrypted database: no plaintext holders file.
    assert [p.name for p in place.iterdir()] == [auth.DATABASE]
    for path in place.iterdir():
        assert b"PERSONA" not in path.read_bytes()


def test_the_hosted_holders_come_from_the_database_not_a_file(local: Path, tmp_path: Path) -> None:
    export = tmp_path / "e.db"
    _export(local, export)
    store, master, root = _server(tmp_path)
    transfer.import_account(store, master, root, "owner@example.com", export)
    folder, key = _key_of(store, master, "owner@example.com")
    place = root / auth.USERS / folder
    (place / auth.HOLDERS).write_text("SOMEONE ELSE\n")  # ignored for an encrypted workspace
    found = holders.of(Workspace(place / auth.DATABASE, place / auth.HOLDERS, key))
    assert found == parse_holders(HOLDERS) and found.names
    assert holders.of(Workspace(local / "michelito.db", local / "holders.txt")) == found


def test_import_runs_the_forward_migrations(tmp_path: Path) -> None:
    script = (FIXTURES / "schema_v18_shared.sql").read_text(encoding="utf-8")
    old, reference = tmp_path / "old.db", tmp_path / "reference.db"
    for path in (old, reference):
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(script)
    export = tmp_path / "export.db"
    assert transfer.export_account(old, export).schema_version == 18
    store, master, root = _server(tmp_path)
    done = transfer.import_account(store, master, root, "owner@example.com", export)
    assert (done.schema_from, done.schema_to) == (18, db.SCHEMA_VERSION)
    assert not export.exists()
    # The same content as the same fixture migrated in plain SQLite (the Shared ledger built).
    folder, key = _key_of(store, master, "owner@example.com")
    stamp = transfer._stamp(18)
    with closing(db.connect(root / auth.USERS / folder / auth.DATABASE, key)) as conn:
        imported = transfer.digest(conn, stamp)
        assert conn.execute("SELECT count(*) FROM ledger_entries").fetchone()[0] > 0
    with closing(db.connect(reference)) as conn:
        assert imported == transfer.digest(conn, stamp)


def test_a_symlinked_export_is_refused_up_front(local: Path, tmp_path: Path) -> None:
    export = tmp_path / "real.db"
    _export(local, export)
    link = tmp_path / "link.db"
    link.symlink_to(export)
    store, master, root = _server(tmp_path)
    with pytest.raises(transfer.TransferError, match="symbolic link"):
        transfer.import_account(store, master, root, "owner@example.com", link)
    assert export.exists() and link.is_symlink()
    assert store.account_by_email("owner@example.com") is None


def test_a_malformed_manifest_imports_nothing(local: Path, tmp_path: Path) -> None:
    store, master, root = _server(tmp_path)
    for bad in ("not json", '{"x": "y"}'):
        export = tmp_path / f"e{len(bad)}.db"
        _export(local, export)
        with closing(sqlite3.connect(export)) as conn, conn:
            conn.execute("UPDATE michelito_export SET value = ? WHERE key = 'tables'", (bad,))
        with pytest.raises(transfer.TransferError):
            transfer.import_account(store, master, root, "owner@example.com", export)
        assert export.exists()
    export = tmp_path / "e-version.db"
    _export(local, export)
    with closing(sqlite3.connect(export)) as conn, conn:
        conn.execute("UPDATE michelito_export SET value = 'x' WHERE key = 'schema_version'")
    with pytest.raises(transfer.TransferError, match="not valid"):
        transfer.import_account(store, master, root, "owner@example.com", export)
    assert store.account_by_email("owner@example.com") is None


def test_a_plaintext_that_cannot_be_removed_is_reported_apart(
    local: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export = tmp_path / "e.db"
    _export(local, export)
    store, master, root = _server(tmp_path)

    def broken(path: Path) -> transfer.SecureDelete:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(transfer, "secure_delete", broken)
    with pytest.raises(transfer.PlaintextNotRemoved) as error:
        transfer.import_account(store, master, root, "owner@example.com", export)
    assert error.value.path == export and export.exists()
    assert store.account_by_email("owner@example.com") is not None  # the import itself is done


def test_import_refuses_an_existing_account_and_keeps_the_file(local: Path, tmp_path: Path) -> None:
    store, master, root = _server(tmp_path)
    first = tmp_path / "first.db"
    _export(local, first)
    transfer.import_account(store, master, root, "owner@example.com", first)
    second = tmp_path / "second.db"
    _export(local, second)
    with pytest.raises(transfer.TransferError, match="already has an account"):
        transfer.import_account(store, master, root, "owner@example.com", second)
    assert second.exists()
    assert len(store.folders()) == 1


def test_replace_destroys_the_old_key_and_folder(local: Path, tmp_path: Path) -> None:
    store, master, root = _server(tmp_path)
    first = tmp_path / "first.db"
    _export(local, first)
    old = transfer.import_account(store, master, root, "owner@example.com", first).account
    second = tmp_path / "second.db"
    _export(local, second)
    new = transfer.import_account(store, master, root, "owner@example.com", second, replace=True)
    assert new.replaced and new.account.folder != old.folder
    assert [k.folder for k in store.data_keys()] == [new.account.folder]  # the old key is gone
    assert not (root / auth.USERS / old.folder).exists()
    assert store.folders() == {new.account.folder}
    assert store.deleted_folders() == []  # removed now, so no tombstone is left


def test_a_failed_replace_leaves_the_old_account_intact(
    local: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, master, root = _server(tmp_path)
    first = tmp_path / "first.db"
    _export(local, first)
    old = transfer.import_account(store, master, root, "owner@example.com", first).account
    old_folder, old_key = _key_of(store, master, "owner@example.com")
    second = tmp_path / "second.db"
    _export(local, second)

    def fails(*args: object) -> bytes:
        raise RuntimeError("the new key could not be sealed")

    monkeypatch.setattr(keys, "wrap", fails)  # fails inside the replacing transaction
    with pytest.raises(RuntimeError):
        transfer.import_account(store, master, root, "owner@example.com", second, replace=True)
    monkeypatch.undo()
    assert store.account_by_email("owner@example.com") == old
    assert _key_of(store, master, "owner@example.com") == (old_folder, old_key)
    assert store.folders() == {old.folder}
    assert sorted(p.name for p in (root / auth.USERS).iterdir()) == [old.folder]
    with closing(db.connect(root / auth.USERS / old_folder / auth.DATABASE, old_key)) as conn:
        assert holders.read(conn) == HOLDERS
    assert second.exists()


def test_replace_account_is_one_transaction(tmp_path: Path) -> None:
    store, master, _ = _server(tmp_path)
    old = store.create_account("a@example.com", "a" * 32, 1, None, lambda i: (b"k1", master.id))
    store.create_account("c@example.com", "c" * 32, 1, None, lambda i: (b"kc", master.id))
    with pytest.raises(LookupError):  # the new folder is another account's: nothing changes
        store.replace_account(old.id, "a@example.com", "c" * 32, 2, lambda i: (b"k2", master.id))
    assert store.account_by_email("a@example.com") == old
    assert store.data_key(old.id).wrapped == b"k1"
    new = store.replace_account(old.id, "a@example.com", "b" * 32, 3, lambda i: (b"k3", master.id))
    assert store.folders() == {"b" * 32, "c" * 32}
    assert store.data_key(new.id).wrapped == b"k3"


def test_a_damaged_export_is_refused_and_nothing_is_created(local: Path, tmp_path: Path) -> None:
    export = tmp_path / "e.db"
    _export(local, export)
    with closing(sqlite3.connect(export)) as conn, conn:
        conn.execute("DELETE FROM exchange_rates")  # a file that changed after the export
    store, master, root = _server(tmp_path)
    with pytest.raises(transfer.TransferError, match="manifest"):
        transfer.import_account(store, master, root, "owner@example.com", export)
    assert export.exists()
    assert store.account_by_email("owner@example.com") is None
    assert not (root / auth.USERS).exists() or not list((root / auth.USERS).iterdir())


def test_a_file_not_from_export_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "michelito.db"
    db.connect(plain).close()
    store, master, root = _server(tmp_path)
    with pytest.raises(transfer.TransferError, match="export-account"):
        transfer.import_account(store, master, root, "owner@example.com", plain)
    (tmp_path / "garbage.db").write_bytes(b"not sqlite at all, nothing to see")
    with pytest.raises(transfer.TransferError, match="unencrypted SQLite"):
        transfer.import_account(store, master, root, "owner@example.com", tmp_path / "garbage.db")


def test_secure_delete_overwrites_before_unlinking(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    path = tmp_path / "plain.db"
    path.write_bytes(b"SECRET-PLAINTEXT" * 1000)
    (tmp_path / "plain.db-journal").write_bytes(b"JOURNAL")
    seen: list[bytes] = []
    real_unlink = Path.unlink

    def spy(self: Path, missing_ok: bool = False) -> None:
        seen.append(self.read_bytes())
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", spy)
    done = transfer.secure_delete(path)
    assert done.removed == ("plain.db", "plain.db-journal")
    assert all(set(content) == {0} for content in seen)
    assert not path.exists()


# verify-import.


def test_the_figures_are_the_same_locally_and_hosted(local: Path, tmp_path: Path) -> None:
    months = ["2026-08", "2026-09", "2026-10"]
    plain = figures.collect(Workspace(local / "michelito.db", local / "holders.txt"), months, TODAY)
    export = tmp_path / "e.db"
    _export(local, export)
    store, master, root = _server(tmp_path)
    account = transfer.import_account(store, master, root, "owner@example.com", export).account
    stored = store.data_key(account.id)
    key = keys.unwrap(master, stored.wrapped, account.id, account.folder)
    place = root / auth.USERS / account.folder
    sealed = figures.collect(
        Workspace(place / auth.DATABASE, place / auth.HOLDERS, key), months, TODAY
    )
    assert figures.render(plain, exact=False) == figures.render(sealed, exact=False)
    assert figures.render(plain, exact=True) == figures.render(sealed, exact=True)
    assert all(s.payload is not None for s in plain)  # real figures, not "no data"
    numbers = figures.render(plain, exact=True)
    assert any(line.startswith("shared ") for line in numbers)
    assert any(line.startswith("investments ") for line in numbers)


def test_a_different_figure_changes_the_hash(local: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy.db"
    with (
        closing(sqlite3.connect(local / "michelito.db")) as src,
        closing(sqlite3.connect(copy)) as dst,
    ):
        src.backup(dst)
    with closing(sqlite3.connect(copy)) as conn, conn:
        conn.execute(
            "UPDATE transactions SET amount_cents = amount_cents + 100 "
            "WHERE transacted_on LIKE '2026-10%' AND direction = 'debit'"
        )
    months = ["2026-10"]
    one = figures.render(
        figures.collect(Workspace(local / "michelito.db", local / "holders.txt"), months, TODAY),
        False,
    )
    two = figures.render(
        figures.collect(Workspace(copy, local / "holders.txt"), months, TODAY), False
    )
    assert one[-1] != two[-1]


def test_the_figures_refuse_a_regular_file(tmp_path: Path) -> None:
    with (tmp_path / "out.txt").open("w") as handle:
        assert figures.refuse_file(handle)
    assert not figures.refuse_file(open("/dev/null", "w"))  # noqa: SIM115


def test_the_hosted_figures_use_the_imported_holders(local: Path, tmp_path: Path) -> None:
    """Without the holders the demo's own transfers would count as spending: the equal figures
    above prove the holders reached the encrypted database and are read from it."""
    export = tmp_path / "e.db"
    _export(local, export)
    store, master, root = _server(tmp_path)
    transfer.import_account(store, master, root, "owner@example.com", export)
    folder, key = _key_of(store, master, "owner@example.com")
    place = root / auth.USERS / folder
    workspace = Workspace(place / auth.DATABASE, place / auth.HOLDERS, key)
    months = ["2026-10"]
    before = figures.render(figures.collect(workspace, months, TODAY), False)
    with closing(db.connect(workspace.database, key)) as conn, conn:
        conn.execute("DELETE FROM holders")
    after = figures.render(figures.collect(workspace, months, TODAY), False)
    assert before[-1] != after[-1]
