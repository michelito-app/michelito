"""`finanzas analisis` y `finanzas insight` con la base de la demo (datos inventados)."""

import io
import json
from contextlib import closing
from pathlib import Path

import keyring
import pytest

from finanzas import cli, config, db, dossier
from finanzas.analysis import corrections, insights
from tests.e2e_server import build_demo_db

FEBRUARY = "2026-02"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "datos"
    monkeypatch.setenv("FINANZAS_DATA_DIR", str(root))
    root.mkdir(mode=0o700)
    build_demo_db(config.default_paths().database)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("estos comandos no deben leer el keyring")

    monkeypatch.setattr(keyring, "get_password", forbidden)
    return root


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def _stored(month: str = FEBRUARY) -> insights.Insight | None:
    with closing(db.connect(config.default_paths().database)) as conn:
        return insights.get(conn, month)


def _hash(accounts=None) -> str:
    with closing(db.connect(config.default_paths().database)) as conn:
        return dossier.build(conn, FEBRUARY, accounts=accounts).data_hash


class TestAnalisis:
    def test_prints_the_markdown_dossier(self, data_dir: Path, capsys) -> None:
        assert cli.main(["analisis", FEBRUARY]) == 0
        out = capsys.readouterr().out
        assert out.startswith(
            "<!-- dossier finanzas: mes=2026-02 cuentas=todas -->\n# Febrero 2026"
        )
        assert "AGENCIA FICTICIA VIAJES PUNTA CANA" in out
        assert str(data_dir) not in out

    def test_json_has_the_data_and_its_hash(self, data_dir: Path, capsys) -> None:
        assert cli.main(["analisis", FEBRUARY, "--formato", "json"]) == 0
        body = json.loads(capsys.readouterr().out)
        assert body["huella_de_datos"] == _hash()
        assert body["datos"]["mes"] == FEBRUARY

    def test_accounts_filter_and_errors(self, data_dir: Path, capsys) -> None:
        assert cli.main(["analisis", FEBRUARY, "--cuentas", "demo:credit_card"]) == 0
        assert "Cuentas: VISA DEMO ···4242." in capsys.readouterr().out
        assert cli.main(["analisis", FEBRUARY, "--cuentas", "no-existe"]) == 1
        assert "cuentas desconocidas" in capsys.readouterr().err
        assert cli.main(["analisis", "2030-01"]) == 1
        assert "sin datos" in capsys.readouterr().err
        with pytest.raises(SystemExit):
            cli.main(["analisis", "2026-13"])


class TestInsight:
    def test_save_from_stdin_with_the_data_hash(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _stdin(monkeypatch, "## Febrero\nGasté más en viajes.\n")
        assert cli.main(["insight", "guardar", FEBRUARY]) == 0
        assert "Análisis de Febrero 2026 guardado" in capsys.readouterr().out
        stored = _stored()
        assert stored.text == "## Febrero\nGasté más en viajes."
        assert (stored.data_hash, stored.accounts) == (_hash(), None)

    def test_save_from_a_file_with_accounts(self, data_dir: Path, tmp_path: Path) -> None:
        source = tmp_path / "analisis.md"
        source.write_text("Solo la tarjeta.", encoding="utf-8")
        code = cli.main(
            [
                "insight",
                "guardar",
                FEBRUARY,
                "--archivo",
                str(source),
                "--cuentas",
                "demo:credit_card",
            ]
        )
        assert code == 0
        stored = _stored()
        assert stored.accounts == ("demo:credit_card",)
        assert stored.data_hash == _hash(["demo:credit_card"])

    def test_rejects_empty_long_or_missing_input(
        self, data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _stdin(monkeypatch, "   \n")
        assert cli.main(["insight", "guardar", FEBRUARY]) == 1
        assert "vacío" in capsys.readouterr().err
        _stdin(monkeypatch, "x" * 4001)
        assert cli.main(["insight", "guardar", FEBRUARY]) == 1
        assert "4000" in capsys.readouterr().err
        assert cli.main(["insight", "guardar", FEBRUARY, "--archivo", str(tmp_path / "no")]) == 1
        assert "no existe" in capsys.readouterr().err
        _stdin(monkeypatch, "Algo.")
        assert cli.main(["insight", "guardar", "2030-01"]) == 1
        assert _stored() is None

    def test_a_terminal_stdin_without_file_is_an_error_not_a_wait(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        class Terminal(io.StringIO):
            def isatty(self) -> bool:
                return True

            def read(self, *_args) -> str:
                raise AssertionError("no debe quedarse esperando la terminal")

        monkeypatch.setattr("sys.stdin", Terminal())
        assert cli.main(["insight", "guardar", FEBRUARY]) == 1
        assert "--archivo" in capsys.readouterr().err
        assert _stored() is None

    def test_the_dossier_header_gives_the_accounts(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        header = "<!-- dossier finanzas: mes=2026-02 cuentas=demo:credit_card -->"
        _stdin(monkeypatch, f"{header}\nSolo la tarjeta.\n")
        assert cli.main(["insight", "guardar", FEBRUARY]) == 0
        stored = _stored()
        assert stored.text == "Solo la tarjeta."  # sin el encabezado
        assert stored.accounts == ("demo:credit_card",)
        assert stored.data_hash == _hash(["demo:credit_card"])

    def test_the_header_must_match_the_month_and_the_accounts(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _stdin(monkeypatch, "<!-- dossier finanzas: mes=2026-01 cuentas=todas -->\nOtro mes.")
        assert cli.main(["insight", "guardar", FEBRUARY]) == 1
        assert "2026-01" in capsys.readouterr().err
        _stdin(monkeypatch, "<!-- dossier finanzas: mes=2026-02 cuentas=todas -->\nTodas.")
        assert cli.main(["insight", "guardar", FEBRUARY, "--cuentas", "demo:credit_card"]) == 1
        assert "cuentas" in capsys.readouterr().err
        assert _stored() is None

    def test_view_says_when_the_data_changed(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        assert cli.main(["insight", "ver", FEBRUARY]) == 1
        assert "No hay análisis de Febrero 2026" in capsys.readouterr().err
        _stdin(monkeypatch, "Texto del análisis.")
        cli.main(["insight", "guardar", FEBRUARY])
        capsys.readouterr()
        assert cli.main(["insight", "ver", FEBRUARY]) == 0
        out = capsys.readouterr().out
        assert "Texto del análisis." in out and "cambiaron" not in out
        with closing(db.connect(config.default_paths().database)) as conn:
            moves = dossier.build(conn, FEBRUARY).data["movimientos"]
        agency = next(m for m in moves if m["comercio"] == "AGENCIA FICTICIA")
        with closing(db.connect(config.default_paths().database)) as conn, conn:
            corrections.set_one_off(conn, agency["huella"], True)
        assert cli.main(["insight", "ver", FEBRUARY]) == 0
        assert "Los datos cambiaron desde este análisis" in capsys.readouterr().out

    def test_delete(self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        _stdin(monkeypatch, "Borrar esto.")
        cli.main(["insight", "guardar", FEBRUARY])
        assert cli.main(["insight", "borrar", FEBRUARY]) == 0
        assert _stored() is None
        assert cli.main(["insight", "borrar", FEBRUARY]) == 1
