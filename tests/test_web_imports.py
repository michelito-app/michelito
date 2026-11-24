"""AI imports (`web.imports`, applied through `web.proposal_routes`) on the local board with the
synthetic statements: statements that must square, loose provisional charges with their
duplicates, and cash entries. Every amount and description is made up."""

from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from michelito import db
from michelito.analysis import catalog, spending
from michelito.web import imports
from michelito.web.app import create_app
from michelito.web.imports import RowIn
from michelito.web.proposals import ProposalError
from tests.test_spending import seed

WRITE = {"X-Michelito": "1"}
TODAY = date(2026, 4, 15)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    found = tmp_path / "michelito.db"
    with closing(db.connect(found)) as conn:
        seed(conn)
    return found


@pytest.fixture
def board(path: Path) -> TestClient:
    return TestClient(create_app(path, today=lambda: TODAY), "http://127.0.0.1")


def _key(path: Path, kind: str) -> str:
    with closing(db.connect(path)) as conn:
        return str(conn.execute("SELECT key FROM accounts WHERE kind = ?", (kind,)).fetchone()[0])


def _flow(conn) -> list[spending.Movement]:  # noqa: ANN001
    return list(spending.load_all(conn, (), None, TODAY))


def _savings_statement(debit: int = 10000, closing_cents: int = 90000) -> dict[str, Any]:
    return {
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
        "sections": [
            {
                "currency": "DOP",
                "previous_balance_cents": 100000,
                "closing_balance_cents": closing_cents,
                "printed_debits_cents": debit,
                "printed_credits_cents": 0,
                "transactions": [
                    {
                        "day": "2026-03-10",
                        "description": "MADE UP STORE",
                        "amount_cents": 10000,
                        "direction": "debit",
                    }
                ],
            }
        ],
    }


def _propose_statement(path: Path, payload: dict[str, Any]) -> int:
    with closing(db.connect(path)) as conn:
        return imports.propose_statement(
            conn, TODAY, "Claude", "Statement", "", _key(path, "savings"), payload
        )


# Statements.


def test_a_statement_that_squares_is_stored_once_approved(path: Path, board: TestClient) -> None:
    proposal_id = _propose_statement(path, _savings_statement())
    (shown,) = board.get("/api/proposals").json()
    assert shown["kind"] == "statement" and shown["statement"]["transactions"] == 1
    assert shown["account_label"]

    answer = board.post(f"/api/proposals/{proposal_id}/apply", json={"item_ids": []}, headers=WRITE)

    assert answer.status_code == 200, answer.text
    assert answer.json()["statement"]["document_status"] == "parsed"
    with closing(db.connect(path)) as conn:
        stored = conn.execute(
            "SELECT s.parser FROM statements s WHERE s.period_end = '2026-03-31'"
        ).fetchone()
    assert stored[0] == imports.PARSER


def test_a_statement_that_does_not_square_is_refused_with_why(path: Path) -> None:
    with pytest.raises(ProposalError) as error:
        _propose_statement(path, _savings_statement(debit=12000))

    assert error.value.code == "not_squared"
    assert "debits" in error.value.detail and "120.00" in error.value.detail


def test_a_statement_without_totals_is_refused(path: Path) -> None:
    payload = _savings_statement()
    section = payload["sections"][0]
    for name in ("previous_balance_cents", "closing_balance_cents"):
        section.pop(name)
    section.pop("printed_debits_cents")
    section.pop("printed_credits_cents")

    with pytest.raises(ProposalError) as error:
        _propose_statement(path, payload)

    assert error.value.code == "not_squared"


