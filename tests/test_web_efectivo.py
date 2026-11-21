"""The cash account (schema 23) through the API: concepts, scheduled payments and collections,
their answers and 7-day rules, automatic withdrawals after the activation and "I spent it
directly", the reconcile and its undo. Synthetic data only (tests/samples.py)."""

from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import cash_activation, categories, rates
from michelito.i18n import t
from michelito.web.app import create_app
from tests.test_spending import _add_bank_rows, seed

WRITE = {"X-Michelito": "1"}
WITHDRAWAL = "RETIRO CAJERO AUTOMATICO INVENTADO"
LATE_WITHDRAWAL = "RETIRO CAJERO AUTOMATICO INVENTADO DOS"


class Clock:
    def __init__(self, day: date) -> None:
        self.day = day

    def __call__(self) -> date:
        return self.day


@pytest.fixture
def clock() -> Clock:
    return Clock(date(2026, 2, 7))


@pytest.fixture
def path(tmp_path: Path) -> Path:
    found = tmp_path / "michelito.db"
    with closing(db.connect(found)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-10", WITHDRAWAL, "debit", "2000000"),
                ("2026-02-05", LATE_WITHDRAWAL, "debit", "500000"),
            ],
        )
        with conn:
            rates.store_bcrd(conn, {"2026-01": Decimal("60"), "2026-02": Decimal("60")})
    return found


@pytest.fixture
def client(path: Path, clock: Clock) -> TestClient:
    return TestClient(create_app(path, today=clock), "http://127.0.0.1")


def _box(client: TestClient) -> dict:
    return client.get("/api/cash-box").json()


def _entry(client: TestClient, **body) -> dict:
    response = client.post("/api/cash-box/entries", json=body, headers=WRITE)
    assert response.status_code == 201, response.text
    return response.json()


def _schedule(client: TestClient, **body) -> dict:
    base = {"kind": "payment", "concept": "Cleaning", "amount_cents": 300_000, "currency": "DOP"}
    response = client.post("/api/cash-box/schedules", json={**base, **body}, headers=WRITE)
    assert response.status_code == 201, response.text
    return response.json()


def _answer(client: TestClient, entry_id: int, action: str, amount: int | None = None) -> dict:
    body = {"action": action, "amount_cents": amount}
    response = client.post(f"/api/cash-box/occurrences/{entry_id}", json=body, headers=WRITE)
    assert response.status_code == 200, response.text
    return response.json()


def _summary(client: TestClient, month: str) -> dict:
    return client.get("/api/summary", params={"month": month}).json()


def _tx(client: TestClient, month: str, text: str) -> dict:
    items = client.get("/api/transactions", params={"month": month}).json()["items"]
    return next(i for i in items if i["description"] == text)


def _last_log(client: TestClient) -> dict:
    return client.get("/api/log").json()["items"][0]


def _undo(client: TestClient, entry_id: int) -> None:
    assert client.post(f"/api/log/{entry_id}/undo", headers=WRITE).status_code == 200


def _balance(box: dict, currency: str = "DOP") -> int:
    return next((b["amount_cents"] for b in box["balances"] if b["currency"] == currency), 0)


# --- Concepts ------------------------------------------------------------------------------


def test_a_new_expense_needs_a_concept_and_it_is_the_description(client: TestClient) -> None:
    base = {"kind": "expense", "day": "2026-02-06", "amount_cents": 25_000, "currency": "DOP"}
    missing = client.post("/api/cash-box/entries", json=base, headers=WRITE)
    assert missing.status_code == 422
    assert missing.json()["detail"] == t("analysis.cash_box.concept_required")
    blank = client.post("/api/cash-box/entries", json={**base, "concept": "   "}, headers=WRITE)
    assert blank.status_code == 422
    long = client.post("/api/cash-box/entries", json={**base, "concept": "x" * 61}, headers=WRITE)
    assert long.status_code == 422
    box = _entry(client, **base, concept="  Corner   store ")
    assert box["lines"][0]["concept"] == "Corner store"
    row = _tx(client, "2026-02", "Corner store")
    assert (row["merchant"], row["category"]) == ("CORNER STORE", categories.CASH)
    found = client.get("/api/transactions", params={"month": "2026-02", "q": "corner"}).json()
    assert [i["description"] for i in found["items"]] == ["Corner store"]


