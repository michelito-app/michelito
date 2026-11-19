"""«Copiar para Claude»: `GET /api/dossier`, la instrucción fija y el pegado de vuelta.

Local sobre la base de las pruebas e2e; la demo, sobre copias del generador (datos inventados).
"""

from contextlib import closing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finanzas import db, dossier
from finanzas.analysis import claude_prompt, corrections, insights
from finanzas.demo import opiniones
from finanzas.web.app import create_app
from tests.demo_helpers import WRITE, _restore_providers, client, visitor  # noqa: F401
from tests.e2e_server import build_demo_db

FEBRUARY = "2026-02"
CARD = "demo:credit_card"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "local.db"
    build_demo_db(path)
    return path


@pytest.fixture
def local(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path), "http://127.0.0.1")


def _built(db_path: Path, month: str = FEBRUARY, accounts=None) -> dossier.Dossier:
    with closing(db.connect(db_path)) as conn:
        return dossier.build(conn, month, accounts=accounts)


def test_the_dossier_is_the_same_markdown_as_the_cli(local: TestClient, db_path: Path) -> None:
    found = local.get("/api/dossier", params={"mes": FEBRUARY})
    assert found.status_code == 200
    assert found.headers["content-type"].startswith("text/markdown")
    assert found.headers["cache-control"] == "no-store"
    built = _built(db_path)
    assert found.text == built.markdown
    assert found.headers["x-finanzas-huella"] == built.data_hash
    # Las defensas del dossier llegan intactas.
    assert dossier.DATA_NOTICE in found.text and "```text" in found.text


def test_accounts_filter_the_dossier(local: TestClient, db_path: Path) -> None:
    found = local.get("/api/dossier", params={"mes": FEBRUARY, "cuentas": f" {CARD},{CARD} "})
    assert found.status_code == 200
    assert found.text == _built(db_path, accounts=[CARD]).markdown
    assert found.text.startswith(dossier.header(FEBRUARY, [CARD]))
    assert local.get("/api/dossier", params={"mes": FEBRUARY, "cuentas": ""}).text == (
        _built(db_path).markdown
    )


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({}, 422),
        ({"mes": "2026-13"}, 422),
        ({"mes": "febrero"}, 422),
        ({"mes": FEBRUARY, "cuentas": "no:existe"}, 422),
        ({"mes": FEBRUARY, "cuentas": "x" * 2001}, 422),
        ({"mes": FEBRUARY, "cuentas": f"{CARD},{'x' * 101}"}, 422),
        ({"mes": "2001-01"}, 404),
    ],
)
def test_invalid_requests(local: TestClient, params: dict, status: int) -> None:
    assert local.get("/api/dossier", params=params).status_code == status


def test_unknown_account_names_it(local: TestClient) -> None:
    found = local.get("/api/dossier", params={"mes": FEBRUARY, "cuentas": "no:existe"})
    assert "no:existe" in found.json()["detail"]


def test_the_dossier_only_reads(local: TestClient, db_path: Path) -> None:
    before = _built(db_path).data_hash
    local.get("/api/dossier", params={"mes": FEBRUARY})
    assert _built(db_path).data_hash == before
    assert local.get("/api/log").json()["items"] == []


def test_the_instruction_is_the_single_source(local: TestClient) -> None:
    found = local.get("/api/dossier/instruccion").json()
    assert found == {"texto": claude_prompt.INSTRUCTION}
    text = found["texto"]
    assert "```text" in text and "no instrucciones" in text
    assert f"menos de {claude_prompt.MAX_WORDS} palabras" in text and "Tres ideas" in text


def test_pasting_back_saves_a_fresh_analysis_with_the_copied_accounts(local: TestClient) -> None:
    pasted = f"{dossier.header(FEBRUARY, [CARD])}\n## Febrero\n\nGasté más en viajes."
    body = {"text": pasted, "fresh": True, "accounts": [CARD]}
    saved = local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE)
    assert saved.status_code == 200, saved.text
    out = saved.json()
    assert out["text"] == "## Febrero\n\nGasté más en viajes."  # sin el encabezado
    assert (out["accounts"], out["stale"]) == ([CARD], False)
    # Volver a pegar reemplaza el texto y las cuentas (todas).
    again = {"text": "Otro análisis.", "fresh": True}
    replaced = local.put(f"/api/insights/{FEBRUARY}", json=again, headers=WRITE).json()
    assert (replaced["text"], replaced["accounts"], replaced["stale"]) == (
        "Otro análisis.",
        None,
        False,
    )


