"""Fixes from the review of the cash account (schema 23): a schedule whose category changed kind,
edits that must not back-fill, provisional alerts, undo of the first change, undo of a schedule
with later occurrences, the reconcile balance, the CLI pass, stale insights, far starts,
duplicate counts, the pass marker and the local date. Synthetic data only."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from michelito import config, db
from michelito.analysis import (
    cash_activation,
    cash_box_store,
    cash_schedule,
    links,
    live_store,
    spending,
)
from michelito.analysis.cash_schedule import Schedule
from michelito.analysis.spending import Movement
from michelito.web.app import create_app
from tests.test_web_efectivo import (
    LATE_WITHDRAWAL,
    WRITE,
    Clock,
    _answer,
    _balance,
    _box,
    _entry,
    _last_log,
    _schedule,
    _summary,
    _tx,
    _undo,
)
from tests.test_web_efectivo import (
    client as client,  # noqa: F401 (fixture)
)
from tests.test_web_efectivo import (
    clock as clock,  # noqa: F401 (fixture)
)
from tests.test_web_efectivo import (
    path as path,  # noqa: F401 (fixture)
)


def _occurrence_days(client: TestClient) -> list[str]:
    return sorted(line["day"] for line in _box(client)["lines"] if line["schedule_id"])


# --- C1: a schedule's category changed kind --------------------------------------------------


def test_a_schedule_whose_category_changed_kind_breaks_nothing(
    client: TestClient, clock: Clock
) -> None:
    made = client.post(
        "/api/categories", json={"name": "Housekeeping", "kind": "expense"}, headers=WRITE
    ).json()
    _schedule(client, frequency="weekly", start_day="2026-02-07", category_id=made["id"])
    changed = client.patch(f"/api/categories/{made['id']}", json={"kind": "income"}, headers=WRITE)
    assert changed.status_code == 200, changed.text
    clock.day = date(2026, 2, 14)
    for url in ("/api/cash-box", "/api/summary", "/api/categories"):
        assert client.get(url).status_code == 200, url
    assert _occurrence_days(client) == ["2026-02-07", "2026-02-14"]


def test_a_failing_pass_never_breaks_the_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args, **_kwargs) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(cash_activation, "refresh", broken)
    assert client.get("/api/cash-box").status_code == 200


# --- H1: editing does not back-fill --------------------------------------------------------


def test_a_later_start_does_not_back_fill(client: TestClient) -> None:
    box = _schedule(client, frequency="monthly", start_day="2025-11-05")
    schedule = box["schedules"][0]["id"]
    assert len(_occurrence_days(client)) == 4  # 11-05, 12-05, 01-05, 02-05
    body = {
        "kind": "payment",
        "concept": "Cleaning",
        "amount_cents": 300_000,
        "currency": "DOP",
        "frequency": "monthly",
        "start_day": "2025-11-10",
    }
    client.put(f"/api/cash-box/schedules/{schedule}", json=body, headers=WRITE)
    assert len(_occurrence_days(client)) == 4
    weekly = {**body, "frequency": "weekly", "start_day": "2025-11-05"}
    client.put(f"/api/cash-box/schedules/{schedule}", json=weekly, headers=WRITE)
    assert len(_occurrence_days(client)) == 4  # no past weeks created


def test_after_an_edit_the_next_dates_still_come(client: TestClient, clock: Clock) -> None:
    box = _schedule(client, frequency="weekly", start_day="2026-02-06")
    schedule = box["schedules"][0]["id"]
    body = {
        "kind": "payment",
        "concept": "Cleaning",
        "amount_cents": 300_000,
        "currency": "DOP",
        "frequency": "monthly",
        "start_day": "2026-01-01",
    }
    client.put(f"/api/cash-box/schedules/{schedule}", json=body, headers=WRITE)
    clock.day = date(2026, 3, 1)
    assert _occurrence_days(client) == ["2026-02-06", "2026-03-01"]


# --- H2: provisional ATM alerts ------------------------------------------------------------


def _move(fingerprint: str, provisional: bool) -> Movement:
    return Movement(
        day=date(2026, 2, 10),
        merchant="ATM",
        description="RETIRO CAJERO INVENTADO",
        category="Efectivo",  # spanish-data
        amount=Decimal(500),
        currency="DOP",
        institution="x",
        fingerprint=fingerprint,
        account="bank",
        provisional=provisional,
    )


def test_provisional_alerts_are_not_moved_into_cash() -> None:
    flow = [_move("alert-1", True), _move("row-1", False)]
    found = cash_activation.auto_candidates(flow, links.NONE, date(2026, 1, 1), frozenset())
    assert found == ["row-1"]


def test_discarding_a_provisional_drops_a_system_mark(path: Path) -> None:
    with closing(db.connect(path)) as conn, conn:
        cash_box_store.store(conn, "alert-7")
        cash_activation.record_auto(conn, ["alert-7"])
        assert not live_store.is_linked(conn, "alert-7")
        live_store.decide(conn, "alert-7", "discard", "2026-02-10T00:00:00+00:00")
        assert conn.execute("SELECT COUNT(*) FROM link_members").fetchone()[0] == 0


def test_a_hand_stored_provisional_says_it_is_in_cash(client: TestClient, path: Path) -> None:
    with closing(db.connect(path)) as conn, conn:
        cash_box_store.store(conn, "alert-9")
        assert live_store.is_linked(conn, "alert-9")


# --- H3: undoing the first change ---------------------------------------------------------


def test_the_first_change_undoes_after_an_automatic_withdrawal(
    client: TestClient, clock: Clock
) -> None:
    clock.day = date(2026, 2, 5)
    _entry(
        client, kind="expense", day="2026-02-05", amount_cents=100, currency="DOP", concept="Tip"
    )
    assert _tx(client, "2026-02", LATE_WITHDRAWAL)["cash_box_role"] == "stored"
    first = _last_log(client)
    response = client.post(f"/api/log/{first['id']}/undo", headers=WRITE)
    assert response.status_code == 200, response.text
    assert _tx(client, "2026-02", LATE_WITHDRAWAL)["cash_box_role"] == "stored"


# --- M1: undoing a schedule with later occurrences ------------------------------------------


def test_undoing_a_schedule_drops_its_pending_occurrences(client: TestClient, clock: Clock) -> None:
    spent = _summary(client, "2026-02")["total_cents"]
    _schedule(client, frequency="weekly", start_day="2026-02-07")
    created = _last_log(client)
    clock.day = date(2026, 2, 14)
    assert len(_box(client)["occurrences"]) == 2  # the second one, outside the change
    _undo(client, created["id"])
    box = _box(client)
    assert (box["schedules"], box["occurrences"]) == ([], [])
    assert _summary(client, "2026-02")["total_cents"] == spent


def test_a_deleted_schedule_keeps_its_answered_and_waiting_occurrences(client: TestClient) -> None:
    box = _schedule(client, frequency="weekly", start_day="2026-01-31")
    first, second = (o["entry_id"] for o in box["occurrences"])
    _answer(client, first, "confirm")
    schedule = box["schedules"][0]["id"]
    client.delete(f"/api/cash-box/schedules/{schedule}", headers=WRITE)
    box = _box(client)
    assert [o["entry_id"] for o in box["occurrences"]] == [second]
    assert _answer(client, second, "confirm")["occurrences"] == []
    assert len([line for line in _box(client)["lines"] if line["kind"] == "expense"]) == 2


# --- M2: the reconcile compares with today's balance ----------------------------------------


def test_the_box_says_the_balance_up_to_today(client: TestClient) -> None:
    _entry(client, kind="initial", day="2026-01-01", amount_cents=100_000, currency="DOP")
    box = _entry(
        client,
        kind="expense",
        day="2026-03-01",
        amount_cents=30_000,
        currency="DOP",
        concept="Rent",
    )
    assert _balance(box) == 70_000
    assert box["balances_today"] == [{"currency": "DOP", "amount_cents": 100_000}]
    body = {"counts": [{"currency": "DOP", "amount_cents": 100_000}]}
    same = client.post("/api/cash-box/reconcile", json=body, headers=WRITE).json()
    assert len(same["lines"]) == len(box["lines"])


# --- LOW --------------------------------------------------------------------------------


def test_next_due_finds_a_start_years_ahead() -> None:
    far = Schedule(
        id=1,
        kind="payment",
        concept="Fee",
        amount=Decimal(1),
        currency="DOP",
        category_id=None,
        frequency="monthly",
        start=date(2030, 5, 5),
    )
    assert cash_schedule.next_due(far, date(2026, 1, 1)) == date(2030, 5, 5)


def test_a_reconcile_with_a_repeated_currency_is_refused(client: TestClient) -> None:
    body = {
        "counts": [
            {"currency": "DOP", "amount_cents": 100},
            {"currency": "DOP", "amount_cents": 200},
        ]
    }
    assert client.post("/api/cash-box/reconcile", json=body, headers=WRITE).status_code == 422


def test_the_marker_changes_with_holders_and_rebuilt_rows(path: Path) -> None:
    with closing(db.connect(path)) as conn:
        before = cash_activation.marker(conn, "holders-a")
        assert cash_activation.marker(conn, "holders-b") != before
        with conn:
            conn.execute("UPDATE transactions SET amount_cents = amount_cents + 1 WHERE id = 1")
        assert cash_activation.marker(conn, "holders-a") != before


def test_the_pass_takes_no_write_lock_when_nothing_changed(path: Path) -> None:
    today = date(2026, 2, 7)
    with closing(db.connect(path)) as conn:
        with conn:
            cash_activation.activate(conn, today)
        load = lambda c: spending.load_all(c, (), None, today)  # noqa: E731
        cash_activation.refresh(conn, today, load)
        with closing(sqlite3.connect(path)) as other:
            other.execute("BEGIN IMMEDIATE")  # another writer holds the lock
            cash_activation.refresh(conn, today, load)  # read-only: does not wait
            other.rollback()


def test_today_is_the_local_date_not_the_server_s(monkeypatch: pytest.MonkeyPatch) -> None:
    late = datetime(2026, 2, 21, 3, 30, tzinfo=UTC)  # 23:30 on the 20th in Santo Domingo
    monkeypatch.delenv(config.TIMEZONE_ENV, raising=False)
    assert config.local_today(late) == date(2026, 2, 20)
    monkeypatch.setenv(config.TIMEZONE_ENV, "UTC")
    assert config.local_today(late) == date(2026, 2, 21)


def test_the_app_uses_the_local_date_by_default(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "local_today", lambda now=None: date(2026, 2, 20))
    client = TestClient(create_app(path), "http://127.0.0.1")
    box = client.post(
        "/api/cash-box/schedules",
        json={
            "kind": "payment",
            "concept": "Cleaning",
            "amount_cents": 100,
            "currency": "DOP",
            "frequency": "weekly",
            "start_day": "2026-02-20",
        },
        headers=WRITE,
    ).json()
    assert [o["day"] for o in box["occurrences"]] == ["2026-02-20"]
    with closing(db.connect(path)) as conn:
        assert cash_activation.activated_on(conn) == date(2026, 2, 20)


# --- M3: the CLI runs the pass ------------------------------------------------------------


def test_the_cli_opens_the_database_with_the_pass_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from michelito import cli, cli_insights, cli_log
    from michelito.analysis import cash_schedule_store

    paths = config.Paths(tmp_path)
    monkeypatch.setattr(config, "local_today", lambda now=None: date(2026, 2, 7))
    with closing(db.connect(paths.database)) as conn, conn:
        draft = cash_schedule_store.ScheduleDraft(
            "payment", "Cleaning", Decimal(30), "DOP", None, "weekly", date(2026, 1, 24)
        )
        cash_schedule_store.add(conn, draft, date(2026, 1, 24))
    for opener in (cli._open_db, cli_insights._open, cli_log._open):
        with closing(opener(paths)) as conn:
            days = [row[0] for row in conn.execute("SELECT day FROM cash_entries ORDER BY day")]
        assert days == ["2026-01-24", "2026-01-31", "2026-02-07"]


# --- M4: insights saved under schemas 18-21 -----------------------------------------------


def _v17(tmp_path: Path) -> Path:
    found = tmp_path / "v17.db"
    fixtures = Path(__file__).parent / "fixtures"
    with closing(sqlite3.connect(found)) as raw:
        raw.executescript((fixtures / "schema_v17.sql").read_text(encoding="utf-8"))
    return found


def test_an_insight_saved_with_the_old_cash_names_stays_fresh(tmp_path: Path) -> None:
    from michelito import dossier
    from michelito.analysis import insights
    from michelito.analysis.accounts import CASH_BOX_KEY

    with closing(db.connect(_v17(tmp_path))) as conn:
        built = dossier.build(conn, "2026-01", accounts=[CASH_BOX_KEY])
        assert built.renamed == {"account", "category", "descriptions"}
        # What schemas 18-21 wrote: the same data with the old names (by hand, not the helper).
        # spanish-data: begin
        old = {"Efectivo": "Caja fuerte", "Pasado a efectivo": "Caja fuerte",
               "Salida en efectivo": "Salida de la caja fuerte",
               "Entrada en efectivo": "Entrada a la caja fuerte"}  # fmt: skip
        # spanish-data: end
        before = {
            **built.data,
            "accounts": [old.get(a, a) for a in built.data["accounts"]],
            "coverage": [
                {**c, "account": old.get(c["account"], c["account"])}
                for c in built.data["coverage"]
            ],
            "transactions": [
                {
                    **row,
                    "account": old.get(row.get("account"), row.get("account")),
                    "category": old.get(row.get("category"), row.get("category"))
                    if row.get("category") != "Efectivo"  # spanish-data: the spending one stays
                    else row.get("category"),
                    "description": old.get(row.get("description"), row.get("description")),
                }
                for row in built.data["transactions"]
            ],
        }  # fmt: skip
        saved = dossier.data_hash(before)
        assert saved != built.data_hash
        assert saved in built.older_hashes
        found = insights.Insight(
            month="2026-01",
            text="x",
            data_hash=saved,
            accounts=None,
            created_at="x",
            updated_at="x",
        )
        assert insights.is_fresh(conn, found, built.data_hash, lambda: built.older_hashes)


def test_without_a_rename_an_account_named_like_cash_keeps_its_hash(tmp_path: Path) -> None:
    from michelito import dossier

    with closing(db.connect(_v17(tmp_path))) as conn:
        with conn:
            conn.execute("DELETE FROM cash_renames")
        built = dossier.build(conn, "2026-01")
        assert built.renamed == frozenset()
        assert built.older_hashes == (built.legacy_hash,)
