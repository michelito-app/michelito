"""Opiniones y contadores de uso: nada que identifique al visitante."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from finanzas import cli
from finanzas.demo import opiniones
from finanzas.demo.app import PLAIN_COOKIE as COOKIE
from tests.demo_helpers import WRITE, _restore_providers, client  # noqa: F401


def _dump(path: Path) -> str:
    with closing(sqlite3.connect(path)) as conn:
        return "\n".join(conn.iterdump())


def test_opinion_with_context_and_no_personal_trace(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/sesion", headers=WRITE)
    body = {
        "texto": "Me gustó el presupuesto",
        "correo": "persona@example.com",
        "pagina": "/presupuesto?mes=2026-10",
        "ancho": 390,
        "version": "0.1.0",
        "ref": "foro-1",
    }
    assert api.post("/api/opiniones", json=body, headers=WRITE).status_code == 201
    api.post("/api/uso", json={"pantalla": "/presupuesto"}, headers=WRITE)
    api.post("/api/uso", json={"pantalla": "/transacciones/abc123"}, headers=WRITE)
    api.post("/api/uso", json={"pantalla": "/no-existe"}, headers=WRITE)
    api.app.state.maintenance.flush()  # los conteos se vuelcan de a tandas
    feedback = opiniones.Feedback(tmp_path / "demo" / opiniones.FILENAME)
    [stored] = feedback.opinions()
    assert (stored.pagina, stored.ancho, stored.ref) == ("/presupuesto", 390, "foro-1")
    usage = {(u["tipo"], u["clave"]): u["conteo"] for u in feedback.usage()}
    assert usage[("visita", "presupuesto")] == 1
    assert usage[("visita", "transacciones")] == 1
    assert usage[("visita", "otra")] == 1
    assert usage[("copia", "creada")] == 1
    dump = _dump(tmp_path / "demo" / opiniones.FILENAME)
    assert api.cookies[COOKIE] not in dump
    assert "testclient" not in dump and "127.0.0.1" not in dump


@pytest.mark.parametrize(
    "body",
    [
        {"texto": ""},
        {"texto": "x" * 2001},
        {"texto": "hola", "correo": "no-es-correo"},
        {"texto": "hola", "ref": "<script>"},
    ],
)
def test_invalid_opinions_are_rejected(tmp_path: Path, body: dict) -> None:
    api = client(tmp_path)
    api.post("/api/demo/sesion", headers=WRITE)
    assert api.post("/api/opiniones", json=body, headers=WRITE).status_code == 422


def test_opinions_need_a_session_and_are_capped(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert api.post("/api/opiniones", json={"texto": "x"}, headers=WRITE).status_code == 401
    api.post("/api/demo/sesion", headers=WRITE)
    codes = [
        api.post("/api/opiniones", json={"texto": f"n{i}"}, headers=WRITE).status_code
        for i in range(11)
    ]
    assert codes[:10] == [201] * 10 and codes[10] == 429


def test_key_events_are_counted(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/sesion", headers=WRITE)
    assert api.post("/api/budget/activate", json={}, headers=WRITE).status_code == 201
    api.post("/api/demo/estado-ejemplo", headers=WRITE)
    entry = api.get("/api/log").json()["items"][0]["id"]
    assert api.post(f"/api/log/{entry}/undo", headers=WRITE).status_code == 200
    api.app.state.maintenance.flush()
    usage = opiniones.Feedback(tmp_path / "demo" / opiniones.FILENAME).usage()
    events = {u["clave"] for u in usage if u["tipo"] == "evento"}
    assert {"activar_presupuesto", "estado_ejemplo", "deshacer"} <= events


def test_cli_lists_opinions_and_usage(tmp_path: Path, capsys) -> None:
    feedback = opiniones.Feedback(tmp_path / opiniones.FILENAME)
    feedback.save(opiniones.Opinion("Falta un modo oscuro", pagina="/", ancho=1280))
    feedback.count("visita", "resumen")
    feedback.flush()
    assert cli.main(["opiniones", "--datos", str(tmp_path)]) == 0
    assert "Falta un modo oscuro" in capsys.readouterr().out
    assert cli.main(["opiniones", "--json", "--datos", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["ancho"] == 1280
    assert cli.main(["opiniones", "--uso", "--datos", str(tmp_path)]) == 0
    assert "resumen" in capsys.readouterr().out


def test_control_characters_never_reach_the_terminal(tmp_path: Path, capsys) -> None:
    feedback = opiniones.Feedback(tmp_path / opiniones.FILENAME)
    feedback.save(opiniones.Opinion("hola\x1b[2J\nmundo ‮odnum", ref="a‮b"))
    [stored] = feedback.opinions()
    assert stored.texto == "hola[2J\nmundo odnum" and stored.ref == "ab"
    # Lo que ya estuviera guardado con controles se imprime escapado.
    import sqlite3 as _sqlite

    with closing(_sqlite.connect(tmp_path / opiniones.FILENAME)) as conn, conn:
        conn.execute("UPDATE opiniones SET texto = ?", ("x\x1b[2Jy‮z\nfin",))
    assert cli.main(["opiniones", "--datos", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "‮" not in out
    assert "x\\u001b[2Jy\\u202ez\nfin" in out
    assert cli.main(["opiniones", "--json", "--datos", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "‮" not in out
