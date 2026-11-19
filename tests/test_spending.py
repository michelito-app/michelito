from collections import Counter
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from michelito import db
from michelito.analysis import categories as cat
from michelito.analysis import corrections, spending
from michelito.analysis.spending import Movement
from michelito.parsers import bhd_card, bhd_savings, popular_card
from michelito.parsers.common import CREDIT
from tests import samples


def movement(
    day: str,
    amount: str,
    category: str = cat.GROCERIES,
    merchant: str = "COLMADO INVENTADO",
    currency: str = "DOP",
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=merchant,
        description=merchant,
        category=category,
        amount=Decimal(amount),
        currency=currency,
        institution="popular",
    )


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)
    yield connection
    connection.close()


def seed(connection) -> None:
    """Store the synthetic card (Popular and BHD) and savings statements."""
    for index, statement in enumerate(
        (
            popular_card.parse(samples.POPULAR_PAGES),
            bhd_card.parse(samples.BHD_TC_PAGES),
            bhd_savings.parse(samples.BHD_AHORRO_PAGES),
        )
    ):
        with connection:
            connection.execute(
                "INSERT INTO gmail_messages VALUES (?, 'bank', 'x', 'y', 'z', 1, 'z')",
                (f"m{index}",),
            )
            document_id = connection.execute(
                "INSERT INTO documents (message_id, source, filename, path, sha256, size, "
                "received_at, status) VALUES (?, 'bank', 'f.pdf', 'p', 's', 1, 'z', 'parsed')",
                (f"m{index}",),
            ).lastrowid
            db.store_statement(connection, document_id, statement)


def test_movements_carry_account_and_original_category(conn) -> None:
    keys = {row[0] for row in conn.execute("SELECT key FROM accounts")}
    loaded = spending.load_movements(conn)
    assert loaded and all(m.account in keys for m in loaded)
    colmado = next(m for m in loaded if m.description.startswith("COLMADO INVENTADO"))

    corrections.set_transaction_category(conn, colmado.fingerprint, cat.RESTAURANTS)

    fixed = next(m for m in spending.load_movements(conn) if m.fingerprint == colmado.fingerprint)
    assert (fixed.category, fixed.original_category) == (cat.RESTAURANTS, cat.GROCERIES)


class TestLoad:
    def test_card_expenses_exclude_card_payments_and_bank_credits(self, conn) -> None:
        loaded = spending.load_movements(conn)
        cards = [m for m in loaded if m.account.endswith(":credit_card")]
        assert not any("PAGO" in m.description for m in cards)  # payments to the card
        assert len(cards) == 6
        assert not any("TRANSFERENCIA" in m.description for m in loaded)  # bank credit

    def test_categories_and_learned_merchants(self, conn) -> None:
        by_description = {m.description: m for m in spending.load_movements(conn)}
        colmado = by_description["COLMADO INVENTADO SANTO DOMINGO"]
        assert (colmado.category, colmado.amount, colmado.currency) == (
            cat.GROCERIES,
            Decimal("1200.50"),
            "DOP",
        )
        # BHD prints no MCC; the category is learned from the same merchant at Popular.
        bhd_store = by_description["TIENDA ONLINE SEATTLE-US"]
        assert (bhd_store.institution, bhd_store.category) == ("bhd", cat.BOOKS)
        assert bhd_store.merchant == "TIENDA ONLINE"

    def test_complete_through_is_the_earliest_latest_cut(self, conn) -> None:
        # Popular cuts on 13/01/2026 and BHD on 26/01/2026: January is only complete
        # through the 13th for both cards.
        assert spending.complete_through(conn) == date(2026, 1, 13)

    def test_complete_through_without_cards(self) -> None:
        assert spending.complete_through(db.connect(":memory:")) is None


def _old_fingerprints(conn) -> list[tuple[str, str]]:
    """Fingerprints as load_movements computed them before payments were included."""
    seen: Counter = Counter()
    found = []
    for row in conn.execute(spending._CARD_TRANSACTIONS):
        if row["direction"] == CREDIT and cat.is_payment(row["description"]):
            continue
        identity = tuple(row[key] for key in spending._IDENTITY)
        mark = corrections.fingerprint(
            row["account"],
            date.fromisoformat(row["transacted_on"]),
            row["description"],
            row["amount_cents"],
            row["direction"],
            row["currency"],
            seen[identity],
        )
        seen[identity] += 1
        found.append((row["description"], mark))
    return found


