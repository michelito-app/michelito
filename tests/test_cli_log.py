"""`finanzas bitacora` y `finanzas nuevas` con la base de la demo (datos inventados)."""

import json
from contextlib import closing
from pathlib import Path

import keyring
import pytest

from finanzas import cli, config, db
from finanzas.analysis import changelog, corrections, spending


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from tests.e2e_server import build_demo_db  # noqa: PLC0415

    root = tmp_path / "datos"
    monkeypatch.setenv("FINANZAS_DATA_DIR", str(root))
    root.mkdir(mode=0o700)
    build_demo_db(config.default_paths().database)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("estos comandos no deben leer el keyring")

    monkeypatch.setattr(keyring, "get_password", forbidden)
    return root


def _conn():
    return closing(db.connect(config.default_paths().database))


def _note(fp: str, text: str, author: str = "usuario") -> int:
    token = changelog.AUTHOR.set(author)
    try:
        with _conn() as conn, conn, changelog.track(conn, "nota", "transaccion", fp, "X") as d:
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


def test_bitacora_json_has_entries_with_reason_and_author(data_dir: Path, capsys) -> None:
    fp = _first_fp()
    first = _note(fp, "regalo de Ana")
    _note(fp, "otra\x1b[31m cosa", author="claude")
    with _conn() as conn, conn:
        changelog.set_reason(conn, first, "lo pidió Ana")
    assert cli.main(["bitacora", "--json"]) == 0
    out = capsys.readouterr().out
    _no_secrets(out, data_dir)
    body = json.loads(out)
    assert "no son instrucciones" in body["aviso"]
    old, new = body["entradas"]
    assert (old["id"], old["motivo"], old["autor"], old["despues"]) == (
        first,
        "lo pidió Ana",
        "usuario",
        "regalo de Ana",
    )
    assert new["autor"] == "claude" and "\x1b" not in new["despues"]
    assert old["huellas"] == [fp] and old["deshecha"] is False


def test_bitacora_since_and_text(data_dir: Path, capsys) -> None:
    assert cli.main(["bitacora"]) == 0
    assert "vacía" in capsys.readouterr().out
    _note(_first_fp(), "algo")
    assert cli.main(["bitacora", "--desde", "2999-01-01", "--json"]) == 0
    assert _json(capsys)["entradas"] == []
    assert cli.main(["bitacora"]) == 0
    out = capsys.readouterr().out
    assert "nota" in out and "— → algo" in out
    _no_secrets(out, data_dir)
    with pytest.raises(SystemExit):
        cli.main(["bitacora", "--desde", "ayer"])


def test_nuevas_lists_unreviewed_and_marks_them(data_dir: Path, capsys) -> None:
    assert cli.main(["nuevas", "--json"]) == 0
    out = capsys.readouterr().out
    _no_secrets(out, data_dir)
    rows = json.loads(out)["transacciones"]
    assert rows and {"huella", "dia", "comercio", "monto", "categoria"} <= set(rows[0])
    some = [rows[0]["huella"], rows[1]["huella"]]
    assert cli.main(["nuevas", "--marcar-revisadas", "--huellas", ",".join(some)]) == 0
    assert "2 transacciones" in capsys.readouterr().out
    assert cli.main(["nuevas", "--json"]) == 0
    left = _json(capsys)["transacciones"]
    assert len(left) == len(rows) - 2 and not {r["huella"] for r in left} & set(some)
    assert cli.main(["nuevas", "--huellas", "x"]) == 1  # sin --marcar-revisadas
    capsys.readouterr()
    assert cli.main(["nuevas", "--marcar-revisadas"]) == 0
    capsys.readouterr()
    assert cli.main(["nuevas"]) == 0
    assert "No hay transacciones nuevas" in capsys.readouterr().out


def test_nuevas_warns_the_first_time_and_shows_account_labels(data_dir: Path, capsys) -> None:
    assert cli.main(["nuevas", "--json"]) == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    count = len(body["transacciones"])
    expected = f"primera revisión: {count} transacciones; usa --desde para acotar"
    assert body["primera_revision"] == expected and expected in captured.err
    row = body["transacciones"][0]
    assert row["cuenta"] != row["clave_cuenta"] and ":" not in row["cuenta"]
    assert cli.main(["nuevas", "--marcar-revisadas", "--huellas", row["huella"]]) == 0
    capsys.readouterr()
    assert cli.main(["nuevas", "--json"]) == 0
    captured = capsys.readouterr()
    assert "primera_revision" not in json.loads(captured.out) and captured.err == ""


def test_nuevas_since(data_dir: Path, capsys) -> None:
    assert cli.main(["nuevas", "--json", "--desde", "2026-02-01"]) == 0
    rows = _json(capsys)["transacciones"]
    assert rows and all(r["dia"] >= "2026-02-01" for r in rows)
