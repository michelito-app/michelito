"""El parámetro `accounts` de las rutas del Resumen y de Transacciones (datos de la demo)."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas.web.app import create_app
from tests.e2e_server import build_demo_db

CARD = "demo:credit_card"  # VISA DEMO ···4242: streaming, gimnasio y la agencia de viajes
INTEREST_CARD = "ficticio:credit_card"  # cobra intereses en enero
CHECKING = "ficticio:checking:777-0"  # nómina, cajero, préstamo, terceros y pago de tarjeta
JANUARY = "2026-01"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    path = Path(tmp_path_factory.mktemp("demo")) / "finanzas.db"
    build_demo_db(path)
    app = create_app(path, today=lambda: date(2026, 2, 12))
    return TestClient(app, "http://127.0.0.1")


def _summary(client: TestClient, accounts: str | None = None, month: str = JANUARY) -> dict:
    params = {"month": month} | ({} if accounts is None else {"accounts": accounts})
    response = client.get("/api/summary", params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/summary", {"month": JANUARY}),
        ("/api/months", {}),
        ("/api/recurring", {"month": JANUARY}),
        ("/api/one-off-suggestions", {"month": JANUARY}),
        ("/api/interest", {"year": 2026}),
        ("/api/transactions", {"month": JANUARY}),
    ],
)
def test_unknown_account_is_rejected(client: TestClient, path: str, params: dict) -> None:
    response = client.get(path, params={**params, "accounts": f"{CARD},no:existe"})
    assert response.status_code == 422
    assert "no:existe" in response.json()["detail"]


def test_empty_or_all_accounts_equal_no_selection(client: TestClient) -> None:
    everything = _summary(client)
    assert _summary(client, "") == everything
    keys = ",".join(a["key"] for a in client.get("/api/accounts").json())
    assert _summary(client, keys) == everything


def test_summary_of_one_card(client: TestClient) -> None:
    everything = _summary(client)
    one = _summary(client, CARD)
    assert 0 < one["total_cents"] < everything["total_cents"]
    assert [a["key"] for a in one["by_account"]] == [CARD]
    assert one["total_cents"] == one["by_account"][0]["total_cents"]
    assert one["income_cents"] == 0
    assert one["net_cents"] is None and one["savings_rate"] is None
    assert one["needs_income"] is True
    assert sum(t["total_cents"] for t in one["trend"]) < sum(
        t["total_cents"] for t in everything["trend"]
    )


def test_checking_alone_keeps_the_card_payment_as_transfer(client: TestClient) -> None:
    result = _summary(client, CHECKING)
    # Cajero (5,000) y préstamo (2,000); el pago de la tarjeta (8,000) no es gasto.
    assert result["total_cents"] == 700_000
    assert result["income_cents"] == 9_700_000
    assert result["third_party_cents"] == 300_000
    assert result["net_cents"] == 9_700_000 - 700_000 - 300_000
    assert (result["to_cards_cents"], result["to_own_cents"]) == (800_000, 0)
    assert _summary(client)["to_cards_cents"] == 0


def test_months_honor_accounts(client: TestClient) -> None:
    everything = client.get("/api/months").json()
    checking = client.get("/api/months", params={"accounts": CHECKING}).json()
    assert [m["month"] for m in checking] == [m["month"] for m in everything]
    # Febrero está en curso para las tarjetas; la cuenta corriente aún no llega a febrero.
    assert checking[0] == {**everything[0], "partial": True}
    assert [m["partial"] for m in checking[1:]] == [False] * (len(checking) - 1)


def test_recurring_only_from_selected_accounts(client: TestClient) -> None:
    def merchants(accounts: str | None) -> set[str]:
        params = {"month": "2026-02"} | ({} if accounts is None else {"accounts": accounts})
        return {i["merchant"] for i in client.get("/api/recurring", params=params).json()["items"]}

    assert "STREAMING FICTICIO" in merchants(None)
    assert "STREAMING FICTICIO" in merchants(CARD)
    assert "STREAMING FICTICIO" not in merchants(CHECKING)


def test_interest_only_from_selected_cards(client: TestClient) -> None:
    def interest(accounts: str) -> dict:
        return client.get("/api/interest", params={"year": 2026, "accounts": accounts}).json()

    with_interest = interest(INTEREST_CARD)
    assert [line["key"] for line in with_interest["lines"]] == [INTEREST_CARD]
    other = interest(CARD)
    assert other["lines"] == [] and other["total_dop_cents"] == 0
    assert other["next_due"] is None or other["next_due"]["key"] == CARD


def test_one_off_suggestions_only_from_selected_accounts(client: TestClient) -> None:
    def merchants(accounts: str | None) -> list[str]:
        params = {"month": "2026-02"} | ({} if accounts is None else {"accounts": accounts})
        return [s["merchant"] for s in client.get("/api/one-off-suggestions", params=params).json()]

    assert merchants(None) == merchants(CARD) != []
    assert merchants(CHECKING) == []


def test_transactions_filter_by_several_accounts(client: TestClient) -> None:
    def keys(**params: str) -> set[str]:
        body = client.get("/api/transactions", params={"month": JANUARY, **params}).json()
        return {i["account"] for i in body["items"]}

    assert keys(accounts=f"{CARD},{CHECKING}") == {CARD, CHECKING}
    assert keys(account=CHECKING) == {CHECKING}  # el parámetro de una sola cuenta sigue
    assert keys(account=CHECKING, accounts=f"{CARD},{CHECKING}") == {CHECKING}
    assert len(keys()) > 2


def test_transactions_totals_match_the_summary_of_the_selection(client: TestClient) -> None:
    body = client.get(
        "/api/transactions", params={"month": JANUARY, "accounts": CARD, "kind": "gasto"}
    ).json()
    assert body["total_cents"] == _summary(client, CARD)["total_cents"]
