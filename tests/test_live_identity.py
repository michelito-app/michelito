"""Live sync: a provisional keeps its identity when its statement confirms it, so every link
(shared groups, exchanges, investments, cash box, reserves), mark and log entry survives.

The shared ledger (schema 19) links its entries by fingerprint too (`ledger_links`): a provisional
shared into a group keeps its entry, its split and what the group owes after confirmation.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from decimal import Decimal

import pytest

from michelito import db
from michelito.analysis import (
    cash_box_store,
    catalog,
    categories,
    changelog,
    corrections,
    ledger,
    ledger_store,
    links,
    one_off_dismissals,
    reserve_store,
    review_marks,
    spending,
)
from tests.ledger_helpers import share
from tests.live_helpers import NOW, alert, card_statement, ingest_card, known_card, status

AMOUNT = "2,345.67"
ROW = ("2026-02-15", "COMERCIO FICTICIO SANTO DOMINGO", "2345.67")


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    known_card(connection)
    yield connection
    connection.close()


def _provisional(conn: sqlite3.Connection) -> str:
    mark = alert(conn, "a1", amount=AMOUNT, day="14/02/2026", merchant="COMERCIO FICTICIO")
    assert status(conn, mark) == "provisional"
    return mark


def _confirm(conn: sqlite3.Connection, mark: str, *extra: tuple[str, str, str]) -> None:
    assert ingest_card(conn, card_statement("2026-02-28", [ROW, *extra])) == "parsed"
    assert status(conn, mark) == "confirmed"


def _movement(conn: sqlite3.Connection, mark: str) -> spending.Movement:
    found = [m for m in spending.load_all(conn) if m.fingerprint == mark]
    assert len(found) == 1
    assert not found[0].provisional
    return found[0]


def _members(conn: sqlite3.Connection) -> set[str]:
    """Every fingerprint in a link or in the shared ledger (entries and payments)."""
    return set(links.load(conn).fingerprints) | set(ledger_store.linked_fingerprints(conn))


def test_category_note_and_one_off_survive(conn) -> None:
    mark = _provisional(conn)
    with conn:
        corrections.set_transaction_category(conn, mark, categories.RESTAURANTS)
        corrections.set_note(conn, mark, "cena")  # spanish-data
        corrections.set_one_off(conn, mark, True)
    _confirm(conn, mark)
    found = _movement(conn, mark)
    assert found.ref == categories.RESTAURANTS
    assert (found.note, found.one_off, found.corrected) == ("cena", True, True)  # spanish-data
    assert found.description == ROW[1]  # bank fields from the statement


def _shared(conn: sqlite3.Connection, mark: str) -> None:
    """Shared into a ledger group: the entry is linked to the provisional by fingerprint."""
    share(conn, mark, Decimal("2345.67"), people=2, with_whom="Ana")


def _exchange(conn: sqlite3.Connection, mark: str) -> None:
    other = alert(conn, "a2", amount="10.00", currency="US", day="14/02/2026")
    links.create_exchange(conn, [mark, other])


def _investment(conn: sqlite3.Connection, mark: str) -> None:
    links.create_investment(conn, mark, with_whom="Pedro")


def _cash_box(conn: sqlite3.Connection, mark: str) -> None:
    cash_box_store.store(conn, mark)


def _reserve(conn: sqlite3.Connection, mark: str) -> None:
    category = catalog.resolve_ref(conn, categories.RESTAURANTS)
    reserve = reserve_store.create(
        conn,
        name="Viaje",  # spanish-data
        amount=Decimal(5000),
        category_id=category,
        due_month="2026-06",
        every_months=None,
        multiple=True,
    )
    reserve_store.add_member(conn, reserve, mark)


@pytest.mark.parametrize(
    ("make", "link"),
    [
        (_shared, "shared"),
        (_exchange, ""),  # a card leg is not relabeled (only bank legs are), but stays linked
        (_investment, "investment"),
        (_cash_box, "cash_box"),
        (_reserve, ""),
    ],
    ids=["shared", "exchange", "investment", "cash_box", "reserve"],
)
def test_every_link_kind_survives(
    conn, make: Callable[[sqlite3.Connection, str], None], link: str
) -> None:
    mark = _provisional(conn)
    with conn:
        make(conn, mark)
    before = _members(conn)
    assert mark in before
    _confirm(conn, mark)
    assert _members(conn) == before
    assert _movement(conn, mark).link == link


def test_review_marks_dismissals_and_reviewed_survive(conn) -> None:
    mark = _provisional(conn)
    with conn:
        review_marks.set_reviewed(conn, mark, "duplicate", True)
        one_off_dismissals.set_dismissed(conn, mark, True)
        conn.execute(
            "INSERT INTO reviewed_fingerprints (fingerprint, reviewed_at) VALUES (?, ?)",
            (mark, NOW),
        )
    _confirm(conn, mark)
    _movement(conn, mark)
    assert (mark, "duplicate") in review_marks.load(conn)
    assert mark in one_off_dismissals.load(conn)


def test_the_log_keeps_the_history_and_can_still_undo(conn) -> None:
    mark = _provisional(conn)
    with (
        conn,
        changelog.track(conn, "category", "transaction", mark, "COMERCIO", fingerprints=[mark]),
    ):
        corrections.set_transaction_category(conn, mark, categories.RESTAURANTS)
    _confirm(conn, mark)
    history = changelog.load(conn, fingerprint=mark)
    assert len(history) == 1
    assert changelog.undo_state(conn, history[0]).allowed
    with conn:
        changelog.undo(conn, history[0].id)
    assert _movement(conn, mark).ref != categories.RESTAURANTS


def test_a_shared_provisional_keeps_its_ledger_entry_and_balances(conn) -> None:
    mark = _provisional(conn)
    with conn:
        group = share(conn, mark, Decimal("2345.67"), people=2, with_whom="Ana")
    book = ledger_store.load(conn)
    before = {(e.id, e.fingerprint) for g in book.groups for e in g.entries}
    owed = ledger.states(book, {})
    _confirm(conn, mark)
    after = ledger_store.load(conn)
    assert {(e.id, e.fingerprint) for g in after.groups for e in g.entries} == before
    assert ledger_store.linked_fingerprints(conn)[mark] == (group, "entry")
    assert ledger.states(after, {}) == owed
    confirmed = _movement(conn, mark)
    assert confirmed.link == "shared"
    assert confirmed.gross == Decimal("2345.67")
