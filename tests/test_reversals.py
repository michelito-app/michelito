"""Bank-account reversals ("DEV ..."): they take the category of the debit they cancel."""

from datetime import date
from decimal import Decimal

import pytest

from michelito import db
from michelito.analysis import categories as cat
from michelito.analysis import corrections, reversals, spending
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.spending import Movement
from tests.test_spending import _add_bank_rows, _bank_rows, seed

OWN = AccountInfo(key="bhd:savings:555-0042", kind="savings", label="Savings", through=None)
OTHER = AccountInfo(key="popular:checking:700-1", kind="checking", label="P", through=None)
CARD = AccountInfo(key="bhd:credit_card", kind="credit_card", label="BHD", through=None)
ACCOUNTS = (OWN, OTHER, CARD)

DEV = "DEV LBTR E765432.ADEV9876CAS"


def mv(
    day: str,
    description: str,
    amount: str,
    category: str = cat.THIRD_PARTY,
    account: str = OWN.key,
    currency: str = "DOP",
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=description,
        description=description,
        category=category,
        amount=Decimal(amount),
        currency=currency,
        institution="x",
        fingerprint=f"{account}|{day}|{description}|{amount}|{category}",
        account=account,
        original_category=category,
    )


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)
    yield connection
    connection.close()


def pair(movements: list[Movement]) -> dict[str, str]:
    return reversals.pair_reversals(movements, ACCOUNTS)


class TestPairReversals:
    def test_reversal_takes_the_debit_category(self) -> None:
        sent = mv("2026-01-10", "LBTR 1234567890 JUAN PEREZ", "900", cat.OWN_TRANSFER)
        back = mv("2026-01-12", DEV, "-900")
        assert pair([sent, back]) == {back.fingerprint: cat.OWN_TRANSFER}

    def test_same_day_and_seven_days_count_eight_do_not(self) -> None:
        sent = mv("2026-01-10", "LBTR 1 A", "900", cat.GOVERNMENT)
        assert pair([sent, mv("2026-01-10", DEV, "-900")])
        assert pair([sent, mv("2026-01-17", DEV, "-900")])
        assert pair([sent, mv("2026-01-18", DEV, "-900")]) == {}

    def test_debit_after_the_reversal_does_not_count(self) -> None:
        later = mv("2026-01-13", "LBTR 1 A", "900", cat.OWN_TRANSFER)
        assert pair([mv("2026-01-12", DEV, "-900"), later]) == {}

    def test_amount_currency_and_account_must_match(self) -> None:
        back = mv("2026-01-12", DEV, "-900")
        assert pair([mv("2026-01-10", "X", "901", cat.OWN_TRANSFER), back]) == {}
        usd = mv("2026-01-10", "X", "900", cat.OWN_TRANSFER, currency="USD")
        assert pair([usd, back]) == {}
        elsewhere = mv("2026-01-10", "X", "900", cat.OWN_TRANSFER, account=OTHER.key)
        assert pair([elsewhere, back]) == {}

    def test_one_to_one_closest_debit_first(self) -> None:
        early = mv("2026-01-05", "LBTR 1 A", "900", cat.GOVERNMENT)
        near = mv("2026-01-09", "LBTR 2 B", "900", cat.OWN_TRANSFER)
        first = mv("2026-01-10", DEV, "-900")
        second = mv("2026-01-11", DEV + " 2", "-900")
        third = mv("2026-01-11", DEV + " 3", "-900")
        assert pair([early, near, first, second, third]) == {
            first.fingerprint: cat.OWN_TRANSFER,
            second.fingerprint: cat.GOVERNMENT,
        }

    def test_only_dev_credits_on_bank_accounts(self) -> None:
        sent = mv("2026-01-10", "LBTR 1 A", "900", cat.OWN_TRANSFER)
        refund = mv("2026-01-11", "DEVOLUCION LBTR", "-900", cat.OTHER_INCOME)
        assert pair([sent, refund]) == {}
        card_debit = mv("2026-01-10", "TIENDA", "900", cat.SHOPPING, account=CARD.key)
        card_dev = mv("2026-01-11", "DEV TIENDA", "-900", cat.SHOPPING, account=CARD.key)
        assert pair([card_debit, card_dev]) == {}
        assert pair([sent, mv("2026-01-11", DEV, "900")]) == {}  # a "DEV" debit does not

    def test_uses_the_final_category_of_the_debit(self) -> None:
        # It used to be the debit's default category; now the final one, with its correction.
        sent = mv("2026-01-10", "LBTR 1 A", "900", cat.THIRD_PARTY)
        fixed = Movement(**{**sent.__dict__, "category": cat.HOUSING, "corrected": True})
        back = mv("2026-01-12", DEV, "-900")
        assert pair([fixed, back]) == {back.fingerprint: cat.HOUSING}


