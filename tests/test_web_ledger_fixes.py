"""Shared through the API, the fixes after the first real use: removing a person who has a share
in expenses (re-split among the rest, one undo), splits by parts, and a payment on behalf of
others (allocations in balances, people, pending and To review). Made-up data."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests import test_web_ledger as base
from tests.test_web_ledger import (
    ANA_SENT,
    LUIS_SENT,
    MONTH,
    WRITE,
    _cents,
    _entry,
    _group,
    _ids,
    _member,
    _pay,
)

# The same made-up database and client as `test_web_ledger`.
db_path = base.db_path
client = base.client


def _splits(group: dict, description: str) -> dict[str, int]:
    entry = next(i for i in group["timeline"] if i.get("description") == description)
    return {s["name"]: s["cents"] for s in entry["splits"]}


def _log(client: TestClient) -> dict:
    return client.get("/api/log").json()["items"][0]


class TestRemovePerson:
    def _group(self, client: TestClient) -> tuple[dict, int, dict[str, int]]:
        group = _group(client, people=[{"name": "Ana"}, {"name": "Luis"}, {"name": "Rosa"}])
        me, people = _ids(group)
        gid = group["id"]
        _entry(
            client,
            gid,
            {
                "paid_by": me,
                "amount_cents": 90000,
                "description": "Cena",  # spanish-data
                "day": "2026-01-10",
                "people": [me, *people.values()],
            },
        )
        _entry(
            client,
            gid,
            {
                "paid_by": me,
                "amount_cents": 120000,
                "description": "Hotel",
                "day": "2026-01-11",
                "split": "exact",
                "shares": [
                    {"contact_id": me, "cents": 30000},
                    {"contact_id": people["Ana"], "cents": 60000},
                    {"contact_id": people["Luis"], "cents": 30000},
                ],
            },
        )
        found = _entry(
            client,
            gid,
            {
                "paid_by": people["Ana"],
                "amount_cents": 40000,
                "description": "Taxi",
                "day": "2026-01-12",
                "split": "parts",
                "parts": [
                    {"contact_id": me, "parts": 1},
                    {"contact_id": people["Ana"], "parts": 2},
                    {"contact_id": people["Luis"], "parts": 1},
                ],
            },
        )
        return found, me, people

    def test_the_usage_names_the_expenses_and_the_refusal_says_why(
        self, client: TestClient
    ) -> None:
        group, _, people = self._group(client)
        url = f"/api/shared/groups/{group['id']}/members/{people['Luis']}"
        usage = client.get(f"{url}/usage").json()
        assert [u["description"] for u in usage["shares"]] == ["Cena", "Hotel", "Taxi"]
        assert usage["resplittable"] and not usage["free"]
        assert usage["paid"] == [] and usage["payments"] == []
        refused = client.delete(url, headers=WRITE)
        assert refused.status_code == 422
        detail = refused.json()["detail"]
        assert "Luis" in detail and "«Cena» (10/01/2026)" in detail
        assert "3 gasto(s)" in detail  # spanish-ui

    def test_resplit_keeps_each_mode_and_is_one_undo(self, client: TestClient) -> None:
        group, me, people = self._group(client)
        gid = group["id"]
        before = client.get(f"/api/shared/groups/{gid}").json()
        url = f"/api/shared/groups/{gid}/members/{people['Luis']}"
        done = client.delete(url, params={"resplit": "true"}, headers=WRITE)
        assert done.status_code == 200, done.text
        after = done.json()
        assert "Luis" not in {m["name"] for m in after["members"]}
        # Equal: 900 among the three left. Exact: Luis's 300 goes 1:2 to me and Ana. Parts:
        # 400 in 3 parts (me 1, Ana 2), the leftover cent to the payer (Ana).
        assert _splits(after, "Cena") == {"me": 30000, "Ana": 30000, "Rosa": 30000}
        assert _splits(after, "Hotel") == {"me": 40000, "Ana": 80000}
        assert _splits(after, "Taxi") == {"me": 13333, "Ana": 26667}
        taxi = next(i for i in after["timeline"] if i.get("description") == "Taxi")
        assert taxi["split"] == "parts"
        assert {s["name"]: s["parts"] for s in taxi["splits"]} == {"me": 1, "Ana": 2}
        entry = _log(client)
        assert entry["kind"] == "group_member_resplit" and entry["can_undo"]
        assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
        assert client.get(f"/api/shared/groups/{gid}").json() == before

    def test_someone_who_paid_or_has_payments_stays(self, client: TestClient) -> None:
        group, me, people = self._group(client)
        gid = group["id"]
        ana = client.get(f"/api/shared/groups/{gid}/members/{people['Ana']}/usage").json()
        assert [u["description"] for u in ana["paid"]] == ["Taxi"] and not ana["resplittable"]
        refused = client.delete(
            f"/api/shared/groups/{gid}/members/{people['Ana']}",
            params={"resplit": "true"},
            headers=WRITE,
        )
        assert refused.status_code == 422
        assert "pagó «Taxi»" in refused.json()["detail"]  # spanish-ui
        body = {"from_contact": people["Rosa"], "to_contact": me, "amount_cents": 1000}
        assert _pay(client, gid, {**body, "day": "2026-01-20"}).status_code == 201
        rosa = client.delete(
            f"/api/shared/groups/{gid}/members/{people['Rosa']}",
            params={"resplit": "true"},
            headers=WRITE,
        )
        assert rosa.status_code == 422
        # The payment is named by its amount and date.
        assert "un pago en el grupo: RD$ 10 el 20/01/2026" in rosa.json()["detail"]  # spanish-ui

    def test_the_usage_shows_each_expense_as_it_would_be(self, client: TestClient) -> None:
        group, me, people = self._group(client)
        gid = group["id"]
        usage = client.get(f"/api/shared/groups/{gid}/members/{people['Luis']}/usage").json()
        after = {
            u["description"]: {s["name"]: s["cents"] for s in u["after"]} for u in usage["shares"]
        }
        assert after == {
            "Cena": {"me": 30000, "Ana": 30000, "Rosa": 30000},  # spanish-data
            "Hotel": {"me": 40000, "Ana": 80000},
            "Taxi": {"me": 13333, "Ana": 26667},
        }
        assert not any(u["to_payer"] for u in usage["shares"])
        # An expense only with Rosa: without her, nobody else is left and it is all mine.
        _entry(
            client,
            gid,
            {
                "paid_by": me,
                "amount_cents": 5000,
                "description": "Regalo",  # spanish-data
                "day": "2026-01-13",
                "split": "exact",
                "shares": [{"contact_id": people["Rosa"], "cents": 5000}],
            },
        )
        rosa = client.get(f"/api/shared/groups/{gid}/members/{people['Rosa']}/usage").json()
        gift = next(u for u in rosa["shares"] if u["description"] == "Regalo")  # spanish-data
        assert gift["to_payer"] and gift["paid_by_me"]
        assert [(s["name"], s["cents"]) for s in gift["after"]] == [("me", 5000)]

    def test_someone_with_nothing_just_leaves(self, client: TestClient) -> None:
        group = _group(client, people=[{"name": "Ana"}])
        _, people = _ids(group)
        url = f"/api/shared/groups/{group['id']}/members/{people['Ana']}"
        assert client.get(f"{url}/usage").json()["free"]
        assert client.delete(url, headers=WRITE).status_code == 200


class TestParts:
    def test_parts_are_stored_shown_and_kept_when_editing(self, client: TestClient) -> None:
        group = _group(client, people=[{"name": "Javier"}, {"name": "Gordo"}])
        me, people = _ids(group)
        found = _entry(
            client,
            group["id"],
            {
                "paid_by": me,
                "amount_cents": 489600,
                "description": "Entradas",  # spanish-data
                "day": "2026-01-10",
                "split": "parts",
                "parts": [
                    {"contact_id": me, "parts": 1},
                    {"contact_id": people["Javier"], "parts": 2},
                    {"contact_id": people["Gordo"], "parts": 3},
                ],
            },
        )
        [entry] = found["timeline"]
        assert entry["split"] == "parts"
        assert {s["name"]: (s["cents"], s["parts"]) for s in entry["splits"]} == {
            "me": (81600, 1),
            "Javier": (163200, 2),
            "Gordo": (244800, 3),
        }
        assert _cents(_member(found, "Javier")["balance"]) == {"DOP": 163200}
        edited = client.put(
            f"/api/shared/entries/{entry['id']}",
            json={
                "description": "Entradas MLB",  # spanish-data
                "split": "parts",
                "parts": [{"contact_id": c, "parts": 2} for c in (me, *people.values())],
            },
            headers=WRITE,
        ).json()
        [entry] = edited["timeline"]
        assert entry["split"] == "parts" and entry["amount_cents"] == 489600
        assert {s["name"]: s["cents"] for s in entry["splits"]} == {
            "me": 163200,
            "Javier": 163200,
            "Gordo": 163200,
        }

    def test_parts_must_be_at_least_one(self, client: TestClient) -> None:
        group = _group(client)
        me, people = _ids(group)
        body = {
            "paid_by": me,
            "amount_cents": 1000,
            "description": "x",
            "split": "parts",
            "parts": [{"contact_id": me, "parts": 0}],
        }
        made = client.post(f"/api/shared/groups/{group['id']}/entries", json=body, headers=WRITE)
        assert made.status_code == 422
        empty = client.post(
            f"/api/shared/groups/{group['id']}/entries",
            json={**body, "parts": []},
            headers=WRITE,
        )
        assert empty.status_code == 422


class TestPaidForOthers:
    def _owed(self, client: TestClient) -> tuple[dict, int, dict[str, int]]:
        group = _group(
            client,
            people=[
                {"name": "Ana", "alias": "ANA FICTICIA"},
                {"name": "Luis", "alias": "LUIS INVENTADO"},
            ],
        )
        me, people = _ids(group)
        body = {
            "paid_by": me,
            "amount_cents": 450000,
            "description": "Hotel",
            "day": "2026-01-15",
            "people": [me, *people.values()],
        }
        return _entry(client, group["id"], body), me, people

    def test_one_payment_settles_several_people(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        body = {
            "from_contact": people["Ana"],
            "to_contact": me,
            "amount_cents": 300000,
            "day": "2026-01-19",
            "allocations": [
                {"contact_id": people["Ana"], "cents": 150000},
                {"contact_id": people["Luis"], "cents": 150000},
            ],
        }
        found = _pay(client, group["id"], body)
        assert found.status_code == 201, found.text
        paid = found.json()
        assert _member(paid, "Ana")["balance"] == [] and _member(paid, "Luis")["balance"] == []
        payment = next(i for i in paid["timeline"] if i["kind"] == "payment")
        assert [(a["name"], a["cents"]) for a in payment["allocations"]] == [
            ("Ana", 150000),
            ("Luis", 150000),
        ]
        home = client.get("/api/shared").json()
        assert home["totals"] == []
        assert all(p["balance"] == [] for p in home["people"])
        pending = client.get("/api/pending").json()
        assert not any(g.get("group_id") == group["id"] for g in pending.get("owed", []))
        # Luis's own transfer is no longer proposed as his payment in To review.
        items = client.get("/api/review", params={"month": MONTH}).json()
        assert not any(i["kind"] == "possible_payment" for i in items)
        entry = _log(client)
        assert entry["can_undo"]
        assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
        assert client.get(f"/api/shared/groups/{group['id']}").json() == group

    def test_without_allocations_the_others_still_owe(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        body = {"from_contact": people["Ana"], "to_contact": me, "amount_cents": 150000}
        paid = _pay(client, group["id"], {**body, "day": "2026-01-19"}).json()
        assert _cents(_member(paid, "Luis")["balance"]) == {"DOP": 150000}
        items = client.get("/api/review", params={"month": MONTH}).json()
        proposed = [i for i in items if i["kind"] == "possible_payment"]
        assert LUIS_SENT in {i["description"] for i in proposed}

    def test_allocations_must_add_up_and_be_group_people(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        body = {
            "from_contact": people["Ana"],
            "to_contact": me,
            "amount_cents": 300000,
            "day": "2026-01-19",
        }
        short = [
            {"contact_id": people["Ana"], "cents": 150000},
            {"contact_id": people["Luis"], "cents": 100000},
        ]
        assert _pay(client, group["id"], {**body, "allocations": short}).status_code == 422
        mine = [{"contact_id": me, "cents": 300000}]
        assert _pay(client, group["id"], {**body, "allocations": mine}).status_code == 422
        stranger = client.post("/api/shared/contacts", json={"name": "Rosa"}, headers=WRITE)
        outside = [{"contact_id": stranger.json()["id"], "cents": 300000}]
        assert _pay(client, group["id"], {**body, "allocations": outside}).status_code == 422
        mine_paid = {
            "from_contact": me,
            "to_contact": people["Ana"],
            "amount_cents": 1000,
            "day": "2026-01-19",
            "allocations": [{"contact_id": people["Luis"], "cents": 1000}],
        }
        assert _pay(client, group["id"], mine_paid).status_code == 422

    def test_linked_to_the_bank_the_payer_takes_the_difference(self, client: TestClient) -> None:
        group, me, people = self._owed(client)
        credit = next(
            i
            for i in client.get("/api/transactions", params={"month": MONTH}).json()["items"]
            if i["description"].startswith(ANA_SENT)
        )
        body = {
            "from_contact": people["Ana"],
            "to_contact": me,
            "amount_cents": 155000,
            "day": credit["day"],
            "fingerprint": credit["fingerprint"],
            "allocations": [
                {"contact_id": people["Ana"], "cents": 5000},
                {"contact_id": people["Luis"], "cents": 150000},
            ],
        }
        found = _pay(client, group["id"], body)
        assert found.status_code == 201, found.text
        paid = found.json()
        # The bank brought 1,500 (not 1,550): Ana's own allocation takes the 50 less.
        payment = next(i for i in paid["timeline"] if i["kind"] == "payment")
        assert [(a["name"], a["cents"]) for a in payment["allocations"]] == [("Luis", 150000)]
        assert _member(paid, "Luis")["balance"] == []
        assert _cents(_member(paid, "Ana")["balance"]) == {"DOP": 150000}

    def test_less_in_the_bank_with_the_payer_at_zero_comes_off_the_others(
        self, client: TestClient
    ) -> None:
        """Ana pays only for Luis and typed RD$ 1,550; the bank brought RD$ 1,500. The same rule
        as the ledger's (`fit_allocations`): nothing to take off Ana, so Luis's part is 1,500."""
        group, me, people = self._owed(client)
        credit = next(
            i
            for i in client.get("/api/transactions", params={"month": MONTH}).json()["items"]
            if i["description"].startswith(ANA_SENT)
        )
        body = {
            "from_contact": people["Ana"],
            "to_contact": me,
            "amount_cents": 155000,
            "day": credit["day"],
            "fingerprint": credit["fingerprint"],
            "allocations": [{"contact_id": people["Luis"], "cents": 155000}],
        }
        found = _pay(client, group["id"], body)
        assert found.status_code == 201, found.text
        payment = next(i for i in found.json()["timeline"] if i["kind"] == "payment")
        assert [(a["name"], a["cents"]) for a in payment["allocations"]] == [("Luis", 150000)]
        assert _member(found.json(), "Luis")["balance"] == []
