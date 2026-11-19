from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.analysis import categories as cat
from finanzas.web.app import create_app
from tests.test_spending import seed

WRITE = {"X-Finanzas": "1"}
MONTH = "2026-01"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "finanzas.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
    return path


@pytest.fixture
def client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path, today=lambda: date(2026, 3, 1)), "http://127.0.0.1")


def _by_name(client: TestClient, name: str) -> dict:
    return next(c for c in client.get("/api/categories").json() if c["name"] == name)


def _tx(client: TestClient, text: str, month: str = MONTH) -> dict:
    items = client.get("/api/transactions", params={"month": month}).json()["items"]
    return next(i for i in items if i["description"].startswith(text))


def _create(client: TestClient, **body) -> dict:
    response = client.post("/api/categories", json=body, headers=WRITE)
    assert response.status_code == 201, response.text
    return response.json()


class TestList:
    def test_list_has_ids_flags_keywords_and_yearly_count(self, client: TestClient) -> None:
        body = client.get("/api/categories").json()
        assert [c["name"] for c in body] == list(cat.ALL)
        other = _by_name(client, cat.OTHER)
        assert set(other) == {
            "id",
            "name",
            "kind",
            "color",
            "hidden",
            "builtin",
            "builtin_key",
            "keywords",
            "count_year",
        }
        assert (other["kind"], other["builtin"], other["builtin_key"]) == ("gasto", True, "OTHER")
        # En 2026 (hoy es marzo): el supermercado de diciembre no cuenta; la farmacia sí.
        assert other["count_year"] == 1
        assert _by_name(client, cat.CARD_PAYMENT)["count_year"] == 4


class TestWrites:
    def test_create_rename_recolor_hide(self, client: TestClient) -> None:
        made = _create(client, name="Mantenimiento del vehículo", kind="gasto", color="#C2702E")
        assert (made["builtin"], made["hidden"], made["count_year"]) == (False, False, 0)
        changed = client.patch(
            f"/api/categories/{made['id']}",
            json={"name": "Taller", "color": None, "hidden": True},
            headers=WRITE,
        ).json()
        assert (changed["name"], changed["color"], changed["hidden"]) == ("Taller", None, True)

    def test_writes_need_the_header(self, client: TestClient) -> None:
        response = client.post("/api/categories", json={"name": "X", "kind": "gasto"})
        assert response.status_code == 403

    def test_errors(self, client: TestClient) -> None:
        def post(body: dict) -> int:
            return client.post("/api/categories", json=body, headers=WRITE).status_code

        assert post({"name": "otros", "kind": "gasto"}) == 409
        assert post({"name": "X", "kind": "ahorro"}) == 422
        assert post({"name": "X", "kind": "gasto", "color": "rojo"}) == 422
        assert post({"name": " ", "kind": "gasto"}) == 422
        loans = _by_name(client, cat.LOANS)["id"]
        assert (
            client.patch(
                f"/api/categories/{loans}", json={"kind": "ingreso"}, headers=WRITE
            ).status_code
            == 400
        )
        assert client.delete(f"/api/categories/{loans}", headers=WRITE).status_code == 400
        assert client.patch("/api/categories/9999", json={}, headers=WRITE).status_code == 404

    def test_rename_keeps_corrections_and_old_name_filters(self, client: TestClient) -> None:
        cafe = _tx(client, "CAFE FICTICIO")
        grocery = _by_name(client, cat.GROCERIES)
        edited = client.patch(
            f"/api/transactions/{cafe['fingerprint']}",
            json={"category_id": grocery["id"]},
            headers=WRITE,
        )
        assert edited.status_code == 200 and edited.json()["category"] == cat.GROCERIES
        client.patch(f"/api/categories/{grocery['id']}", json={"name": "Súper"}, headers=WRITE)
        fixed = _tx(client, "CAFE FICTICIO")
        assert (fixed["category"], fixed["category_id"], fixed["corrected"]) == (
            "Súper",
            grocery["id"],
            True,
        )
        for name in ("Súper", "Supermercado"):  # el nombre de hoy y un enlace viejo
            listed = client.get(
                "/api/transactions", params={"month": MONTH, "category": name}
            ).json()["items"]
            assert [i["description"][:4] for i in listed] == ["CAFE"]
        by_id = client.get(
            "/api/transactions", params={"month": MONTH, "category_id": grocery["id"]}
        ).json()
        assert by_id["count"] == 1
        summary = client.get("/api/summary", params={"month": MONTH}).json()
        assert "Súper" in {line["category"] for line in summary["categories"]}

    def test_transaction_patch_accepts_names_and_rejects_unknown(self, client: TestClient) -> None:
        cafe = _tx(client, "CAFE FICTICIO")
        path = f"/api/transactions/{cafe['fingerprint']}"
        assert client.patch(path, json={"category": cat.HOME}, headers=WRITE).json()[
            "category"
        ] == (cat.HOME)
        assert client.patch(path, json={"category": "Inventada"}, headers=WRITE).status_code == 422
        assert client.patch(path, json={"category_id": 9999}, headers=WRITE).status_code == 422

    def test_delete_reassigns_and_needs_a_target_while_in_use(self, client: TestClient) -> None:
        made = _create(client, name="Farmacia", kind="gasto", keywords=["farmacia"])
        assert _tx(client, "FARMACIA")["category"] == "Farmacia"
        path = f"/api/categories/{made['id']}"
        assert client.delete(path, headers=WRITE).status_code == 400
        health = _by_name(client, cat.HEALTH)["id"]
        response = client.delete(path, params={"reassign_to": health}, headers=WRITE)
        assert response.status_code == 204
        assert _tx(client, "FARMACIA")["category"] == cat.HEALTH
        assert _by_name(client, cat.HEALTH)["keywords"] == ["FARMACIA"]
        assert client.delete(path, params={"reassign_to": health}, headers=WRITE).status_code == 404

    def test_keywords_move_past_transactions(self, client: TestClient) -> None:
        made = _create(client, name="Farmacia", kind="gasto")
        client.patch(
            f"/api/categories/{made['id']}", json={"keywords": ["Farmacia"]}, headers=WRITE
        )
        assert _tx(client, "FARMACIA")["category"] == "Farmacia"
        assert _by_name(client, "Farmacia")["count_year"] == 1


