"""Shared groups through the API: several expenses, FIFO refunds, name and "with whom"."""

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import links, rates
from michelito.web.app import create_app
from tests.test_spending import _add_bank_rows, seed

WRITE = {"X-Michelito": "1"}
MONTH = "2026-01"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                # Pays both expenses at once: coffee RD$ 300 and pharmacy RD$ 500, for someone
                # else (you are owed RD$ 800), plus one too many.
                ("2026-01-12", "TRANSF DE CAROLA INVENTADA", "credit", "90000"),
                ("2026-01-13", "TOKE DE LUISA INVENTADA", "credit", "5000"),
            ],
        )
        with conn:
            rates.store_bcrd(conn, {"2026-01": Decimal("60")})
    return TestClient(create_app(path, today=lambda: date(2026, 3, 1)), "http://127.0.0.1")


def _items(client: TestClient, month: str = MONTH) -> list[dict]:
    return client.get("/api/transactions", params={"month": month}).json()["items"]


def _tx(client: TestClient, text: str) -> dict:
    return next(i for i in _items(client) if i["description"].startswith(text))


def _group(client: TestClient) -> tuple[int, dict, dict]:
    """Coffee shared "for someone else" with Carola; returns the id, the coffee and the pharmacy."""
    cafe = _tx(client, "CAFE FICTICIO")
    pharmacy = next(
        i
        for i in _items(client)
        if i["description"].startswith("FARMACIA") and i["currency"] == "DOP"
    )
    body = {"shared": {"for_other": True, "with_whom": "Carola and Rafael"}}
    made = client.patch(f"/api/transactions/{cafe['fingerprint']}", json=body, headers=WRITE)
    return made.json()["shared"]["id"], cafe, pharmacy


def test_add_a_second_expense_and_settle_both_with_one_transfer(client: TestClient) -> None:
    group, cafe, pharmacy = _group(client)
    picker = client.get(f"/api/shared/{group}/expense-candidates").json()
    assert pharmacy["fingerprint"] in [c["fingerprint"] for c in picker]
    added = client.post(
        f"/api/shared/{group}/expenses",
        json={"fingerprint": pharmacy["fingerprint"], "split": {"for_other": True}},
        headers=WRITE,
    )
    assert added.status_code == 200
    assert [e["fingerprint"] for e in added.json()["expenses"]] == [
        cafe["fingerprint"],
        pharmacy["fingerprint"],
    ]
    assert added.json()["pending"] == [{"currency": "DOP", "cents": 80000}]

    transfer = _tx(client, "TRANSF DE CAROLA")
    # "Carola" is in the description, but RD$ 900 does not fit the RD$ 800 pending (5 %).
    assert transfer["suggested_group"] is None
    linked = client.post(
        f"/api/shared/{group}/reimbursements",
        json={"credit": transfer["fingerprint"]},
        headers=WRITE,
    ).json()
    assert [e["pending_cents"] for e in linked["expenses"]] == [0, 0]
    assert linked["excess"] == [{"currency": "DOP", "cents": 10000}]
    # A US$ expense was missing (January 5): the excess warning goes away. By FIFO, the RD$ 900
    # settle the coffee (RD$ 300), then US$ 10 of the store (RD$ 600 at 60), and the pharmacy,
    # the newest, stays pending.
    store = _tx(client, "TIENDA ONLINE SEATTLE-US")
    client.post(
        f"/api/shared/{group}/expenses",
        json={"fingerprint": store["fingerprint"], "split": {"for_other": True}},
        headers=WRITE,
    )
    regrouped = client.get(f"/api/shared/{group}").json()
    assert regrouped["expense_count"] == 3
    assert regrouped["excess"] == []
    assert [(e["currency"], e["pending_cents"]) for e in regrouped["expenses"]] == [
        ("DOP", 0),
        ("USD", 2000),
        ("DOP", 50000),
    ]
    assert regrouped["pending"] == [
        {"currency": "DOP", "cents": 50000},
        {"currency": "USD", "cents": 2000},
    ]


