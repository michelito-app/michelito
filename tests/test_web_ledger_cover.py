"""Shared through the API: one person paying for several, in another currency. The synthetic
case of `tests.ledger_cover_case` built with the routes: the suggestion (group and To review),
the proposed allocations, replacing a payment's allocations as one change with undo and redo,
"No" kept and undoable, the exchange leftover and its toggle, the "in total ≈" line and the rate
of a converted payment. Made-up data."""

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
from tests import ledger_cover_case as case
from tests.test_spending import seed
from tests.test_web_ledger import WRITE, _cents, _entry, _group, _ids, _member, _pay

FEBRUARY = "2026-02"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        with conn:
            every = {**case.RATES, **case.SPREAD_RATES}
            rates.store_bcrd(conn, {m: r.value for m, r in every.items()})
    app = create_app(path, today=lambda: date(2026, 2, 20))
    return TestClient(app, "http://127.0.0.1")


def _cover_case(client: TestClient) -> tuple[int, int, int, int, int]:
    """(group, me, Ana, Beto, Ana's last payment) with the case's expenses and payments."""
    group = _group(client, people=[{"name": "Ana Ficticia"}, {"name": "Beto Inventado"}])
    me, people = _ids(group)
    ana, beto = people["Ana Ficticia"], people["Beto Inventado"]
    for amount, day in ((case.HOTEL, "2025-12-05"), (case.FLIGHTS, "2025-12-10")):
        _entry(
            client,
            group["id"],
            {
                "paid_by": me,
                "amount_cents": int(amount * 100),
                "currency": "USD",
                "description": "Hotel",
                "day": day,
                "people": [me, ana, beto],
            },
        )
    ids = {case.ANA: ana, case.BETO: beto}
    for _, who, amount, day in case.PAYMENTS:
        made = _pay(
            client,
            group["id"],
            {
                "from_contact": ids[who],
                "to_contact": me,
                "amount_cents": int(amount * 100),
                "currency": "DOP",
                "day": day.isoformat(),
            },
        )
        assert made.status_code == 201, made.text
    last = _payments(made.json())[0]
    return group["id"], me, ana, beto, last["id"]


def _payments(group: dict) -> list[dict]:
    return [i for i in group["timeline"] if i["kind"] == "payment"]


def _get(client: TestClient, group: int) -> dict:
    return client.get(f"/api/shared/groups/{group}").json()


def _last_log(client: TestClient) -> dict:
    return client.get("/api/log").json()["items"][0]


def _proposal(client: TestClient, group: int, payer: int, covers: list[int], **extra) -> dict:
    params = {
        "from_contact": payer,
        "amount_cents": 4082000,
        "currency": "DOP",
        "day": "2026-02-10",
        "covers": ",".join(str(c) for c in covers),
        **extra,
    }
    found = client.get(f"/api/shared/groups/{group}/allocation-proposal", params=params)
    assert found.status_code == 200, found.text
    return found.json()


def _put(client: TestClient, payment: int, parts: dict[int, int]):
    body = {"allocations": [{"contact_id": c, "cents": v} for c, v in parts.items()]}
    return client.put(f"/api/shared/payments/{payment}/allocations", json=body, headers=WRITE)


def test_the_case_shows_the_suggestion_the_total_line_and_the_rate(client: TestClient) -> None:
    group_id, _, ana, beto, last = _cover_case(client)
    group = _get(client, group_id)
    assert _cents(group["owed_to_me"]) == {"USD": 62931}
    assert _cents(group["i_owe"]) == {"DOP": 4010783}
    assert group["total"] == {"currency": "DOP", "cents": -2078}
    assert _member(group, "Beto Inventado")["total"] is None  # one currency
    cover = group["cover"]
    assert (cover["payment_id"], cover["payer_id"], cover["covers"]) == (last, ana, [beto])
    assert cover["text"] == (
        "Ana Ficticia pagó RD$ 40,108 de más y Beto Inventado debe US$ 629.31. "  # spanish-data
        "¿Ese pago también era por Beto Inventado?"  # spanish-data
    )
    # Every payment settled US$ claims: its detail says at which rate.
    rates_used = {p["id"]: p["rate"] for p in _payments(group)}
    assert rates_used[last] == {"value": "63.7000", "month": "2026-02"}
    review = client.get("/api/review", params={"month": FEBRUARY}).json()
    item = next(i for i in review if i["kind"] == "possible_cover")
    assert (item["group_id"], item["payment_id"], item["contact_id"]) == (group_id, last, ana)
    assert item["fingerprint"] == f"ledger-payment-{last}"
    assert item["reason"] == cover["text"]
    home = client.get("/api/shared").json()
    assert next(g for g in home["groups"] if g["id"] == group_id)["total"] == group["total"]