class TestPreview:
    def test_preview_counts_what_would_move_without_saving(self, client: TestClient) -> None:
        made = _create(client, name="Farmacia", kind="gasto")
        response = client.post(
            f"/api/categories/{made['id']}/preview",
            json={"keywords": ["FARMACIA", "TIENDA ONLINE"]},
            headers=WRITE,
        )
        assert response.status_code == 200
        # La farmacia (RD$ 500) y las dos compras de TIENDA ONLINE (US$ 25 y 30, sin tasa).
        assert response.json() == {
            "count": 3,
            "total_cents": 50000,
            "unconverted_usd_cents": 5500,
            "conflicts": 0,
        }
        assert _tx(client, "FARMACIA")["category"] == cat.OTHER  # nada guardado

    def test_preview_reports_conflicts_with_other_keywords(self, client: TestClient) -> None:
        _create(client, name="Tiendas", kind="gasto", keywords=["TIENDA"])
        made = _create(client, name="En línea", kind="gasto")
        body = client.post(
            f"/api/categories/{made['id']}/preview",
            json={"keywords": ["TIENDA ONLINE"]},
            headers=WRITE,
        ).json()
        assert body == {
            "count": 2,
            "total_cents": 0,
            "unconverted_usd_cents": 5500,
            "conflicts": 2,
        }

    def test_conflicts_count_only_what_would_move(self, client: TestClient) -> None:
        _create(client, name="Tiendas", kind="gasto", keywords=["TIENDA"])
        made = _create(client, name="En línea", kind="gasto")
        store = _tx(client, "TIENDA ONLINE SEATTLE-US")
        home = _by_name(client, cat.HOME)["id"]
        client.patch(
            f"/api/transactions/{store['fingerprint']}", json={"category_id": home}, headers=WRITE
        )
        body = client.post(
            f"/api/categories/{made['id']}/preview",
            json={"keywords": ["TIENDA ONLINE"]},
            headers=WRITE,
        ).json()
        # La corregida a mano no se mueve: ni cuenta ni choca.
        assert (body["count"], body["conflicts"]) == (1, 1)

    def test_preview_rejects_bad_keywords_and_unknown_category(self, client: TestClient) -> None:
        made = _create(client, name="Farmacia", kind="gasto")
        bad = client.post(
            f"/api/categories/{made['id']}/preview", json={"keywords": ["--"]}, headers=WRITE
        )
        assert bad.status_code == 422
        missing = client.post("/api/categories/9999/preview", json={"keywords": []}, headers=WRITE)
        assert missing.status_code == 404
