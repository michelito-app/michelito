"""The month in progress of the BHD savings account (portal, before the cut) is a printout."""

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db, report
from michelito.analysis import coverage, spending
from michelito.parsers import bhd_savings
from michelito.parsers.common import ParseError, validate_statement
from michelito.web import accounts as accounts_view
from michelito.web.schemas import StatementLineOut
from tests import samples
from tests.helpers import store
from tests.layout import page

BHD = "bhd:savings:999-1"
PARTIAL = bhd_savings.parse(samples.BHD_AHORRO_PORTAL_PARTIAL_PAGES)
FULL = bhd_savings.parse(samples.BHD_AHORRO_PORTAL_PAGES)


@pytest.fixture
def conn():
    """Empty database: `test_spending.seed` already brings an official January of this account."""
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def bhd_rows(connection: sqlite3.Connection) -> list[spending.Movement]:
    return [m for m in spending.load_all(connection) if m.account == BHD]


class TestParser:
    def test_partial_is_a_printout_up_to_the_last_row(self) -> None:
        assert PARTIAL.parser == bhd_savings.PARTIAL_NAME
        assert PARTIAL.parser in db.PRINTOUT_PARSERS
        assert (PARTIAL.period_start, PARTIAL.period_end) == (date(2026, 1, 1), date(2026, 1, 10))
        assert (PARTIAL.institution, PARTIAL.kind, PARTIAL.identifier) == (
            FULL.institution,
            FULL.kind,
            FULL.identifier,
        )

    def test_partial_closes_at_the_last_running_balance(self) -> None:
        (section,) = PARTIAL.sections
        assert (section.previous_balance, section.closing_balance) == (
            Decimal("10000.00"),
            Decimal("12000.00"),
        )
        assert [t.balance for t in section.transactions] == [
            Decimal("15000.00"),
            Decimal("12000.00"),
        ]
        assert validate_statement(PARTIAL) == ()

    def test_partial_with_a_broken_chain_is_invalid(self) -> None:
        broken = bhd_savings.parse(bhd_partial(balances=("15,000.00", "12,500.00")))
        problems = validate_statement(broken)
        assert broken.parser == bhd_savings.PARTIAL_NAME
        assert any("imprime balance 12500.00" in p for p in problems)  # spanish-ui

    def test_previous_balance_line_starts_the_day_after(self) -> None:
        pages = bhd_partial(opening_line="Balance anterior: 31/12/2025")  # spanish-data
        assert bhd_savings.parse(pages).period_start == date(2026, 1, 1)

    def test_partial_without_the_opening_date_fails(self) -> None:
        with pytest.raises(ParseError, match="start of the current month"):
            bhd_savings.parse(bhd_partial(opening_line="No opening date"))

    def test_row_before_the_period_start_fails(self) -> None:
        with pytest.raises(ParseError, match="before the start of the period"):
            opening_line = "Balance inicial: 06/01/2026"  # spanish-data
            bhd_savings.parse(bhd_partial(opening_line=opening_line))

    def test_full_portal_month_is_unchanged(self) -> None:
        assert FULL.parser == bhd_savings.NAME
        assert (FULL.period_start, FULL.period_end) == (None, date(2026, 1, 31))
        (section,) = FULL.sections
        assert all(t.balance is None for t in section.transactions)

    def test_month_that_really_ends_at_zero_is_also_a_printout(self) -> None:
        # "Balance final" 0.00 with no rows up to the cut is the month in progress even if the
        # chain reaches 0.00: storing it as a printout is safe (it counts while there is no
        # official statement and never blocks importing the full month later).
        statement = bhd_savings.parse(
            bhd_partial(opening="-2,000.00", balances=("3,000.00", "0.00"))
        )
        assert statement.parser == bhd_savings.PARTIAL_NAME
        assert statement.period_end == date(2026, 1, 10)
        assert statement.sections[0].closing_balance == Decimal("0.00")
        assert validate_statement(statement) == ()

    def test_email_statement_is_unchanged(self) -> None:
        email = bhd_savings.parse(samples.BHD_AHORRO_PAGES)
        assert email.parser == bhd_savings.NAME
        assert (email.period_start, email.period_end) == (None, date(2026, 1, 31))
        assert validate_statement(email) == ()

    def test_email_2025_with_zero_final_is_not_a_printout(self) -> None:
        rows = tuple(
            line.replace("12,000.50", "0.00") if line.strip() == "12,000.50" else line
            for line in samples.BHD_AHORRO_2025_ROWS
            if "INTERESES" not in line
        )
        statement = bhd_savings.parse((page(*rows),))
        assert statement.parser == bhd_savings.NAME


