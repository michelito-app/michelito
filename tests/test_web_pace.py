from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.rates import Rate
from michelito.web import pace
from michelito.web.app import create_app
from tests.test_spending import movement as _movement
from tests.test_spending import seed

CARDS = [
    AccountInfo("A", "credit_card", "Card A", date(2026, 10, 31)),
    AccountInfo("B", "credit_card", "Card B", date(2026, 10, 31)),
]


def movement(day, amount, *, account="A", one_off=False, currency="DOP", fingerprint=""):
    base = replace(_movement(day, amount, currency=currency), account=account, one_off=one_off)
    return replace(base, fingerprint=fingerprint or f"fp-{day}-{amount}")


MOVES = [
    movement("2026-09-02", "100"),
    movement("2026-09-10", "200"),
    movement("2026-09-10", "1000", one_off=True),
    movement("2026-09-30", "50"),
    movement("2026-10-01", "40"),
    movement("2026-10-05", "60", account="B"),
    movement("2026-10-06", "500", one_off=True, fingerprint="big"),
    movement("2026-10-25", "70"),
]


def test_current_month_counts_up_to_today():
    found = pace.build_pace(MOVES, CARDS, {}, "2026-10", date(2026, 10, 10))
    assert found.through_day == 10
    assert found.days_in_month == 31
    assert found.previous_month == "2026-09"
    assert len(found.current) == 10
    assert found.current[0] == Decimal(40)
    assert found.current[-1] == Decimal(100)  # one-offs left out of the curve
    assert found.total_to_date == Decimal(600)  # with the one-off, without the 25th
    assert len(found.previous) == 30
    assert found.previous[-1] == Decimal(350)
    assert found.previous_same_day == Decimal(300)  # 100 + 200 by the 10th
    assert found.previous_same_day_total == Decimal(1300)
    assert [(o.fingerprint, o.amount) for o in found.one_offs] == [("big", Decimal(500))]


def test_past_month_counts_every_day():
    found = pace.build_pace(MOVES, CARDS, {}, "2026-09", date(2026, 10, 10))
    assert found.finished
    assert found.through_day == 30
    assert found.current[-1] == Decimal(350)
    assert found.total_to_date == Decimal(1350)
    assert found.previous == [Decimal(0)] * 31


def test_future_month_counts_nothing():
    found = pace.build_pace(MOVES, CARDS, {}, "2026-11", date(2026, 10, 10))
    assert found.through_day == 0
    assert found.current == []
    assert found.previous_same_day == Decimal(0)
    assert found.total_to_date == Decimal(0)


def test_same_day_stops_at_the_end_of_a_shorter_month():
    moves = [movement("2026-02-28", "10"), movement("2026-03-31", "5")]
    found = pace.build_pace(moves, CARDS, {}, "2026-03", date(2026, 3, 30))
    assert not found.finished
    assert found.previous_same_day == Decimal(10)


def test_a_finished_month_compares_with_the_whole_previous_month():
    # February (28 days) against January's 31: the 29th to the 31st count too.
    moves = [movement("2026-01-10", "10"), movement("2026-01-31", "7", one_off=True)]
    moves.append(movement("2026-01-30", "5"))
    found = pace.build_pace(moves, CARDS, {}, "2026-02", date(2026, 3, 5))
    assert found.finished
    assert found.previous_same_day == Decimal(15)
    assert found.previous_same_day_total == Decimal(22)


def test_selection_and_usd_conversion():
    moves = [*MOVES, movement("2026-10-03", "2", currency="USD")]
    rates = {"2026-09": Rate(Decimal(60), "2026-09", "manual")}
    found = pace.build_pace(moves, CARDS, rates, "2026-10", date(2026, 10, 10), {"A"})
    assert found.current[-1] == Decimal(160)  # 40 + 120 (US$ 2 at 60), not B's 60


def test_january_compares_with_december():
    assert pace.previous_month("2026-01") == "2025-12"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
    return TestClient(create_app(path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")


def test_route_matches_the_summary_total(client: TestClient) -> None:
    month = client.get("/api/months").json()[-1]["month"]
    body = client.get("/api/summary/pace", params={"month": month}).json()
    summary = client.get("/api/summary", params={"month": month}).json()
    assert body["today"] == "2026-10-20"
    assert body["through_day"] == body["days_in_month"]
    assert body["total_to_date_cents"] == summary["total_cents"]
    assert body["current_cents"][-1] == summary["regular_total_cents"]


def test_route_validates_month_and_accounts(client: TestClient) -> None:
    assert client.get("/api/summary/pace", params={"month": "2026-13"}).status_code == 422
    assert client.get("/api/summary/pace").status_code == 422
    response = client.get("/api/summary/pace", params={"month": "2026-10", "accounts": "nope"})
    assert response.status_code == 422


def test_route_rejects_a_year_without_a_previous_month(client: TestClient) -> None:
    for month in ("0000-01", "0001-01", "0999-12"):
        response = client.get("/api/summary/pace", params={"month": month})
        assert response.status_code == 422, month


def test_today_month_without_expenses_is_a_month(tmp_path: Path) -> None:
    """On the 1st (nothing spent yet) the month in progress is listed and has a summary."""
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
    probe = TestClient(create_app(path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")
    newest = probe.get("/api/months").json()[0]["month"]
    year, number = (int(part) for part in newest.split("-"))
    first = date(year + number // 12, number % 12 + 1, 1)
    client = TestClient(create_app(path, today=lambda: first), "http://127.0.0.1")
    months = client.get("/api/months").json()
    current = f"{first.year:04d}-{first.month:02d}"
    assert months[0] == {"month": current, "label": months[0]["label"], "partial": True}
    assert months[1]["month"] == newest
    summary = client.get("/api/summary", params={"month": current})
    assert summary.status_code == 200
    assert summary.json()["total_cents"] == 0
    body = client.get("/api/summary/pace", params={"month": current}).json()
    assert body["through_day"] == 1
    assert body["current_cents"] == [0]
    # Two months later the gap is not filled in: only the month right after the newest.
    later = TestClient(
        create_app(path, today=lambda: date(first.year + 1, first.month, 1)), "http://127.0.0.1"
    )
    assert later.get("/api/months").json()[0]["month"] == newest


def test_demo_charges_the_pace_like_the_summary() -> None:
    from michelito.demo.app import cost_of

    assert cost_of("/api/summary/pace") == cost_of("/api/summary") == 3
