"""What a transaction shows of its merchant receipts (see `analysis.receipt_store`).

Laid over the transaction rows after they are listed, like the hosted "approved" mark: it is
never part of a movement, so it changes no figure, no fingerprint and nothing the flow cache
keeps.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

from michelito.analysis import receipt_items, receipt_store
from michelito.analysis.receipt_items import Item
from michelito.analysis.receipt_store import Stored

FORWARDING = "forwarding"
_GMAIL = "https://mail.google.com/mail/u/0/"


@dataclass(frozen=True)
class ReceiptView:
    id: int
    merchant: str
    kind: str
    orders: tuple[str, ...]
    amount_cents: int
    currency: str
    day: date  # when the email arrived
    summary: str
    item_count: int | None
    order_link: str  # the order's page at the merchant
    email_link: str  # the email in the person's Gmail
    origin: str  # who linked it: "automatic" or "confirmed"
    items: tuple[Item, ...] = ()  # its orders' item names, if the browser extension sent them


def email_link(receipt: Stored) -> str:
    """Where the email opens in Gmail: by Gmail's own id when the sync read it; a forwarded
    one only carries its `Message-ID`, which Gmail finds with a search."""
    if receipt.source == FORWARDING:
        return f"{_GMAIL}#search/{quote('rfc822msgid:' + receipt.message_id, safe='')}"
    return f"{_GMAIL}#all/{quote(receipt.message_id, safe='')}"


def view(
    receipt: Stored, origin: str, items: dict[str, tuple[Item, ...]] | None = None
) -> ReceiptView:
    """`items`: the item names by order number (`analysis.receipt_items`)."""
    names = items or {}
    return ReceiptView(
        id=receipt.id,
        merchant=receipt.merchant,
        kind=receipt.kind,
        orders=receipt.orders,
        amount_cents=receipt.amount_cents,
        currency=receipt.currency,
        day=receipt.day,
        summary=receipt.summary,
        item_count=receipt.item_count,
        order_link=receipt.link,
        email_link=email_link(receipt),
        origin=origin,
        items=tuple(item for order in receipt.orders for item in names.get(order, ())),
    )


def by_fingerprint(conn: sqlite3.Connection) -> dict[str, tuple[ReceiptView, ...]]:
    """The receipts each linked transaction shows, oldest email first."""
    linked = receipt_store.by_fingerprint(conn)
    if not linked:
        return {}
    origins = receipt_store.origins(conn)
    orders = [order for receipts in linked.values() for r in receipts for order in r.orders]
    items = receipt_items.by_order(conn, orders)
    return {
        fingerprint: tuple(
            view(receipt, origins.get((receipt.id, fingerprint), "automatic"), items)
            for receipt in receipts
        )
        for fingerprint, receipts in linked.items()
    }
