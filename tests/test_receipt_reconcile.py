"""Receipts against the loaded flow (`receipt_match.reconcile`), with made-up values."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import categories, changelog, receipt_match, receipt_store
from michelito.analysis.spending import Movement
from tests import receipt_samples as samples

NOW = "2026-02-14T15:00:00+00:00"
LATER = "2026-02-16T09:00:00+00:00"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


def charge(
    fingerprint: str = "tx-1",
    amount: str = "130.56",
    *,
    day: date = date(2026, 2, 15),
    description: str = "AMAZON MKTPL*AB1CD2EF3",
    gross: str | None = None,
) -> Movement:
    return Movement(
        day=day,
        merchant="AMAZON",
        description=description,
        category=categories.OTHER,
        amount=Decimal(amount),
        currency="USD",
        institution="bank",
        fingerprint=fingerprint,
        gross=None if gross is None else Decimal(gross),
    )


def _store(conn: sqlite3.Connection, *emails: object) -> None:
    with conn:
        for email in emails:
            receipt_store.record(conn, email, "gmail", NOW)  # type: ignore[arg-type]


def _reconcile(
    conn: sqlite3.Connection,
    *movements: Movement,
    now: str = NOW,
    moved: dict[str, str] | None = None,
) -> receipt_match.Matches:
    with conn:
        return receipt_match.reconcile(conn, movements, now, moved=moved)


def _links(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    return {r.orders[0] + "/" + r.kind: r.links for r in receipt_store.load(conn)}


def test_an_order_is_linked_to_its_only_exact_charge(conn: sqlite3.Connection) -> None:
    _store(conn, samples.order_email())

    found = _reconcile(conn, charge("tx-1", "130.56"), charge("tx-2", "35.80"))

    assert len(found.links) == 2 and found.proposals == {}
    assert _links(conn) == {
        f"{samples.FIRST_ORDER}/order": ("tx-1",),
        f"{samples.SECOND_ORDER}/order": ("tx-2",),
    }
    origins = {row[0] for row in conn.execute("SELECT origin FROM receipt_links")}
    assert origins == {"automatic"}


def test_running_it_again_changes_nothing(conn: sqlite3.Connection) -> None:
    _store(conn, samples.order_email())
    _reconcile(conn, charge("tx-1"))

    again = _reconcile(conn, charge("tx-1"), now=LATER)

    assert again.links == {}
    assert conn.execute("SELECT linked_at FROM receipt_links").fetchall()[0][0] == NOW


def test_a_receipt_without_a_charge_waits(conn: sqlite3.Connection) -> None:
    _store(conn, samples.shipment_email())

    assert _reconcile(conn, charge("tx-1", "130.56")).links == {}

    later = _reconcile(conn, charge("tx-1", "130.56"), charge("tx-9", "110.97"), now=LATER)
    assert list(later.links.values()) == ["tx-9"]


def test_two_candidates_are_proposed_and_nothing_is_written(conn: sqlite3.Connection) -> None:
    _store(conn, samples.shipment_email())
    rows = (charge("tx-1", "110.97"), charge("tx-2", "110.97", day=date(2026, 2, 16)))

    found = _reconcile(conn, *rows)

    assert found.links == {}
    assert list(found.proposals.values()) == [("tx-1", "tx-2")]
    assert receipt_match.proposals(conn, rows) == found.proposals
    assert conn.execute("SELECT COUNT(*) FROM receipt_links").fetchone()[0] == 0


def test_the_statement_amount_counts_not_the_persons_share(conn: sqlite3.Connection) -> None:
    _store(conn, samples.shipment_email())

    found = _reconcile(conn, charge("tx-1", "55.48", gross="110.97"))

    assert list(found.links.values()) == ["tx-1"]


def test_a_refund_is_never_a_candidate(conn: sqlite3.Connection) -> None:
    _store(conn, samples.shipment_email())

    assert _reconcile(conn, charge("tx-1", "-110.97")).links == {}


def test_a_removed_link_is_not_made_again(conn: sqlite3.Connection) -> None:
    _store(conn, samples.shipment_email())
    _reconcile(conn, charge("tx-1", "110.97"))
    (receipt,) = receipt_store.load(conn)
    with conn:
        receipt_store.unlink(conn, receipt.id, "tx-1", LATER)

    again = _reconcile(conn, charge("tx-1", "110.97"), now=LATER)

    assert again.links == {} and again.proposals == {}


def test_a_link_to_a_transaction_that_is_gone_is_looked_for_again(conn: sqlite3.Connection) -> None:
    # The provisional (alert-7) was replaced by its statement row under another fingerprint.
    _store(conn, samples.shipment_email())
    _reconcile(conn, charge("alert-7", "110.97"))

    found = _reconcile(conn, charge("tx-statement", "110.97"), now=LATER)

    assert list(found.links.values()) == ["tx-statement"]
    (receipt,) = receipt_store.load(conn)
    # The link to the transaction that no longer exists is dropped, not kept beside the new one.
    assert receipt.links == ("tx-statement",)


def test_a_charge_of_another_order_is_left_alone(conn: sqlite3.Connection) -> None:
    _store(
        conn,
        samples.order_email(),
        samples.shipment_email(
            message_id="m-s", text=samples.shipment_text(samples.SECOND_ORDER, "130.56"), html=""
        ),
    )

    found = _reconcile(conn, charge("tx-1", "130.56"))

    # The first order's confirmation and the second order's shipment both say 130.56.
    assert found.links == {}
    assert sorted(found.proposals.values()) == [("tx-1",), ("tx-1",)]


def test_removing_a_link_is_an_entry_that_can_be_undone(conn: sqlite3.Connection) -> None:
    _store(conn, samples.shipment_email())
    _reconcile(conn, charge("tx-1", "110.97"))
    (receipt,) = receipt_store.load(conn)

    with (
        conn,
        changelog.track(
            conn, "receipt", "transaction", "tx-1", "Amazon", fingerprints=["tx-1"]
        ) as draft,
    ):
        receipt_store.unlink(conn, receipt.id, "tx-1", LATER)
    assert receipt_store.load(conn)[0].links == ()
    assert draft.entry_id is not None

    with conn:
        changelog.undo(conn, draft.entry_id)

    assert receipt_store.load(conn)[0].links == ("tx-1",)
    assert receipt_store.dismissed(conn) == set()
    origin = conn.execute("SELECT origin, linked_at FROM receipt_links").fetchone()
    assert tuple(origin) == ("automatic", NOW)


def test_nothing_is_loaded_when_no_receipt_is_waiting(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from michelito.analysis import spending

    _store(conn, samples.shipment_email())
    _reconcile(conn, charge("tx-1", "110.97"))
    calls: list[int] = []
    monkeypatch.setattr(spending, "load_all", lambda *args, **kwargs: calls.append(1) or ())

    with conn:
        receipt_match.reconcile_stored(conn, LATER)

    assert calls == []


def test_a_waiting_receipt_loads_the_flow_once(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from michelito.analysis import spending

    _store(conn, samples.shipment_email())
    calls: list[int] = []
    monkeypatch.setattr(spending, "load_all", lambda *args, **kwargs: calls.append(1) or ())

    with conn:
        receipt_match.reconcile_stored(conn, LATER)

    assert calls == [1]


def test_a_refusal_made_on_a_provisional_holds_for_its_statement_row(
    conn: sqlite3.Connection,
) -> None:
    _store(conn, samples.shipment_email())
    (receipt,) = receipt_store.load(conn)
    with conn:
        receipt_store.dismiss(conn, receipt.id, "alert-7", NOW)

    found = _reconcile(
        conn, charge("tx-statement", "110.97"), now=LATER, moved={"alert-7": "tx-statement"}
    )

    assert found.links == {} and found.proposals == {}


def test_a_confirmed_link_follows_the_provisional_to_its_statement_row(
    conn: sqlite3.Connection,
) -> None:
    _store(conn, samples.shipment_email())
    (receipt,) = receipt_store.load(conn)
    with conn:
        receipt_store.link(conn, receipt.id, "alert-7", "confirmed", NOW)

    _reconcile(conn, charge("tx-statement", "110.97"), now=LATER, moved={"alert-7": "tx-statement"})

    rows = conn.execute(
        "SELECT fingerprint, origin FROM receipt_links ORDER BY fingerprint"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("tx-statement", "confirmed")]


def test_a_forwarded_receipt_is_proposed_even_with_a_single_candidate(
    conn: sqlite3.Connection,
) -> None:
    # Anyone who knows the forwarding address can send a genuine email of their own order.
    with conn:
        receipt_store.record(conn, samples.shipment_email(), "forwarding", NOW)

    found = _reconcile(conn, charge("tx-1", "110.97"))

    assert found.links == {}
    assert list(found.proposals.values()) == [("tx-1",)]
