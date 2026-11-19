from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.analysis import providers, rates, recurring_marks, spending
from finanzas.web.app import create_app
from finanzas.web.recurring import build_overview
from tests.e2e_server import (
    ANNUAL_TAX,
    CRYPTO_CREDITS,
    CRYPTO_TAG,
    DEMO_PROVIDERS,
    DEMO_TODAY,
    HOME_LOAN,
    RENT,
    WATER,
    build_demo_db,
)


def test_demo_db_has_household_recurring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers, "PROVIDERS", (*providers.PROVIDERS, *DEMO_PROVIDERS))
    path = tmp_path / "demo.db"
    build_demo_db(path, household=True)
    client = TestClient(create_app(path), "http://127.0.0.1")
    body = client.get("/api/recurring").json()
    items = {i["name"]: i for i in body["items"]}
    phone = items["Telefónica Ficticia"]
    assert phone["members"] == ["TELFIC IBANKING", "TELFIC P", "TELFIC PAGO", "TELFIC WB"]
    assert (phone["group"], phone["charges"], phone["typical_cents"]) == ("Servicios", 3, 150000)
    assert (items[RENT]["group"], items[WATER]["group"]) == ("Vivienda", "Servicios")
    loan = items[HOME_LOAN]
    assert (loan["group"], loan["typical_cents"], loan["extras_year_cents"]) == (
        "Préstamos",
        1200000,
        3000000,
    )
    assert [g["group"] for g in body["groups"]][:3] == ["Vivienda", "Préstamos", "Servicios"]
    assert "SEGURO HOGAR" not in items


def test_household_demo_has_crypto_credits_in_other_income(tmp_path: Path) -> None:
    path = tmp_path / "demo.db"
    build_demo_db(path, household=True)
    client = TestClient(create_app(path), "http://127.0.0.1")
    params = {"month": "2026-01", "kind": "ingreso", "q": CRYPTO_TAG}
    items = client.get("/api/transactions", params=params).json()["items"]
    assert sorted(i["description"] for i in items) == sorted(t for _, t, _ in CRYPTO_CREDITS)
    assert {i["category"] for i in items} == {"Otros ingresos"}
    assert sum(i["amount_cents"] for i in items) == -4_050_000


CHECKING = "ficticio:checking:777-0"


def test_demo_db_has_a_partial_newest_month_and_a_complete_one(tmp_path: Path) -> None:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    client = TestClient(create_app(path), "http://127.0.0.1")

    months = client.get("/api/months").json()

    assert months[0]["partial"] is True
    assert any(not m["partial"] for m in months)
    summary = client.get("/api/summary", params={"month": months[0]["month"]}).json()
    assert any(not c["complete"] for c in summary["coverage"])
    assert summary["rate"] is not None


def test_demo_db_has_recurring(tmp_path: Path) -> None:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    with closing(db.connect(path)) as conn:
        movements = spending.load_movements(conn)
        overview = build_overview(
            movements, recurring_marks.load(conn), rates.load(conn), "2026-02"
        )

    items = {i.merchant: i for i in overview.items}
    streaming, gym = items["STREAMING FICTICIO"], items["GIMNASIO FICTICIO"]
    assert streaming.currency == "USD"
    assert streaming.group == "Suscripciones"
    change = streaming.price_change
    assert change is not None
    assert change.before == Decimal("9.99")
    assert change.after == Decimal("11.99")
    assert change.day.strftime("%Y-%m") == "2026-02"
    assert (gym.currency, gym.typical, gym.category) == ("DOP", Decimal("2500"), "Otros")
    rises = [a for a in overview.alerts if a.kind == "subio" and a.merchant == "STREAMING FICTICIO"]
    assert [a.detail for a in rises] == ["Subió de US$ 9.99 a US$ 11.99"]
    # El aviso lleva la huella del primer cobro con el precio nuevo (para «Para revisar»).
    charged = next(m for m in movements if m.fingerprint == rises[0].fingerprint)
    assert (charged.day.isoformat(), charged.amount) == ("2026-02-05", Decimal("11.99"))


