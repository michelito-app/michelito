"""Shared groups: split per expense, reimbursements (FIFO), what is pending and how they count."""

import sqlite3
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import ClassVar

import pytest

from michelito import db
from michelito.analysis import catalog, links, shared, spending
from michelito.analysis import categories as cat
from michelito.analysis.links import Links, ManualEntry, Shared, SharedExpense
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from tests.test_spending import _add_bank_rows, seed

D = Decimal
RATES = {"2026-01": Rate(D("60"), "2026-01", "bcrd")}


def _move(
    day: str,
    amount: str,
    fp: str,
    category: str = cat.RESTAURANTS,
    link: str = "",
    currency: str = "DOP",
    merchant: str | None = None,
    description: str | None = None,
    note: str = "",
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=fp if merchant is None else merchant,
        description=fp if description is None else description,
        category=category,
        amount=D(amount),
        currency=currency,
        institution="x",
        fingerprint=fp,
        account="A",
        link=link,
        note=note,
    )


def _credit(day: str, amount: str, fp: str, **kw) -> Movement:
    return _move(day, f"-{amount}", fp, category=cat.OTHER_INCOME, **kw)


def _state(link: Shared, moves: list[Movement], rates=None) -> shared.SharedState:
    return shared.states(moves, Links((link,)), rates or {})[link.id]


class TestMath:
    def test_equal_split_rounds_to_the_cent(self) -> None:
        assert shared.nominal_share(SharedExpense("g", people=3), D("1850.00")) == D("616.67")
        assert shared.nominal_share(SharedExpense("g", people=2), D("0.05")) == D("0.02")

    def test_my_share_and_paid_for_someone_else(self) -> None:
        assert shared.nominal_share(SharedExpense("g", my_share=D(400)), D(1000)) == D(400)
        assert shared.nominal_share(SharedExpense("g", for_other=True), D(1000)) == 0

    def test_pending_is_what_they_still_owe(self) -> None:
        expense = _move("2026-01-01", "3000", "g", link="shared")
        state = _state(
            Shared.one(1, "g", people=3, reimbursements=("c1",)),
            [expense, _credit("2026-01-02", "1000", "c1")],
        )
        [e] = state.expenses
        assert (e.share, e.reimbursed, e.pending, e.counted) == (D(1000), D(1000), D(1000), D(1000))
        assert state.pending == {"DOP": D(1000)}

    def test_manual_entries_count_as_reimbursed(self) -> None:
        cash = ManualEntry(1, D(500), date(2026, 1, 3), "DOP", "Ana", "")
        state = _state(
            Shared.one(1, "g", people=2, manual=(cash,)),
            [_move("2026-01-01", "1000", "g", link="shared")],
        )
        assert (state.expenses[0].pending, state.expenses[0].counted, state.pending) == (
            0,
            D(500),
            {},
        )

    def test_excess_is_ignored_and_reported_for_the_group(self) -> None:
        cash = ManualEntry(1, D(400), date(2026, 1, 3), "DOP")
        link = Shared.one(1, "g", people=2, reimbursements=("c1",), manual=(cash,))
        moves = [
            _move("2026-01-01", "1000", "g", link="shared"),
            _credit("2026-01-02", "300", "c1"),
        ]
        state = _state(link, moves)
        assert (state.expenses[0].reimbursed, state.expenses[0].counted) == (D(500), D(500))
        assert state.excess == {"DOP": D(200)}

    def test_written_off_pending_goes_back_to_your_spending(self) -> None:
        link = Shared.one(1, "g", people=4, written_off=True, reimbursements=("c1",))
        moves = [
            _move("2026-01-01", "4000", "g", link="shared"),
            _credit("2026-01-02", "1000", "c1"),
        ]
        [e] = _state(link, moves).expenses
        assert (e.pending, e.written_off, e.counted) == (0, D(2000), D(3000))

    def test_paid_for_someone_else_counts_zero_and_pending_is_everything(self) -> None:
        [e] = _state(
            Shared.one(1, "g", for_other=True), [_move("2026-01-01", "800", "g", link="shared")]
        ).expenses
        assert (e.counted, e.pending) == (0, D(800))

    def test_missing_credits_are_ignored(self) -> None:
        link = Shared.one(1, "g", people=2, reimbursements=("gone",))
        state = _state(link, [_move("2026-01-01", "100", "g", link="shared")])
        assert state.pending == {"DOP": D(50)}


