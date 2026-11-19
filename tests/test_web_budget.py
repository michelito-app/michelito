"""Presupuesto y reservas desde la API: activar, topes, aviso de «lo habitual cambió», gastos
únicos, compartidos, reservas (aporte, vínculos, sugerencias), «Para revisar», la tarjeta del
Resumen, la bitácora y deshacer. Datos inventados: una tarjeta ficticia de 2024-01 a 2026-01."""

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finanzas import db
from finanzas.analysis import links
from finanzas.parsers.common import Statement
from finanzas.web.app import create_app
from tests.e2e_server import _purchase, _section
from tests.helpers import store

WRITE = {"X-Finanzas": "1"}
TODAY = date(2026, 2, 20)
MARBETE = "MARBETE INVENTADO"
FUN_EXTRA = "FERIA NAVIDENA FICTICIA"


def _months(first: tuple[int, int], count: int) -> list[str]:
    year, month = first
    found = []
    for _ in range(count):
        found.append(f"{year:04d}-{month:02d}")
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    return found


MONTHS = _months((2024, 1), 25)  # enero 2024 a enero 2026, todos completos


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
        # El ocio de cada mes, en sitios que cambian (no es una serie recurrente mensual: si lo
        # fuera, Entretenimiento no se sugeriría por pico).
        rows.append(_purchase(f"{month}-12", _cinema(index), "3000.00", mcc="7832"))
    # Un pico de Entretenimiento en diciembre de dos años (para la sugerencia de reserva).
    rows.append(_purchase("2024-12-15", FUN_EXTRA, "15000.00", mcc="7832"))
    rows.append(_purchase("2025-12-15", "PARQUE NAVIDENO FICTICIO", "15000.00", mcc="7832"))
    # Un cobro anual (recurrente) en Gobierno e impuestos.
    rows.append(_purchase("2025-01-20", MARBETE, "3400.00", mcc="9311"))
    rows.append(_purchase("2026-01-20", MARBETE, "3400.00", mcc="9311"))
    # Enero 2026: una cena de RD$ 4,000 y una compra grande (las pruebas la marcan como única).
    rows.append(_purchase("2026-01-22", "RESTAURANTE FICTICIO", "4000.00", mcc="5812"))
    rows.append(_purchase("2026-01-25", "RESTAURANTE CARO FICTICIO", "45000.00", mcc="5812"))
    return tuple(rows)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    found = tmp_path / "finanzas.db"
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
        "name": "Marbete",
        "amount_cents": 350_000,
        "category_id": _category_id(client, "Gobierno e impuestos"),
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
    super_ = _line(body, "Supermercado")
    assert (super_["cap_cents"], super_["manual"], super_["spent_cents"]) == (
        1_000_000,
        False,
        1_000_000,
    )
    # Entretenimiento: mediana de seis meses con un diciembre alto = 3,000.
    assert _line(body, "Entretenimiento")["cap_cents"] == 300_000
    # Gobierno solo tuvo el marbete de enero: su mediana es 0 -> «Sin presupuesto».
    assert _line(body, "Gobierno e impuestos")["cap_cents"] is None
    assert client.post("/api/budget/activate", headers=WRITE).status_code == 409


def test_one_off_stays_out_of_the_cap_and_a_hand_cap_is_fixed(client: TestClient) -> None:
    _activate(client)
    dinner = _fp(client, "RESTAURANTE CARO FICTICIO")
    patched = client.patch(f"/api/transactions/{dinner}", json={"one_off": True}, headers=WRITE)
    assert patched.status_code == 200, patched.text
    food = _category_id(client, "Restaurantes")
    assert (
        client.put(
            f"/api/budget/caps/{food}", json={"cap_cents": 300_000}, headers=WRITE
        ).status_code
        == 200
    )
    line = _line(_budget(client), "Restaurantes")
    assert (line["cap_cents"], line["manual"], line["spent_cents"], line["one_offs_cents"]) == (
        300_000,
        True,
        400_000,
        4_500_000,
    )
    assert line["over_cents"] == 100_000
    body = _budget(client)
    assert body["over_count"] == 1 and body["over_cents"] == 100_000
    assert body["lines"][0]["category"] == "Restaurantes"  # la que más pasa, primero
    # Sin arrastre: diciembre no ve lo de enero.
    assert _line(_budget(client, "2025-12"), "Restaurantes")["spent_cents"] == 0
    # «Sin presupuesto» a mano.
    assert (
        client.put(f"/api/budget/caps/{food}", json={"cap_cents": None}, headers=WRITE).status_code
        == 200
    )
    assert _line(_budget(client), "Restaurantes")["cap_cents"] is None


