"""Cambios de divisas desde la API: crear, agregar y quitar patas, tasa, cerrar y Resumen."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.analysis import rates
from finanzas.parsers.common import Section, Statement, Transaction
from finanzas.web.app import create_app
from tests.helpers import store
from tests.test_spending import seed

WRITE = {"X-Finanzas": "1"}
MONTH = "2026-01"
PESOS = "ficticio:checking:111-1"
DOLLARS = "ficticio:savings:222-2"


def _row(day: str, text: str, amount: str, direction: str, currency: str) -> Transaction:
    when = date.fromisoformat(day)
    return Transaction(when, when, text, Decimal(amount), direction, currency, None, None, text)


def _bank(kind: str, identifier: str, currency: str, rows: tuple[Transaction, ...]) -> Statement:
    debits = sum((t.amount for t in rows if t.direction == "debit"), Decimal(0))
    credits = sum((t.amount for t in rows if t.direction == "credit"), Decimal(0))
    opening = Decimal("100000.00")
    section = Section(
        currency=currency,
        previous_balance=opening,
        closing_balance=opening + credits - debits,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=debits,
        printed_credits=credits,
        transactions=rows,
    )
    return Statement(
        parser="demo",
        institution="ficticio",
        kind=kind,
        product="Cuenta",
        identifier=identifier,
        period_end=date(2026, 1, 31),
        due_date=None,
        sections=(section,),
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "finanzas.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        store(
            conn,
            _bank(
                "checking",
                "111-1",
                "DOP",
                (
                    _row("2026-01-12", "DEPOSITO CAMBIO FICTICIO", "63700.00", "credit", "DOP"),
                    _row("2026-01-20", "DEPOSITO CAMBIO FICTICIO", "31850.00", "credit", "DOP"),
                ),
            ),
        )
        store(
            conn,
            _bank(
                "savings",
                "222-2",
                "USD",
                (
                    _row(
                        "2026-01-13", "TRANSFERENCIA A PERSONA FICTICIA", "1000.00", "debit", "USD"
                    ),
                ),
            ),
        )
        with conn:
            rates.store_bcrd(conn, {"2026-01": Decimal("63.70")})
    return path


@pytest.fixture
def client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")


def _items(client: TestClient, **params) -> list[dict]:
    return client.get("/api/transactions", params={"month": MONTH, **params}).json()["items"]


def _tx(client: TestClient, text: str, cents: int | None = None) -> dict:
    return next(
        i
        for i in _items(client)
        if i["description"].startswith(text) and (cents is None or abs(i["amount_cents"]) == cents)
    )


def _summary(client: TestClient, **params) -> dict:
    return client.get("/api/summary", params={"month": MONTH, **params}).json()


def _create(client: TestClient, *fingerprints: str, rate: str | None = None):
    body: dict = {"fingerprints": list(fingerprints)}
    if rate is not None:
        body["agreed_rate"] = rate
    return client.post("/api/exchanges", json=body, headers=WRITE)


def test_suggested_and_linked_across_accounts(client: TestClient) -> None:
    deposit = _tx(client, "DEPOSITO CAMBIO", 6370000)
    sent = _tx(client, "TRANSFERENCIA A PERSONA")
    assert deposit["suggested_exchange_with"]["fingerprint"] == sent["fingerprint"]
    before = _summary(client)
    options = client.get(f"/api/transactions/{deposit['fingerprint']}/exchange-candidates").json()
    assert [o["fingerprint"] for o in options] == [sent["fingerprint"]]
    assert options[0]["primary"] is True  # a la tasa del mes (63.70)

    response = _create(client, deposit["fingerprint"], sent["fingerprint"])
    assert response.status_code == 201
    exchange = response.json()
    assert (exchange["base"], exchange["rate"], exchange["pending_cents"]) == ("DOP", "63.7000", 0)
    linked = _tx(client, "DEPOSITO CAMBIO", 6370000)
    assert (linked["link"], linked["category"], linked["kind"]) == (
        "exchange",
        "Cambio de divisas",
        "transferencia",
    )
    assert linked["suggested_exchange_with"] is None
    after = _summary(client)
    assert after["income_cents"] == before["income_cents"] - 6370000
    assert after["third_party_cents"] == before["third_party_cents"] - 6370000
    assert after["net_cents"] == before["net_cents"]  # "Te quedó" no cambia
    assert after["exchanges_pending_cents"] == 0


def test_partial_pending_agreed_rate_more_legs_and_close(client: TestClient) -> None:
    deposit = _tx(client, "DEPOSITO CAMBIO", 6370000)
    sent = _tx(client, "TRANSFERENCIA A PERSONA")
    second = _tx(client, "DEPOSITO CAMBIO", 3185000)
    # El depósito del 12 es la base. RD$ 63,700 a 60 son US$ 1,061.67; salieron US$ 1,000.
    made = _create(client, deposit["fingerprint"], sent["fingerprint"], rate="60").json()
    assert (made["agreed_rate"], made["implied_rate"], made["pending_cents"]) == (
        "60.0000",
        "63.7000",
        6167,
    )
    ident = made["id"]
    # Faltan US$ 61.67 de vuelta y no hay otro envío en US$: nada. El otro depósito en pesos es
    # del lado base y no se ofrece mientras haya pendiente.
    legs = client.get(f"/api/transactions/{deposit['fingerprint']}/exchange-candidates").json()
    assert legs == []
    more = client.post(
        f"/api/exchanges/{ident}/legs",
        json={"fingerprints": [second["fingerprint"]]},
        headers=WRITE,
    ).json()
    # RD$ 95,550 a 60 = US$ 1,592.50: faltan US$ 592.50 ≈ RD$ 35,550.
    assert (more["pending_cents"], more["pending_currency"], more["pending_dop_cents"]) == (
        59250,
        "USD",
        3555000,
    )
    assert _summary(client)["exchanges_pending_cents"] == 3555000
    assert _summary(client, accounts=PESOS)["exchanges_pending_cents"] == 3555000
    assert _summary(client, accounts="popular:credit_card")["exchanges_pending_cents"] == 0

    implied = client.patch(f"/api/exchanges/{ident}", json={"agreed_rate": None}, headers=WRITE)
    # A la implícita (63.70): US$ 1,500 menos US$ 1,000.
    assert (implied.json()["rate"], implied.json()["pending_cents"]) == ("63.7000", 50000)
    closed = client.patch(f"/api/exchanges/{ident}", json={"closed": True}, headers=WRITE).json()
    assert (closed["closed"], closed["pending_cents"]) == (True, 0)
    # Cerrado: sin pendiente, nada es primario.
    legs = client.get(f"/api/transactions/{deposit['fingerprint']}/exchange-candidates").json()
    assert not any(o["primary"] for o in legs)


def test_unlinking_a_leg_and_dissolving(client: TestClient) -> None:
    deposit = _tx(client, "DEPOSITO CAMBIO", 6370000)
    sent = _tx(client, "TRANSFERENCIA A PERSONA")
    second = _tx(client, "DEPOSITO CAMBIO", 3185000)
    ident = _create(client, deposit["fingerprint"], sent["fingerprint"], second["fingerprint"])
    ident = ident.json()["id"]
    one = client.delete(f"/api/exchanges/{ident}/legs/{second['fingerprint']}", headers=WRITE)
    assert one.status_code == 200
    assert len(one.json()["legs"]) == 2
    assert _tx(client, "DEPOSITO CAMBIO", 3185000)["link"] == ""
    gone = client.delete(f"/api/exchanges/{ident}/legs/{sent['fingerprint']}", headers=WRITE)
    assert gone.status_code == 204
    assert _tx(client, "DEPOSITO CAMBIO", 6370000)["category"] == "Otros ingresos"


def test_invalid_exchanges(client: TestClient) -> None:
    deposit = _tx(client, "DEPOSITO CAMBIO", 6370000)
    second = _tx(client, "DEPOSITO CAMBIO", 3185000)
    sent = _tx(client, "TRANSFERENCIA A PERSONA")
    card = _tx(client, "TIENDA ONLINE SEATTLE-US")  # US$ en tarjeta
    assert _create(client, deposit["fingerprint"], second["fingerprint"]).status_code == 422
    assert _create(client, deposit["fingerprint"], card["fingerprint"]).status_code == 422
    assert _create(client, deposit["fingerprint"], "nope").status_code == 404
    assert _create(client, deposit["fingerprint"], sent["fingerprint"], rate="0").status_code == 422
    assert _create(client, deposit["fingerprint"], sent["fingerprint"]).status_code == 201
    again = _create(client, second["fingerprint"], sent["fingerprint"])
    assert again.status_code == 409  # ya en otro cambio
    denied = client.post("/api/exchanges", json={"fingerprints": [deposit["fingerprint"]]})
    assert denied.status_code == 403
    assert (
        client.patch("/api/exchanges/999", json={"closed": True}, headers=WRITE).status_code == 404
    )


def test_an_exchange_survives_reprocessing(client: TestClient, db_path: Path) -> None:
    deposit = _tx(client, "DEPOSITO CAMBIO", 6370000)
    sent = _tx(client, "TRANSFERENCIA A PERSONA")
    _create(client, deposit["fingerprint"], sent["fingerprint"])
    with closing(db.connect(db_path)) as conn, conn:  # como parse --retry: filas nuevas
        conn.execute("UPDATE transactions SET id = id + 100000")
    assert (
        _tx(client, "TRANSFERENCIA A PERSONA")["exchange"]["legs"][0]["fingerprint"]
        == (deposit["fingerprint"])
    )


def test_card_only_numbers_do_not_move_with_an_exchange(client: TestClient) -> None:
    keys = ("total_cents", "categories", "trend", "by_account", "income_cents", "net_cents")
    cards = "popular:credit_card,bhd:credit_card"
    before = {k: _summary(client, accounts=cards)[k] for k in keys}
    deposit = _tx(client, "DEPOSITO CAMBIO", 6370000)
    sent = _tx(client, "TRANSFERENCIA A PERSONA")
    _create(client, deposit["fingerprint"], sent["fingerprint"])
    assert {k: _summary(client, accounts=cards)[k] for k in keys} == before
    assert _summary(client)["total_cents"] == _summary(client, accounts=None)["total_cents"]


def test_an_exchange_missing_a_leg_stays_linked_and_can_be_undone(
    client: TestClient, db_path: Path
) -> None:
    deposit = _tx(client, "DEPOSITO CAMBIO", 6370000)
    sent = _tx(client, "TRANSFERENCIA A PERSONA")
    ident = _create(client, deposit["fingerprint"], sent["fingerprint"]).json()["id"]
    with closing(db.connect(db_path)) as conn, conn:  # el estado volvió sin el envío
        conn.execute("DELETE FROM transactions WHERE description LIKE 'TRANSFERENCIA A PERSONA%'")
    dormant = _tx(client, "DEPOSITO CAMBIO", 6370000)
    assert (dormant["link"], dormant["link_id"], dormant["exchange"]) == ("exchange", ident, None)
    assert (dormant["category"], dormant["kind"]) == ("Cambio de divisas", "transferencia")
    # Quitar la pata que queda deshace el cambio, sin buscar la que falta.
    gone = client.delete(f"/api/exchanges/{ident}/legs/{deposit['fingerprint']}", headers=WRITE)
    assert gone.status_code == 204
    assert _tx(client, "DEPOSITO CAMBIO", 6370000)["kind"] == "ingreso"


def test_deleting_a_dormant_or_unknown_exchange(client: TestClient, db_path: Path) -> None:
    deposit = _tx(client, "DEPOSITO CAMBIO", 6370000)
    sent = _tx(client, "TRANSFERENCIA A PERSONA")
    ident = _create(client, deposit["fingerprint"], sent["fingerprint"]).json()["id"]
    with closing(db.connect(db_path)) as conn, conn:
        conn.execute("DELETE FROM transactions WHERE description LIKE 'TRANSFERENCIA A PERSONA%'")
    assert client.delete(f"/api/exchanges/{ident}", headers=WRITE).status_code == 204
    assert _tx(client, "DEPOSITO CAMBIO", 6370000)["link"] == ""
    assert client.delete(f"/api/exchanges/{ident}", headers=WRITE).status_code == 404
    assert client.delete("/api/exchanges/999/legs/x", headers=WRITE).status_code == 404


def test_first_pair_without_agreed_rate_asks_for_it(client: TestClient) -> None:
    deposit = _tx(client, "DEPOSITO CAMBIO", 6370000)
    sent = _tx(client, "TRANSFERENCIA A PERSONA")
    second = _tx(client, "DEPOSITO CAMBIO", 3185000)
    made = _create(client, deposit["fingerprint"], sent["fingerprint"]).json()
    assert made["needs_agreed_rate"] is True
    ident = made["id"]
    agreed = client.patch(f"/api/exchanges/{ident}", json={"agreed_rate": "60"}, headers=WRITE)
    assert agreed.json()["needs_agreed_rate"] is False
    client.patch(f"/api/exchanges/{ident}", json={"agreed_rate": None}, headers=WRITE)
    more = client.post(
        f"/api/exchanges/{ident}/legs",
        json={"fingerprints": [second["fingerprint"]]},
        headers=WRITE,
    )
    assert more.json()["needs_agreed_rate"] is False  # ya hay más que el primer par


def test_dollar_account_movements_appear_with_their_key(client: TestClient) -> None:
    keys = {i["account"] for i in _items(client)}
    assert {PESOS, DOLLARS} <= keys
