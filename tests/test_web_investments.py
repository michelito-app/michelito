"""Inversiones desde la API: crear, sumar y quitar movimientos, tipo de un crédito, perdida,
lista con totales, Resumen y «Para revisar», con datos inventados."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.analysis import rates
from finanzas.web.app import create_app
from tests.test_spending import _add_bank_rows, seed

WRITE = {"X-Finanzas": "1"}
MONTH = "2026-01"
SENT = "MB a 0000000066 SOCIO INVENTADO"
BACK = "TRANSF DE SOCIO INVENTADO"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "finanzas.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-08", SENT, "debit", "30000000"),
                ("2026-01-12", SENT, "debit", "10000000"),
                ("2026-01-14", SENT, "debit", "150000"),
                ("2026-01-20", BACK, "credit", "900000"),
                ("2026-01-28", BACK, "credit", "6000000"),
            ],
        )
        with conn:
            rates.store_bcrd(conn, {"2026-01": Decimal("60")})
    return TestClient(create_app(path, today=lambda: date(2026, 2, 7)), "http://127.0.0.1")


def _items(client: TestClient) -> list[dict]:
    return client.get("/api/transactions", params={"month": MONTH}).json()["items"]


def _fps(client: TestClient, text: str) -> list[str]:
    found = [i for i in _items(client) if i["description"] == text]
    return [i["fingerprint"] for i in sorted(found, key=lambda i: i["day"])]


def _tx(client: TestClient, fp: str) -> dict:
    return client.get(f"/api/transactions/{fp}").json()


def _create(client: TestClient, fp: str, **body):
    return client.post("/api/investments", json={"fingerprint": fp, **body}, headers=WRITE)


def _add(client: TestClient, investment: int, fp: str, role: str, capital: int | None = None):
    body = {"fingerprint": fp, "role": role}
    if capital is not None:
        body["capital_cents"] = capital
    return client.post(f"/api/investments/{investment}/members", json=body, headers=WRITE)


def test_mark_a_debit_link_a_return_and_a_mixed_credit(client: TestClient) -> None:
    first, second, small = _fps(client, SENT)
    ret, mixed = _fps(client, BACK)
    before = client.get("/api/summary", params={"month": MONTH}).json()
    assert _tx(client, first)["can_invest"] and _tx(client, ret)["can_invest_credit"]

    created = _create(client, first, with_whom="Socio Inventado", name="Negocio")
    assert created.status_code == 201
    body = created.json()
    assert (body["title"], body["status"], body["currency"]) == ("Negocio", "active", "DOP")
    assert body["contributed_cents"] == body["pending_cents"] == 30000000
    investment = body["id"]

    assert _add(client, investment, ret, "return").status_code == 200
    # Mixto: el capital tiene que ser mayor que 0 y menor que el crédito.
    assert _add(client, investment, mixed, "mixed", 6000000).status_code == 422
    assert _add(client, investment, mixed, "mixed").status_code == 422
    body = _add(client, investment, mixed, "mixed", 5000000).json()
    assert body["capital_returned_cents"] == 5000000
    assert body["returns_cents"] == 900000 + 1000000
    assert body["pending_cents"] == 25000000
    assert body["last_credit"] == "2026-01-28"
    assert [e["role"] for e in body["entries"]] == ["contribution", "return", "mixed"]
    assert body["annual_rate"] is not None and body["annual_rate"] > 0

    tx = _tx(client, mixed)
    assert (tx["link"], tx["investment_role"], tx["investment_capital_cents"]) == (
        "investment",
        "mixed",
        5000000,
    )
    assert (tx["amount_cents"], tx["gross_cents"], tx["kind"]) == (-1000000, -6000000, "ingreso")
    assert _tx(client, first)["investment"]["title"] == "Negocio"

    # El aporte no resta de lo que te quedó; el rendimiento es ingreso y el capital, no.
    after = client.get("/api/summary", params={"month": MONTH}).json()
    assert after["third_party_cents"] == before["third_party_cents"] - 30000000
    assert after["invested_cents"] == 30000000
    assert after["income_cents"] == before["income_cents"] - 5000000
    # El segundo envío grande al mismo destino se propone (sin enlazarse); el chico, no.
    review = client.get("/api/review", params={"month": MONTH}).json()
    proposed = {(i["kind"], i["fingerprint"]): i for i in review}
    assert proposed[("aporte_posible", second)]["investment_id"] == investment
    assert not any(i["fingerprint"] in (first, small) for i in review)
    assert _tx(client, second)["link"] == ""
    assert _tx(client, second)["suggested_investment"]["kind"] == "aporte_posible"


def test_change_a_credit_type_rename_and_write_off(client: TestClient) -> None:
    first, *_ = _fps(client, SENT)
    ret, _ = _fps(client, BACK)
    investment = _create(client, first).json()["id"]
    _add(client, investment, ret, "return")
    path = f"/api/investments/{investment}/members/{ret}"
    body = client.put(path, json={"role": "capital"}, headers=WRITE).json()
    assert (body["capital_returned_cents"], body["returns_cents"]) == (900000, 0)
    assert client.put(path, json={"role": "mixed"}, headers=WRITE).status_code == 422
    body = client.put(path, json={"role": "mixed", "capital_cents": 400000}, headers=WRITE).json()
    assert (body["capital_returned_cents"], body["returns_cents"]) == (400000, 500000)
    # Un aporte no cambia de tipo.
    put = client.put(
        f"/api/investments/{investment}/members/{first}", json={"role": "return"}, headers=WRITE
    )
    assert put.status_code == 404

    patch = {"name": "Préstamo", "with_whom": "Socio", "written_off": True}
    body = client.patch(f"/api/investments/{investment}", json=patch, headers=WRITE).json()
    assert (body["title"], body["with_whom"], body["status"]) == (
        "Préstamo",
        "Socio",
        "written_off",
    )
    listed = client.get("/api/investments").json()
    assert (listed["active_count"], listed["pending_dop_cents"]) == (0, 0)
    body = client.patch(
        f"/api/investments/{investment}", json={"written_off": False}, headers=WRITE
    ).json()
    assert body["status"] == "active"
    assert client.get("/api/investments/open").json()[0]["id"] == investment


def test_list_totals_closed_and_account_filter(client: TestClient) -> None:
    first, _, small = _fps(client, SENT)
    ret, mixed = _fps(client, BACK)
    one = _create(client, first, with_whom="Socio").json()["id"]
    _add(client, one, ret, "return")
    two = _create(client, small).json()["id"]
    _add(client, two, mixed, "mixed", 150000)  # vuelve los 1,500 y rinde 58,500: cerrada
    listed = client.get("/api/investments").json()
    rows = {r["id"]: r for r in listed["investments"]}
    assert rows[two]["status"] == "closed" and rows[one]["status"] == "active"
    assert [r["id"] for r in listed["investments"]] == [two, one]  # la última actividad primero
    assert listed["pending_dop_cents"] == 30000000
    assert listed["returns_year_dop_cents"] == 900000 + 5850000  # los dos cobros son de 2026
    assert listed["year"] == 2026
    assert listed["active_count"] == 1
    cards = client.get("/api/investments", params={"accounts": "popular:credit_card"}).json()
    assert cards["investments"] == []


def test_removing_the_last_contribution_deletes_the_investment(client: TestClient) -> None:
    first, *_ = _fps(client, SENT)
    ret, _ = _fps(client, BACK)
    investment = _create(client, first).json()["id"]
    _add(client, investment, ret, "return")
    gone = client.delete(f"/api/investments/{investment}/members/{first}", headers=WRITE)
    assert gone.status_code == 204
    assert client.get(f"/api/investments/{investment}").status_code == 404
    assert _tx(client, ret)["link"] == ""  # el crédito vuelve a su categoría
    assert _tx(client, ret)["category"] == "Otros ingresos"


def test_validation_and_conflicts(client: TestClient) -> None:
    first, second, _ = _fps(client, SENT)
    ret, _ = _fps(client, BACK)
    card = next(i for i in _items(client) if i["account"] == "popular:credit_card")
    assert _create(client, ret).status_code == 422  # un crédito no es un aporte
    assert _create(client, card["fingerprint"]).status_code == 422  # una tarjeta, tampoco
    assert _create(client, "no-existe").status_code == 404
    investment = _create(client, first).json()["id"]
    assert _create(client, first).status_code == 409
    assert _add(client, investment, second, "return").status_code == 422  # débito como cobro
    assert _add(client, 999, ret, "return").status_code == 404
    no_header = client.post("/api/investments", json={"fingerprint": second})
    assert no_header.status_code == 403
    candidates = client.get(f"/api/investments/{investment}/candidates?kind=contribution").json()
    assert candidates[0]["fingerprint"] == second and candidates[0]["primary"]
    credits = client.get(f"/api/investments/{investment}/candidates?kind=credit").json()
    assert {c["fingerprint"] for c in credits} >= {ret}


def test_without_investments_the_list_is_empty(client: TestClient) -> None:
    listed = client.get("/api/investments").json()
    assert listed["investments"] == [] and listed["active_count"] == 0
    assert client.get("/api/summary", params={"month": MONTH}).json()["invested_cents"] == 0


def test_a_credit_before_the_first_contribution_is_rejected(client: TestClient) -> None:
    _, second, _ = _fps(client, SENT)  # 12 ene
    ret, _ = _fps(client, BACK)  # 20 ene
    first_credit_day = _tx(client, ret)["day"]
    investment = _create(client, second).json()["id"]
    # Un crédito del 20 es posterior: entra. Uno anterior al aporte del 12, no.
    early = next(
        i
        for i in _items(client)
        if i["amount_cents"] < 0 and i["day"] < "2026-01-12" and i["can_invest_credit"]
    )
    response = _add(client, investment, early["fingerprint"], "return")
    assert response.status_code == 422
    assert "anterior al primer aporte (2026-01-12)" in response.json()["detail"]
    assert first_credit_day > "2026-01-12"
    assert _add(client, investment, ret, "return").status_code == 200


def test_credits_can_go_to_a_written_off_investment(client: TestClient) -> None:
    first, *_ = _fps(client, SENT)
    ret, _ = _fps(client, BACK)
    investment = _create(client, first).json()["id"]
    client.patch(f"/api/investments/{investment}", json={"written_off": True}, headers=WRITE)
    assert client.get("/api/investments/open").json() == []
    lost = client.get("/api/investments/open", params={"include_lost": "true"}).json()
    assert [(i["id"], i["status"]) for i in lost] == [(investment, "written_off")]
    body = _add(client, investment, ret, "return").json()
    assert body["returns_cents"] == 900000


def test_a_reviewed_proposal_leaves_the_row_hint(client: TestClient) -> None:
    first, second, _ = _fps(client, SENT)
    _create(client, first, with_whom="Socio Inventado")
    assert _tx(client, second)["suggested_investment"]["kind"] == "aporte_posible"
    path = f"/api/review/aporte_posible/{second}"
    assert client.put(path, json={"reviewed": True}, headers=WRITE).status_code == 200
    assert _tx(client, second)["suggested_investment"] is None
    review = client.get("/api/review", params={"month": MONTH}).json()
    kinds = {(i["kind"], i["fingerprint"]) for i in review}
    assert ("aporte_posible", second) not in kinds
    assert ("tercero_grande", second) in kinds  # vuelve a salir lo que es


def test_capital_back_beyond_contributions_shows_as_excess(client: TestClient) -> None:
    *_, small = _fps(client, SENT)  # 1,500
    ret, _ = _fps(client, BACK)  # 9,000
    investment = _create(client, small).json()["id"]
    body = _add(client, investment, ret, "capital").json()
    assert (body["capital_returned_cents"], body["excess_cents"], body["returns_cents"]) == (
        150000,
        750000,
        750000,
    )
    assert body["status"] == "closed"
    entry = next(e for e in body["entries"] if e["fingerprint"] == ret)
    assert (entry["capital_cents"], entry["excess_cents"]) == (150000, 750000)
    tx = _tx(client, ret)
    assert (tx["kind"], tx["amount_cents"]) == ("ingreso", -750000)