def test_join_from_share_and_open_groups(client: TestClient) -> None:
    group, _, pharmacy = _group(client)
    [open_group] = client.get("/api/shared/open").json()
    assert (open_group["id"], open_group["title"]) == (group, "Carola and Rafael")
    # The split of the last added expense is proposed.
    assert open_group["last_split"] == {"people": None, "my_share_cents": None, "for_other": True}
    joined = client.patch(
        f"/api/transactions/{pharmacy['fingerprint']}",
        json={"shared": {"people": 2, "link_id": group}},
        headers=WRITE,
    ).json()
    assert (joined["shared"]["id"], joined["shared"]["expense_count"]) == (group, 2)
    assert joined["pending_cents"] == pharmacy["amount_cents"] // 2
    unknown = client.patch(
        f"/api/transactions/{_tx(client, 'TIENDA ONLINE')['fingerprint']}",
        json={"shared": {"people": 2, "link_id": 999}},
        headers=WRITE,
    )
    assert unknown.status_code == 404


def test_name_with_whom_and_written_off(client: TestClient) -> None:
    group, _, _ = _group(client)
    named = client.patch(
        f"/api/shared/{group}", json={"name": "Made-up Island Trip"}, headers=WRITE
    ).json()
    assert (named["title"], named["with_whom"]) == ("Made-up Island Trip", "Carola and Rafael")
    cleared = client.patch(f"/api/shared/{group}", json={"name": ""}, headers=WRITE).json()
    assert cleared["title"] == "Carola and Rafael"
    gone = client.patch(f"/api/shared/{group}", json={"written_off": True}, headers=WRITE).json()
    assert (gone["written_off"], gone["pending"]) == (True, [])
    assert client.patch("/api/shared/999", json={"name": "x"}, headers=WRITE).status_code == 404
    long = client.patch(f"/api/shared/{group}", json={"name": "x" * 81}, headers=WRITE)
    assert long.status_code == 422


def test_change_a_split_and_remove_expenses(client: TestClient) -> None:
    group, cafe, pharmacy = _group(client)
    client.post(
        f"/api/shared/{group}/expenses",
        json={"fingerprint": pharmacy["fingerprint"], "split": {"for_other": True}},
        headers=WRITE,
    )
    toke = _tx(client, "TOKE DE LUISA")
    client.post(
        f"/api/shared/{group}/reimbursements", json={"credit": toke["fingerprint"]}, headers=WRITE
    )
    resplit = client.put(
        f"/api/shared/{group}/expenses/{cafe['fingerprint']}", json={"people": 3}, headers=WRITE
    ).json()
    assert resplit["expenses"][0]["people"] == 3

    left = client.delete(f"/api/shared/{group}/expenses/{cafe['fingerprint']}", headers=WRITE)
    assert left.status_code == 200
    assert [e["fingerprint"] for e in left.json()["expenses"]] == [pharmacy["fingerprint"]]
    assert [r["fingerprint"] for r in left.json()["reimbursements"]] == [toke["fingerprint"]]
    assert _tx(client, "CAFE FICTICIO")["link"] == ""

    last = client.delete(f"/api/shared/{group}/expenses/{pharmacy['fingerprint']}", headers=WRITE)
    assert last.status_code == 204
    assert _tx(client, "TOKE DE LUISA")["link"] == ""  # the refund is free again
    assert client.get(f"/api/shared/{group}").status_code == 404


def test_pending_shows_one_row_per_group(client: TestClient) -> None:
    group, _, pharmacy = _group(client)
    client.post(
        f"/api/shared/{group}/expenses",
        json={"fingerprint": pharmacy["fingerprint"], "split": {"for_other": True}},
        headers=WRITE,
    )
    pending = client.get("/api/pending").json()
    [row] = [i for i in pending["owed_to_me"] if i["kind"] == "shared"]
    assert (row["merchant"], row["expense_count"], row["parts"]) == (
        "Carola and Rafael",
        2,
        [{"currency": "DOP", "cents": 80000}],
    )


