"""Installment plans in the board's API: the draft from a charge, creating a plan (with the
earlier installments), the row's "installment n/N", a member's plan, review and deleting.
Synthetic statements only."""

from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import ledger_store
from michelito.web.app import create_app
from tests import live_helpers

WRITE = {"X-Michelito": "1"}
STORE = "Store.com*{ref} STORE.COM/BILL"
MONTHS = ("2026-02", "2026-03", "2026-04")


def _charge(month: str, ref: str, amount: str = "150.00") -> live_helpers.Row:
    return (f"{month}-10", STORE.format(ref=ref), amount, "USD")


def _database(tmp_path: Path, extra: tuple[live_helpers.Row, ...] = ()) -> Path:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        for index, month in enumerate(MONTHS):
            rows = [
                ("" + month + "-05", "LIBRERIA FICTICIA", "500.00"),
                _charge(month, f"R{index}"),
            ]
            if month == MONTHS[-1]:
                rows.extend(extra)
            statement = live_helpers.card_statement(f"{month}-28", rows, period_start=f"{month}-01")
            assert live_helpers.ingest_card(conn, statement) == "parsed"
    return path


def _client(path: Path) -> TestClient:
    return TestClient(create_app(path, today=lambda: date(2026, 4, 30)), "http://127.0.0.1")


def _store_rows(client: TestClient, month: str) -> list[dict]:
    items = client.get("/api/transactions", params={"month": month}).json()["items"]
    return [r for r in items if r["description"].startswith("Store.com*")]


def _last(client: TestClient) -> dict:
    (row,) = _store_rows(client, MONTHS[-1])
    return row


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return _client(_database(tmp_path))


def test_the_draft_prefills_from_the_charge_and_counts_the_earlier_ones(
    client: TestClient,
) -> None:
    row = _last(client)

    draft = client.get(f"/api/transactions/{row['fingerprint']}/installment-draft").json()

    assert draft["amount_cents"] == 15000
    assert draft["currency"] == "USD"
    assert draft["number"] == 3
    assert draft["paid_before"] == 2
    assert draft["name"]


def test_creating_a_plan_links_the_earlier_installments(client: TestClient) -> None:
    row = _last(client)

    created = client.post(
        "/api/installments",
        json={"fingerprint": row["fingerprint"], "name": "Phone (Store)", "count": 6},
        headers=WRITE,
    )

    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["paid"] == 3
    assert plan["count"] == 6
    assert plan["remaining_cents"] == 45000
    assert plan["first_month"] == "2026-02"
    assert plan["last_month"] == "2026-07"
    assert [i["state"] for i in plan["installments"]] == ["paid"] * 3 + ["pending"] * 3
    assert _last(client)["installment"] == {
        "plan_id": plan["id"],
        "name": "Phone (Store)",
        "number": 3,
        "count": 6,
    }
    (first,) = _store_rows(client, "2026-02")
    assert first["installment"]["number"] == 1
    assert client.get("/api/installments").json()[0]["id"] == plan["id"]


def test_the_number_given_wins_over_the_earlier_charges(client: TestClient) -> None:
    row = _last(client)

    plan = client.post(
        "/api/installments",
        json={"fingerprint": row["fingerprint"], "name": "Phone", "count": 6, "number": 1},
        headers=WRITE,
    ).json()

    assert plan["first_month"] == "2026-04"
    assert plan["paid"] == 1


def test_a_members_plan_records_each_installment_in_their_group(tmp_path: Path) -> None:
    path = _database(tmp_path)
    with closing(db.connect(path)) as conn, conn:
        brother = ledger_store.contact_for(conn, "Person B")
        group = ledger_store.create_group(conn, "Phone", [brother])
    client = _client(path)
    row = _last(client)

    plan = client.post(
        "/api/installments",
        json={
            "fingerprint": row["fingerprint"],
            "name": "Phone (Store)",
            "count": 6,
            "group_id": group,
            "contact_id": brother,
        },
        headers=WRITE,
    ).json()

    assert plan["group_id"] == group and plan["contact_id"] == brother
    assert plan["group_name"] == "Phone"
    detail = client.get(f"/api/shared/groups/{group}").json()
    assert len(detail["timeline"]) == 3
    assert detail["owed_to_me"] == [{"currency": "USD", "cents": 45000}]
    assert _last(client)["amount_dop_cents"] in (0, None)

    deleted = client.delete(f"/api/installments/{plan['id']}", headers=WRITE)

    assert deleted.status_code == 204
    assert client.get(f"/api/shared/groups/{group}").json()["timeline"] == []
    assert _last(client)["installment"] is None


