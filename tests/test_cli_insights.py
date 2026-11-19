"""`michelito analysis` and `michelito insight` with the demo database (made-up data)."""

import io
import json
from contextlib import closing
from pathlib import Path

import keyring
import pytest

from michelito import cli, config, db, dossier
from michelito.analysis import corrections, insights
from michelito.i18n import t
from tests.e2e_server import build_demo_db

FEBRUARY = "2026-02"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(root))
    root.mkdir(mode=0o700)
    build_demo_db(config.default_paths().database)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("these commands must not read the keyring")

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


class TestAnalysis:
    def test_prints_the_markdown_dossier(self, data_dir: Path, capsys) -> None:
        assert cli.main(["analysis", FEBRUARY]) == 0
        out = capsys.readouterr().out
        assert out.startswith(
            "<!-- michelito dossier: month=2026-02 accounts=all -->\n# Febrero 2026"  # spanish-ui
        )
        assert "AGENCIA FICTICIA VIAJES PUNTA CANA" in out
        assert str(data_dir) not in out

    def test_json_has_the_data_and_its_hash(self, data_dir: Path, capsys) -> None:
        assert cli.main(["analysis", FEBRUARY, "--format", "json"]) == 0
        body = json.loads(capsys.readouterr().out)
        assert body["data_hash"] == _hash()
        assert body["data"]["month"] == FEBRUARY

    def test_accounts_filter_and_errors(self, data_dir: Path, capsys) -> None:
        assert cli.main(["analysis", FEBRUARY, "--accounts", "demo:credit_card"]) == 0
        assert t("dossier.accounts", accounts="VISA DEMO ···4242") in capsys.readouterr().out
        assert cli.main(["analysis", FEBRUARY, "--accounts", "missing-account"]) == 1
        assert t("dossier.unknown_accounts", accounts="missing-account") in capsys.readouterr().err
        assert cli.main(["analysis", "2030-01"]) == 1
        assert "has no data" in capsys.readouterr().err
        with pytest.raises(SystemExit):
            cli.main(["analysis", "2026-13"])


class TestInsight:
    def test_save_from_stdin_with_the_data_hash(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _stdin(monkeypatch, "## February\nI spent more on travel.\n")
        assert cli.main(["insight", "save", FEBRUARY]) == 0
        assert "Analysis for February 2026 saved" in capsys.readouterr().out
        stored = _stored()
        assert stored.text == "## February\nI spent more on travel."
        assert (stored.data_hash, stored.accounts) == (_hash(), None)

    def test_save_from_a_file_with_accounts(self, data_dir: Path, tmp_path: Path) -> None:
        source = tmp_path / "analysis.md"
        source.write_text("Only the card.", encoding="utf-8")
        code = cli.main(
            [
                "insight",
                "save",
                FEBRUARY,
                "--file",
                str(source),
                "--accounts",
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
        assert cli.main(["insight", "save", FEBRUARY]) == 1
        assert "vacío" in capsys.readouterr().err  # spanish-ui
        _stdin(monkeypatch, "x" * 4001)
        assert cli.main(["insight", "save", FEBRUARY]) == 1
        assert "4000" in capsys.readouterr().err
        assert cli.main(["insight", "save", FEBRUARY, "--file", str(tmp_path / "no")]) == 1
        assert "does not exist" in capsys.readouterr().err
        _stdin(monkeypatch, "Something.")
        assert cli.main(["insight", "save", "2030-01"]) == 1
        assert _stored() is None

    def test_a_terminal_stdin_without_file_is_an_error_not_a_wait(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        class Terminal(io.StringIO):
            def isatty(self) -> bool:
                return True

            def read(self, *_args) -> str:
                raise AssertionError("must not wait on the terminal")

        monkeypatch.setattr("sys.stdin", Terminal())
        assert cli.main(["insight", "save", FEBRUARY]) == 1
        assert "--file" in capsys.readouterr().err
        assert _stored() is None

    def test_the_dossier_header_gives_the_accounts(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        header = "<!-- michelito dossier: month=2026-02 accounts=demo:credit_card -->"
        _stdin(monkeypatch, f"{header}\nOnly the card.\n")
        assert cli.main(["insight", "save", FEBRUARY]) == 0
        stored = _stored()
        assert stored.text == "Only the card."  # without the header
        assert stored.accounts == ("demo:credit_card",)
        assert stored.data_hash == _hash(["demo:credit_card"])

    def test_the_header_must_match_the_month_and_the_accounts(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _stdin(
            monkeypatch, "<!-- michelito dossier: month=2026-01 accounts=all -->\nAnother month."
        )
        assert cli.main(["insight", "save", FEBRUARY]) == 1
        assert "2026-01" in capsys.readouterr().err
        _stdin(monkeypatch, "<!-- michelito dossier: month=2026-02 accounts=all -->\nAll of them.")
        assert cli.main(["insight", "save", FEBRUARY, "--accounts", "demo:credit_card"]) == 1
        assert "--accounts" in capsys.readouterr().err
        assert _stored() is None

    def test_view_says_when_the_data_changed(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        assert cli.main(["insight", "show", FEBRUARY]) == 1
        assert "There is no analysis for February 2026" in capsys.readouterr().err
        _stdin(monkeypatch, "Analysis text.")
        cli.main(["insight", "save", FEBRUARY])
        capsys.readouterr()
        assert cli.main(["insight", "show", FEBRUARY]) == 0
        out = capsys.readouterr().out
        assert "Analysis text." in out and "changed" not in out
        with closing(db.connect(config.default_paths().database)) as conn:
            moves = dossier.build(conn, FEBRUARY).data["transactions"]
        agency = next(m for m in moves if m["merchant"] == "AGENCIA FICTICIA")
        with closing(db.connect(config.default_paths().database)) as conn, conn:
            corrections.set_one_off(conn, agency["fingerprint"], True)
        assert cli.main(["insight", "show", FEBRUARY]) == 0
        assert "The data changed since this analysis" in capsys.readouterr().out

    def test_delete(self, data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        _stdin(monkeypatch, "Delete this.")
        cli.main(["insight", "save", FEBRUARY])
        assert cli.main(["insight", "delete", FEBRUARY]) == 0
        assert _stored() is None
        assert cli.main(["insight", "delete", FEBRUARY]) == 1
