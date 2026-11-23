"""The redesigned "It is an installment…": a person instead of a group, the earlier charges
listed and confirmed one by one, the charges a new plan can start from, and editing a plan
(name, count, whose it is). Synthetic statements only."""

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


def _database(tmp_path: Path, months: tuple[str, ...] = MONTHS) -> Path:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        for index, month in enumerate(months):
            rows = [
                (f"{month}-05", "LIBRERIA FICTICIA", "500.00"),
                (f"{month}-10", STORE.format(ref=f"R{index}"), "150.00", "USD"),
            ]
            statement = live_helpers.card_statement(f"{month}-28", rows, period_start=f"{month}-01")
            assert live_helpers.ingest_card(conn, statement) == "parsed"
    return path


def _client(path: Path) -> TestClient:
    return TestClient(create_app(path, today=lambda: date(2026, 4, 30)), "http://127.0.0.1")


def _store_rows(client: TestClient) -> list[dict]:
    rows = []
    for month in MONTHS:
        items = client.get("/api/transactions", params={"month": month}).json()["items"]
        rows.extend(r for r in items if r["description"].startswith("Store.com*"))
    return sorted(rows, key=lambda r: r["day"])


def _create(client: TestClient, **extra: object) -> dict:
    last = _store_rows(client)[-1]
    body = {"fingerprint": last["fingerprint"], "name": "Phone", "count": 6, **extra}
    created = client.post("/api/installments", json=body, headers=WRITE)
    assert created.status_code == 201, created.text
    return created.json()


def _groups(client: TestClient) -> list[dict]:
    return client.get("/api/shared").json()["groups"]


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return _database(tmp_path)


@pytest.fixture
def client(path: Path) -> TestClient:
    return _client(path)


def test_the_draft_lists_the_earlier_charges_with_their_numbers(client: TestClient) -> None:
    rows = _store_rows(client)

    draft = client.get(f"/api/transactions/{rows[-1]['fingerprint']}/installment-draft").json()

    assert [e["fingerprint"] for e in draft["earlier"]] == [r["fingerprint"] for r in rows[:2]]
    assert [e["number"] for e in draft["earlier"]] == [1, 2]
    assert draft["earlier"][0]["amount_cents"] == 15000
    assert draft["number"] == 3
    assert draft["number_known"] is True


def test_the_number_is_unknown_when_the_card_has_no_earlier_months(tmp_path: Path) -> None:
    client = _client(_database(tmp_path, months=("2026-04",)))
    (row,) = [r for r in _store_rows(client)]

    draft = client.get(f"/api/transactions/{row['fingerprint']}/installment-draft").json()

    assert draft["earlier"] == []
    assert draft["number_known"] is False


def test_an_unchecked_earlier_charge_is_left_out_of_the_plan(client: TestClient) -> None:
    rows = _store_rows(client)

    plan = _create(client, earlier=[rows[1]["fingerprint"]])

    assert plan["first_month"] == "2026-03"
    assert plan["paid"] == 2
    first = _store_rows(client)[0]
    assert first["installment"] is None


def test_a_new_person_gets_a_two_person_group(client: TestClient) -> None:
    plan = _create(client, new_person="Person B")

    (group,) = _groups(client)
    assert plan["group_id"] == group["id"]
    assert plan["contact_name"] == "Person B"
    detail = client.get(f"/api/shared/groups/{group['id']}").json()
    assert sorted(m["name"] for m in detail["members"] if not m["is_me"]) == ["Person B"]
    assert len(detail["timeline"]) == 3


def test_a_person_with_a_pair_group_uses_it(path: Path) -> None:
    with closing(db.connect(path)) as conn, conn:
        person = ledger_store.contact_for(conn, "Person B")
        other = ledger_store.contact_for(conn, "Person C")
        ledger_store.create_group(conn, "Trip", [person, other])
        pair = ledger_store.create_group(conn, "Us two", [person])
    client = _client(path)

    plan = _create(client, contact_id=person)

    assert plan["group_id"] == pair
    assert len(_groups(client)) == 2


def test_a_person_only_in_a_bigger_group_gets_their_own_pair_group(path: Path) -> None:
    with closing(db.connect(path)) as conn, conn:
        person = ledger_store.contact_for(conn, "Person B")
        other = ledger_store.contact_for(conn, "Person C")
        trip = ledger_store.create_group(conn, "Trip", [person, other])
    client = _client(path)

    plan = _create(client, contact_id=person)

    assert plan["group_id"] != trip
    assert len(_groups(client)) == 2


def test_a_charge_shared_by_hand_keeps_its_group_and_is_not_recorded_twice(path: Path) -> None:
    client = _client(path)
    last = _store_rows(client)[-1]
    with closing(db.connect(path)) as conn, conn:
        person = ledger_store.contact_for(conn, "Person B")
        other = ledger_store.contact_for(conn, "Person C")
        trip = ledger_store.create_group(conn, "Trip", [person, other])
    shared = client.post(
        f"/api/shared/groups/{trip}/entries",
        json={
            "fingerprint": last["fingerprint"],
            "split": "exact",
            "shares": [{"contact_id": person, "cents": 15000}],
        },
        headers=WRITE,
    )
    assert shared.status_code == 201, shared.text

    plan = _create(client, contact_id=person)

    assert plan["group_id"] == trip
    detail = client.get(f"/api/shared/groups/{trip}").json()
    assert len(detail["timeline"]) == 3


