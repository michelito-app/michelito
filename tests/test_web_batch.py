"""Selección múltiple desde la API (`PATCH /api/transactions`), con datos inventados: aplica y
omite con motivo, rechaza categorías de vínculo, límite, atomicidad, una sola entrada de
bitácora y «Deshacer» que restaura cada corrección anterior exacta."""

from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db, dossier
from finanzas.analysis import corrections
from finanzas.web import batch_edit
from tests.test_web_log import (
    BACK,
    DELIVERY,
    DEPOSIT,
    MONTH,
    REFUND,
    WITHDRAWAL,
    WRITE,
    _category_id,
    _fp,
    _fps,
    _log,
    _patch,
    _tx,
    _undo,
)
from tests.test_web_log import client as client  # noqa: F401 (fixture)

CLAUDE = {**WRITE, "X-Finanzas-Autor": "claude"}


def _batch(client: TestClient, fps: list[str], category: str, headers: dict = WRITE, **extra):
    body = {"fingerprints": fps, "category_id": _category_id(client, category), **extra}
    return client.patch("/api/transactions", json=body, headers=headers)


def test_needs_the_header(client: TestClient) -> None:
    response = client.patch("/api/transactions", json={"fingerprints": ["x"], "category_id": 1})
    assert response.status_code == 403