def test_shared_counts_only_my_part(client: TestClient, path: Path) -> None:
    _activate(client)
    fp = _fp(client, "SUPERMERCADO FICTICIO")
    with closing(db.connect(path)) as conn, conn:
        links.set_shared(conn, fp, Decimal("10000.00"), people=2)
    assert _line(_budget(client), "Supermercado")["spent_cents"] == 500_000


def test_habitual_change_warns_and_accept_or_ignore(client: TestClient, path: Path) -> None:
    _activate(client)
    # Una tarjeta nueva con más súper y más cine en los últimos seis meses: lo habitual sube.
    extra = []
    for month in MONTHS[-6:]:
        extra.append(_purchase(f"{month}-08", "SUPER FICTICIO DOS", "10000.00", mcc="5411"))
        extra.append(_purchase(f"{month}-09", "TEATRO FICTICIO", "2000.00", mcc="7922"))
    with closing(db.connect(path)) as conn:
        store(conn, _card("2222", tuple(extra)))
    body = _budget(client)
    super_, fun = _line(body, "Supermercado"), _line(body, "Entretenimiento")
    assert super_["warning"] == {"habitual_cents": 2_000_000, "basis_cents": 1_000_000, "up": True}
    assert fun["warning"] == {"habitual_cents": 500_000, "basis_cents": 300_000, "up": True}
    url = f"/api/budget/caps/{super_['category_id']}/habitual"
    assert client.post(url, json={"accept": True}, headers=WRITE).status_code == 200
    url = f"/api/budget/caps/{fun['category_id']}/habitual"
    assert client.post(url, json={"accept": False}, headers=WRITE).status_code == 200
    body = _budget(client)
    assert (_line(body, "Supermercado")["cap_cents"], _line(body, "Supermercado")["warning"]) == (
        2_000_000,
        None,
    )
    # Ignorado: el tope no cambia y no vuelve a avisar.
    assert (
        _line(body, "Entretenimiento")["cap_cents"],
        _line(body, "Entretenimiento")["warning"],
    ) == (
        300_000,
        None,
    )
    assert client.post(url, json={"accept": True}, headers=WRITE).status_code == 404


