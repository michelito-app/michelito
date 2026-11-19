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

from finanzas import cli, config, db, importer, vault
from finanzas.analysis import bcrd, rates, spending
from finanzas.parsers.common import Page
from finanzas.web.accounts import DuePayment, due_text
from tests import samples
from tests.fakes import FakeClient, make_message
from tests.test_spending import seed
from tests.test_web_accounts import add_statement


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "datos"
    monkeypatch.setenv("FINANZAS_DATA_DIR", str(root))
    return root


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    store = {vault.PDF_PASSWORD: "clave", vault.GMAIL_TOKEN: "{}"}
    monkeypatch.setattr("keyring.get_password", lambda service, name: store.get(name))
    monkeypatch.setattr(
        "keyring.set_password", lambda service, name, value: store.__setitem__(name, value)
    )
    return store


def test_report_on_empty_data_dir(data_dir: Path, secrets, capsys) -> None:
    assert cli.main(["report"]) == 0
    assert "Sin alertas." in capsys.readouterr().out
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((data_dir / "finanzas.db").stat().st_mode) == 0o600


def test_missing_secret_exits_with_hint(data_dir: Path, secrets, capsys) -> None:
    del secrets[vault.PDF_PASSWORD]
    assert cli.main(["parse"]) == 2
    assert "finanzas secret pdf-password" in capsys.readouterr().err


