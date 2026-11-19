"""`michelito demo` and `MICHELITO_MODE=demo`: the demo never touches anything real."""

from __future__ import annotations

from pathlib import Path

import pytest

from michelito import cli


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    real = tmp_path / "real-data"
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(real))
    monkeypatch.delenv("MICHELITO_MODE", raising=False)
    return real


def test_demo_refuses_the_real_data_folder(_data_dir: Path, capsys) -> None:
    for folder in (_data_dir, _data_dir / "demo", _data_dir.parent):
        assert cli.main(["demo", "--data", str(folder)]) == 2
        assert "real data folder" in capsys.readouterr().err


def test_demo_refuses_the_board_ports(tmp_path: Path, capsys) -> None:
    for port in ("8501", "8500"):
        assert cli.main(["demo", "--port", port, "--data", str(tmp_path / "d")]) == 2
    assert "local board" in capsys.readouterr().err


def test_demo_mode_only_allows_demo_commands(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("MICHELITO_MODE", "demo")
    for argv in (["sync"], ["auth"], ["report"], ["secret", "pdf-password"], ["spending"]):
        assert cli.main(argv) == 2
        assert "only 'demo' and 'feedback' work" in capsys.readouterr().err


def test_board_in_demo_mode_starts_the_demo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = {}
    monkeypatch.setenv("MICHELITO_MODE", "demo")
    monkeypatch.setattr(cli.cli_demo, "cmd_demo", lambda args, paths: seen.setdefault("p", args))
    cli.main(["board", "--port", "8700"])
    assert seen["p"].port == 8700


def test_demo_refuses_the_default_data_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # The current default and the pre-rename one (`legacy.DATA_DIR`).
    for name in ("michelito-data", "finanzas-data"):
        default = tmp_path / "home" / name
        assert cli.main(["demo", "--data", str(default / "demo")]) == 2
        assert "real data folder" in capsys.readouterr().err


def test_board_in_demo_mode_without_port_uses_the_demo_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}
    monkeypatch.setenv("MICHELITO_MODE", "demo")
    monkeypatch.setattr(cli.cli_demo, "cmd_demo", lambda args, paths: seen.setdefault("p", args))
    cli.main(["board"])
    assert seen["p"].port == cli.cli_demo.DEFAULT_PORT


def test_bad_numeric_env_only_breaks_the_demo_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("MICHELITO_DEMO_PORT", "not-a-number")
    assert cli.main(["feedback", "--data", str(tmp_path / "x")]) == 1  # still works
    with pytest.raises(SystemExit) as exited:
        cli.main(["demo", "--data", str(tmp_path / "d")])
    assert exited.value.code == 2
    assert "invalid int value" in capsys.readouterr().err
