"""Suggestions around the ledger (`analysis.ledger_suggest`) and the store's contacts
(`analysis.ledger_store`): names in transfers, matching contacts, likely expenses, payment
candidates and the reverse flow; aliases and merging. Made-up names and amounts."""

from __future__ import annotations

from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import categories as cat
from michelito.analysis import ledger, ledger_store, ledger_suggest
from michelito.analysis.ledger import Contact, Entry, Group, Ledger, Member, Payment
from michelito.analysis.links import LinkError, Links
from michelito.analysis.spending import Movement

D = Decimal
ME, ANA, LUIS = 1, 2, 3
BANKS = frozenset({"checking"})


def _move(
    day: str,
    amount: str,
    description: str,
    fp: str | None = None,
    account: str = "checking",
    category: str = cat.OTHER_INCOME,
    currency: str = "DOP",
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=description,
        description=description,
        category=category,
        amount=D(amount),
        currency=currency,
        institution="x",
        fingerprint=fp or description,
        account=account,
    )


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("TRANSFERENCIA DE ANA FICTICIA REF 123456", "ANA FICTICIA"),  # spanish-data
        ("TOKE DE LUIS INVENTADO", "LUIS INVENTADO"),
        ("TRANSF. DE ROSA FICTICIA CTA 0001", "ROSA FICTICIA"),
        ("TRANSFERENCIA RECIBIDA DE PEDRO INVENTADO", "PEDRO INVENTADO"),  # spanish-data
        ("DEPOSITO NOMINA EMPRESA INVENTADA", None),
        ("PAGO INTERESES CA", None),
    ],
)
def test_transfer_name(text: str, name: str | None) -> None:
    assert ledger_suggest.transfer_name(text) == name


def test_bank_names_skip_known_contacts_and_count_repeats() -> None:
    moves = [
        _move("2026-01-02", "-100", "TOKE DE ANA FICTICIA", "a"),
        _move("2026-01-09", "-100", "TOKE DE ANA FICTICIA", "b"),
        _move("2026-01-05", "-100", "TOKE DE LUIS INVENTADO", "c"),
        _move("2026-01-05", "100", "TOKE DE ROSA FICTICIA", "d"),  # a debit: not incoming
    ]
    book = Ledger(
        ME, {ME: Contact(ME, "me", True), LUIS: Contact(LUIS, "Luis", aliases=("LUIS INVENTADO",))}
    )
    [ana] = ledger_suggest.bank_names(moves, book)
    assert (ana.name, ana.raw, ana.count, ana.last_day) == (
        "Ana Ficticia",
        "ANA FICTICIA",
        2,
        date(2026, 1, 9),
    )


def test_matches_contact_by_alias_or_every_long_word_of_its_name() -> None:
    ana = Contact(ANA, "Ana", aliases=("ANA FICTICIA",))
    assert ledger_suggest.matches_contact(ana, "TRANSFERENCIA DE ANA FICTICIA")
    assert not ledger_suggest.matches_contact(ana, "TRANSFERENCIA DE ANA MARIA")  # alias only
    luis = Contact(LUIS, "Luis Inventado")
    assert ledger_suggest.matches_contact(luis, "toke de luis inventado sa")
    assert not ledger_suggest.matches_contact(luis, "TOKE DE LUIS")


def test_expense_candidates_put_likely_ones_first() -> None:
    today = date(2026, 2, 1)
    moves = [
        _move("2026-01-20", "450", "CAFE", category=cat.RESTAURANTS, account="visa"),
        _move("2026-01-10", "2500", "CENA", category=cat.RESTAURANTS, account="visa"),
        _move("2026-01-15", "3000", "TIENDA", category=cat.SHOPPING, account="visa"),  # round
        _move("2026-01-25", "1234.5", "REGALO", category=cat.SHOPPING, account="visa"),
        _move("2025-08-01", "5000", "VIEJA", category=cat.RESTAURANTS, account="visa"),  # old
        _move("2026-01-02", "5000", "CAJERO", category=cat.CASH, account="visa"),  # never shared
    ]
    found = ledger_suggest.expense_candidates(moves, Links(), today, {})
    assert [(c.move.description, c.likely) for c in found] == [
        ("TIENDA", True),
        ("CENA", True),
        ("REGALO", False),
        ("CAFE", False),
    ]
    busy = Links(ledger={"TIENDA": (1, "entry")})
    assert "TIENDA" not in {
        c.move.description for c in ledger_suggest.expense_candidates(moves, busy, today, {})
    }


def test_payment_candidates_tolerance_window_and_name_first() -> None:
    moves = [
        _move("2026-01-20", "-1250", "TOKE DE OTRA PERSONA", "other"),
        _move("2026-01-21", "-1240", "TOKE DE ANA FICTICIA", "ana"),
        _move("2026-01-22", "-1350", "TOKE DE MUY LEJOS", "far"),  # out of 5%
        _move("2026-02-10", "-1250", "TOKE TARDE", "late"),  # out of 7 days
        _move("2026-01-20", "-1250", "SALARIO", "salary", category=cat.SALARY),
        _move("2026-01-19", "1250", "TRANSFERENCIA A ANA", "sent", category=cat.THIRD_PARTY),
    ]
    ana = Contact(ANA, "Ana", aliases=("ANA FICTICIA",))
    found = ledger_suggest.payment_candidates(
        moves,
        Links(),
        BANKS,
        received=True,
        amount=D(1250),
        currency="DOP",
        day=date(2026, 1, 20),
        contact=ana,
    )
    assert [m.fingerprint for m in found] == ["ana", "other"]
    paid = ledger_suggest.payment_candidates(
        moves, Links(), BANKS, received=False, amount=D(1250), currency="DOP", day=date(2026, 1, 20)
    )
    assert [m.fingerprint for m in paid] == ["sent"]