def test_the_proposal_is_payer_first_with_the_conversion(client: TestClient) -> None:
    group_id, _, ana, beto, last = _cover_case(client)
    found = _proposal(client, group_id, ana, [beto], payment_id=last)
    assert found["rate"] == {"value": "63.7000", "month": "2026-02"}
    parts = {a["contact_id"]: a for a in found["allocations"]}
    assert [a["contact_id"] for a in found["allocations"]] == [ana, beto]
    assert parts[ana]["cents"] == 73295 and parts[ana]["owed_cents"] == 71217
    assert parts[beto]["cents"] == 4008705
    assert parts[beto]["equivalent"] == {"currency": "USD", "cents": 62931}
    unknown = client.get(
        f"/api/shared/groups/{group_id}/allocation-proposal",
        params={"from_contact": ana, "amount_cents": 1, "day": "2026-02-10", "payment_id": 999},
    )
    assert unknown.status_code == 404


def test_also_paid_for_is_one_change_with_undo_and_redo(client: TestClient) -> None:
    group_id, _, ana, beto, last = _cover_case(client)
    saved = _put(client, last, {ana: 73295, beto: 4008705})
    assert saved.status_code == 200, saved.text
    group = saved.json()
    ana_row, beto_row = _member(group, "Ana Ficticia"), _member(group, "Beto Inventado")
    assert ana_row["balance"] == [] and _cents(ana_row["leftover"]) == {"DOP": -2078}
    assert beto_row["balance"] == [] and beto_row["leftover"] == []
    assert group["owed_to_me"] == [] and group["i_owe"] == [] and group["cover"] is None
    payment = next(p for p in _payments(group) if p["id"] == last)
    assert [(a["contact_id"], a["cents"]) for a in payment["allocations"]] == [
        (ana, 73295),
        (beto, 4008705),
    ]
    entry = _last_log(client)
    assert entry["kind"] == "group_payment" and entry["can_undo"]
    assert "también a Beto Inventado" in entry["summary"]  # spanish-data
    undone = client.post(f"/api/log/{entry['id']}/undo", headers=WRITE)
    assert undone.status_code == 200, undone.text
    back = _get(client, group_id)
    assert _cents(back["owed_to_me"]) == {"USD": 62931} and back["cover"] is not None
    assert len(next(p for p in _payments(back) if p["id"] == last)["allocations"]) == 1
    redone = client.post(f"/api/log/{entry['id']}/redo", headers=WRITE)
    assert redone.status_code == 200, redone.text
    assert _get(client, group_id)["owed_to_me"] == []


def test_removing_every_covered_person_gives_it_back_to_the_payer(client: TestClient) -> None:
    group_id, _, ana, beto, last = _cover_case(client)
    assert _put(client, last, {ana: 73295, beto: 4008705}).status_code == 200
    group = _put(client, last, {}).json()
    payment = next(p for p in _payments(group) if p["id"] == last)
    assert [(a["contact_id"], a["cents"]) for a in payment["allocations"]] == [(ana, 4082000)]
    assert "Quitaste a Beto Inventado" in _last_log(client)["summary"]  # spanish-data
    assert group["cover"] is not None


def test_allocations_must_add_up_and_only_for_payments_to_me(client: TestClient) -> None:
    group_id, me, ana, beto, last = _cover_case(client)
    assert _put(client, last, {ana: 100, beto: 200}).status_code == 422
    assert _put(client, last, {me: 4082000}).status_code == 422
    paid = _pay(
        client,
        group_id,
        {"from_contact": me, "to_contact": ana, "amount_cents": 100, "day": "2026-02-11"},
    ).json()
    mine = next(p for p in _payments(paid) if p["from_me"])
    assert _put(client, mine["id"], {ana: 100}).status_code == 422
    assert _put(client, 9999, {ana: 100}).status_code == 404


def test_no_is_kept_and_can_be_undone(client: TestClient) -> None:
    group_id, *_, last = _cover_case(client)
    url = f"/api/shared/payments/{last}/cover-dismissed"
    group = client.put(url, json={"dismissed": True}, headers=WRITE).json()
    assert group["cover"] is None
    review = client.get("/api/review", params={"month": FEBRUARY}).json()
    assert all(i["kind"] != "possible_cover" for i in review)
    entry = _last_log(client)
    summary = entry["summary"]  # spanish-data (below)
    assert entry["kind"] == "group_payment"
    assert "no era por nadie más" in summary  # spanish-data
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
    assert _get(client, group_id)["cover"]["payment_id"] == last