def test_payments_become_card_payment_transfers(conn) -> None:
    payments = [
        m
        for m in spending.load_all(conn)
        if m.kind == "transfer" and m.account.endswith(":credit_card")
    ]
    assert payments
    assert all(m.category == cat.CARD_PAYMENT and m.amount < 0 for m in payments)
    assert all("PAGO" in m.description.upper() for m in payments)


def test_load_movements_unchanged_for_cards(conn) -> None:
    loaded = [m for m in spending.load_movements(conn) if m.account.endswith(":credit_card")]
    assert len(loaded) == 6
    assert [(m.description, m.fingerprint) for m in loaded] == _old_fingerprints(conn)
    assert all(m.kind == "expense" for m in loaded)
    everything = spending.load_movements(conn)
    assert everything == tuple(m for m in spending.load_all(conn) if m.kind == "expense")


def _bank_rows(conn) -> dict[str, Movement]:
    return {
        m.description: m for m in spending.load_all(conn) if not m.account.endswith(":credit_card")
    }


def test_bank_credit_is_other_income(conn) -> None:
    deposit = _bank_rows(conn)["TRANSFERENCIA RECIBIDA"]
    assert (deposit.kind, deposit.category) == ("income", cat.OTHER_INCOME)
    assert (deposit.institution, deposit.currency, deposit.amount) == (
        "bhd",
        "DOP",
        Decimal("-5000.00"),
    )
    assert ":savings:" in deposit.account
    assert deposit.original_category == cat.OTHER_INCOME


def test_bank_debit_is_an_expense_and_enters_load_movements(conn) -> None:
    # Used to be "COMPRA INVENTADA XYZ": a debit with no rule is now a third-party transfer.
    _add_bank_rows(conn, [("2026-01-12", "RETIRO CAJERO INVENTADO XYZ", "debit", "300000")])
    debit = _bank_rows(conn)["RETIRO CAJERO INVENTADO XYZ"]
    assert (debit.kind, debit.amount) == ("expense", Decimal("3000.00"))
    assert debit.fingerprint in {m.fingerprint for m in spending.load_movements(conn)}
    interest = _bank_rows(conn)["PAGO INTERESES CA"]
    assert interest.kind == "income"


def _add_bank_rows(conn, rows: list[tuple[str, str, str, str]]) -> None:
    """Add made-up transactions to the synthetic savings account: (day, text, dir, cents)."""
    statement_id, currency = conn.execute(
        "SELECT s.id, s.currency FROM statements s JOIN accounts a ON a.id = s.account_id "
        "WHERE a.kind = 'savings'"
    ).fetchone()
    top = conn.execute(
        "SELECT MAX(sequence) FROM transactions WHERE statement_id = ?", (statement_id,)
    ).fetchone()[0]
    with conn:
        for offset, (day, text, direction, cents) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO transactions (statement_id, sequence, transacted_on, description, "
                "amount_cents, direction, currency, raw_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (statement_id, top + offset, day, text, int(cents), direction, currency, text),
            )


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("RETIRO CAJERO AUTOMATICO INVENTADO", cat.CASH),
        ("CONSUMO ATM INVENTADO", cat.CASH),
        ("COMISION MANTENIMIENTO", cat.BANK_FEES),
        ("CARGO POR SERVICIO", cat.BANK_FEES),
        ("IMPUESTO LEY 288-04", cat.GOVERNMENT),
        ("RETENCION INTERESES", cat.GOVERNMENT),
        ("IMPUESTOS VARIOS", cat.GOVERNMENT),
        ("RETENCIONES DEL MES", cat.GOVERNMENT),
        ("RETENIDO ISR", cat.GOVERNMENT),
        # Used to be "Other" (expense): a debit with no rule is a third-party transfer.
        ("DEPOSITOS INVENTADOS XYZ", cat.THIRD_PARTY),
        ("AUT PAGO 0000000009 INVENTADO", cat.LOANS),
    ],
)
def test_bank_debit_rules(conn, text: str, category: str) -> None:
    _add_bank_rows(conn, [("2026-01-20", text, "debit", "10000")])
    found = _bank_rows(conn)[text]
    assert (found.category, found.kind) == (category, cat.kind_of(category))


