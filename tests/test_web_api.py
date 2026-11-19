from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import categories
from michelito.analysis.recurring import GROUPS
from michelito.parsers import bhd_savings, popular_account
from michelito.web.app import create_app
from michelito.web.schemas import RecurringItemOut
from tests import samples
from tests.test_spending import _add_bank_rows, seed

WRITE = {"X-Michelito": "1"}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "michelito.db"
    with closing(db.connect(path)) as conn:
        seed(conn)
    return path


@pytest.fixture
def client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")


def _notes(db_path: Path) -> int:
    with closing(db.connect(db_path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM transaction_notes").fetchone()[0]


def _first_tx(client: TestClient) -> dict:
    month = client.get("/api/months").json()[0]["month"]
    return client.get("/api/transactions", params={"month": month}).json()["items"][0]


def test_months_and_summary_shape(client: TestClient) -> None:
    months = client.get("/api/months").json()
    assert months and set(months[0]) == {"month", "label", "partial"}
    response = client.get("/api/summary")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["total_cents"], int)
    assert body["option"]["month"] in {m["month"] for m in months}
    assert all(isinstance(c["amount_cents"], int) for c in body["categories"])


def test_summary_defaults_to_newest_complete_month(client: TestClient) -> None:
    months = client.get("/api/months").json()
    expected = next((m["month"] for m in months if not m["partial"]), months[0]["month"])
    assert client.get("/api/summary").json()["option"]["month"] == expected


def test_summary_unknown_month_404(client: TestClient) -> None:
    response = client.get("/api/summary", params={"month": "1999-01"})
    assert response.status_code == 404
    assert response.json() == {"detail": "mes sin datos"}  # spanish-ui


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "september", "2026-00"])
def test_summary_bad_month_422(client: TestClient, month: str) -> None:
    assert client.get("/api/summary", params={"month": month}).status_code == 422


def test_patch_requires_local_header(client: TestClient, db_path: Path) -> None:
    tx = _first_tx(client)
    response = client.patch(
        f"/api/transactions/{tx['fingerprint']}", json={"one_off": not tx["one_off"]}
    )
    assert response.status_code == 403
    assert _notes(db_path) == 0


def test_foreign_host_rejected(db_path: Path) -> None:
    app = TestClient(create_app(db_path), "http://127.0.0.1")
    assert app.get("/api/months", headers={"host": "evil.example"}).status_code == 400


def test_patch_merchant_scope_then_summary_moves_amount(client: TestClient) -> None:
    before = client.get("/api/summary").json()
    month = before["option"]["month"]
    tx = next(
        t
        for t in client.get("/api/transactions", params={"month": month}).json()["items"]
        if t["amount_dop_cents"] and t["amount_dop_cents"] > 0 and t["category"] != categories.OTHER
    )
    target = next(c for c in categories.ALL if c not in (tx["category"], categories.OTHER))
    response = client.patch(
        f"/api/transactions/{tx['fingerprint']}",
        json={"category": target, "scope": "merchant"},
        headers=WRITE,
    )
    assert response.status_code == 200
    assert response.json()["category"] == target
    assert response.json()["fingerprint"] == tx["fingerprint"]
    after = client.get("/api/summary", params={"month": month}).json()
    amount = {c["category"]: c["amount_cents"] for c in after["categories"]}
    old = {c["category"]: c["amount_cents"] for c in before["categories"]}
    assert amount[target] > old.get(target, 0)
    assert amount.get(tx["category"], 0) < old[tx["category"]]


def test_patch_one_off_only_leaves_category(client: TestClient) -> None:
    tx = _first_tx(client)
    response = client.patch(
        f"/api/transactions/{tx['fingerprint']}", json={"one_off": True}, headers=WRITE
    )
    assert response.status_code == 200
    assert response.json()["one_off"] is True
    assert response.json()["category"] == tx["category"]