def test_an_old_entry_without_a_concept_keeps_the_generic_description(path: Path) -> None:
    from michelito.analysis import cash_box_store, spending

    with closing(db.connect(path)) as conn:
        with conn:
            cash_box_store.add_entry(conn, "expense", date(2026, 1, 20), Decimal(5), "DOP")
        [row] = [m for m in spending.load_all(conn) if m.fingerprint == "cash-1"]
    assert row.description == t("analysis.cash_box.description_expense")


def test_an_old_entry_still_corrects_only_itself(client: TestClient, path: Path) -> None:
    from michelito.analysis import cash_box_store

    with closing(db.connect(path)) as conn, conn:
        cash_box_store.add_entry(conn, "expense", date(2026, 2, 1), Decimal(5), "DOP")
    patch = {"category": categories.GROCERIES, "scope": "merchant"}
    response = client.patch("/api/transactions/cash-1", json=patch, headers=WRITE)
    assert response.status_code == 422
    assert response.json()["detail"] == t("web.cash_box_self_only")


def test_the_concept_is_the_merchant_for_rules(client: TestClient) -> None:
    listed = client.get("/api/categories").json()
    groceries = next(c["id"] for c in listed if c["name"] == categories.GROCERIES)
    base = {"kind": "expense", "amount_cents": 10_000, "currency": "DOP"}
    _entry(client, **base, day="2026-02-01", concept="Corner store")
    first = _tx(client, "2026-02", "Corner store")
    patch = {"category_id": groceries, "scope": "merchant"}
    response = client.patch(f"/api/transactions/{first['fingerprint']}", json=patch, headers=WRITE)
    assert response.status_code == 200, response.text
    # The next one with the same concept (any case) takes the merchant rule.
    _entry(client, **base, day="2026-02-03", concept="corner STORE")
    assert _tx(client, "2026-02", "corner STORE")["category"] == categories.GROCERIES
    # The autocomplete brings the last category and currency.
    [concept] = client.get("/api/cash-box/concepts").json()
    assert (concept["concept"], concept["category_id"], concept["currency"]) == (
        "corner STORE",
        groceries,
        "DOP",
    )


# --- Scheduled payments -----------------------------------------------------------------------


def test_creating_a_schedule_materializes_what_is_due_once(client: TestClient) -> None:
    box = _schedule(client, frequency="weekly", start_day="2026-01-24")
    occurrences = box["occurrences"]
    assert [o["day"] for o in occurrences] == ["2026-01-31", "2026-02-07"]  # 01-24: over a week
    assert [line["state"] for line in box["lines"] if line["schedule_id"]] == [
        "pending",
        "pending",
        "unconfirmed",
    ]
    # Loading again (every request materializes) never duplicates.
    for _ in range(3):
        again = _box(client)
    assert len([line for line in again["lines"] if line["schedule_id"]]) == 3
    assert again["upcoming"]["day"] == "2026-02-14"
    assert again["schedules"][0]["next_due"] == "2026-02-14"


def test_a_new_occurrence_appears_on_its_date(client: TestClient, clock: Clock) -> None:
    _schedule(client, frequency="monthly", start_day="2026-02-07")
    assert len(_box(client)["occurrences"]) == 1
    clock.day = date(2026, 3, 6)
    assert _box(client)["occurrences"] == []  # 03-07 not yet; 02-07 is now unconfirmed
    clock.day = date(2026, 3, 7)
    box = _box(client)
    assert [o["day"] for o in box["occurrences"]] == ["2026-03-07"]


