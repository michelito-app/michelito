"""Recurrentes del hogar desde la API: proveedor con varios nombres, «Unir con…», «Separar» y
«Es recurrente…» desde una transacción; cabecera `X-Finanzas`, bitácora con su tipo y deshacer.
Datos y proveedores inventados."""

from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.analysis import categories as cat
from finanzas.analysis import corrections, providers
from finanzas.web.app import create_app
from tests.test_spending import _add_bank_rows, seed

WRITE = {"X-Finanzas": "1"}
TEL = "proveedor:telfic"
ROWS = [
    ("2025-10-05", "TELFIC PAGO 0001", "debit", "150000"),
    ("2025-11-06", "TELFIC WB 0002", "debit", "150000"),
    ("2026-01-04", "TELFIC IBANKING 0003", "debit", "200000"),
    ("2026-01-20", "TELFIC PAGO 0004", "debit", "100000"),
    ("2025-10-03", "RECARGA TELFIC 8095550000", "debit", "30000"),
    ("2025-10-08", "AGUA FICTICIA PAGO 11", "debit", "45000"),
    ("2025-11-08", "AGUA FICTICIA WEB 12", "debit", "45000"),
    ("2025-12-08", "AGUA FICTICIA PAGO 13", "debit", "45000"),
    ("2026-01-08", "AGUA FICTICIA WEB 14", "debit", "45000"),
    ("2026-01-15", "CLUB INVENTADO ANUAL", "debit", "480000"),
    ("2025-10-25", "AUT PAGO 0000000099 REF1", "debit", "1500000"),
    ("2025-11-25", "AUT PAGO 0000000099 REF2", "debit", "1500000"),
    ("2025-12-26", "AUT PAGO 0000000099 REF3", "debit", "1500000"),
    ("2025-12-28", "AUT PAGO 0000000099 REF4", "debit", "5000000"),
    ("2026-01-25", "AUT PAGO 0000000099 REF5", "debit", "1500000"),
]
RULES = {
    "TELFIC PAGO": cat.UTILITIES,
    "TELFIC WB": cat.UTILITIES,
    "TELFIC IBANKING": cat.UTILITIES,
    "RECARGA TELFIC": cat.UTILITIES,
    "AGUA FICTICIA PAGO": cat.UTILITIES,
    "AGUA FICTICIA WEB": cat.UTILITIES,
    "CLUB INVENTADO ANUAL": cat.OTHER,
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake = providers.make_provider("telfic", "Telefónica Ficticia", r"TELFIC")
    monkeypatch.setattr(providers, "PROVIDERS", (fake,))
    path = tmp_path / "finanzas.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(conn, ROWS)
        with conn:
            for merchant, ref in RULES.items():
                corrections.set_merchant_category(conn, merchant, ref)
    return TestClient(create_app(path, today=lambda: date(2026, 2, 7)), "http://127.0.0.1")


def _recurring(client: TestClient) -> dict:
    response = client.get("/api/recurring")
    assert response.status_code == 200
    return response.json()


def _item(body: dict, merchant: str) -> dict | None:
    return next((i for i in body["items"] if i["merchant"] == merchant), None)


def _fp(client: TestClient, text: str) -> str:
    items = client.get("/api/transactions", params={"month": "2026-01"}).json()["items"]
    return next(i["fingerprint"] for i in items if i["description"].startswith(text))


def _last_log(client: TestClient) -> dict:
    return client.get("/api/log").json()["items"][0]


def _undo(client: TestClient, entry_id: int) -> None:
    assert client.post(f"/api/log/{entry_id}/undo", headers=WRITE).status_code == 200


def test_provider_with_several_names_and_loan_in_their_groups(client: TestClient) -> None:
    body = _recurring(client)
    phone = _item(body, TEL)
    assert phone is not None
    assert (phone["name"], phone["group"], phone["provider"]) == (
        "Telefónica Ficticia",
        "Servicios",
        True,
    )
    assert phone["members"] == ["TELFIC IBANKING", "TELFIC PAGO", "TELFIC WB"]
    assert phone["charges"] == 3 and phone["variable"] is True
    assert phone["typical_cents"] == 150000  # el doble de enero cubre diciembre
    loan = _item(body, "AUT PAGO 0000000099")
    assert loan is not None
    assert (loan["group"], loan["typical_cents"], loan["extras_year_cents"]) == (
        "Préstamos",
        1500000,
        0,  # el abono fue en 2025
    )
    assert {"key": TEL, "name": "Telefónica Ficticia"} in body["providers"]
    assert [g["group"] for g in body["groups"]][:2] == ["Préstamos", "Servicios"]
    assert all("RECARGA" not in m for i in body["items"] for m in i["members"])


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/recurring/join", {"merchant": "AGUA FICTICIA WEB", "target": "AGUA FICTICIA PAGO"}),
        ("/api/recurring/separate", {"merchant": "TELFIC WB"}),
    ],
)
def test_new_writes_require_the_header(client: TestClient, path: str, payload: dict) -> None:
    assert client.post(path, json=payload).status_code == 403
    assert client.get("/api/log").json()["items"] == []


