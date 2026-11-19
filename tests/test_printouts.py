"""Portal printouts: stored with their range, and no movement is counted twice."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from michelito import db, report
from michelito.analysis import accounts, coverage, rates, spending
from michelito.ingest import process_documents
from michelito.parsers import banreservas_account, popular_account, popular_web
from michelito.parsers.common import Page
from michelito.web import accounts as accounts_view
from michelito.web import summary
from michelito.web.interest import interest_year
from michelito.web.schemas import StatementLineOut
from tests import samples
from tests.helpers import store
from tests.test_ingest import add_document
from tests.test_spending import seed

CHECKING = "popular:checking:123456789"
OFFICIAL = popular_account.parse(samples.POPULAR_CUENTA_DOP)
WEB = popular_web.parse(samples.POPULAR_WEB)
WEB_LATER = popular_web.parse(samples.POPULAR_WEB_LATER)
WEB_REPRINT = popular_web.parse(samples.POPULAR_WEB_REPRINT)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)  # cards and a savings account at another bank
    yield connection
    connection.close()


def checking(conn: sqlite3.Connection) -> list[spending.Movement]:
    return [m for m in spending.load_all(conn) if m.account == CHECKING]


def days(movements: list[spending.Movement]) -> list[tuple[str, str]]:
    return [(m.day.isoformat(), f"{m.amount:.2f}") for m in movements]


class TestStorage:
    def test_period_start_is_stored(self, conn) -> None:
        store(conn, WEB)
        store(conn, OFFICIAL)
        rows = conn.execute(
            "SELECT parser, period_start, period_end FROM statements "
            "WHERE parser IN ('popular_web', 'popular_account') ORDER BY id"
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("popular_web", "2026-01-12", "2026-01-20"),
            ("popular_account", "2025-12-16", "2026-01-15"),
        ]

    def test_printout_lands_on_the_official_account(self, conn) -> None:
        store(conn, OFFICIAL)
        store(conn, WEB)
        keys = [r[0] for r in conn.execute("SELECT key FROM accounts WHERE kind = 'checking'")]
        assert keys == [CHECKING]

    def test_old_database_gets_the_column_and_new_indexes(self, tmp_path: Path) -> None:
        path = tmp_path / "old.db"
        with closing(db.connect(path)) as old:
            old.executescript(
                "DROP INDEX statements_unique_printout; DROP INDEX statements_unique_period;"
                "ALTER TABLE statements DROP COLUMN period_start;"
                "CREATE UNIQUE INDEX statements_unique_period ON statements "
                "(account_id, COALESCE(card_id, 0), currency, period_end);"
                "ALTER TABLE statements DROP COLUMN transaction_count;"
            )
        with closing(db.connect(path)) as conn:
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(statements)")}
            assert {"period_start", "transaction_count"} <= columns
            ending_together = popular_web.parse(
                samples.popular_web(
                    (
                        (
                            "15/01/2026",
                            "15/01/2026",
                            None,
                            None,
                            ("DEPOSITO",),
                            "$1.00",
                            "$1.00",
                        ),
                    ),
                )
            )
            store(conn, OFFICIAL)
            store(conn, ending_together)  # does not clash with the statement ending that day
            assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 2


def test_v6_database_gets_the_currency_table(tmp_path: Path) -> None:
    path = tmp_path / "v6.db"
    with closing(db.connect(path)) as old:
        old.execute("DROP TABLE account_currency")
        old.execute("PRAGMA user_version = 6")
        old.commit()
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert db.account_currency(conn, SAVINGS) is None
        add_document(conn, "savings.pdf")
        assert process_documents(conn, "x", reader, printout_currency="USD") == {"parsed": 1}
        assert db.account_currency(conn, SAVINGS) == "USD"


def test_printout_index_without_content_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "intermediate.db"
    with closing(db.connect(path)) as old:
        old.executescript(
            "DROP INDEX statements_unique_printout;"
            "ALTER TABLE statements DROP COLUMN transaction_count;"
            "CREATE UNIQUE INDEX statements_unique_printout ON statements "
            "(account_id, currency, COALESCE(period_start, ''), period_end) "
            "WHERE parser = 'popular_web';"
        )
    with closing(db.connect(path)) as conn:
        index = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'statements_unique_printout'"
        ).fetchone()[0]
        assert "transaction_count" in index
        store(conn, WEB)
        store(conn, WEB_REPRINT)  # same range, different content
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 2


SAVINGS_HEADER = "Cuenta de Ahorro / 987654321"  # spanish-data
SAVINGS = "popular:savings:987654321"

PAGES: dict[str, tuple[Page, ...]] = {
    "reprint.pdf": samples.POPULAR_WEB_REPRINT,
    "statement.pdf": samples.POPULAR_CUENTA_DOP,
    "printout.pdf": samples.POPULAR_WEB,
    "printout_other.pdf": samples.POPULAR_WEB,
    "broken.pdf": samples.POPULAR_WEB_BROKEN_CHAIN,
    "overdraft.pdf": samples.POPULAR_WEB_OVERDRAFT,
    "savings.pdf": samples.popular_web(samples.WEB_ROWS, account=SAVINGS_HEADER),
    "savings_later.pdf": samples.popular_web(samples.WEB_ROWS_LATER, account=SAVINGS_HEADER),
}


def reader(path: Path, password: str) -> tuple[Page, ...]:
    return PAGES[path.name]


class TestIngest:
    def test_printout_and_statement_with_the_same_cut_are_both_kept(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "statement.pdf")
            add_document(conn, "printout.pdf")
            assert process_documents(conn, "x", reader) == {"parsed": 2}

    def test_same_printout_range_twice_is_duplicate(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "printout.pdf")
            add_document(conn, "printout_other.pdf")
            assert process_documents(conn, "x", reader) == {"parsed": 1, "duplicate": 1}

    def test_reprint_with_the_same_range_and_a_late_posting_is_kept(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "printout.pdf")
            add_document(conn, "reprint.pdf")
            assert process_documents(conn, "x", reader) == {"parsed": 2}
            jan_20 = [m for m in checking(conn) if m.day == date(2026, 1, 20)]
            assert [f"{m.amount:.2f}" for m in jan_20] == ["-500.00", "50.00"]

    def test_broken_chain_is_invalid(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "broken.pdf")
            assert process_documents(conn, "x", reader) == {"invalid": 1}
            detail = conn.execute("SELECT detail FROM documents").fetchone()[0]
            assert "fila 3" in detail  # spanish-ui

    def test_overdraft_printout_is_parsed(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "overdraft.pdf")
            assert process_documents(conn, "x", reader) == {"parsed": 1}
            closing_cents = conn.execute("SELECT closing_balance_cents FROM statements").fetchone()
            assert closing_cents[0] == 1360


def currencies(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return [
        (row[0], row[1])
        for row in conn.execute(
            "SELECT d.filename, s.currency FROM statements s "
            "JOIN documents d ON d.id = s.document_id ORDER BY s.id"
        )
    ]


class TestPrintoutCurrency:
    def test_without_a_choice_bare_dollar_is_dop(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            assert process_documents(conn, "x", reader) == {"parsed": 1}
            assert currencies(conn) == [("savings.pdf", "DOP")]
            assert db.account_currency(conn, SAVINGS) is None

    def test_chosen_currency_is_stored_and_reused(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            assert process_documents(conn, "x", reader, printout_currency="USD") == {"parsed": 1}
            assert db.account_currency(conn, SAVINGS) == "USD"
            add_document(conn, "savings_later.pdf", "2026-01-24T12:00:00+00:00")
            assert process_documents(conn, "x", reader) == {"parsed": 1}  # no choice given
            assert currencies(conn) == [("savings.pdf", "USD"), ("savings_later.pdf", "USD")]
            rows = conn.execute("SELECT DISTINCT currency FROM transactions").fetchall()
            assert [tuple(row) for row in rows] == [("USD",)]

    def test_the_choice_belongs_to_one_account(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            process_documents(conn, "x", reader, printout_currency="USD")
            add_document(conn, "printout.pdf", "2026-01-24T12:00:00+00:00")
            assert process_documents(conn, "x", reader) == {"parsed": 1}
            assert currencies(conn) == [("savings.pdf", "USD"), ("printout.pdf", "DOP")]

    def test_the_flag_overrides_and_updates_the_choice(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            process_documents(conn, "x", reader, printout_currency="USD")
            add_document(conn, "savings_later.pdf", "2026-01-24T12:00:00+00:00")
            assert process_documents(conn, "x", reader, printout_currency="DOP") == {"parsed": 1}
            assert currencies(conn) == [("savings.pdf", "USD"), ("savings_later.pdf", "DOP")]
            assert db.account_currency(conn, SAVINGS) == "DOP"

    def test_retry_reuses_the_stored_choice(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            process_documents(conn, "x", reader, printout_currency="USD")
            document_id = add_document(conn, "savings_later.pdf", "2026-01-24T12:00:00+00:00")
            with conn:
                conn.execute("UPDATE documents SET status = 'error' WHERE id = ?", (document_id,))
            assert process_documents(conn, "x", reader, retry=True) == {"parsed": 1}
            assert currencies(conn)[-1] == ("savings_later.pdf", "USD")

    def test_same_printout_in_the_same_currency_is_duplicate(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            process_documents(conn, "x", reader, printout_currency="USD")
            pages = PAGES["savings.pdf"]
            add_document(conn, "savings_copy.pdf")
            outcome = process_documents(
                conn, "x", lambda path, password: pages, printout_currency=None
            )
            assert outcome == {"duplicate": 1}
            assert db.account_currency(conn, SAVINGS) == "USD"

    def test_a_flagged_duplicate_still_updates_the_choice(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            process_documents(conn, "x", reader, printout_currency="USD")
            add_document(conn, "savings_later.pdf", "2026-01-24T12:00:00+00:00")
            process_documents(conn, "x", reader, printout_currency="DOP")
            pages = PAGES["savings.pdf"]
            add_document(conn, "savings_copy.pdf", "2026-01-25T12:00:00+00:00")
            outcome = process_documents(
                conn, "x", lambda path, password: pages, printout_currency="USD"
            )
            assert outcome == {"duplicate": 1}
            assert db.account_currency(conn, SAVINGS) == "USD"

    def test_the_flag_reads_a_printout_that_mixes_bare_and_explicit_dollars(self) -> None:
        rows = list(samples.WEB_ROWS)
        rows[0] = (*rows[0][:5], "US$10,000.00", "US$64,998.50")
        pages = samples.popular_web(tuple(rows), account=SAVINGS_HEADER)
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "mixed.pdf")
            outcome = process_documents(
                conn, "x", lambda path, password: pages, printout_currency="USD"
            )
            assert outcome == {"parsed": 1}
            assert currencies(conn) == [("mixed.pdf", "USD")]
            assert db.account_currency(conn, SAVINGS) == "USD"

    def test_without_the_flag_a_mixed_printout_is_an_error(self) -> None:
        rows = list(samples.WEB_ROWS)
        rows[0] = (*rows[0][:5], "US$10,000.00", "US$64,998.50")
        pages = samples.popular_web(tuple(rows), account=SAVINGS_HEADER)
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "mixed.pdf")
            assert process_documents(conn, "x", lambda path, password: pages) == {"error": 1}

    def test_no_choice_is_saved_when_the_chain_is_broken(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "broken.pdf")
            assert process_documents(conn, "x", reader, printout_currency="USD") == {"invalid": 1}
            assert db.account_currency(conn, CHECKING) is None

    def test_usd_printout_reaches_the_summary_converted_with_the_rate(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            process_documents(conn, "x", reader, printout_currency="USD")
            with conn:
                rates.set_manual(conn, "2026-01", Decimal("60"))
            built = summary.build_summary(
                spending.load_all(conn),
                accounts.account_infos(conn),
                rates.load(conn),
                "2026-01",
            )
            assert built.usd == Decimal("2.25")  # the tax, the printout's only expense
            assert built.usd_in_dop == Decimal("135")
            assert built.total == Decimal("135")
            assert built.income == Decimal("12500") * 60

    def test_reimporting_the_range_with_the_flag_replaces_a_wrong_currency(self) -> None:
        pages = PAGES["savings.pdf"]
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            process_documents(conn, "x", reader)  # not given: it was stored as DOP
            add_document(conn, "savings_again.pdf", "2026-01-24T12:00:00+00:00")
            outcome = process_documents(
                conn, "x", lambda path, password: pages, printout_currency="USD"
            )
            assert outcome == {"parsed": 1}
            kept = {m.currency for m in spending.load_all(conn) if m.account == SAVINGS}
            assert kept == {"USD"}

    def test_the_choice_does_not_touch_official_statements(self) -> None:
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "statement.pdf")
            assert process_documents(conn, "x", reader, printout_currency="USD") == {"parsed": 1}
            assert currencies(conn) == [("statement.pdf", "DOP")]
            assert db.account_currency(conn, CHECKING) is None

    def test_a_contradicting_symbol_is_an_error_and_keeps_the_choice(self) -> None:
        rows = tuple(
            (*r[:5], r[5].replace("$", "RD$"), r[6].replace("$", "RD$")) for r in samples.WEB_ROWS
        )
        pages = samples.popular_web(rows, account=SAVINGS_HEADER)
        with closing(db.connect(":memory:")) as conn:
            add_document(conn, "savings.pdf")
            process_documents(conn, "x", reader, printout_currency="USD")
            add_document(conn, "savings_rd.pdf", "2026-01-24T12:00:00+00:00")
            assert process_documents(conn, "x", lambda path, password: pages) == {"error": 1}
            assert db.account_currency(conn, SAVINGS) == "USD"


class TestOverlap:
    def test_official_statement_wins_on_its_days(self, conn) -> None:
        store(conn, OFFICIAL)
        before = checking(conn)
        store(conn, WEB)
        after = checking(conn)
        assert after[: len(before)] == before  # same fingerprints and categories
        assert days(after[len(before) :]) == [
            ("2026-01-16", "1500.00"),
            ("2026-01-17", "-2000.00"),
            ("2026-01-19", "2.25"),
            ("2026-01-20", "-500.00"),
        ]

    def test_official_wins_even_when_imported_later(self, conn) -> None:
        store(conn, WEB)
        store(conn, OFFICIAL)
        same = [m for m in checking(conn) if "000000003" in m.description]
        assert [(m.day, m.description) for m in same] == [
            (date(2026, 1, 11), "MB desde 000000003 FULANO DE")  # the statement row  # spanish-data
        ]

    def test_printout_alone_counts_every_row(self, conn) -> None:
        store(conn, WEB)
        assert len(checking(conn)) == 5

    def test_newest_printout_wins_on_shared_days(self, conn) -> None:
        store(conn, WEB)
        store(conn, WEB_LATER)
        assert days(checking(conn)) == [
            ("2026-01-12", "-10000.00"),  # only the first one covers that day
            ("2026-01-16", "1500.00"),
            ("2026-01-17", "-2000.00"),
            ("2026-01-19", "2.25"),
            ("2026-01-20", "-500.00"),
            ("2026-01-20", "50.00"),  # the newer one has one more movement that day
            ("2026-01-22", "1000.00"),
        ]

    def test_longer_printout_wins_even_when_imported_first(self, conn) -> None:
        store(conn, WEB_LATER)
        store(conn, WEB)  # older: it ends earlier, even though imported later
        assert days(checking(conn)) == [
            ("2026-01-12", "-10000.00"),
            ("2026-01-16", "1500.00"),
            ("2026-01-17", "-2000.00"),
            ("2026-01-19", "2.25"),
            ("2026-01-20", "-500.00"),
            ("2026-01-20", "50.00"),
            ("2026-01-22", "1000.00"),
        ]

    def test_official_without_period_start_covers_from_its_first_posting(self, conn) -> None:
        first, *rest = OFFICIAL.sections[0].transactions
        early = replace(first, transacted_on=date(2025, 12, 18))  # posted on the 20th
        section = replace(OFFICIAL.sections[0], transactions=(early, *rest))
        store(conn, replace(OFFICIAL, period_start=None, sections=(section,)))
        row = ("19/12/2025", "19/12/2025", None, None, ("DEPOSITO",), "$1.00", "$1.00")
        store(conn, popular_web.parse(samples.popular_web((row,))))
        assert date(2025, 12, 19) in [m.day for m in checking(conn)]

    def test_same_movement_keeps_its_fingerprint_across_printouts(self, conn) -> None:
        store(conn, WEB)
        first = {m.day: m.fingerprint for m in checking(conn)}
        store(conn, WEB_LATER)
        later = {m.day: m.fingerprint for m in checking(conn)}
        assert later[date(2026, 1, 17)] == first[date(2026, 1, 17)]

    def test_cards_and_other_banks_are_untouched(self, conn) -> None:
        before = [m for m in spending.load_all(conn) if m.account != CHECKING]
        store(conn, OFFICIAL)
        store(conn, WEB)
        store(conn, WEB_LATER)
        after = [m for m in spending.load_all(conn) if m.account != CHECKING]
        assert after == before

    def test_interest_is_counted_once(self, conn) -> None:
        row = ("12/01/2026", "12/01/2026", None, None, ("CARGO INTERESES",), "$5.00-", "$5.00-")
        store(conn, OFFICIAL)
        store(conn, popular_web.parse(samples.popular_web((row,))))
        year = interest_year(conn, {}, 2026, date(2026, 2, 1))
        assert [line.key for line in year.lines if line.key == CHECKING] == []


class TestAccounts:
    def test_printout_extends_coverage(self, conn) -> None:
        store(conn, OFFICIAL)
        store(conn, WEB)
        info = next(i for i in accounts.account_infos(conn) if i.key == CHECKING)
        assert info.through == date(2026, 1, 20)

    def test_accounts_view_labels_printouts_and_keeps_statements_apart(self, conn) -> None:
        store(conn, OFFICIAL)
        store(conn, WEB)
        view = next(
            v for v in accounts_view.account_views(conn, date(2026, 1, 25)) if v.key == CHECKING
        )
        assert [
            (line.printout, line.period_start, line.period_end) for line in view.statements
        ] == [
            (True, date(2026, 1, 12), date(2026, 1, 20)),
            (False, date(2025, 12, 16), date(2026, 1, 15)),  # stored start
        ]
        assert [line.printout for line in view.latest] == [False]
        assert view.cut_day == 15
        assert StatementLineOut.of(view.statements[0]).printout is True

    def test_report_counts_only_statements(self, conn) -> None:
        store(conn, OFFICIAL)
        store(conn, WEB)
        lines, _ = report._coverage(conn, date(2026, 1, 25), date(2026, 1, 1), 60)
        checking_line = next(line for line in lines if "123456789" in line)
        assert "1 closings" in checking_line


BANRESERVAS = "banreservas:savings:0000000000"
BR_FULL = banreservas_account.parse(samples.BANRESERVAS)
BR_PARTIAL = banreservas_account.parse(samples.BANRESERVAS_PARTIAL)


def banreservas_rows(conn: sqlite3.Connection) -> list[spending.Movement]:
    return [m for m in spending.load_all(conn) if m.account == BANRESERVAS]


class TestBanreservasPartial:
    """The current Banreservas month is a printout; the complete month is a statement."""

    def test_is_a_printout(self) -> None:
        assert BR_PARTIAL.parser in db.PRINTOUT_PARSERS
        assert BR_FULL.parser not in db.PRINTOUT_PARSERS
        assert db.PRINTOUT_PARSER in db.PRINTOUT_PARSERS  # Popular stays the same

    def test_partial_alone_counts(self, conn) -> None:
        store(conn, BR_PARTIAL)
        assert len(banreservas_rows(conn)) == len(BR_PARTIAL.sections[0].transactions)

    def test_full_month_is_kept_and_wins(self, conn) -> None:
        store(conn, BR_PARTIAL)
        store(conn, BR_FULL)  # same month: does not clash with the printout
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM statements WHERE parser LIKE 'banreservas%'"
            ).fetchone()[0]
            == 2
        )
        moved = banreservas_rows(conn)
        assert len(moved) == len(BR_FULL.sections[0].transactions)  # each row once
        partial_id = conn.execute(
            "SELECT id FROM statements WHERE parser = 'banreservas_partial'"
        ).fetchone()[0]
        covered = coverage.bank_coverage(conn)
        assert not any(
            covered.keeps(partial_id, t.transacted_on) for t in BR_PARTIAL.sections[0].transactions
        )

    def test_later_partial_wins_over_the_earlier_one(self, conn) -> None:
        later = banreservas_account.parse(
            samples.banreservas(samples.BANRESERVAS_ROWS, report="31/01/2026", balance="1,408.59")
        )
        store(conn, BR_PARTIAL)
        store(conn, later)
        assert len(banreservas_rows(conn)) == len(samples.BANRESERVAS_ROWS)

    def test_same_partial_twice_is_duplicate(self, conn) -> None:
        store(conn, BR_PARTIAL)
        with pytest.raises(sqlite3.IntegrityError):
            store(conn, BR_PARTIAL)

    def test_accounts_view_labels_the_partial_as_printout(self, conn) -> None:
        store(conn, BR_PARTIAL)
        store(conn, BR_FULL)
        view = next(
            v for v in accounts_view.account_views(conn, date(2026, 2, 5)) if v.key == BANRESERVAS
        )
        assert [(line.printout, line.period_end) for line in view.statements] == [
            (False, date(2026, 1, 31)),
            (True, date(2026, 1, 27)),
        ]
        assert [line.printout for line in view.latest] == [False]
        assert StatementLineOut.of(view.statements[1]).printout is True

    def test_report_counts_only_the_full_month(self, conn) -> None:
        store(conn, BR_PARTIAL)
        lines, _ = report._coverage(conn, date(2026, 2, 5), date(2026, 1, 1), 60)
        assert not any("0000000000" in line for line in lines)
        store(conn, BR_FULL)
        lines, _ = report._coverage(conn, date(2026, 2, 5), date(2026, 1, 1), 60)
        assert "1 closings" in next(line for line in lines if "0000000000" in line)


def test_old_indexes_learn_the_new_printout_parser(tmp_path: Path) -> None:
    path = tmp_path / "before_banreservas.db"
    with closing(db.connect(path)) as old:
        old.executescript(
            "DROP INDEX statements_unique_printout; DROP INDEX statements_unique_period;"
            "CREATE UNIQUE INDEX statements_unique_period ON statements "
            "(account_id, COALESCE(card_id, 0), currency, period_end) "
            "WHERE parser <> 'popular_web';"
            "CREATE UNIQUE INDEX statements_unique_printout ON statements ("
            "account_id, currency, COALESCE(period_start, ''), period_end, "
            "COALESCE(closing_balance_cents, 0), COALESCE(printed_debits_cents, 0), "
            "COALESCE(printed_credits_cents, 0), COALESCE(transaction_count, 0)) "
            "WHERE parser = 'popular_web';"
        )
    for _ in range(2):  # idempotent
        with closing(db.connect(path)) as conn:
            for name in (db.DUPLICATE_PERIOD_INDEX, db.DUPLICATE_PRINTOUT_INDEX):
                sql = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
                ).fetchone()[0]
                assert "banreservas_partial" in sql
    with closing(db.connect(path)) as conn:
        ending_together = banreservas_account.parse(
            samples.banreservas(samples.BANRESERVAS_ROWS, report="31/01/2026", balance="1,408.59")
        )
        store(conn, ending_together)
        store(conn, BR_FULL)  # same cut as the printout: not a duplicate
        assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 2
