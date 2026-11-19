from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from finanzas import db
from finanzas.analysis import categories as cat
from finanzas.analysis import corrections, spending
from finanzas.analysis.accounts import AccountInfo
from finanzas.analysis.rates import Rate
from finanzas.web import transactions
from finanzas.web.transactions import Filters
from tests.test_spending import movement as _movement
from tests.test_spending import seed

# Las reglas guardan el id; su categoría, por nombre.
RULE_NAME = "SELECT c.name FROM merchant_categories m JOIN categories c ON c.id = m.category_id"
ACCOUNTS = [
    AccountInfo("A", "credit_card", "Tarjeta A", date(2026, 10, 31)),
    AccountInfo("B", "credit_card", "Tarjeta B", date(2026, 10, 31)),
]


def movement(
    day, amount="100", category=cat.GROCERIES, merchant="COLMADO", account="A", fp=None, **kw
):
    return replace(
        _movement(day, amount, category, merchant, **kw),
        account=account,
        fingerprint=fp or f"{day}-{merchant}-{amount}-{account}",
        original_category=category,
    )


def test_filters_by_month_account_category():
    moves = [
        movement("2026-10-02", "100"),
        movement("2026-10-03", "200", cat.RESTAURANTS, "CAFE", account="B"),
        movement("2026-09-30", "300"),
    ]
    month = Filters("2026-10")
    assert len(transactions.list_transactions(moves, ACCOUNTS, {}, month)) == 2
    by_account = transactions.list_transactions(
        moves, ACCOUNTS, {}, Filters("2026-10", account="B")
    )
    assert [(v.merchant, v.account_label) for v in by_account] == [("CAFE", "Tarjeta B")]
    by_category = transactions.list_transactions(
        moves, ACCOUNTS, {}, Filters("2026-10", category=cat.GROCERIES)
    )
    assert [v.amount for v in by_category] == [Decimal(100)]


def test_old_category_name_in_the_filter_lists_the_renamed_category():
    moves = [movement("2026-10-02", "100", cat.CASH, "CAJERO"), movement("2026-10-03", "200")]
    old = Filters("2026-10", category="Efectivo y transferencias")
    assert [v.merchant for v in transactions.list_transactions(moves, ACCOUNTS, {}, old)] == [
        "CAJERO"
    ]


def test_ordered_newest_first_keeping_load_order_within_a_day():
    moves = [
        movement("2026-10-02", "1", merchant="X"),
        movement("2026-10-05", "2", merchant="Y"),
        movement("2026-10-02", "3", merchant="Z"),
    ]
    views = transactions.list_transactions(moves, ACCOUNTS, {}, Filters("2026-10"))
    assert [v.merchant for v in views] == ["Y", "X", "Z"]


def test_search_ignores_case_and_accents():
    moves = [
        movement("2026-10-02", merchant="CAFÉ FICTICIO"),
        movement("2026-10-03", merchant="OTRO"),
    ]
    found = transactions.list_transactions(moves, ACCOUNTS, {}, Filters("2026-10", q="cafe"))
    assert [v.merchant for v in found] == ["CAFÉ FICTICIO"]
    assert transactions.list_transactions(moves, ACCOUNTS, {}, Filters("2026-10", q="%")) == []
    blank = transactions.list_transactions(moves, ACCOUNTS, {}, Filters("2026-10", q="  "))
    assert len(blank) == 2


def test_search_matches_description():
    move = replace(movement("2026-10-02"), description="Pago ÁRBOL")
    found = transactions.list_transactions([move], ACCOUNTS, {}, Filters("2026-10", q="arbol"))
    assert len(found) == 1


def test_merchant_year_count():
    moves = [
        movement("2026-01-05", fp="a"),
        movement("2026-10-05", fp="b", account="B"),
        movement("2026-10-06", "-50", fp="c"),  # devolución: no cuenta
        movement("2025-12-30", fp="d"),
        movement("2026-10-07", merchant="OTRO", fp="e"),
    ]
    views = transactions.list_transactions(moves, ACCOUNTS, {}, Filters("2026-10"))
    counts = {v.fingerprint: v.merchant_year_count for v in views}
    assert counts == {"b": 2, "c": 2, "e": 1}