def test_the_exchange_leftover_toggle_is_logged_and_undoable(client: TestClient) -> None:
    group_id, _, ana, beto, last = _cover_case(client)
    _put(client, last, {ana: 73295, beto: 4008705})
    url = f"/api/shared/groups/{group_id}/exchange-leftover"
    off = client.post(url, json={"contact_id": ana, "settled": False}, headers=WRITE).json()
    row = _member(off, "Ana Ficticia")
    assert _cents(row["balance"]) == {"DOP": -2078} and row["leftover"] == []
    assert not row["leftover_settled"] and _cents(off["i_owe"]) == {"DOP": 2078}
    entry = _last_log(client)
    assert entry["kind"] == "group_member" and "vuelven a contar" in entry["summary"]
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
    back = _member(_get(client, group_id), "Ana Ficticia")
    assert back["leftover_settled"] and back["balance"] == []
    person = client.get(f"/api/shared/people/{ana}").json()
    assert person["balance"] == []
    assert _cents(next(g for g in person["groups"] if g["group_id"] == group_id)["leftover"]) == {
        "DOP": -2078
    }


def test_a_new_payment_proposal_uses_every_payment_until_that_day(client: TestClient) -> None:
    group_id, _, ana, beto, _ = _cover_case(client)
    found = _proposal(client, group_id, beto, [], day="2026-02-12", currency="USD")
    assert found["rate"] is None
    assert [(a["contact_id"], a["cents"]) for a in found["allocations"]] == [(beto, 4082000)]
    assert found["allocations"][0]["owed_cents"] == 62931
    assert Decimal(found["allocations"][0]["owed_cents"]) / 100 == Decimal("629.31")
    assert ana  # Ana is not part of it


def test_the_same_person_twice_is_refused(client: TestClient) -> None:
    group_id, me, ana, beto, last = _cover_case(client)
    # The last one would win silently (and add up): it must be refused instead.
    body = {"allocations": [{"contact_id": ana, "cents": 0}, {"contact_id": ana, "cents": 4082000}]}
    url = f"/api/shared/payments/{last}/allocations"
    assert client.put(url, json=body, headers=WRITE).status_code == 422
    twice = _pay(
        client,
        group_id,
        {
            "from_contact": ana,
            "to_contact": me,
            "amount_cents": 200,
            "day": "2026-02-11",
            "allocations": [
                {"contact_id": beto, "cents": 200},
                {"contact_id": beto, "cents": 0},
            ],
        },
    )
    assert twice.status_code == 422


def test_an_accepted_difference_edits_what_it_settles(client: TestClient) -> None:
    """Received RD$ 1,000, sent RD$ 1,100 and the difference accepted: it settles RD$ 1,100, so
    its detail shows and edits allocations adding up to that."""
    group_id, me, ana, beto, _ = _cover_case(client)
    made = _pay(
        client,
        group_id,
        {
            "from_contact": ana,
            "to_contact": me,
            "amount_cents": 100000,
            "sent_cents": 110000,
            "day": "2026-02-11",
        },
    ).json()
    payment = next(p for p in _payments(made) if p["sent_cents"] == 110000)
    url = f"/api/shared/payments/{payment['id']}"
    group = client.patch(url, json={"accepted": True}, headers=WRITE).json()
    payment = next(p for p in _payments(group) if p["id"] == payment["id"])
    assert payment["settles_cents"] == 110000
    assert sum(a["cents"] for a in payment["allocations"]) == 110000
    assert _put(client, payment["id"], {ana: 10000, beto: 100000}).status_code == 200
    assert _put(client, payment["id"], {ana: 1, beto: 99999}).status_code == 422


def test_undoing_a_deleted_payment_brings_its_no_back(client: TestClient) -> None:
    group_id, *_, last = _cover_case(client)
    url = f"/api/shared/payments/{last}"
    client.put(f"{url}/cover-dismissed", json={"dismissed": True}, headers=WRITE)
    assert client.delete(url, headers=WRITE).status_code == 200
    entry = _last_log(client)
    assert entry["kind"] == "group_payment_delete"
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
    group = _get(client, group_id)
    assert any(p["id"] == last for p in _payments(group))
    assert group["cover"] is None  # still answered "No"