def test_reserves_contribution_and_linked_expense_is_covered(client: TestClient) -> None:
    _activate(client)
    yearly = _reserve(client)
    _reserve(client, name="Seguro", amount_cents=3_000_000, every_months=6, due_month="2026-03")
    _reserve(client, name="Colegio", amount_cents=450_000, every_months=None, due_month="2026-12")
    items = {r["name"]: r for r in _reserves(client)["items"]}
    assert items["Marbete"]["monthly_cents"] == 30_000  # 3,500 / 12 -> RD$ 300
    assert items["Seguro"]["monthly_cents"] == 500_000  # 30,000 / 6
    assert items["Colegio"]["monthly_cents"] == 50_000  # 4,500 / 10 meses -> RD$ 500
    assert items["Seguro"]["next_due"] == "2026-03"
    assert _reserves(client)["monthly_cents"] == 580_000

    fp = _fp(client, MARBETE)
    detail = client.get(f"/api/transactions/{fp}/reserve").json()
    assert detail["can_link"] and yearly in [o["id"] for o in detail["options"]]
    # Creada en febrero: el vencimiento de enero es de antes, así que no se sugiere (sí se puede
    # vincular a mano).
    assert not any(o["suggested"] for o in detail["options"])
    linked = client.post(
        f"/api/reserves/{yearly}/members", json={"fingerprints": [fp]}, headers=WRITE
    )
    assert linked.json()["applied"] == [fp]
    line = _line(_budget(client), "Gobierno e impuestos")
    assert (line["spent_cents"], line["covered_cents"]) == (0, 340_000)
    marbete = next(r for r in _reserves(client)["items"] if r["id"] == yearly)
    # Este año (2026): vence en enero y el gasto vinculado es de enero.
    assert (marbete["year_spent_cents"], marbete["year_estimated_cents"]) == (340_000, 350_000)
    assert client.get(f"/api/transactions/{fp}/reserve").json()["reserve"]["id"] == yearly
    tx = client.get(f"/api/transactions/{fp}").json()
    assert tx["link"] == "reserve" and tx["can_share"] is False
    # Quitar el vínculo lo devuelve al tope.
    assert client.delete(f"/api/reserves/{yearly}/members/{fp}", headers=WRITE).status_code == 200
    line = _line(_budget(client), "Gobierno e impuestos")
    assert (line["spent_cents"], line["covered_cents"]) == (340_000, 0)


def test_a_reserve_with_several_expenses_and_the_batch(client: TestClient, path: Path) -> None:
    fun = _category_id(client, "Entretenimiento")
    christmas = _reserve(
        client, name="Navidad", category_id=fun, amount_cents=1_800_000, due_month="2025-12",
        multiple=True,
    )  # fmt: skip
    gifts = [
        _fp(client, "PARQUE NAVIDENO FICTICIO", "2025-12"),
        _fp(client, _cinema(MONTHS.index("2025-12")), "2025-12"),
    ]
    shared = _fp(client, "SUPERMERCADO FICTICIO", "2025-12")
    with closing(db.connect(path)) as conn, conn:
        links.set_shared(conn, shared, Decimal("10000.00"), people=2)
    body = {"fingerprints": [*gifts, shared, "no-existe"]}
    found = client.post(f"/api/reserves/{christmas}/members", json=body, headers=WRITE).json()
    assert found["applied"] == gifts
    reasons = {s["fingerprint"]: s["reason"] for s in found["skipped"]}
    assert reasons["no-existe"] == "desconocida"
    assert reasons[shared] == "vinculo"  # una huella, un solo vínculo
    navidad = next(r for r in _reserves(client)["items"] if r["id"] == christmas)
    assert {m["fingerprint"] for m in navidad["members"]} == set(gifts)
    _activate(client)
    line = _line(_budget(client, "2025-12"), "Entretenimiento")
    assert (line["spent_cents"], line["covered_cents"]) == (0, 1_800_000)
    entries = client.get("/api/log", params={"kind": "reserva_gasto"}).json()["items"]
    assert entries[0]["affected"] == 2 and entries[0]["after"]["text"].startswith("2 gastos")


def test_suggestions_from_a_yearly_recurring_and_a_repeated_peak(client: TestClient) -> None:
    found = {s["key"]: s for s in _reserves(client)["suggestions"]}
    recurring = next(s for k, s in found.items() if k.startswith("recurrente:"))
    assert (recurring["name"], recurring["amount_cents"], recurring["due_month"]) == (
        MARBETE.split()[0] + " INVENTADO",
        340_000,
        "2027-01",
    )
    peak = next(s for k, s in found.items() if k.startswith("pico:"))
    assert (peak["name"], peak["amount_cents"], peak["due_month"], peak["multiple"]) == (
        "Diciembre: Entretenimiento",
        1_500_000,  # el exceso del último diciembre sobre la mediana del cine (18,000 - 3,000)
        "2026-12",
        True,
    )
    # Descartar: no vuelve (también con un filtro de cuentas: solo se valida la clave).
    dismissed = client.post(
        "/api/reserve-suggestions/dismiss?accounts=x",
        json={"key": peak["key"], "name": peak["name"]},
        headers=WRITE,
    )
    assert dismissed.status_code == 200
    assert peak["key"] not in {s["key"] for s in _reserves(client)["suggestions"]}
    # Crear desde la sugerencia: tampoco vuelve.
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
            "/api/reserve-suggestions/dismiss", json={"key": "no-existe"}, headers=WRITE
        ).status_code
        == 422
    )


