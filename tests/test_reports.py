"""Reports: comparing months (categories × months) with made-up data."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito.analysis import categories as cat
from michelito.analysis.accounts import AccountInfo
from michelito.i18n import t
from michelito.web import reports
from michelito.web.app import create_app
from tests.e2e_server import build_demo_db
from tests.test_anomalies import move


def card(key, through):
    return AccountInfo(key, "credit_card", f"Card {key}", date.fromisoformat(through))


def bank(key, through):
    return AccountInfo(key, "checking", f"Account {key}", date.fromisoformat(through))


ACCOUNTS = [card("A", "2026-07-31"), bank("BANK", "2026-07-31")]


def _moves():
    """Six equal months and a July with more groceries and a trip."""
    moves = []
    for month in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"):
        moves.append(move(f"{month}-05", "4000"))
        moves.append(move(f"{month}-07", "2000", "FARMACIA", cat.HEALTH))
        moves.append(move(f"{month}-15", "-50000", "NOMINA", cat.SALARY, "BANK"))
        moves.append(move(f"{month}-20", "1000", "MB A PERSONA", cat.THIRD_PARTY, "BANK"))
    moves.append(move("2026-07-05", "9000"))
    moves.append(move("2026-07-07", "500", "FARMACIA", cat.HEALTH))
    moves.append(move("2026-07-15", "-50000", "NOMINA", cat.SALARY, "BANK"))
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
        assert [r.key for r in result.totals] == ["income", "expenses", "third_party", "net"]
        spent = _row(result.totals, "expenses")
        assert [c.amount for c in spent.cells] == [Decimal(6000), Decimal(9500)]
        net = _row(result.totals, "net")
        assert [c.amount for c in net.cells] == [Decimal(43000), Decimal(40500)]
        assert _row(result.totals, "third_party").cells[1].amount == Decimal(0)

    def test_category_cells_compare_with_their_usual(self):
        result = _compare(first="2026-06", last="2026-07")
        groceries = _row(result.categories, cat.GROCERIES)
        july = groceries.cells[1]
        assert (july.amount, july.habitual, july.flag, july.level) == (
            Decimal(9000),
            Decimal(4000),
            "up",
            3,
        )
        health = _row(result.categories, cat.HEALTH).cells[1]
        assert (health.flag, health.level) == ("down", 0)
        # June is within the usual range.
        assert groceries.cells[0].flag is None
        assert [r.key for r in result.categories] == [cat.GROCERIES, cat.HEALTH]  # by total
        assert groceries.label == cat.GROCERIES

    def test_small_differences_need_the_floor(self):
        assert reports.cell_flag(Decimal(1401), Decimal(400)) == ("up", 3)
        assert reports.cell_flag(Decimal(1400), Decimal(400)) == (None, 0)  # exactly RD$ 1,000
        assert reports.cell_flag(Decimal(6500), Decimal(5000)) == (None, 0)  # exactly 30 %
        assert reports.cell_flag(Decimal(8100), Decimal(5000)) == ("up", 2)
        assert reports.cell_flag(Decimal(7000), Decimal(5000)) == ("up", 1)
        assert reports.cell_flag(Decimal(100), None) == (None, 0)

    def test_range_is_validated(self):
        with pytest.raises(ValueError, match=re.escape(t("web.report.reversed_range"))):
            _compare(first="2026-07", last="2026-06")
        with pytest.raises(
            ValueError, match=re.escape(t("web.report.too_many_months", max=reports.MAX_MONTHS))
        ):
            available = [f"{y}-{m:02d}" for y in (2023, 2024, 2025) for m in range(1, 13)]
            reports.month_range(available, "2023-01", "2025-12")

    def test_honors_the_account_filter(self):
        result = reports.compare(_moves(), ACCOUNTS, {}, selected=["BANK"])
        assert _row(result.totals, "expenses").cells[-1].amount == Decimal(0)
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
    assert [r["key"] for r in body["totals"]] == ["income", "expenses", "third_party", "net"]
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
