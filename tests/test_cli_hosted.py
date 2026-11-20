"""`michelito hosted` and `michelito invite`: never the real data folder, outbox only locally."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from michelito import cli


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    real = tmp_path / "real-data"
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(real))
    monkeypatch.delenv("MICHELITO_MODE", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY_FILE", raising=False)
    monkeypatch.delenv("MICHELITO_HOSTED_SECRET_FILE", raising=False)
    return real


def test_invite_writes_the_email_to_the_outbox(tmp_path: Path, capsys) -> None:
    data = tmp_path / "hosted"
    argv = ["invite", "alice@example.com", "--data", str(data), "--mailer", "outbox"]
    assert cli.main(argv) == 0
    (email,) = [json.loads(p.read_text()) for p in (data / "outbox").glob("*.json")]
    assert email["to"] == "alice@example.com"
    output = capsys.readouterr()
    assert "Invitation sent" in output.out
    assert not any(ch.isdigit() for ch in output.out.replace("7 days", ""))  # no code printed
    assert cli.main(argv) == 0  # a second invitation while unused is fine


def test_invite_without_a_resend_key_fails(tmp_path: Path, capsys) -> None:
    assert cli.main(["invite", "a@example.com", "--data", str(tmp_path / "h")]) == 2
    assert "RESEND_API_KEY" in capsys.readouterr().err


def test_hosted_refuses_the_real_data_folder(_data_dir: Path, capsys) -> None:
    for folder in (_data_dir, _data_dir / "hosted", _data_dir.parent):
        argv = ["invite", "a@example.com", "--data", str(folder), "--mailer", "outbox"]
        assert cli.main(argv) == 2
        assert "real data folder" in capsys.readouterr().err


def test_the_outbox_is_refused_beyond_loopback(tmp_path: Path, capsys) -> None:
    argv = ["hosted", "--listen", "0.0.0.0", "--mailer", "outbox", "--data", str(tmp_path / "h")]
    assert cli.main(argv) == 2
    assert "only for this machine" in capsys.readouterr().err


def test_hosted_refuses_the_board_ports(tmp_path: Path, capsys) -> None:
    argv = ["hosted", "--port", "8501", "--mailer", "outbox", "--data", str(tmp_path / "h")]
    assert cli.main(argv) == 2
    assert "local board" in capsys.readouterr().err


def test_demo_servers_cannot_run_hosted_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv("MICHELITO_MODE", "demo")
    for argv in (["hosted"], ["invite", "a@example.com"]):
        assert cli.main(argv) == 2
        assert "only 'demo' and 'feedback' work" in capsys.readouterr().err
