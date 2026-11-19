import sqlite3
from contextlib import closing
from datetime import date

import pytest

from michelito import db
from michelito.analysis import catalog, corrections
from michelito.analysis import categories as cat


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def test_fingerprint_is_stable_and_distinguishes_repeated_charges() -> None:
    args = ("popular:credit_card", date(2026, 1, 5), "CAFE FICTICIO", 15000, "debit", "DOP")
    first = corrections.fingerprint(*args, occurrence=0)
    assert first == corrections.fingerprint(*args, occurrence=0)
    assert first != corrections.fingerprint(*args, occurrence=1)  # the same coffee twice
    other_amount = ("popular:credit_card", date(2026, 1, 5), "CAFE FICTICIO", 15001)
    assert first != corrections.fingerprint(*other_amount, "debit", "DOP", occurrence=0)


def test_empty_corrections(conn) -> None:
    loaded = corrections.load(conn)
    assert loaded.merchants == {}
    assert loaded.transactions == {}
    assert loaded.category_for("abc", "AMAZON") is None
    assert not loaded.is_one_off("abc")


def test_transaction_category_wins_over_merchant(conn) -> None:
    with conn:
        corrections.set_merchant_category(conn, "LA SIRENA", cat.SHOPPING)
        corrections.set_transaction_category(conn, "fp1", cat.GROCERIES)
    loaded = corrections.load(conn)
    assert loaded.category_for("fp1", "LA SIRENA") == cat.GROCERIES
    assert loaded.category_for("fp2", "LA SIRENA") == cat.SHOPPING


def test_one_off_and_category_live_together(conn) -> None:
    with conn:
        corrections.set_one_off(conn, "fp1", True)
        corrections.set_transaction_category(conn, "fp1", cat.HEALTH)
    loaded = corrections.load(conn)
    assert loaded.is_one_off("fp1")
    assert loaded.category_for("fp1", "X") == cat.HEALTH
    with conn:
        corrections.set_one_off(conn, "fp1", False)
    loaded = corrections.load(conn)
    assert not loaded.is_one_off("fp1")
    assert loaded.category_for("fp1", "X") == cat.HEALTH


def test_clearing_removes_the_correction(conn) -> None:
    with conn:
        corrections.set_merchant_category(conn, "LA SIRENA", cat.SHOPPING)
        corrections.set_transaction_category(conn, "fp1", cat.GROCERIES)
        corrections.set_merchant_category(conn, "LA SIRENA", None)
        corrections.set_transaction_category(conn, "fp1", None)
    loaded = corrections.load(conn)
    assert loaded.merchants == {}
    assert loaded.transactions == {}  # no category and no flag: the row is not needed


def test_unknown_category_is_rejected(conn) -> None:
    with pytest.raises(ValueError, match="categoría desconocida"):  # spanish-ui
        corrections.set_merchant_category(conn, "X", "Inventada")  # spanish-data
    with pytest.raises(ValueError, match="categoría desconocida"):  # spanish-ui
        corrections.set_transaction_category(conn, "fp", "Inventada")  # spanish-data


def test_merchant_rule_only_for_accepted_kinds(conn) -> None:
    with conn:
        corrections.set_merchant_category(conn, "PAGO DE", cat.SALARY)
        corrections.set_transaction_category(conn, "fp1", cat.GROCERIES)
    loaded = corrections.load(conn)
    assert loaded.category_for("fp2", "PAGO DE", ("income", "transfer")) == cat.SALARY
    assert loaded.category_for("fp2", "PAGO DE", ("expense", "transfer")) is None
    assert loaded.category_for("fp2", "PAGO DE") == cat.SALARY  # no limit: cards
    # A transaction correction always wins, whatever its kind.
    assert loaded.category_for("fp1", "PAGO DE", ("income",)) == cat.GROCERIES


def _schema_7_db(path, merchants=(), notes=()) -> None:
    """A database with corrections as before schema 8: the category name."""
    with closing(sqlite3.connect(path)) as old:
        old.executescript(
            "CREATE TABLE merchant_categories (merchant TEXT PRIMARY KEY, "
            "category TEXT NOT NULL, updated_at TEXT NOT NULL);"
            "CREATE TABLE transaction_notes (fingerprint TEXT PRIMARY KEY, category TEXT, "
            "one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)), "
            "updated_at TEXT NOT NULL);"
        )
        old.executemany("INSERT INTO merchant_categories VALUES (?, ?, 'z')", merchants)
        old.executemany("INSERT INTO transaction_notes VALUES (?, ?, ?, 'z')", notes)
        old.commit()


