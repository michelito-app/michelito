"""Multi-select through the API (`PATCH /api/transactions`), with made-up data: applies and
skips with a reason, rejects link categories, limit, atomicity, a single log entry and an undo
that restores each previous correction exactly."""

from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import db, dossier
from michelito.analysis import categories, corrections
from michelito.i18n import t
from michelito.web import batch_edit
from tests.test_web_log import (
    BACK,
    DELIVERY,
    DEPOSIT,
    MONTH,
    REFUND,
    WITHDRAWAL,
    WRITE,
    _category_id,
    _fp,
    _fps,
    _log,
    _patch,
    _tx,
    _undo,
)
from tests.test_web_log import client as client  # noqa: F401 (fixture)

CLAUDE = {**WRITE, "X-Michelito-Author": "claude"}


def _batch(client: TestClient, fps: list[str], category: str, headers: dict = WRITE, **extra):
    body = {"fingerprints": fps, "category_id": _category_id(client, category), **extra}
    return client.patch("/api/transactions", json=body, headers=headers)


def test_needs_the_header(client: TestClient) -> None:
    response = client.patch("/api/transactions", json={"fingerprints": ["x"], "category_id": 1})
    assert response.status_code == 403


def test_applies_the_valid_ones_and_skips_the_rest_with_a_reason(client: TestClient) -> None:
    deposit, back, withdrawal = _fp(client, DEPOSIT), _fp(client, BACK), _fp(client, WITHDRAWAL)
    dop_leg, usd_leg = _fp(client, "DEPOSITO CAMBIO"), _fp(client, "TRANSFERENCIA A PERSONA")
    made = client.post("/api/exchanges", json={"fingerprints": [dop_leg, usd_leg]}, headers=WRITE)
    assert made.status_code == 201

    response = _batch(
        client,
        [deposit, back, dop_leg, withdrawal, "missing-fp"],
        categories.CRYPTO,
        reason="P2P sale",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == [deposit, back]
    assert [(s["fingerprint"], s["reason"]) for s in body["skipped"]] == [
        (dop_leg, "linked"),
        (withdrawal, "direction"),
        ("missing-fp", "unknown"),
    ]
    assert all(s["message"] for s in body["skipped"])
    assert [_tx(client, fp)["category"] for fp in (deposit, back)] == [
        categories.CRYPTO,
        categories.CRYPTO,
    ]
    assert _tx(client, dop_leg)["category"] == categories.CURRENCY_EXCHANGE
    assert _tx(client, withdrawal)["category"] == categories.CASH

    entries = [e for e in _log(client) if e["kind"] == batch_edit.BATCH_KIND]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == body["entry_id"]
    assert (entry["subject"], entry["before"]["text"], entry["after"]["text"]) == (
        t("web.batch.transactions", count=2),
        categories.OTHER_INCOME,
        categories.CRYPTO,
    )
    assert (entry["reason"], entry["affected"], entry["author"]) == ("P2P sale", 2, "user")
    assert sorted(entry["fingerprints"]) == sorted([deposit, back])
    assert entry["can_undo"] is True


def test_never_creates_a_merchant_rule_and_records_the_author(client: TestClient) -> None:
    deposit = _fp(client, DEPOSIT)
    assert _batch(client, [deposit], categories.CRYPTO, CLAUDE).status_code == 200
    rules = client.get("/api/log").json()["items"][0]
    assert (rules["author"], rules["target_type"]) == ("claude", "category")
    assert "merchant_categories" not in rules["after"]["rows"]


def test_nothing_to_change_leaves_no_entry(client: TestClient) -> None:
    withdrawal = _fp(client, WITHDRAWAL)
    body = _batch(client, [withdrawal], categories.CRYPTO).json()
    assert (body["applied"], body["entry_id"]) == ([], None)
    assert _log(client) == []


@pytest.mark.parametrize(
    "name", [categories.CASH_BOX, categories.INVESTMENT, categories.INVESTMENT_CAPITAL]
)
def test_link_categories_are_rejected(client: TestClient, name: str) -> None:
    response = _batch(client, [_fp(client, DEPOSIT)], name)
    assert response.status_code == 422
    assert _log(client) == []


def test_unknown_category_limit_and_reason_length(client: TestClient) -> None:
    deposit = _fp(client, DEPOSIT)
    unknown = {"fingerprints": [deposit], "category_id": 99999}
    assert client.patch("/api/transactions", json=unknown, headers=WRITE).status_code == 422
    too_many = [f"h{i}" for i in range(batch_edit.BATCH_MAX + 1)]
    assert _batch(client, too_many, categories.CRYPTO).status_code == 422
    assert _batch(client, [], categories.CRYPTO).status_code == 422
    at_limit = [deposit, *(f"h{i}" for i in range(batch_edit.BATCH_MAX - 1))]
    assert _batch(client, at_limit, categories.CRYPTO).status_code == 200
    assert (
        _batch(client, [_fp(client, BACK)], categories.CRYPTO, reason="x" * 501).status_code == 422
    )


def test_all_or_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    deposit, back, refund = _fp(client, DEPOSIT), _fp(client, BACK), _fp(client, REFUND)
    real = corrections.set_transaction_category
    calls: list[str] = []

    def failing(conn, fingerprint, category):  # noqa: ANN001, ANN202
        calls.append(fingerprint)
        if len(calls) == 2:
            raise ValueError("made-up failure")
        return real(conn, fingerprint, category)

    monkeypatch.setattr(corrections, "set_transaction_category", failing)
    response = _batch(client, [deposit, back, refund], categories.CRYPTO, reason="x")
    assert response.status_code == 422
    assert calls == [deposit, back]
    assert [_tx(client, fp)["category"] for fp in (deposit, back, refund)] == [
        categories.OTHER_INCOME,
        categories.OTHER_INCOME,
        categories.OTHER_INCOME,
    ]
    assert _log(client) == []


def _note_rows(tmp_path: Path, fps: list[str]) -> dict[str, tuple]:
    """The `transaction_notes` rows (the `client` fixture's database, in `tmp_path`)."""
    with closing(db.connect(tmp_path / "michelito.db")) as conn:
        marks = ", ".join("?" * len(fps))
        rows = conn.execute(
            "SELECT fingerprint, category_id, one_off, note FROM transaction_notes "
            f"WHERE fingerprint IN ({marks})",
            fps,
        )
        return {r[0]: (r[1], r[2], r[3]) for r in rows}


def test_undo_restores_each_previous_correction_exactly(client: TestClient, tmp_path: Path) -> None:
    bare, noted, salary = _fp(client, DEPOSIT), _fp(client, BACK), _fp(client, REFUND)
    _patch(client, noted, note="from Pedro")  # row without a category
    _patch(client, salary, category_id=_category_id(client, categories.SALARY))
    before = _note_rows(tmp_path, [bare, noted, salary])
    assert bare not in before and before[noted][0] is None

    entry = _batch(client, [bare, noted, salary], categories.CRYPTO, reason="P2P").json()[
        "entry_id"
    ]
    batch = next(e for e in _log(client) if e["id"] == entry)
    assert batch["before"]["text"] == f"{categories.OTHER_INCOME}, {categories.SALARY}"
    # After the batch: a note and a one-off mark that undoing the batch must not touch.
    _patch(client, bare, note="later")
    _patch(client, salary, one_off=True)

    undone = _undo(client, entry)
    assert undone.status_code == 200
    assert (undone.json()["id"], undone.json()["undone"]) == (entry, True)
    after = _note_rows(tmp_path, [bare, noted, salary])
    crypto_id = _category_id(client, categories.CRYPTO)
    assert all(row[0] != crypto_id for row in after.values())
    assert after[bare] == (None, 0, "later")
    assert after[noted] == before[noted]
    assert after[salary] == (before[salary][0], 1, None)
    assert [_tx(client, fp)["category"] for fp in (bare, noted, salary)] == [
        categories.OTHER_INCOME,
        categories.OTHER_INCOME,
        categories.SALARY,
    ]
    # One row: the batch, now undone (its undo is an audit record under it).
    assert _batch_entries(client) == 1


def test_undo_without_later_edits_removes_the_new_rows(client: TestClient, tmp_path: Path) -> None:
    bare, back = _fp(client, DEPOSIT), _fp(client, BACK)
    entry = _batch(client, [bare, back], categories.CRYPTO).json()["entry_id"]
    assert _undo(client, entry).status_code == 200
    assert _note_rows(tmp_path, [bare, back]) == {}


def test_undo_is_blocked_if_one_changed_later(client: TestClient) -> None:
    bare, back = _fp(client, DEPOSIT), _fp(client, BACK)
    entry = _batch(client, [bare, back], categories.CRYPTO).json()["entry_id"]
    _patch(client, back, category_id=_category_id(client, categories.SALARY))
    later = _log(client)[0]
    batch = next(e for e in _log(client) if e["id"] == entry)
    assert (batch["can_undo"], batch["blocked_by"]) == (False, later["id"])
    blocked = _undo(client, entry)
    assert blocked.status_code == 409 and str(later["id"]) in blocked.json()["detail"]
    assert _tx(client, bare)["category"] == categories.CRYPTO
    assert _undo(client, later["id"]).status_code == 200
    assert _undo(client, entry).status_code == 200
    assert [_tx(client, fp)["category"] for fp in (bare, back)] == [categories.OTHER_INCOME] * 2


def _batch_entries(client: TestClient) -> int:
    return sum(1 for e in _log(client) if e["kind"] == batch_edit.BATCH_KIND)


def test_crypto_is_its_own_income_in_summary_reports_and_dossier(
    client: TestClient, tmp_path: Path
) -> None:
    deposit, back = _fp(client, DEPOSIT), _fp(client, BACK)
    assert _batch(client, [deposit, back], categories.CRYPTO).status_code == 200

    summary = client.get("/api/summary", params={"month": MONTH}).json()
    lines = {i["category"]: i for i in summary["incomes"]}
    assert (lines[categories.CRYPTO]["amount_cents"], lines[categories.CRYPTO]["count"]) == (
        1_500_000,
        2,
    )
    assert categories.OTHER_INCOME in lines
    assert sum(i["amount_cents"] for i in summary["incomes"]) == summary["income_cents"]

    compare = client.get("/api/reports/compare").json()
    rows = {r["key"]: r for r in compare["incomes"]}
    months = [m["month"] for m in compare["months"]]
    crypto = rows[f"income:{categories.CRYPTO}"]
    assert crypto["label"] == categories.CRYPTO
    assert crypto["cells"][months.index(MONTH)]["amount_cents"] == 1_500_000
    assert f"income:{categories.OTHER_INCOME}" in rows
    assert [r["key"] for r in compare["totals"]] == ["income", "expenses", "third_party", "net"]

    with closing(db.connect(tmp_path / "michelito.db")) as conn:
        found = dossier.build(conn, MONTH)
        other = [m for m in months if m != MONTH]
        without = dossier.build(conn, other[0]) if other else None
    assert found.data["totals"]["crypto_income"] == "15000.00"
    assert f"{t('dossier.total.crypto_income')}: 15000.00" in found.markdown
    if without is not None:  # a month without crypto does not change (nor its fingerprint)
        assert "crypto_income" not in without.data["totals"]


def _review(client: TestClient, kind: str) -> list[dict]:
    items = client.get("/api/review", params={"month": MONTH}).json()
    return [i for i in items if i["kind"] == kind]


def test_a_later_batch_stops_the_rule_suggestion_and_the_hint(client: TestClient) -> None:
    first, second, third = _fps(client, DELIVERY)
    _patch(client, first, category_id=_category_id(client, categories.HEALTH))
    _patch(client, second, category_id=_category_id(client, categories.HEALTH))
    assert len(_review(client, "possible_rule")) == 1
    assert client.get(f"/api/transactions/{third}/history").json()["rule_hint"] is not None

    assert _batch(client, [first, second], categories.RESTAURANTS).status_code == 200
    assert _review(client, "possible_rule") == []
    assert client.get(f"/api/transactions/{third}/history").json()["rule_hint"] is None


def test_batches_never_reach_the_rule_minimum(client: TestClient) -> None:
    first, second, _ = _fps(client, DELIVERY)
    assert _batch(client, [first, second], categories.HEALTH).status_code == 200
    assert _review(client, "possible_rule") == []


def test_a_batch_on_another_transaction_of_the_merchant_contradicts_too(
    client: TestClient,
) -> None:
    first, second, third = _fps(client, DELIVERY)
    health = _category_id(client, categories.HEALTH)
    _patch(client, first, category_id=health)
    _patch(client, second, category_id=health)
    entry = _batch(client, [third], categories.RESTAURANTS).json()["entry_id"]
    assert _review(client, "possible_rule") == []
    assert _undo(client, entry).status_code == 200  # undone, no longer contradicts
    assert len(_review(client, "possible_rule")) == 1


def test_cash_box_entries_follow_the_cash_box_category_rule(client: TestClient) -> None:
    body = {"kind": "expense", "day": "2026-01-15", "amount_cents": 50000, "currency": "DOP"}
    assert client.post("/api/cash-box/entries", json=body, headers=WRITE).status_code == 201
    income = {**body, "kind": "income", "day": "2026-01-16"}
    assert client.post("/api/cash-box/entries", json=income, headers=WRITE).status_code == 201
    out, came_in = "cash-1", "cash-2"
    assert _tx(client, out)["amount_cents"] > 0 > _tx(client, came_in)["amount_cents"]

    to_income = _batch(client, [out, came_in], categories.CRYPTO).json()
    assert to_income["applied"] == [came_in]
    assert [(s["fingerprint"], s["reason"]) for s in to_income["skipped"]] == [(out, "cash_box")]
    to_expense = _batch(client, [out, came_in], categories.DELIVERY).json()
    assert to_expense["applied"] == [out]
    assert [(s["fingerprint"], s["reason"]) for s in to_expense["skipped"]] == [
        (came_in, "cash_box")
    ]
    to_transfer = _batch(client, [out], categories.OWN_TRANSFER).json()
    assert [s["reason"] for s in to_transfer["skipped"]] == ["cash_box"]

    # A single one, from its detail view: same rule.
    single = _patch(client, out, category_id=_category_id(client, categories.SALARY))
    assert single.status_code == 422 and "caja fuerte" in single.json()["detail"]  # spanish-ui
    assert (
        _patch(client, out, category_id=_category_id(client, categories.RESTAURANTS)).status_code
        == 200
    )