def test_bank_credit_is_income_whatever_the_text(conn) -> None:
    _add_bank_rows(conn, [("2026-01-21", "RETIRO ANULADO", "credit", "10000")])
    assert _bank_rows(conn)["RETIRO ANULADO"].category == cat.OTHER_INCOME


def test_bank_correction_wins(conn) -> None:
    deposit = _bank_rows(conn)["TRANSFERENCIA RECIBIDA"]
    corrections.set_transaction_category(conn, deposit.fingerprint, cat.SALARY)
    fixed = _bank_rows(conn)[deposit.description]
    assert (fixed.category, fixed.kind, fixed.corrected) == (cat.SALARY, "income", True)
    assert fixed.original_category == cat.OTHER_INCOME


def test_identical_bank_rows_get_distinct_fingerprints(conn) -> None:
    _add_bank_rows(conn, [("2026-01-22", "RETIRO CAJERO", "debit", "5000")] * 2)
    marks = [m.fingerprint for m in spending.load_all(conn) if m.description == "RETIRO CAJERO"]
    assert len(marks) == 2 and len(set(marks)) == 2


def test_correcting_to_income_removes_from_spending(conn) -> None:
    target = spending.load_movements(conn)[0]
    corrections.set_transaction_category(conn, target.fingerprint, cat.OTHER_INCOME)
    assert target.fingerprint not in {m.fingerprint for m in spending.load_movements(conn)}
    fixed = next(m for m in spending.load_all(conn) if m.fingerprint == target.fingerprint)
    assert (fixed.category, fixed.kind) == (cat.OTHER_INCOME, "income")


class TestCorrections:
    def test_every_movement_has_a_distinct_fingerprint(self, conn) -> None:
        loaded = spending.load_movements(conn)
        assert len({m.fingerprint for m in loaded}) == len(loaded)
        assert all(not m.one_off and not m.corrected for m in loaded)

    def test_fingerprint_survives_reprocessing(self, conn) -> None:
        before = {m.description: m.fingerprint for m in spending.load_movements(conn)}
        with conn:
            for table in ("transactions", "statements", "documents", "gmail_messages"):
                conn.execute(f"DELETE FROM {table}")
        seed(conn)  # same statements, new rows and ids
        after = {m.description: m.fingerprint for m in spending.load_movements(conn)}
        assert after == before

    def test_merchant_and_transaction_corrections_apply(self, conn) -> None:
        colmado = next(
            m for m in spending.load_movements(conn) if m.merchant == "COLMADO INVENTADO"
        )
        with conn:
            corrections.set_merchant_category(conn, "TIENDA ONLINE", cat.ONLINE)
            corrections.set_transaction_category(conn, colmado.fingerprint, cat.RESTAURANTS)
            corrections.set_one_off(conn, colmado.fingerprint, True)
        by_merchant = {m.merchant: m for m in spending.load_movements(conn)}
        assert by_merchant["TIENDA ONLINE"].category == cat.ONLINE
        assert by_merchant["TIENDA ONLINE"].corrected
        fixed = by_merchant["COLMADO INVENTADO"]
        assert (fixed.category, fixed.one_off, fixed.corrected) == (cat.RESTAURANTS, True, True)


def test_one_offs_stay_out_of_the_baseline_average() -> None:
    surgery = replace(movement("2025-11-20", "900.00", cat.HEALTH), one_off=True)
    changes = spending.compare_month(
        (*MOVEMENTS, surgery), "DOP", "2025-12", ("2025-10", "2025-11")
    )
    # Without the mark, Health would show an average of 450 (900 over 2 months).
    assert cat.HEALTH not in {c.category for c in changes}