def test_mark_from_transaction_requires_the_header(client: TestClient) -> None:
    fp = _fp(client, "CLUB INVENTADO ANUAL")
    assert client.post(f"/api/transactions/{fp}/recurring", json={}).status_code == 403


def test_join_logs_and_undoes(client: TestClient) -> None:
    assert _item(_recurring(client), "AGUA FICTICIA PAGO") is None
    response = client.post(
        "/api/recurring/join",
        json={"merchant": "AGUA FICTICIA WEB", "target": "AGUA FICTICIA PAGO"},
        headers=WRITE,
    )
    assert response.status_code == 200
    water = _item(response.json(), "AGUA FICTICIA PAGO")
    assert water is not None
    assert water["members"] == ["AGUA FICTICIA PAGO", "AGUA FICTICIA WEB"]
    assert water["charges"] == 4
    entry = _last_log(client)
    assert (entry["kind"], entry["subject"]) == (
        "recurrente_union",
        "AGUA FICTICIA WEB → AGUA FICTICIA PAGO",
    )
    assert entry["after"]["text"] == "con AGUA FICTICIA PAGO"
    assert entry["affected"] == 4 and entry["can_undo"]
    _undo(client, entry["id"])
    assert _item(_recurring(client), "AGUA FICTICIA PAGO") is None
    assert _last_log(client)["undoes"] == entry["id"]


def test_join_errors(client: TestClient) -> None:
    unknown = {"merchant": "NO EXISTE", "target": TEL}
    assert client.post("/api/recurring/join", json=unknown, headers=WRITE).status_code == 404
    same = {"merchant": TEL, "target": TEL}
    assert client.post("/api/recurring/join", json=same, headers=WRITE).status_code == 422
    alone = {"merchant": "AGUA FICTICIA WEB"}
    assert client.post("/api/recurring/separate", json=alone, headers=WRITE).status_code == 422


def test_join_with_provider_then_separate_and_undo(client: TestClient) -> None:
    joined = client.post(
        "/api/recurring/join",
        json={"merchant": "AGUA FICTICIA WEB", "target": TEL},
        headers=WRITE,
    ).json()
    assert "AGUA FICTICIA WEB" in _item(joined, TEL)["members"]
    separated = client.post(
        "/api/recurring/separate", json={"merchant": "AGUA FICTICIA WEB"}, headers=WRITE
    )
    assert separated.status_code == 200
    assert "AGUA FICTICIA WEB" not in _item(separated.json(), TEL)["members"]
    entry = _last_log(client)
    assert entry["kind"] == "recurrente_union"
    assert entry["subject"] == "AGUA FICTICIA WEB · fuera de Telefónica Ficticia"
    _undo(client, entry["id"])
    assert "AGUA FICTICIA WEB" in _item(_recurring(client), TEL)["members"]