class TestGroups:
    """Several expenses with the same people and reimbursements without saying for which one:
    oldest to newest."""

    def _trip(self, **kw) -> Shared:
        return Shared(
            1,
            (
                SharedExpense("flights", for_other=True),  # US$ 100, the oldest
                SharedExpense("agency", people=2),  # RD$ 12,000: you are owed 6,000
            ),
            with_whom="Carola and Rafael",
            **kw,
        )

    def _moves(self, *credits: Movement) -> list[Movement]:
        return [
            _move("2026-01-02", "12000", "agency", link="shared"),
            _move("2026-01-01", "100", "flights", link="shared", currency="USD"),
            *credits,
        ]

    def test_peso_refunds_settle_the_oldest_then_part_of_the_next(self) -> None:
        # RD$ 9,000 at 60: US$ 100 settle the flights (RD$ 6,000) and RD$ 3,000 go to the agency.
        link = self._trip(reimbursements=("t1",))
        state = _state(link, self._moves(_credit("2026-01-10", "9000", "t1")), RATES)
        flights, agency = state.expenses
        assert [e.fingerprint for e in state.expenses] == ["flights", "agency"]
        assert (flights.reimbursed, flights.pending) == (D(100), 0)
        assert (agency.reimbursed, agency.pending) == (D(3000), D(3000))
        assert state.pending == {"DOP": D(3000)}
        assert state.excess == {}

    def test_refunds_go_in_date_order_manual_ones_included(self) -> None:
        cash = ManualEntry(7, D(3000), date(2026, 1, 5), "DOP")
        link = self._trip(reimbursements=("t1",), manual=(cash,))
        # The manual one (January 5) goes before the transfer (10th): it settles US$ 50 of flights.
        state = _state(link, self._moves(_credit("2026-01-10", "6000", "t1")), RATES)
        flights, agency = state.expenses
        assert (flights.reimbursed, agency.reimbursed) == (D(100), D(3000))
        assert [r.key for r in state.refunds] == ["manual:7", "t1"]

    def test_excess_only_after_settling_everything(self) -> None:
        link = self._trip(reimbursements=("t1", "t2"))
        partial = self._moves(_credit("2026-01-10", "11000", "t1"))
        assert _state(replace(link, reimbursements=("t1",)), partial, RATES).excess == {}
        moves = self._moves(
            _credit("2026-01-10", "11000", "t1"), _credit("2026-01-11", "2000", "t2")
        )
        state = _state(link, moves, RATES)
        assert state.pending == {}
        assert state.excess == {"DOP": D(1000)}

    def test_each_expense_keeps_its_own_split(self) -> None:
        link = self._trip()
        flights, agency = _state(link, self._moves(), RATES).expenses
        assert (flights.share, flights.counted) == (0, 0)
        assert (agency.share, agency.counted) == (D(6000), D(6000))
        assert [(t.currency, t.share, t.pending) for t in _state(link, self._moves()).totals] == [
            ("DOP", D(6000), D(6000)),
            ("USD", 0, D(100)),
        ]

    def test_written_off_lands_on_the_newest_expenses(self) -> None:
        link = self._trip(reimbursements=("t1",), written_off=True)
        flights, agency = _state(
            link, self._moves(_credit("2026-01-10", "9000", "t1")), RATES
        ).expenses
        assert (flights.written_off, flights.counted) == (0, 0)
        assert (agency.written_off, agency.counted) == (D(3000), D(9000))

    def test_without_a_rate_the_refund_does_not_count_and_is_reported(self) -> None:
        link = Shared(1, (SharedExpense("flights", for_other=True),), reimbursements=("t1",))
        state = _state(link, self._moves(_credit("2026-01-10", "9000", "t1")))
        assert state.pending == {"USD": D(100)}
        assert state.unconverted == ("t1",)
        assert state.uncounted == frozenset({"t1"})

    def test_same_day_ties_are_stable(self) -> None:
        link = Shared(
            1,
            (SharedExpense("b", for_other=True), SharedExpense("a", for_other=True)),
            reimbursements=("c",),
        )
        moves = [
            _move("2026-01-01", "100", "b", link="shared"),
            _move("2026-01-01", "100", "a", link="shared"),
            _credit("2026-01-02", "150", "c"),
        ]
        a, b = _state(link, moves).expenses
        assert (a.fingerprint, a.pending, b.pending) == ("a", 0, D(50))

    def test_rounding_leftovers_are_not_excess(self) -> None:
        # Two of RD$ 3,000.35 at 60 (US$ 50.01 each) for a US$ 100 expense: RD$ 0.95 is left over
        # when converting back to DOP, which is rounding, not an over-reimbursement.
        dollars = Shared(1, (SharedExpense("e", for_other=True),), reimbursements=("a", "b"))
        moves = [
            _move("2026-01-01", "100", "e", link="shared", currency="USD"),
            _credit("2026-01-02", "3000.35", "a"),
            _credit("2026-01-03", "3000.35", "b"),
        ]
        state = _state(dollars, moves, RATES)
        assert (state.pending, state.excess) == ({}, {})
        # In the same currency, less than US$ 0.05 is not excess either.
        cents = _state(
            Shared(1, (SharedExpense("e", for_other=True),), reimbursements=("c",)),
            [
                _move("2026-01-01", "100", "e", link="shared", currency="USD"),
                _credit("2026-01-02", "100.04", "c", currency="USD"),
            ],
        )
        assert cents.excess == {}
        real = _state(
            Shared(1, (SharedExpense("e", for_other=True),), reimbursements=("c",)),
            [
                _move("2026-01-01", "100", "e", link="shared", currency="USD"),
                _credit("2026-01-02", "100.05", "c", currency="USD"),
            ],
        )
        assert real.excess == {"USD": D("0.05")}

    def test_without_a_rate_for_the_oldest_the_refund_goes_to_the_next(self) -> None:
        # No rates: the RD$ cannot settle the flights in US$ (the oldest), but they can settle the
        # agency in DOP.
        link = self._trip(reimbursements=("t1",))
        state = _state(link, self._moves(_credit("2026-01-10", "4000", "t1")))
        flights, agency = state.expenses
        assert (flights.reimbursed, agency.reimbursed, agency.pending) == (0, D(4000), D(2000))
        assert (state.unconverted, state.excess) == ((), {})
        # What is left after the agency is not excess: it belonged to the flights and there is
        # no rate.
        more = _state(link, self._moves(_credit("2026-01-10", "8000", "t1")))
        assert (more.expenses[1].pending, more.excess, more.unconverted) == (0, {}, ("t1",))
        assert more.uncounted == frozenset()  # something counted: still a "Reimbursement"

    def test_with_links_counts_each_expense_by_its_part(self, conn) -> None:
        known = catalog.load(conn)
        link = self._trip(reimbursements=("t1",))
        raw = [
            _move("2026-01-02", "12000", "agency"),
            _move("2026-01-01", "100", "flights", currency="USD"),
            _credit("2026-01-10", "9000", "t1"),
        ]
        agency, flights, refund = spending.with_links(raw, Links((link,)), known, rates=RATES)
        assert (agency.amount, agency.gross, flights.amount) == (D(6000), D(12000), 0)
        assert refund.link == "reimbursement"
        # A group of one expense counts as before.
        single = Shared.one(2, "agency", people=2)
        [alone] = spending.with_links([raw[0]], Links((single,)), known)
        assert alone.amount == D(6000)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)
    # A small credit 3 days after the coffee (TOKE DE ...) and another outside the window.
    _add_bank_rows(
        connection,
        [
            ("2026-01-04", "TOKE DE PEDRO INVENTADO", "credit", "10000"),
            ("2026-01-25", "TOKE DE LUISA INVENTADA", "credit", "5000"),
            ("2026-01-03", "TOKE DE MARTA INVENTADA", "credit", "50000"),  # larger than the expense
        ],
    )
    yield connection
    connection.close()