def test_auth_stores_client_config_and_reuses_it(
    tmp_path: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    seen: list[dict] = []
    monkeypatch.setattr(cli, "authorize", lambda config: seen.append(config) or "token-nuevo")
    client_file = tmp_path / "client_secret.json"
    client_file.write_text('{"installed": {"client_id": "id"}}')

    assert cli.main(["auth", "--client-secrets", str(client_file)]) == 0
    assert secrets[vault.GMAIL_CLIENT] == '{"installed": {"client_id": "id"}}'
    assert secrets[vault.GMAIL_TOKEN] == "token-nuevo"

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
    assert "no existe" in error and "Google Cloud" in error


def test_auth_with_invalid_json_explains(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "client_secret.json"
    broken.write_text("esto no es json")
    assert cli.main(["auth", "--client-secrets", str(broken)]) == 1
    assert "no es un JSON válido" in capsys.readouterr().err


def test_secret_command_stores_value(secrets, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt: "nueva")
    assert cli.main(["secret", vault.PDF_PASSWORD]) == 0
    assert secrets[vault.PDF_PASSWORD] == "nueva"
    monkeypatch.setattr("getpass.getpass", lambda prompt: "")
    assert cli.main(["secret", vault.PDF_PASSWORD]) == 1


def test_sync_runs_the_whole_pipeline(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    client = FakeClient(make_message("m1", {"estado.pdf": b"%PDF-falso"}))
    monkeypatch.setattr(cli, "build_client", lambda token, save: client)

    def reader(path: Path, password: str) -> tuple[Page, ...]:
        assert password == "clave"
        return samples.POPULAR_PAGES

    monkeypatch.setattr(cli.pdf, "read_pages", reader)
    notices: list[list[str]] = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(cli.subprocess, "run", lambda args, check: notices.append(args))

    exit_code = cli.main(["sync", "--notify"])

    output = capsys.readouterr().out
    assert "1 mensajes nuevos" in output
    assert "parsed: 1" in output
    assert "POPULAR VISA PRESTIGE DOP: 1 cortes" in output
    assert exit_code == 1  # el corte sintético es de 2026-01: queda vencido
    assert notices and "1 estados validados" in notices[0][-1]


def test_extract_single_source(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli, "build_client", lambda token, save: FakeClient())
    assert cli.main(["extract", "--source", "popular"]) == 0
    assert "popular: 0 mensajes nuevos" in capsys.readouterr().out


class _QueryLog(FakeClient):
    """Un cliente sin correos que anota qué búsquedas de Gmail se le piden."""

    def __init__(self) -> None:
        super().__init__()
        self.queries: list[str] = []

    def list_message_ids(self, query: str):  # noqa: ANN201 - mismo tipo que FakeClient
        self.queries.append(query)
        return super().list_message_ids(query)


def test_sync_without_sources_file_asks_gmail_the_default_sources(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    client = _QueryLog()
    monkeypatch.setattr(cli, "build_client", lambda token, save: client)
    cli.main(["sync"])
    assert client.queries == [s.query for s in config.DEFAULT_SOURCES]
    assert "afp_crecer: 0 mensajes nuevos" in capsys.readouterr().out


def test_sync_uses_only_the_sources_of_the_user_file(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir.mkdir(parents=True)
    (data_dir / "fuentes.toml").write_text(
        '[[fuente]]\nnombre = "banco"\nconsulta = "from:x@banco.example"\nextensiones = [".pdf"]\n'
    )
    client = _QueryLog()
    monkeypatch.setattr(cli, "build_client", lambda token, save: client)
    cli.main(["sync"])
    assert client.queries == ["from:x@banco.example"]
    assert cli.main(["extract", "--source", "banco"]) == 0
    assert cli.main(["extract", "--source", "popular"]) == 2
    assert "fuente desconocida: popular; las configuradas son: banco" in capsys.readouterr().err


def test_broken_sources_file_stops_with_a_hint(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir.mkdir(parents=True)
    (data_dir / "fuentes.toml").write_text("[[fuente]]\nnombre = 1\n")
    monkeypatch.setattr(cli, "build_client", lambda token, save: pytest.fail("no debe conectar"))
    assert cli.main(["sync"]) == 2
    assert cli.main(["extract"]) == 2
    assert "fuentes.toml" in capsys.readouterr().err


def test_parse_archives_the_archive_only_sources_of_the_user_file(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir.mkdir(parents=True)
    (data_dir / "fuentes.toml").write_text(
        '[[fuente]]\nnombre = "afp-x"\nconsulta = "from:afp@afp.example"\n'
        'extensiones = [".pdf"]\ninterpretar = false\n'
    )
    seen: dict[str, object] = {}

    def spy(conn, password, read_pages, **kwargs):  # noqa: ANN001, ANN202
        seen.update(kwargs)
        return Counter()

    monkeypatch.setattr(cli.ingest, "process_documents", spy)
    assert cli.main(["parse"]) == 0
    # Las AFP de omisión siguen solo archivadas aunque el archivo ya no las liste.
    assert seen["archive_only"] == config.ARCHIVE_ONLY | {"afp-x"}


def test_gastos_without_data(data_dir: Path, capsys) -> None:
    assert cli.main(["gastos"]) == 0
    out = capsys.readouterr().out
    assert "No hay estados de tarjeta" in out
    assert not (data_dir / "reportes").exists()  # ya no se escribe ninguna página


def test_gastos_with_data(data_dir: Path, capsys) -> None:
    data_dir.mkdir(mode=0o700)
    with closing(db.connect(data_dir / "finanzas.db")) as conn:
        seed(conn)
    assert cli.main(["gastos", "--meses", "3"]) == 0
    out = capsys.readouterr().out
    # Un solo estado por tarjeta: diciembre está incompleto y enero no ha cerrado.
    assert "Todavía no hay un mes cubierto entero" in out


def test_gastos_reads_the_holders_file(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir.mkdir(mode=0o700)
    with closing(db.connect(data_dir / "finanzas.db")) as conn:
        seed(conn)
    (data_dir / "titulares.txt").write_text("Maria Perez Inventada\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []
    original = cli.spending.load_movements

    def spy(conn, holders=()):  # noqa: ANN001, ANN202
        # Antes `tuple(holders)`: ahora llegan nombres y números aparte (`Holders`).
        seen.append(cli.transfers.as_holders(holders).names)
        return original(conn, holders)

    monkeypatch.setattr(cli.spending, "load_movements", spy)
    assert cli.main(["gastos"]) == 0
    assert seen == [("MARIA PEREZ INVENTADA",)]


def test_board_requires_built_frontend(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli, "STATIC_DIR", tmp_path / "sin-compilar")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("no debe arrancar"))
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
    assert cli.main(["board", "--puerto", "8600", "--sin-navegador"]) == 0
    ((app, kwargs),) = calls
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8600
    assert app.title == "finanzas"
    assert "http://127.0.0.1:8600" in capsys.readouterr().out


def test_board_opens_the_browser_itself(
    data_dir: Path, built_frontend: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[tuple[str, int]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_open_when_ready", lambda url, port: opened.append((url, port)))
    assert cli.main(["board", "--puerto", "8601"]) == 0
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


def test_gastos_rejects_bad_month_count(data_dir: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["gastos", "--meses", "0"])


def test_tasas_fijar(data_dir: Path, secrets, capsys) -> None:
    assert cli.main(["tasas", "--fijar", "2026-09", "64.25"]) == 0
    with closing(db.connect(data_dir / "finanzas.db")) as conn:
        loaded = rates.load(conn)
    assert loaded["2026-09"].value == Decimal("64.2500")
    assert loaded["2026-09"].source == "manual"
    assert "Septiembre 2026" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["tasas", "--fijar", "2026-13", "64"],
        ["tasas", "--fijar", "2026-00", "64"],
        ["tasas", "--fijar", "septiembre", "64"],
        ["tasas", "--fijar", "2026-09", "-1"],
        ["tasas", "--fijar", "2026-09", "0"],
        ["tasas", "--fijar", "2026-09", "abc"],
        ["tasas", "--fijar", "2026-09", "NaN"],
    ],
)
def test_tasas_rejects_bad_input(argv: list[str], data_dir: Path, secrets) -> None:
    with pytest.raises(SystemExit):
        cli.main(argv)


def test_tasas_downloads_and_keeps_manual(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    assert cli.main(["tasas", "--fijar", "2026-08", "70"]) == 0
    monkeypatch.setattr(bcrd, "fetch", lambda: b"{}")
    monkeypatch.setattr(
        bcrd,
        "parse_monthly_averages",
        lambda content: {"2026-08": Decimal("63.1"), "2026-09": Decimal("63.4")},
    )
    capsys.readouterr()
    assert cli.main(["tasas"]) == 0
    assert "Tasas BCRD: 1 meses guardados (último: Septiembre 2026 63.4000)" in (
        capsys.readouterr().out
    )
    with closing(db.connect(data_dir / "finanzas.db")) as conn:
        loaded = rates.load(conn)
    assert loaded["2026-08"].value == Decimal("70.0000")
    assert loaded["2026-09"].source == "bcrd"


@pytest.mark.parametrize("error", [OSError("sin red"), ValueError("formato")])
def test_tasas_download_failure(
    error: Exception, data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def failing_fetch() -> bytes:
        raise error

    monkeypatch.setattr(bcrd, "fetch", failing_fetch)
    assert cli.main(["tasas"]) == 1
    assert "--fijar" in capsys.readouterr().err


def test_tasas_last_shows_the_stored_rate_of_a_manual_month(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    assert cli.main(["tasas", "--fijar", "2026-09", "70"]) == 0
    monkeypatch.setattr(bcrd, "fetch", lambda: b"{}")
    monkeypatch.setattr(
        bcrd, "parse_monthly_averages", lambda content: {"2026-09": Decimal("63.4")}
    )
    capsys.readouterr()
    assert cli.main(["tasas"]) == 0
    assert "(último: Septiembre 2026 70.0000)" in capsys.readouterr().out


def test_tasas_empty_bcrd_answer_fails_with_hint(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(bcrd, "fetch", lambda: b'{"result": {"items": []}}')
    assert cli.main(["tasas"]) == 1
    err = capsys.readouterr().err
    assert "no devolvió tasas" in err and "--fijar" in err


def _due(*amounts: tuple[str, str]) -> DuePayment:
    return DuePayment(
        key="k",
        label="POPULAR VISA PRESTIGE",
        due_date=date(2026, 12, 14),
        amounts=[(currency, Decimal(value)) for currency, value in amounts],
        minimums=[],
    )


def test_due_text_one_and_two_currencies() -> None:
    assert due_text(_due(("DOP", "45300"))) == (
        "POPULAR VISA PRESTIGE: paga RD$ 45,300 antes del 14 dic para no pagar intereses"
    )
    assert due_text(_due(("DOP", "45300"), ("USD", "120.5"))) == (
        "POPULAR VISA PRESTIGE: paga RD$ 45,300 y US$ 120.50 antes del 14 dic "
        "para no pagar intereses"
    )
    early = DuePayment("k", "X", date(2026, 3, 5), [("DOP", Decimal("10"))], [])
    assert "antes del 5 mar" in due_text(early)


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
    assert "Pagos para no generar intereses:" in output
    assert f"  {due_text(payments[0])}" in output
    sent = [args[-1] for args in notices]
    assert sent[1:] == [due_text(p) for p in payments]
    assert all(args[2] == "normal" for args in notices[1:])


def test_sync_without_upcoming_payments_adds_nothing(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    notices = _sync_stubs(monkeypatch, [])

    cli.main(["sync", "--notify"])

    assert "Pagos para no generar intereses" not in capsys.readouterr().out
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
        raise sqlite3.OperationalError("base dañada")

    monkeypatch.setattr(cli, "_run_due_payments", broken)
    capsys.readouterr()
    exit_code = cli.main(["sync", "--notify"])

    captured = capsys.readouterr()
    assert "No se pudieron calcular los pagos pendientes: base dañada" in captured.err
    assert "Pagos para no generar intereses" not in captured.out
    assert exit_code == expected
    assert len(notices) == 1 and "1 estados validados" in notices[0][-1]


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
    assert "Pagos para no generar intereses:" in out
    assert ": paga RD$ 45,300 antes del " in out


def _downloaded(tmp_path: Path, name: str = "estado enero.pdf", data: bytes = b"%PDF-1") -> Path:
    folder = tmp_path / "descargas"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path


def _read_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_CUENTA_DOP)


def test_importar_copia_y_procesa(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    _read_account(monkeypatch)

    assert cli.main(["importar", str(source)]) == 0

    assert "estado enero.pdf: parsed" in capsys.readouterr().out
    (copy,) = (data_dir / "raw" / "importados").rglob("*.pdf")
    assert copy.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert stat.S_IMODE(copy.parent.stat().st_mode) == 0o700
    assert copy.parent.name == datetime.now(UTC).strftime("%Y-%m")  # la misma fuente que cli
    assert source.exists()  # el original no se toca
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        document = conn.execute("SELECT source, status, path FROM documents").fetchone()
        account = conn.execute("SELECT kind, key FROM accounts").fetchone()
        statements = conn.execute("SELECT count(*) FROM statements").fetchone()[0]
    assert document == ("importado", "parsed", str(copy))
    assert account == ("checking", "popular:checking:123456789")
    assert statements == 1


def test_importar_dos_veces_no_duplica(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    other_copy = _downloaded(tmp_path, "otra descarga.pdf", b"%PDF-2")  # mismo estado
    _read_account(monkeypatch)

    assert cli.main(["importar", str(source)]) == 0
    assert cli.main(["importar", str(source), str(other_copy)]) == 0

    output = capsys.readouterr().out
    assert "estado enero.pdf: ya importado (estado: parsed)" in output
    assert "otra descarga.pdf: duplicate" in output
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        documents = conn.execute("SELECT status FROM documents ORDER BY id").fetchall()
        statements = conn.execute("SELECT count(*) FROM statements").fetchone()[0]
    assert documents == [("parsed",), ("duplicate",)]
    assert statements == 1
    assert len(list((data_dir / "raw" / "importados").rglob("*.pdf"))) == 2


def test_importar_mismo_nombre_no_pisa_la_copia_anterior(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _read_account(monkeypatch)
    first = _downloaded(tmp_path, "estado.pdf", b"%PDF-1")
    assert cli.main(["importar", str(first)]) == 0
    second = _downloaded(tmp_path, "estado.pdf", b"%PDF-2")
    assert cli.main(["importar", str(second)]) == 0  # el mismo estado: duplicate no es fallo
    copies = sorted(p.read_bytes() for p in (data_dir / "raw" / "importados").rglob("*.pdf"))
    assert copies == [b"%PDF-1", b"%PDF-2"]
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        statuses = conn.execute("SELECT status FROM documents ORDER BY id").fetchall()
    assert statuses == [("parsed",), ("duplicate",)]


def _read_bhd_savings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estados de ahorro de BHD: "portal" en el nombre es la descarga del portal."""
    monkeypatch.setattr(
        cli.pdf,
        "read_pages",
        lambda path, pw: (
            samples.BHD_AHORRO_PORTAL_PAGES if "portal" in path.name else samples.BHD_AHORRO_PAGES
        ),
    )


def test_importar_estado_de_ahorro_del_portal_bhd(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_bhd_savings(monkeypatch)
    assert cli.main(["importar", str(_downloaded(tmp_path, "ahorro portal enero.pdf"))]) == 0
    assert "ahorro portal enero.pdf: parsed" in capsys.readouterr().out
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        accounts = conn.execute("SELECT kind, key FROM accounts").fetchall()
        transactions = conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
    assert accounts == [("savings", "bhd:savings:999-1")]
    assert transactions == 3


def test_importar_del_portal_un_estado_de_ahorro_ya_guardado_es_duplicado(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_bhd_savings(monkeypatch)
    email = _downloaded(tmp_path, "ahorro correo enero.pdf", b"%PDF-1")
    portal = _downloaded(tmp_path, "ahorro portal enero.pdf", b"%PDF-2")

    assert cli.main(["importar", str(email)]) == 0
    assert cli.main(["importar", str(portal)]) == 0

    assert "ahorro portal enero.pdf: duplicate" in capsys.readouterr().out
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        statuses = conn.execute("SELECT status FROM documents ORDER BY id").fetchall()
        statements = conn.execute("SELECT count(*) FROM statements").fetchone()[0]
        accounts = conn.execute("SELECT count(*) FROM accounts").fetchone()[0]
    assert statuses == [("parsed",), ("duplicate",)]
    assert (statements, accounts) == (1, 1)


def test_importar_rechaza_lo_que_no_es_pdf(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_account(monkeypatch)
    missing = tmp_path / "no-existe.pdf"
    text = _downloaded(tmp_path, "notas.pdf", b"no soy un pdf")
    good = _downloaded(tmp_path)

    assert cli.main(["importar", str(missing), str(text), str(good)]) == 1

    captured = capsys.readouterr()
    assert "no-existe.pdf" in captured.err
    assert "notas.pdf" in captured.err
    assert "estado enero.pdf: parsed" in captured.out
    assert len(list((data_dir / "raw" / "importados").rglob("*.pdf"))) == 1


def test_importar_reporta_un_estado_que_no_cuadra(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(
        cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_CUENTA_WRONG_CLOSING
    )
    assert cli.main(["importar", str(_downloaded(tmp_path))]) == 1
    assert "estado enero.pdf: invalid" in capsys.readouterr().out


def test_importar_reprocesa_un_archivo_ya_registrado_sin_interpretar(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: (samples.UNKNOWN,))
    assert cli.main(["importar", str(source)]) == 1
    assert "estado enero.pdf: unsupported" in capsys.readouterr().out

    _read_account(monkeypatch)  # ya hay un parser para este estado
    assert cli.main(["importar", str(source)]) == 0

    assert "estado enero.pdf: parsed (ya importado, reprocesado)" in capsys.readouterr().out
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        documents = conn.execute("SELECT status FROM documents").fetchall()
        statements = conn.execute("SELECT count(*) FROM statements").fetchone()[0]
    assert (documents, statements) == ([("parsed",)], 1)


def test_importar_ya_registrado_que_sigue_sin_cuadrar_es_fallo(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: (samples.UNKNOWN,))
    assert cli.main(["importar", str(source)]) == 1
    assert cli.main(["importar", str(source)]) == 1
    assert "estado enero.pdf: unsupported (ya importado, reprocesado" in capsys.readouterr().out


def test_importar_pendiente_registrado_se_interpreta(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    source = _downloaded(tmp_path)
    data_dir.mkdir(mode=0o700)
    with closing(db.connect(data_dir / "finanzas.db")) as conn:
        importer.register(conn, source, data_dir / "raw", datetime.now(UTC))  # queda pending
    _read_account(monkeypatch)
    assert cli.main(["importar", str(source)]) == 0
    assert "estado enero.pdf: parsed (ya importado, reprocesado)" in capsys.readouterr().out


def _read_savings_printout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Impresiones de una cuenta de ahorro en dólares (con "$" a secas, como el portal)."""
    header = "Cuenta de Ahorro / 987654321"
    first = samples.popular_web(samples.WEB_ROWS, account=header)
    later = samples.popular_web(samples.WEB_ROWS_LATER, account=header)
    monkeypatch.setattr(
        cli.pdf, "read_pages", lambda path, pw: later if "luego" in path.name else first
    )


def _statement_currencies(data_dir: Path) -> list[str]:
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        return [row[0] for row in conn.execute("SELECT currency FROM statements ORDER BY id")]


def test_importar_moneda_fija_la_de_la_impresion_y_la_recuerda(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_savings_printout(monkeypatch)
    first = _downloaded(tmp_path, "ahorro enero.pdf", b"%PDF-1")
    later = _downloaded(tmp_path, "ahorro luego.pdf", b"%PDF-2")

    assert cli.main(["importar", "--moneda", "USD", str(first)]) == 0
    assert cli.main(["importar", str(later)]) == 0

    assert "ahorro luego.pdf: parsed" in capsys.readouterr().out
    assert _statement_currencies(data_dir) == ["USD", "USD"]


def test_importar_moneda_avisa_cuando_cambia_la_de_la_cuenta(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_savings_printout(monkeypatch)
    first = _downloaded(tmp_path, "ahorro enero.pdf", b"%PDF-1")
    later = _downloaded(tmp_path, "ahorro luego.pdf", b"%PDF-2")
    again = _downloaded(tmp_path, "ahorro luego otra.pdf", b"%PDF-3")

    assert cli.main(["importar", "--moneda", "USD", str(first)]) == 0
    assert "ahorro enero.pdf: parsed (moneda de la cuenta: USD)" in capsys.readouterr().out
    assert cli.main(["importar", "--moneda", "DOP", str(later)]) == 0
    assert "ahorro luego.pdf: parsed (moneda de la cuenta: USD → DOP)" in (capsys.readouterr().out)
    assert cli.main(["importar", "--moneda", "DOP", str(again)]) == 0
    assert "moneda de la cuenta" not in capsys.readouterr().out  # no cambió


def test_importar_sin_moneda_queda_en_pesos(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _read_savings_printout(monkeypatch)
    assert cli.main(["importar", str(_downloaded(tmp_path, "ahorro enero.pdf"))]) == 0
    assert _statement_currencies(data_dir) == ["DOP"]


def test_importar_moneda_no_aplica_a_un_estado_oficial(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_account(monkeypatch)
    assert cli.main(["importar", "--moneda", "USD", str(_downloaded(tmp_path))]) == 0
    assert "estado enero.pdf: parsed (--moneda no aplica a popular_cuenta)" in (
        capsys.readouterr().out
    )
    assert _statement_currencies(data_dir) == ["DOP"]


def test_importar_moneda_no_cambia_lo_ya_guardado(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_savings_printout(monkeypatch)
    source = _downloaded(tmp_path, "ahorro enero.pdf")
    assert cli.main(["importar", str(source)]) == 0
    assert cli.main(["importar", "--moneda", "USD", str(source)]) == 0
    assert "--moneda no cambia lo ya guardado" in capsys.readouterr().out
    assert _statement_currencies(data_dir) == ["DOP"]


@pytest.mark.parametrize("value", ["EUR", "", "pesos"])
def test_importar_rechaza_una_moneda_desconocida(
    value: str, data_dir: Path, secrets, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["importar", "--moneda", value, str(_downloaded(tmp_path))])


def test_importer_sin_copia_si_falla_el_registro(data_dir: Path, tmp_path: Path) -> None:
    source = _downloaded(tmp_path)
    data_dir.mkdir(mode=0o700)
    raw = data_dir / "raw"
    with closing(db.connect(data_dir / "finanzas.db")) as conn:
        conn.execute(
            "CREATE TRIGGER no_docs BEFORE INSERT ON documents BEGIN SELECT RAISE(ABORT, 'x'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            importer.register(conn, source, raw, datetime.now(UTC))
        assert conn.execute("SELECT count(*) FROM gmail_messages").fetchone()[0] == 0
    assert list((raw / "importados").rglob("*.pdf")) == []


def test_importer_sin_registro_si_falla_la_copia(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _downloaded(tmp_path)
    data_dir.mkdir(mode=0o700)

    def broken(path: Path, data: bytes) -> None:
        path.write_bytes(data[:2])  # copia a medias
        raise OSError("disco lleno")

    monkeypatch.setattr(importer, "write_private", broken)
    with closing(db.connect(data_dir / "finanzas.db")) as conn:
        with pytest.raises(OSError):
            importer.register(conn, source, data_dir / "raw", datetime.now(UTC))
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
    assert list((data_dir / "raw" / "importados").rglob("*.pdf")) == []


def test_importar_impresion_del_portal_junto_al_estado(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    pages = {"estado.pdf": samples.POPULAR_CUENTA_DOP, "impresion.pdf": samples.POPULAR_WEB}
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: pages[path.name.split("_")[-1]])
    statement = _downloaded(tmp_path, "estado.pdf", b"%PDF-1")
    printout = _downloaded(tmp_path, "impresion.pdf", b"%PDF-2")

    assert cli.main(["importar", str(statement), str(printout)]) == 0

    output = capsys.readouterr().out
    assert "estado.pdf: parsed" in output
    assert "impresion.pdf: parsed" in output
    with closing(db.connect(data_dir / "finanzas.db")) as conn:
        parsers = [r[0] for r in conn.execute("SELECT parser FROM statements ORDER BY id")]
        movements = [m for m in spending.load_all(conn) if m.account.endswith("123456789")]
    assert parsers == ["popular_cuenta", "popular_web"]
    # 5 del estado + 4 de la impresión fuera de su periodo; el 12 de enero no se repite.
    assert len(movements) == 9


def test_importar_impresion_con_balances_rotos_no_entra(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_WEB_BROKEN_CHAIN)
    assert cli.main(["importar", str(_downloaded(tmp_path, "impresion.pdf"))]) == 1
    assert "impresion.pdf: invalid" in capsys.readouterr().out
    with closing(db.connect(data_dir / "finanzas.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0


def _read_banreservas(monkeypatch: pytest.MonkeyPatch, pages: tuple) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: pages)


def test_importar_estado_de_banreservas(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_banreservas(monkeypatch, samples.BANRESERVAS)

    assert cli.main(["importar", str(_downloaded(tmp_path, "enero.pdf"))]) == 0

    assert "enero.pdf: parsed" in capsys.readouterr().out
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
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
        "banreservas_cuenta", "DOP", "2026-01-01", "2026-01-31", 1000000, 140859, 7
    )  # fmt: skip
    assert first == ("TRANSFERENCIA DE PERSONA INVENTADA OTRO APELLIDO", "credit", 2500000)


def test_importar_banreservas_con_cadena_rota_no_se_guarda(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_banreservas(monkeypatch, samples.BANRESERVAS_BROKEN_CHAIN)

    assert cli.main(["importar", str(_downloaded(tmp_path, "enero.pdf"))]) == 1

    assert "enero.pdf: invalid" in capsys.readouterr().out
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        assert conn.execute("SELECT count(*) FROM statements").fetchone()[0] == 0


def test_importar_banreservas_del_mes_en_curso_y_luego_el_completo(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_banreservas(monkeypatch, samples.BANRESERVAS_PARTIAL)
    assert cli.main(["importar", str(_downloaded(tmp_path, "enero parcial.pdf"))]) == 0
    _read_banreservas(monkeypatch, samples.BANRESERVAS)
    assert cli.main(["importar", str(_downloaded(tmp_path, "enero.pdf", b"%PDF-2"))]) == 0

    out = capsys.readouterr().out
    assert "enero parcial.pdf: parsed" in out
    assert "enero.pdf: parsed" in out  # el completo no es un repetido
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        stored = conn.execute(
            "SELECT parser, period_start, period_end FROM statements ORDER BY id"
        ).fetchall()
    assert stored == [
        ("banreservas_parcial", "2026-01-01", "2026-01-27"),
        ("banreservas_cuenta", "2026-01-01", "2026-01-31"),
    ]


def _read_pages(monkeypatch: pytest.MonkeyPatch, pages: tuple) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: pages)


def test_importar_bhd_ahorro_del_mes_en_curso_y_luego_el_completo(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _read_pages(monkeypatch, samples.BHD_AHORRO_PORTAL_PARTIAL_PAGES)
    assert cli.main(["importar", str(_downloaded(tmp_path, "ahorro parcial.pdf"))]) == 0
    assert cli.main(["importar", str(_downloaded(tmp_path, "otra vez.pdf", b"%PDF-2"))]) == 0
    _read_pages(monkeypatch, samples.BHD_AHORRO_PORTAL_PAGES)
    assert cli.main(["importar", str(_downloaded(tmp_path, "ahorro enero.pdf", b"%PDF-3"))]) == 0

    out = capsys.readouterr().out
    assert "ahorro parcial.pdf: parsed" in out
    assert "otra vez.pdf: duplicate" in out
    assert "ahorro enero.pdf: parsed" in out  # el completo no es un repetido
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as connection:
        stored = connection.execute(
            "SELECT parser, period_start, period_end, closing_balance_cents FROM statements "
            "ORDER BY id"
        ).fetchall()
    assert stored == [
        ("bhd_ahorro_parcial", "2026-01-01", "2026-01-10", 1200000),
        ("bhd_ahorro", None, "2026-01-31", 1200050),
    ]


def test_importar_un_pdf_con_varios_estados(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_HISTORICO)
    source = _downloaded(tmp_path, "historico.pdf")
    assert cli.main(["importar", str(source)]) == 0
    assert cli.main(["importar", str(source)]) == 0  # el mismo archivo: no se registra otra vez
    output = capsys.readouterr().out
    assert "historico.pdf: parsed (3 de 3 estados guardados (8 transacciones))" in output
    assert "historico.pdf: ya importado (estado: parsed)" in output
    assert len(list((data_dir / "raw" / "importados").rglob("*.pdf"))) == 1
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        statements = conn.execute("SELECT COUNT(DISTINCT document_id), COUNT(*) FROM statements")
        assert (documents, tuple(statements.fetchone())) == (1, (1, 3))


def test_importar_un_pdf_con_un_estado_que_no_cuadra_y_reintentarlo(
    data_dir: Path, secrets, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_HISTORICO_BAD_DIC)
    source = _downloaded(tmp_path, "historico.pdf")
    assert cli.main(["importar", str(source)]) == 1  # entraron dos, pero falta uno
    assert "2025-12-12 invalid" in capsys.readouterr().out

    monkeypatch.setattr(cli.pdf, "read_pages", lambda path, pw: samples.POPULAR_HISTORICO)
    assert cli.main(["importar", str(source)]) == 0  # ya importado: reintenta el que faltaba
    output = capsys.readouterr().out
    assert "historico.pdf: parsed (ya importado, reprocesado; 3 de 3 estados guardados" in output
    with closing(sqlite3.connect(data_dir / "finanzas.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 3
