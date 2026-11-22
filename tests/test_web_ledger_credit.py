"""A new shared group from a credit through the API (`web.ledger_credit_routes`): the plan
(who paid, the expense it pays back, other credits), creating the group with its expenses and
payments in one change, the two ways to split, the change log with undo, and the refusals.
Made-up data."""

from __future__ import annotations

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import rates
from michelito.web.app import create_app
from tests.test_spending import _add_bank_rows, seed

WRITE = {"X-Michelito": "1"}
ROSA_SENT = "TOKE DE ROSA FICTICIA"
ANA_SENT = "TRANSFERENCIA DE ANA FICTICIA"
SUPERMARKET = "SUPERMERCADO FICTICIO"  # RD$ 2,000 on 2025-12-28 (synthetic seed)
ONLINE_USD = "TIENDA ONLINE SEATTLE-US"  # US$ 30
URL = "/api/shared/groups/from-credit"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-20", ROSA_SENT, "credit", "100000"),
                ("2026-01-22", ANA_SENT, "credit", "50000"),
            ],
        )
    app = create_app(path, today=lambda: date(2026, 2, 1))
    return TestClient(app, "http://127.0.0.1")


def _fp(client: TestClient, text: str) -> str:
    for month in ("2025-12", "2026-01"):
        items = client.get("/api/transactions", params={"month": month}).json()["items"]
        found = next((i for i in items if i["description"].startswith(text)), None)
        if found is not None:
            return found["fingerprint"]
    raise AssertionError(text)


def _cents(values: list[dict]) -> dict[str, int]:
    return {v["currency"]: v["cents"] for v in values}


def _member(group: dict, name: str) -> dict:
    return next(m for m in group["members"] if m["name"] == name)


def _body(client: TestClient, **changes: object) -> dict:
    body: dict = {
        "name": "Supermarket run",
        "payments": [
            {
                "fingerprint": _fp(client, ROSA_SENT),
                "person": {"name": "Rosa Ficticia", "alias": "ROSA FICTICIA"},
            }
        ],
        "expenses": [{"fingerprint": _fp(client, SUPERMARKET)}],
    }
    return {**body, **changes}


def test_the_plan_guesses_the_person_the_expense_and_the_other_credits(
    client: TestClient,
) -> None:
    plan = client.get("/api/shared/credit-plan", params={"fingerprint": _fp(client, ROSA_SENT)})
    assert plan.status_code == 200, plan.text
    found = plan.json()
    assert found["person"] == {
        "contact_id": None,
        "name": "Rosa Ficticia",
        "alias": "ROSA FICTICIA",
    }
    first = found["expenses"][0]
    assert first["merchant"].startswith(SUPERMARKET) and first["fits"]
    assert all(not e["fits"] for e in found["expenses"][1:])
    others = [c["tx"]["description"] for c in found["credits"]]
    assert others[0] == ANA_SENT
    assert found["credits"][0]["person"]["name"] == "Ana Ficticia"


def test_the_plan_refuses_a_credit_that_cannot_be_a_payment(client: TestClient) -> None:
    interest = _fp(client, "PAGO INTERESES CA")
    assert (
        client.get("/api/shared/credit-plan", params={"fingerprint": interest}).status_code == 422
    )
    missing = client.get("/api/shared/credit-plan", params={"fingerprint": "nope"})
    assert missing.status_code == 404


def test_their_share_is_what_they_paid_and_the_group_is_settled(client: TestClient) -> None:
    made = client.post(URL, json=_body(client), headers=WRITE)
    assert made.status_code == 201, made.text
    group = made.json()
    assert group["name"] == "Supermarket run"
    assert [m["name"] for m in group["members"]] == ["me", "Rosa Ficticia"]
    assert _cents(_member(group, "Rosa Ficticia")["balance"]) == {}
    entry = next(i for i in group["timeline"] if i["kind"] == "entry")
    assert entry["split"] == "exact"
    assert {s["name"]: s["cents"] for s in entry["splits"]} == {
        "me": 100000,
        "Rosa Ficticia": 100000,
    }
    # Both transactions now point at the group; the bank's name is Rosa's alias.
    contacts = client.get("/api/shared/contacts").json()
    rosa = next(c for c in contacts["contacts"] if c["name"] == "Rosa Ficticia")
    assert rosa["aliases"] == ["ROSA FICTICIA"]
    plan = client.get("/api/shared/credit-plan", params={"fingerprint": _fp(client, ANA_SENT)})
    assert SUPERMARKET not in {e["merchant"] for e in plan.json()["expenses"]}