def test_patch_unknown_category_422(client: TestClient, db_path: Path) -> None:
    tx = _first_tx(client)
    response = client.patch(
        f"/api/transactions/{tx['fingerprint']}", json={"category": "Made-up"}, headers=WRITE
    )
    assert response.status_code == 422
    assert _notes(db_path) == 0


def test_patch_unknown_fingerprint_404(client: TestClient) -> None:
    response = client.patch("/api/transactions/nope", json={"one_off": True}, headers=WRITE)
    assert response.status_code == 404


def test_patch_bad_scope_422(client: TestClient) -> None:
    tx = _first_tx(client)
    response = client.patch(
        f"/api/transactions/{tx['fingerprint']}", json={"scope": "everything"}, headers=WRITE
    )
    assert response.status_code == 422


def test_transactions_envelope(client: TestClient) -> None:
    body = client.get("/api/transactions").json()
    assert body["count"] == len(body["items"]) > 0
    assert isinstance(body["total_cents"], int)
    assert client.get("/api/transactions", params={"q": "zzzzzz"}).json()["count"] == 0


def test_accounts_and_categories(client: TestClient) -> None:
    accounts = client.get("/api/accounts").json()
    assert accounts and isinstance(accounts[0]["statements"], list)
    # It now has more fields (id, color, keywords…); `name` and `kind` are unchanged.
    assert [
        {"name": c["name"], "kind": c["kind"]} for c in client.get("/api/categories").json()
    ] == [{"name": name, "kind": categories.kind_of(name)} for name in categories.ALL]


def test_summary_has_flow_fields_and_transactions_have_kind(client: TestClient) -> None:
    body = client.get("/api/summary").json()
    assert isinstance(body["income_cents"], int) and isinstance(body["net_cents"], int)
    # Formerly income − expenses: third-party transfers are now subtracted too.
    assert body["net_cents"] == (
        body["income_cents"] - body["total_cents"] - body["third_party_cents"]
    )
    assert body["savings_rate"] is None or isinstance(body["savings_rate"], float)
    assert all(isinstance(t["income_cents"], int) for t in body["trend"])
    items = client.get("/api/transactions").json()["items"]
    assert items and all(t["kind"] in {"income", "expense", "transfer"} for t in items)


def test_transactions_kind_filter(client: TestClient) -> None:
    for kind in ("income", "expense", "transfer"):
        items = client.get("/api/transactions", params={"month": "2026-01", "kind": kind}).json()[
            "items"
        ]
        assert items and all(t["kind"] == kind for t in items)
    assert client.get("/api/transactions", params={"kind": "other"}).status_code == 422


def test_transactions_totals_are_per_kind(client: TestClient) -> None:
    body = client.get("/api/transactions", params={"month": "2026-01"}).json()
    spent = sum(t["amount_dop_cents"] or 0 for t in body["items"] if t["kind"] == "expense")
    assert body["total_cents"] == spent > 0
    assert body["income_cents"] == 500000 + 50  # 5,000.00 + 0.50 received
    assert body["unconverted_usd_cents"] == sum(
        t["amount_cents"]
        for t in body["items"]
        if t["kind"] == "expense" and t["amount_dop_cents"] is None
    )
    only_income = client.get(
        "/api/transactions", params={"month": "2026-01", "kind": "income"}
    ).json()
    assert only_income["total_cents"] == 0 and only_income["income_cents"] == 500050


def test_holders_file_is_read_per_request(db_path: Path, tmp_path: Path) -> None:
    holders = tmp_path / "holders.txt"
    client = TestClient(create_app(db_path, holders_path=holders), "http://127.0.0.1")

    def kind_of_received() -> str:
        items = client.get("/api/transactions", params={"month": "2026-01"}).json()["items"]
        return next(t["kind"] for t in items if t["description"] == "TRANSFERENCIA RECIBIDA")

    assert kind_of_received() == "income"
    holders.write_text("TRANSFERENCIA RECIBIDA\n", encoding="utf-8")
    assert kind_of_received() == "transfer"


