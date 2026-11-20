"""The change log through the API: each kind of change leaves its entry, undo, reason, filters,
author, a transaction's history and the possible-rule review item, with made-up data."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import categories, rates
from michelito.i18n import t
from michelito.web.app import create_app
from tests.helpers import store
from tests.test_spending import _add_bank_rows, seed
from tests.test_web_exchanges import _bank, _row

WRITE = {"X-Michelito": "1"}
CLAUDE = {**WRITE, "X-Michelito-Author": "claude"}
MONTH = "2026-01"
WITHDRAWAL = "RETIRO CAJERO AUTOMATICO INVENTADO"
DEPOSIT = "DEPOSITO EFECTIVO INVENTADO"
SENT = "MB a 0000000066 SOCIO INVENTADO"
BACK = "TRANSF DE SOCIO INVENTADO"
DELIVERY = "PEDIDO DELIVERY FICTICIO"
REFUND = "TRANSF DE CAROLA INVENTADA"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-10", WITHDRAWAL, "debit", "2000000"),
                ("2026-01-25", DEPOSIT, "credit", "600000"),
                ("2026-01-08", SENT, "debit", "30000000"),
                ("2026-01-20", BACK, "credit", "900000"),
                ("2026-01-05", DELIVERY, "debit", "120000"),
                ("2026-01-15", DELIVERY, "debit", "130000"),
                ("2026-01-22", DELIVERY, "debit", "140000"),
                ("2026-01-12", REFUND, "credit", "30000"),
            ],
        )
        store(
            conn,
            _bank(
                "checking",
                "111-1",
                "DOP",
                (_row("2026-01-12", "DEPOSITO CAMBIO FICTICIO", "63700.00", "credit", "DOP"),),
            ),
        )
        store(
            conn,
            _bank(
                "savings",
                "222-2",
                "USD",
                (_row("2026-01-13", "TRANSFERENCIA A PERSONA", "1000.00", "debit", "USD"),),
            ),
        )
        with conn:
            rates.store_bcrd(conn, {"2026-01": Decimal("63.70")})
    return TestClient(create_app(path, today=lambda: date(2026, 2, 7)), "http://127.0.0.1")


def _items(client: TestClient) -> list[dict]:
    return client.get("/api/transactions", params={"month": MONTH}).json()["items"]


def _fps(client: TestClient, text: str) -> list[str]:
    found = [i for i in _items(client) if i["description"].startswith(text)]
    return [i["fingerprint"] for i in sorted(found, key=lambda i: i["day"])]


def _fp(client: TestClient, text: str) -> str:
    return _fps(client, text)[0]


def _tx(client: TestClient, fp: str) -> dict:
    return client.get(f"/api/transactions/{fp}").json()


def _log(client: TestClient, **params) -> list[dict]:
    response = client.get("/api/log", params=params)
    assert response.status_code == 200
    return response.json()["items"]


def _last(client: TestClient) -> dict:
    return _log(client)[0]


def _category_id(client: TestClient, name: str) -> int:
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


def _patch(client: TestClient, fp: str, headers: dict = WRITE, **body):
    return client.patch(f"/api/transactions/{fp}", json=body, headers=headers)


def _undo(client: TestClient, entry_id: int):
    return client.post(f"/api/log/{entry_id}/undo", headers=WRITE)


def test_empty_log(client: TestClient) -> None:
    body = client.get("/api/log").json()
    assert (body["items"], body["total"], body["kinds"]) == ([], 0, [])


def test_category_note_and_one_off_each_leave_an_entry_and_undo(client: TestClient) -> None:
    fp = _fp(client, WITHDRAWAL)
    delivery = _category_id(client, categories.DELIVERY)
    response = _patch(client, fp, category_id=delivery, note="for the party", one_off=True)
    assert response.status_code == 200
    entries = _log(client)
    assert [(e["kind"], e["before"]["text"], e["after"]["text"]) for e in entries] == [
        ("category", categories.CASH, categories.DELIVERY),
        ("one_off", "no", "sí"),  # spanish-ui
        ("note", "—", "for the party"),
    ]
    category = entries[0]
    assert (category["subject"], category["affected"], category["fingerprint"]) == (
        _tx(client, fp)["merchant"],
        1,
        fp,
    )
    assert category["after"]["rows"]["transaction_notes"][0]["category_id"] == delivery
    assert all(e["can_undo"] and e["author"] == "user" for e in entries)

    undone = _undo(client, category["id"])
    assert undone.status_code == 200
    # The original comes back with its new state; the audit record stays out of the list.
    assert (undone.json()["id"], undone.json()["undone"], undone.json()["can_redo"]) == (
        category["id"],
        True,
        True,
    )
    row = _tx(client, fp)
    assert (row["category"], row["note"], row["one_off"]) == (
        categories.CASH,
        "for the party",
        True,
    )
    first = next(e for e in _log(client) if e["id"] == category["id"])
    assert (first["undone"], first["can_undo"], first["toggles"]) == (True, False, 1)
    assert len(_log(client)) == 3 and all(e["undoes"] is None for e in _log(client))


def test_undo_blocked_after_a_later_change(client: TestClient) -> None:
    fp = _fp(client, WITHDRAWAL)
    _patch(client, fp, category_id=_category_id(client, categories.DELIVERY))
    _patch(client, fp, category_id=_category_id(client, categories.RESTAURANTS))
    newer, older = _log(client)
    assert (older["can_undo"], older["blocked_by"]) == (False, newer["id"])
    assert str(newer["id"]) in older["undo_message"]
    blocked = _undo(client, older["id"])
    assert blocked.status_code == 409 and str(newer["id"]) in blocked.json()["detail"]
    assert _undo(client, 999).status_code == 404


def test_a_failed_change_leaves_no_entry(client: TestClient) -> None:
    fp = _fp(client, WITHDRAWAL)
    # The note would be saved before the category, but the category is invalid: nothing stays.
    response = _patch(client, fp, note="x", category_id=99999)
    assert response.status_code in (404, 422)
    assert _log(client) == [] and _tx(client, fp)["note"] == ""


def test_merchant_rule_lists_affected_and_undo_restores_previous_rule(client: TestClient) -> None:
    first, second, third = _fps(client, DELIVERY)
    home = _category_id(client, categories.HOME)
    _patch(client, first, category_id=_category_id(client, categories.DELIVERY), scope="merchant")
    _patch(client, second, category_id=home, scope="merchant")
    rule = _last(client)
    assert (rule["kind"], rule["target_type"], rule["before"]["text"], rule["after"]["text"]) == (
        "merchant_rule",
        "merchant",
        categories.DELIVERY,
        categories.HOME,
    )
    assert rule["affected"] == 3 and set(rule["fingerprints"]) == {first, second, third}
    assert _undo(client, rule["id"]).status_code == 200
    assert {_tx(client, fp)["category"] for fp in (first, second, third)} == {categories.DELIVERY}


def test_author_header_marks_claude_and_rejects_unknown(client: TestClient) -> None:
    fp = _fp(client, WITHDRAWAL)
    assert _patch(client, fp, headers=CLAUDE, note="proposed").status_code == 200
    assert _last(client)["author"] == "claude"
    bad = _patch(client, fp, headers={**WRITE, "X-Michelito-Author": "other"}, note="x")
    assert bad.status_code == 400
    assert [e["author"] for e in _log(client, author="claude")] == ["claude"]
    assert _log(client, author="user") == []


def test_reason_is_editable_and_filters_search_it(client: TestClient) -> None:
    fp = _fp(client, WITHDRAWAL)
    _patch(client, fp, note="something")
    entry = _last(client)
    saved = client.patch(f"/api/log/{entry['id']}", json={"reason": " gift "}, headers=WRITE)
    assert saved.status_code == 200 and saved.json()["reason"] == "gift"
    assert len(_log(client)) == 1  # the reason is not a change
    assert [e["id"] for e in _log(client, q="GIFT")] == [entry["id"]]
    assert _log(client, q="nothing like it") == []
    assert [e["id"] for e in _log(client, kind="note,category")] == [entry["id"]]
    assert _log(client, kind="merchant_rule") == []
    too_long = client.patch(f"/api/log/{entry['id']}", json={"reason": "x" * 501}, headers=WRITE)
    assert too_long.status_code == 422
    assert client.patch("/api/log/999", json={"reason": "x"}, headers=WRITE).status_code == 404
    assert client.patch(f"/api/log/{entry['id']}", json={"reason": "x"}).status_code == 403


def test_pagination_and_sessions(client: TestClient) -> None:
    fp = _fp(client, WITHDRAWAL)
    for text in ("a", "b", "c"):
        _patch(client, fp, note=text)
    page = client.get("/api/log", params={"limit": 2, "offset": 1}).json()
    assert (page["total"], len(page["items"]), page["offset"]) == (3, 2, 1)
    assert {e["session_count"] for e in page["items"]} == {3}


def test_shared_group_actions_are_logged_and_undo_restores_them(client: TestClient) -> None:
    expense = _fp(client, "CAFE FICTICIO")
    credit = _fp(client, REFUND)
    made = client.post(
        "/api/shared/groups", json={"name": "Carola", "people": [{"name": "Carola"}]}, headers=WRITE
    ).json()
    group = made["id"]
    carola = next(m["id"] for m in made["members"] if not m["is_me"])
    assert (_last(client)["kind"], _last(client)["target_type"]) == ("group_new", "link")
    body = {"fingerprint": expense, "split": "equal", "people": [carola]}  # for someone else
    client.post(f"/api/shared/groups/{group}/entries", json=body, headers=WRITE)
    entry = _last(client)
    assert (entry["kind"], entry["target"]) == ("group_entry", f"group-{group}")
    assert expense in entry["fingerprints"]
    paid = client.get(f"/api/transactions/{credit}").json()
    payment = {
        "from_contact": carola,
        "to_contact": next(m["id"] for m in made["members"] if m["is_me"]),
        "amount_cents": -paid["amount_cents"],
        "day": paid["day"],
        "fingerprint": credit,
    }
    client.post(f"/api/shared/groups/{group}/payments", json=payment, headers=WRITE)
    client.patch(f"/api/shared/groups/{group}", json={"name": "Trip"}, headers=WRITE)
    renamed = _last(client)
    assert "Trip" in renamed["after"]["text"]
    written = {"contact_id": carola, "written_off": True}
    client.post(f"/api/shared/groups/{group}/write-off", json=written, headers=WRITE)
    before = client.get(f"/api/shared/groups/{group}").json()
    entry_id = next(i["id"] for i in before["timeline"] if i["kind"] == "entry")
    gone = client.delete(f"/api/shared/entries/{entry_id}", headers=WRITE)
    assert gone.status_code == 200
    deleted = _last(client)
    assert expense in deleted["fingerprints"]
    assert _undo(client, deleted["id"]).status_code == 200
    assert client.get(f"/api/shared/groups/{group}").json() == before


def test_exchange_investment_and_cash_box_are_logged(client: TestClient) -> None:
    dop_leg = _fp(client, "DEPOSITO CAMBIO")
    usd_leg = _fp(client, "TRANSFERENCIA A PERSONA")
    made = client.post("/api/exchanges", json={"fingerprints": [dop_leg, usd_leg]}, headers=WRITE)
    assert made.status_code == 201
    exchange = _last(client)
    assert (exchange["kind"], exchange["target"]) == ("exchange", str(made.json()["id"]))
    assert set(exchange["fingerprints"]) == {dop_leg, usd_leg}

    sent, back = _fp(client, SENT), _fp(client, BACK)
    created = client.post(
        "/api/investments", json={"fingerprint": sent, "with_whom": "Partner"}, headers=WRITE
    )
    investment = created.json()["id"]
    client.post(
        f"/api/investments/{investment}/members",
        json={"fingerprint": back, "role": "mixed", "capital_cents": 400000},
        headers=WRITE,
    )
    mixed = _last(client)
    assert (mixed["kind"], mixed["target"]) == ("investment", str(investment))
    member = mixed["after"]["rows"]["link_members"][0]
    assert (member["role"], member["capital_cents"]) == ("mixed", 400000)
    assert _undo(client, mixed["id"]).status_code == 200
    assert _tx(client, back)["investment"] is None

    withdrawal = _fp(client, WITHDRAWAL)
    assert client.put(f"/api/cash-box/stored/{withdrawal}", headers=WRITE).status_code == 200
    stored = _last(client)
    assert (stored["kind"], stored["before"]["text"], stored["after"]["text"]) == (
        "cash_box",
        categories.CASH,
        categories.CASH_BOX,
    )
    box = client.get("/api/cash-box").json()
    assert _undo(client, stored["id"]).status_code == 200
    assert _tx(client, withdrawal)["category"] == categories.CASH
    assert box["exists"] is True


def test_manual_cash_entries_are_logged_and_undo_brings_back_the_same_id(
    client: TestClient,
) -> None:
    body = {"kind": "expense", "day": "2026-01-15", "amount_cents": 50000, "currency": "DOP"}
    made = client.post("/api/cash-box/entries", json={**body, "note": "x"}, headers=WRITE)
    assert made.status_code == 201
    entry = _last(client)
    assert (entry["kind"], entry["target"]) == ("cash_entry", "cash-1")
    assert entry["fingerprints"] == ["cash-1"]
    assert client.delete("/api/cash-box/entries/1", headers=WRITE).status_code == 200
    deleted = _last(client)
    assert "salida RD$ 500.00" in deleted["before"]["text"]  # spanish-ui
    assert _undo(client, deleted["id"]).status_code == 200
    restored = _tx(client, "cash-1")
    assert (restored["note"], restored["amount_cents"]) == ("x", 50000)


def test_recurring_marks_review_and_one_off_dismissals_are_logged(client: TestClient) -> None:
    fp = _fp(client, "CAFE FICTICIO")
    merchant = _tx(client, fp)["merchant"]
    body = {"merchant": merchant, "currency": "DOP", "status": "confirmed"}
    assert client.put("/api/recurring/mark", json=body, headers=WRITE).status_code == 200
    mark = _last(client)
    assert (mark["kind"], mark["target_type"], mark["after"]["text"]) == (
        "recurring",
        "recurring",
        t("analysis.changelog_rules.mark_confirmed"),
    )
    assert fp in mark["fingerprints"]

    big = _fp(client, SENT)
    client.put(f"/api/review/large_third_party/{big}", json={"reviewed": True}, headers=WRITE)
    assert (_last(client)["kind"], _last(client)["after"]["text"]) == (
        "reviewed",
        t("analysis.changelog_rules.reviewed"),
    )
    client.put(f"/api/one-off-suggestions/{big}", json={"dismissed": True}, headers=WRITE)
    assert (_last(client)["kind"], _last(client)["after"]["text"]) == (
        "reviewed",
        "no es único",  # spanish-ui
    )


def test_keywords_kind_change_and_category_delete_are_logged(client: TestClient) -> None:
    made = client.post(
        "/api/categories",
        json={"name": "Orders", "kind": "expense", "keywords": ["pedido delivery"]},  # spanish-data
        headers=WRITE,
    )
    category = made.json()["id"]
    words = _last(client)
    assert (words["kind"], words["before"]["text"], words["after"]["text"]) == (
        "keywords",
        "—",
        "PEDIDO DELIVERY",
    )
    assert set(words["fingerprints"]) == set(_fps(client, DELIVERY))
    client.patch(f"/api/categories/{category}", json={"color": "#112233"}, headers=WRITE)
    assert _last(client)["id"] == words["id"]  # the color is not logged
    client.patch(f"/api/categories/{category}", json={"kind": "income"}, headers=WRITE)
    kind = _last(client)
    assert (kind["kind"], kind["before"]["text"], kind["after"]["text"]) == (
        "category_kind",
        t("analysis.categories.kind_expense"),
        t("analysis.categories.kind_income"),
    )
    other = _category_id(client, categories.DELIVERY)
    gone = client.delete(
        f"/api/categories/{category}", params={"reassign_to": other}, headers=WRITE
    )
    assert gone.status_code == 204
    deleted = _last(client)
    assert deleted["kind"] == "category_deleted" and deleted["after"]["text"].endswith(
        f"{categories.DELIVERY})"
    )
    assert _undo(client, deleted["id"]).status_code == 200
    back = next(c for c in client.get("/api/categories").json() if c["id"] == category)
    assert (back["name"], back["kind"], back["keywords"]) == (
        "Orders",
        "income",
        ["PEDIDO DELIVERY"],
    )


def test_history_of_a_transaction_and_rule_suggestion(client: TestClient) -> None:
    first, second, third = _fps(client, DELIVERY)
    delivery = _category_id(client, categories.DELIVERY)
    _patch(client, first, category_id=delivery)
    assert _review(client, "possible_rule") == []  # with just one, nothing is proposed
    _patch(client, second, category_id=delivery)
    (item,) = _review(client, "possible_rule")
    merchant = _tx(client, first)["merchant"]
    assert item["fingerprint"] == second and item["category_id"] == delivery
    assert item["reason"] == t(
        "web.review.rule_reason", merchant=merchant, count=2, category=categories.DELIVERY
    )

    history = client.get(f"/api/transactions/{first}/history").json()
    assert [e["kind"] for e in history["items"]] == ["category"]
    assert history["rule_hint"] is None  # already in that category
    hint = client.get(f"/api/transactions/{third}/history").json()["rule_hint"]
    assert hint == {
        "merchant": merchant,
        "category_id": delivery,
        "category": categories.DELIVERY,
        "count": 2,
    }
    assert client.get("/api/transactions/missing-fp/history").status_code == 404

    dismissed = client.put(
        f"/api/review/possible_rule/{second}", json={"reviewed": True}, headers=WRITE
    )
    assert dismissed.status_code == 200
    assert _last(client)["kind"] == "reviewed" and _last(client)["target_type"] == "merchant"
    assert _review(client, "possible_rule") == []
    _patch(client, third, category_id=delivery)  # a third identical one: still dismissed
    assert _review(client, "possible_rule") == []


def test_accepting_a_rule_suggestion_creates_the_rule(client: TestClient) -> None:
    first, second, third = _fps(client, DELIVERY)
    delivery = _category_id(client, categories.DELIVERY)
    _patch(client, first, category_id=delivery)
    _patch(client, second, category_id=delivery)
    _patch(client, second, category_id=delivery, scope="merchant")
    assert _last(client)["kind"] == "merchant_rule"
    assert _tx(client, third)["category"] == categories.DELIVERY
    assert _review(client, "possible_rule") == []


def test_a_contrary_edit_stops_the_suggestion(client: TestClient) -> None:
    first, second, third = _fps(client, DELIVERY)
    _patch(client, first, category_id=_category_id(client, categories.DELIVERY))
    _patch(client, second, category_id=_category_id(client, categories.DELIVERY))
    _patch(client, third, category_id=_category_id(client, categories.RESTAURANTS))
    assert _review(client, "possible_rule") == []


def _review(client: TestClient, kind: str) -> list[dict]:
    items = client.get("/api/review", params={"month": MONTH}).json()
    return [i for i in items if i["kind"] == kind]


def test_claude_edits_do_not_teach_the_rule(client: TestClient) -> None:
    first, second, _ = _fps(client, DELIVERY)
    delivery = _category_id(client, categories.DELIVERY)
    _patch(client, first, headers=CLAUDE, category_id=delivery)
    _patch(client, second, headers=CLAUDE, category_id=delivery)
    assert _review(client, "possible_rule") == []
    _patch(client, first, category_id=_category_id(client, categories.RESTAURANTS))
    _patch(client, first, category_id=delivery)  # one by the user: still just one
    assert _review(client, "possible_rule") == []
