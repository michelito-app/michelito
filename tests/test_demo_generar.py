"""El generador de la demo: pasa por la validación real y llena todas las pantallas."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.demo import ejemplo, generar
from finanzas.demo import movimientos as mv
from finanzas.parsers.common import validate_statement
from finanzas.web.app import create_app
from tests.demo_helpers import TODAY, _restore_providers  # noqa: F401
from tests.test_check_private import check


@pytest.fixture
def template(tmp_path: Path) -> generar.Template:
    generar.use_demo_providers()
    return generar.build_template(tmp_path / "plantilla", TODAY)


@pytest.fixture
def api(template: generar.Template) -> TestClient:
    app = create_app(template.database, holders_path=template.holders, today=lambda: TODAY)
    return TestClient(app, base_url="http://127.0.0.1")


def test_every_generated_statement_balances() -> None:
    found = generar.statements(TODAY)
    assert len(found) > 60
    assert all(validate_statement(s) == () for s in found)


def test_template_goes_through_ingest(template: generar.Template) -> None:
    with closing(sqlite3.connect(template.database)) as conn:
        statuses = dict(conn.execute("SELECT status, COUNT(*) FROM documents GROUP BY status"))
        sources = {row[0] for row in conn.execute("SELECT DISTINCT source FROM documents")}
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert set(statuses) == {"parsed"}
    assert sources == {"generado"}
    assert count > 500
    assert template.holders.read_text(encoding="utf-8").strip().endswith(mv.PERSONA)
    assert template.seconds < 10


def test_window_is_24_months_ending_this_month(api: TestClient) -> None:
    months = [m["month"] for m in api.get("/api/months").json()]
    assert len(months) == 24
    assert max(months) == TODAY.strftime("%Y-%m")
    assert min(months) == "2024-12"


def test_generation_is_deterministic(tmp_path: Path) -> None:
    first = [s.sections for s in generar.statements(TODAY)]
    assert first == [s.sections for s in generar.statements(TODAY)]


@pytest.mark.parametrize(
    "path",
    [
        "/api/summary",
        "/api/transactions",
        "/api/pending",
        "/api/shared",
        "/api/investments",
        "/api/recurring",
        "/api/accounts",
        "/api/categories",
        "/api/cash-box",
        "/api/reports/compare",
        "/api/budget",
        "/api/review/history",
    ],
)
def test_every_screen_has_data(api: TestClient, path: str) -> None:
    answer = api.get(path)
    assert answer.status_code == 200, answer.text
    assert answer.json()


def test_screens_show_the_stories(api: TestClient) -> None:
    assert api.get("/api/pending").json()["owed_to_me"]
    assert api.get("/api/investments").json()["active_count"] == 1
    providers_ = {i["name"] for i in api.get("/api/recurring").json()["items"]}
    assert {"Telefónica Ficticia", "Eléctrica Ficticia", "STREAMING FICTICIO"} <= providers_
    cash = api.get("/api/cash-box").json()
    assert cash["exists"] and cash["lines"]
    review = api.get("/api/review", params={"month": "2026-10"}).json()
    assert {"duplicado", "ingreso_inusual", "tercero_grande"} <= {r["kind"] for r in review}
    accounts = api.get("/api/accounts").json()
    assert {"DOP", "USD"} <= set(accounts[0]["currencies"])


def test_budget_and_reserves_start_off_with_suggestions(api: TestClient) -> None:
    assert api.get("/api/budget").json()["active"] is False
    reserves = api.get("/api/reserves").json()
    assert reserves["items"] == []
    names = [s["name"] for s in reserves["suggestions"]]
    assert "Diciembre: Supermercado" in names  # la Navidad
    assert "MARBETE FICTICIO" in names  # un recurrente anual


def test_sample_statement_is_the_next_cut(template: generar.Template) -> None:
    with closing(db.connect(template.database)) as conn:
        first = ejemplo.import_next(conn, TODAY)
        second = ejemplo.import_next(conn, TODAY)
    assert first.balanced and first.transactions > 10
    assert first.period_end.isoformat() == "2026-12-10"
    assert second.period_end.isoformat() == "2027-01-10"
    assert first.months == ["2026-11", "2026-12"]


# Lo que delataría un dato real: dígitos largos, correos, rutas de usuario.
_SUSPECT = re.compile(r"\d{11,}|@|/home/|/Users/")


def test_nothing_looks_real(template: generar.Template) -> None:
    with closing(sqlite3.connect(template.database)) as conn:
        texts = [row[0] for row in conn.execute("SELECT description FROM transactions")]
        identifiers = {row[0] for row in conn.execute("SELECT key FROM accounts")}
    assert texts and not [t for t in texts if _SUSPECT.search(t)]
    invented = ("FICTICI", "INVENTAD", "SU PAGO GRACIAS", "P2P", "TELFIC", "MARBETE", "PAGO TARJ")
    assert all(any(word in text for word in invented) for text in texts)
    assert all("ficticio" in key or "inventado" in key or "manual" in key for key in identifiers)
    # El mismo chequeo que corre sobre el repositorio, ahora sobre lo generado.
    with closing(sqlite3.connect(template.database)) as conn:
        dump = "\n".join(
            " ".join(str(value) for value in row)
            for row in conn.execute(
                "SELECT description, raw_line FROM transactions UNION ALL "
                "SELECT name, key FROM accounts UNION ALL SELECT filename, path FROM documents"
            )
        )
    assert not list(check.scan_text("plantilla", dump))