def _by(conn, text: str) -> Movement:
    return next(m for m in spending.load_all(conn) if m.description.startswith(text))


def _share(conn, people=3, **kw) -> int:
    cafe = _by(conn, "CAFE FICTICIO")  # RD$ 300 on January 1 on the Popular card
    with conn:
        return links.set_shared(conn, cafe.fingerprint, cafe.amount, people=people, **kw)


class TestLoad:
    def test_a_shared_expense_counts_only_your_part(self, conn) -> None:
        _share(conn)
        cafe = _by(conn, "CAFE FICTICIO")
        assert (cafe.amount, cafe.gross, cafe.link, cafe.kind) == (
            D(100),
            D(300),
            "shared",
            "expense",
        )

    def test_a_linked_credit_is_a_reimbursement_not_income(self, conn) -> None:
        group = _share(conn)
        toke = _by(conn, "TOKE DE PEDRO")
        assert (toke.category, toke.kind) == (cat.OTHER_INCOME, "income")
        with conn:
            links.add_reimbursement(conn, group, toke.fingerprint)
        linked = _by(conn, "TOKE DE PEDRO")
        assert (linked.ref, linked.kind, linked.link) == (
            cat.REIMBURSEMENT,
            "transfer",
            "reimbursement",
        )
        assert linked.original_category == cat.OTHER_INCOME
        assert _by(conn, "CAFE FICTICIO").amount == D(100)  # still your part

    def test_removing_the_last_expense_deletes_the_group(self, conn) -> None:
        group = _share(conn)
        cafe = _by(conn, "CAFE FICTICIO")
        toke = _by(conn, "TOKE DE PEDRO")
        with conn:
            links.add_reimbursement(conn, group, toke.fingerprint)
            links.set_written_off(conn, group, True)
            links.add_manual(conn, group, D(50), date(2026, 1, 2), "DOP", "Ana")
        with conn:
            assert links.unshare(conn, cafe.fingerprint) is True
        assert _by(conn, "TOKE DE PEDRO").kind == "income"
        assert _by(conn, "CAFE FICTICIO").amount == D(300)
        for table in ("links", "link_members", "link_manual"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0

    def test_removing_one_expense_keeps_the_group_and_its_refunds(self, conn) -> None:
        group = _share(conn)
        cafe = _by(conn, "CAFE FICTICIO")
        pharmacy = _by(conn, "FARMACIA")
        toke = _by(conn, "TOKE DE PEDRO")
        with conn:
            links.add_expense(conn, group, pharmacy.fingerprint, pharmacy.amount, people=2)
            links.add_reimbursement(conn, group, toke.fingerprint)
        with conn:
            assert links.unshare(conn, cafe.fingerprint) is False
        [left] = links.load(conn).shared
        assert [e.fingerprint for e in left.expenses] == [pharmacy.fingerprint]
        assert left.reimbursements == (toke.fingerprint,)
        assert _by(conn, "CAFE FICTICIO").amount == D(300)
        assert _by(conn, "TOKE DE PEDRO").link == "reimbursement"

    def test_written_off_brings_the_pending_back(self, conn) -> None:
        group = _share(conn)
        with conn:
            links.set_written_off(conn, group, True)
        assert _by(conn, "CAFE FICTICIO").amount == D(300)

    def test_nothing_linked_leaves_every_movement_untouched(self, conn) -> None:
        before = spending.load_all(conn)
        assert spending.with_links(before, links.NONE, catalog.load(conn)) == before
        _share(conn)
        with conn:
            links.unshare(conn, _by(conn, "CAFE FICTICIO").fingerprint)
        assert spending.load_all(conn) == before

    def test_links_survive_reprocessing(self, conn) -> None:
        group = _share(conn)
        toke = _by(conn, "TOKE DE PEDRO")
        with conn:
            links.add_reimbursement(conn, group, toke.fingerprint)
            conn.execute("UPDATE transactions SET id = id + 100000")  # like parse --retry
        assert _by(conn, "TOKE DE PEDRO").link == "reimbursement"
        assert _by(conn, "CAFE FICTICIO").link == "shared"


class TestStorage:
    def test_split_validation(self, conn) -> None:
        cafe = _by(conn, "CAFE FICTICIO")
        bad = [
            {},
            {"people": 1},
            {"people": 2, "my_share": D(10)},
            {"my_share": D(0)},
            {"my_share": D(301)},
            {"my_share": D("1.001")},
        ]
        for kw in bad:
            with pytest.raises(links.LinkError):
                links.set_shared(conn, cafe.fingerprint, cafe.amount, **kw)
        with pytest.raises(links.LinkError):
            links.set_shared(conn, "x", D(-5), people=2)

    def test_changing_the_split_keeps_the_group(self, conn) -> None:
        group = _share(conn, with_whom="  my   sister ")
        cafe = _by(conn, "CAFE FICTICIO")
        toke = _by(conn, "TOKE DE PEDRO")
        with conn:
            links.add_reimbursement(conn, group, toke.fingerprint)
            again = links.set_shared(conn, cafe.fingerprint, D(300), for_other=True)
        assert again == group
        [link] = links.load(conn).shared
        assert (link.expenses, link.with_whom, link.reimbursements) == (
            (SharedExpense(cafe.fingerprint, for_other=True),),
            "my sister",
            (toke.fingerprint,),
        )

    def test_name_and_with_whom(self, conn) -> None:
        group = _share(conn)
        with conn:
            links.set_group(conn, group, name=" Fictional  Island  trip ", with_whom="Carola")
        assert (links.load(conn).shared[0].name, links.load(conn).shared[0].with_whom) == (
            "Fictional Island trip",
            "Carola",
        )
        with conn:
            links.set_group(conn, group, name="")
        assert links.load(conn).shared[0].name == ""
        assert links.load(conn).shared[0].with_whom == "Carola"  # absent: unchanged
        with pytest.raises(links.LinkError):
            links.set_group(conn, group, name="x" * 81)
        with pytest.raises(LookupError):
            links.set_group(conn, 999, name="x")

    def test_each_fingerprint_is_in_at_most_one_link(self, conn) -> None:
        group = _share(conn)
        cafe = _by(conn, "CAFE FICTICIO")
        other = _by(conn, "FARMACIA")
        toke = _by(conn, "TOKE DE PEDRO")
        with conn:
            second = links.set_shared(conn, other.fingerprint, other.amount, people=2)
            links.add_reimbursement(conn, group, toke.fingerprint)
        with pytest.raises(links.AlreadyLinked):
            links.add_reimbursement(conn, second, toke.fingerprint)
        with pytest.raises(links.AlreadyLinked):  # nor can it be a shared expense
            links.set_shared(conn, toke.fingerprint, D(100), people=2)
        with pytest.raises(links.AlreadyLinked):  # an expense is in a single group
            links.add_expense(conn, second, cafe.fingerprint, D(300), people=2)

    def test_the_database_itself_refuses_a_second_link(self, conn) -> None:
        _share(conn)
        cafe = _by(conn, "CAFE FICTICIO")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO link_members (link_id, fingerprint, role, added_at) VALUES "
                "((SELECT link_id FROM link_members), ?, 'reimbursement', 'x')",
                (cafe.fingerprint,),
            )

    def test_manual_entries_and_remembered_places(self, conn) -> None:
        group = _share(conn)
        with conn:
            first = links.add_manual(
                conn, group, D(50), date(2026, 1, 2), "DOP", "Ana", "Banreservas"
            )
            # "Efectivo" (cash, the UI's value) stores no place.
            links.add_manual(conn, group, D(20), date(2026, 1, 3), "USD", None, "Efectivo")
        [link] = links.load(conn).shared
        assert [(m.amount, m.person, m.place, m.currency) for m in link.manual] == [
            (D(50), "Ana", "Banreservas", "DOP"),
            (D(20), "", "", "USD"),
        ]
        assert links.places(conn) == ["Banreservas"]
        with conn:
            links.remove_manual(conn, group, first)
        assert len(links.load(conn).shared[0].manual) == 1
        with pytest.raises(links.LinkError):
            links.add_manual(conn, group, D(0), date(2026, 1, 3), "DOP")
        with pytest.raises(links.LinkError):
            links.add_manual(conn, group, D(5), date(2026, 1, 3), "EUR")
        with pytest.raises(LookupError):
            links.add_manual(conn, 999, D(5), date(2026, 1, 3), "DOP")