def test_writes_need_the_header(client: TestClient) -> None:
    group, _, _ = _group(client)
    assert client.patch(f"/api/shared/{group}", json={"name": "x"}).status_code == 403
    assert client.delete(f"/api/shared/{group}/expenses/x").status_code == 403


def _share(client: TestClient, fp: str, split: dict):  # noqa: ANN202
    response = client.patch(f"/api/transactions/{fp}", json={"shared": split}, headers=WRITE)
    return response


def test_adding_a_linked_or_non_expense_is_409_or_422(client: TestClient) -> None:
    group, _, pharmacy = _group(client)
    path = f"/api/shared/{group}/expenses"
    assert _share(client, pharmacy["fingerprint"], {"people": 2}).status_code == 200
    busy = {"fingerprint": pharmacy["fingerprint"], "split": {"people": 2}}
    assert client.post(path, json=busy, headers=WRITE).status_code == 409
    toke = _tx(client, "TOKE DE LUISA")
    credit = {"fingerprint": toke["fingerprint"], "split": {"people": 2}}
    assert client.post(path, json=credit, headers=WRITE).status_code == 422
    bad_split = {"fingerprint": _tx(client, "TIENDA ONLINE")["fingerprint"], "split": {}}
    assert client.post(path, json=bad_split, headers=WRITE).status_code == 422
    assert client.post("/api/shared/999/expenses", json=busy, headers=WRITE).status_code == 404


def test_changing_a_split_of_an_unknown_group_writes_nothing(client: TestClient) -> None:
    store = _tx(client, "TIENDA ONLINE")
    unknown = client.put(
        f"/api/shared/999/expenses/{store['fingerprint']}", json={"people": 2}, headers=WRITE
    )
    assert unknown.status_code == 404
    group, _, _ = _group(client)
    elsewhere = client.put(
        f"/api/shared/{group}/expenses/{store['fingerprint']}", json={"people": 2}, headers=WRITE
    )
    assert elsewhere.status_code == 404
    assert _tx(client, "TIENDA ONLINE")["link"] == ""
    assert [g["expense_count"] for g in client.get("/api/shared/open").json()] == [1]


def test_joining_with_an_expense_of_another_group_is_409(client: TestClient) -> None:
    group, _, pharmacy = _group(client)
    assert _share(client, pharmacy["fingerprint"], {"people": 2}).status_code == 200
    moved = _share(client, pharmacy["fingerprint"], {"people": 3, "link_id": group})
    assert moved.status_code == 409
    assert _tx(client, "FARMACIA")["shared"]["expenses"][0]["people"] == 2
    # With its own group, only the split changes.
    own = _tx(client, "FARMACIA")["shared"]["id"]
    same = _share(client, pharmacy["fingerprint"], {"people": 3, "link_id": own})
    assert same.status_code == 200
    assert same.json()["shared"]["expenses"][0]["people"] == 3


def test_removing_a_refund_of_another_group_is_404(client: TestClient) -> None:
    group, _, pharmacy = _group(client)
    other = _share(client, pharmacy["fingerprint"], {"people": 2}).json()["shared"]["id"]
    toke = _tx(client, "TOKE DE LUISA")
    linked = client.post(
        f"/api/shared/{other}/reimbursements", json={"credit": toke["fingerprint"]}, headers=WRITE
    )
    assert linked.status_code == 200
    wrong = client.delete(
        f"/api/shared/{group}/reimbursements/{toke['fingerprint']}", headers=WRITE
    )
    assert wrong.status_code == 404
    assert _tx(client, "TOKE DE LUISA")["link"] == "reimbursement"
    assert client.delete(f"/api/shared/{group}/manual/12345", headers=WRITE).status_code == 404


def test_a_race_on_the_unique_index_is_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    group, _, pharmacy = _group(client)

    def racing(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.IntegrityError("UNIQUE constraint failed: link_members.fingerprint")

    monkeypatch.setattr(links, "add_expense", racing)
    body = {"fingerprint": pharmacy["fingerprint"], "split": {"people": 2}}
    response = client.post(f"/api/shared/{group}/expenses", json=body, headers=WRITE)
    assert response.status_code == 409