def test_demo_db_has_a_partly_paid_cut_with_interest(tmp_path: Path) -> None:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    client = TestClient(create_app(path), "http://127.0.0.1")

    card = next(a for a in client.get("/api/accounts").json() if a["key"] == "ficticio:credit_card")
    newest, partly, full = card["statements"]

    assert newest["paid_full"] is None
    assert newest["due_date"] > "2026-02-10"  # posterior al dato más nuevo de la demo
    assert card["to_pay"]["amounts"] == [{"currency": "DOP", "cents": newest["balance_cents"]}]
    assert (partly["paid_full"], partly["left_over_cents"]) == (False, 615000)
    assert partly["next_interest_cents"] == 28740
    assert (full["paid_full"], full["next_interest_cents"]) == (True, 0)
    interest = client.get("/api/interest", params={"year": 2026}).json()
    assert interest["lines"] == [
        {
            "key": "ficticio:credit_card",
            "label": card["label"],
            "currency": "DOP",
            "total_cents": 28740,
        }
    ]
    assert interest["total_dop_cents"] == 28700


def test_demo_db_keeps_december_as_the_newest_complete_month(tmp_path: Path) -> None:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    client = TestClient(create_app(path), "http://127.0.0.1")

    months = {m["month"]: m["partial"] for m in client.get("/api/months").json()}

    assert months == {"2026-02": True, "2026-01": True, "2025-12": False}


def test_demo_db_has_a_checking_account_with_income_cash_and_a_card_payment(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    client = TestClient(create_app(path), "http://127.0.0.1")

    keys = {a["key"]: a["kind"] for a in client.get("/api/accounts").json()}
    assert keys[CHECKING] == "checking"
    rows = client.get("/api/transactions", params={"month": "2026-01", "account": CHECKING}).json()
    by_kind = {
        kind: [i for i in rows["items"] if i["kind"] == kind]
        for kind in ("ingreso", "gasto", "transferencia")
    }
    assert len(by_kind["ingreso"]) >= 2
    assert all("DEPOSITO" in i["description"] for i in by_kind["ingreso"])
    # Antes solo "Efectivo" y "Pago de tarjeta": la demo ganó un pago de préstamo (gasto) y un
    # envío a terceros (transferencia que resta de lo que te quedó).
    assert sorted(i["category"] for i in by_kind["gasto"]) == ["Efectivo", "Préstamos"]
    assert sorted(i["category"] for i in by_kind["transferencia"]) == [
        "Pago de tarjeta",
        "Transferencias a terceros",
    ]
    summary = client.get("/api/summary", params={"month": "2026-01"}).json()
    assert summary["third_party_cents"] == 300000
    assert summary["net_cents"] == (
        summary["income_cents"] - summary["total_cents"] - summary["third_party_cents"]
    )
    assert summary["net_cents"] > 0
    assert summary["savings_rate"] is not None
    december = client.get("/api/summary", params={"month": "2025-12"}).json()
    assert december["income_cents"] > 0


def test_demo_db_suggests_a_big_rare_purchase(tmp_path: Path) -> None:
    path = tmp_path / "demo.db"
    build_demo_db(path)
    client = TestClient(create_app(path), "http://127.0.0.1")

    found = client.get("/api/one-off-suggestions", params={"month": "2026-02"}).json()

    assert [s["merchant"] for s in found] == ["AGENCIA FICTICIA"]
    assert found[0]["amount_dop_cents"] == 4500000
    for month in ("2025-12", "2026-01"):  # los demás meses no cambian
        assert client.get("/api/one-off-suggestions", params={"month": month}).json() == []


def test_household_demo_suggests_a_reserve_for_the_yearly_tax(tmp_path: Path) -> None:
    path = tmp_path / "demo.db"
    build_demo_db(path, household=True)
    client = TestClient(create_app(path, today=lambda: DEMO_TODAY), "http://127.0.0.1")
    [found] = client.get("/api/reserves").json()["suggestions"]
    assert (found["name"], found["amount_cents"], found["due_month"]) == (
        ANNUAL_TAX,
        340000,
        "2027-01",
    )
