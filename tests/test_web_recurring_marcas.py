"""Marcas heredadas de los comercios de un proveedor, desde la API: se pueden quitar, la
«cancelé» no pierde las cuotas ni las cuotas mueven la fecha de cancelación, todo deshacible;
el grupo a mano; y «Deshacer» con la base ocupada. Datos y proveedores inventados."""

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.analysis import changelog
from finanzas.analysis import recurring_marks as marks
from tests.test_web_recurring_hogar import TEL, WRITE, _fp, _item, _last_log, _recurring, _undo
from tests.test_web_recurring_hogar import client as client  # noqa: F401 (fixture)

DAY1 = date(2025, 11, 1)
DAY2 = date(2025, 12, 1)


def _set(path: Path, merchant: str, status=None, left=None, day: date = DAY1) -> None:
    """Una marca hecha en el esquema 15 sobre un comercio que hoy va en el proveedor."""
    with closing(db.connect(path)) as conn, conn:
        marks.set_status(conn, merchant, "DOP", status, day)
        marks.set_installments(conn, merchant, "DOP", left, day)


def _row(path: Path, key: str = TEL) -> marks.Mark | None:
    with closing(db.connect(path)) as conn:
        return marks.load(conn).get((key, "DOP"))


def _put(client: TestClient, **body) -> dict:
    response = client.put(
        "/api/recurring/mark", json={"merchant": TEL, "currency": "DOP", **body}, headers=WRITE
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_inherited_dismissal_can_be_restored_and_undone(client: TestClient, tmp_path) -> None:
    path = tmp_path / "finanzas.db"
    _set(path, "TELFIC WB", "dismissed")
    assert [d["merchant"] for d in _recurring(client)["dismissed"]] == [TEL]
    body = _put(client, status=None)
    assert _item(body, TEL)["mark"] is None
    assert body["dismissed"] == []
    assert _row(path) == marks.Mark(None, None, None, None)  # «sin marca» explícito
    entry = _last_log(client)
    assert entry["kind"] == "recurrente" and entry["can_undo"]
    _undo(client, entry["id"])
    assert [d["merchant"] for d in _recurring(client)["dismissed"]] == [TEL]
    assert _row(path) is None  # vuelve a heredar


def test_cancelling_the_provider_keeps_the_member_installments(
    client: TestClient, tmp_path
) -> None:
    path = tmp_path / "finanzas.db"
    _set(path, "TELFIC PAGO", "confirmed", left=4)
    _put(client, status="cancelled")
    saved = _row(path)
    assert saved is not None
    assert (saved.status, saved.installments_left, saved.installments_on) == ("cancelled", 4, DAY1)
    assert _item(_recurring(client), TEL)["mark"] == "cancelled"


def test_installments_on_an_inherited_cancellation_keep_its_date(
    client: TestClient, tmp_path
) -> None:
    path = tmp_path / "finanzas.db"
    _set(path, "TELFIC WB", "cancelled", day=DAY2)
    _put(client, status="cancelled", installments_left=5)
    saved = _row(path)
    assert saved is not None
    assert (saved.status, saved.status_on, saved.installments_left) == ("cancelled", DAY2, 5)
    _undo(client, _last_log(client)["id"])
    assert _row(path) is None
    with closing(db.connect(path)) as conn:  # la marca del comercio no se tocó
        assert marks.load(conn)[("TELFIC WB", "DOP")].status_on == DAY2


def test_group_chosen_by_hand_and_back_to_the_category(client: TestClient) -> None:
    body = _put(client, status=None, group="vivienda")
    assert _item(body, TEL)["group"] == "Vivienda"
    assert _last_log(client)["after"]["text"] == "sin marca, en Vivienda"
    body = _put(client, status=None, group=None)
    assert _item(body, TEL)["group"] == "Servicios"


def test_mark_from_transaction_without_group_clears_the_previous_one(client: TestClient) -> None:
    fp = _fp(client, "CLUB INVENTADO ANUAL")
    url = f"/api/transactions/{fp}/recurring"
    assert client.post(url, json={"group": "vivienda"}, headers=WRITE).json()["group"] == "Vivienda"
    again = client.post(url, json={}, headers=WRITE).json()
    assert again["group"] == "Otros recurrentes"


def test_undo_state_when_the_database_is_busy(client: TestClient, tmp_path) -> None:
    path = tmp_path / "finanzas.db"
    _put(client, status="confirmed")
    with closing(db.connect(path)) as conn:
        entry = changelog.load(conn)[0]
    holder = sqlite3.connect(path)
    waiting = sqlite3.connect(path, timeout=0.05)
    waiting.row_factory = sqlite3.Row
    try:
        holder.execute("BEGIN IMMEDIATE")
        state = changelog.undo_state(waiting, entry)
        assert (state.allowed, state.message) == (False, changelog.BUSY)
        assert not waiting.in_transaction
    finally:
        holder.rollback()
        holder.close()
        waiting.close()
    with closing(db.connect(path)) as conn:
        assert changelog.undo_state(conn, entry).allowed


@pytest.mark.parametrize("merchant", ["TELFIC PAGO", "TELFIC WB"])
def test_member_marks_still_count_after_a_separate(client: TestClient, tmp_path, merchant) -> None:
    path = tmp_path / "finanzas.db"
    _set(path, merchant, "confirmed")
    response = client.post("/api/recurring/separate", json={"merchant": merchant}, headers=WRITE)
    assert response.status_code == 200
    assert _row(path, merchant) is not None