def test_put_rate_saves_manual_rate(client: TestClient) -> None:
    response = client.put("/api/rates/2026-09", json={"value": "63.40"}, headers=WRITE)
    assert response.status_code == 200
    assert response.json() == {
        "month": "2026-09",
        "value": "63.4000",
        "month_used": "2026-09",
        "source": "manual",
    }


@pytest.mark.parametrize("value", ["0", "-1", "abc", "NaN", "Infinity", "0.00001", "1e30"])
def test_put_rate_rejects_non_positive(client: TestClient, value: str) -> None:
    response = client.put("/api/rates/2026-09", json={"value": value}, headers=WRITE)
    assert response.status_code == 422


def test_put_rate_rejects_bad_month_and_missing_header(client: TestClient) -> None:
    assert client.put("/api/rates/2026-13", json={"value": "63"}, headers=WRITE).status_code == 422
    assert client.put("/api/rates/2026-09", json={"value": "63"}).status_code == 403


def test_spa_fallback_serves_index(db_path: Path, tmp_path: Path) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>spa</html>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    client = TestClient(create_app(db_path, static), "http://127.0.0.1")
    page = client.get("/transactions")
    assert page.status_code == 200 and page.text == "<html>spa</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/../../etc/passwd").text == "<html>spa</html>"
    assert client.get("/api/months").status_code == 200


def test_unknown_api_path_is_404_json_not_spa(db_path: Path, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>spa</html>")
    client = TestClient(create_app(db_path, tmp_path), "http://127.0.0.1")
    response = client.get("/api/nothing")
    assert response.status_code == 404
    assert response.json()["detail"]
    assert client.post("/api/nothing", headers=WRITE).status_code == 404


def test_empty_database(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "empty.db"), "http://127.0.0.1")
    assert client.get("/api/months").json() == []
    assert client.get("/api/summary").status_code == 404
    assert client.get("/api/accounts").json() == []


def test_transactions_total_does_not_hide_usd_without_rate(client: TestClient) -> None:
    items = []
    for option in client.get("/api/months").json():
        items += client.get("/api/transactions", params={"month": option["month"]}).json()["items"]
    unconverted = [i for i in items if i["amount_dop_cents"] is None]
    assert unconverted and all(i["currency"] == "USD" for i in unconverted)
    for option in client.get("/api/months").json():
        body = client.get("/api/transactions", params={"month": option["month"]}).json()
        rows = [i for i in body["items"] if i["kind"] == "expense"]  # totals: expenses only
        assert body["total_cents"] == sum(
            i["amount_dop_cents"] for i in rows if i["amount_dop_cents"] is not None
        )
        assert body["unconverted_usd_cents"] == sum(
            i["amount_cents"] for i in rows if i["amount_dop_cents"] is None
        )
    # Once each month has a rate, nothing is left unconverted.
    for option in client.get("/api/months").json():
        client.put(f"/api/rates/{option['month']}", json={"value": "60"}, headers=WRITE)
    for option in client.get("/api/months").json():
        body = client.get("/api/transactions", params={"month": option["month"]}).json()
        assert body["unconverted_usd_cents"] == 0


def test_bare_api_head_and_nul_paths(db_path: Path, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>spa</html>")
    client = TestClient(create_app(db_path, tmp_path), "http://127.0.0.1")
    bare = client.get("/api")
    assert bare.status_code == 404 and bare.json()["detail"]
    assert client.head("/api/nothing").status_code == 404
    assert client.get("/%00").status_code == 200


def _charge_rows(db_path: Path, merchant: str, charges: list[tuple[str, int]]) -> None:
    """Insert made-up monthly charges into a card statement from `seed`."""
    with closing(db.connect(db_path)) as conn, conn:
        statement_id, currency = conn.execute(
            "SELECT s.id, s.currency FROM statements s JOIN accounts a ON a.id = s.account_id "
            "WHERE a.kind = 'credit_card' ORDER BY s.id LIMIT 1"
        ).fetchone()
        start = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM transactions WHERE statement_id = ?",
            (statement_id,),
        ).fetchone()[0]
        conn.executemany(
            db._INSERT_TRANSACTION,
            [
                (
                    statement_id,
                    start + i,
                    day,
                    day,
                    merchant,
                    cents,
                    "debit",
                    currency,
                    None,
                    "4899",
                    merchant,
                )
                for i, (day, cents) in enumerate(charges)
            ],
        )


