"""Item names of merchant orders, keyed by order number (hosted mode: the browser extension).

The extension reads the person's own order-history pages at the merchant and sends, per order,
its number and the names of its items (with quantity and unit price when the page shows them).
They only add detail to the receipts the merchant's emails already brought: a receipt shows the
items of its order numbers (`web.receipts`); nothing here creates a receipt, links one or
changes a figure.

The table is created on first use (`ensure`), so a database that never got names has none and
reads as empty. `save` replaces each order's items (idempotent: sending the same order again
leaves the same rows). Nothing here commits: the caller wraps it in `with conn:`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

ORDER_MAX = 40
TITLE_MAX = 300
QUANTITY_MAX = 999
ITEMS_MAX = 50  # items of one order
ORDERS_MAX = 5000  # orders with names in one account
TITLES_MAX = 1_000_000  # characters of titles in one account (a few MB at most)

SCHEMA = f"""CREATE TABLE IF NOT EXISTS receipt_items (
    order_number TEXT NOT NULL CHECK (length(order_number) BETWEEN 1 AND {ORDER_MAX}),
    position INTEGER NOT NULL CHECK (position BETWEEN 0 AND {ITEMS_MAX - 1}),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND {TITLE_MAX}),
    quantity INTEGER CHECK (quantity IS NULL OR quantity BETWEEN 1 AND {QUANTITY_MAX}),
    price_cents INTEGER CHECK (price_cents IS NULL OR price_cents >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (order_number, position)
)"""


@dataclass(frozen=True)
class Item:
    title: str
    quantity: int | None
    price_cents: int | None  # the unit price in US cents, when the page shows it


@dataclass(frozen=True)
class Order:
    number: str
    items: tuple[Item, ...]


@dataclass(frozen=True)
class Saved:
    orders: int
    items: int


class TooManyOrders(Exception):
    """Storing these orders would pass the account's limits (nothing was stored)."""


def _has_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'receipt_items'"
    ).fetchone()
    return row is not None


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)


def _stored_orders(conn: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute("SELECT DISTINCT order_number FROM receipt_items")}


def _titles_after(conn: sqlite3.Connection, latest: dict[str, Order]) -> int:
    """The characters of titles the account would hold once these orders replace theirs."""
    placeholders = ", ".join("?" for _ in latest)
    (kept,) = conn.execute(
        "SELECT COALESCE(SUM(length(title)), 0) FROM receipt_items "
        f"WHERE order_number NOT IN ({placeholders})",
        tuple(latest),
    ).fetchone()
    sent = sum(len(item.title) for order in latest.values() for item in order.items)
    return int(kept) + sent


def save(
    conn: sqlite3.Connection,
    orders: Iterable[Order],
    now: str,
    orders_max: int = ORDERS_MAX,
    titles_max: int = TITLES_MAX,
) -> Saved:
    """Replace the items of each order (an order sent twice keeps the last). `TooManyOrders`
    if the new order numbers would pass `orders_max`, or the account's titles `titles_max`
    characters."""
    latest = {order.number: order for order in orders}
    ensure(conn)
    if not latest:
        return Saved(orders=0, items=0)
    new = set(latest) - _stored_orders(conn)
    if new and count(conn) + len(new) > orders_max:
        raise TooManyOrders
    if _titles_after(conn, latest) > titles_max:
        raise TooManyOrders
    for order in latest.values():
        conn.execute("DELETE FROM receipt_items WHERE order_number = ?", (order.number,))
        conn.executemany(
            "INSERT INTO receipt_items (order_number, position, title, quantity, price_cents, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (order.number, position, item.title, item.quantity, item.price_cents, now)
                for position, item in enumerate(order.items)
            ],
        )
    return Saved(orders=len(latest), items=sum(len(order.items) for order in latest.values()))


def count(conn: sqlite3.Connection) -> int:
    """How many orders have names."""
    if not _has_table(conn):
        return 0
    row = conn.execute("SELECT COUNT(DISTINCT order_number) FROM receipt_items").fetchone()
    return int(row[0])


def by_order(
    conn: sqlite3.Connection, numbers: Sequence[str] | None = None
) -> dict[str, tuple[Item, ...]]:
    """The items of each order with names, in the page's order (only `numbers`, if given)."""
    if not _has_table(conn) or (numbers is not None and not numbers):
        return {}
    query = "SELECT order_number, title, quantity, price_cents FROM receipt_items"
    params: tuple[str, ...] = ()
    if numbers is not None:
        wanted = tuple(dict.fromkeys(numbers))
        query += f" WHERE order_number IN ({', '.join('?' for _ in wanted)})"
        params = wanted
    found: dict[str, list[Item]] = {}
    for number, title, quantity, price in conn.execute(
        f"{query} ORDER BY order_number, position", params
    ):
        found.setdefault(str(number), []).append(
            Item(str(title), None if quantity is None else int(quantity), price)
        )
    return {number: tuple(items) for number, items in found.items()}


def with_receipt(conn: sqlite3.Connection, numbers: Sequence[str]) -> int:
    """How many of these order numbers a merchant email already brought."""
    wanted = tuple(dict.fromkeys(numbers))
    if not wanted:
        return 0
    placeholders = ", ".join("?" for _ in wanted)
    row = conn.execute(
        "SELECT COUNT(DISTINCT o.order_number) FROM receipt_orders o "
        "JOIN receipts r ON r.id = o.receipt_id JOIN receipt_emails e ON e.id = r.email_id "
        f"WHERE e.status = 'read' AND o.order_number IN ({placeholders})",
        wanted,
    ).fetchone()
    return int(row[0])
