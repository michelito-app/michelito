"""Live sync: alerts become provisional transactions, statements confirm them."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from michelito import db
from michelito.analysis import (
    categories,
    changelog,
    corrections,
    live_match,
    live_store,
    spending,
)
from michelito.analysis.live_match import Candidate, Open, match
from michelito.parsers.common import validate_statement
from tests import alert_samples as samples
from tests.ledger_helpers import share
from tests.live_helpers import NOW, alert, card_statement, ingest_card, known_card, status
from tests.live_helpers import row as statement_row


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def _flow(conn: sqlite3.Connection) -> dict[str, spending.Movement]:
    return {m.fingerprint: m for m in spending.load_all(conn)}


def test_an_approved_alert_on_a_known_card_is_a_provisional_transaction(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="1,250.00", day="14/02/2026", merchant="SUPERMERCADO FICTICIO")
    assert status(conn, mark) == "provisional"
    found = _flow(conn)[mark]
    assert found.provisional
    assert (found.amount, found.currency, found.day) == (
        Decimal("1250.00"),
        "DOP",
        date(2026, 2, 14),
    )
    assert found.account == "popular:credit_card"
    assert found.kind == "expense"
    assert found.merchant == "SUPERMERCADO FICTICIO"


def test_the_same_message_twice_stores_one_alert(conn) -> None:
    known_card(conn)
    alert(conn, "a1")
    alert(conn, "a1")
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1
    assert sum(1 for m in spending.load_all(conn) if m.provisional) == 1
    assert "a1" in live_store.known_message_ids(conn)


def test_a_failed_alert_keeps_a_data_free_fingerprint_and_is_retried_after_a_parser_change(
    conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    known_card(conn)
    bad = samples.alert_email("a1", html=samples.alert_html(currency="EUR"))
    with conn:
        assert live_store.record(conn, bad, "popular_alerts", NOW) == "failed"
    assert "a1" in live_store.known_message_ids(conn)  # the same parser would fail again
    monkeypatch.setattr(live_store, "PARSER_VERSION", "next")
    assert "a1" not in live_store.known_message_ids(conn)  # downloaded again
    assert live_store.failures(conn)[0]["failed_field"] == "currency"
    stored = conn.execute("SELECT * FROM alerts").fetchone()
    assert stored["amount_cents"] is None and stored["merchant"] is None and stored["last4"] is None
    with conn:
        assert live_store.record(conn, samples.alert_email("a1"), "popular_alerts", NOW) == "stored"
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1


def test_an_unknown_card_is_held_not_guessed_until_a_statement_brings_it(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", card=samples.OTHER_CARD, day="12/02/2026")
    assert status(conn, mark) == "unknown_card"
    assert mark not in _flow(conn)
    # The new plastic's statement (dated after the alert window: it is not in it) makes it known.
    later = card_statement(
        "2026-02-28", [("2026-02-26", "OTRA TIENDA", "10.00")], samples.OTHER_CARD
    )  # spanish-data
    assert ingest_card(conn, later) == "parsed"
    assert status(conn, mark) == "provisional"
    assert _flow(conn)[mark].account == "popular:credit_card"


def test_an_unknown_status_is_held_and_never_counted(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", status=samples.UNKNOWN_STATUS)
    assert status(conn, mark) == "unknown_status"
    assert mark not in _flow(conn)


def test_an_alert_before_the_first_statement_is_history(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", day="20/12/2025")
    assert status(conn, mark) == "stale"
    assert mark not in _flow(conn)


def test_declined_and_reversed_alerts_never_create_transactions(conn) -> None:
    known_card(conn)
    alert(conn, "d1", status=samples.DECLINED, amount="80.00")
    alert(conn, "r1", status=samples.REVERSED, amount="90.00")
    assert not any(m.provisional for m in spending.load_all(conn))


def test_a_reversal_voids_its_provisional(conn) -> None:
    known_card(conn)
    bought = alert(conn, "a1", amount="2,000.00", day="10/02/2026", merchant="TIENDA FICTICIA")
    other = alert(conn, "a2", amount="2,000.00", day="11/02/2026", merchant="FERRETERIA FICTICIA")
    alert(conn, "r1", amount="2,000.00", day="12/02/2026", merchant="TIENDA FICTICIA",
          status=samples.REVERSED)  # fmt: skip
    decisions = live_store.decisions(conn)
    assert decisions.get(bought) == "void"
    assert other not in decisions  # merchant similarity picks the right one
    assert bought not in _flow(conn)
    assert other in _flow(conn)


def test_a_decline_never_voids_an_approved_purchase(conn) -> None:
    known_card(conn)
    bought = alert(conn, "a1", amount="300.00", day="10/02/2026")
    declined = alert(conn, "d1", amount="300.00", day="10/02/2026", status=samples.DECLINED)
    assert live_store.decisions(conn) == {}
    assert bought in _flow(conn)
    assert declined not in _flow(conn)  # a failed attempt: no transaction either
    assert status(conn, declined) == "declined"


def test_a_void_is_logged_and_its_undo_sticks(conn) -> None:
    known_card(conn)
    bought = alert(conn, "a1", amount="300.00", day="10/02/2026")
    alert(conn, "r1", amount="300.00", day="11/02/2026", status=samples.REVERSED)
    history = changelog.load(conn, fingerprint=bought)
    assert [e.kind for e in history] == ["provisional"]
    with conn:
        changelog.undo(conn, history[0].id)
    assert bought in _flow(conn)
    with conn:  # the reversal was used: reconciling again does not void it a second time
        live_match.reconcile(conn, NOW)
    assert bought in _flow(conn)


def test_a_held_alert_cancelled_by_a_reversal_is_voided(conn) -> None:
    known_card(conn)
    held = alert(conn, "a1", amount="300.00", card=samples.OTHER_CARD)
    alert(conn, "r1", amount="300.00", card=samples.OTHER_CARD, status=samples.REVERSED)
    assert status(conn, held) == "voided"


def test_provisionals_never_enter_a_statements_validation(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="700.00", day="05/02/2026", merchant="TIENDA FICTICIA")
    statement = card_statement("2026-02-28", [("2026-02-20", "OTRO COMERCIO", "100.00")])
    assert validate_statement(statement) == ()
    # Had the provisional been counted in the statement, its printed totals would not balance.
    section = statement.sections[0]
    with_provisional = replace(
        statement,
        sections=(
            replace(
                section,
                transactions=(
                    *section.transactions,
                    statement_row(("2026-02-05", "TIENDA", "700.00")),
                ),
            ),
        ),
    )
    assert validate_statement(with_provisional) != ()
    assert ingest_card(conn, statement) == "parsed"
    assert _flow(conn)[mark].provisional  # still counted, outside the statement


def _open(**fields: object) -> Open:
    base: dict[str, object] = {
        "id": 1,
        "account": "a",
        "day": date(2026, 2, 10),
        "amount_cents": 125000,
        "currency": "DOP",
        "merchant": "SUPERMERCADO FICTICIO",
        "last4": "5151",
    }
    return Open(**(base | fields))  # type: ignore[arg-type]


def _candidate(fp: str, **fields: object) -> Candidate:
    base: dict[str, object] = {
        "fingerprint": fp,
        "account": "a",
        "day": date(2026, 2, 10),
        "amount_cents": 125000,
        "currency": "DOP",
        "description": "SUPERMERCADO FICTICIO SANTO DOMINGO",
        "last4": "5151",
        "order": 0,
    }
    return Candidate(**(base | fields))  # type: ignore[arg-type]


@pytest.mark.parametrize(("offset", "matched"), [(-2, False), (-1, True), (5, True), (6, False)])
def test_the_window_runs_from_one_day_before_to_five_after(offset: int, matched: bool) -> None:
    day = date.fromordinal(date(2026, 2, 10).toordinal() + offset)
    found = match([_open()], [_candidate("x", day=day)])
    assert (1 in found) is matched


def test_the_amount_must_match_to_the_cent() -> None:
    assert match([_open()], [_candidate("x", amount_cents=125001)]) == {}
    assert match([_open()], [_candidate("x", currency="USD")]) == {}
    assert match([_open()], [_candidate("x", account="b")]) == {}


def test_ties_go_to_the_most_similar_merchant_then_the_closest_date() -> None:
    rows = [
        _candidate("pharmacy", description="FARMACIA FICTICIA", order=0),
        _candidate("market-far", day=date(2026, 2, 13), order=1),
        _candidate("market", day=date(2026, 2, 11), order=2),
    ]
    assert match([_open()], rows)[1].fingerprint == "market"
    # Two alerts of the same amount: each gets its own row.
    two = [_open(id=1), _open(id=2, merchant="FARMACIA FICTICIA")]
    found = match(two, rows)
    assert (found[1].fingerprint, found[2].fingerprint) == ("market", "pharmacy")


def test_a_statement_confirms_the_provisional_keeping_its_identity(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="1,250.00", day="14/02/2026", merchant="SUPERMERCADO FICTICIO")
    statement = card_statement(
        "2026-02-28",
        [
            ("2026-02-15", "SUPERMERCADO FICTICIO SANTO DOMINGO", "1250.00"),
            ("2026-02-16", "GASOLINERA FICTICIA", "900.00"),
        ],
    )
    assert ingest_card(conn, statement) == "parsed"
    assert status(conn, mark) == "confirmed"
    flow = _flow(conn)
    confirmed = flow[mark]
    assert not confirmed.provisional
    # The bank fields come from the statement.
    assert confirmed.description == "SUPERMERCADO FICTICIO SANTO DOMINGO"
    assert confirmed.day == date(2026, 2, 15)
    # Counted once.
    assert sum(1 for m in flow.values() if m.amount == Decimal("1250.00")) == 1
    assert not any(m.provisional for m in flow.values())


def test_a_late_alert_does_not_rename_a_statement_row(conn) -> None:
    known_card(conn)
    statement = card_statement("2026-02-28", [("2026-02-15", "TIENDA FICTICIA", "400.00")])
    ingest_card(conn, statement)
    before = {m.fingerprint for m in spending.load_all(conn)}
    mark = alert(conn, "a1", amount="400.00", day="14/02/2026", merchant="TIENDA FICTICIA")
    assert status(conn, mark) == "confirmed"
    assert {m.fingerprint for m in spending.load_all(conn)} == before


def test_usd_purchases_match_the_dollar_side(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="49.99", currency="US", day="09/02/2026",
                 merchant="TIENDA ONLINE FICTICIA")  # fmt: skip
    rd = alert(conn, "a2", amount="49.99", currency="RD", day="09/02/2026")
    statement = card_statement(
        "2026-02-28",
        [("2026-02-10", "TIENDA ONLINE FICTICIA", "49.99", "USD"), ("2026-02-11", "X", "1.00")],
    )
    ingest_card(conn, statement)
    assert status(conn, mark) == "confirmed"
    assert _flow(conn)[mark].currency == "USD"
    assert status(conn, rd) == "provisional"  # the RD$ 49.99 did not show up


def test_a_provisional_missing_from_its_statement_is_unmatched_until_decided(conn) -> None:
    known_card(conn)
    early = alert(conn, "a1", amount="333.00", day="05/02/2026")
    late = alert(conn, "a2", amount="444.00", day="26/02/2026")  # window not covered yet
    ingest_card(conn, card_statement("2026-02-28", [("2026-02-20", "OTRO", "1.00")]))
    assert live_store.unmatched(conn) == {early: date(2026, 2, 28)}
    assert late not in live_store.unmatched(conn)
    with conn:
        live_store.decide(conn, early, "keep", NOW)
    assert early in live_store.unmatched(conn)  # still missing; the review shows it as reviewed
    assert _flow(conn)[early].provisional
    with conn:
        live_store.decide(conn, early, "discard", NOW)
    assert early not in live_store.unmatched(conn)
    assert early not in _flow(conn)
    assert status(conn, early) == "provisional"  # never deleted: undo brings it back
    with conn:
        live_store.decide(conn, early, None, NOW)
    assert early in _flow(conn)


def test_a_discarded_provisional_is_not_confirmed(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="555.00", day="05/02/2026")
    with conn:
        live_store.decide(conn, mark, "discard", NOW)
    ingest_card(conn, card_statement("2026-02-28", [("2026-02-06", "X", "555.00")]))
    assert status(conn, mark) == "provisional"
    assert sum(1 for m in spending.load_all(conn) if m.amount == Decimal("555.00")) == 1


def test_merchant_rules_and_corrections_apply_to_provisionals(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", merchant="CAFETERIA FICTICIA")
    with conn:
        corrections.set_merchant_category(conn, "CAFETERIA FICTICIA", categories.RESTAURANTS)
    assert _flow(conn)[mark].ref == categories.RESTAURANTS


@pytest.mark.parametrize(("day", "matched"), [(9, False), (10, True), (16, True), (17, False)])
def test_the_window_edges_through_ingestion(conn, day: int, matched: bool) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="321.00", day="11/02/2026", merchant="TIENDA FICTICIA")
    row = (f"2026-02-{day:02d}", "TIENDA FICTICIA SD", "321.00")
    ingest_card(conn, card_statement("2026-02-28", [row]))
    assert status(conn, mark) == ("confirmed" if matched else "provisional")


def _undo_last(conn, mark: str) -> None:
    """Undo the provisional's latest log entry and reconcile, as the board's undo does."""
    entry = changelog.load(conn, fingerprint=mark)[0]
    with conn:
        changelog.undo(conn, entry.id)
    with conn:
        live_match.reconcile(conn, NOW)


def _statement_with(conn, amount: str) -> str:
    """Store a statement whose only row is the purchase; returns that row's fingerprint."""
    ingest_card(conn, card_statement("2026-02-28", [("2026-02-06", "TIENDA FICTICIA", amount)]))
    return next(m.fingerprint for m in spending.load_all(conn) if m.amount == Decimal(amount))