def _spread_case(client: TestClient) -> tuple[int, int, int, list[int]]:
    """(group, Ana, Beto, Ana's three payments) of `ledger_cover_case.spread_group`."""
    group = _group(client, "Viaje largo", [{"name": "Ana Ficticia"}, {"name": "Beto Inventado"}])
    me, people = _ids(group)
    ana, beto = people["Ana Ficticia"], people["Beto Inventado"]
    for _, amount, day in case.SPREAD_EXPENSES:
        _entry(
            client,
            group["id"],
            {
                "paid_by": me,
                "amount_cents": int(amount * 100),
                "currency": "USD",
                "description": "Hotel",
                "day": day.isoformat(),
                "people": [me, ana, beto],
            },
        )
    ids = {case.ANA: ana, case.BETO: beto}
    for _, who, amount, day in case.SPREAD_PAYMENTS:
        made = _pay(
            client,
            group["id"],
            {
                "from_contact": ids[who],
                "to_contact": me,
                "amount_cents": int(amount * 100),
                "currency": "DOP",
                "day": day.isoformat(),
            },
        )
        assert made.status_code == 201, made.text
    hers = sorted(
        (p for p in _payments(made.json()) if p["from_contact"] == ana),
        key=lambda p: (p["day"], p["id"]),
    )
    return group["id"], ana, beto, [p["id"] for p in hers]


def test_several_payments_are_one_suggestion_and_one_change(client: TestClient) -> None:
    group_id, ana, beto, hers = _spread_case(client)
    group = _get(client, group_id)
    cover = group["cover"]
    assert cover["payment_ids"] == hers and cover["covers"] == [beto]
    excess = _cents(group["i_owe"])["DOP"]
    assert cover["excess_cents"] == excess
    whole = f"{round(excess / 100):,}"
    assert cover["text"] == (
        f"Ana Ficticia pagó RD$ {whole} de más en 3 pagos "  # spanish-data
        "y Beto Inventado debe US$ 990.76. "  # spanish-data
        "¿Esos pagos también eran por Beto Inventado?"  # spanish-data
    )
    review = client.get("/api/review", params={"month": "2025-10"}).json()
    item = next(i for i in review if i["kind"] == "possible_cover")
    assert item["payment_ids"] == hers and item["payment_id"] == hers[0]

    plan = client.get(f"/api/shared/groups/{group_id}/cover-proposal")
    assert plan.status_code == 200, plan.text
    found = plan.json()
    assert [p["payment_id"] for p in found["payments"]] == hers
    first = {a["contact_id"]: a["cents"] for a in found["payments"][0]["allocations"]}
    assert first[ana] + first[beto] == 9800000
    after = {m["contact_id"]: m for m in found["after"]}
    assert after[ana]["balance"] == []
    left = _cents(after[beto]["balance"])["USD"]
    assert 6200 < left < 6400

    body = {
        "payments": [
            {
                "payment_id": p["payment_id"],
                "allocations": [
                    {"contact_id": a["contact_id"], "cents": a["cents"]} for a in p["allocations"]
                ],
            }
            for p in found["payments"]
        ]
    }
    before = _last_log(client)["id"]
    done = client.put(f"/api/shared/groups/{group_id}/cover", json=body, headers=WRITE)
    assert done.status_code == 200, done.text
    applied = done.json()
    assert applied["i_owe"] == [] and _cents(applied["owed_to_me"]) == {"USD": left}
    assert applied["cover"] is None
    entry = _last_log(client)
    assert entry["kind"] == "group_payment" and "3 pagos" in entry["summary"]  # spanish-data
    newer = [e for e in client.get("/api/log").json()["items"] if e["id"] > before]
    assert [e["id"] for e in newer] == [entry["id"]]  # the three payments in one change
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
    assert _get(client, group_id)["cover"]["payment_ids"] == hers
    assert client.post(f"/api/log/{entry['id']}/redo", headers=WRITE).status_code == 200
    assert _get(client, group_id)["i_owe"] == []


def test_a_cover_with_a_payment_of_another_group_is_refused(client: TestClient) -> None:
    group_id, ana, beto, hers = _spread_case(client)
    other, *_ = _cover_case(client)
    body = {"payments": [{"payment_id": hers[0], "allocations": []}]}
    url = f"/api/shared/groups/{other}/cover"
    assert client.put(url, json=body, headers=WRITE).status_code == 422


def test_no_dismisses_every_payment_of_the_suggestion_as_one_change(client: TestClient) -> None:
    group_id, _, _, hers = _spread_case(client)
    url = f"/api/shared/groups/{group_id}/cover-dismissed"
    group = client.put(url, json={"payment_ids": hers, "dismissed": True}, headers=WRITE).json()
    assert group["cover"] is None
    entry = _last_log(client)
    assert entry["kind"] == "group_payment" and "3 pagos" in entry["summary"]  # spanish-data
    assert client.post(f"/api/log/{entry['id']}/undo", headers=WRITE).status_code == 200
    assert _get(client, group_id)["cover"]["payment_ids"] == hers
