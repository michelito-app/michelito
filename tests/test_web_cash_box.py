"""Caja fuerte desde la API: saldo, movimientos a mano, retiros guardados, depósitos, Resumen y
filtro de cuentas, con datos inventados."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.analysis import rates
from finanzas.analysis.accounts import CASH_BOX_KEY
from finanzas.web.app import create_app
from tests.test_spending import _add_bank_rows, seed

WRITE = {"X-Finanzas": "1"}
MONTH = "2026-01"
WITHDRAWAL = "RETIRO CAJERO AUTOMATICO INVENTADO"
DEPOSIT = "DEPOSITO EFECTIVO INVENTADO"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "finanzas.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-10", WITHDRAWAL, "debit", "2000000"),
                ("2026-01-25", DEPOSIT, "credit", "600000"),
            ],
        )
        with conn:
            rates.store_bcrd(conn, {"2026-01": Decimal("60")})
    return TestClient(create_app(path, today=lambda: date(2026, 2, 7)), "http://127.0.0.1")


def _fp(client: TestClient, text: str) -> str:
    items = client.get("/api/transactions", params={"month": MONTH}).json()["items"]
    return next(i["fingerprint"] for i in items if i["description"] == text)


def _entry(client: TestClient, **body):
    return client.post("/api/cash-box/entries", json=body, headers=WRITE)


def test_an_unused_box_is_empty_and_not_an_account(client: TestClient) -> None:
    box = client.get("/api/cash-box").json()
    assert (box["exists"], box["balances"], box["lines"], box["label"]) == (
        False,
        [],
        [],
        "Caja fuerte",
    )
    assert CASH_BOX_KEY not in {a["key"] for a in client.get("/api/accounts").json()}


def test_writes_need_the_header(client: TestClient) -> None:
    body = {"kind": "initial", "day": "2026-01-01", "amount_cents": 100, "currency": "USD"}
    assert client.post("/api/cash-box/entries", json=body).status_code == 403
    assert client.put(f"/api/cash-box/stored/{_fp(client, WITHDRAWAL)}").status_code == 403


def test_store_a_withdrawal_and_undo(client: TestClient) -> None:
    fp = _fp(client, WITHDRAWAL)
    before = client.get("/api/transactions", params={"month": MONTH}).json()
    row = next(i for i in before["items"] if i["fingerprint"] == fp)
    assert (row["can_store"], row["cash_box_role"], row["category"]) == (True, "", "Efectivo")

    stored = client.put(f"/api/cash-box/stored/{fp}", headers=WRITE)
    assert stored.status_code == 200
    body = stored.json()
    assert (body["cash_box_role"], body["link"], body["category"], body["can_store"]) == (
        "stored",
        "cash_box",
        "Caja fuerte",
        False,
    )
    assert client.put(f"/api/cash-box/stored/{fp}", headers=WRITE).status_code == 409
    summary = client.get("/api/summary", params={"month": MONTH}).json()
    assert summary["cash_box_cents"] == 2_000_000
    box = client.get("/api/cash-box").json()
    assert box["balances"] == [{"currency": "DOP", "amount_cents": 2_000_000}]
    assert box["lines"][0]["kind"] == "stored" and box["lines"][0]["in_flow"] is True

    undone = client.delete(f"/api/cash-box/stored/{fp}", headers=WRITE).json()
    assert (undone["cash_box_role"], undone["category"]) == ("", "Efectivo")
    assert client.delete(f"/api/cash-box/stored/{fp}", headers=WRITE).status_code == 404
    assert client.get("/api/summary", params={"month": MONTH}).json()["cash_box_cents"] == 0


def test_only_cash_debits_can_be_stored(client: TestClient) -> None:
    fp = _fp(client, DEPOSIT)
    assert client.put(f"/api/cash-box/stored/{fp}", headers=WRITE).status_code == 422
    assert client.put("/api/cash-box/stored/no-existe", headers=WRITE).status_code == 404


def test_manual_entries_are_movements_of_the_box_account(client: TestClient) -> None:
    categories = client.get("/api/categories").json()
    groceries = next(c["id"] for c in categories if c["name"] == "Supermercado")
    created = _entry(
        client,
        kind="expense",
        day="2026-01-20",
        amount_cents=150_000,
        currency="DOP",
        category_id=groceries,
        note="Colmado",
    )
    assert created.status_code == 201
    box = created.json()
    assert box["exists"] is True
    # Sin nada más en la caja, la salida la deja en negativo: se avisa, no se bloquea.
    assert box["negative"] == [{"currency": "DOP", "amount_cents": -150_000}]
    line = box["lines"][0]
    assert (line["kind"], line["category"], line["note"], line["entry_id"]) == (
        "expense",
        "Supermercado",
        "Colmado",
        1,
    )
    assert CASH_BOX_KEY in {a["key"] for a in client.get("/api/accounts").json()}
    # El filtro de cuentas: la caja es una cuenta más.
    only = client.get("/api/transactions", params={"month": MONTH, "accounts": CASH_BOX_KEY}).json()
    [row] = only["items"]
    assert (row["fingerprint"], row["account_label"], row["kind"], row["cash_entry_id"]) == (
        "caja-1",
        "Caja fuerte",
        "gasto",
        1,
    )
    assert only["total_cents"] == 150_000
    # «Todo el comercio» no aplica a lo anotado a mano.
    patch = {"category": "Restaurantes", "scope": "merchant"}
    assert client.patch("/api/transactions/caja-1", json=patch, headers=WRITE).status_code == 422
    fixed = client.patch(
        "/api/transactions/caja-1", json={"category": "Restaurantes"}, headers=WRITE
    )
    assert fixed.json()["category"] == "Restaurantes"

    edited = client.put(
        "/api/cash-box/entries/1",
        json={"day": "2026-01-21", "amount_cents": 2_500, "currency": "USD"},
        headers=WRITE,
    ).json()
    assert edited["lines"][0]["currency"] == "USD"
    assert edited["lines"][0]["dop_cents"] == -150_000  # US$ 25 a 60
    gone = client.delete("/api/cash-box/entries/1", headers=WRITE).json()
    assert gone["lines"] == []
    assert client.get("/api/transactions/caja-1").status_code == 404
    assert client.delete("/api/cash-box/entries/1", headers=WRITE).status_code == 404


def test_invalid_entries(client: TestClient) -> None:
    salary = next(c["id"] for c in client.get("/api/categories").json() if c["name"] == "Salario")
    base = {"day": "2026-01-01", "amount_cents": 100, "currency": "DOP"}
    assert _entry(client, kind="expense", category_id=salary, **base).status_code == 422
    assert _entry(client, kind="otro", **base).status_code == 422
    assert _entry(client, kind="initial", **{**base, "amount_cents": 0}).status_code == 422
    assert _entry(client, kind="initial", **{**base, "currency": "EUR"}).status_code == 422


def test_a_deposit_from_the_box_and_in_another_currency(client: TestClient) -> None:
    _entry(client, kind="initial", day="2026-01-01", amount_cents=50_000, currency="USD")
    fp = _fp(client, DEPOSIT)
    row = client.get(f"/api/transactions/{fp}").json()
    assert (row["can_deposit"], row["kind"]) == (True, "ingreso")
    linked = client.put(f"/api/cash-box/deposits/{fp}", json={"currency": "USD"}, headers=WRITE)
    assert linked.status_code == 200
    body = linked.json()
    # RD$ 6,000 a 60: salieron US$ 100 de la caja.
    assert (body["cash_box_role"], body["cash_box_currency"], body["cash_box_amount_cents"]) == (
        "deposit",
        "USD",
        10_000,
    )
    assert body["kind"] == "transferencia"
    box = client.get("/api/cash-box").json()
    assert box["balances"] == [{"currency": "USD", "amount_cents": 40_000}]
    assert box["total_dop_cents"] == 50_000 * 60 - 600_000
    summary = client.get("/api/summary", params={"month": MONTH}).json()
    assert summary["cash_box_cents"] == 0  # un depósito no es un retiro guardado

    client.delete(f"/api/cash-box/deposits/{fp}", headers=WRITE)
    told = client.put(
        f"/api/cash-box/deposits/{fp}",
        json={"currency": "USD", "amount_cents": 9_800},
        headers=WRITE,
    ).json()
    assert told["cash_box_amount_cents"] == 9_800
    undone = client.delete(f"/api/cash-box/deposits/{fp}", headers=WRITE).json()
    assert (undone["cash_box_role"], undone["kind"]) == ("", "ingreso")
    same = {"currency": "DOP", "amount_cents": 100}
    assert client.put(f"/api/cash-box/deposits/{fp}", json=same, headers=WRITE).status_code == 422
    withdrawal = _fp(client, WITHDRAWAL)
    assert (
        client.put(f"/api/cash-box/deposits/{withdrawal}", json={}, headers=WRITE).status_code
        == 422
    )


@pytest.mark.parametrize("name", ["Caja fuerte", "Inversiones", "Devolución de capital"])
@pytest.mark.parametrize("scope", ["transaction", "merchant"])
def test_link_categories_cannot_be_chosen_by_hand(
    client: TestClient, name: str, scope: str
) -> None:
    """«RETIRO CAJERO…» → «Caja fuerte» (también con «Todo el comercio»): 422 y nada cambia."""
    fp = _fp(client, WITHDRAWAL)
    before = client.get("/api/transactions", params={"month": MONTH}).json()
    patch = {"category": name, "scope": scope}
    response = client.patch(f"/api/transactions/{fp}", json=patch, headers=WRITE)
    assert response.status_code == 422
    assert "la pone su vínculo" in response.json()["detail"]
    assert client.get("/api/transactions", params={"month": MONTH}).json() == before
    assert client.get(f"/api/transactions/{fp}").json()["category"] == "Efectivo"


def test_link_categories_take_no_keywords_nor_reassignments(client: TestClient) -> None:
    categories = {c["name"]: c for c in client.get("/api/categories").json()}
    box = categories["Caja fuerte"]["id"]
    body = {"keywords": ["RETIRO CAJERO"]}
    assert client.patch(f"/api/categories/{box}", json=body, headers=WRITE).status_code == 422
    assert (
        client.post(f"/api/categories/{box}/preview", json=body, headers=WRITE).status_code == 422
    )
    assert next(c for c in client.get("/api/categories").json() if c["id"] == box)["keywords"] == []
    # Renombrarla u ocultarla sigue igual (sin palabras clave).
    assert (
        client.patch(f"/api/categories/{box}", json={"keywords": []}, headers=WRITE).status_code
        == 200
    )
    made = client.post(
        "/api/categories", json={"name": "Mía", "kind": "gasto"}, headers=WRITE
    ).json()
    fp = _fp(client, WITHDRAWAL)
    client.patch(f"/api/transactions/{fp}", json={"category_id": made["id"]}, headers=WRITE)
    gone = client.delete(f"/api/categories/{made['id']}?reassign_to={box}", headers=WRITE)
    assert gone.status_code == 422
    assert client.get(f"/api/transactions/{fp}").json()["category"] == "Mía"


def test_returns_can_still_be_chosen_by_hand(client: TestClient) -> None:
    fp = _fp(client, DEPOSIT)
    patch = {"category": "Rendimientos"}
    fixed = client.patch(f"/api/transactions/{fp}", json=patch, headers=WRITE)
    assert fixed.status_code == 200 and fixed.json()["category"] == "Rendimientos"


def test_dates_go_from_2000_to_a_month_ahead(client: TestClient) -> None:
    """Hoy es 2026-02-07 en la app de prueba: hasta 2026-03-10."""
    base = {"kind": "expense", "amount_cents": 100, "currency": "DOP"}
    far = _entry(client, day="2062-01-20", **base)
    assert far.status_code == 422 and "2026-03-10" in far.json()["detail"]
    assert _entry(client, day="1999-12-31", **base).status_code == 422
    assert _entry(client, day="2026-03-10", **base).status_code == 201
    edit = {"day": "2062-01-20", "amount_cents": 100, "currency": "DOP"}
    assert client.put("/api/cash-box/entries/1", json=edit, headers=WRITE).status_code == 422
    assert client.get("/api/cash-box").json()["lines"][0]["day"] == "2026-03-10"


def test_amounts_must_be_whole_cents(client: TestClient) -> None:
    base = {"kind": "initial", "day": "2026-01-01", "currency": "DOP"}
    assert _entry(client, amount_cents="100", **base).status_code == 422
    assert _entry(client, amount_cents=100.5, **base).status_code == 422
    assert _entry(client, amount_cents=True, **base).status_code == 422
    fp = _fp(client, DEPOSIT)
    body = {"currency": "USD", "amount_cents": "9800"}
    assert client.put(f"/api/cash-box/deposits/{fp}", json=body, headers=WRITE).status_code == 422


def test_an_empty_note_clears_it_and_a_missing_one_keeps_it(client: TestClient) -> None:
    _entry(client, kind="expense", day="2026-01-20", amount_cents=100, currency="DOP", note="Algo")
    keep = {"day": "2026-01-20", "amount_cents": 200, "currency": "DOP"}
    box = client.put("/api/cash-box/entries/1", json=keep, headers=WRITE).json()
    assert box["lines"][0]["note"] == "Algo"
    cleared = client.put("/api/cash-box/entries/1", json={**keep, "note": ""}, headers=WRITE)
    assert cleared.json()["lines"][0]["note"] == ""
    _entry(client, kind="income", day="2026-01-20", amount_cents=100, currency="DOP", note="x")
    nulled = client.put("/api/cash-box/entries/2", json={**keep, "note": None}, headers=WRITE)
    assert all(line["note"] == "" for line in nulled.json()["lines"])


def test_orphan_marks_can_be_undone(client: TestClient, tmp_path: Path) -> None:
    """Un retiro guardado o un depósito cuyo movimiento ya no aparece se desmarcan igual."""
    stored, deposit = _fp(client, WITHDRAWAL), _fp(client, DEPOSIT)
    client.put(f"/api/cash-box/stored/{stored}", headers=WRITE)
    client.put(f"/api/cash-box/deposits/{deposit}", json={}, headers=WRITE)
    with closing(db.connect(tmp_path / "finanzas.db")) as conn, conn:
        conn.execute("DELETE FROM transactions WHERE description IN (?, ?)", (WITHDRAWAL, DEPOSIT))
    assert client.get(f"/api/transactions/{stored}").status_code == 404
    assert client.delete(f"/api/cash-box/stored/{stored}", headers=WRITE).status_code == 204
    assert client.delete(f"/api/cash-box/deposits/{deposit}", headers=WRITE).status_code == 204
    assert client.delete(f"/api/cash-box/stored/{stored}", headers=WRITE).status_code == 404
    with closing(db.connect(tmp_path / "finanzas.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM link_members").fetchone()[0] == 0


def test_a_shared_exit_says_its_group(client: TestClient) -> None:
    box = _entry(client, kind="expense", day="2026-01-20", amount_cents=90_000, currency="DOP")
    assert box.json()["lines"][0]["group"] is None
    shared = {"shared": {"people": 3, "with_whom": "Ana"}}
    assert client.patch("/api/transactions/caja-1", json=shared, headers=WRITE).status_code == 200
    assert client.get("/api/cash-box").json()["lines"][0]["group"] == "Ana"
