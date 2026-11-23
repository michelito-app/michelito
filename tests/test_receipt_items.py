"""Item names of merchant orders (`analysis.receipt_items`), as the browser extension sends
them. Every order number and title is made up."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import receipt_items
from michelito.analysis.receipt_items import Item, Order

NOW = "2026-02-14T15:00:00+00:00"
LATER = "2026-02-15T09:00:00+00:00"
FIRST = "111-1111111-1111111"
SECOND = "222-2222222-2222222"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


def _save(conn: sqlite3.Connection, *orders: Order, now: str = NOW) -> receipt_items.Saved:
    with conn:
        return receipt_items.save(conn, orders, now)


def test_a_database_that_never_got_names_reads_as_empty(conn: sqlite3.Connection) -> None:
    assert receipt_items.by_order(conn) == {}
    assert receipt_items.count(conn) == 0
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert "receipt_items" not in tables


def test_saving_stores_each_order_items_in_order(conn: sqlite3.Connection) -> None:
    saved = _save(
        conn,
        Order(FIRST, (Item("Synthetic headphones", 1, 2999), Item("Cable", 2, None))),
        Order(SECOND, (Item("Desk lamp", None, None),)),
    )

    assert saved == receipt_items.Saved(orders=2, items=3)
    found = receipt_items.by_order(conn)
    assert found[FIRST] == (Item("Synthetic headphones", 1, 2999), Item("Cable", 2, None))
    assert found[SECOND] == (Item("Desk lamp", None, None),)
    assert receipt_items.count(conn) == 2


def test_saving_the_same_order_again_replaces_its_items(conn: sqlite3.Connection) -> None:
    _save(conn, Order(FIRST, (Item("Old name", 1, None), Item("Gone", 1, None))))

    _save(conn, Order(FIRST, (Item("New name", 3, 500),)), now=LATER)
    _save(conn, Order(FIRST, (Item("New name", 3, 500),)), now=LATER)

    assert receipt_items.by_order(conn) == {FIRST: (Item("New name", 3, 500),)}
    rows = conn.execute("SELECT updated_at FROM receipt_items").fetchall()
    assert [tuple(row) for row in rows] == [(LATER,)]


def test_an_order_sent_twice_in_one_batch_keeps_the_last(conn: sqlite3.Connection) -> None:
    _save(conn, Order(FIRST, (Item("First", 1, None),)), Order(FIRST, (Item("Second", 1, None),)))

    assert receipt_items.by_order(conn) == {FIRST: (Item("Second", 1, None),)}


def test_only_the_asked_orders_are_read(conn: sqlite3.Connection) -> None:
    _save(conn, Order(FIRST, (Item("One", 1, None),)), Order(SECOND, (Item("Two", 1, None),)))

    assert receipt_items.by_order(conn, [SECOND, "000-0000000-0000000"]) == {
        SECOND: (Item("Two", 1, None),)
    }
    assert receipt_items.by_order(conn, []) == {}


def test_past_the_account_limit_nothing_new_is_stored(conn: sqlite3.Connection) -> None:
    _save(conn, Order(FIRST, (Item("One", 1, None),)))

    with pytest.raises(receipt_items.TooManyOrders), conn:
        receipt_items.save(conn, [Order(SECOND, (Item("Two", 1, None),))], NOW, orders_max=1)
    # An order already stored can still be updated at the limit.
    with conn:
        receipt_items.save(conn, [Order(FIRST, (Item("Renamed", 1, None),))], NOW, orders_max=1)

    assert receipt_items.by_order(conn) == {FIRST: (Item("Renamed", 1, None),)}


def test_the_database_refuses_what_the_schemas_would(conn: sqlite3.Connection) -> None:
    receipt_items.ensure(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO receipt_items (order_number, position, title, updated_at) "
            "VALUES (?, 0, '', ?)",
            (FIRST, NOW),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO receipt_items (order_number, position, title, quantity, updated_at) "
            "VALUES (?, 0, 'x', 0, ?)",
            (FIRST, NOW),
        )


def test_past_the_account_title_size_nothing_is_stored(conn: sqlite3.Connection) -> None:
    _save(conn, Order(FIRST, (Item("x" * 10, 1, None),)))

    with pytest.raises(receipt_items.TooManyOrders), conn:
        receipt_items.save(conn, [Order(SECOND, (Item("y" * 11, 1, None),))], NOW, titles_max=20)
    # Replacing an order's titles counts the new ones instead of the old ones.
    with conn:
        receipt_items.save(conn, [Order(FIRST, (Item("z" * 20, 1, None),))], NOW, titles_max=20)

    assert receipt_items.by_order(conn) == {FIRST: (Item("z" * 20, 1, None),)}