def test_refund_credits_are_negative(conn) -> None:
    connection = conn
    with connection:
        connection.execute(
            "UPDATE transactions SET description = '66666666666666666666666 DEVOLUCION' "
            "WHERE description = 'PAGO DEBITO A CUENTA MBP' AND currency = 'USD'"
        )
    refund = next(m for m in spending.load_movements(connection) if "DEVOLUCION" in m.description)
    assert refund.amount == Decimal("-10.00")


@pytest.mark.parametrize(
    ("through", "month"),
    [
        (date(2026, 1, 13), "2025-12"),
        (date(2026, 1, 31), "2026-01"),
        (date(2026, 3, 1), "2026-02"),
    ],
)
def test_last_full_month(through: date, month: str) -> None:
    assert spending.last_full_month(through) == month


def test_months_back_crosses_years() -> None:
    assert spending.months_back("2026-02", 4) == ("2025-11", "2025-12", "2026-01", "2026-02")


MOVEMENTS = (
    movement("2025-11-03", "100.00"),
    movement("2025-12-05", "300.00"),
    movement("2025-12-06", "50.00", cat.RESTAURANTS, "CAFE FICTICIO"),
    movement("2025-12-07", "-20.00", cat.RESTAURANTS, "CAFE FICTICIO"),
    movement("2025-12-08", "40.00", cat.BOOKS, "TIENDA ONLINE", currency="USD"),
    movement("2026-01-02", "999.00"),  # outside the requested range
)
MONTHS = ("2025-10", "2025-11", "2025-12")


def test_monthly_totals_fill_empty_months_and_net_refunds() -> None:
    assert spending.monthly_totals(MOVEMENTS, "DOP", MONTHS) == {
        "2025-10": Decimal(0),
        "2025-11": Decimal("100.00"),
        "2025-12": Decimal("330.00"),
    }


def test_by_category_sorted_by_total() -> None:
    assert spending.by_category(MOVEMENTS, "DOP", MONTHS) == [
        (cat.GROCERIES, Decimal("400.00")),
        (cat.RESTAURANTS, Decimal("30.00")),
    ]
    assert spending.by_category(MOVEMENTS, "USD", MONTHS) == [(cat.BOOKS, Decimal("40.00"))]


def test_monthly_by_category_fills_every_month() -> None:
    assert spending.monthly_by_category(MOVEMENTS, "DOP", MONTHS) == {
        cat.GROCERIES: {
            "2025-10": Decimal(0),
            "2025-11": Decimal("100.00"),
            "2025-12": Decimal("300.00"),
        },
        cat.RESTAURANTS: {
            "2025-10": Decimal(0),
            "2025-11": Decimal(0),
            "2025-12": Decimal("30.00"),
        },
    }


def test_top_merchants_counts_only_purchases() -> None:
    top = spending.top_merchants(MOVEMENTS, "DOP", MONTHS, limit=1)
    assert top == [spending.MerchantTotal("COLMADO INVENTADO", Decimal("400.00"), 2)]
    cafe = spending.top_merchants(MOVEMENTS, "DOP", MONTHS, limit=5)[1]
    assert (cafe.total, cafe.purchases) == (Decimal("30.00"), 1)


def test_compare_month_against_average_of_previous_months() -> None:
    changes = spending.compare_month(MOVEMENTS, "DOP", "2025-12", ("2025-10", "2025-11"))
    assert changes[0] == spending.CategoryChange(cat.GROCERIES, Decimal("300.00"), Decimal("50.00"))
    assert changes[1] == spending.CategoryChange(cat.RESTAURANTS, Decimal("30.00"), Decimal("0"))


def test_first_full_month_is_the_latest_first_cut(conn) -> None:
    # Each sample statement is its card's first; both cut in January 2026,
    # so December is incomplete and January is the first fully covered month.
    assert spending.first_full_month(conn) == "2026-01"


def test_first_full_month_without_cards() -> None:
    assert spending.first_full_month(db.connect(":memory:")) is None


