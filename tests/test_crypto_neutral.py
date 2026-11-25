"""Crypto <-> fiat is neutral, like a currency exchange (`.superpowers/sdd/crypto-neutral.md`):
selling or buying crypto is neither income nor spending and leaves what you kept unchanged.
Made-up data from `tests.e2e_server` (the household accounts carry three P2P credits)."""

from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db, dossier
from michelito.analysis import catalog
from michelito.analysis import categories as cat
from michelito.web.app import create_app
from tests.e2e_server import CRYPTO_CREDITS, CRYPTO_TAG, DEMO_TODAY, build_demo_db

JANUARY = "2026-01"
WRITE = {"X-Michelito": "1"}


@pytest.fixture
def path(tmp_path: Path) -> Path:
    found = tmp_path / "demo.db"
    build_demo_db(found, household=True)
    return found


def _client(path: Path) -> TestClient:
    return TestClient(create_app(path, today=lambda: DEMO_TODAY), "http://127.0.0.1")


def _summary(client: TestClient) -> dict:
    return client.get("/api/summary", params={"month": JANUARY}).json()


def test_a_crypto_sale_is_neither_income_nor_what_you_kept(path: Path) -> None:
    client = _client(path)
    before = _summary(client)
    items = client.get(
        "/api/transactions", params={"month": JANUARY, "q": CRYPTO_TAG, "kind": "income"}
    ).json()["items"]
    sale = next(i for i in items if i["description"] == CRYPTO_CREDITS[0][1])
    with closing(db.connect(path)) as conn:
        crypto = catalog.load(conn).by_ref(cat.CRYPTO)
    answer = client.patch(
        f"/api/transactions/{sale['fingerprint']}", json={"category_id": crypto.id}, headers=WRITE
    )
    assert answer.status_code == 200
    assert answer.json()["kind"] == "transfer"
    after = _summary(client)
    sold = 1200000  # RD$ 12,000.00
    assert after["income_cents"] == before["income_cents"] - sold
    # As "other income" it had raised what you kept; as crypto it neither raises nor lowers it.
    assert after["net_cents"] == before["net_cents"] - sold
    assert after["total_cents"] == before["total_cents"]


def test_the_dossier_reports_no_crypto_income(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        crypto = catalog.load(conn).by_ref(cat.CRYPTO)
        assert crypto.kind == "transfer"
        data = dossier.build(conn, JANUARY, accounts=None, holders=()).data
    assert "crypto_income" not in data


def test_schema_31_turns_a_stored_income_crypto_category_neutral(tmp_path: Path) -> None:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 31
        with conn:  # as a schema 30 database had it
            conn.execute("UPDATE categories SET kind = 'income' WHERE builtin_key = 'CRYPTO'")
            conn.execute("PRAGMA user_version = 30")
    with closing(db.connect(path)) as conn:
        kind = conn.execute("SELECT kind FROM categories WHERE builtin_key = 'CRYPTO'").fetchone()
        assert kind[0] == "transfer"
        assert catalog.load(conn).by_ref(cat.CRYPTO).kind == "transfer"


def test_buying_crypto_lowers_neither_spending_nor_what_you_kept(path: Path) -> None:
    """A debit moved to crypto (paying the seller) stops being a third-party transfer: what you
    kept no longer drops by it, and spending stays the same."""
    client = _client(path)
    before = _summary(client)
    items = client.get(
        "/api/transactions", params={"month": JANUARY, "category": cat.THIRD_PARTY}
    ).json()["items"]
    paid = next(i for i in items if i["amount_cents"] > 0 and i["currency"] == "DOP")
    with closing(db.connect(path)) as conn:
        crypto = catalog.load(conn).by_ref(cat.CRYPTO)
    answer = client.patch(
        f"/api/transactions/{paid['fingerprint']}", json={"category_id": crypto.id}, headers=WRITE
    )
    assert answer.status_code == 200
    after = _summary(client)
    assert after["third_party_cents"] == before["third_party_cents"] - paid["amount_cents"]
    assert after["net_cents"] == before["net_cents"] + paid["amount_cents"]
    assert (after["total_cents"], after["income_cents"]) == (
        before["total_cents"],
        before["income_cents"],
    )


def test_a_crypto_debit_is_never_suggested_as_a_payment_an_investment_or_an_exchange() -> None:
    from michelito.analysis import exchanges, investments, ledger_suggest, links, shared
    from tests.test_web_transactions import movement

    bought = movement("2026-01-10", "30000", cat.CRYPTO, "MB A 0000000123", account="bank")
    assert not ledger_suggest.is_payment_debit(bought, links.Links(), ["bank"])
    # Like a currency exchange: never an investment contribution, an exchange leg or a payment
    # received from someone.
    assert cat.CRYPTO in investments.NOT_INVESTMENT
    assert cat.CRYPTO in exchanges.NOT_A_LEG
    assert cat.CRYPTO in shared.NOT_REIMBURSEMENT
