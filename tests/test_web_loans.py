"""Loans in the board's API: creating one links every payment with its number (from any account,
earlier ones too), the card's figures, the row's tag, rates, real balances, linking by hand and
deleting. Synthetic statements only."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import loan_store
from michelito.analysis.loan_schedule import StatementLine
from michelito.web.app import create_app
from tests import live_helpers

WRITE = {"X-Michelito": "1"}
NUMBER = "1234567890"
PAYMENT = "AUT PAGO {number} 101-0000{n} 5555555555"
MONTHS = ("2026-02", "2026-03", "2026-04")
LOAN = {
    "name": "Car loan",
    "number": NUMBER,
    "principal_cents": 10_000_000,
    "rate_bp": 1200,
    "term": 12,
    "start_date": "2026-01-15",
}


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        for index, month in enumerate(MONTHS):
            rows = [
                (f"{month}-05", "LIBRERIA FICTICIA", "500.00"),
                (f"{month}-15", PAYMENT.format(number=NUMBER, n=index), "8884.88"),
            ]
            statement = live_helpers.card_statement(f"{month}-28", rows, period_start=f"{month}-01")
            assert live_helpers.ingest_card(conn, statement) == "parsed"
    return path


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = _database(tmp_path)
    return TestClient(create_app(path, today=lambda: date(2026, 4, 30)), "http://127.0.0.1")


def _rows(client: TestClient, month: str) -> list[dict]:
    return client.get("/api/transactions", params={"month": month}).json()["items"]


def _create(client: TestClient, **extra: object) -> dict:
    created = client.post("/api/loans", json={**LOAN, **extra}, headers=WRITE)
    assert created.status_code == 201, created.text
    return created.json()


def test_creating_a_loan_links_the_earlier_payments_and_computes_the_card(
    client: TestClient,
) -> None:
    loan = _create(client)

    assert len(loan["payments"]) == 3
    assert loan["paid_cents"] == 3 * 888_488
    assert loan["installments_left"] == 9
    assert loan["end_date"] == "2027-01-15"
    assert loan["interest_statements_cents"] == 0
    assert loan["interest_estimated_cents"] > 0
    assert 0 < loan["balance_cents"] < LOAN["principal_cents"]
    assert loan["rate_bp"] == 1200
    assert loan["next_due"] == "2026-05-15"
    assert loan["next_payment_cents"] == 888_488
    assert len(loan["schedule"]) == 12
    assert client.get("/api/loans").json()[0]["id"] == loan["id"]


def test_a_payment_row_says_which_loan_it_pays_and_still_counts_as_spending(
    client: TestClient,
) -> None:
    before = client.get("/api/transactions", params={"month": "2026-03"}).json()["total_cents"]
    loan = _create(client)

    rows = _rows(client, "2026-03")
    (paid,) = [r for r in rows if r["description"].startswith("AUT PAGO")]
    assert paid["loan"] == {"loan_id": loan["id"], "name": "Car loan"}
    after = client.get("/api/transactions", params={"month": "2026-03"}).json()["total_cents"]
    assert after == before


def test_a_new_rate_and_a_real_balance_change_the_projection(client: TestClient) -> None:
    loan = _create(client)

    raised = client.put(
        f"/api/loans/{loan['id']}/rates/2026-04-15", json={"rate_bp": 1800}, headers=WRITE
    ).json()
    assert [r["rate_bp"] for r in raised["rates"]] == [1200, 1800]
    assert raised["next_payment_cents"] > loan["next_payment_cents"]

    corrected = client.put(
        f"/api/loans/{loan['id']}/balances/2026-04-20",
        json={"balance_cents": 2_000_000},
        headers=WRITE,
    ).json()
    assert corrected["balance_cents"] == 2_000_000
    assert corrected["installments_left"] < raised["installments_left"]

    starting = client.delete(f"/api/loans/{loan['id']}/rates/2026-01-15", headers=WRITE)
    assert starting.status_code == 409


def test_a_payment_can_be_unlinked_and_linked_back_by_hand(client: TestClient) -> None:
    loan = _create(client)
    fingerprint = loan["payments"][0]["fingerprint"]

    unlinked = client.delete(
        f"/api/loans/{loan['id']}/transactions/{fingerprint}", headers=WRITE
    ).json()
    assert len(unlinked["payments"]) == 2
    candidates = client.get(f"/api/loans/{loan['id']}/candidates", params={"q": "aut"}).json()
    assert [c["fingerprint"] for c in candidates] == [fingerprint]

    linked = client.put(f"/api/loans/{loan['id']}/transactions/{fingerprint}", headers=WRITE)
    assert linked.status_code == 200
    assert {p["origin"] for p in linked.json()["payments"]} == {"automatic", "confirmed"}


def test_a_second_loan_with_the_same_number_is_refused(client: TestClient) -> None:
    _create(client)

    again = client.post("/api/loans", json=LOAN, headers=WRITE)

    assert again.status_code == 409


def test_deleting_a_loan_frees_its_payments_and_can_be_undone(client: TestClient) -> None:
    loan = _create(client)

    assert client.delete(f"/api/loans/{loan['id']}", headers=WRITE).status_code == 204
    assert client.get("/api/loans").json() == []
    (entry, *_) = client.get("/api/log").json()["items"]
    assert entry["kind"] == "loan"
    undone = client.post(f"/api/log/{entry['id']}/undo", headers=WRITE)
    assert undone.status_code in (200, 201), undone.text
    assert len(client.get("/api/loans").json()[0]["payments"]) == 3


def test_an_unknown_loan_is_a_404(client: TestClient) -> None:
    assert client.get("/api/loans/99/candidates").status_code == 404
    assert client.delete("/api/loans/99", headers=WRITE).status_code == 404


def test_undoing_a_deleted_loan_brings_its_statement_lines_back(
    tmp_path: Path, client: TestClient
) -> None:
    loan = _create(client)
    line = StatementLine(
        date(2026, 2, 15), Decimal("7884.88"), Decimal("1000"), Decimal("92115.12")
    )
    with closing(db.connect(tmp_path / "michelito.db")) as conn, conn:
        loan_store.add_statement_lines(conn, loan["id"], [line], "test", "2026-04-30T00:00:00")

    client.delete(f"/api/loans/{loan['id']}", headers=WRITE)
    (entry, *_) = client.get("/api/log").json()["items"]
    client.post(f"/api/log/{entry['id']}/undo", headers=WRITE)

    (back,) = client.get("/api/loans").json()
    assert back["statement_months"] == 1
    assert back["interest_statements_cents"] == 100_000


def test_the_banks_installment_drives_the_projection(client: TestClient) -> None:
    loan = _create(client, installment_cents=1_000_000)

    assert loan["installment_cents"] == 1_000_000
    assert loan["installments"] == [{"effective": "2026-01-15", "installment_cents": 1_000_000}]
    assert loan["next_payment_cents"] == 1_000_000
    assert loan["end_date"] == "2026-12-15"

    later = client.put(
        f"/api/loans/{loan['id']}/installments/2026-05-01",
        json={"installment_cents": 900_000},
        headers=WRITE,
    ).json()
    assert later["installment_cents"] == 1_000_000  # still the April one today
    assert later["next_payment_cents"] == 900_000  # May's charge is the new one
    assert [i["effective"] for i in later["installments"]] == ["2026-01-15", "2026-05-01"]

    gone = client.delete(f"/api/loans/{loan['id']}/installments/2026-05-01", headers=WRITE)
    assert gone.json()["next_payment_cents"] == 1_000_000


def test_editing_sets_or_clears_the_installment_from_the_start(client: TestClient) -> None:
    loan = _create(client)
    assert loan["installment_cents"] is None
    assert loan["installments"] == []

    path = f"/api/loans/{loan['id']}"
    edited = client.patch(path, json={"installment_cents": 1_000_000}, headers=WRITE).json()
    assert edited["installments"] == [{"effective": "2026-01-15", "installment_cents": 1_000_000}]
    assert edited["end_date"] == "2026-12-15"

    renamed = client.patch(path, json={"name": "Carro"}, headers=WRITE).json()
    assert renamed["installment_cents"] == 1_000_000  # left out: unchanged

    cleared = client.patch(path, json={"installment_cents": None}, headers=WRITE).json()
    assert cleared["installments"] == []
    assert cleared["end_date"] == "2027-01-15"


def test_a_bank_installment_of_zero_is_refused(client: TestClient) -> None:
    loan = _create(client)
    refused = client.put(
        f"/api/loans/{loan['id']}/installments/2026-05-01",
        json={"installment_cents": 0},
        headers=WRITE,
    )
    assert refused.status_code == 422


def test_an_installment_with_no_payment_is_estimated_until_one_is_linked(
    client: TestClient,
) -> None:
    loan = _create(client)
    assert loan["estimates"] == []
    assert loan["estimated_cents"] == 0
    fingerprint = next(p["fingerprint"] for p in loan["payments"] if p["day"] == "2026-03-15")

    unlinked = client.delete(
        f"/api/loans/{loan['id']}/transactions/{fingerprint}", headers=WRITE
    ).json()
    assert unlinked["estimates"] == [
        {"kind": "installment", "day": "2026-03-15", "amount_cents": 888_488}
    ]
    assert unlinked["estimated_cents"] == 888_488
    assert unlinked["paid_cents"] == loan["paid_cents"]  # the estimate counts as paid

    linked = client.put(f"/api/loans/{loan['id']}/transactions/{fingerprint}", headers=WRITE)
    assert linked.json()["estimates"] == []


def test_an_extra_payment_nobody_recorded_squares_the_real_balance(client: TestClient) -> None:
    loan = _create(client)

    corrected = client.put(
        f"/api/loans/{loan['id']}/balances/2026-04-20",
        json={"balance_cents": 5_000_000},
        headers=WRITE,
    ).json()

    (extra,) = corrected["estimates"]
    assert extra["kind"] == "extra"
    assert extra["day"] == "2026-04-20"
    assert extra["amount_cents"] > 2_000_000
    assert corrected["paid_cents"] == 3 * 888_488 + extra["amount_cents"]