def test_one_year_of_data_suggests_no_peak(tmp_path: Path) -> None:
    path = tmp_path / "uno.db"
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
    # Creada en enero de 2026 (su «hoy»): el marbete de ese enero es de su vencimiento.
    client = TestClient(create_app(path, today=lambda: date(2026, 1, 5)), "http://127.0.0.1")
    reserve = _reserve(client)
    fp = _fp(client, MARBETE)
    items = client.get("/api/review", params={"month": "2026-01"}).json()
    [proposed] = [i for i in items if i["kind"] == "reserva_posible"]
    assert (proposed["fingerprint"], proposed["reserve_id"]) == (fp, reserve)
    assert "Marbete" in proposed["reason"]
    marked = client.put(f"/api/review/reserva_posible/{fp}", json={"reviewed": True}, headers=WRITE)
    assert marked.status_code == 200
    items = client.get("/api/review", params={"month": "2026-01"}).json()
    assert not [i for i in items if i["kind"] == "reserva_posible"]


def test_overview_for_the_summary(client: TestClient) -> None:
    assert client.get("/api/budget/overview").json()["active"] is False
    _activate(client)
    _reserve(client)
    _reserve(client, name="Colegio", amount_cents=450_000, every_months=None, due_month="2026-04")
    food = _category_id(client, "Restaurantes")
    client.put(f"/api/budget/caps/{food}", json={"cap_cents": 100_000}, headers=WRITE)
    body = client.get("/api/budget/overview", params={"month": "2026-01"}).json()
    assert (body["active"], body["over_count"], body["over_cents"]) == (True, 1, 4_800_000)
    assert body["monthly_cents"] == 30_000 + 150_000  # 3,500 / 12 y 4,500 / 3 meses (feb-abr)
    assert [(u["name"], u["due_month"]) for u in body["upcoming"]] == [("Colegio", "2026-04")]


def test_every_change_is_in_the_log_and_undoes(client: TestClient) -> None:
    _activate(client)
    food = _category_id(client, "Restaurantes")
    client.put(f"/api/budget/caps/{food}", json={"cap_cents": 100_000}, headers=WRITE)
    reserve = _reserve(client)
    client.patch(f"/api/reserves/{reserve}", json={"amount_cents": 400_000}, headers=WRITE)
    fp = _fp(client, MARBETE)
    client.post(f"/api/reserves/{reserve}/members", json={"fingerprints": [fp]}, headers=WRITE)
    peak = next(s for s in _reserves(client)["suggestions"] if s["key"].startswith("pico:"))
    client.post(
        "/api/reserve-suggestions/dismiss",
        json={"key": peak["key"], "name": peak["name"]},
        headers=WRITE,
    )
    other = _reserve(client, name="Borrar", due_month="2026-06", every_months=None)
    assert client.delete(f"/api/reserves/{other}", headers=WRITE).status_code == 204
    log = client.get("/api/log").json()
    kinds = [e["kind"] for e in log["items"]]
    assert kinds == [
        "reserva",
        "reserva",
        "reserva_descarte",
        "reserva_gasto",
        "reserva",
        "reserva",
        "presupuesto",
        "presupuesto",
    ]
    lines = [f"{e['subject']} · {e['before']['text']} → {e['after']['text']}" for e in log["items"]]
    assert lines == [
        "Borrar · RD$ 3,500 · una vez, en 2026-06 → borrada",
        "Borrar · — → RD$ 3,500 · una vez, en 2026-06",
        "Diciembre: Entretenimiento · sugerida → descartada",
        "MARBETE INVENTADO · — → cubierto por «Marbete»",
        "Marbete · RD$ 3,500 · cada año en enero → RD$ 4,000 · cada año en enero",
        "Marbete · — → RD$ 3,500 · cada año en enero",
        "Restaurantes · sin presupuesto → tope RD$ 1,000",
        "Presupuesto · sin activar → 26 categorías, 2 con tope",
    ]
    # Deshacer todo, de la más nueva a la más vieja (cada una se ensaya antes en un SAVEPOINT).
    for entry in log["items"]:
        now = {e["id"]: e for e in client.get("/api/log").json()["items"]}
        assert now[entry["id"]]["can_undo"], now[entry["id"]]["undo_message"]
        undone = client.post(f"/api/log/{entry['id']}/undo", headers=WRITE)
        assert undone.status_code == 200, undone.text
    assert _budget(client)["active"] is False
    assert _reserves(client)["items"] == []
    assert peak["key"] in {s["key"] for s in _reserves(client)["suggestions"]}