def test_undoing_a_discard_after_the_statement_counts_once_and_renames_nothing(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="555.00", day="05/02/2026", merchant="TIENDA FICTICIA")
    with conn:
        changelog_track_decision(conn, mark, "discard")
    row = _statement_with(conn, "555.00")
    with conn:
        corrections.set_note(conn, row, "su propia nota")  # spanish-data
    _undo_last(conn, mark)
    found = [m for m in spending.load_all(conn) if m.amount == Decimal("555.00")]
    assert [m.fingerprint for m in found] == [row]  # once, with its own identity
    assert found[0].note == "su propia nota"  # spanish-data
    assert status(conn, mark) == "confirmed"


def test_undoing_a_void_after_the_statement_counts_once_and_renames_nothing(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="556.00", day="05/02/2026", merchant="TIENDA FICTICIA")
    alert(conn, "r1", amount="556.00", day="06/02/2026", merchant="TIENDA FICTICIA",
          status=samples.REVERSED)  # fmt: skip
    assert live_store.decisions(conn)[mark] == "void"
    # The statement charges it anyway: the void is undone and the alert confirmed (the row was
    # stored in this run, so it takes the provisional's identity) and it is a To review item.
    ingest_card(conn, card_statement("2026-02-28", [("2026-02-06", "TIENDA FICTICIA", "556.00")]))
    assert status(conn, mark) == "confirmed"
    assert mark not in live_store.decisions(conn)
    assert live_store.reversals(conn) == {mark: "charged"}
    found = [m for m in spending.load_all(conn) if m.amount == Decimal("556.00")]
    assert [m.fingerprint for m in found] == [mark]
    kinds = [e.after_text for e in changelog.load(conn, fingerprint=mark)]
    assert len(kinds) == 2  # the void and its undo, both in the log