def _book(payments: tuple[Payment, ...] = ()) -> tuple[Ledger, dict[int, ledger.GroupState]]:
    entry = Entry(
        1,
        1,
        ME,
        D(3000),
        "DOP",
        date(2026, 1, 10),
        "Hotel",
        ledger.equal_split(D(3000), [ME, ANA, LUIS], ME),
    )
    group = Group(1, "Trip", (Member(ME), Member(ANA), Member(LUIS)), (entry,), payments)
    contacts = {
        ME: Contact(ME, "me", True),
        ANA: Contact(ANA, "Ana", aliases=("ANA FICTICIA",)),
        LUIS: Contact(LUIS, "Luis Inventado"),
    }
    book = Ledger(ME, contacts, (group,))
    return book, ledger.states(book, {})


def test_reverse_flow_proposes_a_credit_from_someone_who_owes() -> None:
    book, states = _book()
    moves = [
        _move("2026-01-20", "-1000", "TRANSFERENCIA DE ANA FICTICIA", "ana"),
        _move("2026-01-05", "-1000", "TOKE DE LUIS INVENTADO", "early"),  # before the expense
        _move("2026-01-25", "-5000", "TOKE DE LUIS INVENTADO", "too-much"),  # more than he owes
        _move("2026-01-26", "-900", "TOKE DE NADIE", "nobody"),
    ]
    found = ledger_suggest.reverse_suggestions(moves, Links(), book, states)
    assert set(found) == {"ana"}
    assert (found["ana"].group_id, found["ana"].contact_id, found["ana"].amount) == (
        1,
        ANA,
        D(1000),
    )


def test_reverse_flow_proposes_linking_an_unlinked_payment() -> None:
    written = Payment(7, 1, LUIS, ME, D(1000), "DOP", date(2026, 1, 22))
    book, states = _book((written,))
    moves = [_move("2026-01-24", "-990", "DEPOSITO SIN NOMBRE", "dep")]
    found = ledger_suggest.reverse_suggestions(moves, Links(), book, states)
    assert (found["dep"].payment_id, found["dep"].contact_id) == (7, LUIS)


@pytest.fixture
def conn(tmp_path: Path):
    with closing(db.connect(tmp_path / "michelito.db")) as connection:
        yield connection


class TestStore:
    def test_the_user_is_created_once(self, conn) -> None:
        with conn:
            first = ledger_store.ensure_me(conn)
            assert ledger_store.ensure_me(conn) == first
        assert ledger_store.load(conn).me == first

    def test_contacts_by_name_or_alias_and_aliases_are_unique(self, conn) -> None:
        with conn:
            ana = ledger_store.contact_for(conn, "Ána", "ANA FICTICIA")  # spanish-data
            assert ledger_store.contact_for(conn, "ana") == ana
            assert ledger_store.find_contact(conn, "Ana Ficticia") == ana
            luis = ledger_store.create_contact(conn, "Luis")
            with pytest.raises(LinkError):
                ledger_store.add_alias(conn, luis, "ana ficticia")
            ledger_store.add_alias(conn, ana, "ANA FICTICIA")  # again: nothing changes
        assert ledger_store.load(conn).contacts[ana].aliases == ("ANA FICTICIA",)

    def test_merging_adds_shares_and_keeps_the_name_as_an_alias(self, conn) -> None:
        with conn:
            me = ledger_store.ensure_me(conn)
            ana = ledger_store.create_contact(conn, "Ana")
            twin = ledger_store.create_contact(conn, "Ana F")
            group = ledger_store.create_group(conn, "Trip", [ana, twin])
            splits = ledger_store.build_splits(D(300), me, "equal", [me, ana, twin])
            ledger_store.add_entry(
                conn, group, paid_by=me, amount=D(300), currency="DOP", day=date(2026, 1, 1),
                description="x", splits=splits, mode="equal",
            )  # fmt: skip
            ledger_store.merge_contacts(conn, twin, ana)
            with pytest.raises(LinkError):
                ledger_store.merge_contacts(conn, ana, me)
        book = ledger_store.load(conn)
        [entry] = book.groups[0].entries
        assert {s.contact_id: s.share for s in entry.splits} == {me: D(100), ana: D(200)}
        assert book.contacts[ana].aliases == ("Ana F",) and twin not in book.contacts
        assert [m.contact_id for m in book.groups[0].members] == [me, ana]

    def test_a_member_in_use_cannot_leave_and_payments_need_the_user(self, conn) -> None:
        with conn:
            me = ledger_store.ensure_me(conn)
            ana = ledger_store.create_contact(conn, "Ana")
            luis = ledger_store.create_contact(conn, "Luis")
            group = ledger_store.create_group(conn, "Trip", [ana, luis])
            ledger_store.add_payment(
                conn, group, from_contact=ana, to_contact=me, amount=D(10), currency="DOP",
                day=date(2026, 1, 2),
            )  # fmt: skip
            with pytest.raises(LinkError):
                ledger_store.remove_member(conn, group, ana)
            ledger_store.remove_member(conn, group, luis)
            with pytest.raises(LinkError):
                ledger_store.add_payment(
                    conn, group, from_contact=ana, to_contact=luis, amount=D(10),
                    currency="DOP", day=date(2026, 1, 2),
                )  # fmt: skip
            with pytest.raises(LinkError):
                ledger_store.build_splits(D(100), me, "exact", shares={me: D(30), ana: D(60)})
            with pytest.raises(LinkError):
                ledger_store.build_splits(D(100), me, "equal", [])
        assert [m.contact_id for m in ledger_store.load(conn).groups[0].members] == [me, ana]
