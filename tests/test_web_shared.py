"""Gastos compartidos y reembolsos desde la API: reparto, enlaces, Resumen y validación."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.analysis import rates
from finanzas.web.app import create_app
from tests.test_spending import _add_bank_rows, seed

WRITE = {"X-Finanzas": "1"}
MONTH = "2026-01"
CARD = "popular:credit_card"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "finanzas.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-04", "TOKE DE PEDRO INVENTADO", "credit", "10000"),
                ("2026-01-06", "TOKE DE LUISA INVENTADA", "credit", "5000"),
            ],
        )
        with conn:
            rates.store_bcrd(conn, {"2025-12": Decimal("60"), "2026-01": Decimal("60")})
    return path


@pytest.fixture
def client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")


def _items(client: TestClient, month: str = MONTH, **params) -> list[dict]:
    return client.get("/api/transactions", params={"month": month, **params}).json()["items"]


def _tx(client: TestClient, text: str, month: str = MONTH) -> dict:
    return next(i for i in _items(client, month) if i["description"].startswith(text))


def _patch(client: TestClient, fp: str, body: dict):
    return client.patch(f"/api/transactions/{fp}", json=body, headers=WRITE)


def _link(client: TestClient, expense: str, credit: str):
    return client.post(
        f"/api/transactions/{expense}/reimbursements", json={"credit": credit}, headers=WRITE
    )


def _summary(client: TestClient, **params) -> dict:
    return client.get("/api/summary", params={"month": MONTH, **params}).json()


def test_marking_shared_counts_your_part_and_shows_what_they_owe(client: TestClient) -> None:
    before = _summary(client)
    cafe = _tx(client, "CAFE FICTICIO")
    response = _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    assert response.status_code == 200
    body = response.json()
    assert (body["link"], body["amount_cents"], body["gross_cents"]) == ("shared", 10000, 30000)
    assert body["pending_cents"] == 20000
    assert body["shared"]["pending"] == [{"currency": "DOP", "cents": 20000}]
    assert body["shared"]["expense_count"] == 1
    after = _summary(client)
    assert after["total_cents"] == before["total_cents"] - 20000
    assert after["owed_cents"] == 20000
    assert before["owed_cents"] == 0


def test_linking_a_credit_takes_it_out_of_income(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    toke = _tx(client, "TOKE DE PEDRO")
    assert toke["suggested_group"]["first_fingerprint"] == cafe["fingerprint"]
    income = _summary(client)["income_cents"]

    response = _link(client, cafe["fingerprint"], toke["fingerprint"])
    assert response.status_code == 200
    shared = response.json()["shared"]
    [total] = shared["totals"]
    assert (total["reimbursed_cents"], total["pending_cents"]) == (10000, 10000)
    assert [r["fingerprint"] for r in shared["reimbursements"]] == [toke["fingerprint"]]
    linked = _tx(client, "TOKE DE PEDRO")
    assert (linked["link"], linked["kind"], linked["category"]) == (
        "reimbursement",
        "transferencia",
        "Reembolso",
    )
    assert linked["reimbursement_of"]["merchant"] == cafe["merchant"]
    assert linked["suggested_group"] is None
    assert linked["shared"]["id"] == shared["id"]  # el grupo, también desde el crédito
    summary = _summary(client)
    assert summary["income_cents"] == income - 10000
    assert summary["owed_cents"] == 10000


def test_a_credit_links_to_one_expense_only(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    farmacia = _tx(client, "FARMACIA")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    _patch(client, farmacia["fingerprint"], {"shared": {"people": 2}})
    toke = _tx(client, "TOKE DE PEDRO")
    assert _link(client, cafe["fingerprint"], toke["fingerprint"]).status_code == 200
    again = _link(client, farmacia["fingerprint"], toke["fingerprint"])
    assert again.status_code == 409  # ya enlazado
    assert _tx(client, "TOKE DE PEDRO")["reimbursement_of"]["fingerprint"] == cafe["fingerprint"]


def test_candidates_for_an_expense_and_for_a_credit(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    found = client.get(f"/api/transactions/{cafe['fingerprint']}/reimbursement-candidates").json()
    assert [c["merchant"] for c in found["credits"]] == [
        "TOKE DE PEDRO INVENTADO",
        "TOKE DE LUISA INVENTADA",
    ]
    assert all("primary" in c for c in found["credits"])
    assert found["groups"] == []
    toke = _tx(client, "TOKE DE LUISA")
    picker = client.get(f"/api/transactions/{toke['fingerprint']}/reimbursement-candidates")
    [group] = picker.json()["groups"]
    assert (group["first_fingerprint"], group["primary"]) == (cafe["fingerprint"], True)


def test_one_transaction_with_its_links(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    one = client.get(f"/api/transactions/{cafe['fingerprint']}")
    assert one.status_code == 200
    assert one.json() == _tx(client, "CAFE FICTICIO")  # la misma fila que la lista
    assert one.json()["shared"] is not None
    assert client.get("/api/transactions/no-existe").status_code == 404


def test_written_off_and_unmarking(client: TestClient) -> None:
    before = _summary(client)
    cafe = _tx(client, "CAFE FICTICIO")
    toke = _tx(client, "TOKE DE PEDRO")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    _link(client, cafe["fingerprint"], toke["fingerprint"])
    written = _patch(client, cafe["fingerprint"], {"written_off": True}).json()
    assert (written["amount_cents"], written["pending_cents"]) == (20000, 0)
    assert _summary(client)["owed_cents"] == 0

    gone = _patch(client, cafe["fingerprint"], {"shared": None}).json()
    assert (gone["link"], gone["amount_cents"], gone["shared"]) == ("", 30000, None)
    assert _tx(client, "TOKE DE PEDRO")["kind"] == "ingreso"
    after = _summary(client)
    for key in ("total_cents", "income_cents", "net_cents", "owed_cents", "categories"):
        assert after[key] == before[key]


def test_manual_reimbursements_in_cash_or_another_account(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    _patch(client, cafe["fingerprint"], {"shared": {"for_other": True, "with_whom": "Ana"}})
    path = f"/api/transactions/{cafe['fingerprint']}/reimbursements"
    body = {"manual": {"amount_cents": 5000, "day": "2026-01-02", "person": "Ana"}}
    first = client.post(path, json=body, headers=WRITE).json()["shared"]
    assert (first["with_whom"], first["title"], first["expenses"][0]["share_cents"]) == (
        "Ana",
        "Ana",
        0,
    )
    assert first["pending"] == [{"currency": "DOP", "cents": 25000}]
    other = {"amount_cents": 5000, "day": "2026-01-03", "place": "Banreservas"}
    second = client.post(path, json={"manual": other}, headers=WRITE).json()["shared"]
    assert [(m["place"], m["currency"]) for m in second["manual"]] == [
        ("", "DOP"),
        ("Banreservas", "DOP"),
    ]
    places = client.get(f"/api/transactions/{cafe['fingerprint']}/reimbursement-candidates")
    assert places.json()["places"] == ["Banreservas"]
    entry = second["manual"][0]["id"]
    removed = client.delete(f"{path}/manual/{entry}", headers=WRITE).json()["shared"]
    assert [m["place"] for m in removed["manual"]] == ["Banreservas"]
    # Ningún reembolso a mano es ingreso.
    assert _summary(client)["income_cents"] == _summary(client)["income_cents"]


def test_unlink_one_credit(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    toke = _tx(client, "TOKE DE PEDRO")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    _link(client, cafe["fingerprint"], toke["fingerprint"])
    response = client.delete(
        f"/api/transactions/{cafe['fingerprint']}/reimbursements/{toke['fingerprint']}",
        headers=WRITE,
    )
    assert response.json()["shared"]["reimbursements"] == []
    assert _tx(client, "TOKE DE PEDRO")["kind"] == "ingreso"


@pytest.mark.parametrize(
    "shared",
    [
        {"people": 1},
        {"my_share_cents": 0},
        {"my_share_cents": 30001},
        {},
        {"people": 2, "my_share_cents": 100},
    ],
)
def test_bad_shares_are_422(client: TestClient, shared: dict) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    assert _patch(client, cafe["fingerprint"], {"shared": shared}).status_code == 422
    assert _tx(client, "CAFE FICTICIO")["link"] == ""


def test_only_an_expense_can_be_shared_and_writes_need_the_header(client: TestClient) -> None:
    toke = _tx(client, "TOKE DE PEDRO")
    assert _patch(client, toke["fingerprint"], {"shared": {"people": 2}}).status_code == 422
    cafe = _tx(client, "CAFE FICTICIO")
    denied = client.patch(
        f"/api/transactions/{cafe['fingerprint']}", json={"shared": {"people": 2}}
    )
    assert denied.status_code == 403
    no_header = client.post(
        f"/api/transactions/{cafe['fingerprint']}/reimbursements", json={"credit": "x"}
    )
    assert no_header.status_code == 403
    assert _patch(client, cafe["fingerprint"], {"written_off": True}).status_code == 422


def test_filter_shared_with_pending(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    farmacia = _tx(client, "FARMACIA")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    _patch(client, farmacia["fingerprint"], {"shared": {"people": 2}})
    _patch(client, farmacia["fingerprint"], {"written_off": True})
    pending = _items(client, shared="pending")
    assert [i["fingerprint"] for i in pending] == [cafe["fingerprint"]]
    assert len(_items(client, shared="shared")) == 2
    assert client.get("/api/transactions", params={"shared": "bogus"}).status_code == 422


def test_owed_honours_the_account_selection(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    assert _summary(client, accounts=CARD)["owed_cents"] == 20000
    assert _summary(client, accounts="bhd:credit_card")["owed_cents"] == 0


def test_usd_expense_owed_is_converted_with_the_month_rate(client: TestClient) -> None:
    store = _tx(client, "TIENDA ONLINE SEATTLE-US")  # US$ 30 en la BHD
    shared = _patch(client, store["fingerprint"], {"shared": {"my_share_cents": 1000}}).json()
    assert (shared["amount_cents"], shared["pending_cents"]) == (1000, 2000)
    assert _summary(client)["owed_cents"] == 2000 * 60


def test_nothing_shared_leaves_the_card_only_numbers_alone(client: TestClient) -> None:
    keys = ("total_cents", "categories", "trend", "by_account", "habitual_cents", "owed_cents")
    card_only = {k: _summary(client, accounts=CARD)[k] for k in keys}
    everything = {k: _summary(client)[k] for k in keys}
    cafe = _tx(client, "CAFE FICTICIO")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    _patch(client, cafe["fingerprint"], {"shared": None})
    assert {k: _summary(client, accounts=CARD)[k] for k in keys} == card_only
    assert {k: _summary(client)[k] for k in keys} == everything


def _shared_with_toke(client: TestClient) -> tuple[dict, dict]:
    cafe = _tx(client, "CAFE FICTICIO")
    toke = _tx(client, "TOKE DE PEDRO")
    _patch(client, cafe["fingerprint"], {"shared": {"people": 3}})
    _link(client, cafe["fingerprint"], toke["fingerprint"])
    return cafe, toke


def test_expense_turned_into_a_transfer_keeps_its_credit_linked(client: TestClient) -> None:
    cafe, toke = _shared_with_toke(client)
    moved = _patch(client, cafe["fingerprint"], {"category": "Entre mis cuentas"}).json()
    # Dormido: el gasto ya no es gasto, no se reparte, pero el vínculo sigue guardado.
    assert (moved["link"], moved["shared"], moved["amount_cents"]) == ("shared", None, 30000)
    assert moved["link_id"] is not None
    dormant = _tx(client, "TOKE DE PEDRO")
    assert (dormant["link"], dormant["category"], dormant["kind"]) == (
        "reimbursement",
        "Reembolso",
        "transferencia",
    )
    assert dormant["reimbursement_of"]["fingerprint"] == cafe["fingerprint"]
    assert dormant["can_reimburse"] is False
    gone = client.delete(f"/api/reimbursements/{toke['fingerprint']}", headers=WRITE)
    assert gone.status_code == 204
    assert _tx(client, "TOKE DE PEDRO")["link"] == ""
    assert (
        client.delete(f"/api/reimbursements/{toke['fingerprint']}", headers=WRITE).status_code
        == 404
    )


def test_expense_missing_after_reprocessing_keeps_its_credit_linked(
    client: TestClient, db_path: Path
) -> None:
    cafe, toke = _shared_with_toke(client)
    with closing(db.connect(db_path)) as conn, conn:  # el estado volvió sin esa fila
        conn.execute("DELETE FROM transactions WHERE description LIKE 'CAFE FICTICIO%'")
    dormant = _tx(client, "TOKE DE PEDRO")
    assert (dormant["link"], dormant["category"], dormant["reimbursement_of"]) == (
        "reimbursement",
        "Reembolso",
        None,
    )
    assert _summary(client)["owed_cents"] == 0
    gone = client.delete(f"/api/reimbursements/{toke['fingerprint']}", headers=WRITE)
    assert gone.status_code == 204
    assert _tx(client, "TOKE DE PEDRO")["kind"] == "ingreso"


def test_manual_entry_cannot_be_before_the_expense(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")  # 1 de enero
    _patch(client, cafe["fingerprint"], {"shared": {"people": 2}})
    early = {"manual": {"amount_cents": 1000, "day": "2025-12-31"}}
    path = f"/api/transactions/{cafe['fingerprint']}/reimbursements"
    assert client.post(path, json=early, headers=WRITE).status_code == 422
    same_day = {"manual": {"amount_cents": 1000, "day": "2026-01-01"}}
    assert client.post(path, json=same_day, headers=WRITE).status_code == 200


def test_reimbursed_beyond_what_was_owed_is_capped(client: TestClient) -> None:
    cafe, _ = _shared_with_toke(client)  # te deben RD$ 200; el TOKE devolvió RD$ 100
    path = f"/api/transactions/{cafe['fingerprint']}/reimbursements"
    extra = {"manual": {"amount_cents": 15000, "day": "2026-01-02"}}
    shared = client.post(path, json=extra, headers=WRITE).json()["shared"]
    [total] = shared["totals"]
    assert (total["reimbursed_cents"], total["pending_cents"]) == (20000, 0)
    assert shared["excess"] == [{"currency": "DOP", "cents": 5000}]
    [expense] = shared["expenses"]
    assert expense["counted_cents"] == expense["share_cents"] == 10000  # tu parte no baja


def test_row_flags_follow_the_server_rules(client: TestClient) -> None:
    cafe = _tx(client, "CAFE FICTICIO")
    toke = _tx(client, "TOKE DE PEDRO")
    payment = _tx(client, "PAGO DE TC")  # pago de tarjeta: nunca reembolso
    assert (cafe["can_share"], cafe["can_reimburse"]) == (True, False)
    assert (toke["can_share"], toke["can_reimburse"]) == (False, True)
    assert payment["can_reimburse"] is False


def test_a_dollar_expense_reimbursed_in_pesos(client: TestClient, db_path: Path) -> None:
    """Pagaste en US$ y te devuelven en pesos meses después: cuenta a la tasa del mes."""
    with closing(db.connect(db_path)) as conn:
        # RD$ 600 el 10 de febrero (sin tasa de febrero: usa la de enero, 60) = US$ 10.
        _add_bank_rows(conn, [("2026-02-10", "TOKE DE ANA INVENTADA", "credit", "60000")])
    shop = _tx(client, "TIENDA ONLINE SEATTLE-US")
    assert shop["currency"] == "USD"
    _patch(client, shop["fingerprint"], {"shared": {"for_other": True}})
    ana = _tx(client, "TOKE DE ANA", "2026-02")
    assert ana["suggested_group"] is None  # otra moneda y sin «Con quién»: no se sugiere

    found = client.get(f"/api/transactions/{shop['fingerprint']}/reimbursement-candidates")
    credits = {c["merchant"]: c for c in found.json()["credits"]}
    assert (
        credits["TOKE DE ANA INVENTADA"]["converted_cents"],
        credits["TOKE DE ANA INVENTADA"]["converted_currency"],
    ) == (1000, "USD")
    picker = client.get(f"/api/transactions/{ana['fingerprint']}/reimbursement-candidates")
    assert [g["first_fingerprint"] for g in picker.json()["groups"]] == [shop["fingerprint"]]

    response = _link(client, shop["fingerprint"], ana["fingerprint"])
    assert response.status_code == 200
    shared = response.json()["shared"]
    [total] = shared["totals"]
    assert (total["reimbursed_cents"], total["pending_cents"]) == (1000, 2000)
    [linked] = shared["reimbursements"]
    assert (linked["amount_cents"], linked["currency"]) == (-60000, "DOP")
    assert (linked["converted_cents"], linked["converted_currency"]) == (1000, "USD")
    assert _tx(client, "TOKE DE ANA", "2026-02")["category"] == "Reembolso"


def test_other_currency_credit_needs_a_rate(client: TestClient, db_path: Path) -> None:
    with closing(db.connect(db_path)) as conn:
        _add_bank_rows(conn, [("2026-02-10", "TOKE DE ANA INVENTADA", "credit", "60000")])
        with conn:
            conn.execute("DELETE FROM exchange_rates")
    shop = _tx(client, "TIENDA ONLINE SEATTLE-US")
    _patch(client, shop["fingerprint"], {"shared": {"for_other": True}})
    ana = _tx(client, "TOKE DE ANA", "2026-02")
    found = client.get(f"/api/transactions/{shop['fingerprint']}/reimbursement-candidates")
    assert "TOKE DE ANA INVENTADA" not in [c["merchant"] for c in found.json()["credits"]]
    response = _link(client, shop["fingerprint"], ana["fingerprint"])
    assert response.status_code == 422
    assert "tasa" in response.json()["detail"]