def test_paid_other_amount_and_not_paid(client: TestClient) -> None:
    box = _schedule(client, frequency="weekly", start_day="2026-01-31")
    first, second = (o["entry_id"] for o in box["occurrences"])
    spent_before = _summary(client, "2026-02")["total_cents"]
    box = _answer(client, second, "amount", 250_000)
    assert _summary(client, "2026-02")["total_cents"] == spent_before - 50_000
    assert [o["entry_id"] for o in box["occurrences"]] == [first]
    box = _answer(client, first, "skip")
    assert box["occurrences"] == []
    assert all(line["entry_id"] != first for line in box["lines"])
    # Remembered: not created again.
    assert all(line["entry_id"] != first for line in _box(client)["lines"])
    assert len([line for line in _box(client)["lines"] if line["schedule_id"]]) == 1


def test_confirm_and_its_undo(client: TestClient) -> None:
    box = _schedule(client, frequency="weekly", start_day="2026-02-06")
    [item] = box["occurrences"]
    assert _answer(client, item["entry_id"], "confirm")["occurrences"] == []
    entry = _last_log(client)
    assert entry["kind"] == "cash_occurrence"
    _undo(client, entry["id"])
    assert [o["entry_id"] for o in _box(client)["occurrences"]] == [item["entry_id"]]


def test_an_unanswered_payment_counts_as_paid_after_a_week(
    client: TestClient, clock: Clock
) -> None:
    before = _summary(client, "2026-02")["total_cents"]
    _schedule(client, frequency="monthly", start_day="2026-02-07", max_count=1)
    assert _summary(client, "2026-02")["total_cents"] == before + 300_000
    clock.day = date(2026, 2, 14)  # 7 days: still pending
    assert len(_box(client)["occurrences"]) == 1
    clock.day = date(2026, 2, 15)
    box = _box(client)
    assert box["occurrences"] == []
    assert _summary(client, "2026-02")["total_cents"] == before + 300_000
    assert _tx(client, "2026-02", "Cleaning")["cash_state"] == "unconfirmed"
    assert _balance(box) == -300_000


def test_an_unanswered_collection_stops_counting_after_a_week(
    client: TestClient, clock: Clock
) -> None:
    before = _summary(client, "2026-02")["income_cents"]
    box = _schedule(
        client, kind="collection", concept="Rent", frequency="monthly", start_day="2026-02-07"
    )
    assert _summary(client, "2026-02")["income_cents"] == before + 300_000
    assert _balance(box) == 300_000
    clock.day = date(2026, 2, 15)
    box = _box(client)
    [item] = box["occurrences"]
    assert item["state"] == "lapsed"
    assert _balance(box) == 0
    assert _summary(client, "2026-02")["income_cents"] == before
    box = _answer(client, item["entry_id"], "confirm")
    assert _balance(box) == 300_000
    assert _summary(client, "2026-02")["income_cents"] == before + 300_000


def test_pause_resume_and_a_new_amount(client: TestClient, clock: Clock) -> None:
    box = _schedule(client, frequency="weekly", start_day="2026-02-06")
    schedule = box["schedules"][0]["id"]
    paused = client.put(
        f"/api/cash-box/schedules/{schedule}/paused", json={"paused": True}, headers=WRITE
    )
    assert paused.json()["schedules"][0]["paused"] is True
    assert paused.json()["upcoming"] is None
    clock.day = date(2026, 2, 20)  # 02-13 and 02-20 pass while paused
    client.put(f"/api/cash-box/schedules/{schedule}/paused", json={"paused": False}, headers=WRITE)
    days = [line["day"] for line in _box(client)["lines"] if line["schedule_id"]]
    assert days == ["2026-02-20", "2026-02-06"]  # 02-13 is not created
    body = {
        "kind": "payment",
        "concept": "Cleaning",
        "amount_cents": 350_000,
        "currency": "DOP",
        "frequency": "weekly",
        "start_day": "2026-02-06",
    }
    changed = client.put(f"/api/cash-box/schedules/{schedule}", json=body, headers=WRITE)
    assert changed.status_code == 200
    clock.day = date(2026, 2, 27)
    lines = {line["day"]: line for line in _box(client)["lines"] if line["schedule_id"]}
    amounts = {day: line["source_amount_cents"] for day, line in lines.items()}
    assert amounts == {"2026-02-27": 350_000, "2026-02-20": 300_000, "2026-02-06": 300_000}