def test_recurring_empty_database(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    with closing(db.connect(path)):
        pass
    body = TestClient(create_app(path), "http://127.0.0.1").get("/api/recurring").json()
    assert body["items"] == [] and body["groups"] == [] and body["dismissed"] == []
    assert body["monthly_cents"] == 0 and body["as_of"] is None and body["alerts"] == []


def test_recurring_mark_requires_header(client: TestClient) -> None:
    body = {"merchant": "NETFLIX", "currency": "DOP", "status": "dismissed"}
    assert client.put("/api/recurring/mark", json=body).status_code == 403


@pytest.fixture
def subscription_client(db_path: Path) -> TestClient:
    _charge_rows(
        db_path,
        "NETFLIX INVENTADO",
        [
            ("2027-01-05", 59900),
            ("2027-02-05", 59900),
            ("2027-03-05", 59900),
            ("2027-04-05", 79900),
        ],
    )
    return TestClient(create_app(db_path, today=lambda: date(2027, 4, 10)), "http://127.0.0.1")


def test_recurring_mark_dismiss_and_undo(subscription_client: TestClient) -> None:
    client = subscription_client
    before = client.get("/api/recurring").json()
    item = next(i for i in before["items"] if i["merchant"].startswith("NETFLIX"))
    key = {"merchant": item["merchant"], "currency": item["currency"]}

    hidden = client.put("/api/recurring/mark", json={**key, "status": "dismissed"}, headers=WRITE)
    assert hidden.status_code == 200
    assert [d["merchant"] for d in hidden.json()["dismissed"]] == [item["merchant"]]
    assert item["merchant"] not in [i["merchant"] for i in hidden.json()["items"]]

    undone = client.put("/api/recurring/mark", json={**key, "status": None}, headers=WRITE)
    assert undone.json()["dismissed"] == []
    assert item["merchant"] in [i["merchant"] for i in undone.json()["items"]]


def test_recurring_mark_installments_absent_vs_null(subscription_client: TestClient) -> None:
    client = subscription_client
    key = {"merchant": "NETFLIX INVENTADO", "currency": "DOP"}

    def left(response) -> int | None:  # noqa: ANN001
        return response.json()["items"][0]["installments_left"]

    with_left = client.put(
        "/api/recurring/mark",
        json={**key, "status": "confirmed", "installments_left": 5},
        headers=WRITE,
    )
    assert left(with_left) == 5
    untouched = client.put(
        "/api/recurring/mark", json={**key, "status": "confirmed"}, headers=WRITE
    )
    assert left(untouched) == 5  # absent: left alone
    cleared = client.put(
        "/api/recurring/mark",
        json={**key, "status": "confirmed", "installments_left": None},
        headers=WRITE,
    )
    assert left(cleared) is None  # explicit null: cleared


@pytest.mark.parametrize(
    "extra",
    [{"status": "other"}, {"status": "confirmed", "installments_left": -1}, {"currency": "EUR"}],
)
def test_recurring_mark_validation(client: TestClient, extra: dict) -> None:
    body = {"merchant": "NETFLIX", "currency": "DOP", "status": "dismissed", **extra}
    response = client.put("/api/recurring/mark", json=body, headers=WRITE)
    assert response.status_code == 422


def test_recurring_month_alerts_shape(subscription_client: TestClient) -> None:
    body = subscription_client.get("/api/recurring", params={"month": "2027-04"}).json()
    assert body["as_of"] == "2027-04-05"
    item = next(i for i in body["items"] if i["merchant"].startswith("NETFLIX"))
    assert item["typical_cents"] == 79900 and item["currency"] == "DOP"
    assert item["monthly_cents"] == 79900 and item["yearly_cents"] == 79900 * 12
    assert item["price_change"] == {
        "before_cents": 59900,
        "after_cents": 79900,
        "day": "2027-04-05",
    }
    assert item["group"] == GROUPS["subscriptions"] and item["status"] == "active"
    assert body["monthly_cents"] >= item["monthly_cents"]
    assert {"group", "monthly_cents", "yearly_cents", "count"} == set(body["groups"][0])
    alert = next(a for a in body["alerts"] if a["kind"] == "price_up")
    assert set(alert) == {"kind", "merchant", "currency", "detail", "name"}
    assert alert["merchant"] == item["merchant"]
    no_month = subscription_client.get("/api/recurring").json()
    assert no_month["alerts"] == []


def test_recurring_installments_count_from_latest_movement(
    subscription_client: TestClient, db_path: Path
) -> None:
    key = {"merchant": "NETFLIX INVENTADO", "currency": "DOP"}
    body = {**key, "status": "confirmed", "installments_left": 5}
    assert (
        subscription_client.put("/api/recurring/mark", json=body, headers=WRITE).status_code == 200
    )
    with closing(db.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT installments_on, status_on FROM recurring_marks WHERE merchant = ?",
            (key["merchant"],),
        ).fetchone()
    assert tuple(row) == (
        "2027-04-05",
        "2027-04-10",
    )  # installments: latest data point; status: today


def test_recurring_response_types_are_enums(subscription_client: TestClient) -> None:
    props = RecurringItemOut.model_json_schema()["properties"]
    assert props["cadence"]["enum"] == ["monthly", "yearly"]
    assert props["currency"]["enum"] == ["DOP", "USD"]
    assert props["status"]["enum"] == ["active", "inactive", "cancelled", "ended"]
    assert subscription_client.get("/api/recurring").json()["first_month"] == "2025-12"


def test_interest_api_shape(client: TestClient) -> None:
    body = client.get("/api/interest").json()
    assert set(body) == {"year", "lines", "total_dop_cents", "unconverted_usd_cents", "next_due"}
    assert body["year"] == 2026
    assert isinstance(body["total_dop_cents"], int)
    assert client.get("/api/interest", params={"year": 2025}).json()["year"] == 2025
    assert client.get("/api/interest", params={"year": 1999}).status_code == 422
    assert client.get("/api/interest", params={"year": "x"}).status_code == 422


def test_accounts_api_has_to_pay(db_path: Path) -> None:
    with closing(db.connect(db_path)) as conn, conn:
        conn.execute("UPDATE statements SET closing_balance_cents = 12345, due_date = '2026-11-02'")
    client = TestClient(create_app(db_path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")
    accounts = client.get("/api/accounts").json()
    paying = next(a for a in accounts if a["to_pay"])
    to_pay = paying["to_pay"]
    assert set(to_pay) == {"due_date", "amounts", "minimums", "text"}
    assert to_pay["amounts"][0]["cents"] > 0 and "antes del" in to_pay["text"]  # spanish-ui
    line = paying["statements"][0]
    assert {"paid_full", "left_over_cents", "paid_late", "next_interest_cents"} <= set(line)
    assert "statement_id" not in line


def test_recurring_leaves_out_transfers_to_a_holder(db_path: Path, tmp_path: Path) -> None:
    with closing(db.connect(db_path)) as conn:
        _add_bank_rows(
            conn,
            [
                # Formerly "ENVIO A …", no longer an expense; a loan payment still is.
                (day, "AUT PAGO MARIA PEREZ INVENTADA", "debit", "700000")
                for day in ("2025-10-12", "2025-11-12", "2025-12-12", "2026-01-12")
            ],
        )
    holders = tmp_path / "holders.txt"
    client = TestClient(create_app(db_path, holders_path=holders), "http://127.0.0.1")

    def merchants(response) -> set[str]:
        body = response.json()
        return {i["merchant"] for i in (*body["items"], *body["dismissed"])}

    # The key used to be "AUT PAGO"; a bank key now includes the counterparty.
    assert "AUT PAGO MARIA PEREZ" in merchants(client.get("/api/recurring"))
    holders.write_text("MARIA PEREZ INVENTADA\n", encoding="utf-8")
    assert "AUT PAGO MARIA PEREZ" not in merchants(client.get("/api/recurring"))
    marked = client.put(
        "/api/recurring/mark",
        json={"merchant": "OTRO INVENTADO", "currency": "DOP", "status": "dismissed"},
        headers=WRITE,
    )
    assert marked.status_code == 200
    assert "AUT PAGO" not in merchants(marked)


def _store(db_path: Path, name: str, statement) -> int:
    with closing(db.connect(db_path)) as conn, conn:
        # spanish-data: begin (synthetic mail source)
        conn.execute(
            "INSERT INTO gmail_messages VALUES (?, 'banco', 'x', 'y', 'z', 1, 'z')",
            (name,),
        )
        document_id = conn.execute(
            "INSERT INTO documents (message_id, source, filename, path, sha256, size, "
            "received_at, status) VALUES (?, 'banco', 'f.pdf', 'p', ?, 1, 'z', 'parsed')",
            (name, name),
        ).lastrowid
        # spanish-data: end
        db.store_statement(conn, document_id, statement)
        return conn.execute("SELECT MAX(id) FROM statements").fetchone()[0]


def test_older_bank_statement_adds_no_months(db_path: Path, client: TestClient) -> None:
    before = client.get("/api/months").json()
    statement_id = _store(db_path, "old", bhd_savings.parse((samples.BHD_AHORRO_2025,)))
    with closing(db.connect(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO transactions (statement_id, sequence, transacted_on, description, "
            "amount_cents, direction, currency, raw_line) VALUES (?, 99, '2025-05-20', "
            "'COMPRA VIEJA INVENTADA', 90000000, 'debit', 'DOP', 'x')",
            (statement_id,),
        )
    assert client.get("/api/months").json() == before
    body = client.get("/api/summary").json()
    assert all(t["month"] >= before[-1]["month"] for t in body["trend"])


def test_summary_reports_income_through(db_path: Path, client: TestClient) -> None:
    covered = client.get("/api/summary", params={"month": "2026-01"}).json()
    assert covered["income_through"] is None
    # The Popular checking account cuts off on January 15.
    _store(db_path, "pop", popular_account.parse(samples.POPULAR_CUENTA_DOP))
    body = client.get("/api/summary", params={"month": "2026-01"}).json()
    assert (body["income_through"], body["savings_rate"]) == ("2026-01-15", None)


def test_summary_third_party_is_out_of_spending_but_lowers_net(db_path: Path) -> None:
    client = TestClient(create_app(db_path, today=lambda: date(2026, 10, 20)), "http://127.0.0.1")
    before = client.get("/api/summary", params={"month": "2026-01"}).json()
    with closing(db.connect(db_path)) as conn:
        _add_bank_rows(
            conn, [("2026-01-21", "MB a 0000000001 PERSONA INVENTADA", "debit", "123400")]
        )
    after = client.get("/api/summary", params={"month": "2026-01"}).json()
    assert after["third_party_cents"] == before["third_party_cents"] + 123400
    assert after["total_cents"] == before["total_cents"]
    assert after["categories"] == before["categories"]
    assert after["net_cents"] == before["net_cents"] - 123400
    sent = client.get(
        "/api/transactions",
        params={"month": "2026-01", "category": categories.THIRD_PARTY},
    ).json()["items"]
    assert [t["description"] for t in sent] == ["MB a 0000000001 PERSONA INVENTADA"]