def test_amount_dop_uses_the_transaction_month_rate():
    rates = {"2026-09": Rate(Decimal("60"), "2026-09", "manual")}
    moves = [movement("2026-10-02", "10", currency="USD"), movement("2026-10-03", "5")]
    views = transactions.list_transactions(moves, ACCOUNTS, rates, Filters("2026-10"))
    assert {v.currency: v.amount_dop for v in views} == {"USD": Decimal(600), "DOP": Decimal(5)}
    no_rate = transactions.list_transactions(moves, ACCOUNTS, {}, Filters("2026-10"))
    assert {v.currency: v.amount_dop for v in no_rate} == {"USD": None, "DOP": Decimal(5)}


def test_find_unknown_fingerprint_raises():
    with pytest.raises(LookupError):
        transactions.find([movement("2026-10-02")], "nope")


class TestEdit:
    @pytest.fixture
    def path(self, tmp_path):
        return tmp_path / "finanzas.db"

    @pytest.fixture
    def conn(self, path):
        connection = db.connect(path)
        seed(connection)
        yield connection
        connection.close()

    def _colmado(self, conn) -> spending.Movement:
        return next(m for m in spending.load_movements(conn) if m.merchant == "COLMADO INVENTADO")

    def test_edit_single_transaction(self, conn) -> None:
        colmado = self._colmado(conn)
        _edit(conn, colmado, cat.RESTAURANTS, True, "transaction")
        reloaded = self._colmado(conn)
        assert (reloaded.category, reloaded.one_off) == (cat.RESTAURANTS, True)
        assert conn.execute("SELECT COUNT(*) FROM merchant_categories").fetchone()[0] == 0

    def test_the_edit_is_saved_by_the_callers_transaction(self, conn, path) -> None:
        """`apply_edit` no hace commit: lo guarda el `with conn:` de quien llama."""
        _edit(conn, self._colmado(conn), cat.RESTAURANTS, None, "transaction", "con Ana")
        with closing(db.connect(path)) as other:
            row = other.execute("SELECT note FROM transaction_notes").fetchone()
            colmado = next(
                m for m in spending.load_movements(other) if m.merchant == "COLMADO INVENTADO"
            )
        assert (row[0], colmado.category) == ("con Ana", cat.RESTAURANTS)

    def test_edit_whole_merchant_replaces_single(self, conn) -> None:
        _edit(conn, self._colmado(conn), cat.RESTAURANTS, None, "transaction")
        _edit(conn, self._colmado(conn), cat.HOME, None, "merchant")
        assert self._colmado(conn).category == cat.HOME
        rule = conn.execute(RULE_NAME).fetchone()[0]
        assert rule == cat.HOME
        assert conn.execute("SELECT COUNT(*) FROM transaction_notes").fetchone()[0] == 0

    def test_edit_only_one_off_keeps_category(self, conn) -> None:
        colmado = self._colmado(conn)
        _edit(conn, colmado, None, True, "transaction")
        reloaded = self._colmado(conn)
        assert (reloaded.category, reloaded.one_off) == (colmado.category, True)
        assert not reloaded.corrected
        _edit(conn, reloaded, None, False, "merchant")
        assert not self._colmado(conn).one_off

    def test_unknown_category_or_scope_rejected_without_writes(self, conn) -> None:
        colmado = self._colmado(conn)
        with pytest.raises(ValueError, match="categoría"):
            _edit(conn, colmado, "Inventada", True, "transaction")
        with pytest.raises(ValueError, match="alcance"):
            _edit(conn, colmado, cat.HOME, None, "todo")
        assert conn.execute("SELECT COUNT(*) FROM transaction_notes").fetchone()[0] == 0

    def test_merchant_scope_with_same_individual_category_sets_rule(self, conn) -> None:  # A
        colmado = self._colmado(conn)
        _edit(conn, colmado, cat.RESTAURANTS, None, "transaction")
        _edit(conn, self._colmado(conn), cat.RESTAURANTS, None, "merchant")
        rule = conn.execute(RULE_NAME).fetchone()[0]
        assert rule == cat.RESTAURANTS
        assert conn.execute("SELECT COUNT(*) FROM transaction_notes").fetchone()[0] == 0

    def test_merchant_scope_with_current_category_sets_rule(self, conn) -> None:  # B
        colmado = self._colmado(conn)
        _edit(conn, colmado, colmado.category, None, "merchant")
        rule = conn.execute(RULE_NAME).fetchone()[0]
        assert rule == colmado.category

    def test_transaction_scope_with_current_category_pins_it(self, conn) -> None:  # C
        colmado = self._colmado(conn)
        _edit(conn, colmado, colmado.category, None, "transaction")
        with conn:
            corrections.set_merchant_category(conn, colmado.merchant, cat.HOME)
        assert self._colmado(conn).category == colmado.category  # la nota gana sobre la regla