def test_deleting_a_schedule_keeps_its_past_occurrences(client: TestClient, clock: Clock) -> None:
    box = _schedule(client, frequency="weekly", start_day="2026-02-06")
    schedule = box["schedules"][0]["id"]
    gone = client.delete(f"/api/cash-box/schedules/{schedule}", headers=WRITE).json()
    assert gone["schedules"] == []
    # Kept, detached from the schedule that is gone.
    assert [line["concept"] for line in gone["lines"]] == ["Cleaning"]
    clock.day = date(2026, 2, 20)
    assert [line["concept"] for line in _box(client)["lines"]] == ["Cleaning"]


def test_repeat_on_a_new_expense_is_one_change(client: TestClient, clock: Clock) -> None:
    body = {
        "kind": "expense",
        "day": "2026-02-07",
        "amount_cents": 300_000,
        "currency": "DOP",
        "concept": "Cleaning",
        "repeat": {"frequency": "weekly"},
    }
    box = _entry(client, **body)
    assert box["occurrences"] == []  # the one written is already paid
    assert box["schedules"][0]["next_due"] == "2026-02-14"
    entry = _last_log(client)
    _undo(client, entry["id"])
    box = _box(client)
    assert (box["schedules"], box["lines"]) == ([], [])


# --- Activation and automatic withdrawals ----------------------------------------------------


def test_withdrawals_move_into_cash_only_from_the_activation(
    client: TestClient, clock: Clock, path: Path
) -> None:
    january = _summary(client, "2026-01")["total_cents"]
    assert _tx(client, "2026-02", LATE_WITHDRAWAL)["cash_box_role"] == ""
    clock.day = date(2026, 2, 5)
    _entry(
        client, kind="expense", day="2026-02-05", amount_cents=1000, currency="DOP", concept="Tip"
    )
    with closing(db.connect(path)) as conn:
        assert cash_activation.activated_on(conn) == date(2026, 2, 5)
    late = _tx(client, "2026-02", LATE_WITHDRAWAL)
    assert (late["cash_box_role"], late["kind"]) == ("stored", "transfer")
    early = _tx(client, "2026-01", WITHDRAWAL)
    assert (early["cash_box_role"], early["can_store"]) == ("", True)  # before: unchanged
    assert _summary(client, "2026-01")["total_cents"] == january
    # A withdrawal then a cash expense: one spending (the expense), not two.
    february = _summary(client, "2026-02")
    assert february["total_cents"] == _tx(client, "2026-02", "Tip")["amount_cents"] + sum(
        i["amount_cents"]
        for i in client.get("/api/transactions", params={"month": "2026-02"}).json()["items"]
        if i["kind"] == "expense" and i["description"] != "Tip"
    )
    assert _balance(_box(client)) == 500_000 - 1000


def test_spent_directly_is_remembered(client: TestClient, clock: Clock) -> None:
    clock.day = date(2026, 2, 1)
    _entry(client, kind="initial", day="2026-02-01", amount_cents=100, currency="DOP")
    late = _tx(client, "2026-02", LATE_WITHDRAWAL)
    assert late["cash_box_role"] == "stored"
    spent = client.delete(f"/api/cash-box/stored/{late['fingerprint']}", headers=WRITE)
    assert spent.status_code == 200
    assert spent.json()["category"] == categories.CASH
    # New statements or alerts trigger the pass again: it stays as spending.
    for _ in range(2):
        assert _tx(client, "2026-02", LATE_WITHDRAWAL)["cash_box_role"] == ""
    undo = _last_log(client)
    _undo(client, undo["id"])
    assert _tx(client, "2026-02", LATE_WITHDRAWAL)["cash_box_role"] == "stored"