class TestCandidates:
    def test_credits_months_later_smaller_than_the_expense(self, conn) -> None:
        group = _share(conn)
        found_links = links.load(conn)
        movements = spending.load_all(conn)
        state = shared.states(movements, found_links)[group]
        texts = [m.description for m in shared.candidates(state, movements, found_links)]
        # TRANSFERENCIA RECIBIDA does not fit: it is more than the expense. Luisa's comes weeks
        # later (it fits: people sometimes pay months later). Bank interest is never a
        # reimbursement.
        assert texts == ["TOKE DE PEDRO INVENTADO", "TOKE DE LUISA INVENTADA"]

    def test_salary_card_payments_and_own_transfers_are_never_candidates(self) -> None:
        state = _state(
            Shared.one(1, "e", people=2), [_move("2026-01-01", "300", "e", link="shared")]
        )
        bad = [
            replace(_move("2026-01-02", "-10", fp=f"c{i}"), category=ref)
            for i, ref in enumerate((cat.SALARY, cat.CARD_PAYMENT, cat.OWN_TRANSFER))
        ]
        interest = _credit("2026-01-02", "1", "int", description="PAGO INTERESES CA")
        good = _credit("2026-01-02", "10", "ok")
        found = shared.candidates(state, [*bad, interest, good], Links())
        assert [m.fingerprint for m in found] == ["ok"]

    def test_picker_reaches_months_after_the_newest_expense(self) -> None:
        link = Shared(1, (SharedExpense("e", people=2), SharedExpense("f", people=2)))
        state = _state(
            link,
            [
                _move("2026-01-01", "300", "e", link="shared"),
                _move("2026-01-10", "300", "f", link="shared"),
            ],
        )
        edge = _credit("2026-05-10", "100", "edge")  # 120 days after the newest
        late = _credit("2026-05-11", "100", "late")
        before = _credit("2025-12-31", "100", "before")
        between = _credit("2026-01-05", "100", "between")
        found = shared.candidates(state, [edge, late, before, between], Links())
        assert [m.fingerprint for m in found] == ["between", "edge"]

    def test_a_transfer_can_cover_several_expenses(self) -> None:
        link = Shared(1, (SharedExpense("e", for_other=True), SharedExpense("f", for_other=True)))
        state = _state(
            link,
            [
                _move("2026-01-01", "300", "e", link="shared"),
                _move("2026-01-02", "300", "f", link="shared"),
            ],
        )
        both = _credit("2026-01-05", "600", "both")
        too_much = _credit("2026-01-05", "601", "much")
        picked = shared.pick_credits(state, [both, too_much], Links())
        assert [(c.move.fingerprint, c.primary) for c in picked] == [("both", True)]

    def test_picker_puts_credits_that_fit_the_pending_first(self) -> None:
        # A 300 expense split in 3: you are owed 200, 100 already paid back by hand: 100 pending.
        cash = ManualEntry(1, D(100), date(2026, 1, 1), "DOP")
        state = _state(
            Shared.one(1, "e", people=3, manual=(cash,)),
            [_move("2026-01-01", "300", "e", link="shared")],
        )
        big = _credit("2026-01-02", "150", "big")  # does not fit
        late = _credit("2026-01-20", "100", "late")
        edge = _credit("2026-01-10", "104", "edge")  # fits within 5%
        found = shared.pick_credits(state, [big, late, edge], Links())
        assert [(c.move.fingerprint, c.primary) for c in found] == [
            ("edge", True),
            ("late", True),
            ("big", False),
        ]

    def test_credit_side_lists_groups_with_pending(self) -> None:
        small = _move("2026-01-05", "120", "small", link="shared")  # you are owed 80
        wide = _move("2026-01-01", "300", "wide", link="shared")  # you are owed 200
        credit = _credit("2026-01-06", "100", "c")
        found = Links((Shared.one(1, "small", people=3), Shared.one(2, "wide", people=3)))
        groups = shared.states([small, wide, credit], found)
        options = shared.pick_groups(credit, groups)
        assert [(c.state.id, c.primary) for c in options] == [(2, True), (1, False)]
        months = _credit("2026-03-15", "50", "m")
        assert [g.id for g in shared.groups_for(months, groups)] == [1, 2]

    def test_open_groups_newest_first(self) -> None:
        old = _move("2026-01-01", "300", "old", link="shared")
        new = _move("2026-02-01", "300", "new", link="shared")
        paid = _move("2026-03-01", "300", "paid", link="shared")
        found = Links(
            (
                Shared.one(1, "old", people=2),
                Shared.one(2, "new", people=2),
                Shared.one(3, "paid", people=2, written_off=True),
            )
        )
        groups = shared.states([old, new, paid], found)
        assert [g.id for g in shared.open_groups(groups)] == [2, 1]

    def test_expenses_to_add_same_merchant_or_name_first(self) -> None:
        link = Shared.one(1, "flights", for_other=True, with_whom="Carola and Rafael")
        flights = _move("2026-01-10", "500", "flights", link="shared", merchant="AEROLINEA")
        state = _state(link, [flights])
        near = _move("2026-01-11", "100", "near", merchant="COLMADO")
        same = _move("2026-03-01", "200", "same", merchant="AEROLINEA")
        named = _move("2026-02-01", "300", "named", merchant="AGENCIA", note="Trip with Rafael")
        far = _move("2026-06-01", "300", "far", merchant="AEROLINEA")  # more than 120 days
        credit = _credit("2026-01-11", "50", "credit")
        linked = _move("2026-01-11", "100", "linked", link="exchange")
        picked = shared.pick_expenses(
            state, [flights, near, same, named, far, credit, linked], Links()
        )
        assert [(c.move.fingerprint, c.primary) for c in picked] == [
            ("named", True),
            ("same", True),
            ("near", False),
        ]

    def test_with_excess_the_expense_that_fits_it_goes_first(self) -> None:
        # US$ 912.37 too much came back: an expense is missing. Among many, the US$ 941.81 one is
        # within 5 % of the excess: it goes first and is the only primary one. The small ones no
        # longer are (fitting is not enough), nor is RD$ 120,000 (US$ 2,000 at 60). A withdrawal
        # and an automatic payment of a similar amount are not expenses people share: they do
        # not even show up.
        link = Shared(1, (SharedExpense("hotel", for_other=True),), reimbursements=("t",))
        hotel = _move("2026-01-10", "1000", "hotel", link="shared", currency="USD")
        transfer = _credit("2026-01-20", "1912.37", "t", currency="USD")
        state = _state(link, [hotel, transfer], RATES)
        assert state.excess == {"USD": D("912.37")}
        noise = [
            _move(f"2026-01-{day:02d}", str(100 + day), f"g{day}", merchant=f"COMERCIO {day}")
            for day in range(1, 29)
        ]
        flights = _move("2026-01-25", "941.81", "flights", currency="USD", merchant="AEROLINEA")
        big = _move("2026-01-11", "120000", "big", merchant="OTHER")
        cash = _move("2026-01-12", "58600", "withdrawal", category=cat.CASH, merchant="RETIRO")
        loan = _move("2026-01-13", "980", "aut", category=cat.LOANS, currency="USD")
        moves = [*noise, big, cash, loan, flights]
        picked = shared.pick_expenses(state, moves, Links(), RATES)
        assert (picked[0].move.fingerprint, picked[0].primary) == ("flights", True)
        assert [c.move.fingerprint for c in picked if c.primary] == ["flights"]
        assert {"withdrawal", "aut"}.isdisjoint(c.move.fingerprint for c in picked)
        assert len(picked) == len(noise) + 2  # the rest, behind "Show more"

    def test_no_suggestion_when_nothing_is_shared(self) -> None:
        assert shared.suggestions([_credit("2026-01-06", "100", "credit")], Links(), {}) == {}