@pytest.mark.parametrize(
    "body",
    [
        {"text": dossier.header("2026-01", None) + "\nEnero.", "fresh": True},
        {"text": "   ", "fresh": True},
        {"text": "x", "fresh": True, "accounts": ["no:existe"]},
        {"text": "x", "fresh": True, "accounts": ["no:existe"], "huella": "0" * 16},
        # El encabezado dice una cuenta y el cuerpo, todas (o al revés): no se adivina.
        {"text": dossier.header(FEBRUARY, [CARD]) + "\nX.", "fresh": True, "accounts": None},
        {"text": dossier.header(FEBRUARY, None) + "\nX.", "fresh": True, "accounts": [CARD]},
        {"text": "x", "fresh": True, "huella": "no-es-huella"},
        {"text": "x", "fresh": True, "huella": "A" * 16},
        {"text": "x", "fresh": True, "accounts": ["x" * 101]},
        {"text": "x", "fresh": True, "accounts": [""]},
    ],
)
def test_pasting_back_rejects_bad_answers(local: TestClient, body: dict) -> None:
    assert local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE).status_code == 422
    assert local.get(f"/api/insights/{FEBRUARY}").status_code == 404


def test_without_accounts_the_header_decides(local: TestClient) -> None:
    pasted = f"{dossier.header(FEBRUARY, [CARD])}\nSolo la tarjeta."
    body = {"text": pasted, "fresh": True}
    saved = local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE).json()
    assert (saved["text"], saved["accounts"], saved["stale"]) == ("Solo la tarjeta.", [CARD], False)


def test_the_copied_hash_is_kept_so_later_changes_show(local: TestClient, db_path: Path) -> None:
    copied = local.get("/api/dossier", params={"mes": FEBRUARY, "cuentas": CARD})
    huella = copied.headers["x-finanzas-huella"]
    # Los datos cambian mientras el visitante está en Claude.
    with closing(db.connect(db_path)) as conn:
        moves = dossier.build(conn, FEBRUARY).data["movimientos"]
        agency = next(m for m in moves if m["comercio"] == "AGENCIA FICTICIA")
        with conn:
            corrections.set_one_off(conn, agency["huella"], True)
    body = {"text": "Febrero.", "fresh": True, "accounts": [CARD], "huella": huella}
    saved = local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE).json()
    assert saved["stale"] is True  # el análisis es del dossier de antes
    with closing(db.connect(db_path)) as conn:
        assert insights.get(conn, FEBRUARY).data_hash == huella  # type: ignore[union-attr]
    # Con la huella de hoy, al día.
    fresh = local.get("/api/dossier", params={"mes": FEBRUARY, "cuentas": CARD})
    body["huella"] = fresh.headers["x-finanzas-huella"]
    assert local.put(f"/api/insights/{FEBRUARY}", json=body, headers=WRITE).json()["stale"] is False


def test_without_fresh_the_put_is_unchanged(local: TestClient, db_path: Path) -> None:
    made = {"text": "Creado.", "accounts": [CARD], "huella": "0" * 16}
    created = local.put(f"/api/insights/{FEBRUARY}", json=made, headers=WRITE).json()
    assert (created["accounts"], created["stale"]) == (None, False)  # todas, huella de hoy
    edit = {"text": "Editado.", "accounts": [CARD], "huella": "0" * 16}
    edited = local.put(f"/api/insights/{FEBRUARY}", json=edit, headers=WRITE).json()
    assert (edited["text"], edited["accounts"], edited["stale"]) == ("Editado.", None, False)
    with closing(db.connect(db_path)) as conn:
        assert insights.get(conn, FEBRUARY).data_hash == _built(db_path).data_hash  # type: ignore[union-attr]


# --- demo ---


def _demo_month(api: TestClient) -> str:
    return api.get("/api/months").json()[1]["month"]


