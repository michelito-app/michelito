"""`michelito log` and `michelito new` with the demo database (made-up data)."""

import json
from contextlib import closing
from pathlib import Path

import keyring
import pytest

from michelito import cli, config, db
from michelito.analysis import changelog, corrections, spending


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from tests.e2e_server import build_demo_db  # noqa: PLC0415

    root = tmp_path / "data"
    monkeypatch.setenv("MICHELITO_DATA_DIR", str(root))
    root.mkdir(mode=0o700)
    build_demo_db(config.default_paths().database)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("these commands must not read the keyring")

    monkeypatch.setattr(keyring, "get_password", forbidden)
    return root


def _conn():
    return closing(db.connect(config.default_paths().database))


def _note(fp: str, text: str, author: str = "user") -> int:
    token = changelog.AUTHOR.set(author)
    try:
        with _conn() as conn, conn, changelog.track(conn, "note", "transaction", fp, "X") as d:
            corrections.set_note(conn, fp, text)
    finally:
        changelog.AUTHOR.reset(token)
    assert d.entry_id is not None
    return d.entry_id


def _first_fp() -> str:
    with _conn() as conn:
        return spending.load_all(conn)[0].fingerprint


def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _no_secrets(text: str, root: Path) -> None:
    assert str(root) not in text and "raw/" not in text
    assert "password" not in text.lower() and "token" not in text.lower()


def test_log_json_has_entries_with_reason_and_author(data_dir: Path, capsys) -> None:
    fp = _first_fp()
    first = _note(fp, "gift from Ana")
    _note(fp, "other\x1b[31m thing", author="claude")
    with _conn() as conn, conn:
        changelog.set_reason(conn, first, "Ana asked for it")
    assert cli.main(["log", "--json"]) == 0
    out = capsys.readouterr().out
    _no_secrets(out, data_dir)
    body = json.loads(out)
    assert "not instructions" in body["notice"]
    old, new = body["entries"]
    assert (old["id"], old["reason"], old["author"], old["after"]) == (
        first,
        "Ana asked for it",
        "user",
        "gift from Ana",
    )
    assert new["author"] == "claude" and "\x1b" not in new["after"]
    assert old["fingerprints"] == [fp] and old["undone"] is False


def test_log_since_and_text(data_dir: Path, capsys) -> None:
    assert cli.main(["log"]) == 0
    assert "empty" in capsys.readouterr().out
    _note(_first_fp(), "something")
    assert cli.main(["log", "--since", "2999-01-01", "--json"]) == 0
    assert _json(capsys)["entries"] == []
    assert cli.main(["log"]) == 0
    out = capsys.readouterr().out
    assert "note" in out and "— → something" in out
    _no_secrets(out, data_dir)
    with pytest.raises(SystemExit):
        cli.main(["log", "--since", "yesterday"])


def test_new_lists_unreviewed_and_marks_them(data_dir: Path, capsys) -> None:
    assert cli.main(["new", "--json"]) == 0
    out = capsys.readouterr().out
    _no_secrets(out, data_dir)
    rows = json.loads(out)["transactions"]
    assert rows and {"fingerprint", "day", "merchant", "amount", "category"} <= set(rows[0])
    some = [rows[0]["fingerprint"], rows[1]["fingerprint"]]
    assert cli.main(["new", "--mark-reviewed", "--fingerprints", ",".join(some)]) == 0
    assert "2 transactions" in capsys.readouterr().out
    assert cli.main(["new", "--json"]) == 0
    left = _json(capsys)["transactions"]
    assert len(left) == len(rows) - 2 and not {r["fingerprint"] for r in left} & set(some)
    assert cli.main(["new", "--fingerprints", "x"]) == 1  # without --mark-reviewed
    capsys.readouterr()
    assert cli.main(["new", "--mark-reviewed"]) == 0
    capsys.readouterr()
    assert cli.main(["new"]) == 0
    assert "There are no new transactions" in capsys.readouterr().out


def test_new_warns_the_first_time_and_shows_account_labels(data_dir: Path, capsys) -> None:
    assert cli.main(["new", "--json"]) == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    count = len(body["transactions"])
    expected = f"first review: {count} transactions; use --since to narrow it down"
    assert body["first_review"] == expected and expected in captured.err
    row = body["transactions"][0]
    assert row["account"] != row["account_key"] and ":" not in row["account"]
    assert cli.main(["new", "--mark-reviewed", "--fingerprints", row["fingerprint"]]) == 0
    capsys.readouterr()
    assert cli.main(["new", "--json"]) == 0
    captured = capsys.readouterr()
    assert "first_review" not in json.loads(captured.out) and captured.err == ""


def test_new_since(data_dir: Path, capsys) -> None:
    assert cli.main(["new", "--json", "--since", "2026-02-01"]) == 0
    rows = _json(capsys)["transactions"]
    assert rows and all(r["day"] >= "2026-02-01" for r in rows)