def test_a_stored_statement_is_a_duplicate(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        cut = conn.execute(
            "SELECT s.period_end, s.currency FROM statements s JOIN accounts a "
            "ON a.id = s.account_id WHERE a.kind = 'savings' LIMIT 1"
        ).fetchone()
    payload = _savings_statement()
    payload["period_end"] = cut[0]
    payload["period_start"] = None
    payload["sections"][0]["currency"] = cut[1]
    payload["sections"][0]["transactions"][0]["day"] = cut[0]

    with pytest.raises(ProposalError) as error:
        _propose_statement(path, payload)

    assert error.value.code == "duplicate_statement"


def test_only_existing_accounts(path: Path) -> None:
    with closing(db.connect(path)) as conn, pytest.raises(ProposalError) as error:
        imports.propose_statement(conn, TODAY, "Claude", "x", "", "nope:savings:1", {})

    assert error.value.code == "unknown_account"


# Provisional charges.


def test_provisional_charges_flag_duplicates_and_become_pending(
    path: Path, board: TestClient
) -> None:
    key = _key(path, "credit_card")
    with closing(db.connect(path)) as conn:
        stored = next(m for m in _flow(conn) if m.account == key and m.amount > 0)
        rows = [
            RowIn(stored.day, "SAME AS STORED", int(stored.amount * 100), stored.currency, "out"),
            RowIn(date(2026, 4, 2), "MADE UP COFFEE", 25050, "DOP", "out"),
        ]
        today = stored.day + timedelta(days=30)
        rows[1] = RowIn(today, "MADE UP COFFEE", 25050, "DOP", "out")
        proposal_id = imports.propose_rows(
            conn, _flow(conn), today, "Claude", "Charges", "", "provisional", key, rows
        )
    month = rows[1].day.isoformat()[:7]
    shown = board.get("/api/proposals").json()[0]
    first, second = shown["rows"]
    assert first["duplicate_of"] == stored.fingerprint
    assert second["duplicate_of"] == ""

    answer = board.post(
        f"/api/proposals/{proposal_id}/apply", json={"item_ids": [second["id"]]}, headers=WRITE
    )

    assert answer.status_code == 200, answer.text
    done = {r["id"]: r["status"] for r in answer.json()["rows"]}
    assert done == {first["id"]: "skipped", second["id"]: "applied"}
    pending = board.get("/api/transactions", params={"month": month, "provisional": True})
    assert [i["description"] for i in pending.json()["items"]] == ["MADE UP COFFEE"]


def test_provisional_rows_are_only_charges(path: Path) -> None:
    key = _key(path, "credit_card")
    with closing(db.connect(path)) as conn, pytest.raises(ProposalError) as error:
        imports.propose_rows(
            conn,
            _flow(conn),
            TODAY,
            "Claude",
            "x",
            "",
            "provisional",
            key,
            [RowIn(date(2026, 4, 2), "REFUND", 100, "DOP", "in")],
        )

    assert error.value.code == "provisional_charges_only"


def test_rows_in_the_future_are_refused(path: Path) -> None:
    with closing(db.connect(path)) as conn, pytest.raises(ProposalError) as error:
        imports.propose_rows(
            conn,
            _flow(conn),
            TODAY,
            "Claude",
            "x",
            "",
            "cash",
            "",
            [RowIn(date(2026, 5, 30), "LATER", 100, "DOP", "out")],
        )

    assert error.value.code == "day"


# Cash.


def test_cash_entries_go_through_the_cash_route(path: Path, board: TestClient) -> None:
    with closing(db.connect(path)) as conn:
        expense = next(c.id for c in catalog.load(conn).items if c.kind == "expense")
        rows = [RowIn(date(2026, 4, 3), "MADE UP MARKET", 50000, "DOP", "out", expense)]
        proposal_id = imports.propose_rows(
            conn, _flow(conn), TODAY, "Claude", "Cash", "", "cash", "", rows
        )
    row = board.get("/api/proposals").json()[0]["rows"][0]

    answer = board.post(
        f"/api/proposals/{proposal_id}/apply", json={"item_ids": [row["id"]]}, headers=WRITE
    )

    assert answer.json()["rows"][0]["status"] == "applied", answer.text
    entries = board.get("/api/transactions", params={"month": "2026-04", "q": "MADE UP MARKET"})
    (found,) = entries.json()["items"]
    assert found["category_id"] == expense
    assert board.get("/api/log").json()["items"][0]["author"] == "claude"


def test_a_cash_category_must_fit_the_direction(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        income = next(c.id for c in catalog.load(conn).items if c.kind == "income")
        with pytest.raises(ProposalError) as error:
            imports.propose_rows(
                conn,
                _flow(conn),
                TODAY,
                "Claude",
                "x",
                "",
                "cash",
                "",
                [RowIn(date(2026, 4, 3), "MARKET", 100, "DOP", "out", income)],
            )

    assert error.value.code == "category"


def test_schema_29_applies_twice(path: Path) -> None:
    from michelito import migrations_v29

    with closing(db.connect(path)) as conn, conn:
        migrations_v29.apply(conn)
        migrations_v29.apply(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_proposals)")}

    assert {"kind", "account_key"} <= columns


def test_movements_outside_the_period_are_refused(path: Path) -> None:
    payload = _savings_statement()
    payload["sections"][0]["transactions"][0]["day"] = "2026-05-10"

    with pytest.raises(ProposalError) as error:
        _propose_statement(path, payload)

    assert error.value.code == "day"


def test_a_currency_the_account_never_had_is_refused(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        used = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT s.currency FROM statements s JOIN accounts a "
                "ON a.id = s.account_id WHERE a.kind = 'savings'"
            )
        }
    payload = _savings_statement()
    payload["sections"][0]["currency"] = next(c for c in ("USD", "DOP") if c not in used)

    with pytest.raises(ProposalError) as error:
        _propose_statement(path, payload)

    assert error.value.code == "currency"


def test_the_same_statement_cannot_wait_twice(path: Path) -> None:
    _propose_statement(path, _savings_statement())

    with pytest.raises(ProposalError) as error:
        _propose_statement(path, _savings_statement())

    assert error.value.code == "already_proposed"


def test_unknown_fields_and_cards_are_refused(path: Path) -> None:
    payload = _savings_statement()
    payload["sections"][0]["transactions"][0]["extra"] = 1
    with pytest.raises(ProposalError) as error:
        _propose_statement(path, payload)
    assert error.value.code == "transaction"

    card = _key(path, "credit_card")
    with closing(db.connect(path)) as conn, pytest.raises(ProposalError) as error:
        imports.propose_statement(
            conn, TODAY, "Claude", "x", "", card, {**_savings_statement(), "card_last4": "0000"}
        )
    assert error.value.code == "card_last4"


def test_old_pending_charges_are_refused(path: Path) -> None:
    key = _key(path, "credit_card")
    with closing(db.connect(path)) as conn, pytest.raises(ProposalError) as error:
        imports.propose_rows(
            conn,
            _flow(conn),
            TODAY,
            "Claude",
            "x",
            "",
            "provisional",
            key,
            [RowIn(TODAY - timedelta(days=200), "OLD", 100, "DOP", "out")],
        )

    assert error.value.code == "too_old_for_pending"


def test_review_shows_totals_and_whether_the_balance_continues(
    path: Path, board: TestClient
) -> None:
    with closing(db.connect(path)) as conn:
        last = conn.execute(
            "SELECT s.closing_balance_cents FROM statements s JOIN accounts a "
            "ON a.id = s.account_id WHERE a.kind = 'savings' AND s.currency = 'DOP' "
            "ORDER BY s.period_end DESC LIMIT 1"
        ).fetchone()[0]
    payload = _savings_statement()
    section = payload["sections"][0]
    section["previous_balance_cents"] = last
    section["closing_balance_cents"] = last - 10000
    _propose_statement(path, payload)

    (shown,) = board.get("/api/proposals").json()[0]["statement"]["sections"]

    assert shown["continues"] is True
    assert shown["debits_cents"] == 10000 and shown["closing_cents"] == last - 10000