def test_demo_dossier_is_the_visitor_copy(tmp_path: Path) -> None:
    one = client(tmp_path)
    assert one.get("/api/dossier", params={"mes": "2026-10"}).status_code == 401  # sin sesión
    one.post("/api/demo/sesion", headers=WRITE)
    two = visitor(one)
    month = _demo_month(one)
    before = one.get("/api/dossier", params={"mes": month}).text
    assert two.get("/api/dossier", params={"mes": month}).text == before
    category = next(c for c in one.get("/api/categories").json() if c["name"] in before)
    renamed = one.patch(
        f"/api/categories/{category['id']}", json={"name": "Renombrada Solo Mía"}, headers=WRITE
    )
    assert renamed.status_code == 200, renamed.text
    assert "Renombrada Solo Mía" in one.get("/api/dossier", params={"mes": month}).text
    assert two.get("/api/dossier", params={"mes": month}).text == before


def test_demo_pasting_back_only_writes_the_visitor_copy(tmp_path: Path) -> None:
    one = client(tmp_path)
    one.post("/api/demo/sesion", headers=WRITE)
    two = visitor(one)
    month = _demo_month(one)
    copied = one.get("/api/dossier", params={"mes": month})
    body = {"text": "Mi análisis.", "fresh": True, "huella": copied.headers["x-finanzas-huella"]}
    saved = one.put(f"/api/insights/{month}", json=body, headers=WRITE)
    assert saved.status_code == 200, saved.text
    assert saved.json()["stale"] is False
    assert two.get(f"/api/insights/{month}").status_code == 404
    template = tmp_path / "demo" / "plantilla" / "finanzas.db"
    with closing(db.connect(template)) as conn:
        assert insights.list_all(conn) == []
    # Claude no escribe en la demo, tampoco por aquí.
    claude = {**WRITE, "X-Finanzas-Autor": "claude"}
    assert one.put(f"/api/insights/{month}", json=body, headers=claude).status_code == 403


def test_demo_dossier_is_an_expensive_route(tmp_path: Path) -> None:
    api = client(tmp_path, per_minute=10)
    api.post("/api/demo/sesion", headers=WRITE)
    month = "2026-10"
    assert api.get("/api/dossier", params={"mes": month}).status_code == 200  # cuesta 4
    assert api.get("/api/dossier", params={"mes": month}).status_code == 200  # 8
    assert api.get("/api/dossier", params={"mes": month}).status_code == 429
    assert api.get("/api/dossier/instruccion").status_code == 200  # 1: aún cabe


def test_demo_counts_copy_for_claude(tmp_path: Path) -> None:
    api = client(tmp_path)
    event = {"evento": "copiar_claude"}
    assert api.post("/api/demo/evento", json=event, headers=WRITE).status_code == 401
    api.post("/api/demo/sesion", headers=WRITE)
    assert api.post("/api/demo/evento", json=event, headers=WRITE).status_code == 204
    assert api.post("/api/demo/evento", json=event, headers=WRITE).status_code == 204
    unknown = api.post("/api/demo/evento", json={"evento": "otro"}, headers=WRITE)
    assert unknown.status_code == 422
    app = api.app
    assert isinstance(app, FastAPI)
    app.state.maintenance.flush()
    usage = opiniones.Feedback(tmp_path / "demo" / opiniones.FILENAME).usage()
    counts = {u["clave"]: u["conteo"] for u in usage if u["tipo"] == "evento"}
    assert counts == {"copiar_claude": 2}


def test_demo_ui_events_have_their_own_cap(tmp_path: Path) -> None:
    api = client(tmp_path)
    api.post("/api/demo/sesion", headers=WRITE)
    event = {"evento": "copiar_claude"}
    codes = {api.post("/api/demo/evento", json=event, headers=WRITE).status_code for _ in range(55)}
    assert codes == {204}  # pasado el tope se ignora en silencio
    assert api.post("/api/uso", json={"pantalla": "/"}, headers=WRITE).status_code == 204
    app = api.app
    assert isinstance(app, FastAPI)
    app.state.maintenance.flush()
    usage = opiniones.Feedback(tmp_path / "demo" / opiniones.FILENAME).usage()
    counts = {(u["tipo"], u["clave"]): u["conteo"] for u in usage}
    assert counts[("evento", "copiar_claude")] == 50
    assert counts[("visita", "resumen")] == 1  # las visitas tienen su propio tope


def test_local_mode_has_no_demo_event_route(local: TestClient) -> None:
    event = {"evento": "copiar_claude"}
    assert local.post("/api/demo/evento", json=event, headers=WRITE).status_code == 404