class TestStorage:
    def test_partial_alone_counts(self, conn) -> None:
        store(conn, PARTIAL)
        assert len(bhd_rows(conn)) == 2

    def test_full_month_is_kept_and_wins(self, conn) -> None:
        store(conn, PARTIAL)
        store(conn, FULL)
        parsers = [
            r[0]
            for r in conn.execute(
                "SELECT parser FROM statements WHERE parser LIKE 'bhd_savings%' ORDER BY id"
            )
        ]
        assert parsers == [bhd_savings.PARTIAL_NAME, bhd_savings.NAME]
        assert len(bhd_rows(conn)) == len(FULL.sections[0].transactions)
        partial_id = conn.execute(
            "SELECT id FROM statements WHERE parser = ?", (bhd_savings.PARTIAL_NAME,)
        ).fetchone()[0]
        covered = coverage.bank_coverage(conn)
        assert not any(
            covered.keeps(partial_id, t.transacted_on) for t in PARTIAL.sections[0].transactions
        )

    def test_same_partial_twice_is_duplicate(self, conn) -> None:
        store(conn, PARTIAL)
        with pytest.raises(sqlite3.IntegrityError, match=db.DUPLICATE_PRINTOUT_INDEX):
            store(conn, PARTIAL)

    def test_accounts_labels_the_partial_as_printout(self, conn) -> None:
        store(conn, PARTIAL)
        store(conn, FULL)
        view = next(v for v in accounts_view.account_views(conn, date(2026, 2, 5)) if v.key == BHD)
        assert [(line.printout, line.period_end) for line in view.statements] == [
            (False, date(2026, 1, 31)),
            (True, date(2026, 1, 10)),
        ]
        assert StatementLineOut.of(view.statements[1]).printout is True

    def test_report_counts_only_the_full_month(self, conn) -> None:
        store(conn, PARTIAL)
        lines, _ = report._coverage(conn, date(2026, 2, 5), date(2026, 1, 1), 60)
        assert not any("999-1" in line for line in lines)
        store(conn, FULL)
        lines, _ = report._coverage(conn, date(2026, 2, 5), date(2026, 1, 1), 60)
        assert "1 closings" in next(line for line in lines if "999-1" in line)


def test_old_indexes_learn_the_bhd_printout(tmp_path: Path) -> None:
    path = tmp_path / "before_bhd_partial.db"
    with closing(db.connect(path)) as old:
        old.executescript(
            "DROP INDEX statements_unique_printout; DROP INDEX statements_unique_period;"
            "CREATE UNIQUE INDEX statements_unique_period ON statements "
            "(account_id, COALESCE(card_id, 0), currency, period_end) "
            "WHERE parser NOT IN ('popular_web', 'banreservas_partial');"
            "CREATE UNIQUE INDEX statements_unique_printout ON statements ("
            "account_id, currency, COALESCE(period_start, ''), period_end, "
            "COALESCE(closing_balance_cents, 0), COALESCE(printed_debits_cents, 0), "
            "COALESCE(printed_credits_cents, 0), COALESCE(transaction_count, 0)) "
            "WHERE parser IN ('popular_web', 'banreservas_partial');"
            f"PRAGMA user_version = {db.SCHEMA_VERSION - 1};"  # an up-to-date one is not migrated
        )
    for _ in range(2):  # idempotent
        with closing(db.connect(path)) as connection:
            for name in (db.DUPLICATE_PERIOD_INDEX, db.DUPLICATE_PRINTOUT_INDEX):
                sql = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
                ).fetchone()[0]
                assert "bhd_savings_partial" in sql
                assert "banreservas_partial" in sql


def bhd_partial(**changes) -> tuple:
    return samples.bhd_ahorro_portal_partial(**changes)  # spanish-data: name in samples.py
