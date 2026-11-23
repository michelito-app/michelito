"""Installment plans as stored (`analysis.installment_store`, schema 25), made-up values."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db, migrations_v25
from michelito.analysis import installment_store as store
from michelito.analysis import ledger_store
from michelito.analysis.links import LinkError
from michelito.analysis.spending import Movement

NOW = "2026-03-20T12:00:00+00:00"
CARD = "bank:credit_card"
DESCRIPTION = "Store.com*XY12AB STORE.COM/BILL"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "michelito.db")) as opened:
        yield opened


def entries(conn: sqlite3.Connection) -> list:
    return [e for g in ledger_store.load(conn).groups for e in g.entries]


def move(fingerprint: str, day: date, amount: str = "150.00") -> Movement:
    return Movement(
        day=day,
        merchant="STORE",
        description=DESCRIPTION,
        category="Online shopping",
        amount=Decimal(amount),
        currency="USD",
        institution="bank",
        fingerprint=fingerprint,
        account=CARD,
    )


FLOW = [move("a", date(2026, 3, 10)), move("b", date(2026, 4, 9))]


def create(conn: sqlite3.Connection, **extra: object) -> int:
    with conn:
        return store.create(
            conn,
            name="Phone (Store)",
            account=CARD,
            matcher="store.com*",
            amount_cents=15000,
            currency="USD",
            count=4,
            first_month="2026-03",
            now=NOW,
            **extra,  # type: ignore[arg-type]
        )


def test_the_schema_has_the_installment_tables(conn: sqlite3.Connection) -> None:
    assert db.SCHEMA_VERSION == migrations_v25.VERSION
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"installment_plans", "installment_links", "installment_dismissals"} <= tables


def test_reconcile_links_each_charge_as_its_installment(conn: sqlite3.Connection) -> None:
    plan_id = create(conn)

    with conn:
        store.reconcile(conn, FLOW, NOW)

    plan = store.load(conn)[0]
    assert plan.id == plan_id
    assert plan.links == {1: "a", 2: "b"}
    assert plan.entries == {}


def test_a_members_installment_becomes_their_whole_share_in_the_group(
    conn: sqlite3.Connection,
) -> None:
    with conn:
        brother = ledger_store.contact_for(conn, "Person B")
        group = ledger_store.create_group(conn, "Phone", [brother])
    create(conn, group_id=group, contact_id=brother)

    with conn:
        store.reconcile(conn, FLOW, NOW)

    plan = store.load(conn)[0]
    assert set(plan.entries) == {1, 2}
    found = entries(conn)
    assert len(found) == 2
    assert all(
        [(s.contact_id, s.share) for s in e.splits] == [(brother, Decimal("150.00"))] for e in found
    )
    assert set(ledger_store.linked_fingerprints(conn)) == {"a", "b"}


def test_reconcile_twice_changes_nothing(conn: sqlite3.Connection) -> None:
    with conn:
        brother = ledger_store.contact_for(conn, "Person B")
        group = ledger_store.create_group(conn, "Phone", [brother])
    create(conn, group_id=group, contact_id=brother)

    with conn:
        store.reconcile(conn, FLOW, NOW)
        store.reconcile(conn, FLOW, NOW)

    assert len(entries(conn)) == 2


def test_a_charge_shared_by_hand_already_is_linked_without_a_new_expense(
    conn: sqlite3.Connection,
) -> None:
    with conn:
        brother = ledger_store.contact_for(conn, "Person B")
        group = ledger_store.create_group(conn, "Phone", [brother])
        me = ledger_store.ensure_me(conn)
        ledger_store.add_entry(
            conn,
            group,
            paid_by=me,
            amount=Decimal("150.00"),
            currency="USD",
            day=date(2026, 3, 10),
            description="Phone",
            splits=ledger_store.build_splits(
                Decimal("150.00"), me, "exact", shares={brother: Decimal("150.00")}
            ),
            mode="exact",
            fingerprint="a",
        )
    create(conn, group_id=group, contact_id=brother)

    with conn:
        store.reconcile(conn, FLOW, NOW)

    plan = store.load(conn)[0]
    assert plan.links == {1: "a", 2: "b"}
    assert set(plan.entries) == {2}  # the expense shared by hand stays the user's
    assert len(entries(conn)) == 2


def test_unlinking_refuses_the_charge_and_removes_its_expense(conn: sqlite3.Connection) -> None:
    with conn:
        brother = ledger_store.contact_for(conn, "Person B")
        group = ledger_store.create_group(conn, "Phone", [brother])
    plan_id = create(conn, group_id=group, contact_id=brother)
    with conn:
        store.reconcile(conn, FLOW, NOW)

    with conn:
        store.unlink(conn, plan_id, "b", NOW)
        store.reconcile(conn, FLOW, NOW)

    plan = store.load(conn)[0]
    assert plan.links == {1: "a"}
    assert len(entries(conn)) == 1
    assert store.dismissed(conn) == {(plan_id, "b")}


def test_confirming_links_a_charge_with_the_number_given(conn: sqlite3.Connection) -> None:
    plan_id = create(conn)
    odd = move("c", date(2026, 5, 11), "151.00")

    with conn:
        store.confirm(conn, plan_id, odd, 3, NOW)

    assert store.load(conn)[0].links == {3: "c"}


def test_deleting_a_plan_removes_the_expenses_it_recorded(conn: sqlite3.Connection) -> None:
    with conn:
        brother = ledger_store.contact_for(conn, "Person B")
        group = ledger_store.create_group(conn, "Phone", [brother])
    plan_id = create(conn, group_id=group, contact_id=brother)
    with conn:
        store.reconcile(conn, FLOW, NOW)

    with conn:
        store.delete(conn, plan_id)

    assert store.load(conn) == []
    assert entries(conn) == []


def test_off_script_charges_are_reported(conn: sqlite3.Connection) -> None:
    plan_id = create(conn)
    flow = [*FLOW, move("r", date(2026, 4, 20), "-150.00")]

    with conn:
        found = store.reconcile(conn, flow, NOW)

    assert found.off_script["r"].reason == "refund"
    assert found.off_script["r"].plan_id == plan_id


@pytest.mark.parametrize(
    "odd",
    [
        Movement(**{**move("x", date(2026, 5, 11)).__dict__, "account": "other:credit_card"}),
        Movement(**{**move("x", date(2026, 5, 11)).__dict__, "currency": "DOP"}),
        Movement(**{**move("x", date(2026, 5, 11)).__dict__, "provisional": True}),
        move("x", date(2026, 5, 11), "-150.00"),
    ],
)
def test_confirming_refuses_a_charge_that_cannot_be_the_plans(
    conn: sqlite3.Connection, odd: Movement
) -> None:
    plan_id = create(conn)

    with pytest.raises(LinkError), conn:
        store.confirm(conn, plan_id, odd, 3, NOW)


def test_deleting_the_group_deletes_a_members_plan(conn: sqlite3.Connection) -> None:
    with conn:
        brother = ledger_store.contact_for(conn, "Person B")
        group = ledger_store.create_group(conn, "Phone", [brother])
    create(conn, group_id=group, contact_id=brother)

    with conn:
        ledger_store.delete_group(conn, group)

    assert store.load(conn) == []