class TestMerchantRulesOnBankRows:
    """A merchant rule applies to a bank transaction only if its kind fits."""

    def test_income_rule_does_not_turn_debits_into_income(self, conn) -> None:
        _add_bank_rows(
            conn,
            [
                ("2026-01-15", "PAGO DE NOMINA EMPRESA FICTICIA", "credit", "5000000"),
                ("2026-01-16", "PAGO DE PRESTAMO INVENTADO", "debit", "800000"),
            ],
        )
        payroll = _bank_rows(conn)["PAGO DE NOMINA EMPRESA FICTICIA"]
        # Both rows used to share the key "PAGO DE"; now each has its own, but a rule saved
        # under the old key still applies (with the same per-kind limit).
        assert payroll.merchant != _bank_rows(conn)["PAGO DE PRESTAMO INVENTADO"].merchant
        corrections.set_merchant_category(conn, "PAGO DE", cat.SALARY)
        rows = _bank_rows(conn)
        assert (rows[payroll.description].category, rows[payroll.description].corrected) == (
            cat.SALARY,
            True,
        )
        loan = rows["PAGO DE PRESTAMO INVENTADO"]
        # Used to be "Other": a debit saying PRESTAMO is now Loans (still an expense).
        assert (loan.kind, loan.category, loan.corrected) == ("expense", cat.LOANS, False)

    def test_expense_rule_does_not_move_deposits(self, conn) -> None:
        deposit = _bank_rows(conn)["TRANSFERENCIA RECIBIDA"]
        corrections.set_merchant_category(conn, deposit.merchant, cat.GROCERIES)
        fixed = _bank_rows(conn)["TRANSFERENCIA RECIBIDA"]
        assert (fixed.kind, fixed.category, fixed.corrected) == ("income", cat.OTHER_INCOME, False)

    def test_transfer_rule_applies_both_ways(self, conn) -> None:
        _add_bank_rows(
            conn,
            [
                ("2026-01-15", "MB A INVENTADO UNO", "debit", "100000"),
                ("2026-01-16", "MB A INVENTADO DOS", "credit", "100000"),
            ],
        )
        corrections.set_merchant_category(conn, "MB A", cat.OWN_TRANSFER)
        rows = _bank_rows(conn)
        assert rows["MB A INVENTADO UNO"].category == cat.OWN_TRANSFER
        assert rows["MB A INVENTADO DOS"].category == cat.OWN_TRANSFER

    def test_transaction_correction_still_wins(self, conn) -> None:
        deposit = _bank_rows(conn)["TRANSFERENCIA RECIBIDA"]
        corrections.set_transaction_category(conn, deposit.fingerprint, cat.GROCERIES)
        fixed = _bank_rows(conn)["TRANSFERENCIA RECIBIDA"]
        assert (fixed.kind, fixed.category, fixed.corrected) == ("expense", cat.GROCERIES, True)

    def test_card_refunds_keep_following_merchant_rules(self, conn) -> None:
        with conn:
            conn.execute(
                "UPDATE transactions SET description = 'DEV TIENDA ONLINE' "
                "WHERE description = 'PAGO DEBITO A CUENTA MBP' AND currency = 'USD'"
            )
        corrections.set_merchant_category(conn, "TIENDA ONLINE", cat.ONLINE)
        refund = next(m for m in spending.load_all(conn) if m.description == "DEV TIENDA ONLINE")
        assert (refund.category, refund.amount, refund.corrected) == (
            cat.ONLINE,
            Decimal("-10.00"),
            True,
        )


def test_bank_tax_anywhere_in_the_text(conn) -> None:
    text = "PAGO IMPUESTO 0.15% DGII, 1 TRANS POR $ 1,000.00"
    _add_bank_rows(conn, [("2026-01-20", text, "debit", "150")])
    assert _bank_rows(conn)[text].category == cat.GOVERNMENT


def test_load_movements_uses_holders(conn) -> None:
    # Used to be "ENVIO A ...": a transfer with no rule is no longer an expense; a loan payment is.
    _add_bank_rows(conn, [("2026-01-12", "AUT PAGO MARIA PEREZ INVENTADA", "debit", "70000")])
    texts = {m.description for m in spending.load_movements(conn)}
    assert "AUT PAGO MARIA PEREZ INVENTADA" in texts
    held = {m.description for m in spending.load_movements(conn, ("MARIA PEREZ INVENTADA",))}
    assert "AUT PAGO MARIA PEREZ INVENTADA" not in held


