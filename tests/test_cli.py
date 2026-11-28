import socket
import sqlite3
import stat
from collections import Counter
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import uvicorn

from michelito import cli, config, db, importer, vault
from michelito.analysis import bcrd, rates, spending
from michelito.parsers.common import Page
from michelito.web.accounts import DuePayment, due_text
from tests import samples
from tests.fakes import FakeClient, make_message
from tests.test_spending import seed
from tests.test_web_accounts import add_statement


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(root))
    return root


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    store = {vault.PDF_PASSWORD: "pdf-pass", vault.GMAIL_TOKEN: "{}"}
    monkeypatch.setattr("keyring.get_password", lambda service, name: store.get(name))
    monkeypatch.setattr(
        "keyring.set_password", lambda service, name, value: store.__setitem__(name, value)
    )
    return store


def test_report_on_empty_data_dir(data_dir: Path, secrets, capsys) -> None:
    assert cli.main(["report"]) == 0
    assert "No alerts." in capsys.readouterr().out
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((data_dir / "michelito.db").stat().st_mode) == 0o600


def test_a_migration_mismatch_says_how_to_check_instead_of_a_traceback(
    data_dir: Path, secrets, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from michelito import migrations_v19  # noqa: PLC0415

    assert cli.main(["report"]) == 0
    with closing(sqlite3.connect(data_dir / "michelito.db")) as raw:
        raw.execute("PRAGMA user_version = 18")
        raw.commit()

    def refuse(*args: object) -> None:
        raise migrations_v19.MigrationMismatch("shared group 1 would change its balances")

    monkeypatch.setattr(migrations_v19, "migrate", refuse)
    assert cli.main(["report"]) == 3
    err = capsys.readouterr().err
    assert "check_shared_migration.py" in err and "shared group 1" in err
    assert "Traceback" not in err


def test_a_database_from_a_newer_version_ends_with_a_message(
    data_dir: Path, secrets, capsys
) -> None:
    from michelito import db  # noqa: PLC0415

    assert cli.main(["report"]) == 0
    with closing(sqlite3.connect(data_dir / "michelito.db")) as raw:
        raw.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
        raw.commit()

    assert cli.main(["report"]) == 3

    err = capsys.readouterr().err
    assert str(db.SCHEMA_VERSION + 1) in err and "Traceback" not in err


def test_missing_secret_exits_with_hint(data_dir: Path, secrets, capsys) -> None:
    secrets.pop(vault.PDF_PASSWORD)
    assert cli.main(["parse"]) == 2
    assert "michelito secret pdf-password" in capsys.readouterr().err


def test_auth_stores_client_config_and_reuses_it(
    tmp_path: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    seen: list[dict] = []
    monkeypatch.setattr(cli, "authorize", lambda config: seen.append(config) or "new-token")
    client_file = tmp_path / "client_secret.json"
    client_file.write_text('{"installed": {"client_id": "id"}}')

    assert cli.main(["auth", "--client-secrets", str(client_file)]) == 0
    assert secrets[vault.GMAIL_CLIENT] == '{"installed": {"client_id": "id"}}'
    assert secrets[vault.GMAIL_TOKEN] == "new-token"

    client_file.unlink()
    assert cli.main(["auth"]) == 0
    assert seen == [{"installed": {"client_id": "id"}}] * 2


def test_auth_without_file_or_stored_client_explains(data_dir: Path, secrets, capsys) -> None:
    assert cli.main(["auth"]) == 2
    assert "--client-secrets" in capsys.readouterr().err


def test_auth_with_missing_file_explains_instead_of_crashing(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "client_secret_XXXX.json"
    assert cli.main(["auth", "--client-secrets", str(missing)]) == 1
    error = capsys.readouterr().err
    assert "does not exist" in error and "Google Cloud" in error


def test_auth_with_invalid_json_explains(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "client_secret.json"
    broken.write_text("this is not json")
    assert cli.main(["auth", "--client-secrets", str(broken)]) == 1
    assert "is not valid JSON" in capsys.readouterr().err


def test_secret_command_stores_value(secrets, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt: "new-secret")
    assert cli.main(["secret", vault.PDF_PASSWORD]) == 0
    assert secrets[vault.PDF_PASSWORD] == "new-secret"
    monkeypatch.setattr("getpass.getpass", lambda prompt: "")
    assert cli.main(["secret", vault.PDF_PASSWORD]) == 1


def test_sync_runs_the_whole_pipeline(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    client = FakeClient(make_message("m1", {"statement.pdf": b"%PDF-fake"}))
    monkeypatch.setattr(cli, "build_client", lambda token, save: client)

    def reader(path: Path, password: str) -> tuple[Page, ...]:
        assert password == "pdf-pass"
        return samples.POPULAR_PAGES

    monkeypatch.setattr(cli.pdf, "read_pages", reader)
    notices: list[list[str]] = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(cli.subprocess, "run", lambda args, check: notices.append(args))

    exit_code = cli.main(["sync", "--notify"])

    output = capsys.readouterr().out
    assert "1 new messages" in output
    assert "parsed: 1" in output
    assert "POPULAR VISA PRESTIGE DOP: 1 closings" in output
    assert exit_code == 1  # the synthetic closing is from 2026-01: it is overdue
    assert notices and "1 statements validated" in notices[0][-1]


def test_extract_single_source(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli, "build_client", lambda token, save: FakeClient())
    assert cli.main(["extract", "--source", "popular"]) == 0
    assert "popular: 0 new messages" in capsys.readouterr().out


class _QueryLog(FakeClient):
    """A client with no emails that records which Gmail searches it is asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.queries: list[str] = []

    def list_message_ids(self, query: str):  # noqa: ANN201 - same type as FakeClient
        self.queries.append(query)
        return super().list_message_ids(query)


def test_sync_without_sources_file_asks_gmail_the_default_sources(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    client = _QueryLog()
    monkeypatch.setattr(cli, "build_client", lambda token, save: client)
    cli.main(["sync"])
    assert client.queries == [s.query for s in config.DEFAULT_SOURCES]
    assert "afp_crecer: 0 new messages" in capsys.readouterr().out


def test_sync_uses_only_the_sources_of_the_user_file(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir.mkdir(parents=True)
    (data_dir / "sources.toml").write_text(
        '[[source]]\nname = "bank"\nquery = "from:x@bank.example"\nextensions = [".pdf"]\n'
    )
    client = _QueryLog()
    monkeypatch.setattr(cli, "build_client", lambda token, save: client)
    cli.main(["sync"])
    assert client.queries == ["from:x@bank.example"]
    assert cli.main(["extract", "--source", "bank"]) == 0
    assert cli.main(["extract", "--source", "popular"]) == 2
    assert "unknown source: popular; the configured ones are: bank" in capsys.readouterr().err


def test_broken_sources_file_stops_with_a_hint(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir.mkdir(parents=True)
    (data_dir / "sources.toml").write_text("[[source]]\nname = 1\n")
    monkeypatch.setattr(cli, "build_client", lambda token, save: pytest.fail("must not connect"))
    assert cli.main(["sync"]) == 2
    assert cli.main(["extract"]) == 2
    assert "sources.toml" in capsys.readouterr().err


def test_parse_archives_the_archive_only_sources_of_the_user_file(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir.mkdir(parents=True)
    (data_dir / "sources.toml").write_text(
        '[[source]]\nname = "afp-x"\nquery = "from:afp@afp.example"\n'
        'extensions = [".pdf"]\nparse = false\n'
    )
    seen: dict[str, object] = {}

    def spy(conn, password, read_pages, **kwargs):  # noqa: ANN001, ANN202
        seen.update(kwargs)
        return Counter()

    monkeypatch.setattr(cli.ingest, "process_documents", spy)
    assert cli.main(["parse"]) == 0
    # The default AFPs stay archive-only even though the file no longer lists them.
    assert seen["archive_only"] == config.ARCHIVE_ONLY | {"afp-x"}


def test_spending_without_data(data_dir: Path, capsys) -> None:
    assert cli.main(["spending"]) == 0
    out = capsys.readouterr().out
    assert "No card statements saved yet" in out
    assert not (data_dir / "reportes").exists()  # no page is written any more  # spanish-data


def test_spending_with_data(data_dir: Path, capsys) -> None:
    data_dir.mkdir(mode=0o700)
    with closing(db.connect(data_dir / "michelito.db")) as conn:
        seed(conn)
    assert cli.main(["spending", "--months", "3"]) == 0
    out = capsys.readouterr().out
    # A single statement per card: December is incomplete and January has not closed.
    assert "No month is fully covered" in out


def test_spending_reads_the_holders_file(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir.mkdir(mode=0o700)
    with closing(db.connect(data_dir / "michelito.db")) as conn:
        seed(conn)
    (data_dir / "holders.txt").write_text("Maria Perez Inventada\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []
    original = cli.spending.load_movements

    def spy(conn, holders=()):  # noqa: ANN001, ANN202
        # Formerly `tuple(holders)`: names and numbers now arrive separately (`Holders`).
        seen.append(cli.transfers.as_holders(holders).names)
        return original(conn, holders)

    monkeypatch.setattr(cli.spending, "load_movements", spy)
    assert cli.main(["spending"]) == 0
    assert seen == [("MARIA PEREZ INVENTADA",)]


def test_board_requires_built_frontend(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli, "STATIC_DIR", tmp_path / "not-built")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("must not start"))
    assert cli.main(["board"]) == 1
    captured = capsys.readouterr()
    assert "cd frontend && npm ci && npm run build" in captured.err
    assert captured.out == ""


@pytest.fixture
def built_frontend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(cli, "STATIC_DIR", static)
    return static


def test_board_runs_uvicorn_on_loopback(
    data_dir: Path, built_frontend: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    calls: list[tuple[object, dict]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    assert cli.main(["board", "--port", "8600", "--no-browser"]) == 0
    ((app, kwargs),) = calls
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8600
    assert app.title == "michelito"
    assert "http://127.0.0.1:8600" in capsys.readouterr().out


def test_board_opens_the_browser_itself(
    data_dir: Path, built_frontend: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[tuple[str, int]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_open_when_ready", lambda url, port: opened.append((url, port)))
    assert cli.main(["board", "--port", "8601"]) == 0
    assert opened == [("http://127.0.0.1:8601", 8601)]


def test_open_when_ready_waits_for_the_port(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        cli._open_when_ready("http://127.0.0.1:x", port)
    assert opened == ["http://127.0.0.1:x"]


def test_open_when_ready_gives_up_when_nothing_listens(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    monkeypatch.setattr(cli, "BOARD_STARTUP_SECONDS", 0.2)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    cli._open_when_ready("http://127.0.0.1:x", free_port)
    assert opened == []


def test_board_stops_cleanly_on_ctrl_c(
    data_dir: Path, built_frontend: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(*args, **kwargs) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(uvicorn, "run", interrupted)
    monkeypatch.setattr(cli, "_open_when_ready", lambda url, port: None)
    assert cli.main(["board"]) == 0


def test_spending_rejects_bad_month_count(data_dir: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["spending", "--months", "0"])


def test_rates_set(data_dir: Path, secrets, capsys) -> None:
    assert cli.main(["rates", "--set", "2026-09", "64.25"]) == 0
    with closing(db.connect(data_dir / "michelito.db")) as conn:
        loaded = rates.load(conn)
    assert loaded["2026-09"].value == Decimal("64.2500")
    assert loaded["2026-09"].source == "manual"
    assert "September 2026" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["rates", "--set", "2026-13", "64"],
        ["rates", "--set", "2026-00", "64"],
        ["rates", "--set", "september", "64"],
        ["rates", "--set", "2026-09", "-1"],
        ["rates", "--set", "2026-09", "0"],
        ["rates", "--set", "2026-09", "abc"],
        ["rates", "--set", "2026-09", "NaN"],
    ],
)
def test_rates_rejects_bad_input(argv: list[str], data_dir: Path, secrets) -> None:
    with pytest.raises(SystemExit):
        cli.main(argv)


def test_rates_downloads_and_keeps_manual(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    assert cli.main(["rates", "--set", "2026-08", "70"]) == 0
    monkeypatch.setattr(bcrd, "fetch", lambda: b"{}")
    monkeypatch.setattr(
        bcrd,
        "parse_monthly_averages",
        lambda content: {"2026-08": Decimal("63.1"), "2026-09": Decimal("63.4")},
    )
    capsys.readouterr()
    assert cli.main(["rates"]) == 0
    assert "BCRD rates: 1 months saved (latest: September 2026 63.4000)" in (
        capsys.readouterr().out
    )
    with closing(db.connect(data_dir / "michelito.db")) as conn:
        loaded = rates.load(conn)
    assert loaded["2026-08"].value == Decimal("70.0000")
    assert loaded["2026-09"].source == "bcrd"


@pytest.mark.parametrize("error", [OSError("no network"), ValueError("format")])
def test_rates_download_failure(
    error: Exception, data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def failing_fetch() -> bytes:
        raise error

    monkeypatch.setattr(bcrd, "fetch", failing_fetch)
    assert cli.main(["rates"]) == 1
    assert "--set" in capsys.readouterr().err


def test_rates_last_shows_the_stored_rate_of_a_manual_month(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    assert cli.main(["rates", "--set", "2026-09", "70"]) == 0
    monkeypatch.setattr(bcrd, "fetch", lambda: b"{}")
    monkeypatch.setattr(
        bcrd, "parse_monthly_averages", lambda content: {"2026-09": Decimal("63.4")}
    )
    capsys.readouterr()
    assert cli.main(["rates"]) == 0
    assert "(latest: September 2026 70.0000)" in capsys.readouterr().out


def test_rates_empty_bcrd_answer_fails_with_hint(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(bcrd, "fetch", lambda: b'{"result": {"items": []}}')
    assert cli.main(["rates"]) == 1
    err = capsys.readouterr().err
    assert "returned no rates" in err and "--set" in err


def _due(*amounts: tuple[str, str]) -> DuePayment:
    return DuePayment(
        key="k",
        label="POPULAR VISA PRESTIGE",
        due_date=date(2026, 12, 14),
        amounts=[(currency, Decimal(value)) for currency, value in amounts],
        minimums=[],
    )


def test_due_text_one_and_two_currencies() -> None:
    expected = (
        "POPULAR VISA PRESTIGE: paga RD$ 45,300 antes del 14 dic "  # spanish-ui
        "para no pagar intereses"  # spanish-ui
    )
    assert due_text(_due(("DOP", "45300"))) == expected
    assert due_text(_due(("DOP", "45300"), ("USD", "120.5"))) == (
        "POPULAR VISA PRESTIGE: paga RD$ 45,300 y US$ 120.50 antes del 14 dic "  # spanish-ui
        "para no pagar intereses"  # spanish-ui
    )
    early = DuePayment("k", "X", date(2026, 3, 5), [("DOP", Decimal("10"))], [])
    assert "antes del 5 mar" in due_text(early)  # spanish-ui


def _sync_stubs(monkeypatch: pytest.MonkeyPatch, payments: list[DuePayment]) -> list[list[str]]:
    monkeypatch.setattr(cli, "_run_extract", lambda paths, source: [])
    monkeypatch.setattr(cli, "_run_parse", lambda paths, retry: Counter({"parsed": 1}))
    monkeypatch.setattr(cli, "_run_due_payments", lambda paths: payments)
    notices: list[list[str]] = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(cli.subprocess, "run", lambda args, check: notices.append(args))
    return notices


def test_sync_notifies_upcoming_payments(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    payments = [_due(("DOP", "45300"), ("USD", "120.5")), _due(("DOP", "100"))]
    notices = _sync_stubs(monkeypatch, payments)

    cli.main(["sync", "--notify"])

    output = capsys.readouterr().out
    assert "Payments to avoid interest:" in output
    assert f"  {due_text(payments[0])}" in output
    sent = [args[-1] for args in notices]
    assert sent[1:] == [due_text(p) for p in payments]
    assert all(args[2] == "normal" for args in notices[1:])


def test_sync_without_upcoming_payments_adds_nothing(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    notices = _sync_stubs(monkeypatch, [])

    cli.main(["sync", "--notify"])

    assert "Payments to avoid interest" not in capsys.readouterr().out
    assert len(notices) == 1


def test_sync_without_notify_prints_payments_only(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    payments = [_due(("DOP", "45300"))]
    notices = _sync_stubs(monkeypatch, payments)

    cli.main(["sync"])

    assert f"  {due_text(payments[0])}" in capsys.readouterr().out
    assert notices == []


def test_sync_survives_failing_payment_lookup(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    notices = _sync_stubs(monkeypatch, [])
    expected = cli.main(["sync"])

    def broken(paths):
        raise sqlite3.OperationalError("broken database")

    monkeypatch.setattr(cli, "_run_due_payments", broken)
    capsys.readouterr()
    exit_code = cli.main(["sync", "--notify"])

    captured = capsys.readouterr()
    assert "Could not compute the pending payments: broken database" in captured.err
    assert "Payments to avoid interest" not in captured.out
    assert exit_code == expected
    assert len(notices) == 1 and "1 statements validated" in notices[0][-1]


def test_sync_prints_real_upcoming_payment(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli, "_run_extract", lambda paths, source: [])
    monkeypatch.setattr(cli, "_run_parse", lambda paths, retry: Counter())
    today = date.today()
    with closing(cli._open_db(cli.config.default_paths())) as conn:
        seed(conn)
        add_statement(
            conn,
            "popular:credit_card",
            (today - timedelta(days=3)).isoformat(),
            closing=4530000,
            due=(today + timedelta(days=3)).isoformat(),
        )

    cli.main(["sync"])

    out = capsys.readouterr().out
    assert "Payments to avoid interest:" in out
    assert ": paga RD$ 45,300 antes del " in out  # spanish-ui


def _downloaded(
    tmp_path: Path, name: str = "statement january.pdf", data: bytes = b"%PDF-1"
) -> Path:
    folder = tmp_path / "downloads"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path


def _read_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_CUENTA_DOP)


def test_import_copies_and_processes(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    _read_account(monkeypatch)

    assert cli.main(["import", str(source)]) == 0

    assert "statement january.pdf: parsed" in capsys.readouterr().out
    (copy,) = (data_dir / "raw" / "imported").rglob("*.pdf")
    assert copy.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert stat.S_IMODE(copy.parent.stat().st_mode) == 0o700
    assert copy.parent.name == datetime.now(UTC).strftime("%Y-%m")  # the same source as the cli
    assert source.exists()  # the original is not touched
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        document = conn.execute("SELECT source, status, path FROM documents").fetchone()
        account = conn.execute("SELECT kind, key FROM accounts").fetchone()
        statements = conn.execute("SELECT count(*) FROM statements").fetchone()[0]
    assert document == ("imported", "parsed", str(copy))
    assert account == ("checking", "popular:checking:123456789")
    assert statements == 1


def test_import_twice_does_not_duplicate(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    other_copy = _downloaded(tmp_path, "other download.pdf", b"%PDF-2")  # same statement
    _read_account(monkeypatch)

    assert cli.main(["import", str(source)]) == 0
    assert cli.main(["import", str(source), str(other_copy)]) == 0

    output = capsys.readouterr().out
    assert "statement january.pdf: already imported (status: parsed)" in output
    assert "other download.pdf: duplicate" in output
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        documents = conn.execute("SELECT status FROM documents ORDER BY id").fetchall()
        statements = conn.execute("SELECT count(*) FROM statements").fetchone()[0]
    assert documents == [("parsed",), ("duplicate",)]
    assert statements == 1
    assert len(list((data_dir / "raw" / "imported").rglob("*.pdf"))) == 2


def test_import_same_name_does_not_overwrite_the_previous_copy(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _read_account(monkeypatch)
    first = _downloaded(tmp_path, "statement.pdf", b"%PDF-1")
    assert cli.main(["import", str(first)]) == 0
    second = _downloaded(tmp_path, "statement.pdf", b"%PDF-2")
    assert cli.main(["import", str(second)]) == 0  # the same statement: duplicate is not a failure
    copies = sorted(p.read_bytes() for p in (data_dir / "raw" / "imported").rglob("*.pdf"))
    assert copies == [b"%PDF-1", b"%PDF-2"]
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        statuses = conn.execute("SELECT status FROM documents ORDER BY id").fetchall()
    assert statuses == [("parsed",), ("duplicate",)]


def _read_bhd_savings(monkeypatch: pytest.MonkeyPatch) -> None:
    """BHD savings statements: "portal" in the name is the portal download."""
    monkeypatch.setattr(
        cli.pdf,
        "read_pages",
        lambda path, pw: (
            samples.BHD_AHORRO_PORTAL_PAGES if "portal" in path.name else samples.BHD_AHORRO_PAGES
        ),
    )


def test_import_bhd_portal_savings_statement(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_bhd_savings(monkeypatch)
    assert cli.main(["import", str(_downloaded(tmp_path, "savings portal january.pdf"))]) == 0
    assert "savings portal january.pdf: parsed" in capsys.readouterr().out
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        accounts = conn.execute("SELECT kind, key FROM accounts").fetchall()
        transactions = conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
    assert accounts == [("savings", "bhd:savings:999-1")]
    assert transactions == 3


def test_import_from_the_portal_an_already_saved_savings_statement_is_duplicate(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_bhd_savings(monkeypatch)
    email = _downloaded(tmp_path, "savings email january.pdf", b"%PDF-1")
    portal = _downloaded(tmp_path, "savings portal january.pdf", b"%PDF-2")

    assert cli.main(["import", str(email)]) == 0
    assert cli.main(["import", str(portal)]) == 0

    assert "savings portal january.pdf: duplicate" in capsys.readouterr().out
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        statuses = conn.execute("SELECT status FROM documents ORDER BY id").fetchall()
        statements = conn.execute("SELECT count(*) FROM statements").fetchone()[0]
        accounts = conn.execute("SELECT count(*) FROM accounts").fetchone()[0]
    assert statuses == [("parsed",), ("duplicate",)]
    assert (statements, accounts) == (1, 1)


def test_import_rejects_what_is_not_a_pdf(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_account(monkeypatch)
    missing = tmp_path / "missing.pdf"
    text = _downloaded(tmp_path, "notes.pdf", b"not a pdf")
    good = _downloaded(tmp_path)

    assert cli.main(["import", str(missing), str(text), str(good)]) == 1

    captured = capsys.readouterr()
    assert "missing.pdf" in captured.err
    assert "notes.pdf" in captured.err
    assert "statement january.pdf: parsed" in captured.out
    assert len(list((data_dir / "raw" / "imported").rglob("*.pdf"))) == 1


def test_import_reports_a_statement_that_does_not_balance(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(
        cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_CUENTA_WRONG_CLOSING
    )
    assert cli.main(["import", str(_downloaded(tmp_path))]) == 1
    assert "statement january.pdf: invalid" in capsys.readouterr().out


def test_import_reprocesses_an_already_registered_unparsed_file(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: (samples.UNKNOWN,))
    assert cli.main(["import", str(source)]) == 1
    assert "statement january.pdf: unsupported" in capsys.readouterr().out

    _read_account(monkeypatch)  # there is a parser for this statement now
    assert cli.main(["import", str(source)]) == 0

    assert (
        "statement january.pdf: parsed (already imported, reprocessed)" in capsys.readouterr().out
    )
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        documents = conn.execute("SELECT status FROM documents").fetchall()
        statements = conn.execute("SELECT count(*) FROM statements").fetchone()[0]
    assert (documents, statements) == ([("parsed",)], 1)


def test_import_already_registered_that_still_does_not_balance_is_a_failure(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: (samples.UNKNOWN,))
    assert cli.main(["import", str(source)]) == 1
    assert cli.main(["import", str(source)]) == 1
    assert (
        "statement january.pdf: unsupported (already imported, reprocessed"
        in capsys.readouterr().out
    )


def test_import_registered_pending_is_parsed(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    data_dir.mkdir(mode=0o700)
    with closing(db.connect(data_dir / "michelito.db")) as conn:
        importer.register(conn, source, data_dir / "raw", datetime.now(UTC))  # left pending
    _read_account(monkeypatch)
    assert cli.main(["import", str(source)]) == 0
    assert (
        "statement january.pdf: parsed (already imported, reprocessed)" in capsys.readouterr().out
    )


def _read_savings_printout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Printouts of a dollar savings account (with a bare "$", like the portal)."""
    header = "Cuenta de Ahorro / 987654321"  # spanish-data
    first = samples.popular_web(samples.WEB_ROWS, account=header)
    later = samples.popular_web(samples.WEB_ROWS_LATER, account=header)
    monkeypatch.setattr(
        cli.pdf, "read_pages", lambda path, pw: later if "later" in path.name else first
    )


def _statement_currencies(data_dir: Path) -> list[str]:
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        return [row[0] for row in conn.execute("SELECT currency FROM statements ORDER BY id")]


def test_import_currency_sets_the_printout_currency_and_remembers_it(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_savings_printout(monkeypatch)
    first = _downloaded(tmp_path, "savings january.pdf", b"%PDF-1")
    later = _downloaded(tmp_path, "savings later.pdf", b"%PDF-2")

    assert cli.main(["import", "--currency", "USD", str(first)]) == 0
    assert cli.main(["import", str(later)]) == 0

    assert "savings later.pdf: parsed" in capsys.readouterr().out
    assert _statement_currencies(data_dir) == ["USD", "USD"]


def test_import_currency_notes_when_the_account_currency_changes(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_savings_printout(monkeypatch)
    first = _downloaded(tmp_path, "savings january.pdf", b"%PDF-1")
    later = _downloaded(tmp_path, "savings later.pdf", b"%PDF-2")
    again = _downloaded(tmp_path, "savings later again.pdf", b"%PDF-3")

    assert cli.main(["import", "--currency", "USD", str(first)]) == 0
    assert "savings january.pdf: parsed (account currency: USD)" in capsys.readouterr().out
    assert cli.main(["import", "--currency", "DOP", str(later)]) == 0
    assert "savings later.pdf: parsed (account currency: USD → DOP)" in (capsys.readouterr().out)
    assert cli.main(["import", "--currency", "DOP", str(again)]) == 0
    assert "account currency" not in capsys.readouterr().out  # it did not change


def test_import_without_currency_stays_in_dop(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _read_savings_printout(monkeypatch)
    assert cli.main(["import", str(_downloaded(tmp_path, "savings january.pdf"))]) == 0
    assert _statement_currencies(data_dir) == ["DOP"]


def test_import_currency_does_not_apply_to_an_official_statement(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_account(monkeypatch)
    assert cli.main(["import", "--currency", "USD", str(_downloaded(tmp_path))]) == 0
    assert "statement january.pdf: parsed (--currency does not apply to popular_account)" in (
        capsys.readouterr().out
    )
    assert _statement_currencies(data_dir) == ["DOP"]


def test_import_currency_does_not_change_what_is_saved(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_savings_printout(monkeypatch)
    source = _downloaded(tmp_path, "savings january.pdf")
    assert cli.main(["import", str(source)]) == 0
    assert cli.main(["import", "--currency", "USD", str(source)]) == 0
    assert "--currency does not change what is already saved" in capsys.readouterr().out
    assert _statement_currencies(data_dir) == ["DOP"]


@pytest.mark.parametrize("value", ["EUR", "", "pesos"])  # spanish-data
def test_import_rejects_an_unknown_currency(
    value: str, data_dir: Path, secrets, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["import", "--currency", value, str(_downloaded(tmp_path))])


def test_importer_leaves_no_copy_if_registering_fails(data_dir: Path, tmp_path: Path) -> None:
    source = _downloaded(tmp_path)
    data_dir.mkdir(mode=0o700)
    raw = data_dir / "raw"
    with closing(db.connect(data_dir / "michelito.db")) as conn:
        conn.execute(
            "CREATE TRIGGER no_docs BEFORE INSERT ON documents BEGIN SELECT RAISE(ABORT, 'x'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            importer.register(conn, source, raw, datetime.now(UTC))
        assert conn.execute("SELECT count(*) FROM gmail_messages").fetchone()[0] == 0
    assert list((raw / "imported").rglob("*.pdf")) == []


def test_importer_leaves_no_record_if_copying_fails(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _downloaded(tmp_path)
    data_dir.mkdir(mode=0o700)

    def broken(path: Path, data: bytes) -> None:
        path.write_bytes(data[:2])  # half-written copy
        raise OSError("disk full")

    monkeypatch.setattr(importer, "write_private", broken)
    with closing(db.connect(data_dir / "michelito.db")) as conn:
        with pytest.raises(OSError):
            importer.register(conn, source, data_dir / "raw", datetime.now(UTC))
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
    assert list((data_dir / "raw" / "imported").rglob("*.pdf")) == []


def test_import_portal_printout_alongside_the_statement(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    pages = {"statement.pdf": samples.POPULAR_CUENTA_DOP, "printout.pdf": samples.POPULAR_WEB}
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: pages[path.name.split("_")[-1]])
    statement = _downloaded(tmp_path, "statement.pdf", b"%PDF-1")
    printout = _downloaded(tmp_path, "printout.pdf", b"%PDF-2")

    assert cli.main(["import", str(statement), str(printout)]) == 0

    output = capsys.readouterr().out
    assert "statement.pdf: parsed" in output
    assert "printout.pdf: parsed" in output
    with closing(db.connect(data_dir / "michelito.db")) as conn:
        parsers = [r[0] for r in conn.execute("SELECT parser FROM statements ORDER BY id")]
        movements = [m for m in spending.load_all(conn) if m.account.endswith("123456789")]
    assert parsers == ["popular_account", "popular_web"]
    # 5 from the statement + 4 from the printout outside its period; January 12 is not repeated.
    assert len(movements) == 9


def test_import_printout_with_broken_balances_does_not_get_in(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_WEB_BROKEN_CHAIN)
    assert cli.main(["import", str(_downloaded(tmp_path, "printout.pdf"))]) == 1
    assert "printout.pdf: invalid" in capsys.readouterr().out
    with closing(db.connect(data_dir / "michelito.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0


def _read_banreservas(monkeypatch: pytest.MonkeyPatch, pages: tuple) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: pages)


def test_import_banreservas_statement(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_banreservas(monkeypatch, samples.BANRESERVAS)

    assert cli.main(["import", str(_downloaded(tmp_path, "january.pdf"))]) == 0

    assert "january.pdf: parsed" in capsys.readouterr().out
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        account = conn.execute("SELECT institution, kind, key FROM accounts").fetchone()
        statement = conn.execute(
            "SELECT parser, currency, period_start, period_end, previous_balance_cents, "
            "closing_balance_cents, transaction_count FROM statements"
        ).fetchone()
        first = conn.execute(
            "SELECT description, direction, amount_cents FROM transactions ORDER BY sequence"
        ).fetchone()
    assert account == ("banreservas", "savings", "banreservas:savings:0000000000")
    assert statement == (
        "banreservas_account", "DOP", "2026-01-01", "2026-01-31", 1000000, 140859, 7
    )  # fmt: skip
    assert first == ("TRANSFERENCIA DE PERSONA INVENTADA OTRO APELLIDO", "credit", 2500000)


def test_import_banreservas_with_a_broken_chain_is_not_saved(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_banreservas(monkeypatch, samples.BANRESERVAS_BROKEN_CHAIN)

    assert cli.main(["import", str(_downloaded(tmp_path, "january.pdf"))]) == 1

    assert "january.pdf: invalid" in capsys.readouterr().out
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        assert conn.execute("SELECT count(*) FROM statements").fetchone()[0] == 0


def test_import_banreservas_current_month_then_the_complete_one(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_banreservas(monkeypatch, samples.BANRESERVAS_PARTIAL)
    assert cli.main(["import", str(_downloaded(tmp_path, "january partial.pdf"))]) == 0
    _read_banreservas(monkeypatch, samples.BANRESERVAS)
    assert cli.main(["import", str(_downloaded(tmp_path, "january.pdf", b"%PDF-2"))]) == 0

    out = capsys.readouterr().out
    assert "january partial.pdf: parsed" in out
    assert "january.pdf: parsed" in out  # the complete one is not a duplicate
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        stored = conn.execute(
            "SELECT parser, period_start, period_end FROM statements ORDER BY id"
        ).fetchall()
    assert stored == [
        ("banreservas_partial", "2026-01-01", "2026-01-27"),
        ("banreservas_account", "2026-01-01", "2026-01-31"),
    ]


def _read_pages(monkeypatch: pytest.MonkeyPatch, pages: tuple) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: pages)


def test_import_bhd_savings_current_month_then_the_complete_one(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_pages(monkeypatch, samples.BHD_AHORRO_PORTAL_PARTIAL_PAGES)
    assert cli.main(["import", str(_downloaded(tmp_path, "savings partial.pdf"))]) == 0
    assert cli.main(["import", str(_downloaded(tmp_path, "again.pdf", b"%PDF-2"))]) == 0
    _read_pages(monkeypatch, samples.BHD_AHORRO_PORTAL_PAGES)
    assert cli.main(["import", str(_downloaded(tmp_path, "savings january.pdf", b"%PDF-3"))]) == 0

    out = capsys.readouterr().out
    assert "savings partial.pdf: parsed" in out
    assert "again.pdf: duplicate" in out
    assert "savings january.pdf: parsed" in out  # the complete one is not a duplicate
    with closing(sqlite3.connect(data_dir / "michelito.db")) as connection:
        stored = connection.execute(
            "SELECT parser, period_start, period_end, closing_balance_cents FROM statements "
            "ORDER BY id"
        ).fetchall()
    assert stored == [
        ("bhd_savings_partial", "2026-01-01", "2026-01-10", 1200000),
        ("bhd_savings", None, "2026-01-31", 1200050),
    ]


def test_import_a_pdf_with_several_statements(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_HISTORICO)
    source = _downloaded(tmp_path, "history.pdf")
    assert cli.main(["import", str(source)]) == 0
    assert cli.main(["import", str(source)]) == 0  # the same file: not registered again
    output = capsys.readouterr().out
    detail = "3 de 3 estados guardados (8 transacciones)"  # spanish-ui
    assert f"history.pdf: parsed ({detail})" in output
    assert "history.pdf: already imported (status: parsed)" in output
    assert len(list((data_dir / "raw" / "imported").rglob("*.pdf"))) == 1
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        statements = conn.execute("SELECT COUNT(DISTINCT document_id), COUNT(*) FROM statements")
        assert (documents, tuple(statements.fetchone())) == (1, (1, 3))


def test_import_a_pdf_with_an_unbalanced_statement_and_retry_it(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_HISTORICO_BAD_DIC)
    source = _downloaded(tmp_path, "history.pdf")
    assert cli.main(["import", str(source)]) == 1  # two got in, but one is missing
    assert "2025-12-12 invalid" in capsys.readouterr().out

    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_HISTORICO)
    assert cli.main(["import", str(source)]) == 0  # already imported: retries the missing one
    output = capsys.readouterr().out
    saved = "3 de 3 estados guardados"  # spanish-ui
    assert f"history.pdf: parsed (already imported, reprocessed; {saved}" in output
    with closing(sqlite3.connect(data_dir / "michelito.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 3