def test_equal_split_with_another_credit_and_a_cash_expense(client: TestClient) -> None:
    body = _body(
        client,
        split="equal",
        payments=[
            *_body(client)["payments"],
            {"fingerprint": _fp(client, ANA_SENT), "person": {"name": "Ana Ficticia"}},
        ],
        expenses=[
            {"fingerprint": _fp(client, SUPERMARKET)},
            {"amount_cents": 90000, "description": "Taxi", "day": "2026-01-18"},
        ],
    )
    made = client.post(URL, json=body, headers=WRITE)
    assert made.status_code == 201, made.text
    group = made.json()
    # RD$ 2,900 among three (RD$ 966.66 or .67 each, the cent rule). Rosa paid 1,000, Ana 500.
    rosa = _cents(_member(group, "Rosa Ficticia")["balance"])["DOP"]
    ana = _cents(_member(group, "Ana Ficticia")["balance"])["DOP"]
    assert rosa in (-3333, -3334) and ana in (46666, 46667)
    theirs = sum(
        s["cents"]
        for i in group["timeline"]
        if i["kind"] == "entry"
        for s in i["splits"]
        if not s["is_me"]
    )
    assert rosa + ana == theirs - 150000
    kinds = sorted(i["kind"] for i in group["timeline"])
    assert kinds == ["entry", "entry", "payment", "payment"]


def test_equal_parts_may_mix_currencies_like_any_group(client: TestClient, tmp_path: Path) -> None:
    """A RD$ credit for a US$ purchase: "what they paid" is refused (one currency), equal parts
    is not: like any payment in the other currency, it settles at the month's rate."""
    with closing(db.connect(tmp_path / "michelito.db")) as conn, conn:
        rates.store_bcrd(conn, {"2025-12": Decimal("60"), "2026-01": Decimal("60")})
    body = _body(client, split="equal", expenses=[{"fingerprint": _fp(client, ONLINE_USD)}])
    made = client.post(URL, json=body, headers=WRITE)
    assert made.status_code == 201, made.text
    rosa = _cents(_member(made.json(), "Rosa Ficticia")["balance"])
    # Her half, US$ 15, is RD$ 900; she sent RD$ 1,000, so the user owes her RD$ 100.
    assert rosa == {"DOP": -10000}


def test_one_change_in_the_log_and_one_undo_takes_all_of_it_back(client: TestClient) -> None:
    before = client.get("/api/shared").json()
    made = client.post(URL, json=_body(client), headers=WRITE)
    assert made.status_code == 201, made.text
    entry = client.get("/api/log").json()["items"][0]
    assert entry["target_type"] == "link" and entry["can_undo"]
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
    after = client.get("/api/shared").json()
    assert after["groups"] == before["groups"] == []
    again = client.post(URL, json=_body(client), headers=WRITE)
    assert again.status_code == 201, again.text


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        # They paid RD$ 1,000 for a US$ 30 purchase: "what they paid" needs one currency.
        ("usd", 422),
        ("over", 422),
        ("repeated", 422),
        ("no_expense", 422),
        ("cash_without_text", 422),
    ],
)
def test_refusals_leave_nothing_behind(client: TestClient, changes: str, status: int) -> None:
    supermarket = _fp(client, SUPERMARKET)
    rosa = _fp(client, ROSA_SENT)
    bodies = {
        "usd": _body(client, expenses=[{"fingerprint": _fp(client, ONLINE_USD)}]),
        "over": _body(client, expenses=[{"amount_cents": 50000, "description": "Taxi"}]),
        "repeated": _body(
            client, expenses=[{"fingerprint": supermarket}, {"fingerprint": supermarket}]
        ),
        "no_expense": _body(client, expenses=[]),
        "cash_without_text": _body(client, expenses=[{"amount_cents": 50000}]),
    }
    done = client.post(URL, json=bodies[changes], headers=WRITE)
    assert done.status_code == status, done.text
    assert client.get("/api/shared").json()["groups"] == []
    plan = client.get("/api/shared/credit-plan", params={"fingerprint": rosa})
    assert plan.status_code == 200


def test_writes_need_the_header(client: TestClient) -> None:
    assert client.post(URL, json=_body(client)).status_code in (401, 403)