class TestSuggestions:
    def test_by_amount_toward_the_closest_group(self) -> None:
        early = _move("2026-01-01", "300", "early", link="shared")
        late = _move("2026-01-05", "300", "late", link="shared")
        credit = _credit("2026-01-06", "100", "credit")
        big = _credit("2026-01-06", "250", "big")
        found = Links((Shared.one(1, "early", people=3), Shared.one(2, "late", people=3)))
        moves = [early, late, credit, big]
        assert shared.suggestions(moves, found, shared.states(moves, found)) == {"credit": 2}

    def test_by_amount_stays_within_two_weeks_and_the_same_currency(self) -> None:
        expense = _move("2026-01-01", "300", "e", link="shared")
        near = _credit("2026-01-15", "100", "near")
        far = _credit("2026-01-16", "100", "far")
        dollars = _credit("2026-01-02", "1", "usd", currency="USD")
        found = Links((Shared.one(1, "e", people=3),))
        moves = [expense, near, far, dollars]
        assert shared.suggestions(moves, found, shared.states(moves, found), RATES) == {"near": 1}

    def _named(self) -> tuple[list[Movement], Links]:
        trip = _move("2026-01-01", "100", "trip", link="shared", currency="USD")
        dinner = _move("2026-01-20", "3000", "dinner", link="shared")
        found = Links(
            (
                # The Spanish "y" (and) must not match; the accent must fold.
                Shared.one(1, "trip", for_other=True, with_whom="Carola y Rafael"),  # spanish-data
                Shared.one(2, "dinner", people=2, with_whom="Rafael Pérez"),  # spanish-data
            )
        )
        return [trip, dinner], found

    def test_by_name_any_currency_folding_accents_and_case(self) -> None:
        moves, found = self._named()
        # RD$ 6,300 at 60 = US$ 105: fits the US$ 100 pending with the 5 % margin.
        transfer = _credit("2026-03-01", "6300", "t", description="TRANSF. DE CAROLA INVENTADA")
        all_moves = [*moves, transfer]
        groups = shared.states(all_moves, found, RATES)
        assert shared.suggestions(all_moves, found, groups, RATES) == {"t": 1}
        # Without a rate to convert it to US$, nothing is suggested.
        assert shared.suggestions(all_moves, found, shared.states(all_moves, found), {}) == {}

    def test_by_name_the_credit_has_to_fit_the_pending(self) -> None:
        moves, found = self._named()
        big = _credit("2026-03-01", "6400", "t", description="TRANSF. DE CAROLA INVENTADA")
        all_moves = [*moves, big]
        groups = shared.states(all_moves, found, RATES)
        assert shared.suggestions(all_moves, found, groups, RATES) == {}

    def test_by_name_ignores_short_words_and_matches_accents(self) -> None:
        moves, found = self._named()
        # "Y" is too short to count.
        short = _credit("2026-03-01", "500", "s", description="ENVIO DE Y MAS")
        accented = _credit("2026-03-01", "500", "p", description="PAGO PEREZ")
        all_moves = [*moves, short, accented]
        groups = shared.states(all_moves, found, RATES)
        assert shared.suggestions(all_moves, found, groups, RATES) == {"p": 2}

    def test_by_name_with_several_groups_picks_the_oldest_pending(self) -> None:
        moves, found = self._named()
        both = _credit("2026-03-01", "500", "b", description="DE RAFAEL")
        all_moves = [*moves, both]
        groups = shared.states(all_moves, found, RATES)
        assert shared.suggestions(all_moves, found, groups, RATES) == {"b": 1}

    def test_by_name_within_the_window_of_the_oldest_pending(self) -> None:
        moves, found = self._named()
        late = _credit("2026-05-21", "500", "l", description="DE CAROLA")  # 140 days
        all_moves = [*moves, late]
        groups = shared.states(all_moves, found, RATES)
        assert shared.suggestions(all_moves, found, groups, RATES) == {}


