"""Merchant receipts in the e2e test server (`tests.e2e_server --receipts`, made-up data only).

The base e2e data plus a statement of the synthetic Popular card (January 14 to February 28)
with three made-up Amazon charges in dollars, and two synthetic shipment emails
(`tests.receipt_samples`) read through the real readers:

- one says the amount of a single charge: it is linked on its own (`LINKED`);
- the other says an amount two charges share (`TWINS`): it shows in To review for both.

Each spec starts from the same database (the reset route of `tests.e2e_live`).
"""

from __future__ import annotations

import sqlite3

from michelito.analysis import receipt_match, receipt_store
from tests import receipt_samples as samples
from tests.live_helpers import card_statement, ingest_card

CARD = "1234"  # the synthetic Popular card of `tests.samples`
NOW = "2026-02-19T12:00:00+00:00"
SOURCE = "amazon_receipts"
LINKED = ("2026-02-15", "AMAZON MKTPL*AB1CD2EF3", "110.97", "USD")
TWINS = (
    ("2026-02-15", "AMAZON RETAIL*GH4IJ5KL6", "35.80", "USD"),
    ("2026-02-16", "AMAZON RETAIL*MN7OP8QR9", "35.80", "USD"),
)
OTHER_SHIPMENT = "Gh4Ij5Kl6"


def add_receipts(conn: sqlite3.Connection) -> None:
    statement = card_statement("2026-02-28", [LINKED, *TWINS], CARD, "2026-01-14")
    if ingest_card(conn, statement) != "parsed":
        raise RuntimeError("the synthetic statement with the receipts' charges did not balance")
    proposed = samples.shipment_email(
        "e2e-receipt-2",
        subject="Shipped 1 item: Tools",
        html=samples.shipment_html(samples.SECOND_ORDER, "35.80"),
        text=samples.shipment_text(samples.SECOND_ORDER, "35.80").replace(
            samples.SHIPMENT_ID, OTHER_SHIPMENT
        ),
    )
    with conn:
        receipt_store.record(conn, samples.shipment_email("e2e-receipt-1"), SOURCE, NOW)
        receipt_store.record(conn, proposed, SOURCE, NOW)
        receipt_match.reconcile_stored(conn, NOW)