def test_undoing_a_void_after_a_statement_without_it_counts_it_once(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="557.00", day="05/02/2026", merchant="TIENDA FICTICIA")
    alert(conn, "r1", amount="557.00", day="06/02/2026", merchant="TIENDA FICTICIA",
          status=samples.REVERSED)  # fmt: skip
    ingest_card(conn, card_statement("2026-02-28", [("2026-02-20", "OTRO", "1.00")]))
    _undo_last(conn, mark)
    found = [m for m in spending.load_all(conn) if m.amount == Decimal("557.00")]
    assert [m.fingerprint for m in found] == [mark]
    assert mark in live_store.unmatched(conn)  # it is a To review item again


def test_a_reversal_does_not_void_a_linked_provisional(conn) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="800.00", day="05/02/2026", merchant="TIENDA FICTICIA")
    with conn:
        share(conn, mark, Decimal("800.00"), people=2, with_whom="Ana")
    alert(conn, "r1", amount="800.00", day="06/02/2026", merchant="TIENDA FICTICIA",
          status=samples.REVERSED)  # fmt: skip
    assert mark not in live_store.decisions(conn)
    assert mark in _flow(conn)
    assert live_store.reversals(conn) == {mark: "pending"}
    assert live_store.is_linked(conn, mark)


def test_a_resent_alert_is_a_duplicate_not_a_second_purchase(conn) -> None:
    known_card(conn)
    first = alert(conn, "a1", amount="99.00")
    again = samples.alert_email("a2", amount="99.00")
    later = replace(again, message_id="a3", received_at=again.received_at + timedelta(minutes=11))
    with conn:
        soon = replace(again, received_at=again.received_at + timedelta(minutes=9))
        live_store.record(conn, soon, "popular_alerts", NOW)
        live_store.record(conn, later, "popular_alerts", NOW)
        live_match.reconcile(conn, NOW)
    statuses = dict(conn.execute("SELECT message_id, status FROM alerts").fetchall())
    assert statuses == {"a1": "provisional", "a2": "duplicate", "a3": "provisional"}
    assert first in _flow(conn)
    assert sum(1 for m in spending.load_all(conn) if m.provisional) == 2