def test_the_pass_does_nothing_without_an_activation(client: TestClient, path: Path) -> None:
    _box(client)
    with closing(db.connect(path)) as conn:
        assert cash_activation.activated_on(conn) is None
        assert conn.execute("SELECT COUNT(*) FROM link_members").fetchone()[0] == 0


# --- Reconcile ----------------------------------------------------------------------------


def test_reconcile_with_less_cash_is_one_unrecorded_expense(client: TestClient) -> None:
    _entry(client, kind="initial", day="2026-01-01", amount_cents=1_000_000, currency="DOP")
    spent = _summary(client, "2026-02")["total_cents"]
    body = {"counts": [{"currency": "DOP", "amount_cents": 700_000}]}
    box = client.post("/api/cash-box/reconcile", json=body, headers=WRITE).json()
    assert _balance(box) == 700_000
    line = box["lines"][0]
    assert (line["kind"], line["concept"], line["day"]) == (
        "expense",
        t("analysis.cash_box.unrecorded_out"),
        "2026-02-07",
    )
    assert line["category"] == categories.CASH
    assert _summary(client, "2026-02")["total_cents"] == spent + 300_000
    assert (box["reconcile_due"], box["last_reconciled"]) == (False, "2026-02-07")
    _undo(client, _last_log(client)["id"])
    box = _box(client)
    assert _balance(box) == 1_000_000
    assert box["last_reconciled"] is None
    assert _summary(client, "2026-02")["total_cents"] == spent


def test_reconcile_with_more_cash_is_income_or_the_initial_balance(client: TestClient) -> None:
    income = _summary(client, "2026-02")["income_cents"]
    body = {"counts": [{"currency": "USD", "amount_cents": 20_000}]}
    box = client.post("/api/cash-box/reconcile", json=body, headers=WRITE).json()
    # No initial balance in US$ yet: the surplus is it (not income of the month).
    assert (box["lines"][0]["kind"], _balance(box, "USD")) == ("initial", 20_000)
    assert _summary(client, "2026-02")["income_cents"] == income
    body = {"counts": [{"currency": "USD", "amount_cents": 25_000}]}
    box = client.post("/api/cash-box/reconcile", json=body, headers=WRITE).json()
    line = box["lines"][0]
    assert (line["kind"], line["concept"]) == ("income", t("analysis.cash_box.unrecorded_in"))
    assert _balance(box, "USD") == 25_000
    assert _summary(client, "2026-02")["income_cents"] > income
    same = client.post("/api/cash-box/reconcile", json=body, headers=WRITE).json()
    assert len(same["lines"]) == len(box["lines"])  # matched: nothing written


def test_reconcile_clears_a_negative_balance(client: TestClient) -> None:
    box = _entry(
        client, kind="expense", day="2026-02-06", amount_cents=50_000, currency="DOP", concept="Gas"
    )
    assert box["negative"] == [{"currency": "DOP", "amount_cents": -50_000}]
    body = {"counts": [{"currency": "DOP", "amount_cents": 0}]}
    box = client.post("/api/cash-box/reconcile", json=body, headers=WRITE).json()
    assert box["negative"] == []
    assert box["lines"][0]["kind"] == "initial"  # no initial balance yet


def test_the_monthly_prompt(client: TestClient, clock: Clock) -> None:
    _entry(client, kind="initial", day="2026-02-01", amount_cents=100, currency="DOP")
    assert _box(client)["reconcile_due"] is False  # activated this month
    clock.day = date(2026, 3, 1)
    assert _box(client)["reconcile_due"] is True
    body = {"counts": [{"currency": "DOP", "amount_cents": 100}]}
    assert (
        client.post("/api/cash-box/reconcile", json=body, headers=WRITE).json()["reconcile_due"]
        is False
    )
    clock.day = date(2026, 3, 1) + timedelta(days=31)
    assert _box(client)["reconcile_due"] is True