class TestLoadAll:
    ROWS = [
        (
            "2026-01-10",
            "LBTR/IB/ VIA LBTR 0088001234567 MARIA PEREZ INVENTADA BANCO X",
            "debit",
            "90000",
        ),
        ("2026-01-12", DEV, "credit", "90000"),
    ]

    def test_reversal_of_an_own_transfer_cancels_inside_it(self, conn) -> None:
        _add_bank_rows(conn, self.ROWS)
        found = {m.description: m for m in spending.load_all(conn, ("MARIA PEREZ INVENTADA",))}
        sent, back = found[self.ROWS[0][1]], found[DEV]
        assert (sent.category, back.category) == (cat.OWN_TRANSFER, cat.OWN_TRANSFER)
        assert back.original_category == cat.OWN_TRANSFER
        assert sent.amount + back.amount == 0

    def test_reversal_of_a_third_party_transfer_is_not_income(self, conn) -> None:
        _add_bank_rows(conn, self.ROWS)
        back = _bank_rows(conn)[DEV]
        assert (back.category, back.kind, back.amount) == (
            cat.THIRD_PARTY,
            "transfer",
            Decimal("-900.00"),
        )

    def test_unpaired_reversal_is_a_negative_third_party_transfer(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-12", DEV, "credit", "90000")])
        back = _bank_rows(conn)[DEV]
        assert (back.category, back.amount) == (cat.THIRD_PARTY, Decimal("-900.00"))

    def test_reversal_of_a_fee_reduces_the_fee(self, conn) -> None:
        _add_bank_rows(
            conn,
            [
                ("2026-01-10", "COMISION MANEJO DE CUENTA", "debit", "15000"),
                ("2026-01-11", "DEV COMISION MANEJO", "credit", "15000"),
            ],
        )
        back = _bank_rows(conn)["DEV COMISION MANEJO"]
        assert (back.category, back.kind) == (cat.BANK_FEES, "expense")

    def test_corrections_win_on_each_row(self, conn) -> None:
        _add_bank_rows(conn, self.ROWS)
        rows = _bank_rows(conn)
        corrections.set_transaction_category(conn, rows[DEV].fingerprint, cat.OTHER_INCOME)
        corrections.set_transaction_category(conn, rows[self.ROWS[0][1]].fingerprint, cat.HOUSING)
        rows = _bank_rows(conn)
        assert (rows[DEV].category, rows[DEV].corrected) == (cat.OTHER_INCOME, True)
        # It used to be THIRD_PARTY: what is inherited is now the debit's final category.
        assert rows[DEV].original_category == cat.HOUSING
        assert rows[self.ROWS[0][1]].category == cat.HOUSING

    def test_correcting_only_the_debit_moves_its_reversal_too(self, conn) -> None:
        _add_bank_rows(conn, self.ROWS)
        sent = _bank_rows(conn)[self.ROWS[0][1]]
        corrections.set_transaction_category(conn, sent.fingerprint, cat.OWN_TRANSFER)
        rows = _bank_rows(conn)
        back = rows[DEV]
        assert (rows[sent.description].category, back.category) == (
            cat.OWN_TRANSFER,
            cat.OWN_TRANSFER,
        )
        assert not back.corrected
        assert rows[sent.description].amount + back.amount == 0

    def test_merchant_rule_on_the_debit_moves_its_reversal_too(self, conn) -> None:
        _add_bank_rows(conn, self.ROWS)
        sent = _bank_rows(conn)[self.ROWS[0][1]]
        corrections.set_merchant_category(conn, sent.merchant, cat.HOUSING)
        assert _bank_rows(conn)[DEV].category == cat.HOUSING

    def test_fingerprints_do_not_change(self, conn) -> None:
        _add_bank_rows(conn, self.ROWS)
        back = _bank_rows(conn)[DEV]
        assert back.fingerprint == corrections.fingerprint(
            back.account, back.day, DEV, 90000, "credit", back.currency, 0
        )

    def test_merchant_rule_on_a_dev_does_not_move_paired_reversals(self, conn) -> None:
        # Reversals share a key ("DEV LBTR"): a merchant rule saved from one would change them
        # all. On a paired one only that row's own correction counts.
        other = "LBTR 1234567890 JUAN PEREZ"
        _add_bank_rows(
            conn,
            [
                *self.ROWS,
                ("2026-01-15", other, "debit", "50000"),
                ("2026-01-16", "DEV LBTR E111111.ADEV5555XYZ", "credit", "50000"),
                ("2026-01-20", "DEV LBTR E222222.ADEV6666XYZ", "credit", "1000"),  # no debit
            ],
        )
        holders = ("MARIA PEREZ INVENTADA",)
        rows = {m.description: m for m in spending.load_all(conn, holders)}
        assert rows[DEV].merchant == rows["DEV LBTR E111111.ADEV5555XYZ"].merchant == "DEV LBTR"
        corrections.set_merchant_category(conn, "DEV LBTR", cat.OTHER_INCOME)
        rows = {m.description: m for m in spending.load_all(conn, holders)}
        assert (rows[DEV].category, rows[DEV].corrected) == (cat.OWN_TRANSFER, False)
        paired = rows["DEV LBTR E111111.ADEV5555XYZ"]
        assert (paired.category, paired.corrected) == (cat.THIRD_PARTY, False)
        # The rule does apply to the reversal without a debit.
        assert rows["DEV LBTR E222222.ADEV6666XYZ"].category == cat.OTHER_INCOME
        # And the transaction correction still wins.
        corrections.set_transaction_category(conn, paired.fingerprint, cat.HOUSING)
        rows = {m.description: m for m in spending.load_all(conn, holders)}
        fixed = rows["DEV LBTR E111111.ADEV5555XYZ"]
        assert (fixed.category, fixed.corrected) == (cat.HOUSING, True)

    def test_legacy_rule_does_not_move_a_paired_reversal(self, conn) -> None:
        _add_bank_rows(conn, self.ROWS)
        # The reversal's old key was "LBTR E" (merchant_key without the DEV prefix).
        corrections.set_merchant_category(conn, cat.merchant_key(DEV), cat.OTHER_INCOME)
        assert _bank_rows(conn)[DEV].category == cat.THIRD_PARTY
