"""Schema 18 (stored values in English): a database written by the previous release migrates
without losing a movement, a correction, a link or a log entry, and every old entry can still be
undone as before.

`fixtures/schema_v17.sql` is that database, made with the previous release's code through its
board API (synthetic data from tests/samples.py and tests/e2e_server.py), with change-log
entries of every kind. `fixtures/schema_v17_expected.json` is what that release read from it
(every movement and the undo state of every entry), written in the new vocabulary by an
independent translation.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from michelito import db, legacy
from michelito.analysis import (
    accounts,
    categories,
    changelog,
    links,
    providers,
    reserve_store,
    spending,
)
from tests import e2e_server as e2e
from tests.helpers import shown_name

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "schema_v17_expected.json").read_text(encoding="utf-8"))

_OLD_VALUES = frozenset().union(
    *(
        m.keys()
        for m in (
            legacy.CATEGORY_KINDS,
            legacy.REVIEW_KINDS,
            legacy.CADENCES,
            legacy.RECURRING_GROUPS,
            legacy.LOG_AUTHORS,
            legacy.LOG_TARGET_TYPES,
            legacy.LOG_KINDS,
            legacy.DOCUMENT_SOURCES,
            legacy.MESSAGE_SENDERS,
            legacy.PARSER_NAMES,
        )
    )
)
_OLD_RECURRING_PREFIX, _OLD_PEAK_PREFIX = legacy.RESERVE_KEY_PREFIXES
_OLD_KEY = re.compile(
    "|".join(
        (
            re.escape(legacy.CASH_FINGERPRINT_PREFIX) + r"\d",
            re.escape(legacy.CASH_BOX_KEY),
            re.escape(legacy.PROVIDER_PREFIX),
            re.escape(_OLD_RECURRING_PREFIX),
            "^" + re.escape(_OLD_PEAK_PREFIX),
        )
    )
)
# The Gmail source the fixture's owner named (a user-chosen name, not a translated value).
GMAIL_SOURCE = "banco"  # spanish-data
# Text written for people (Spanish display text and statement data), not stored identifiers.
_DISPLAY = {
    "change_log": {"subject", "before_text", "after_text", "reason"},
    "transactions": {"description", "raw_line"},
    "categories": {"name"},
    "category_keywords": {"keyword"},
    "insights": {"text"},
    "gmail_messages": {"subject"},
    "documents": {"filename", "path", "detail"},
    "links": {"name", "with_whom", "for_whom"},
    "link_manual": {"person", "place"},
    "transaction_notes": {"note"},
    "reserve_dismissals": set(),
}


@pytest.fixture(autouse=True)
def _demo_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixture's recurring series use the e2e server's made-up providers."""
    known = {p.key for p in providers.PROVIDERS}
    extra = tuple(p for p in e2e.DEMO_PROVIDERS if p.key not in known)
    monkeypatch.setattr(providers, "PROVIDERS", (*providers.PROVIDERS, *extra))


def _v17(path: Path) -> Path:
    with closing(sqlite3.connect(path)) as raw:
        raw.executescript((FIXTURES / "schema_v17.sql").read_text(encoding="utf-8"))
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 17
    return path


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    return [str(r[0]) for r in rows]