def test_one_offs_and_monthly_totals_use_the_adjusted_amount() -> None:
    from michelito.analysis import one_offs

    known = catalog.load(db.connect(":memory:"))
    trip = _move("2026-01-10", "45000", fp="trip", category=cat.TRAVEL)
    found = Links((Shared.one(1, "trip", people=5),))
    [adjusted] = spending.with_links([trip], found, known)
    assert adjusted.amount == D(9000)
    assert spending.monthly_totals([adjusted], "DOP", ("2026-01",)) == {"2026-01": D(9000)}

    def rate(_month: str) -> None:
        return None  # everything in DOP

    assert one_offs.suggest([trip], "2026-01", rate_for_month=rate, dismissed=())
    assert not one_offs.suggest([adjusted], "2026-01", rate_for_month=rate, dismissed=())


class TestOtherCurrency:
    """A US$ expense reimbursed in DOP (or the other way round): at the credit month's rate."""

    RATES: ClassVar[dict[str, Rate]] = RATES

    def test_converted_at_the_credit_month_rate(self) -> None:
        credit = _credit("2026-02-03", "3000", "c")  # RD$ 3,000
        # February has no rate: it uses the closest earlier month (January, 60).
        assert shared.converted(credit, "USD", self.RATES) == D("50.00")
        assert shared.converted(credit, "DOP", self.RATES) == D("3000")
        assert shared.converted(credit, "USD", {}) is None  # without a rate it cannot be converted
        usd = replace(credit, currency="USD", amount=D("-10"))
        assert shared.converted(usd, "DOP", self.RATES) == D("600.00")

    def test_rounds_to_the_cent(self) -> None:
        assert shared.converted(_credit("2026-01-05", "1000", "c"), "USD", self.RATES) == D("16.67")

    def test_peso_credits_reimburse_a_dollar_expense(self) -> None:
        expense = _move("2026-01-01", "100", "e", link="shared", currency="USD")
        credit = _credit("2026-01-20", "3000", "c")  # US$ 50
        link = Shared.one(1, "e", for_other=True, reimbursements=("c",))
        state = _state(link, [expense, credit], self.RATES)
        assert (state.expenses[0].reimbursed, state.pending) == (D("50.00"), {"USD": D("50.00")})
        assert _state(link, [expense, credit]).expenses[0].reimbursed == 0

    def test_picker_lists_other_currency_credits_up_to_the_expense(self) -> None:
        expense = _move("2026-01-01", "100", "e", link="shared", currency="USD")
        state = _state(Shared.one(1, "e", for_other=True), [expense], self.RATES)
        fits = _credit("2026-01-20", "3000", "fits")  # US$ 50
        whole = _credit("2026-01-20", "6000", "whole")  # US$ 100: all of it came back
        too_big = _credit("2026-01-21", "6060", "big")  # US$ 101
        moves = [fits, whole, too_big]
        found = shared.candidates(state, moves, Links(), self.RATES)
        assert [m.fingerprint for m in found] == ["whole", "fits"]  # same day: the larger first
        assert shared.candidates(state, moves, Links()) == []  # without a rate, nothing

    def test_with_links_counts_the_converted_credit(self, conn) -> None:
        known = catalog.load(conn)
        expense = _move("2026-01-01", "100", "e", currency="USD")
        credit = _credit("2026-01-20", "3000", "c")  # US$ 50
        found = Links((Shared.one(1, "e", people=2, reimbursements=("c",)),))
        adjusted, relabeled = spending.with_links([expense, credit], found, known, rates=self.RATES)
        assert (adjusted.amount, adjusted.gross, adjusted.link) == (D("50.00"), D("100"), "shared")
        assert (relabeled.link, relabeled.category) == ("reimbursement", cat.REIMBURSEMENT)

    def test_without_a_rate_the_credit_stays_as_it_was(self, conn) -> None:
        known = catalog.load(conn)
        expense = _move("2026-01-01", "100", "e", currency="USD")
        credit = _credit("2026-01-20", "3000", "c")
        found = Links((Shared.one(1, "e", for_other=True, reimbursements=("c",)),))
        adjusted, untouched = spending.with_links([expense, credit], found, known)
        assert adjusted.amount == D(0)  # your part; US$ 100 is still pending
        assert untouched == credit  # it does not lower the expense, so it is still income