def _edit(conn, movement, category, one_off, scope, note=None) -> None:
    """Corrige como el board: dentro de la transacción de quien llama."""
    with conn:
        transactions.apply_edit(conn, movement, category, one_off, scope, note)


def test_filter_by_kind_and_kind_in_view():
    moves = [
        movement("2026-10-02", "100"),
        movement("2026-10-03", "-5000", cat.SALARY, "EMPRESA"),
        movement("2026-10-04", "700", cat.CARD_PAYMENT, "PAGO TC"),
    ]
    everything = transactions.list_transactions(moves, ACCOUNTS, {}, Filters("2026-10"))
    assert sorted(v.kind for v in everything) == ["gasto", "ingreso", "transferencia"]
    income = transactions.list_transactions(moves, ACCOUNTS, {}, Filters("2026-10", kind="ingreso"))
    assert [(v.merchant, v.kind) for v in income] == [("EMPRESA", "ingreso")]


class TestKindChange:
    def test_correction_moves_movement_between_kinds(self) -> None:
        conn = db.connect(":memory:")
        seed(conn)
        colmado = next(m for m in spending.load_all(conn) if m.merchant == "COLMADO INVENTADO")
        _edit(conn, colmado, cat.OTHER_INCOME, None, "transaction")
        views = transactions.list_transactions(
            spending.load_all(conn), [], {}, Filters(colmado.month, kind="ingreso")
        )
        assert colmado.fingerprint in {v.fingerprint for v in views}
        assert colmado.fingerprint not in {m.fingerprint for m in spending.load_movements(conn)}
        conn.close()


def test_bank_merchant_year_count_is_per_counterpart():
    conn = db.connect(":memory:")
    seed(conn)
    from tests.test_spending import _add_bank_rows

    _add_bank_rows(
        conn,
        [
            ("2026-01-05", "MB a 0123456789 JUAN PEREZ", "debit", "70000"),
            ("2026-01-20", "MB a 0123456789 JUAN PER", "debit", "70000"),
            ("2026-01-21", "MB a 0999999999 MARIA GOMEZ", "debit", "70000"),
        ],
    )
    # Cuentan como gasto solo si el usuario lo dice: los dos al mismo dueño son el alquiler.
    landlord = next(m for m in spending.load_all(conn) if m.merchant == "MB A 0123456789")
    corrections.set_merchant_category(conn, landlord.merchant, cat.HOUSING)
    corrections.set_merchant_category(conn, "MB A 0999999999", cat.HOUSING)
    views = transactions.list_transactions(
        spending.load_all(conn), [], {}, Filters(month="2026-01", q="MB a")
    )
    counts = {v.description: (v.merchant, v.merchant_year_count) for v in views}
    assert counts == {
        "MB a 0123456789 JUAN PEREZ": ("MB A 0123456789", 2),
        "MB a 0123456789 JUAN PER": ("MB A 0123456789", 2),
        "MB a 0999999999 MARIA GOMEZ": ("MB A 0999999999", 1),
    }
    conn.close()
