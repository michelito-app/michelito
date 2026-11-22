"""Merchant receipts through the local sync: the source, the extraction and the links that
appear once the statement arrives. Synthetic emails and statements only."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from michelito import config, db, extract, sources
from michelito.analysis import receipt_store
from michelito.gmail import MailMessage
from tests import live_helpers
from tests import receipt_samples as samples
from tests.fakes import FakeClient

SOURCE = config.Source("amazon_receipts", "from:auto-confirm@amazon.com", (), receipts=True)
AMAZON_ROW = ("2026-02-15", "AMAZON MKTPL*AB1CD2EF3", "110.97", "USD")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


def _message(email: object) -> tuple[MailMessage, dict[str, bytes]]:
    message = MailMessage(
        message_id=email.message_id,  # type: ignore[attr-defined]
        sender=email.sender,  # type: ignore[attr-defined]
        subject=email.subject,  # type: ignore[attr-defined]
        received_at=email.received_at,  # type: ignore[attr-defined]
        body_text=email.text,  # type: ignore[attr-defined]
        attachments=(),
        body_html=email.html,  # type: ignore[attr-defined]
        auth_results=email.auth_results,  # type: ignore[attr-defined]
    )
    return message, {}


def _february(conn: sqlite3.Connection, *rows: live_helpers.Row) -> None:
    statement = live_helpers.card_statement("2026-02-28", list(rows), period_start="2026-02-01")
    assert live_helpers.ingest_card(conn, statement) == "parsed"


def _links(conn: sqlite3.Connection) -> list[tuple[str, ...]]:
    return [receipt.links for receipt in receipt_store.load(conn)]


def test_a_source_can_be_declared_for_receipts() -> None:
    data = {"source": [{"name": "shop", "query": "from:orders@shop.example", "receipts": True}]}

    (found,) = sources.parse_sources(data, "test")

    assert found == config.Source("shop", "from:orders@shop.example", (), receipts=True)


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "shop", "query": "from:a@shop.example", "receipts": "yes"},
        {"name": "shop", "query": "from:a@shop.example", "receipts": True, "alerts": True},
    ],
)
def test_a_wrong_receipts_source_is_refused(entry: dict[str, object]) -> None:
    with pytest.raises(sources.SourcesError):
        sources.parse_sources({"source": [entry]}, "test")


def test_the_defaults_read_amazons_receipts_of_the_last_year() -> None:
    found = [source for source in config.DEFAULT_SOURCES if source.receipts]

    assert [source.name for source in found] == ["amazon_receipts"]
    query = found[0].query
    assert "auto-confirm@amazon.com" in query and "shipment-tracking@amazon.com" in query
    assert "newer_than:12m" in query
    assert not found[0].alerts and found[0].extensions == ()


def test_receipts_are_stored_and_nothing_goes_to_the_archive(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    client = FakeClient(_message(samples.order_email()), _message(samples.shipment_email()))
    raw = tmp_path / "raw"

    stats = extract.extract_source(conn, client, SOURCE, raw)

    assert stats.new_messages == 2 and stats.saved_files == 0
    assert len(receipt_store.load(conn)) == 3
    assert not raw.exists()
    assert conn.execute("SELECT COUNT(*) FROM gmail_messages").fetchone()[0] == 0
    assert {receipt.source for receipt in receipt_store.load(conn)} == {"amazon_receipts"}


def test_a_second_sync_downloads_nothing(conn: sqlite3.Connection, tmp_path: Path) -> None:
    client = FakeClient(_message(samples.order_email()))
    extract.extract_source(conn, client, SOURCE, tmp_path)
    client.fetched.clear()

    stats = extract.extract_source(conn, client, SOURCE, tmp_path)

    assert client.fetched == [] and stats.new_messages == 0


def test_an_email_that_cannot_be_read_does_not_stop_the_sync(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    broken = samples.order_email("m-broken", html="", text="Grand Total:\n10.00 USD\n")
    client = FakeClient(_message(broken), _message(samples.shipment_email()))

    extract.extract_source(conn, client, SOURCE, tmp_path)

    assert len(receipt_store.load(conn)) == 1
    assert [failure["failed_field"] for failure in receipt_store.failures(conn)] == ["order"]


def test_an_unexpected_error_is_recorded_by_its_class_only(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    class Failing(FakeClient):
        def get_message(self, message_id: str) -> MailMessage:
            raise RuntimeError("a secret detail")

    extract.extract_source(conn, Failing(_message(samples.order_email())), SOURCE, tmp_path)

    (failure,) = receipt_store.failures(conn)
    assert failure["error"] == "RuntimeError"
    assert "secret" not in str(failure)
    # It is asked for again the next time.
    assert "m-order-1" not in receipt_store.known_message_ids(conn)


def test_a_receipt_is_linked_to_the_charge_already_in_a_statement(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    _february(conn, AMAZON_ROW)

    extract.extract_source(conn, FakeClient(_message(samples.shipment_email())), SOURCE, tmp_path)

    ((fingerprint,),) = _links(conn)
    assert fingerprint


def test_a_receipt_waits_for_its_statement_and_is_linked_when_it_arrives(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    live_helpers.known_card(conn)
    extract.extract_source(conn, FakeClient(_message(samples.shipment_email())), SOURCE, tmp_path)
    assert _links(conn) == [()]

    _february(conn, AMAZON_ROW)

    assert [len(found) for found in _links(conn)] == [1]


def test_a_statement_with_two_equal_charges_links_nothing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    _february(conn, AMAZON_ROW, ("2026-02-16", "AMAZON RETAIL*ZZ9YY8XX7", "110.97", "USD"))

    extract.extract_source(conn, FakeClient(_message(samples.shipment_email())), SOURCE, tmp_path)

    assert _links(conn) == [()]


def test_the_received_date_is_the_emails(conn: sqlite3.Connection, tmp_path: Path) -> None:
    extract.extract_source(conn, FakeClient(_message(samples.shipment_email())), SOURCE, tmp_path)

    (receipt,) = receipt_store.load(conn)
    assert receipt.received_at == datetime(2026, 2, 14, 15, tzinfo=UTC)