class TestPromotionCredits:
    """A promotion credit on the card is income, not a refund."""

    PROMO = "CR PROMOCION CASHBACK INVENTADA"

    def _rename_usd_credit(self, conn, text: str) -> None:
        with conn:
            conn.execute(
                "UPDATE transactions SET description = ? "
                "WHERE description IN ('PAGO DEBITO A CUENTA MBP', 'DEV TIENDA ONLINE') "
                "AND currency = 'USD'",
                (text,),
            )

    def _card_spending(self, conn) -> dict[tuple[str, str], Decimal]:
        totals: Counter[tuple[str, str]] = Counter()
        for m in spending.load_movements(conn):
            if m.account.endswith(":credit_card"):
                totals[(m.month, m.currency)] += m.amount
        return dict(totals)

    def test_promotion_credit_is_other_income(self, conn) -> None:
        self._rename_usd_credit(conn, self.PROMO)
        promo = next(m for m in spending.load_all(conn) if m.description == self.PROMO)
        assert (promo.category, promo.kind, promo.amount) == (
            cat.OTHER_INCOME,
            "income",
            Decimal("-10.00"),
        )
        assert promo.original_category == cat.OTHER_INCOME

    def test_merchant_refund_stays_a_negative_expense(self, conn) -> None:
        self._rename_usd_credit(conn, "DEV TIENDA ONLINE")
        refund = next(m for m in spending.load_all(conn) if m.description == "DEV TIENDA ONLINE")
        assert (refund.kind, refund.amount) == ("expense", Decimal("-10.00"))

    def test_correction_wins_over_the_promotion_rule(self, conn) -> None:
        self._rename_usd_credit(conn, self.PROMO)
        promo = next(m for m in spending.load_all(conn) if m.description == self.PROMO)
        corrections.set_transaction_category(conn, promo.fingerprint, cat.SHOPPING)
        fixed = next(m for m in spending.load_all(conn) if m.description == self.PROMO)
        assert (fixed.category, fixed.kind, fixed.corrected) == (cat.SHOPPING, "expense", True)

    def test_only_the_promotion_changes_card_spending(self, conn) -> None:
        self._rename_usd_credit(conn, "DEV TIENDA ONLINE")
        before = self._card_spending(conn)
        self._rename_usd_credit(conn, self.PROMO)
        after = self._card_spending(conn)
        promo = next(m for m in spending.load_all(conn) if m.description == self.PROMO)
        key = (promo.month, promo.currency)
        assert after[key] == before[key] + Decimal("10.00")  # no longer subtracted as a refund
        assert {k: v for k, v in after.items() if k != key} == {
            k: v for k, v in before.items() if k != key
        }

    def test_card_payments_stay_card_payments(self, conn) -> None:
        payments = [m for m in spending.load_all(conn) if m.category == cat.CARD_PAYMENT]
        assert payments and all(m.kind == "transfer" for m in payments)