def test_separate_a_member_of_the_list_and_undo(client: TestClient) -> None:
    response = client.post(
        "/api/recurring/separate", json={"merchant": "TELFIC PAGO"}, headers=WRITE
    )
    assert response.status_code == 200
    phone = _item(response.json(), TEL)
    assert phone is None or "TELFIC PAGO" not in phone["members"]
    entry = _last_log(client)
    assert entry["after"]["text"] == "por separado"
    _undo(client, entry["id"])
    assert "TELFIC PAGO" in _item(_recurring(client), TEL)["members"]


def test_mark_undetected_transaction_as_recurring_and_undo(client: TestClient) -> None:
    fp = _fp(client, "CLUB INVENTADO ANUAL")
    state = client.get(f"/api/transactions/{fp}/recurring").json()
    assert state == {
        "eligible": True,
        "reason": "",
        "key": "CLUB INVENTADO ANUAL",
        "name": "CLUB INVENTADO ANUAL",
        "currency": "DOP",
        "recurring": False,
        "mark": None,
        "group": "",
        "loan": False,
    }
    response = client.post(
        f"/api/transactions/{fp}/recurring",
        json={"cadence": "anual", "group": "vivienda"},
        headers=WRITE,
    )
    assert response.status_code == 200
    assert response.json()["recurring"] is True
    assert (response.json()["group"], response.json()["mark"]) == ("Vivienda", "confirmed")
    club = _item(_recurring(client), "CLUB INVENTADO ANUAL")
    assert club is not None
    assert (club["cadence"], club["yearly_cents"], club["group_key"]) == (
        "anual",
        480000,
        "vivienda",
    )
    entry = _last_log(client)
    assert (entry["kind"], entry["subject"]) == ("recurrente", "CLUB INVENTADO ANUAL")
    assert entry["after"]["text"] == "es recurrente, anual, en Vivienda"
    _undo(client, entry["id"])
    assert _item(_recurring(client), "CLUB INVENTADO ANUAL") is None
    assert client.get(f"/api/transactions/{fp}/recurring").json()["recurring"] is False


def test_mark_from_a_provider_payment_marks_the_provider(client: TestClient) -> None:
    fp = _fp(client, "TELFIC IBANKING")
    state = client.get(f"/api/transactions/{fp}/recurring").json()
    assert (state["key"], state["name"], state["recurring"]) == (
        TEL,
        "Telefónica Ficticia",
        True,
    )
    client.post(f"/api/transactions/{fp}/recurring", json={}, headers=WRITE)
    assert _item(_recurring(client), TEL)["mark"] == "confirmed"


def test_loan_installments_from_transaction(client: TestClient) -> None:
    fp = _fp(client, "AUT PAGO 0000000099 REF5")
    assert client.get(f"/api/transactions/{fp}/recurring").json()["loan"] is True
    response = client.post(
        f"/api/transactions/{fp}/recurring", json={"installments_left": 10}, headers=WRITE
    )
    assert response.status_code == 200
    loan = _item(_recurring(client), "AUT PAGO 0000000099")
    assert (loan["group"], loan["installments_left"]) == ("Préstamos", 10)


def test_recharge_or_bad_body_cannot_be_marked(client: TestClient) -> None:
    items = client.get("/api/transactions", params={"month": "2025-10"}).json()["items"]
    fp = next(i["fingerprint"] for i in items if i["description"].startswith("RECARGA"))
    state = client.get(f"/api/transactions/{fp}/recurring").json()
    assert state["eligible"] is False and "recargas" in state["reason"]
    assert (
        client.post(f"/api/transactions/{fp}/recurring", json={}, headers=WRITE).status_code == 422
    )
    club = _fp(client, "CLUB INVENTADO ANUAL")
    bad = client.post(f"/api/transactions/{club}/recurring", json={"group": "nada"}, headers=WRITE)
    assert bad.status_code == 422
    missing = client.get("/api/transactions/no-existe/recurring")
    assert missing.status_code == 404
    assert client.get("/api/log").json()["items"] == []
