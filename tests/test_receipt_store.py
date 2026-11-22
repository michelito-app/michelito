"""Receipt storage (`analysis.receipt_store`, schema 24), with synthetic emails only."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from michelito import db, migrations_v24
from michelito.analysis import receipt_store
from tests import receipt_samples as samples

NOW = "2026-02-14T15:00:00+00:00"
LATER = "2026-02-15T09:00:00+00:00"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


def _record(conn: sqlite3.Connection, email: object, now: str = NOW) -> str:
    with conn:
        return receipt_store.record(conn, email, "gmail", now)  # type: ignore[arg-type]


def test_the_schema_is_at_this_version(conn: sqlite3.Connection) -> None:
    assert db.SCHEMA_VERSION >= migrations_v24.VERSION
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "receipt_emails",
        "receipts",
        "receipt_orders",
        "receipt_links",
        "receipt_dismissals",
    } <= tables


def test_an_older_database_gets_the_tables(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with closing(db.connect(path)) as conn:
        conn.executescript(
            "DROP TABLE receipt_dismissals; DROP TABLE receipt_links; DROP TABLE receipt_orders; "
            "DROP TABLE receipts; DROP TABLE receipt_emails; PRAGMA user_version = 23;"
        )

    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_an_order_email_stores_one_receipt_per_order(conn: sqlite3.Connection) -> None:
    assert _record(conn, samples.order_email()) == "stored"

    found = receipt_store.load(conn)

    assert [(r.kind, r.orders, r.amount_cents, r.currency) for r in found] == [
        ("order", (samples.FIRST_ORDER,), 13056, "USD"),
        ("order", (samples.SECOND_ORDER,), 3580, "USD"),
    ]
    first = found[0]
    assert (first.merchant, first.parser, first.source) == ("Amazon", "amazon_order", "gmail")
    # The subject counts the whole email: with two orders it says nothing about each one.
    assert [(r.summary, r.item_count) for r in found] == [("", None), ("", None)]
    assert first.message_id == "m-order-1"
    assert first.day == date(2026, 2, 14)
    assert first.links == ()


def test_a_shipment_keeps_its_orders_in_the_emails_order(conn: sqlite3.Connection) -> None:
    email = samples.shipment_email(
        html=samples.shipment_html(link_order=samples.SECOND_ORDER),
        text=samples.shipment_text(link_order=samples.SECOND_ORDER),
    )
    _record(conn, email)

    (found,) = receipt_store.load(conn)

    assert found.orders == (samples.FIRST_ORDER, samples.SECOND_ORDER)
    assert found.reference == samples.SHIPMENT_ID
    assert found.link.endswith(samples.FIRST_ORDER)


def test_the_same_email_twice_is_stored_once(conn: sqlite3.Connection) -> None:
    _record(conn, samples.order_email())

    assert _record(conn, samples.order_email(), LATER) == "known"
    assert len(receipt_store.load(conn)) == 2


def test_only_fields_are_kept_never_the_body(conn: sqlite3.Connection) -> None:
    _record(conn, samples.order_email())

    stored = " ".join(
        str(value)
        for table in ("receipt_emails", "receipts", "receipt_orders")
        for row in conn.execute(f"SELECT * FROM {table}")
        for value in tuple(row)
    )

    assert "PERSONA" not in stored and "CIUDAD" not in stored
    assert "thanks" not in stored and "rio-text" not in stored


def test_an_email_that_cannot_be_read_is_stored_as_a_failure(conn: sqlite3.Connection) -> None:
    broken = samples.order_email(html="", text="Grand Total:\n10.00 USD\n")

    assert _record(conn, broken) == "failed"

    assert receipt_store.load(conn) == ()
    (failure,) = receipt_store.failures(conn)
    assert failure["failed_field"] == "order"
    assert failure["alert_type"] == "amazon_order"
    assert "10.00" not in str(failure)


def test_an_email_no_reader_takes_fails_by_type(conn: sqlite3.Connection) -> None:
    other = samples.order_email(subject="Your package is on the way")

    assert _record(conn, other) == "failed"
    assert receipt_store.failures(conn)[0]["failed_field"] == "type"


def test_a_forged_sender_is_a_permanent_failure(conn: sqlite3.Connection) -> None:
    _record(conn, samples.order_email(auth=(samples.OTHER_SIGNER,)))

    assert receipt_store.failures(conn)[0]["failed_field"] == "authentication"
    assert "m-order-1" in receipt_store.known_message_ids(conn)


def test_a_failure_a_new_reader_may_fix_is_asked_for_again(conn: sqlite3.Connection) -> None:
    _record(conn, samples.order_email(html="", text="Grand Total:\n10.00 USD\n"))
    assert "m-order-1" in receipt_store.known_message_ids(conn)

    with conn:
        conn.execute(
            "UPDATE receipt_emails SET failure = replace(failure, ?, ?)",
            (f'"{receipt_store.READER_VERSION}"', '"0"'),
        )

    assert "m-order-1" not in receipt_store.known_message_ids(conn)
    assert _record(conn, samples.order_email(), LATER) == "stored"
    assert len(receipt_store.load(conn)) == 2
    assert receipt_store.failures(conn) == []


def test_linking_and_unlinking(conn: sqlite3.Connection) -> None:
    _record(conn, samples.order_email())
    first, second = receipt_store.load(conn)

    with conn:
        receipt_store.link(conn, first.id, "tx-1", "automatic", NOW)
        receipt_store.link(conn, first.id, "tx-2", "confirmed", NOW)
        receipt_store.link(conn, second.id, "tx-1", "automatic", NOW)

    loaded = {r.id: r for r in receipt_store.load(conn)}
    assert loaded[first.id].links == ("tx-1", "tx-2")
    assert receipt_store.taken(conn) == {
        "tx-1": frozenset({samples.FIRST_ORDER, samples.SECOND_ORDER}),
        "tx-2": frozenset({samples.FIRST_ORDER}),
    }

    with conn:
        receipt_store.unlink(conn, first.id, "tx-1", LATER)

    assert {r.id: r for r in receipt_store.load(conn)}[first.id].links == ("tx-2",)
    assert receipt_store.dismissed(conn) == {(first.id, "tx-1")}


def test_linking_twice_keeps_the_first_origin(conn: sqlite3.Connection) -> None:
    _record(conn, samples.shipment_email())
    (found,) = receipt_store.load(conn)

    with conn:
        receipt_store.link(conn, found.id, "tx-1", "confirmed", NOW)
        receipt_store.link(conn, found.id, "tx-1", "automatic", LATER)

    assert conn.execute("SELECT origin, linked_at FROM receipt_links").fetchall()[0][:] == (
        "confirmed",
        NOW,
    )


def test_linking_a_dismissed_pair_again_forgets_the_dismissal(conn: sqlite3.Connection) -> None:
    _record(conn, samples.shipment_email())
    (found,) = receipt_store.load(conn)
    with conn:
        receipt_store.dismiss(conn, found.id, "tx-1", NOW)
    assert receipt_store.dismissed(conn) == {(found.id, "tx-1")}

    with conn:
        receipt_store.link(conn, found.id, "tx-1", "confirmed", LATER)

    assert receipt_store.dismissed(conn) == set()


def test_by_fingerprint_gives_each_transactions_receipts(conn: sqlite3.Connection) -> None:
    _record(conn, samples.order_email())
    _record(conn, samples.shipment_email())
    order, _, shipment = receipt_store.load(conn)
    with conn:
        receipt_store.link(conn, order.id, "tx-1", "automatic", NOW)
        receipt_store.link(conn, shipment.id, "tx-1", "automatic", NOW)

    found = receipt_store.by_fingerprint(conn)

    assert [r.id for r in found["tx-1"]] == [order.id, shipment.id]
    assert set(found) == {"tx-1"}


def test_a_database_without_the_tables_loads_nothing() -> None:
    with closing(sqlite3.connect(":memory:")) as bare:
        assert receipt_store.load(bare) == ()
        assert receipt_store.by_fingerprint(bare) == {}


def test_an_email_with_one_order_keeps_the_subjects_summary(conn: sqlite3.Connection) -> None:
    single = samples.order_email(
        html=samples.order_html(((samples.FIRST_ORDER, 1, "20.00"),)),
        text=samples.order_text(((samples.FIRST_ORDER, 1, "20.00"),)),
    )
    _record(conn, single)

    (found,) = receipt_store.load(conn)

    assert (found.summary, found.item_count) == ("Kitchen, Tools, and more", 6)


def test_only_linked_receipts_are_read_for_the_transactions(conn: sqlite3.Connection) -> None:
    _record(conn, samples.order_email())
    _record(conn, samples.shipment_email())
    assert receipt_store.by_fingerprint(conn) == {}

    shipment = receipt_store.load(conn)[-1]
    with conn:
        receipt_store.link(conn, shipment.id, "tx-1", "automatic", NOW)

    assert [r.id for r in receipt_store.load(conn, linked_only=True)] == [shipment.id]
    assert [r.orders for r in receipt_store.by_fingerprint(conn)["tx-1"]] == [
        (samples.FIRST_ORDER,)
    ]


def test_an_amount_too_large_to_store_is_a_failure_not_a_crash(conn: sqlite3.Connection) -> None:
    huge = samples.shipment_text().replace("110.97 USD", "9" * 30 + ".99 USD")

    assert _record(conn, samples.shipment_email(html="", text=huge)) == "failed"
    assert receipt_store.failures(conn)[0]["failed_field"] == "amount"