def test_the_people_are_the_contacts_of_the_users_groups(path: Path) -> None:
    with closing(db.connect(path)) as conn, conn:
        person = ledger_store.contact_for(conn, "Person B")
        ledger_store.create_group(conn, "Trip", [person])
    client = _client(path)

    people = client.get("/api/installments/people").json()

    assert people == [{"id": person, "name": "Person B"}]


def test_the_charges_a_plan_can_start_from_leave_out_the_taken_ones(client: TestClient) -> None:
    before = client.get("/api/installments/charges").json()
    _create(client)

    after = client.get("/api/installments/charges").json()

    stores = [c for c in before if c["description"].startswith("Store.com*")]
    assert len(stores) == 3
    assert stores[0]["day"] >= stores[-1]["day"]
    assert not [c for c in after if c["description"].startswith("Store.com*")]


def test_the_charges_for_a_plan_are_on_its_card_with_their_number(client: TestClient) -> None:
    rows = _store_rows(client)
    plan = _create(client, earlier=[], number=3)

    found = client.get("/api/installments/charges", params={"plan_id": plan["id"]}).json()

    by_fp = {c["fingerprint"]: c for c in found}
    assert by_fp[rows[0]["fingerprint"]]["number"] == 1
    assert by_fp[rows[1]["fingerprint"]]["number"] == 2
    assert all(c["currency"] == "USD" for c in found)


def test_editing_renames_and_changes_the_count(client: TestClient) -> None:
    plan = _create(client)

    edited = client.patch(
        f"/api/installments/{plan['id']}", json={"name": "New phone", "count": 12}, headers=WRITE
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "New phone"
    assert edited.json()["count"] == 12
    assert edited.json()["last_month"] == "2027-01"


def test_the_count_cannot_drop_below_a_linked_installment(client: TestClient) -> None:
    plan = _create(client)

    edited = client.patch(f"/api/installments/{plan['id']}", json={"count": 2}, headers=WRITE)

    assert edited.status_code == 409


def test_making_a_plan_someone_elses_records_the_installments_in_their_group(
    client: TestClient,
) -> None:
    plan = _create(client)

    edited = client.patch(
        f"/api/installments/{plan['id']}",
        json={"owner": {"new_person": "Person B"}},
        headers=WRITE,
    ).json()

    assert edited["contact_name"] == "Person B"
    detail = client.get(f"/api/shared/groups/{edited['group_id']}").json()
    assert len(detail["timeline"]) == 3


def test_making_a_members_plan_mine_takes_the_installments_out_of_the_group(
    client: TestClient,
) -> None:
    plan = _create(client, new_person="Person B")

    edited = client.patch(
        f"/api/installments/{plan['id']}", json={"owner": {}}, headers=WRITE
    ).json()

    assert edited["group_id"] is None and edited["contact_id"] is None
    detail = client.get(f"/api/shared/groups/{plan['group_id']}").json()
    assert detail["timeline"] == []
    assert _store_rows(client)[-1]["amount_cents"] == 15000


def test_renaming_a_members_plan_renames_its_group_expenses(client: TestClient) -> None:
    plan = _create(client, new_person="Person B")

    client.patch(f"/api/installments/{plan['id']}", json={"name": "Pixel"}, headers=WRITE)

    detail = client.get(f"/api/shared/groups/{plan['group_id']}").json()
    assert {e["description"] for e in detail["timeline"]} == {"Pixel"}


def test_a_hand_shared_expense_survives_making_the_plan_mine(path: Path) -> None:
    client = _client(path)
    last = _store_rows(client)[-1]
    with closing(db.connect(path)) as conn, conn:
        person = ledger_store.contact_for(conn, "Person B")
        group = ledger_store.create_group(conn, "Us two", [person])
    client.post(
        f"/api/shared/groups/{group}/entries",
        json={
            "fingerprint": last["fingerprint"],
            "split": "exact",
            "shares": [{"contact_id": person, "cents": 15000}],
        },
        headers=WRITE,
    )
    plan = _create(client, contact_id=person)

    client.patch(f"/api/installments/{plan['id']}", json={"owner": {}}, headers=WRITE)

    detail = client.get(f"/api/shared/groups/{group}").json()
    assert len(detail["timeline"]) == 1  # the one shared by hand


def test_earlier_charges_of_another_plan_are_not_offered(client: TestClient) -> None:
    rows = _store_rows(client)
    first = client.post(
        "/api/installments",
        json={"fingerprint": rows[1]["fingerprint"], "name": "Old", "count": 2},
        headers=WRITE,
    )
    assert first.status_code == 201, first.text

    draft = client.get(f"/api/transactions/{rows[-1]['fingerprint']}/installment-draft").json()
    created = client.post(
        "/api/installments",
        json={"fingerprint": rows[-1]["fingerprint"], "name": "New", "count": 6, "number": 1},
        headers=WRITE,
    )

    assert draft["earlier"] == []
    assert created.status_code == 201, created.text