def test_a_row_stored_in_an_earlier_run_never_takes_the_provisionals_identity(conn) -> None:
    known_card(conn)
    row = _statement_with(conn, "558.00")
    mark = alert(conn, "a1", amount="558.00", day="05/02/2026", merchant="TIENDA FICTICIA")
    assert status(conn, mark) == "confirmed"
    with conn:  # even reconciling again with "new" statements that are not this one's
        live_match.reconcile(conn, NOW, [999])
    assert [m.fingerprint for m in spending.load_all(conn) if m.amount == Decimal("558.00")] == [
        row
    ]


def test_the_statement_is_kept_when_reconciling_fails(
    conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    known_card(conn)
    mark = alert(conn, "a1", amount="559.00", day="05/02/2026", merchant="TIENDA FICTICIA")

    def broken(*_: object, **__: object) -> None:
        raise sqlite3.OperationalError("boom")

    monkeypatch.setattr(live_match, "reconcile", broken)
    statement = card_statement("2026-02-28", [("2026-02-06", "TIENDA FICTICIA", "559.00")])
    assert ingest_card(conn, statement) == "parsed"
    query = "SELECT COUNT(*) FROM transactions WHERE amount_cents = 55900"
    assert conn.execute(query).fetchone()[0] == 1
    assert status(conn, mark) == "provisional"
    monkeypatch.undo()
    with conn:  # the next sync's reconcile does the work
        live_match.reconcile(conn, NOW)
    assert status(conn, mark) == "confirmed"


def changelog_track_decision(conn, mark: str, decision: str | None) -> None:
    """A decision recorded the way the board records it (a change-log entry)."""
    with changelog.track(conn, "provisional", "transaction", mark, "TIENDA", fingerprints=[mark]):
        live_store.decide(conn, mark, decision, NOW)  # type: ignore[arg-type]
