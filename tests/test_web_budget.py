"""Budget and reserves through the API: activating, caps, the "usual amount changed" warning,
one-offs, shared expenses, reserves (contribution, links, suggestions), the review list, the
Summary card, the change log and undo. Made-up data: a fictitious card from 2024-01 to 2026-01."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import categories
from michelito.parsers.common import Statement
from michelito.web.app import create_app
from tests.e2e_server import _purchase, _section
from tests.helpers import store
from tests.ledger_helpers import share

WRITE = {"X-Michelito": "1"}
TODAY = date(2026, 2, 20)
VEHICLE_TAX = "MARBETE INVENTADO"
FUN_EXTRA = "FERIA NAVIDENA FICTICIA"


def _months(first: tuple[int, int], count: int) -> list[str]:
    year, month = first
    found = []
    for _ in range(count):
        found.append(f"{year:04d}-{month:02d}")
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    return found


MONTHS = _months((2024, 1), 25)  # January 2024 to January 2026, all complete


def _card(
    identifier: str,
    rows: tuple,
    period_end: date = date(2026, 1, 31),
    institution: str = "ficticio",
) -> Statement:
    return Statement(
        parser="demo",
        institution=institution,
        kind="credit_card",
        product=f"VISA FICTICIA {identifier}",
        identifier=identifier,
        period_end=period_end,
        due_date=date(2026, 2, 25),
        sections=(_section("DOP", rows, "500.00", Decimal("900000.00")),),
    )


def _cinema(index: int) -> str:
    return ("CINE NORTE FICTICIO", "TEATRO SUR FICTICIO", "BOLERA ESTE FICTICIA")[index % 3]


def _history() -> tuple:
    rows = []
    for index, month in enumerate(MONTHS):
        rows.append(_purchase(f"{month}-05", "SUPERMERCADO FICTICIO", "10000.00", mcc="5411"))
        # Each month's entertainment, at changing places (not a monthly recurring series: if it
        # were, Entertainment would not be suggested as a peak).
        rows.append(_purchase(f"{month}-12", _cinema(index), "3000.00", mcc="7832"))
    # An Entertainment peak in December of two years (for the reserve suggestion).
    rows.append(_purchase("2024-12-15", FUN_EXTRA, "15000.00", mcc="7832"))
    rows.append(_purchase("2025-12-15", "PARQUE NAVIDENO FICTICIO", "15000.00", mcc="7832"))
    # A yearly (recurring) charge in the government and taxes category.
    rows.append(_purchase("2025-01-20", VEHICLE_TAX, "3400.00", mcc="9311"))
    rows.append(_purchase("2026-01-20", VEHICLE_TAX, "3400.00", mcc="9311"))
    # January 2026: a RD$ 4,000 dinner and a large purchase (the tests mark it as a one-off).
    rows.append(_purchase("2026-01-22", "RESTAURANTE FICTICIO", "4000.00", mcc="5812"))
    rows.append(_purchase("2026-01-25", "RESTAURANTE CARO FICTICIO", "45000.00", mcc="5812"))
    return tuple(rows)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    found = tmp_path / "michelito.db"
    with closing(db.connect(found)) as conn:
        store(conn, _card("1111", _history()))
    return found


@pytest.fixture
def client(path: Path) -> TestClient:
    return TestClient(create_app(path, today=lambda: TODAY), "http://127.0.0.1")


def _fp(client: TestClient, text: str, month: str = "2026-01") -> str:
    items = client.get("/api/transactions", params={"month": month}).json()["items"]
    return next(i["fingerprint"] for i in items if i["description"] == text)


def _line(body: dict, name: str) -> dict:
    return next(line for line in body["lines"] if line["category"] == name)


def _budget(client: TestClient, month: str = "2026-01") -> dict:
    return client.get("/api/budget", params={"month": month}).json()


def _activate(client: TestClient) -> int:
    response = client.post("/api/budget/activate", headers=WRITE)
    assert response.status_code == 201, response.text
    return response.json()["entry_id"]


def _category_id(client: TestClient, name: str) -> int:
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


def _reserve(client: TestClient, **body) -> int:
    base = {
        "name": "Plates",
        "amount_cents": 350_000,
        "category_id": _category_id(client, categories.GOVERNMENT),
        "due_month": "2027-01",
        "every_months": 12,
    }
    response = client.post("/api/reserves", json={**base, **body}, headers=WRITE)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _reserves(client: TestClient) -> dict:
    return client.get("/api/reserves").json()


def test_writes_need_the_header(client: TestClient) -> None:
    assert client.post("/api/budget/activate").status_code == 403
    assert client.put("/api/budget/caps/1", json={"cap_cents": 100}).status_code == 403
    assert client.post("/api/reserves", json={}).status_code == 403
    assert client.post("/api/reserve-suggestions/dismiss", json={"key": "x"}).status_code == 403


def test_activate_starts_at_the_rounded_habitual_once(client: TestClient) -> None:
    assert _budget(client)["active"] is False
    _activate(client)
    body = _budget(client)
    assert body["active"] is True
    assert body["reference_months"] == MONTHS[-6:]
    groceries = _line(body, categories.GROCERIES)
    assert (groceries["cap_cents"], groceries["manual"], groceries["spent_cents"]) == (
        1_000_000,
        False,
        1_000_000,
    )
    # Entertainment: six-month median with a high December = 3,000.
    assert _line(body, categories.ENTERTAINMENT)["cap_cents"] == 300_000
    # Government only had the January vehicle tax: its median is 0 -> no budget.
    assert _line(body, categories.GOVERNMENT)["cap_cents"] is None
    assert client.post("/api/budget/activate", headers=WRITE).status_code == 409


def test_one_off_stays_out_of_the_cap_and_a_hand_cap_is_fixed(client: TestClient) -> None:
    _activate(client)
    dinner = _fp(client, "RESTAURANTE CARO FICTICIO")
    patched = client.patch(f"/api/transactions/{dinner}", json={"one_off": True}, headers=WRITE)
    assert patched.status_code == 200, patched.text
    food = _category_id(client, categories.RESTAURANTS)
    assert (
        client.put(
            f"/api/budget/caps/{food}", json={"cap_cents": 300_000}, headers=WRITE
        ).status_code
        == 200
    )
    line = _line(_budget(client), categories.RESTAURANTS)
    assert (line["cap_cents"], line["manual"], line["spent_cents"], line["one_offs_cents"]) == (
        300_000,
        True,
        400_000,
        4_500_000,
    )
    assert line["over_cents"] == 100_000
    body = _budget(client)
    assert body["over_count"] == 1 and body["over_cents"] == 100_000
    assert body["lines"][0]["category"] == categories.RESTAURANTS  # the one most over, first
    # No carry-over: December does not see January.
    assert _line(_budget(client, "2025-12"), categories.RESTAURANTS)["spent_cents"] == 0
    # No budget, set by hand.
    assert (
        client.put(f"/api/budget/caps/{food}", json={"cap_cents": None}, headers=WRITE).status_code
        == 200
    )
    assert _line(_budget(client), categories.RESTAURANTS)["cap_cents"] is None


def test_shared_counts_only_my_part(client: TestClient, path: Path) -> None:
    _activate(client)
    fp = _fp(client, "SUPERMERCADO FICTICIO")
    with closing(db.connect(path)) as conn, conn:
        share(conn, fp, Decimal("10000.00"), people=2)
    assert _line(_budget(client), categories.GROCERIES)["spent_cents"] == 500_000


def test_habitual_change_warns_and_accept_or_ignore(client: TestClient, path: Path) -> None:
    _activate(client)
    # A new card with more groceries and cinema in the last six months: the usual amount rises.
    extra = []
    for month in MONTHS[-6:]:
        extra.append(_purchase(f"{month}-08", "SUPER FICTICIO DOS", "10000.00", mcc="5411"))
        extra.append(_purchase(f"{month}-09", "TEATRO FICTICIO", "2000.00", mcc="7922"))
    with closing(db.connect(path)) as conn:
        store(conn, _card("2222", tuple(extra)))
    body = _budget(client)
    groceries, fun = _line(body, categories.GROCERIES), _line(body, categories.ENTERTAINMENT)
    assert groceries["warning"] == {
        "habitual_cents": 2_000_000,
        "basis_cents": 1_000_000,
        "up": True,
    }
    assert fun["warning"] == {"habitual_cents": 500_000, "basis_cents": 300_000, "up": True}
    url = f"/api/budget/caps/{groceries['category_id']}/usual"
    assert client.post(url, json={"accept": True}, headers=WRITE).status_code == 200
    url = f"/api/budget/caps/{fun['category_id']}/usual"
    assert client.post(url, json={"accept": False}, headers=WRITE).status_code == 200
    body = _budget(client)
    assert (
        _line(body, categories.GROCERIES)["cap_cents"],
        _line(body, categories.GROCERIES)["warning"],
    ) == (
        2_000_000,
        None,
    )
    # Ignored: the cap stays and it does not warn again.
    assert (
        _line(body, categories.ENTERTAINMENT)["cap_cents"],
        _line(body, categories.ENTERTAINMENT)["warning"],
    ) == (
        300_000,
        None,
    )
    assert client.post(url, json={"accept": True}, headers=WRITE).status_code == 404


def test_reserves_contribution_and_linked_expense_is_covered(client: TestClient) -> None:
    _activate(client)
    yearly = _reserve(client)
    _reserve(client, name="Insurance", amount_cents=3_000_000, every_months=6, due_month="2026-03")
    _reserve(client, name="School", amount_cents=450_000, every_months=None, due_month="2026-12")
    items = {r["name"]: r for r in _reserves(client)["items"]}
    assert items["Plates"]["monthly_cents"] == 30_000  # 3,500 / 12 -> RD$ 300
    assert items["Insurance"]["monthly_cents"] == 500_000  # 30,000 / 6
    assert items["School"]["monthly_cents"] == 50_000  # 4,500 / 10 months -> RD$ 500
    assert items["Insurance"]["next_due"] == "2026-03"
    assert _reserves(client)["monthly_cents"] == 580_000

    fp = _fp(client, VEHICLE_TAX)
    detail = client.get(f"/api/transactions/{fp}/reserve").json()
    assert detail["can_link"] and yearly in [o["id"] for o in detail["options"]]
    # Created in February: the January due date is earlier, so it is not suggested (it can still
    # be linked by hand).
    assert not any(o["suggested"] for o in detail["options"])
    linked = client.post(
        f"/api/reserves/{yearly}/members", json={"fingerprints": [fp]}, headers=WRITE
    )
    assert linked.json()["applied"] == [fp]
    line = _line(_budget(client), categories.GOVERNMENT)
    assert (line["spent_cents"], line["covered_cents"]) == (0, 340_000)
    plates = next(r for r in _reserves(client)["items"] if r["id"] == yearly)
    # This year (2026): due in January and the linked expense is from January.
    assert (plates["year_spent_cents"], plates["year_estimated_cents"]) == (340_000, 350_000)
    assert client.get(f"/api/transactions/{fp}/reserve").json()["reserve"]["id"] == yearly
    tx = client.get(f"/api/transactions/{fp}").json()
    assert tx["link"] == "reserve" and tx["can_share"] is False
    # Removing the link puts it back under the cap.
    assert client.delete(f"/api/reserves/{yearly}/members/{fp}", headers=WRITE).status_code == 200
    line = _line(_budget(client), categories.GOVERNMENT)
    assert (line["spent_cents"], line["covered_cents"]) == (340_000, 0)


def test_a_reserve_with_several_expenses_and_the_batch(client: TestClient, path: Path) -> None:
    fun = _category_id(client, categories.ENTERTAINMENT)
    christmas = _reserve(
        client, name="Christmas", category_id=fun, amount_cents=1_800_000, due_month="2025-12",
        multiple=True,
    )  # fmt: skip
    gifts = [
        _fp(client, "PARQUE NAVIDENO FICTICIO", "2025-12"),
        _fp(client, _cinema(MONTHS.index("2025-12")), "2025-12"),
    ]
    shared = _fp(client, "SUPERMERCADO FICTICIO", "2025-12")
    with closing(db.connect(path)) as conn, conn:
        share(conn, shared, Decimal("10000.00"), people=2)
    body = {"fingerprints": [*gifts, shared, "missing-fp"]}
    found = client.post(f"/api/reserves/{christmas}/members", json=body, headers=WRITE).json()
    assert found["applied"] == gifts
    reasons = {s["fingerprint"]: s["reason"] for s in found["skipped"]}
    assert reasons["missing-fp"] == "unknown"
    assert reasons[shared] == "linked"  # one fingerprint, a single link
    christmas_reserve = next(r for r in _reserves(client)["items"] if r["id"] == christmas)
    assert {m["fingerprint"] for m in christmas_reserve["members"]} == set(gifts)
    _activate(client)
    line = _line(_budget(client, "2025-12"), categories.ENTERTAINMENT)
    assert (line["spent_cents"], line["covered_cents"]) == (0, 1_800_000)
    entries = client.get("/api/log", params={"kind": "reserve_expense"}).json()["items"]
    assert entries[0]["affected"] == 2
    assert entries[0]["after"]["text"].startswith("2 gastos")  # spanish-ui


def test_suggestions_from_a_yearly_recurring_and_a_repeated_peak(client: TestClient) -> None:
    found = {s["key"]: s for s in _reserves(client)["suggestions"]}
    recurring = next(s for k, s in found.items() if k.startswith("recurring:"))
    assert (recurring["name"], recurring["amount_cents"], recurring["due_month"]) == (
        VEHICLE_TAX.split()[0] + " INVENTADO",
        340_000,
        "2027-01",
    )
    peak = next(s for k, s in found.items() if k.startswith("peak:"))
    assert (peak["name"], peak["amount_cents"], peak["due_month"], peak["multiple"]) == (
        "Diciembre: Entretenimiento",  # spanish-ui
        1_500_000,  # last December over the cinema median (18,000 - 3,000)
        "2026-12",
        True,
    )
    # Dismissed: it does not come back (also with an account filter: only the key is checked).
    dismissed = client.post(
        "/api/reserve-suggestions/dismiss?accounts=x",
        json={"key": peak["key"], "name": peak["name"]},
        headers=WRITE,
    )
    assert dismissed.status_code == 200
    assert peak["key"] not in {s["key"] for s in _reserves(client)["suggestions"]}
    # Created from the suggestion: it does not come back either.
    _reserve(
        client,
        name=recurring["name"],
        amount_cents=recurring["amount_cents"],
        category_id=recurring["category_id"],
        due_month=recurring["due_month"],
        source=recurring["key"],
    )
    assert _reserves(client)["suggestions"] == []
    assert (
        client.post(
            "/api/reserve-suggestions/dismiss", json={"key": "missing-fp"}, headers=WRITE
        ).status_code
        == 422
    )


def test_one_year_of_data_suggests_no_peak(tmp_path: Path) -> None:
    path = tmp_path / "one.db"
    rows = [
        _purchase(f"{month}-12", _cinema(i), "3000.00", mcc="7832")
        for i, month in enumerate(MONTHS[-12:])
    ]
    rows.append(_purchase("2025-12-15", FUN_EXTRA, "30000.00", mcc="7832"))
    with closing(db.connect(path)) as conn:
        store(conn, _card("3333", tuple(rows)))
    client = TestClient(create_app(path, today=lambda: TODAY), "http://127.0.0.1")
    assert _reserves(client)["suggestions"] == []


def test_review_proposes_linking_and_no_does_not_come_back(path: Path) -> None:
    # Created in January 2026 (its "today"): that January's vehicle tax is from its due date.
    client = TestClient(create_app(path, today=lambda: date(2026, 1, 5)), "http://127.0.0.1")
    reserve = _reserve(client)
    fp = _fp(client, VEHICLE_TAX)
    items = client.get("/api/review", params={"month": "2026-01"}).json()
    [proposed] = [i for i in items if i["kind"] == "possible_reserve"]
    assert (proposed["fingerprint"], proposed["reserve_id"]) == (fp, reserve)
    assert "Plates" in proposed["reason"]
    marked = client.put(
        f"/api/review/possible_reserve/{fp}", json={"reviewed": True}, headers=WRITE
    )
    assert marked.status_code == 200
    items = client.get("/api/review", params={"month": "2026-01"}).json()
    assert not [i for i in items if i["kind"] == "possible_reserve"]


def test_overview_for_the_summary(client: TestClient) -> None:
    assert client.get("/api/budget/overview").json()["active"] is False
    _activate(client)
    _reserve(client)
    _reserve(client, name="School", amount_cents=450_000, every_months=None, due_month="2026-04")
    food = _category_id(client, categories.RESTAURANTS)
    client.put(f"/api/budget/caps/{food}", json={"cap_cents": 100_000}, headers=WRITE)
    body = client.get("/api/budget/overview", params={"month": "2026-01"}).json()
    assert (body["active"], body["over_count"], body["over_cents"]) == (True, 1, 4_800_000)
    assert body["monthly_cents"] == 30_000 + 150_000  # 3,500 / 12 and 4,500 / 3 months (Feb-Apr)
    assert [(u["name"], u["due_month"]) for u in body["upcoming"]] == [("School", "2026-04")]


def test_every_change_is_in_the_log_and_undoes(client: TestClient) -> None:
    _activate(client)
    food = _category_id(client, categories.RESTAURANTS)
    client.put(f"/api/budget/caps/{food}", json={"cap_cents": 100_000}, headers=WRITE)
    reserve = _reserve(client)
    client.patch(f"/api/reserves/{reserve}", json={"amount_cents": 400_000}, headers=WRITE)
    fp = _fp(client, VEHICLE_TAX)
    client.post(f"/api/reserves/{reserve}/members", json={"fingerprints": [fp]}, headers=WRITE)
    peak = next(s for s in _reserves(client)["suggestions"] if s["key"].startswith("peak:"))
    client.post(
        "/api/reserve-suggestions/dismiss",
        json={"key": peak["key"], "name": peak["name"]},
        headers=WRITE,
    )
    other = _reserve(client, name="Delete", due_month="2026-06", every_months=None)
    assert client.delete(f"/api/reserves/{other}", headers=WRITE).status_code == 204
    log = client.get("/api/log").json()
    kinds = [e["kind"] for e in log["items"]]
    assert kinds == [
        "reserve",
        "reserve",
        "reserve_dismissal",
        "reserve_expense",
        "reserve",
        "reserve",
        "budget",
        "budget",
    ]
    lines = [f"{e['subject']} · {e['before']['text']} → {e['after']['text']}" for e in log["items"]]
    assert lines == [
        "Delete · RD$ 3,500 · una vez, en 2026-06 → borrada",  # spanish-ui
        "Delete · — → RD$ 3,500 · una vez, en 2026-06",  # spanish-ui
        "Diciembre: Entretenimiento · sugerida → descartada",  # spanish-ui
        "MARBETE INVENTADO · — → cubierto por «Plates»",  # spanish-ui
        "Plates · RD$ 3,500 · cada año en enero → RD$ 4,000 · cada año en enero",  # spanish-ui
        "Plates · — → RD$ 3,500 · cada año en enero",  # spanish-ui
        "Restaurantes · sin presupuesto → tope RD$ 1,000",  # spanish-ui
        "Presupuesto · sin activar → 26 categorías, 2 con tope",  # spanish-ui
    ]
    # Undo everything, newest to oldest (each one is rehearsed first in a SAVEPOINT).
    for entry in log["items"]:
        now = {e["id"]: e for e in client.get("/api/log").json()["items"]}
        assert now[entry["id"]]["can_undo"], now[entry["id"]]["undo_message"]
        undone = client.post(f"/api/log/{entry['id']}/undo", headers=WRITE)
        assert undone.status_code == 200, undone.text
    assert _budget(client)["active"] is False
    assert _reserves(client)["items"] == []
    assert peak["key"] in {s["key"] for s in _reserves(client)["suggestions"]}


def test_a_cap_before_activating_is_a_conflict(client: TestClient) -> None:
    food = _category_id(client, categories.RESTAURANTS)
    put = client.put(f"/api/budget/caps/{food}", json={"cap_cents": 100_000}, headers=WRITE)
    assert put.status_code == 409
    assert _budget(client)["active"] is False


def test_only_yearly_half_yearly_or_once(client: TestClient) -> None:
    body = {
        "name": "Every three",
        "amount_cents": 100_000,
        "category_id": _category_id(client, categories.GOVERNMENT),
        "due_month": "2026-06",
        "every_months": 3,
    }
    assert client.post("/api/reserves", json=body, headers=WRITE).status_code == 422


def test_options_are_just_id_and_name(client: TestClient) -> None:
    found = _reserve(client)
    assert client.get("/api/reserves/options").json() == [{"id": found, "name": "Plates"}]


def test_a_paid_due_does_not_add_to_the_month_nor_to_upcoming(path: Path) -> None:
    client = TestClient(create_app(path, today=lambda: date(2026, 1, 10)), "http://127.0.0.1")
    reserve = _reserve(client, due_month="2026-01")
    assert [u["name"] for u in client.get("/api/budget/overview").json()["upcoming"]] == ["Plates"]
    fp = _fp(client, VEHICLE_TAX)
    client.post(f"/api/reserves/{reserve}/members", json={"fingerprints": [fp]}, headers=WRITE)
    body = client.get("/api/budget/overview").json()
    assert (body["upcoming"], body["monthly_cents"]) == ([], 0)
    item = _reserves(client)["items"][0]
    assert (item["paid"], item["monthly_cents"]) == (True, 0)


def test_with_an_account_filter_caps_are_of_all_and_passed_are_not_counted(
    client: TestClient,
) -> None:
    _activate(client)
    food = _category_id(client, categories.RESTAURANTS)
    client.put(f"/api/budget/caps/{food}", json={"cap_cents": 100_000}, headers=WRITE)
    key = client.get("/api/accounts").json()[0]["key"]
    body = client.get("/api/budget", params={"month": "2026-01", "accounts": key}).json()
    assert body["filtered"] is False  # with the only account selected it is "all"
    overview = client.get("/api/budget/overview", params={"month": "2026-01"}).json()
    assert overview["over_count"] == 1


def test_a_month_without_every_statement_says_what_is_missing(path: Path) -> None:
    late = (_purchase("2026-01-03", "TIENDA TARDE FICTICIA", "1000.00", mcc="5311"),)
    with closing(db.connect(path)) as conn:
        store(conn, _card("4444", late, period_end=date(2026, 1, 15), institution="late"))
    client = TestClient(create_app(path, today=lambda: TODAY), "http://127.0.0.1")
    _activate(client)
    body = _budget(client)
    assert body["missing"] and "4444" in body["missing"][0]
    keys = [a["key"] for a in client.get("/api/accounts").json()]
    chosen = next(k for k in keys if k.startswith("ficticio:"))
    filtered = client.get("/api/budget", params={"month": "2026-01", "accounts": chosen}).json()
    assert filtered["filtered"] is True and filtered["missing"] == []
    overview = client.get(
        "/api/budget/overview", params={"month": "2026-01", "accounts": chosen}
    ).json()
    assert overview["over_count"] is None  # with a filter the over-cap ones are not counted
    assert client.get("/api/budget/overview", params={"month": "2026-01"}).json()["missing"]
