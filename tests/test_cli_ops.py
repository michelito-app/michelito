"""The operations commands end to end through `michelito …`: export → import → verify-import,
backups to a folder and to a fake R2, restore, the daily check, and which commands the hosted
container accepts. Synthetic data, throwaway keys and loopback only."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from michelito import cli, cli_ops, db
from michelito.demo import generate
from michelito.hosted import s3
from tests.fake_s3 import ACCESS, BUCKET, SECRET, fake_s3
from tests.hosted_helpers import master_file

TODAY = date(2026, 11, 19)
MONTHS = "2026-08,2026-09,2026-10"
RUN = "import sys; from michelito import cli; sys.exit(cli.main(sys.argv[1:]))"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    local = tmp_path / "local"
    local.mkdir()
    generate.fill(local / "michelito.db", TODAY)
    (local / "holders.txt").write_text("# synthetic\n")
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(local))
    for name in ("MICHELITO_MODE", "MICHELITO_HOSTED_SECRET_FILE", "MICHELITO_MASTER_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli_ops, "_keyring_secrets", lambda: (["synthetic-password"], True))
    master = master_file(tmp_path)
    monkeypatch.setenv("MICHELITO_MASTER_KEY_FILE", str(master))
    return {"local": local, "hosted": tmp_path / "hosted", "master": master, "tmp": tmp_path}


def _import(env: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    export = env["tmp"] / "import" / "export.db"
    assert cli.main(["export-account", "--out", str(export)]) == 0
    assert "no keyring secret" in capsys.readouterr().out
    argv = ["import-account", "--email", "owner@example.com", "--from", str(export)]
    assert cli.main([*argv, "--data", str(env["hosted"])]) == 0
    out = capsys.readouterr().out
    assert "Created the account" in out and "may survive" in out
    assert not export.exists()


def _secrets(env: dict[str, Path]) -> list[str]:
    hex_key = env["master"].read_text().strip()
    return [hex_key, SECRET, ACCESS]


def test_export_import_and_the_same_figures(env, capsys) -> None:  # noqa: ANN001
    _import(env, capsys)
    today = ["--today", TODAY.isoformat()]
    assert cli.main(["verify-import", "--months", MONTHS, *today]) == 0
    local = capsys.readouterr().out
    hosted = ["--email", "owner@example.com", "--data", str(env["hosted"])]
    assert cli.main(["verify-import", "--months", MONTHS, *today, *hosted]) == 0
    server = capsys.readouterr().out
    assert local == server
    assert len(local.splitlines()) == 6  # three months, shared, investments, all
    assert cli.main(["verify-import", "--months", MONTHS, *today, *hosted, "--exact"]) == 0
    assert "total_cents" in capsys.readouterr().out
    for value in _secrets(env):
        assert value not in local


def test_import_refuses_replace_without_confirmation(env, capsys) -> None:  # noqa: ANN001
    _import(env, capsys)
    export = env["tmp"] / "again.db"
    assert cli.main(["export-account", "--out", str(export)]) == 0
    base = ["import-account", "--email", "owner@example.com", "--from", str(export)]
    base += ["--data", str(env["hosted"])]
    assert cli.main(base) == 1
    assert "already has an account" in capsys.readouterr().err
    assert cli.main([*base, "--replace"]) == 2
    assert "--confirm-replace" in capsys.readouterr().err
    assert export.exists()
    assert cli.main([*base, "--replace", "--confirm-replace", "OWNER@example.com"]) == 0
    assert "Replaced the account" in capsys.readouterr().out
    assert not export.exists()


def test_backup_to_a_folder_and_restore(env, capsys) -> None:  # noqa: ANN001
    _import(env, capsys)
    backups = env["tmp"] / "deploy-backups"
    data = ["--data", str(env["hosted"])]
    for label in ("aaa", "bbb"):
        argv = ["backup", "--to", str(backups), "--keep", "1", "--label", label, *data]
        assert cli.main(argv) == 0
    assert len([p for p in backups.iterdir() if p.is_dir()]) == 1
    clean = env["tmp"] / "clean"
    restore = ["restore", "--from-dir", str(backups), "--date", "latest", "--data", str(clean)]
    assert cli.main(restore) == 0
    assert "1 account(s)" in capsys.readouterr().out
    assert cli.main(restore) == 1  # not empty any more
    assert "not empty" in capsys.readouterr().err


def test_backup_to_r2_records_the_status_and_restores(
    env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    _import(env, capsys)
    data = ["--data", str(env["hosted"])]
    with fake_s3() as fake:
        monkeypatch.setenv(s3.ENDPOINT_ENV, fake.endpoint)
        monkeypatch.setenv(s3.BUCKET_ENV, BUCKET)
        monkeypatch.setenv(s3.ACCESS_KEY_ENV, ACCESS)
        monkeypatch.setenv(s3.SECRET_KEY_ENV, SECRET)
        assert cli.main(["backup", *data]) == 0
        assert cli.main(["ops-check", *data]) == 0
        assert "Nothing failed" in capsys.readouterr().out
        clean = ["--data", str(env["tmp"] / "clean")]
        assert cli.main(["restore", "--from-r2", "--date", "latest", *clean]) == 0
        fake.fail_puts = True
        assert cli.main(["backup", *data]) == 1
    output = capsys.readouterr()
    assert "backup failed" in output.err
    for value in _secrets(env):
        assert value not in output.out + output.err
    assert cli.main(["ops-check", *data]) == 1  # the failure, and no address to email it to
    output = capsys.readouterr()
    assert "backup" in output.out and "MICHELITO_OPS_EMAIL" in output.err


def test_a_second_r2_backup_on_the_same_day_does_not_hit_the_bucket_lock(
    env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    _import(env, capsys)
    data = ["--data", str(env["hosted"])]
    with fake_s3() as fake:
        fake.object_lock = True
        monkeypatch.setenv(s3.ENDPOINT_ENV, fake.endpoint)
        monkeypatch.setenv(s3.BUCKET_ENV, BUCKET)
        monkeypatch.setenv(s3.ACCESS_KEY_ENV, ACCESS)
        monkeypatch.setenv(s3.SECRET_KEY_ENV, SECRET)
        assert cli.main(["backup", *data]) == 0
        assert cli.main(["backup", *data]) == 0, capsys.readouterr().err
        assert len({k.split("/")[1] for k in fake.objects}) == 2
        assert cli.main(["ops-check", *data]) == 0
        assert "Nothing failed" in capsys.readouterr().out


def test_ops_check_emails_the_owner_only_on_failure(env, capsys) -> None:  # noqa: ANN001
    data = ["--data", str(env["hosted"]), "--mailer", "outbox"]
    assert cli.main(["ops-check", *data, "--to", "owner@example.com"]) == 1  # never backed up
    outbox = list((env["hosted"] / "outbox").glob("*.json"))
    assert len(outbox) == 1
    assert "owner was emailed" in capsys.readouterr().out


def test_check_accounts_opens_every_database(env, capsys) -> None:  # noqa: ANN001
    data = ["--data", str(env["hosted"])]
    assert cli.main(["check-accounts", *data]) == 0
    assert "No accounts yet" in capsys.readouterr().out
    _import(env, capsys)

    assert cli.main(["check-accounts", *data]) == 0

    output = capsys.readouterr()
    assert f"Opened 1 account database(s) at schema {db.SCHEMA_VERSION}" in output.out
    for value in _secrets(env):
        assert value not in output.out + output.err


def test_check_accounts_names_the_account_that_does_not_open(
    env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    _import(env, capsys)
    # As after going back to an earlier version: the database is newer than the code.
    monkeypatch.setattr(db, "SCHEMA_VERSION", db.SCHEMA_VERSION - 1)

    assert cli.main(["check-accounts", "--data", str(env["hosted"])]) == 1

    output = capsys.readouterr()
    assert "- account 1: NewerSchemaError" in output.err
    assert "1 account database(s) could not be opened (0 opened" in output.err
    for value in _secrets(env):
        assert value not in output.out + output.err


def test_check_accounts_tries_again_when_a_database_is_busy(
    env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    _import(env, capsys)
    connect = db.connect
    busy = [sqlite3.OperationalError("database is locked")]

    def sometimes_busy(*args: object, **kwargs: object) -> sqlite3.Connection:
        if busy:
            raise busy.pop()
        return connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(db, "connect", sometimes_busy)

    assert cli.main(["check-accounts", "--data", str(env["hosted"])]) == 0
    assert not busy


def test_check_accounts_needs_the_master_key(env, capsys, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    _import(env, capsys)
    monkeypatch.delenv("MICHELITO_MASTER_KEY_FILE")

    assert cli.main(["check-accounts", "--data", str(env["hosted"])]) == 4


def test_the_hosted_container_only_runs_server_commands(
    env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    monkeypatch.setenv("MICHELITO_MODE", "hosted")
    for argv in (["board"], ["export-account", "--out", "x.db"], ["report"], ["demo"]):
        assert cli.main(argv) == 2
        assert "only the server commands" in capsys.readouterr().err
    assert cli.main(["verify-import", "--months", MONTHS]) == 2
    assert "--email" in capsys.readouterr().err
    data = ["--data", str(env["hosted"]), "--mailer", "outbox"]
    assert cli.main(["invite", "a@example.com", *data]) == 0


def test_verify_import_refuses_a_regular_file(env, tmp_path: Path) -> None:  # noqa: ANN001
    import subprocess
    import sys

    out = tmp_path / "figures.txt"
    with out.open("w") as handle:
        done = subprocess.run(
            [sys.executable, "-c", RUN, "verify-import", "--months", "2026-10"],
            stdout=handle,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env={"MICHELITO_DATA_DIR": str(env["local"]), "PATH": "/usr/bin:/bin"},
        )
    assert done.returncode == 2 and "only go to the terminal" in done.stderr
    assert out.read_text() == ""


def test_import_fails_loudly_when_the_plaintext_stays(
    env, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    from michelito.hosted import transfer

    export = env["tmp"] / "import" / "export.db"
    assert cli.main(["export-account", "--out", str(export)]) == 0
    monkeypatch.setattr(transfer, "secure_delete", lambda path: transfer.SecureDelete((), ""))
    argv = ["import-account", "--email", "owner@example.com", "--from", str(export)]
    assert cli.main([*argv, "--data", str(env["hosted"])]) == 1
    err = capsys.readouterr().err
    assert "was NOT removed" in err and f"shred -u {export}" in err
    assert export.exists()


def test_backup_skip_empty_has_nothing_to_do(env, capsys) -> None:  # noqa: ANN001
    argv = ["backup", "--to", str(env["tmp"] / "b"), "--data", str(env["tmp"] / "empty")]
    assert cli.main([*argv, "--skip-empty"]) == 0
    assert "nothing to back up" in capsys.readouterr().out
    assert cli.main(argv) == 1


def test_the_hosted_api_is_never_cached(tmp_path: Path) -> None:
    from tests.hosted_helpers import hosted

    env = hosted(tmp_path)
    client = env.client()
    assert client.get("/api/summary").headers["cache-control"] == "no-store"  # 401 too
    assert client.get("/api/health").headers["cache-control"] == "no-store"
    signed = env.sign_in("a@example.com")
    assert signed.get("/api/categories").headers["cache-control"] == "no-store"
    assert "no-store" not in client.get("/").headers.get("cache-control", "")


def test_forwarding_check_emails_late_statements_once(env, capsys) -> None:  # noqa: ANN001
    from michelito.hosted import forwarding
    from michelito.hosted.store import FILENAME, Store

    _import(env, capsys)
    store = Store(env["hosted"] / FILENAME)
    account = store.account_by_email("owner@example.com")
    assert account is not None
    store.set_forwarding(account.id, forwarding.token_hash(forwarding.new_token()), 0)
    data = ["--data", str(env["hosted"]), "--mailer", "outbox"]
    assert cli.main(["forwarding-check", *data, "--today", TODAY.isoformat()]) == 0
    assert "sent: 0" in capsys.readouterr().out
    late = ["--today", "2027-03-01"]
    assert cli.main(["forwarding-check", *data, *late]) == 0
    assert "sent: 1" in capsys.readouterr().out  # one email a day, whatever the late accounts
    outbox = list((env["hosted"] / "outbox").glob("*.json"))
    assert len(outbox) == 1
    text = outbox[0].read_text()
    assert "owner@example.com" in text and "RD$" not in text
    assert cli.main(["forwarding-check", *data, *late]) == 0
    assert "sent: 0" in capsys.readouterr().out  # already told


def test_an_existing_account_is_never_marked_or_seeded(env, capsys) -> None:  # noqa: ANN001
    _import(env, capsys)
    data = ["--data", str(env["hosted"])]
    seed = ["seed-test-account", "--email", "owner@example.com", "--stage", "first-statement"]
    today = ["--today", TODAY.isoformat()]

    assert cli.main([*seed, *today, *data]) == 1
    assert "not marked as a test account" in capsys.readouterr().err

    mark = ["invite", "owner@example.com", "--test", "--mailer", "outbox", *data]
    assert cli.main(mark) == 1
    assert "already has an account" in capsys.readouterr().err
    assert cli.main([*seed, *today, *data]) == 1
    assert "not marked as a test account" in capsys.readouterr().err


def test_a_new_invitation_can_be_a_test_account(env, capsys) -> None:  # noqa: ANN001
    from michelito.hosted.store import FILENAME, Store

    data = ["--data", str(env["hosted"])]
    mark = ["invite", "tester@example.com", "--test", "--mailer", "outbox", *data]

    assert cli.main(mark) == 0
    assert "test account" in capsys.readouterr().out
    assert Store(env["hosted"] / FILENAME).is_test_email("tester@example.com")
