"""Stored recurring marks: status, installments left and bank keys from before."""

import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from michelito import db
from michelito.analysis import categories as cat
from michelito.analysis import recurring_marks as marks
from michelito.analysis.spending import Movement
from tests.test_recurring import charge

DAY1 = date(2026, 3, 1)
DAY2 = date(2026, 4, 1)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def test_status_round_trip(conn) -> None:
    assert marks.load(conn) == {}
    marks.set_status(conn, "STREAMING FICTICIO", "USD", "confirmed", DAY1)
    assert marks.load(conn) == {
        ("STREAMING FICTICIO", "USD"): marks.Mark("confirmed", None, DAY1, None)
    }
    marks.set_status(conn, "STREAMING FICTICIO", "USD", "confirmed", DAY2)  # same value
    assert marks.load(conn)[("STREAMING FICTICIO", "USD")].status_on == DAY1
    marks.set_status(conn, "STREAMING FICTICIO", "USD", "cancelled", DAY2)
    assert marks.load(conn)[("STREAMING FICTICIO", "USD")] == marks.Mark(
        "cancelled", None, DAY2, None
    )


def test_clearing_both_deletes_row(conn) -> None:
    marks.set_status(conn, "GIMNASIO FICTICIO", "DOP", "dismissed", DAY1)
    marks.set_status(conn, "GIMNASIO FICTICIO", "DOP", None, DAY2)
    assert marks.load(conn) == {}
    marks.set_installments(conn, "TIENDA FICTICIA", "DOP", 5, DAY1)
    marks.set_installments(conn, "TIENDA FICTICIA", "DOP", None, DAY2)
    assert marks.load(conn) == {}
    marks.set_status(conn, "NEVER SEEN", "DOP", None, DAY1)  # no row: does nothing
    assert marks.load(conn) == {}


def test_installments_kept_when_status_changes(conn) -> None:
    marks.set_installments(conn, "TIENDA FICTICIA", "DOP", 4, DAY1)
    marks.set_status(conn, "TIENDA FICTICIA", "DOP", "confirmed", DAY2)
    assert marks.load(conn)[("TIENDA FICTICIA", "DOP")] == marks.Mark("confirmed", 4, DAY2, DAY1)
    marks.set_status(conn, "TIENDA FICTICIA", "DOP", None, DAY2)
    assert marks.load(conn)[("TIENDA FICTICIA", "DOP")].installments_left == 4
    marks.set_installments(conn, "TIENDA FICTICIA", "DOP", 0, DAY2)
    assert marks.load(conn)[("TIENDA FICTICIA", "DOP")] == marks.Mark(None, 0, None, DAY2)


def test_invalid_status_or_negative_installments_rejected(conn) -> None:
    with pytest.raises(ValueError):
        marks.set_status(conn, "X", "DOP", "bogus", DAY1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        marks.set_installments(conn, "X", "DOP", -1, DAY1)
    with pytest.raises(ValueError):
        marks.set_status(conn, "X", "EUR", "confirmed", DAY1)
    assert marks.load(conn) == {}


def test_existing_v3_database_gets_table(tmp_path) -> None:
    path = tmp_path / "board.sqlite"
    first = db.connect(path)
    first.execute("DROP TABLE recurring_marks")
    first.execute("PRAGMA user_version = 3")
    first.commit()
    first.close()
    second = db.connect(path)
    try:
        assert second.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert marks.load(second) == {}
    finally:
        second.close()


def test_installments_do_not_move_cancel_date(conn) -> None:
    marks.set_status(conn, "STREAMING FICTICIO", "USD", "cancelled", DAY1)
    marks.set_installments(conn, "STREAMING FICTICIO", "USD", 3, DAY2)
    assert marks.load(conn)[("STREAMING FICTICIO", "USD")] == marks.Mark("cancelled", 3, DAY1, DAY2)


def test_database_checks_reject_bad_values(conn) -> None:
    sql = (
        "INSERT INTO recurring_marks (merchant, currency, status, installments_left, updated_at) "
        "VALUES ('X', 'DOP', ?, ?, 't')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, ("bogus", None))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (None, -1))


PREVIOUS = "TRANSFERENCIA UNIVERSAL FICTICIOS"
NEW = "TRANSFERENCIA A UNIVERSAL FICTICIOS"
TEXT = "TRANSFERENCIA A UNIVERSAL DE FICTICIOS SRL"


def _bank_movement(description: str, currency: str = "DOP") -> Movement:
    merchant = cat.bank_merchant_key(description)
    return replace(
        charge("2026-01-05", "100", cat.HOUSING, merchant, currency), description=description
    )


def _mark(status: marks.MarkStatus) -> marks.Mark:
    return marks.Mark(status, None, DAY1, None)


class TestPreviousBankKey:
    """A mark saved under the bank key from before the Banreservas channels."""

    def test_moves_to_the_new_key(self) -> None:
        old = _mark("confirmed")
        resolved = marks.with_previous_keys({(PREVIOUS, "DOP"): old}, [_bank_movement(TEXT)])
        assert resolved == {(NEW, "DOP"): old}

    def test_a_mark_under_the_new_key_wins(self) -> None:
        old, new = _mark("confirmed"), _mark("dismissed")
        resolved = marks.with_previous_keys(
            {(PREVIOUS, "DOP"): old, (NEW, "DOP"): new}, [_bank_movement(TEXT)]
        )
        assert resolved == {(NEW, "DOP"): new}

    def test_previous_key_still_in_use_is_kept(self) -> None:
        old = _mark("confirmed")
        other = _bank_movement("TRANSFERENCIA UNIVERSAL DE FICTICIOS")  # its key is the old one
        assert other.merchant == PREVIOUS
        resolved = marks.with_previous_keys({(PREVIOUS, "DOP"): old}, [_bank_movement(TEXT), other])
        assert resolved == {(PREVIOUS, "DOP"): old, (NEW, "DOP"): old}

    def test_only_the_same_currency_moves(self) -> None:
        old = _mark("confirmed")
        resolved = marks.with_previous_keys({(PREVIOUS, "USD"): old}, [_bank_movement(TEXT)])
        assert resolved == {(PREVIOUS, "USD"): old}

    def test_card_movements_are_ignored(self) -> None:
        card = replace(_bank_movement(TEXT), merchant="TRANSFERENCIA A")  # a card key
        old = _mark("confirmed")
        resolved = marks.with_previous_keys({(PREVIOUS, "DOP"): old}, [card])
        assert resolved == {(PREVIOUS, "DOP"): old}

    def test_load_for_applies_it(self, conn) -> None:
        with conn:
            marks.set_status(conn, PREVIOUS, "DOP", "confirmed", DAY1)
        assert set(marks.load_for(conn, [_bank_movement(TEXT)])) == {(NEW, "DOP")}
