"""Shared (the ledger) through the API: people and groups, expenses paid by the user or by
others, exact splits, payments with candidates and differences, unattributed payments, the
reverse flow in To review, accrual in Summary and Budget, contacts and the change log with undo
for every write. Made-up data."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db, migrations_v19
from michelito.analysis import ledger_store, rates
from michelito.web.app import create_app
from tests.test_spending import _add_bank_rows, seed

WRITE = {"X-Michelito": "1"}
MONTH = "2026-01"
ANA_SENT = "TRANSFERENCIA DE ANA FICTICIA"
LUIS_SENT = "TOKE DE LUIS INVENTADO"
TO_ROSA = "TRANSFERENCIA A ROSA FICTICIA"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-20", ANA_SENT, "credit", "150000"),
                ("2026-01-22", LUIS_SENT, "credit", "98000"),
                ("2026-01-21", TO_ROSA, "debit", "200000"),
            ],
        )
        with conn:
            rates.store_bcrd(conn, {"2025-12": Decimal("60"), "2026-01": Decimal("60")})
    return path


@pytest.fixture
def client(db_path: Path) -> TestClient:
    app = create_app(db_path, today=lambda: date(2026, 2, 1))
    return TestClient(app, "http://127.0.0.1")


def _items(client: TestClient, month: str = MONTH) -> list[dict]:
    return client.get("/api/transactions", params={"month": month}).json()["items"]


def _tx(client: TestClient, text: str, month: str = MONTH) -> dict:
    return next(i for i in _items(client, month) if i["description"].startswith(text))


def _group(client: TestClient, name: str = "Trip", people: list[dict] | None = None) -> dict:
    body = {"name": name, "people": people if people is not None else [{"name": "Ana"}]}
    made = client.post("/api/shared/groups", json=body, headers=WRITE)
    assert made.status_code == 201, made.text
    return made.json()


def _ids(group: dict) -> tuple[int, dict[str, int]]:
    me = next(m["id"] for m in group["members"] if m["is_me"])
    return me, {m["name"]: m["id"] for m in group["members"] if not m["is_me"]}


def _entry(client: TestClient, group: int, body: dict) -> dict:
    made = client.post(f"/api/shared/groups/{group}/entries", json=body, headers=WRITE)
    assert made.status_code == 201, made.text
    return made.json()


def _pay(client: TestClient, group: int, body: dict):
    return client.post(f"/api/shared/groups/{group}/payments", json=body, headers=WRITE)


def _cents(values: list[dict]) -> dict[str, int]:
    return {v["currency"]: v["cents"] for v in values}


def _member(group: dict, name: str) -> dict:
    return next(m for m in group["members"] if m["name"] == name)


class TestGroupsAndPeople:
    def test_a_group_with_people_from_contacts_bank_names_and_new_ones(
        self, client: TestClient
    ) -> None:
        contacts = client.get("/api/shared/contacts").json()
        seen = {b["raw"]: b for b in contacts["bank_names"]}
        assert seen["ANA FICTICIA"]["name"] == "Ana Ficticia"
        assert "LUIS INVENTADO" in seen
        group = _group(
            client,
            people=[{"name": "Ana Ficticia", "alias": "ANA FICTICIA"}, {"name": "Rosa"}],
        )
        assert [m["name"] for m in group["members"]] == ["me", "Ana Ficticia", "Rosa"]
        contacts = client.get("/api/shared/contacts").json()
        assert "ANA FICTICIA" not in {b["raw"] for b in contacts["bank_names"]}
        ana = next(c for c in contacts["contacts"] if c["name"] == "Ana Ficticia")
        assert ana["aliases"] == ["ANA FICTICIA"]
        # The same contact is reused by name or alias in the next group.
        again = _group(client, "Dinners", [{"name": "ana ficticia"}])
        assert _ids(again)[1] == {"Ana Ficticia": ana["id"]}
        home = client.get("/api/shared").json()
        assert {g["name"] for g in home["groups"]} == {"Trip", "Dinners"}
        assert next(p for p in home["people"] if p["name"] == "Ana Ficticia")["group_count"] == 2

    def test_the_name_is_required_and_the_user_is_always_there(self, client: TestClient) -> None:
        bad = client.post("/api/shared/groups", json={"name": "  "}, headers=WRITE)
        assert bad.status_code == 422
        group = _group(client, people=[])
        me, _ = _ids(group)
        gone = client.delete(f"/api/shared/groups/{group['id']}/members/{me}", headers=WRITE)
        assert gone.status_code == 422

    def test_rename_archive_and_empty_home_suggestions(self, client: TestClient) -> None:
        home = client.get("/api/shared").json()
        assert home["groups"] == [] and home["people"] == [] and home["totals"] == []
        # The supermarket (RD$ 2,000, a round amount) and the grocery store look shared.
        assert [s["merchant"] for s in home["suggestions"]] == [
            "SUPERMERCADO FICTICIO",
            "COLMADO INVENTADO",
        ]
        group = _group(client)
        url = f"/api/shared/groups/{group['id']}"
        assert client.patch(url, json={"name": "Beach"}, headers=WRITE).json()["name"] == "Beach"
        assert client.patch(url, json={"archived": True}, headers=WRITE).json()["archived"]
        assert client.get("/api/shared").json()["suggestions"] == []


class TestExpenses:
    def test_i_paid_it_links_the_transaction_and_counts_my_share(self, client: TestClient) -> None:
        candidates = client.get("/api/shared/expense-candidates").json()
        assert candidates[0]["merchant"] == "SUPERMERCADO FICTICIO" and candidates[0]["primary"]
        cafe = _tx(client, "CAFE FICTICIO")
        assert cafe["can_share"]
        group = _group(client, people=[{"name": "Ana"}, {"name": "Luis"}])
        me, people = _ids(group)
        body = {"fingerprint": cafe["fingerprint"], "people": [me, *people.values()]}
        found = _entry(client, group["id"], body)
        [entry] = found["timeline"]
        assert (entry["amount_cents"], entry["paid_by_me"], entry["description"]) == (
            30000,
            True,
            "CAFE FICTICIO",
        )
        assert entry["effect"] == {"kind": "lent", "cents": 20000}
        assert entry["transaction"]["fingerprint"] == cafe["fingerprint"]
        row = _tx(client, "CAFE FICTICIO")
        assert (row["link"], row["amount_cents"], row["gross_cents"], row["pending_cents"]) == (
            "shared",
            10000,
            30000,
            20000,
        )
        assert row["ledger"]["group_name"] == "Trip" and not row["can_share"]
        assert _cents(found["owed_to_me"]) == {"DOP": 20000}
        again = client.post(f"/api/shared/groups/{group['id']}/entries", json=body, headers=WRITE)
        assert again.status_code == 409

    def test_someone_else_paid_is_a_group_movement_in_summary_and_budget(
        self, client: TestClient
    ) -> None:
        before = client.get("/api/summary", params={"month": MONTH}).json()["total_cents"]
        group = _group(client, people=[{"name": "Ana"}, {"name": "Luis"}])
        me, people = _ids(group)
        body = {
            "paid_by": people["Ana"],
            "amount_cents": 500000,
            "description": "Cena en Bocao",  # spanish-data
            "day": "2026-01-12",
            "people": [me, *people.values()],
        }
        found = _entry(client, group["id"], body)
        [entry] = found["timeline"]
        # 5,000 among 3: 1,666.66 each and the leftover cents to the payer.
        assert {s["name"]: s["cents"] for s in entry["splits"]} == {
            "me": 166666,
            "Ana": 166668,
            "Luis": 166666,
        }
        assert entry["effect"] == {"kind": "owe", "cents": 166666}
        assert _cents(_member(found, "Ana")["balance"]) == {"DOP": -166666}
        row = next(i for i in _items(client) if i["link"] == "group")
        assert (row["amount_cents"], row["gross_cents"], row["account_label"]) == (
            166666,
            500000,
            "Compartidos",  # spanish-ui
        )
        assert row["ledger"]["paid_by_name"] == "Ana"
        after = client.get("/api/summary", params={"month": MONTH}).json()["total_cents"]
        assert after == before + 166666
        # Reports read the same months.
        compare = client.get("/api/reports/compare", params={"from": MONTH, "to": MONTH}).json()
        expenses = next(r for r in compare["totals"] if r["key"] == "expenses")
        assert expenses["cells"][0]["amount_cents"] == after

    def test_budget_counts_exactly_the_share(self, client: TestClient) -> None:
        assert client.post("/api/budget/activate", headers=WRITE).status_code in (200, 201)
        others = "Otros"  # spanish-data

        def spent() -> int:
            budget = client.get("/api/budget", params={"month": MONTH}).json()
            line = next((x for x in budget["lines"] if x["category"] == others), None)
            return 0 if line is None else line["spent_cents"]

        before = spent()
        group = _group(client, people=[{"name": "Ana"}])
        me, people = _ids(group)
        body = {
            "paid_by": people["Ana"],
            "amount_cents": 90000,
            "description": "Taxi",
            "day": "2026-01-12",
            "people": [me, people["Ana"]],
        }
        _entry(client, group["id"], body)
        assert spent() - before == 45000

    def test_exact_amounts_must_add_up(self, client: TestClient) -> None:
        group = _group(client)
        me, people = _ids(group)
        body = {
            "paid_by": people["Ana"],
            "amount_cents": 100000,
            "description": "Taxi",
            "split": "exact",
            "shares": [
                {"contact_id": me, "cents": 30000},
                {"contact_id": people["Ana"], "cents": 50000},
            ],
        }
        bad = client.post(f"/api/shared/groups/{group['id']}/entries", json=body, headers=WRITE)
        assert bad.status_code == 422
        body["shares"][1]["cents"] = 70000
        [entry] = _entry(client, group["id"], body)["timeline"]
        assert entry["split"] == "exact" and entry["my_share_cents"] == 30000

    def test_editing_and_deleting_an_entry(self, client: TestClient) -> None:
        group = _group(client)
        me, people = _ids(group)
        body = {
            "paid_by": me,
            "amount_cents": 90000,
            "description": "Gas",
            "people": [me, people["Ana"]],
        }
        [entry] = _entry(client, group["id"], body)["timeline"]
        body["amount_cents"] = 120000
        edited = client.put(f"/api/shared/entries/{entry['id']}", json=body, headers=WRITE).json()
        assert _cents(edited["owed_to_me"]) == {"DOP": 60000}
        gone = client.delete(f"/api/shared/entries/{entry['id']}", headers=WRITE).json()
        assert gone["timeline"] == []


class TestPayments:
    def _owed(self, client: TestClient) -> tuple[dict, int, dict[str, int]]:
        group = _group(client, people=[{"name": "Ana", "alias": "ANA FICTICIA"}, {"name": "Luis"}])
        me, people = _ids(group)
        body = {
            "paid_by": me,
            "amount_cents": 450000,
            "description": "Hotel",
            "day": "2026-01-15",
            "people": [me, *people.values()],
        }
        return _entry(client, group["id"], body), me, people

    def test_candidates_put_the_one_naming_the_person_first(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        params = {
            "contact_id": people["Ana"],
            "received": "true",
            "amount_cents": 150000,
            "day": "2026-01-18",
        }
        found = client.get("/api/shared/payment-candidates", params=params).json()
        assert [c["description"] for c in found] == [ANA_SENT]
        # Out of the tolerance (5%) or of the window (7 days): nothing.
        far = client.get(
            "/api/shared/payment-candidates", params={**params, "amount_cents": 120000}
        ).json()
        assert far == []
        later = client.get(
            "/api/shared/payment-candidates", params={**params, "day": "2026-01-01"}
        ).json()
        assert later == []
        # A payment the user made: bank debits.
        paid = client.get(
            "/api/shared/payment-candidates",
            params={**params, "received": "false", "amount_cents": 200000},
        ).json()
        assert [c["description"] for c in paid] == [TO_ROSA]

    def test_register_a_payment_linked_to_the_bank(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        credit = _tx(client, ANA_SENT)
        body = {
            "from_contact": people["Ana"],
            "to_contact": me,
            "amount_cents": 150000,
            "day": credit["day"],
            "fingerprint": credit["fingerprint"],
        }
        made = _pay(client, group["id"], body)
        assert made.status_code == 201, made.text
        found = made.json()
        assert _cents(_member(found, "Ana")["balance"]) == {}
        payment = next(i for i in found["timeline"] if i["kind"] == "payment")
        assert payment["transaction"]["fingerprint"] == credit["fingerprint"]
        assert _tx(client, ANA_SENT)["link"] == "reimbursement"
        assert _tx(client, ANA_SENT)["ledger"]["role"] == "payment"
        again = _pay(client, group["id"], body)
        assert again.status_code == 409

    def test_a_different_amount_shows_the_difference_until_accepted(
        self, client: TestClient
    ) -> None:
        group, me, people = self._owed(client)
        credit = _tx(client, LUIS_SENT)  # RD$ 980 arrived; Luis says he sent 1,000
        body = {
            "from_contact": people["Luis"],
            "to_contact": me,
            "amount_cents": 100000,
            "day": credit["day"],
            "fingerprint": credit["fingerprint"],
        }
        found = _pay(client, group["id"], body).json()
        payment = next(i for i in found["timeline"] if i["kind"] == "payment")
        assert (payment["amount_cents"], payment["sent_cents"], payment["difference_cents"]) == (
            98000,
            100000,
            2000,
        )
        assert _cents(_member(found, "Luis")["balance"]) == {"DOP": 52000}
        accepted = client.patch(
            f"/api/shared/payments/{payment['id']}", json={"accepted": True}, headers=WRITE
        ).json()
        assert _cents(_member(accepted, "Luis")["balance"]) == {"DOP": 50000}

    def test_not_yet_then_linked_from_to_review(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        body = {
            "from_contact": people["Luis"],
            "to_contact": me,
            "amount_cents": 98000,
            "day": "2026-01-21",
        }
        found = _pay(client, group["id"], body).json()
        payment = next(i for i in found["timeline"] if i["kind"] == "payment")
        assert payment["transaction"] is None
        items = client.get("/api/review", params={"month": MONTH}).json()
        proposed = next(i for i in items if i["kind"] == "possible_payment" and i["payment_id"])
        assert proposed["description"] == LUIS_SENT and proposed["payment_id"] == payment["id"]
        linked = client.patch(
            f"/api/shared/payments/{payment['id']}",
            json={"fingerprint": proposed["fingerprint"]},
            headers=WRITE,
        ).json()
        assert next(i for i in linked["timeline"] if i["kind"] == "payment")["transaction"]
        items = client.get("/api/review", params={"month": MONTH}).json()
        assert not any(i["kind"] == "possible_payment" and i["payment_id"] for i in items)

    def test_reverse_flow_a_credit_naming_someone_who_owes(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        items = client.get("/api/review", params={"month": MONTH}).json()
        proposed = next(i for i in items if i["kind"] == "possible_payment")
        assert (proposed["description"], proposed["contact_id"], proposed["group_id"]) == (
            ANA_SENT,
            people["Ana"],
            group["id"],
        )
        assert "Ana" in proposed["reason"] and proposed["amount_cents"] == 150000
        body = {
            "from_contact": proposed["contact_id"],
            "to_contact": me,
            "amount_cents": proposed["amount_cents"],
            "day": proposed["day"],
            "fingerprint": proposed["fingerprint"],
        }
        assert _pay(client, proposed["group_id"], body).status_code == 201
        items = client.get("/api/review", params={"month": MONTH}).json()
        assert proposed["fingerprint"] not in {i["fingerprint"] for i in items}
        # Luis's transfer names him too: "No" marks it reviewed.
        luis = next(i for i in items if i["kind"] == "possible_payment")
        assert luis["description"] == LUIS_SENT
        url = f"/api/review/possible_payment/{luis['fingerprint']}"
        assert client.put(url, json={"reviewed": True}, headers=WRITE).status_code == 200
        items = client.get("/api/review", params={"month": MONTH}).json()
        assert not any(i["kind"] == "possible_payment" for i in items)

    def test_an_unattributed_payment_and_its_assignment(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        body = {"to_contact": me, "amount_cents": 50000, "day": "2026-01-25"}
        found = _pay(client, group["id"], body).json()
        [loose] = found["unattributed"]
        assert loose["from_contact"] is None
        assert _cents(found["balance"]) == {"DOP": 250000}  # the group total went down
        assert _cents(_member(found, "Ana")["balance"]) == {"DOP": 150000}  # nobody's did
        assigned = client.patch(
            f"/api/shared/payments/{loose['id']}",
            json={"from_contact": people["Ana"]},
            headers=WRITE,
        ).json()
        assert assigned["unattributed"] == []
        assert _cents(_member(assigned, "Ana")["balance"]) == {"DOP": 100000}

    def test_a_payment_given_to_the_wrong_person_changes_payer(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        body = {
            "from_contact": people["Ana"],
            "to_contact": me,
            "amount_cents": 150000,
            "day": "2026-01-25",
            "allocations": [{"contact_id": people["Luis"], "cents": 150000}],
        }
        paid = _pay(client, group["id"], body).json()
        assert _cents(_member(paid, "Luis")["balance"]) == {}
        [payment] = [i for i in paid["timeline"] if i["kind"] == "payment"]
        # It was Luis who sent it: all of it becomes his, the covers start over.
        changed = client.patch(
            f"/api/shared/payments/{payment['id']}",
            json={"from_contact": people["Luis"]},
            headers=WRITE,
        ).json()
        [moved] = [i for i in changed["timeline"] if i["kind"] == "payment"]
        assert moved["from_contact"] == people["Luis"]
        assert [(a["contact_id"], a["cents"]) for a in moved["allocations"]] == [
            (people["Luis"], 150000)
        ]
        assert _cents(_member(changed, "Luis")["balance"]) == {}
        assert _cents(_member(changed, "Ana")["balance"]) == {"DOP": 150000}

    def test_a_payment_the_user_made_keeps_its_payer(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        body = {
            "from_contact": me,
            "to_contact": people["Ana"],
            "amount_cents": 1000,
            "day": "2026-01-25",
        }
        found = _pay(client, group["id"], body).json()
        [payment] = [i for i in found["timeline"] if i["kind"] == "payment"]
        response = client.patch(
            f"/api/shared/payments/{payment['id']}",
            json={"from_contact": people["Luis"]},
            headers=WRITE,
        )
        assert response.status_code == 422

    def test_paying_someone_back(self, client: TestClient) -> None:
        group = _group(client, people=[{"name": "Rosa"}])
        me, people = _ids(group)
        body = {
            "paid_by": people["Rosa"],
            "amount_cents": 400000,
            "description": "Car",
            "people": [me, people["Rosa"]],
        }
        _entry(client, group["id"], body)
        debit = _tx(client, TO_ROSA)
        payment = {
            "from_contact": me,
            "to_contact": people["Rosa"],
            "amount_cents": 200000,
            "day": debit["day"],
            "fingerprint": debit["fingerprint"],
        }
        found = _pay(client, group["id"], payment).json()
        assert _cents(_member(found, "Rosa")["balance"]) == {}
        assert _tx(client, TO_ROSA)["link"] == "reimbursement"

    def test_won_t_pay_per_person_and_for_everyone_left(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        url = f"/api/shared/groups/{group['id']}/write-off"
        one = client.post(
            url, json={"contact_id": people["Luis"], "written_off": True}, headers=WRITE
        ).json()
        assert _member(one, "Luis")["written_off"] and not _member(one, "Ana")["written_off"]
        assert _cents(one["owed_to_me"]) == {"DOP": 150000}
        everyone = client.post(url, json={"contact_id": None, "written_off": True}, headers=WRITE)
        assert everyone.json()["owed_to_me"] == []
        hotel = next(i for i in everyone.json()["timeline"] if i["kind"] == "entry")
        assert hotel["written_off_cents"] == 300000


class TestContacts:
    def test_rename_alias_and_merge(self, client: TestClient) -> None:
        group = _group(client, people=[{"name": "Ana"}, {"name": "Ana F."}])
        _, people = _ids(group)
        url = "/api/shared/contacts"
        renamed = client.patch(
            f"{url}/{people['Ana']}", json={"name": "Ana Ficticia"}, headers=WRITE
        )
        assert any(c["name"] == "Ana Ficticia" for c in renamed.json()["contacts"])
        alias = client.post(
            f"{url}/{people['Ana']}/aliases", json={"alias": "ANA FICTICIA"}, headers=WRITE
        )
        assert alias.status_code == 200
        merged = client.post(
            f"{url}/{people['Ana F.']}/merge", json={"into": people["Ana"]}, headers=WRITE
        ).json()
        ana = next(c for c in merged["contacts"] if c["id"] == people["Ana"])
        assert ana["aliases"] == ["ANA FICTICIA", "Ana F."]
        assert all(c["id"] != people["Ana F."] for c in merged["contacts"])
        group = client.get(f"/api/shared/groups/{group['id']}").json()
        assert [m["name"] for m in group["members"]] == ["me", "Ana Ficticia"]
        person = client.get(f"/api/shared/people/{people['Ana']}").json()
        assert person["group_count"] == 1
        assert client.get("/api/shared/people/999").status_code == 404

    def test_review_people_is_offered_once(self, client: TestClient) -> None:
        assert client.get("/api/shared").json()["review_people"] is False
        assert client.post("/api/shared/review-people/done", headers=WRITE).status_code == 204


def test_writes_need_the_header(client: TestClient) -> None:
    assert client.post("/api/shared/groups", json={"name": "x"}).status_code == 403


def test_every_write_is_logged_and_undone(client: TestClient) -> None:
    """Each write leaves one entry in the log; undoing it gives the group back as it was."""
    group = _group(client, people=[{"name": "Ana"}, {"name": "Luis"}])
    gid = group["id"]
    me, people = _ids(group)
    url = f"/api/shared/groups/{gid}"
    cafe = _tx(client, "CAFE FICTICIO")["fingerprint"]
    credit = _tx(client, ANA_SENT)
    steps = [
        ("post", f"{url}/members", {"name": "Rosa"}),
        ("patch", url, {"name": "Beach"}),
        ("post", f"{url}/entries", {"fingerprint": cafe, "people": [me, *people.values()]}),
        (
            "post",
            f"{url}/entries",
            {
                "paid_by": people["Ana"],
                "amount_cents": 60000,
                "description": "Taxi",
                "people": [me, people["Ana"]],
            },
        ),
        (
            "post",
            f"{url}/payments",
            {
                "from_contact": people["Ana"],
                "to_contact": me,
                "amount_cents": 150000,
                "day": credit["day"],
                "fingerprint": credit["fingerprint"],
            },
        ),
        ("post", f"{url}/payments", {"to_contact": me, "amount_cents": 1000, "day": "2026-01-25"}),
        ("post", f"{url}/write-off", {"contact_id": people["Luis"], "written_off": True}),
    ]
    for method, path, body in steps:
        before = client.get(url).json()
        done = getattr(client, method)(path, json=body, headers=WRITE)
        assert done.status_code in (200, 201), (path, done.text)
        entry = client.get("/api/log").json()["items"][0]
        assert entry["target_type"] == "link" and entry["can_undo"], (path, entry)
        assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
        assert client.get(url).json() == before, path
        assert getattr(client, method)(path, json=body, headers=WRITE).status_code in (200, 201)
    timeline = client.get(url).json()["timeline"]
    payment = next(i for i in timeline if i["kind"] == "payment" and i["from_contact"] is None)
    entry_id = next(i["id"] for i in timeline if i["kind"] == "entry")
    for method, path, body in (
        ("patch", f"/api/shared/payments/{payment['id']}", {"from_contact": people["Luis"]}),
        ("delete", f"/api/shared/payments/{payment['id']}", None),
        ("delete", f"/api/shared/entries/{entry_id}", None),
        ("patch", f"/api/shared/contacts/{people['Ana']}", {"name": "Ana Ficticia"}),
        ("post", f"/api/shared/contacts/{people['Luis']}/merge", {"into": people["Ana"]}),
    ):
        before = client.get(url).json()
        kwargs = {"headers": WRITE} if body is None else {"json": body, "headers": WRITE}
        done = getattr(client, method)(path, **kwargs)
        assert done.status_code == 200, (path, done.text)
        entry = client.get("/api/log").json()["items"][0]
        assert entry["can_undo"], (path, entry)
        assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
        assert client.get(url).json() == before, path
    # The rest: PUT of an entry, aliases, a member, a difference accepted, unlinking, a group.
    entry = next(i for i in client.get(url).json()["timeline"] if i["kind"] == "entry")
    rosa = client.post(f"{url}/members", json={"name": "Rosa"}, headers=WRITE).json()
    rosa_id = next(m["id"] for m in rosa["members"] if m["name"] == "Rosa")
    sent = {
        "from_contact": people["Ana"],
        "to_contact": me,
        "amount_cents": 15000,
        "sent_cents": 16000,
        "day": "2026-01-26",
    }
    paid = _pay(client, gid, sent).json()
    differing = next(i for i in paid["timeline"] if i.get("difference_cents"))
    linked = next(i for i in paid["timeline"] if i["kind"] == "payment" and i["transaction"])
    people_now = [s_["contact_id"] for s_ in entry["splits"]]
    for method, path, body in (
        (
            "put",
            f"/api/shared/entries/{entry['id']}",
            {"description": "Nuevo nombre", "split": "equal", "people": people_now},  # spanish-data
        ),
        ("post", f"/api/shared/contacts/{people['Ana']}/aliases", {"alias": "ANA FICTICIA"}),
        ("delete", f"{url}/members/{rosa_id}", None),
        ("patch", f"/api/shared/payments/{differing['id']}", {"accepted": True}),
        ("patch", f"/api/shared/payments/{linked['id']}", {"unlink": True}),
    ):
        before = client.get(url).json()
        kwargs = {"headers": WRITE} if body is None else {"json": body, "headers": WRITE}
        done = getattr(client, method)(path, **kwargs)
        assert done.status_code == 200, (path, done.text)
        entry_ = client.get("/api/log").json()["items"][0]
        assert entry_["can_undo"], (path, entry_)
        assert client.post(f"/api/log/{entry_['id']}/undo", headers=WRITE).status_code == 200
        assert client.get(url).json() == before, path
    alias = client.post(
        f"/api/shared/contacts/{people['Ana']}/aliases", json={"alias": "ANA F."}, headers=WRITE
    )
    assert alias.status_code == 200
    before = client.get("/api/shared/contacts").json()
    gone = client.delete(f"/api/shared/contacts/{people['Ana']}/aliases/ANA F.", headers=WRITE)
    assert gone.status_code == 200
    undo = client.get("/api/log").json()["items"][0]
    assert client.post(f"/api/log/{undo['id']}/undo", headers=WRITE).status_code == 200
    assert client.get("/api/shared/contacts").json() == before
    home = client.get("/api/shared").json()
    made = client.post("/api/shared/groups", json={"name": "Otro"}, headers=WRITE)  # spanish-data
    assert made.status_code == 201
    created = client.get("/api/log").json()["items"][0]
    assert created["kind"] == "group_new" and created["can_undo"]
    assert client.post(f"/api/log/{created['id']}/undo", headers=WRITE).status_code == 200
    assert client.get("/api/shared").json() == home


def test_both_sides_show_when_different_people_cancel(client: TestClient) -> None:
    """Ana owes the user RD$ 100 and the user owes Luis RD$ 100: nothing nets to zero."""
    group = _group(client, people=[{"name": "Ana"}, {"name": "Luis"}])
    me, people = _ids(group)
    _entry(
        client,
        group["id"],
        {"paid_by": me, "amount_cents": 20000, "description": "A", "people": [me, people["Ana"]]},
    )
    found = _entry(
        client,
        group["id"],
        {
            "paid_by": people["Luis"],
            "amount_cents": 20000,
            "description": "B",
            "people": [me, people["Luis"]],
        },
    )
    assert (_cents(found["owed_to_me"]), _cents(found["i_owe"])) == (
        {"DOP": 10000},
        {"DOP": 10000},
    )
    home = client.get("/api/shared").json()
    assert home["totals"] == [{"currency": "DOP", "owed_to_me_cents": 10000, "i_owe_cents": 10000}]
    [row] = home["groups"]
    assert (_cents(row["owed_to_me"]), _cents(row["i_owe"])) == ({"DOP": 10000}, {"DOP": 10000})
    pending = client.get("/api/pending").json()
    assert [i["link_id"] for i in pending["owed_to_me"]] == [group["id"]]
    assert [i["link_id"] for i in pending["i_owe"]] == [group["id"]]


def test_editing_the_description_keeps_the_stored_cents(client: TestClient) -> None:
    group = _group(client, people=[{"name": "Ana"}, {"name": "Luis"}])
    me, people = _ids(group)
    everyone = [me, people["Ana"], people["Luis"]]
    shares = [
        {"contact_id": me, "cents": 3333},
        {"contact_id": people["Ana"], "cents": 3334},
        {"contact_id": people["Luis"], "cents": 3333},
    ]
    body = {
        "paid_by": me,
        "amount_cents": 10000,
        "description": "Old",
        "split": "exact",
        "shares": shares,
    }
    [entry] = _entry(client, group["id"], body)["timeline"]
    edit = {
        "paid_by": me,
        "amount_cents": 10000,
        "description": "New",
        "split": "equal",
        "people": everyone,
    }
    [edited] = client.put(f"/api/shared/entries/{entry['id']}", json=edit, headers=WRITE).json()[
        "timeline"
    ]
    assert edited["description"] == "New"
    assert {s_["contact_id"]: s_["cents"] for s_ in edited["splits"]} == {
        s_["contact_id"]: s_["cents"] for s_ in shares
    }
    # A real change (another amount) does split again with the cent rule.
    edit["amount_cents"] = 30001
    [again] = client.put(f"/api/shared/entries/{entry['id']}", json=edit, headers=WRITE).json()[
        "timeline"
    ]
    assert {s_["contact_id"]: s_["cents"] for s_ in again["splits"]}[me] == 10001


def test_a_debit_categorized_as_an_expense_is_a_candidate_and_can_be_linked(
    client: TestClient,
) -> None:
    debit = _tx(client, TO_ROSA)
    food = next(c for c in client.get("/api/categories").json() if c["kind"] == "expense")
    patched = client.patch(
        f"/api/transactions/{debit['fingerprint']}", json={"category_id": food["id"]}, headers=WRITE
    )
    assert patched.json()["kind"] == "expense"
    group = _group(client, people=[{"name": "Rosa"}])
    me, people = _ids(group)
    params = {
        "contact_id": people["Rosa"],
        "received": "false",
        "amount_cents": 200000,
        "day": debit["day"],
    }
    found = client.get("/api/shared/payment-candidates", params=params).json()
    assert [c["fingerprint"] for c in found] == [debit["fingerprint"]]
    body = {
        "from_contact": me,
        "to_contact": people["Rosa"],
        "amount_cents": 200000,
        "day": debit["day"],
        "fingerprint": debit["fingerprint"],
    }
    assert _pay(client, group["id"], body).status_code == 201
    # A card purchase is not a payment: the same rule refuses it.
    cafe = _tx(client, "CAFE FICTICIO")
    body = {**body, "fingerprint": cafe["fingerprint"], "amount_cents": 30000}
    assert _pay(client, group["id"], body).status_code == 422


def test_review_people_done_is_logged_and_can_be_undone(db_path: Path, client: TestClient) -> None:
    with closing(db.connect(db_path)) as conn, conn:
        ledger_store.set_review_people(conn, True)
    assert client.get("/api/shared").json()["review_people"] is True
    assert client.post("/api/shared/review-people/done", headers=WRITE).status_code == 204
    assert client.get("/api/shared").json()["review_people"] is False
    entry = client.get("/api/log").json()["items"][0]
    assert entry["kind"] == "review_people" and entry["can_undo"]
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
    assert client.get("/api/shared").json()["review_people"] is True


def test_a_migration_mismatch_is_a_clear_message(
    db_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    with closing(sqlite3.connect(db_path)) as raw:
        raw.execute("PRAGMA user_version = 18")
        raw.commit()

    def refuse(*args: object) -> None:
        raise migrations_v19.MigrationMismatch("shared group 1 would change its balances")

    monkeypatch.setattr(migrations_v19, "migrate", refuse)
    found = client.get("/api/shared")
    assert found.status_code == 503
    assert "check_shared_migration.py" in found.json()["detail"]
    assert "versión 19" in found.json()["detail"]  # spanish-ui


def test_a_bank_debit_to_someone_can_be_a_payment_in_a_group(
    client: TestClient, db_path: Path
) -> None:
    """ "It is a payment…" from the user's side: a transfer to a third party offers it, an
    expense on a card does not, and once it is a payment in a group it is offered no more."""
    transfer = _tx(client, TO_ROSA)
    assert transfer["can_pay"] is True
    assert _tx(client, "CAFE FICTICIO")["can_pay"] is False
    assert _tx(client, ANA_SENT)["can_pay"] is False  # a credit: "It is a payment…" of its own
    # A bank debit that is an expense offers "Share" instead (cash from an ATM, say).
    with closing(db.connect(db_path)) as conn:
        _add_bank_rows(conn, [("2026-01-23", "RETIRO CAJERO FICTICIO", "debit", "50000")])
    atm = _tx(client, "RETIRO CAJERO FICTICIO")
    assert atm["kind"] == "expense" and atm["can_share"] and not atm["can_pay"]
    group = _group(client, people=[{"name": "Rosa"}])
    me, people = _ids(group)
    paid = _pay(
        client,
        group["id"],
        {
            "from_contact": me,
            "to_contact": people["Rosa"],
            "amount_cents": 200000,
            "day": transfer["day"],
            "fingerprint": transfer["fingerprint"],
        },
    )
    assert paid.status_code == 201, paid.text
    after = _tx(client, TO_ROSA)
    assert after["can_pay"] is False and after["ledger"]["role"] == "payment"
