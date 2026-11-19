"""`finanzas demo` y `FINANZAS_MODO=demo`: la demo nunca toca lo real."""

from __future__ import annotations

from pathlib import Path

import pytest

from finanzas import cli


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    real = tmp_path / "datos-reales"
    monkeypatch.setenv("FINANZAS_DATA_DIR", str(real))
    monkeypatch.delenv("FINANZAS_MODO", raising=False)
    return real


def test_demo_refuses_the_real_data_folder(_data_dir: Path, capsys) -> None:
    for folder in (_data_dir, _data_dir / "demo", _data_dir.parent):
        assert cli.main(["demo", "--datos", str(folder)]) == 2
        assert "datos reales" in capsys.readouterr().err


def test_demo_refuses_the_board_ports(tmp_path: Path, capsys) -> None:
    for port in ("8501", "8500"):
        assert cli.main(["demo", "--puerto", port, "--datos", str(tmp_path / "d")]) == 2
    assert "board local" in capsys.readouterr().err


def test_demo_mode_only_allows_demo_commands(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("FINANZAS_MODO", "demo")
    for argv in (["sync"], ["auth"], ["report"], ["secret", "pdf-password"], ["gastos"]):
        assert cli.main(argv) == 2
        assert "solo funcionan" in capsys.readouterr().err


def test_board_in_demo_mode_starts_the_demo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = {}
    monkeypatch.setenv("FINANZAS_MODO", "demo")
    monkeypatch.setattr(cli.cli_demo, "cmd_demo", lambda args, paths: seen.setdefault("p", args))
    cli.main(["board", "--puerto", "8700"])
    assert seen["p"].puerto == 8700


def test_demo_refuses_the_default_data_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "casa"))
    default = tmp_path / "casa" / "finanzas-data"
    assert cli.main(["demo", "--datos", str(default / "demo")]) == 2
    assert "datos reales" in capsys.readouterr().err


def test_board_in_demo_mode_without_port_uses_the_demo_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}
    monkeypatch.setenv("FINANZAS_MODO", "demo")
    monkeypatch.setattr(cli.cli_demo, "cmd_demo", lambda args, paths: seen.setdefault("p", args))
    cli.main(["board"])
    assert seen["p"].puerto == cli.cli_demo.DEFAULT_PORT


def test_bad_numeric_env_only_breaks_the_demo_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("FINANZAS_DEMO_PUERTO", "no-es-numero")
    assert cli.main(["opiniones", "--datos", str(tmp_path / "x")]) == 1  # sigue funcionando
    with pytest.raises(SystemExit) as exited:
        cli.main(["demo", "--datos", str(tmp_path / "d")])
    assert exited.value.code == 2
    assert "invalid int value" in capsys.readouterr().err