def test_a_cap_before_activating_is_a_conflict(client: TestClient) -> None:
    food = _category_id(client, "Restaurantes")
    put = client.put(f"/api/budget/caps/{food}", json={"cap_cents": 100_000}, headers=WRITE)
    assert put.status_code == 409
    assert _budget(client)["active"] is False


def test_only_yearly_half_yearly_or_once(client: TestClient) -> None:
    body = {
        "name": "Cada tres",
        "amount_cents": 100_000,
        "category_id": _category_id(client, "Gobierno e impuestos"),
        "due_month": "2026-06",
        "every_months": 3,
    }
    assert client.post("/api/reserves", json=body, headers=WRITE).status_code == 422


def test_options_are_just_id_and_name(client: TestClient) -> None:
    found = _reserve(client)
    assert client.get("/api/reserves/options").json() == [{"id": found, "name": "Marbete"}]


def test_a_paid_due_does_not_add_to_the_month_nor_to_upcoming(path: Path) -> None:
    client = TestClient(create_app(path, today=lambda: date(2026, 1, 10)), "http://127.0.0.1")
    reserve = _reserve(client, due_month="2026-01")
    assert [u["name"] for u in client.get("/api/budget/overview").json()["upcoming"]] == ["Marbete"]
    fp = _fp(client, MARBETE)
    client.post(f"/api/reserves/{reserve}/members", json={"fingerprints": [fp]}, headers=WRITE)
    body = client.get("/api/budget/overview").json()
    assert (body["upcoming"], body["monthly_cents"]) == ([], 0)
    item = _reserves(client)["items"][0]
    assert (item["paid"], item["monthly_cents"]) == (True, 0)


def test_with_an_account_filter_caps_are_of_all_and_passed_are_not_counted(
    client: TestClient,
) -> None:
    _activate(client)
    food = _category_id(client, "Restaurantes")
    client.put(f"/api/budget/caps/{food}", json={"cap_cents": 100_000}, headers=WRITE)
    key = client.get("/api/accounts").json()[0]["key"]
    body = client.get("/api/budget", params={"month": "2026-01", "accounts": key}).json()
    assert body["filtered"] is False  # con la única cuenta elegida es «todas»
    overview = client.get("/api/budget/overview", params={"month": "2026-01"}).json()
    assert overview["over_count"] == 1


def test_a_month_without_every_statement_says_what_is_missing(path: Path) -> None:
    late = (_purchase("2026-01-03", "TIENDA TARDE FICTICIA", "1000.00", mcc="5311"),)
    with closing(db.connect(path)) as conn:
        store(conn, _card("4444", late, period_end=date(2026, 1, 15), institution="tardio"))
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
    assert overview["over_count"] is None  # con filtro no se cuentan las pasadas
    assert client.get("/api/budget/overview", params={"month": "2026-01"}).json()["missing"]
