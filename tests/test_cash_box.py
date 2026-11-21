"""Cash box: balance by currency, stored withdrawals, entries, exits, opening balance and deposits,
with synthetic movements (no HTTP)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db
from michelito.analysis import (
    cash_box,
    cash_box_store,
    catalog,
    corrections,
    links,
    review,
    spending,
)
from michelito.analysis import categories as cat
from michelito.analysis.accounts import CASH_BOX_KEY, account_infos
from michelito.analysis.cash_box import CashBoxError, ManualEntry
from michelito.analysis.links import CashBox, CashBoxMember, Links
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from michelito.web import summary
from tests.ledger_helpers import share
from tests.test_spending import _add_bank_rows, seed

D = Decimal
MONTH = "2026-01"
WITHDRAWAL = "RETIRO CAJERO AUTOMATICO INVENTADO"
DEPOSIT = "DEPOSITO EFECTIVO INVENTADO"
SALARY = "PAGO NOMINA EMPRESA INVENTADA"
RATES = {MONTH: Rate(D("60"), MONTH, "bcrd")}


@pytest.fixture
def conn(tmp_path: Path) -> Iterator:
    with closing(db.connect(tmp_path / "cash.db")) as found:
        seed(found)
        _add_bank_rows(
            found,
            [
                ("2026-01-10", WITHDRAWAL, "debit", "2000000"),
                ("2026-01-12", WITHDRAWAL, "debit", "300000"),
                ("2026-01-15", SALARY, "credit", "8000000"),
                ("2026-01-25", DEPOSIT, "credit", "500000"),
            ],
        )
        yield found


def _flow(conn) -> dict[str, Movement]:
    return {m.fingerprint: m for m in spending.load_all(conn)}


def _by_text(conn, text: str) -> list[Movement]:
    found = [m for m in spending.load_all(conn) if m.description == text]
    return sorted(found, key=lambda m: m.day)


def _state(conn) -> cash_box.BoxState:
    found = links.load(conn)
    box = found.cash_boxes[0] if found.cash_boxes else None
    return cash_box.state_of(box, cash_box_store.load_entries(conn), spending.load_all(conn), RATES)


def _summary(conn) -> summary.Summary:
    return summary.build_summary(spending.load_all(conn), account_infos(conn), RATES, MONTH)


def _write(conn, action, *args, **kwargs):
    with conn:
        return action(conn, *args, **kwargs)


class TestStoredWithdrawal:
    def test_by_default_a_withdrawal_is_spending_in_cash(self, conn) -> None:
        big, _ = _by_text(conn, WITHDRAWAL)
        assert (big.category, big.kind) == (cat.CASH, "expense")
        assert _state(conn).balances == ()
        assert not links.load(conn).cash_boxes  # nothing is created until it is used
        assert CASH_BOX_KEY not in {a.key for a in account_infos(conn)}

    def test_storing_it_takes_it_out_of_spending_and_keeps_what_you_kept(self, conn) -> None:
        big, _ = _by_text(conn, WITHDRAWAL)
        before = _summary(conn)
        _write(conn, cash_box_store.store, big.fingerprint)
        stored = _flow(conn)[big.fingerprint]
        assert (stored.ref, stored.kind, stored.link) == (
            cat.CASH_BOX,
            "transfer",
            "cash_box",
        )
        after = _summary(conn)
        assert after.total == before.total - D(20000)
        assert after.net == before.net + D(20000)  # it stops taking from what you kept
        assert after.to_cash_box == D(20000)
        assert after.third_party == before.third_party
        assert _state(conn).balances == (("DOP", D(20000)),)
        # The cash box account shows up in the account filter as soon as it is used.
        assert CASH_BOX_KEY in {a.key for a in account_infos(conn)}

    def test_undo_returns_it_to_spending(self, conn) -> None:
        big, _ = _by_text(conn, WITHDRAWAL)
        before = _summary(conn)
        _write(conn, cash_box_store.store, big.fingerprint)
        _write(conn, cash_box_store.remove, big.fingerprint, "stored")
        assert _flow(conn)[big.fingerprint].category == cat.CASH
        assert _summary(conn).total == before.total
        assert _state(conn).balances == ()
        with pytest.raises(LookupError):
            _write(conn, cash_box_store.remove, big.fingerprint, "stored")

    def test_a_stored_withdrawal_is_not_in_spending_reports_nor_alerts(self, conn) -> None:
        big, small = _by_text(conn, WITHDRAWAL)
        _write(conn, cash_box_store.store, big.fingerprint)
        spent = {m.fingerprint for m in spending.load_movements(conn)}
        assert big.fingerprint not in spent and small.fingerprint in spent
        flow = spending.load_all(conn)
        found = review.detect(flow, MONTH, rate_for_month=lambda m: RATES.get(m))
        assert big.fingerprint not in {item.fingerprint for item in found}

    def test_only_a_cash_debit_without_another_link_can_be_stored(self, conn) -> None:
        big, _ = _by_text(conn, WITHDRAWAL)
        [salary] = _by_text(conn, SALARY)
        found = links.load(conn)
        assert cash_box.can_store(big, found)
        assert not cash_box.can_store(salary, found)
        _write(conn, cash_box_store.store, big.fingerprint)
        assert not cash_box.can_store(_flow(conn)[big.fingerprint], links.load(conn))
        with pytest.raises(links.AlreadyLinked):
            _write(conn, cash_box_store.store, big.fingerprint)


class TestManualEntries:
    def test_an_exit_is_spending_in_its_category_and_month(self, conn) -> None:
        before = _summary(conn)
        groceries = catalog.load(conn).by_ref(cat.GROCERIES)
        assert groceries is not None
        entry = _write(
            conn,
            cash_box_store.add_entry,
            "expense",
            date(2026, 1, 20),
            D("1500"),
            "DOP",
            category=groceries.id,
            note="Colmado de la esquina",  # spanish-data
        )
        move = _flow(conn)[cash_box.entry_fingerprint(entry)]
        assert (move.category, move.kind, move.amount, move.month) == (
            cat.GROCERIES,
            "expense",
            D(1500),
            MONTH,
        )
        assert (move.account, move.note) == (CASH_BOX_KEY, "Colmado de la esquina")  # spanish-data
        after = _summary(conn)
        assert after.total == before.total + D(1500)
        lines = {line.category: line.amount for line in after.categories}
        assert lines[cat.GROCERIES] >= D(1500)
        assert _state(conn).balances == (("DOP", D(-1500)),)

    def test_an_exit_defaults_to_cash_and_its_category_can_be_corrected(self, conn) -> None:
        entry = _write(conn, cash_box_store.add_entry, "expense", date(2026, 1, 5), D(300), "DOP")
        fp = cash_box.entry_fingerprint(entry)
        assert _flow(conn)[fp].category == cat.CASH
        with conn:
            corrections.set_transaction_category(conn, fp, cat.RESTAURANTS)
            corrections.set_one_off(conn, fp, True)
        move = _flow(conn)[fp]
        assert (move.category, move.one_off, move.corrected) == (cat.RESTAURANTS, True, True)

    def test_an_entry_is_income_in_its_month(self, conn) -> None:
        before = _summary(conn)
        entry = _write(
            conn, cash_box_store.add_entry, "income", date(2026, 1, 9), D(4000), "DOP", note="Ana"
        )
        move = _flow(conn)[cash_box.entry_fingerprint(entry)]
        assert (move.category, move.kind, move.amount) == (cat.OTHER_INCOME, "income", D(-4000))
        assert _summary(conn).income == before.income + D(4000)
        assert _state(conn).balances == (("DOP", D(4000)),)

    def test_only_the_box_chosen_has_no_savings_rate(self, conn) -> None:
        """Like cards only: without a chosen bank account there is no cash flow nor savings %."""
        _write(conn, cash_box_store.add_entry, "income", date(2026, 1, 9), D(4000), "DOP")
        _write(conn, cash_box_store.add_entry, "expense", date(2026, 1, 9), D(500), "DOP")
        found = summary.build_summary(
            spending.load_all(conn), account_infos(conn), RATES, MONTH, {CASH_BOX_KEY}
        )
        assert (found.needs_income, found.net, found.savings_rate) == (True, None, None)
        assert (found.total, found.income) == (D(500), D(4000))

    def test_the_opening_balance_is_not_income_nor_a_movement(self, conn) -> None:
        before = _summary(conn)
        entry = _write(conn, cash_box_store.add_entry, "initial", date(2026, 1, 1), D(1000), "USD")
        assert cash_box.entry_fingerprint(entry) not in _flow(conn)
        after = _summary(conn)
        assert (after.income, after.total, after.net) == (before.income, before.total, before.net)
        state = _state(conn)
        assert state.balances == (("USD", D(1000)),)
        assert state.total_dop == D(60000)

    def test_categories_must_match_the_kind(self, conn) -> None:
        salary = catalog.load(conn).by_ref(cat.SALARY)
        assert salary is not None
        with pytest.raises(CashBoxError, match="de gasto"):  # spanish-ui
            _write(
                conn,
                cash_box_store.add_entry,
                "expense",
                date(2026, 1, 5),
                D(1),
                "DOP",
                category=salary.id,
            )
        with pytest.raises(CashBoxError):
            _write(conn, cash_box_store.add_entry, "expense", date(2026, 1, 5), D(0), "DOP")
        with pytest.raises(CashBoxError):
            _write(conn, cash_box_store.add_entry, "income", date(2026, 1, 5), D(1), "EUR")

    def test_edit_and_delete(self, conn) -> None:
        entry = _write(
            conn, cash_box_store.add_entry, "expense", date(2026, 1, 5), D(300), "DOP", note="x"
        )
        fp = cash_box.entry_fingerprint(entry)
        _write(conn, cash_box_store.update_entry, entry, date(2026, 1, 6), D(25), "USD")
        move = _flow(conn)[fp]
        assert (move.day, move.amount, move.currency, move.note) == (
            date(2026, 1, 6),
            D(25),
            "USD",
            "x",
        )
        _write(conn, cash_box_store.delete_entry, entry)
        assert fp not in _flow(conn)
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM transaction_notes WHERE fingerprint = ?", (fp,)
            ).fetchone()[0]
            == 0
        )
        # A deleted id is not reused: the next fingerprint is a different one.
        again = _write(conn, cash_box_store.add_entry, "expense", date(2026, 1, 5), D(1), "DOP")
        assert again != entry

    def test_a_shared_exit_counts_only_your_part_and_deleting_it_drops_the_group(
        self, conn
    ) -> None:
        entry = _write(conn, cash_box_store.add_entry, "expense", date(2026, 1, 5), D(900), "DOP")
        fp = cash_box.entry_fingerprint(entry)
        _write(conn, share, fp, D(900), people=3)
        assert _flow(conn)[fp].amount == D(300)
        _write(conn, cash_box_store.delete_entry, entry)
        assert conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
        assert links.load(conn).ledger == {}

    def test_manual_fingerprints_never_look_like_statement_ones(self) -> None:
        assert cash_box.entry_fingerprint(7) == "cash-7"
        assert cash_box.entry_id("cash-7") == 7
        assert cash_box.entry_id("cash-07") is None
        statement = corrections.fingerprint("a", date(2026, 1, 1), "cash-7", 100, "debit", "DOP", 0)
        assert cash_box.entry_id(statement) is None
        assert len(statement) == 24 and all(c in "0123456789abcdef" for c in statement)

    def test_manual_movements_survive_reprocessing_statements(self, conn) -> None:
        entry = _write(conn, cash_box_store.add_entry, "expense", date(2026, 1, 5), D(300), "DOP")
        fp = cash_box.entry_fingerprint(entry)
        with conn:  # like `parse --retry`: the statement rows are rebuilt
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM statements")
        assert fp in _flow(conn)


class TestDeposit:
    def test_a_linked_deposit_is_not_income_and_lowers_the_balance(self, conn) -> None:
        big, _ = _by_text(conn, WITHDRAWAL)
        [deposit] = _by_text(conn, DEPOSIT)
        before = _summary(conn)
        _write(conn, cash_box_store.store, big.fingerprint)
        _write(conn, cash_box_store.deposit, deposit.fingerprint)
        moved = _flow(conn)[deposit.fingerprint]
        assert (moved.ref, moved.kind) == (cat.CASH_BOX, "transfer")
        after = _summary(conn)
        assert after.income == before.income - D(5000)
        assert after.to_cash_box == D(20000)  # the deposit does not take from the line
        assert _state(conn).balances == (("DOP", D(15000)),)

    def test_salary_cannot_come_from_the_box(self, conn) -> None:
        [salary] = _by_text(conn, SALARY)
        [deposit] = _by_text(conn, DEPOSIT)
        banks = [a.key for a in account_infos(conn) if a.kind == "savings"]
        assert cash_box.can_deposit(deposit, links.NONE, banks)
        assert not cash_box.can_deposit(salary, links.NONE, banks)
        big, _ = _by_text(conn, WITHDRAWAL)
        assert not cash_box.can_deposit(big, links.NONE, banks)

    def test_only_plain_income_can_come_from_the_box(self, conn) -> None:
        [deposit] = _by_text(conn, DEPOSIT)
        banks = [deposit.account]
        assert cash_box.can_deposit(deposit, links.NONE, banks)
        for category in (cat.INVESTMENT_RETURN, cat.OWN_TRANSFER, cat.THIRD_PARTY, cat.SALARY):
            moved = replace(deposit, category=category, category_key=category, category_kind=None)
            assert not cash_box.can_deposit(moved, links.NONE, banks), category
        interest = replace(deposit, description="PAGO INTERESES CUENTA AHORRO")
        assert interest.ref == cat.OTHER_INCOME
        assert not cash_box.can_deposit(interest, links.NONE, banks)
        assert not cash_box.can_deposit(deposit, links.NONE, [])  # not from a bank

    def test_a_negative_balance_is_allowed_with_a_warning(self, conn) -> None:
        [deposit] = _by_text(conn, DEPOSIT)
        _write(conn, cash_box_store.deposit, deposit.fingerprint)
        state = _state(conn)
        assert state.balances == (("DOP", D(-5000)),)
        assert state.negative == (("DOP", D(-5000)),)
        assert cash_box.after(state, "DOP", D(-100)) == D(-5100)
        assert cash_box.after(state, "DOP", D(6000)) is None


def _move(day: str, amount: str, fp: str, currency: str = "DOP", **kw) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=fp,
        description=fp,
        category=kw.pop("category", cat.CASH),
        amount=D(amount),
        currency=currency,
        institution="ficticio",  # spanish-data
        fingerprint=fp,
        account="ficticio:savings:1",  # spanish-data
        **kw,
    )


class TestCurrencies:
    """Each movement in its currency; the total ≈ RD$ at its month's rate; without a rate, apart."""

    def _box(self, *members: CashBoxMember) -> CashBox:
        return CashBox(1, CASH_BOX_KEY, members)

    def test_balance_by_currency_with_and_without_rate(self) -> None:
        moves = [
            _move("2026-01-10", "1000", "usd", "USD", link="cash_box"),
            _move("2026-01-11", "5000", "dop", link="cash_box"),
            _move("2025-06-01", "50", "old", "USD", link="cash_box"),
        ]
        box = self._box(
            CashBoxMember("usd", "stored"),
            CashBoxMember("dop", "stored"),
            CashBoxMember("old", "stored"),
        )
        entries = [ManualEntry(1, "initial", date(2026, 1, 1), D(200), "USD")]
        state = cash_box.state_of(box, entries, moves, RATES)
        assert state.balances == (("DOP", D(5000)), ("USD", D(1250)))
        # US$ 1,200 at 60 and RD$ 5,000; the US$ 50 from June has no rate (nor an earlier one).
        assert state.total_dop == D(5000) + D(1200) * 60
        assert state.unconverted == (("USD", D(50)),)
        assert [line.fingerprint for line in state.lines] == ["dop", "usd", "cash-1", "old"]

    def test_a_dop_deposit_from_dollars_in_the_box(self) -> None:
        moves = [
            _move("2026-01-10", "1000", "usd", "USD", link="cash_box"),
            _move("2026-01-20", "-30000", "dop", category=cat.CASH_BOX, link="cash_box"),
        ]
        at_rate = self._box(CashBoxMember("usd", "stored"), CashBoxMember("dop", "deposit", "USD"))
        state = cash_box.state_of(at_rate, [], moves, RATES)
        assert state.balances == (("USD", D(500)),)  # RD$ 30,000 at 60 = US$ 500
        told = self._box(
            CashBoxMember("usd", "stored"), CashBoxMember("dop", "deposit", "USD", D(490))
        )
        assert cash_box.state_of(told, [], moves, RATES).balances == (("USD", D(510)),)

    def test_without_a_rate_the_deposit_does_not_count_and_is_reported(self) -> None:
        moves = [
            _move("2026-01-10", "1000", "usd", "USD", link="cash_box"),
            _move("2026-01-20", "-30000", "dop", category=cat.CASH_BOX, link="cash_box"),
        ]
        box = self._box(CashBoxMember("usd", "stored"), CashBoxMember("dop", "deposit", "USD"))
        state = cash_box.state_of(box, [], moves, {})
        assert state.balances == (("USD", D(1000)),)
        assert state.uncounted == ("dop",)
        assert state.total_dop == 0 and state.unconverted == (("USD", D(1000)),)

    def test_a_movement_that_no_longer_appears_does_not_count(self) -> None:
        box = self._box(CashBoxMember("gone", "stored"))
        assert cash_box.state_of(box, [], [], RATES).balances == ()

    def test_with_links_relabels_only_what_still_fits(self, tmp_path: Path) -> None:
        with closing(db.connect(tmp_path / "c.db")) as conn:
            known = catalog.load(conn)
        moves = [_move("2026-01-10", "100", "withdrawal"), _move("2026-01-11", "-50", "odd")]
        box = Links(
            cash_boxes=(
                self._box(CashBoxMember("withdrawal", "stored"), CashBoxMember("odd", "stored")),
            )
        )
        found = {m.fingerprint: m for m in spending.with_links(moves, box, known)}
        assert found["withdrawal"].ref == cat.CASH_BOX
        assert found["odd"].ref == cat.CASH  # no longer a debit: stays as it was
