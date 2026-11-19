"""Reportes: comparar meses (categorías × meses) con datos inventados."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas.analysis.accounts import AccountInfo
from finanzas.web import reports
from finanzas.web.app import create_app
from tests.e2e_server import build_demo_db
from tests.test_anomalies import move


def card(key, through):
    return AccountInfo(key, "credit_card", f"Tarjeta {key}", date.fromisoformat(through))


def bank(key, through):
    return AccountInfo(key, "checking", f"Cuenta {key}", date.fromisoformat(through))


ACCOUNTS = [card("A", "2026-07-31"), bank("BANK", "2026-07-31")]


def _moves():
    """Seis meses iguales y un julio con más supermercado y un viaje."""
    moves = []
    for month in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"):
        moves.append(move(f"{month}-05", "4000"))
        moves.append(move(f"{month}-07", "2000", "FARMACIA", "Salud"))
        moves.append(move(f"{month}-15", "-50000", "NOMINA", "Salario", "BANK"))
        moves.append(
            move(f"{month}-20", "1000", "MB A PERSONA", "Transferencias a terceros", "BANK")
        )
    moves.append(move("2026-07-05", "9000"))
    moves.append(move("2026-07-07", "500", "FARMACIA", "Salud"))
    moves.append(move("2026-07-15", "-50000", "NOMINA", "Salario", "BANK"))
    return moves


def _compare(**options):
    return reports.compare(_moves(), ACCOUNTS, {}, **options)


def _row(rows, key):
    return next(r for r in rows if r.key == key)


class TestCompare:
    def test_months_default_to_the_newest_twelve_oldest_first(self):
        result = _compare()
        assert [m.month for m in result.months] == [
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
            "2026-05",
            "2026-06",
            "2026-07",
        ]

    def test_top_rows_are_income_spending_third_party_and_net(self):
        result = _compare(first="2026-06", last="2026-07")
        assert [r.key for r in result.totals] == ["ingresos", "gastos", "terceros", "neto"]
        spent = _row(result.totals, "gastos")
        assert [c.amount for c in spent.cells] == [Decimal(6000), Decimal(9500)]
        net = _row(result.totals, "neto")
        assert [c.amount for c in net.cells] == [Decimal(43000), Decimal(40500)]
        assert _row(result.totals, "terceros").cells[1].amount == Decimal(0)

    def test_category_cells_compare_with_their_habitual(self):
        result = _compare(first="2026-06", last="2026-07")
        groceries = _row(result.categories, "Supermercado")
        july = groceries.cells[1]
        assert (july.amount, july.habitual, july.flag, july.level) == (
            Decimal(9000),
            Decimal(4000),
            "up",
            3,
        )
        health = _row(result.categories, "Salud").cells[1]
        assert (health.flag, health.level) == ("down", 0)
        # Junio está dentro de lo habitual.
        assert groceries.cells[0].flag is None
        assert [r.key for r in result.categories] == ["Supermercado", "Salud"]  # por total
        assert groceries.label == "Supermercado"

    def test_small_differences_need_the_floor(self):
        assert reports.cell_flag(Decimal(1401), Decimal(400)) == ("up", 3)
        assert reports.cell_flag(Decimal(1400), Decimal(400)) == (None, 0)  # RD$ 1,000 justo
        assert reports.cell_flag(Decimal(6500), Decimal(5000)) == (None, 0)  # 30 % justo
        assert reports.cell_flag(Decimal(8100), Decimal(5000)) == ("up", 2)
        assert reports.cell_flag(Decimal(7000), Decimal(5000)) == ("up", 1)
        assert reports.cell_flag(Decimal(100), None) == (None, 0)

    def test_range_is_validated(self):
        with pytest.raises(ValueError, match="desde"):
            _compare(first="2026-07", last="2026-06")
        with pytest.raises(ValueError, match="24"):
            available = [f"{y}-{m:02d}" for y in (2023, 2024, 2025) for m in range(1, 13)]
            reports.month_range(available, "2023-01", "2025-12")

    def test_honors_the_account_filter(self):
        result = reports.compare(_moves(), ACCOUNTS, {}, selected=["BANK"])
        assert _row(result.totals, "gastos").cells[-1].amount == Decimal(0)
        assert result.categories == []


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    return TestClient(create_app(path), "http://127.0.0.1")


def test_api_compare(client: TestClient) -> None:
    body = client.get("/api/reports/compare").json()
    assert [m["month"] for m in body["months"]] == ["2025-12", "2026-01", "2026-02"]
    assert [m["partial"] for m in body["months"]] == [False, True, True]
    assert [r["key"] for r in body["totals"]] == ["ingresos", "gastos", "terceros", "neto"]
    cell = body["categories"][0]["cells"][0]
    assert set(cell) == {"amount_cents", "habitual_cents", "flag", "level"}
    assert all(isinstance(c["amount_cents"], int) for r in body["categories"] for c in r["cells"])
    only = client.get(
        "/api/reports/compare",
        params={"from": "2026-01", "to": "2026-01", "accounts": "demo:credit_card"},
    ).json()
    assert [m["month"] for m in only["months"]] == ["2026-01"]
    assert client.get("/api/reports/compare", params={"from": "2026-13"}).status_code == 422
    bad = client.get("/api/reports/compare", params={"from": "2026-02", "to": "2026-01"})
    assert bad.status_code == 422