class TestBankRulesInLoadAll:
    def test_insurer_reimbursement_reduces_health_like_a_refund(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-18", "REEMBOLSO MAPFRE INVENTADO", "credit", "250000")])
        refund = _bank_rows(conn)["REEMBOLSO MAPFRE INVENTADO"]
        assert (refund.category, refund.kind, refund.amount) == (
            cat.HEALTH,
            "expense",
            Decimal("-2500.00"),
        )
        assert refund.fingerprint in {m.fingerprint for m in spending.load_movements(conn)}

    def test_payroll_credit_is_salary(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-15", "PAGO DE NOMINAS EMPRESA FICTICIA", "credit", "9")])
        payroll = _bank_rows(conn)["PAGO DE NOMINAS EMPRESA FICTICIA"]
        assert (payroll.category, payroll.kind) == (cat.SALARY, "income")

    def test_third_party_debit_is_not_spending(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-15", "MB A 0000000001 PERSONA INVENTADA", "debit", "9")])
        sent = _bank_rows(conn)["MB A 0000000001 PERSONA INVENTADA"]
        assert (sent.category, sent.kind) == (cat.THIRD_PARTY, "transfer")
        assert sent.fingerprint not in {m.fingerprint for m in spending.load_movements(conn)}

    def test_correction_wins_over_third_party(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-15", "MB A 0000000001 PERSONA INVENTADA", "debit", "9")])
        sent = _bank_rows(conn)["MB A 0000000001 PERSONA INVENTADA"]
        corrections.set_transaction_category(conn, sent.fingerprint, cat.GROCERIES)
        fixed = _bank_rows(conn)[sent.description]
        assert (fixed.category, fixed.kind, fixed.corrected) == (cat.GROCERIES, "expense", True)
        assert fixed.original_category == cat.THIRD_PARTY

    def test_card_payment_and_own_account_still_win_over_the_rules(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-15", "MB A MARIA PEREZ INVENTADA", "debit", "9")])
        rows = {
            m.description: m
            for m in spending.load_all(conn, ("MARIA PEREZ INVENTADA",))
            if not m.account.endswith(":credit_card")
        }
        assert rows["MB A MARIA PEREZ INVENTADA"].category == cat.OWN_TRANSFER
        assert rows["PAGO DE TC 5100 XXXX XXXX 9999"].category == cat.CARD_PAYMENT


class TestCardRowsUntouched:
    """RF2: the bank rules change nothing in the card rows."""

    @staticmethod
    def _cards(conn) -> list[tuple[object, ...]]:
        return [
            (m.fingerprint, m.category, m.original_category, m.amount, m.kind, m.merchant)
            for m in spending.load_all(conn)
            if m.account.endswith(":credit_card")
        ]

    def test_bank_rows_of_every_rule_leave_card_rows_identical(self, conn) -> None:
        before = self._cards(conn)
        _add_bank_rows(
            conn,
            [
                ("2026-01-20", "MB A 0000000001 PERSONA INVENTADA", "debit", "100000"),
                ("2026-01-20", "AUT PAGO 0000000009 INVENTADO", "debit", "100000"),
                ("2026-01-20", "COMISION MANEJO INVENTADA", "debit", "100000"),
                ("2026-01-20", "BANCASEGURO INVENTADO", "debit", "100000"),
                ("2026-01-20", "RETIRO CAJERO INVENTADO", "debit", "100000"),
                ("2026-01-20", "REEMBOLSO MAPFRE INVENTADO", "credit", "100000"),
                ("2026-01-20", "PAGO DE NOMINAS EMPRESA FICTICIA", "credit", "100000"),
            ],
        )
        assert before and self._cards(conn) == before

    def test_card_categories_still_come_from_the_card_rules(self, conn) -> None:
        rows = conn.execute(
            "SELECT t.description, t.mcc, t.direction FROM transactions t "
            "JOIN statements s ON s.id = t.statement_id JOIN accounts a ON a.id = s.account_id "
            "WHERE a.kind = 'credit_card'"
        ).fetchall()
        learned = cat.learn_merchants(
            (r["description"], r["mcc"])
            for r in rows
            if not (r["direction"] == "credit" and cat.is_payment(r["description"]))
        )
        purchases = {
            m.description: m
            for m in spending.load_all(conn)
            if m.account.endswith(":credit_card") and m.amount > 0
        }
        for row in rows:
            if row["direction"] == "debit":
                expected = cat.categorize(row["description"], row["mcc"], learned)
                assert purchases[row["description"]].original_category == expected


class TestBankMerchants:
    """Bank transactions are grouped by counterpart (`categories.bank_merchant_key`)."""

    def test_bank_rows_use_the_counterpart_key_and_cards_do_not_change(self, conn) -> None:
        _add_bank_rows(
            conn,
            [
                ("2026-01-12", "MB a 0123456789 JUAN PEREZ", "debit", "70000"),
                ("2026-01-13", "MB a 0999999999 MARIA GOMEZ", "debit", "20000"),
            ],
        )
        rows = _bank_rows(conn)
        assert rows["MB a 0123456789 JUAN PEREZ"].merchant == "MB A 0123456789"
        assert rows["MB a 0999999999 MARIA GOMEZ"].merchant == "MB A 0999999999"
        cards = [m for m in spending.load_all(conn) if m.account.endswith(":credit_card")]
        assert cards and all(m.merchant == cat.merchant_key(m.description) for m in cards)

    def test_merchant_rule_hits_only_that_counterpart(self, conn) -> None:
        _add_bank_rows(
            conn,
            [
                ("2026-01-12", "MB a 0123456789 JUAN PEREZ", "debit", "70000"),
                ("2026-01-13", "MB a 0999999999 MARIA GOMEZ", "debit", "20000"),
            ],
        )
        landlord = _bank_rows(conn)["MB a 0123456789 JUAN PEREZ"]
        corrections.set_merchant_category(conn, landlord.merchant, cat.HOUSING)
        rows = _bank_rows(conn)
        assert rows["MB a 0123456789 JUAN PEREZ"].category == cat.HOUSING
        assert rows["MB a 0999999999 MARIA GOMEZ"].category == cat.THIRD_PARTY

    def test_merchant_rule_keeps_the_direction_limit(self, conn) -> None:
        _add_bank_rows(
            conn,
            [
                ("2026-01-12", "LBTR 1234567890 JUAN PEREZ", "debit", "70000"),
                ("2026-01-14", "LBTR 1234567890 JUAN PEREZ", "credit", "10000"),
            ],
        )
        corrections.set_merchant_category(conn, "LBTR JUAN PEREZ", cat.SALARY)
        found = [m for m in spending.load_all(conn) if m.merchant == "LBTR JUAN PEREZ"]
        by_sign = {m.amount > 0: m.category for m in found}
        assert by_sign == {True: cat.THIRD_PARTY, False: cat.SALARY}

    def test_old_generic_key_rule_still_resolves(self, conn) -> None:
        # A rule saved under the previous key ("RETIRO CAJERO") still applies while
        # nobody has saved one under the new key.
        _add_bank_rows(conn, [("2026-01-12", "RETIRO CAJERO INVENTADO XYZ", "debit", "300")])
        corrections.set_merchant_category(conn, "RETIRO CAJERO", cat.HOUSING)
        found = _bank_rows(conn)["RETIRO CAJERO INVENTADO XYZ"]
        assert found.merchant == "RETIRO CAJERO INVENTADO"
        assert (found.category, found.corrected) == (cat.HOUSING, True)
        corrections.set_merchant_category(conn, found.merchant, cat.CASH)
        assert _bank_rows(conn)["RETIRO CAJERO INVENTADO XYZ"].category == cat.CASH

    def test_fingerprints_use_the_raw_description(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-12", "MB a 0123456789 JUAN PEREZ", "debit", "70000")])
        found = _bank_rows(conn)["MB a 0123456789 JUAN PEREZ"]
        assert found.fingerprint == corrections.fingerprint(
            found.account,
            found.day,
            "MB a 0123456789 JUAN PEREZ",
            70000,
            "debit",
            found.currency,
            0,
        )


class TestPreviousBankKey:
    """A rule saved under the bank key from before the Banreservas channels."""

    def test_rule_under_the_previous_key_still_applies(self, conn) -> None:
        text = "TRANSFERENCIA DE UNIVERSAL DE FICTICIOS SRL"
        _add_bank_rows(conn, [("2026-01-12", text, "credit", "50000")])
        corrections.set_merchant_category(conn, "TRANSFERENCIA UNIVERSAL FICTICIOS", cat.SALARY)
        found = _bank_rows(conn)[text]
        assert found.merchant == "TRANSFERENCIA DE UNIVERSAL FICTICIOS"
        assert (found.category, found.corrected) == (cat.SALARY, True)
        corrections.set_merchant_category(conn, found.merchant, cat.SERVICE_PAYMENTS)
        assert _bank_rows(conn)[text].category == cat.SERVICE_PAYMENTS  # the new one wins

    def test_previous_key_rule_keeps_the_direction_limit(self, conn) -> None:
        text = "TRANSFERENCIA A UNIVERSAL DE FICTICIOS SRL"
        _add_bank_rows(conn, [("2026-01-12", text, "debit", "50000")])
        corrections.set_merchant_category(conn, "TRANSFERENCIA UNIVERSAL FICTICIOS", cat.SALARY)
        found = _bank_rows(conn)[text]
        assert (found.category, found.corrected) == (cat.THIRD_PARTY, False)