def test_a_linked_installment_is_not_a_one_off_and_a_later_charge_is_off_script(
    client: TestClient,
) -> None:
    first = _store_rows(client, "2026-02")[0]
    plan = client.post(
        "/api/installments",
        json={"fingerprint": first["fingerprint"], "name": "Phone", "count": 2, "number": 1},
        headers=WRITE,
    ).json()
    assert plan["paid"] == 2

    items = client.get("/api/review", params={"month": MONTHS[-1]}).json()

    off = [i for i in items if i["kind"] == "installment_off_script"]
    assert [(i["plan_id"], i["amount_cents"]) for i in off] == [(plan["id"], 15000)]
    assert "Phone" in off[0]["reason"]
    assert off[0]["installment_number"] == 3
    linked = {r["fingerprint"] for m in MONTHS[:2] for r in _store_rows(client, m)}
    for month in MONTHS[:2]:
        shown = client.get("/api/review", params={"month": month}).json()
        assert not any(i["kind"] == "one_off" and i["fingerprint"] in linked for i in shown)


def test_an_off_script_charge_can_be_linked_with_its_number(tmp_path: Path) -> None:
    odd = ("2026-04-22", STORE.format(ref="ZZ"), "151.00", "USD")
    client = _client(_database(tmp_path, (odd,)))
    first = _store_rows(client, "2026-02")[0]
    plan = client.post(
        "/api/installments",
        json={"fingerprint": first["fingerprint"], "name": "Phone", "count": 6, "number": 1},
        headers=WRITE,
    ).json()
    target = next(r for r in _store_rows(client, MONTHS[-1]) if r["amount_cents"] == 15100)

    linked = client.put(
        f"/api/installments/{plan['id']}/transactions/{target['fingerprint']}",
        json={"number": 4},
        headers=WRITE,
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["paid"] == 4

    removed = client.delete(
        f"/api/installments/{plan['id']}/transactions/{target['fingerprint']}", headers=WRITE
    )
    assert removed.json()["paid"] == 3


def test_a_charge_already_in_a_plan_cannot_start_another(client: TestClient) -> None:
    row = _last(client)
    body = {"fingerprint": row["fingerprint"], "name": "Phone", "count": 6}
    client.post("/api/installments", json=body, headers=WRITE)

    again = client.post("/api/installments", json=body, headers=WRITE)

    assert again.status_code == 409


@pytest.mark.parametrize("count", [1, 121])
def test_the_number_of_installments_is_validated(client: TestClient, count: int) -> None:
    row = _last(client)

    found = client.post(
        "/api/installments",
        json={"fingerprint": row["fingerprint"], "name": "Phone", "count": count},
        headers=WRITE,
    )

    assert found.status_code == 422


def test_the_remaining_installments_go_into_recurrings_forecast(client: TestClient) -> None:
    client.put("/api/rates/2026-04", json={"value": "60"}, headers=WRITE)
    before = client.get("/api/recurring").json()
    row = _last(client)
    client.post(
        "/api/installments",
        json={"fingerprint": row["fingerprint"], "name": "Phone", "count": 6},
        headers=WRITE,
    )

    after = client.get("/api/recurring").json()

    # The charges were a recurring series; now the plan forecasts them, once.
    assert after["monthly_cents"] == before["monthly_cents"]
    group = next(g for g in after["groups"] if g["group"] == "Cuotas")
    assert group["monthly_cents"] == 15000 * 60
    assert not any("Store.com" in i["merchant"] for i in after["items"])


def test_already_reviewed_on_an_off_script_charge_refuses_it_for_the_plan(
    client: TestClient,
) -> None:
    first = _store_rows(client, "2026-02")[0]
    client.post(
        "/api/installments",
        json={"fingerprint": first["fingerprint"], "name": "Phone", "count": 2, "number": 1},
        headers=WRITE,
    )
    (off,) = [
        i
        for i in client.get("/api/review", params={"month": MONTHS[-1]}).json()
        if i["kind"] == "installment_off_script"
    ]

    done = client.put(
        f"/api/review/installment_off_script/{off['fingerprint']}",
        json={"reviewed": True},
        headers=WRITE,
    )

    assert done.status_code == 200, done.text
    left = client.get("/api/review", params={"month": MONTHS[-1]}).json()
    assert not any(i["kind"] == "installment_off_script" for i in left)


def test_a_members_plan_is_not_the_users_forecast(tmp_path: Path) -> None:
    path = _database(tmp_path)
    with closing(db.connect(path)) as conn, conn:
        brother = ledger_store.contact_for(conn, "Person B")
        group = ledger_store.create_group(conn, "Phone", [brother])
    client = _client(path)
    client.put("/api/rates/2026-04", json={"value": "60"}, headers=WRITE)
    before = client.get("/api/recurring").json()["monthly_cents"]
    row = _last(client)
    client.post(
        "/api/installments",
        json={
            "fingerprint": row["fingerprint"],
            "name": "Phone",
            "count": 6,
            "group_id": group,
            "contact_id": brother,
        },
        headers=WRITE,
    )

    after = client.get("/api/recurring").json()
    assert after["monthly_cents"] == before - 15000 * 60
    assert not any(g["group"] == "Cuotas" for g in after["groups"])