def test_applies_the_valid_ones_and_skips_the_rest_with_a_reason(client: TestClient) -> None:
    deposit, back, withdrawal = _fp(client, DEPOSIT), _fp(client, BACK), _fp(client, WITHDRAWAL)
    pesos, dollars = _fp(client, "DEPOSITO CAMBIO"), _fp(client, "TRANSFERENCIA A PERSONA")
    made = client.post("/api/exchanges", json={"fingerprints": [pesos, dollars]}, headers=WRITE)
    assert made.status_code == 201

    response = _batch(
        client, [deposit, back, pesos, withdrawal, "no-existe"], "Cripto", reason="Venta P2P"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == [deposit, back]
    assert [(s["fingerprint"], s["reason"]) for s in body["skipped"]] == [
        (pesos, "vinculo"),
        (withdrawal, "direccion"),
        ("no-existe", "desconocida"),
    ]
    assert all(s["message"] for s in body["skipped"])
    assert [_tx(client, fp)["category"] for fp in (deposit, back)] == ["Cripto", "Cripto"]
    assert _tx(client, pesos)["category"] == "Cambio de divisas"
    assert _tx(client, withdrawal)["category"] == "Efectivo"

    entries = [e for e in _log(client) if e["kind"] == batch_edit.BATCH_KIND]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == body["entry_id"]
    assert (entry["subject"], entry["before"]["text"], entry["after"]["text"]) == (
        "2 transacciones",
        "Otros ingresos",
        "Cripto",
    )
    assert (entry["reason"], entry["affected"], entry["author"]) == ("Venta P2P", 2, "usuario")
    assert sorted(entry["fingerprints"]) == sorted([deposit, back])
    assert entry["can_undo"] is True


def test_never_creates_a_merchant_rule_and_records_the_author(client: TestClient) -> None:
    deposit = _fp(client, DEPOSIT)
    assert _batch(client, [deposit], "Cripto", CLAUDE).status_code == 200
    rules = client.get("/api/log").json()["items"][0]
    assert (rules["author"], rules["target_type"]) == ("claude", "categoria")
    assert "merchant_categories" not in rules["after"]["rows"]


def test_nothing_to_change_leaves_no_entry(client: TestClient) -> None:
    withdrawal = _fp(client, WITHDRAWAL)
    body = _batch(client, [withdrawal], "Cripto").json()
    assert (body["applied"], body["entry_id"]) == ([], None)
    assert _log(client) == []


@pytest.mark.parametrize("name", ["Caja fuerte", "Inversiones", "Devolución de capital"])
def test_link_categories_are_rejected(client: TestClient, name: str) -> None:
    response = _batch(client, [_fp(client, DEPOSIT)], name)
    assert response.status_code == 422
    assert _log(client) == []


def test_unknown_category_limit_and_reason_length(client: TestClient) -> None:
    deposit = _fp(client, DEPOSIT)
    unknown = {"fingerprints": [deposit], "category_id": 99999}
    assert client.patch("/api/transactions", json=unknown, headers=WRITE).status_code == 422
    too_many = [f"h{i}" for i in range(batch_edit.BATCH_MAX + 1)]
    assert _batch(client, too_many, "Cripto").status_code == 422
    assert _batch(client, [], "Cripto").status_code == 422
    at_limit = [deposit, *(f"h{i}" for i in range(batch_edit.BATCH_MAX - 1))]
    assert _batch(client, at_limit, "Cripto").status_code == 200
    assert _batch(client, [_fp(client, BACK)], "Cripto", reason="x" * 501).status_code == 422


def test_all_or_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    deposit, back, refund = _fp(client, DEPOSIT), _fp(client, BACK), _fp(client, REFUND)
    real = corrections.set_transaction_category
    calls: list[str] = []

    def failing(conn, fingerprint, category):  # noqa: ANN001, ANN202
        calls.append(fingerprint)
        if len(calls) == 2:
            raise ValueError("falla inventada")
        return real(conn, fingerprint, category)

    monkeypatch.setattr(corrections, "set_transaction_category", failing)
    response = _batch(client, [deposit, back, refund], "Cripto", reason="x")
    assert response.status_code == 422
    assert calls == [deposit, back]
    assert [_tx(client, fp)["category"] for fp in (deposit, back, refund)] == [
        "Otros ingresos",
        "Otros ingresos",
        "Otros ingresos",
    ]
    assert _log(client) == []


def _note_rows(tmp_path: Path, fps: list[str]) -> dict[str, tuple]:
    """Las filas de `transaction_notes` (la base del fixture `client`, en `tmp_path`)."""
    with closing(db.connect(tmp_path / "finanzas.db")) as conn:
        marks = ", ".join("?" * len(fps))
        rows = conn.execute(
            "SELECT fingerprint, category_id, one_off, note FROM transaction_notes "
            f"WHERE fingerprint IN ({marks})",
            fps,
        )
        return {r[0]: (r[1], r[2], r[3]) for r in rows}


def test_undo_restores_each_previous_correction_exactly(client: TestClient, tmp_path: Path) -> None:
    bare, noted, salary = _fp(client, DEPOSIT), _fp(client, BACK), _fp(client, REFUND)
    _patch(client, noted, note="de Pedro")  # fila sin categoría
    _patch(client, salary, category_id=_category_id(client, "Salario"))
    before = _note_rows(tmp_path, [bare, noted, salary])
    assert bare not in before and before[noted][0] is None

    entry = _batch(client, [bare, noted, salary], "Cripto", reason="P2P").json()["entry_id"]
    batch = next(e for e in _log(client) if e["id"] == entry)
    assert batch["before"]["text"] == "Otros ingresos, Salario"
    # Después del lote: una nota y un «gasto único» que deshacer el lote no debe tocar.
    _patch(client, bare, note="después")
    _patch(client, salary, one_off=True)

    undone = _undo(client, entry)
    assert undone.status_code == 200
    assert undone.json()["undoes"] == entry
    after = _note_rows(tmp_path, [bare, noted, salary])
    cripto = _category_id(client, "Cripto")
    assert all(row[0] != cripto for row in after.values())
    assert after[bare] == (None, 0, "después")
    assert after[noted] == before[noted]
    assert after[salary] == (before[salary][0], 1, None)
    assert [_tx(client, fp)["category"] for fp in (bare, noted, salary)] == [
        "Otros ingresos",
        "Otros ingresos",
        "Salario",
    ]
    assert _batch_entries(client) == 2  # el lote y su «Deshacer»


def test_undo_without_later_edits_removes_the_new_rows(client: TestClient, tmp_path: Path) -> None:
    bare, back = _fp(client, DEPOSIT), _fp(client, BACK)
    entry = _batch(client, [bare, back], "Cripto").json()["entry_id"]
    assert _undo(client, entry).status_code == 200
    assert _note_rows(tmp_path, [bare, back]) == {}


def test_undo_is_blocked_if_one_changed_later(client: TestClient) -> None:
    bare, back = _fp(client, DEPOSIT), _fp(client, BACK)
    entry = _batch(client, [bare, back], "Cripto").json()["entry_id"]
    _patch(client, back, category_id=_category_id(client, "Salario"))
    later = _log(client)[0]
    batch = next(e for e in _log(client) if e["id"] == entry)
    assert (batch["can_undo"], batch["blocked_by"]) == (False, later["id"])
    blocked = _undo(client, entry)
    assert blocked.status_code == 409 and str(later["id"]) in blocked.json()["detail"]
    assert _tx(client, bare)["category"] == "Cripto"
    assert _undo(client, later["id"]).status_code == 200
    assert _undo(client, entry).status_code == 200
    assert [_tx(client, fp)["category"] for fp in (bare, back)] == ["Otros ingresos"] * 2


def _batch_entries(client: TestClient) -> int:
    return sum(1 for e in _log(client) if e["kind"] == batch_edit.BATCH_KIND)


def test_crypto_is_its_own_income_in_summary_reports_and_dossier(
    client: TestClient, tmp_path: Path
) -> None:
    deposit, back = _fp(client, DEPOSIT), _fp(client, BACK)
    assert _batch(client, [deposit, back], "Cripto").status_code == 200

    summary = client.get("/api/summary", params={"month": MONTH}).json()
    lines = {i["category"]: i for i in summary["incomes"]}
    assert (lines["Cripto"]["amount_cents"], lines["Cripto"]["count"]) == (1_500_000, 2)
    assert "Otros ingresos" in lines
    assert sum(i["amount_cents"] for i in summary["incomes"]) == summary["income_cents"]

    compare = client.get("/api/reports/compare").json()
    rows = {r["key"]: r for r in compare["incomes"]}
    months = [m["month"] for m in compare["months"]]
    crypto = rows["ingreso:Cripto"]
    assert crypto["label"] == "Cripto"
    assert crypto["cells"][months.index(MONTH)]["amount_cents"] == 1_500_000
    assert "ingreso:Otros ingresos" in rows
    assert [r["key"] for r in compare["totals"]] == ["ingresos", "gastos", "terceros", "neto"]

    with closing(db.connect(tmp_path / "finanzas.db")) as conn:
        found = dossier.build(conn, MONTH)
        other = [m for m in months if m != MONTH]
        without = dossier.build(conn, other[0]) if other else None
    assert found.data["totales"]["ingresos_cripto"] == "15000.00"
    assert "ingresos cripto: 15000.00" in found.markdown
    if without is not None:  # un mes sin cripto no cambia (ni su huella)
        assert "ingresos_cripto" not in without.data["totales"]


def _review(client: TestClient, kind: str) -> list[dict]:
    items = client.get("/api/review", params={"month": MONTH}).json()
    return [i for i in items if i["kind"] == kind]


def test_a_later_batch_stops_the_rule_suggestion_and_the_hint(client: TestClient) -> None:
    first, second, third = _fps(client, DELIVERY)
    _patch(client, first, category_id=_category_id(client, "Salud"))
    _patch(client, second, category_id=_category_id(client, "Salud"))
    assert len(_review(client, "regla_posible")) == 1
    assert client.get(f"/api/transactions/{third}/history").json()["rule_hint"] is not None

    assert _batch(client, [first, second], "Restaurantes").status_code == 200
    assert _review(client, "regla_posible") == []
    assert client.get(f"/api/transactions/{third}/history").json()["rule_hint"] is None


def test_batches_never_reach_the_rule_minimum(client: TestClient) -> None:
    first, second, _ = _fps(client, DELIVERY)
    assert _batch(client, [first, second], "Salud").status_code == 200
    assert _review(client, "regla_posible") == []


def test_a_batch_on_another_transaction_of_the_merchant_contradicts_too(
    client: TestClient,
) -> None:
    first, second, third = _fps(client, DELIVERY)
    salud = _category_id(client, "Salud")
    _patch(client, first, category_id=salud)
    _patch(client, second, category_id=salud)
    entry = _batch(client, [third], "Restaurantes").json()["entry_id"]
    assert _review(client, "regla_posible") == []
    assert _undo(client, entry).status_code == 200  # deshecho, ya no contradice
    assert len(_review(client, "regla_posible")) == 1


def test_cash_box_entries_follow_the_cash_box_category_rule(client: TestClient) -> None:
    body = {"kind": "expense", "day": "2026-01-15", "amount_cents": 50000, "currency": "DOP"}
    assert client.post("/api/cash-box/entries", json=body, headers=WRITE).status_code == 201
    income = {**body, "kind": "income", "day": "2026-01-16"}
    assert client.post("/api/cash-box/entries", json=income, headers=WRITE).status_code == 201
    out, came_in = "caja-1", "caja-2"
    assert _tx(client, out)["amount_cents"] > 0 > _tx(client, came_in)["amount_cents"]

    to_income = _batch(client, [out, came_in], "Cripto").json()
    assert to_income["applied"] == [came_in]
    assert [(s["fingerprint"], s["reason"]) for s in to_income["skipped"]] == [(out, "caja")]
    to_expense = _batch(client, [out, came_in], "Delivery").json()
    assert to_expense["applied"] == [out]
    assert [(s["fingerprint"], s["reason"]) for s in to_expense["skipped"]] == [(came_in, "caja")]
    to_transfer = _batch(client, [out], "Entre mis cuentas").json()
    assert [s["reason"] for s in to_transfer["skipped"]] == ["caja"]

    # Una sola, desde su detalle: la misma regla.
    single = _patch(client, out, category_id=_category_id(client, "Salario"))
    assert single.status_code == 422 and "caja fuerte" in single.json()["detail"]
    assert _patch(client, out, category_id=_category_id(client, "Restaurantes")).status_code == 200