def _rows(conn: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def _strings(value: Any) -> Iterator[str]:
    """Every string inside a JSON value (dict keys are column names, not stored values)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _stored_strings(conn: sqlite3.Connection) -> Iterator[tuple[str, str, str]]:
    """(table, column, value) of every stored identifier, also inside the log's JSON and row
    keys."""
    for table in _tables(conn):
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        for row in conn.execute(f"SELECT * FROM {table}"):
            for column, value in zip(columns, row, strict=True):
                if not isinstance(value, str) or column in _DISPLAY.get(table, set()):
                    continue
                if (table, column) == ("change_log", "changes"):
                    for item in _strings(json.loads(value)):
                        yield table, column, item
                elif (table, column) == ("change_log_rows", "row_key"):
                    for item in _strings(json.loads(value.split(":", 1)[1])):
                        yield table, column, item
                else:
                    yield table, column, value


def test_every_stored_value_is_translated(tmp_path: Path) -> None:
    path = _v17(tmp_path / "v17.db")
    with closing(sqlite3.connect(path)) as raw:
        old = [(t, c, v) for t, c, v in _stored_strings(raw) if v in _OLD_VALUES]
        assert {t for t, _, _ in old} >= {"categories", "review_marks", "change_log", "statements"}
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 18
        left = [
            (t, c, v) for t, c, v in _stored_strings(conn) if v in _OLD_VALUES or _OLD_KEY.search(v)
        ]
        assert left == []
        for table in ("categories", "review_marks", "recurring_marks", "change_log"):
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
            assert not set(re.findall(r"'([^']*)'", sql[0])) & _OLD_VALUES, table

        def column(sql: str) -> set[Any]:
            return {r[0] for r in conn.execute(sql)}

        assert column("SELECT kind FROM categories") == {"income", "expense", "transfer"}
        assert column("SELECT kind FROM review_marks") == {
            "duplicate", "large_third_party", "unusual_income", "price_up",
            "possible_contribution", "possible_return", "possible_reserve",
        }  # fmt: skip
        assert {
            tuple(r)
            for r in conn.execute("SELECT merchant, cadence, group_key FROM recurring_marks")
        } == {  # fmt: skip
            ("SEGURO HOGAR", "yearly", "insurance"),
            ("provider:telfic", None, "subscriptions"),
            ("MARBETE FICTICIO", "yearly", None),
        }
        assert column("SELECT target FROM recurring_unions") == {"provider:acueducto-ficticio"}
        assert column("SELECT author FROM change_log") == {"user", "claude"}
        assert column("SELECT kind FROM change_log") == set(legacy.LOG_KINDS.values())
        assert column("SELECT target_type FROM change_log") == set(legacy.LOG_TARGET_TYPES.values())
        assert column("SELECT target FROM change_log WHERE kind = 'recurring'") == {
            "SEGURO HOGAR · DOP",
            "provider:telfic · DOP",
        }
        assert "budget" in column("SELECT target FROM change_log WHERE kind = 'budget'")
        # A dismissed suggestion's subject repeats its key: translated like the target.
        dismissed = conn.execute(
            "SELECT subject, target FROM change_log WHERE kind = 'reserve_dismissal'"
        ).fetchall()
        assert {subject for subject, _ in dismissed} >= {
            "peak:ENTERTAINMENT:12",
            "recurring:provider:acueducto-ficticio:DOP",
        }
        assert all(subject == target for subject, target in dismissed)
        assert column("SELECT key FROM reserve_dismissals") == {
            "peak:ENTERTAINMENT:12",
            "recurring:provider:acueducto-ficticio:DOP",
            "irregular:Mascotas ficticias",
        }
        assert column("SELECT source FROM links WHERE source IS NOT NULL") == {
            "recurring:SEGURO HOGAR:DOP",
            "recurring:provider:telfic:DOP",
        }
        box = accounts.CASH_BOX_KEY
        assert box == "manual:cash-box"
        for sql in (
            "SELECT key FROM accounts",
            "SELECT account_key FROM cash_entries",
            "SELECT account_key FROM links",
            "SELECT account_key FROM account_currency",
        ):
            assert box in column(sql), sql
        assert column("SELECT accounts FROM insights") == {f"{box},popular:savings:FIC-3"}
        for sql in (
            "SELECT fingerprint FROM transaction_notes",
            "SELECT fingerprint FROM review_marks",
            "SELECT fingerprint FROM reviewed_fingerprints",
            "SELECT fingerprint FROM change_log_fingerprints",
            "SELECT target FROM change_log",
        ):
            assert "cash-2" in column(sql), sql
        assert 'transaction_notes:["cash-2"]' in column("SELECT row_key FROM change_log_rows")
        assert column("SELECT source FROM gmail_messages") == {
            GMAIL_SOURCE,
            "imported",
            "generated",
        }
        senders = conn.execute(
            "SELECT DISTINCT sender FROM gmail_messages WHERE source != ?", (GMAIL_SOURCE,)
        )
        assert {r[0] for r in senders} == {"manual import"}
        # Existing ids and stored paths are not renamed (only new rows get the new prefixes).
        assert column("SELECT message_id FROM documents WHERE source = 'imported'") == {
            f"{legacy.IMPORT_SOURCE}-{i:032x}" for i in range(6)
        }
        assert column("SELECT parser FROM statements") == {
            *legacy.PARSER_NAMES.values(),
            "popular_web",
            "demo",
        }
        assert column("SELECT parser FROM documents WHERE parser IS NOT NULL") == {
            "banreservas_account", "banreservas_partial", "bhd_savings_partial",
            "popular_account", "popular_history", "popular_web",
        }  # fmt: skip


def test_movements_corrections_and_links_read_the_same(tmp_path: Path) -> None:
    path = _v17(tmp_path / "v17.db")
    with closing(sqlite3.connect(path)) as raw:
        untouched = ("transactions", "merchant_categories", "category_keywords",
                     "budget_caps", "exchange_rates", "cards", "document_parts")  # fmt: skip
        before = {t: _rows(raw, t) for t in untouched}
        sequence = _rows(raw, "sqlite_sequence")
    with closing(db.connect(path)) as conn:
        assert {t: _rows(conn, t) for t in untouched} == before
        # Schema 19 adds the ledger's sequences; the old ones stay as they were.
        assert set(sequence) <= set(_rows(conn, "sqlite_sequence"))
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        found = {
            m.fingerprint: [
                m.day.isoformat(),
                m.kind,
                str(m.amount),
                m.currency,
                m.category,
                m.category_key,
                m.one_off,
                m.note,
                m.link,
                m.account,
            ]
            for m in spending.load_all(conn, ())
        }
        # Schema 23 renamed the cash transfer category's stored name (its reference stays).
        expected = {
            fp: [*m[:4], shown_name(m[4]) if m[5] == categories.CASH_BOX else m[4], *m[5:]]
            for fp, m in EXPECTED["movements"].items()
        }
        assert found == expected
        loaded = links.load(conn)
        [box] = loaded.cash_boxes
        assert box.account_key == accounts.CASH_BOX_KEY
        assert len(reserve_store.load(conn)) == 2 and loaded.investments and loaded.exchanges


def _dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as raw:
        return list(raw.iterdump())


def test_the_migration_is_idempotent(tmp_path: Path) -> None:
    path = _v17(tmp_path / "v17.db")
    db.connect(path).close()
    first = _dump(path)
    with closing(db.connect(path)) as again:
        assert again.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert _dump(path) == first


def test_a_fresh_database_gets_the_english_schema(tmp_path: Path) -> None:
    with closing(db.connect(tmp_path / "new.db")) as conn:
        for table in ("categories", "review_marks", "recurring_marks", "change_log"):
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
            assert not set(re.findall(r"'([^']*)'", sql[0])) & _OLD_VALUES, table
        assert conn.execute("SELECT DISTINCT kind FROM categories").fetchall()


def test_old_entries_keep_their_undo_state(tmp_path: Path) -> None:
    path = _v17(tmp_path / "v17.db")
    with closing(db.connect(path)) as conn:
        done = changelog.undone(conn)
        found = {}
        for entry in changelog.load(conn):
            state = changelog.undo_state(conn, entry, done)
            found[str(entry.id)] = [state.allowed, state.undone, state.blocked_by]
        # Entry 10 created a shared group: schema 19 moved its rows to the ledger, so that old
        # entry can no longer put them back. Every other entry keeps its state.
        expected = {**EXPECTED["undo"], "10": [False, False, None]}
        assert found == expected


def _entry(conn: sqlite3.Connection, kind: str, target: str | None = None) -> changelog.Entry:
    return next(
        e
        for e in changelog.load(conn, kind=kind)
        if e.undoes is None and (target is None or e.target == target)
    )


def test_old_entries_of_every_kind_undo(tmp_path: Path) -> None:
    path = _v17(tmp_path / "v17.db")
    with closing(db.connect(path)) as conn:

        def undo(entry: changelog.Entry) -> None:
            assert changelog.undo_state(conn, entry).allowed, entry.kind
            with conn:
                made = changelog.undo(conn, entry.id)
            assert changelog.get(conn, made).kind == entry.kind

        def one(sql: str, *args: Any) -> Any:
            row = conn.execute(sql, args).fetchone()
            return None if row is None else tuple(row)

        # A review mark on the manual cash entry and the cash entry's latest note.
        undo(_entry(conn, "reviewed", "cash-2"))
        assert one("SELECT 1 FROM review_marks WHERE fingerprint = 'cash-2'") is None
        note = next(e for e in changelog.load(conn, kind="note") if e.target == "cash-2")
        undo(note)
        # The cash entry itself (it set the entry's category): row and category go away.
        undo(_entry(conn, "cash_entry"))
        assert one("SELECT 1 FROM cash_entries WHERE id = 2") is None
        assert one("SELECT 1 FROM transaction_notes WHERE fingerprint = 'cash-2'") is None
        # A recurring mark with cadence and group, and a union with a provider.
        undo(_entry(conn, "recurring", "SEGURO HOGAR · DOP"))
        assert one("SELECT 1 FROM recurring_marks WHERE merchant = 'SEGURO HOGAR'") is None
        undo(_entry(conn, "recurring_union"))
        assert one("SELECT 1 FROM recurring_unions") is None
        # A category kind change goes back to the (translated) old kind.
        changed = _entry(conn, "category_kind")
        assert one("SELECT kind FROM categories WHERE id = ?", int(changed.target)) == ("transfer",)
        undo(changed)
        assert one("SELECT kind FROM categories WHERE id = ?", int(changed.target)) == ("expense",)
        # A batch, a duplicate mark, a dismissed suggestion and Claude's exchange edit.
        batch = _entry(conn, "category_batch")
        undo(batch)
        assert {
            one(
                "SELECT category_id FROM transaction_notes WHERE fingerprint = ?",
                c.key["fingerprint"],
            )
            for c in batch.changes
        } == {None}
        undo(_entry(conn, "reviewed", next(iter(_duplicate(conn)))))
        assert _duplicate(conn) == set()
        undo(_entry(conn, "reserve_dismissal", "recurring:provider:acueducto-ficticio:DOP"))
        assert one("SELECT 1 FROM reserve_dismissals WHERE key LIKE 'recurring:%'") is None
        exchange = _entry(conn, "exchange")
        assert exchange.author == "claude"
        undo(exchange)


def _duplicate(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT fingerprint FROM review_marks WHERE kind = 'duplicate'")
    return {str(r[0]) for r in rows}


def test_a_failed_v18_migration_leaves_the_v17_database_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _v17(tmp_path / "v17.db")
    before = _dump(path)

    def broken(conn: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("broken on purpose")

    monkeypatch.setattr(db.migrations_v18, "translate", broken)
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    assert _dump(path) == before
