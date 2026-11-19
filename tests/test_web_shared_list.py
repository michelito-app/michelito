"""`GET /api/shared` and `GET /api/shared/new-candidates` on the demo database (made-up data
from `tests.e2e_server`)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito.web.app import create_app
from tests.e2e_server import (
    DEMO_TODAY,
    PENDING_GIFT,
    SETTLED_EXPENSE,
    SMALL_TAX,
    SUGGESTED_DINNER,
    WRITTEN_OFF_EXPENSE,
    build_demo_db,
)

VISA = "demo:credit_card"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    return TestClient(create_app(path, today=lambda: DEMO_TODAY), "http://127.0.0.1")


def _description(client: TestClient, fingerprint: str) -> str:
    return client.get(f"/api/transactions/{fingerprint}").json()["description"]


def test_all_groups_newest_activity_first_with_totals(client: TestClient) -> None:
    body = client.get("/api/shared").json()

    clothes, books, gift = body["groups"]
    assert [_description(client, g["first_fingerprint"]) for g in body["groups"]] == [
        SETTLED_EXPENSE,
        WRITTEN_OFF_EXPENSE,
        PENDING_GIFT,
    ]
    assert (clothes["title"], clothes["status"], clothes["last_activity"]) == (
        "Ropa de Marta",  # spanish-data
        "settled",
        "2026-01-10",  # the manual refund, after the expense (Dec 18)
    )
    assert clothes["paid"] == [{"currency": "DOP", "cents": 435000}]
    assert clothes["reimbursed"] == [{"currency": "DOP", "cents": 217500}]
    [cash] = clothes["refunds"]
    assert (cash["manual"], cash["description"], cash["account_label"]) == (True, "Marta", "")
    assert (books["title"], books["status"], books["pending"]) == ("Rosa", "written_off", [])
    assert books["expenses"][0]["written_off_cents"] == 60000
    assert (gift["title"], gift["status"]) == ("Luis", "pending")
    assert gift["pending"] == [{"currency": "DOP", "cents": 400000}]
    assert gift["pending_dop_cents"] == 400000
    [expense] = gift["expenses"]
    assert (expense["for_other"], expense["share_cents"], expense["pending_cents"]) == (
        True,
        0,
        400000,
    )
    assert (gift["first_day"], gift["last_day"]) == ("2025-12-20", "2025-12-20")

    assert body["owed_dop_cents"] == 400000  # same as Pending for the groups
    assert body["reimbursed_year_dop_cents"] == 217500  # the January 2026 cash
    assert (body["year"], body["open_count"]) == (2026, 1)
    assert body["unconverted"] == {"owed_usd_cents": 0, "reimbursed_usd_cents": 0}


def test_owed_matches_pending(client: TestClient) -> None:
    pending = client.get("/api/pending").json()
    shared = [i for i in pending["owed_to_me"] if i["kind"] == "shared"]

    assert client.get("/api/shared").json()["owed_dop_cents"] == sum(
        i["pending_dop_cents"] for i in shared
    )


def test_account_filter(client: TestClient) -> None:
    body = client.get("/api/shared", params={"accounts": VISA}).json()

    assert [g["title"] for g in body["groups"]] == ["Luis"]
    assert body["reimbursed_year_dop_cents"] == 0
    assert client.get("/api/shared", params={"accounts": "none"}).status_code == 422


def test_new_candidates_route_does_not_clash_with_a_group_id(client: TestClient) -> None:
    found = client.get("/api/shared/new-candidates").json()

    descriptions = [c["description"] for c in found]
    assert descriptions
    for taken in (PENDING_GIFT, SETTLED_EXPENSE, WRITTEN_OFF_EXPENSE):
        assert taken not in descriptions  # already shared
    assert not any(
        d.startswith(("RETIRO CAJERO", "AUT PAGO", "PAGO TARJETA")) for d in descriptions
    )
    assert all(c["amount_cents"] > 0 for c in found)
    label = next(a["label"] for a in client.get("/api/accounts").json() if a["key"] == VISA)
    visa = client.get("/api/shared/new-candidates", params={"accounts": VISA}).json()
    assert visa and {c["account_label"] for c in visa} == {label}


def test_new_candidates_primary_is_the_suggestion_rule(client: TestClient) -> None:
    found = client.get("/api/shared/new-candidates").json()

    by_text = {c["description"]: c for c in found}
    assert by_text[SUGGESTED_DINNER]["primary"]  # RD$ 5,200 restaurant
    assert not by_text[SMALL_TAX]["primary"]  # RD$ 3 tax
    assert not by_text["CINE INVENTADO SANTO DOMINGO"]["primary"]  # RD$ 640
    # Suggested first, then the rest; within each block, newest first.
    flags = [c["primary"] for c in found]
    assert flags == sorted(flags, reverse=True) and True in flags and False in flags
    for block in (True, False):
        days = [c["day"] for c in found if c["primary"] is block]
        assert days == sorted(days, reverse=True)
    # The demo only suggests DOP expenses: all of at least RD$ 2,000.
    assert all(c["amount_cents"] >= 200_000 for c in found if c["primary"])


def test_a_group_still_opens_by_id(client: TestClient) -> None:
    group = client.get("/api/shared").json()["groups"][0]

    assert (
        client.get(f"/api/shared/{group['id']}").json()["title"] == "Ropa de Marta"
    )  # spanish-data