def test_old_cash_name_is_read_as_the_new_one(tmp_path) -> None:
    # Corrections saved before the cash category was renamed (and before ids were stored): the
    # migration moves them to today's category.
    path = tmp_path / "old.db"
    _schema_7_db(
        path,
        merchants=[("CAJERO FICTICIO", "Efectivo y transferencias")],  # spanish-data
        notes=[("abc", "Efectivo y transferencias", 0)],  # spanish-data
    )
    with closing(db.connect(path)) as conn:
        loaded = corrections.load(conn)
    assert loaded.merchants == {"CAJERO FICTICIO": cat.CASH}
    assert loaded.category_for("abc", "OTHER") == cat.CASH


class TestMigrationToIds:
    def test_names_become_ids_and_a_second_connect_changes_nothing(self, tmp_path) -> None:
        path = tmp_path / "old.db"
        _schema_7_db(
            path,
            merchants=[("LA SIRENA", cat.SHOPPING), ("PAGO DE", cat.SALARY)],
            notes=[("fp1", cat.GROCERIES, 1), ("fp2", None, 1)],
        )
        with closing(db.connect(path)) as conn:
            first = corrections.load(conn)
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(merchant_categories)")}
            count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        assert "category" not in columns and "category_id" in columns
        with closing(db.connect(path)) as conn:  # idempotent
            assert corrections.load(conn) == first
            assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == count
        assert first.merchants == {"LA SIRENA": cat.SHOPPING, "PAGO DE": cat.SALARY}
        assert first.category_for("fp1", "X") == cat.GROCERIES
        assert first.is_one_off("fp1") and first.is_one_off("fp2")
        assert first.transaction_category("fp2") is None

    def test_an_unknown_old_name_is_kept_as_a_user_category(self, tmp_path) -> None:
        path = tmp_path / "old.db"
        _schema_7_db(path, merchants=[("TIENDA X", "Categoría perdida")])  # spanish-data
        with closing(db.connect(path)) as conn:
            loaded = corrections.load(conn)
            known = catalog.load(conn)
        made = known.by_name("Categoría perdida")  # spanish-data
        assert made is not None and not made.builtin and made.kind == "expense"
        assert loaded.merchants == {"TIENDA X": made.ref}

    def test_odd_old_names_never_stop_the_migration(self, tmp_path) -> None:
        long_a = "A category with an extremely long name, number one"
        long_b = "A category with an extremely long name, number two"
        assert long_a[: catalog.NAME_MAX] == long_b[: catalog.NAME_MAX]
        path = tmp_path / "old.db"
        _schema_7_db(
            path,
            merchants=[("A", long_a), ("B", long_b), ("C", "   "), ("D", long_a)],
            notes=[("fp1", long_b, 0)],
        )
        with closing(db.connect(path)) as conn:
            loaded = corrections.load(conn)
            known = catalog.load(conn)
        names = {key: known.by_ref(ref).name for key, ref in loaded.merchants.items()}
        assert names["C"] == "Sin nombre"  # spanish-ui
        assert names["A"] == long_a[: catalog.NAME_MAX]
        assert names["B"].endswith(" (2)") and len(names["B"]) <= catalog.NAME_MAX
        assert loaded.merchants["D"] == loaded.merchants["A"]  # the same name, a single one
        assert loaded.category_for("fp1", "X") == loaded.merchants["B"]

    def test_builtins_are_seeded_once(self, conn) -> None:
        keys = [r[0] for r in conn.execute("SELECT builtin_key FROM categories")]
        assert sorted(keys) == sorted(cat.BUILTIN_KEYS)


def test_legacy_merchant_key_is_a_fallback(conn) -> None:
    with conn:
        corrections.set_merchant_category(conn, "MB A", cat.HOUSING)
        corrections.set_merchant_category(conn, "MB A 0001", cat.SALARY)
    loaded = corrections.load(conn)
    assert loaded.category_for("fp", "MB A 0002", legacy="MB A") == cat.HOUSING
    assert loaded.category_for("fp", "MB A 0001", legacy="MB A") == cat.SALARY  # the new one wins
    # The limit by kind also applies to the previous key.
    assert loaded.category_for("fp", "MB A 0002", ("income",), legacy="MB A") is None


def test_several_fallback_keys_in_order(conn) -> None:
    corrections.set_merchant_category(conn, "OLD", cat.HOUSING)
    corrections.set_merchant_category(conn, "OLDER", cat.SALARY)
    loaded = corrections.load(conn)
    assert loaded.category_for("fp", "NEW", legacy=("OLD", "OLDER")) == cat.HOUSING
    assert loaded.category_for("fp", "NEW", legacy=("OTHER", "OLDER")) == cat.SALARY
    assert loaded.category_for("fp", "NEW", legacy=()) is None
