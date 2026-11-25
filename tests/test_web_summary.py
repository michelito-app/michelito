from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from michelito.analysis import categories
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.rates import Rate
from michelito.web import summary
from tests.test_spending import movement as _movement


def movement(
    day, amount, category=categories.GROCERIES, currency="DOP", account="A", one_off=False
):
    return replace(
        _movement(day, amount, category, currency=currency), account=account, one_off=one_off
    )


def card(key, through, label=None):
    return AccountInfo(key, "credit_card", label or f"Card {key}", date.fromisoformat(through))


def rate(month, value="60"):
    return Rate(Decimal(value), month, "manual")


BOTH_OCTOBER = [card("A", "2026-10-31"), card("B", "2026-10-13")]


def test_month_options_mark_partial_by_account_coverage():
    moves = [movement("2026-09-10", "100"), movement("2026-10-10", "100")]
    options = summary.month_options(moves, BOTH_OCTOBER)
    assert [(o.month, o.partial) for o in options] == [("2026-10", True), ("2026-09", False)]
    assert options[0].label == "Octubre 2026"  # spanish-ui


def test_inactive_account_does_not_block_months():
    accounts = [card("A", "2026-10-31"), card("OLD", "2026-03-31")]
    moves = [movement("2026-09-10", "100"), movement("2026-10-10", "100")]
    assert [o.partial for o in summary.month_options(moves, accounts)] == [False, False]


def test_habitual_is_median_without_one_offs():
    moves = [
        movement("2026-04-10", "100"),
        movement("2026-05-10", "120"),
        movement("2026-06-10", "100"),
        movement("2026-06-11", "800", one_off=True),
        movement("2026-07-10", "110"),
        movement("2026-08-10", "300"),
    ]
    result = summary.build_summary(moves, [card("A", "2026-08-31")], {}, "2026-08")
    assert result.habitual == Decimal(105)  # median of 100, 120, 100, 110
    june = summary.build_summary(moves, [card("A", "2026-08-31")], {}, "2026-06")
    assert june.total == Decimal(900)
    assert june.one_offs == Decimal(800)
    assert june.regular_total == Decimal(100)


@pytest.mark.parametrize(
    ("habitual", "extra", "same"),
    [("10000", "499", True), ("10000", "501", False), ("20000", "999", True)],
)
def test_same_band(habitual, extra, same):
    moves = [movement(f"2026-0{m}-10", habitual) for m in (4, 5, 6)]
    moves.append(movement("2026-07-10", str(Decimal(habitual) + Decimal(extra))))
    result = summary.build_summary(moves, [card("A", "2026-07-31")], {}, "2026-07")
    assert result.categories[0].same is same


def test_usd_converted_with_fallback_rate():
    moves = [movement("2026-09-05", "10", currency="USD"), movement("2026-09-06", "40")]
    rates = {"2026-08": rate("2026-08")}
    result = summary.build_summary(moves, [card("A", "2026-09-30")], rates, "2026-09")
    assert result.total == Decimal(640)
    assert result.usd == Decimal(10)
    assert result.usd_in_dop == Decimal(600)
    assert result.rate is not None and result.rate.month_used == "2026-08"
    assert result.by_account[0].total == Decimal(640)
    assert result.by_account[0].usd == Decimal(10)


def test_usd_without_any_rate_is_not_counted_silently():
    moves = [movement("2026-09-05", "10", currency="USD"), movement("2026-09-06", "40")]
    result = summary.build_summary(moves, [card("A", "2026-09-30")], {}, "2026-09")
    assert result.usd_in_dop is None
    assert result.rate is None
    assert result.total == Decimal(40)
    assert result.usd == Decimal(10)


def test_refund_only_category_has_zero_share():
    moves = [movement("2026-09-05", "-100", "Clothes"), movement("2026-09-06", "400")]
    result = summary.build_summary(moves, [card("A", "2026-09-30")], {}, "2026-09")
    line = next(c for c in result.categories if c.category == "Clothes")
    assert line.amount == Decimal(-100)
    assert line.share == 0.0


def test_partial_month_has_no_comparison():
    moves = [movement("2026-09-10", "100"), movement("2026-10-10", "100")]
    result = summary.build_summary(moves, BOTH_OCTOBER, {}, "2026-10")
    assert result.habitual is None
    assert all(c.diff is None for c in result.categories)
    assert result.changes == []


def test_changes_top_three_by_absolute_diff_without_same():
    moves = []
    for month in ("2026-04", "2026-05"):
        moves += [
            movement(f"{month}-10", "10000", "Food"),
            movement(f"{month}-11", "10000", "Leisure"),
            movement(f"{month}-12", "5000", "Gym"),
        ]
    moves += [
        movement("2026-06-10", "13000", "Food"),
        movement("2026-06-11", "10100", "Leisure"),
        movement("2026-06-12", "0.01", "Gym"),
        movement("2026-06-13", "2000", categories.TRAVEL),
    ]
    result = summary.build_summary(moves, [card("A", "2026-06-30")], {}, "2026-06")
    assert [c.category for c in result.changes] == ["Gym", "Food", categories.TRAVEL]
    assert result.changes[0].diff < 0
    assert result.changes[0].purchases == 1
    assert result.changes[0].habitual_purchases == 1


def test_trend_and_by_account():
    moves = [movement("2026-08-10", "100"), movement("2026-09-10", "300", account="B")]
    accounts = [card("A", "2026-09-30"), card("B", "2026-09-30")]
    result = summary.build_summary(moves, accounts, {}, "2026-09")
    assert [(t.month, t.total) for t in result.trend] == [
        ("2026-08", Decimal(100)),
        ("2026-09", Decimal(300)),
    ]
    assert [(a.key, a.total) for a in result.by_account] == [("B", Decimal(300))]
    assert [c.key for c in result.coverage] == ["A", "B"]


def test_unknown_month_raises():
    with pytest.raises(LookupError):
        summary.build_summary(
            [movement("2026-09-10", "1")], [card("A", "2026-09-30")], {}, "2030-01"
        )


def test_no_usd_without_rate_is_zero_not_missing():
    result = summary.build_summary(
        [movement("2026-09-06", "40")], [card("A", "2026-09-30")], {}, "2026-09"
    )
    assert result.usd_in_dop == Decimal(0)


def test_coverage_lists_only_active_cards():
    accounts = [card("A", "2026-09-30"), card("OLD", "2026-03-31")]
    result = summary.build_summary([movement("2026-09-06", "40")], accounts, {}, "2026-09")
    assert [c.key for c in result.coverage] == ["A"]


def _flow_moves():
    return [
        movement("2026-09-05", "1000"),
        movement("2026-09-06", "50", currency="USD"),
        movement("2026-09-10", "-5000", categories.SALARY),
        movement("2026-09-11", "-10", categories.SERVICE_PAYMENTS, currency="USD"),
        movement("2026-09-12", "700", categories.CARD_PAYMENT),
        movement("2026-09-13", "-300", categories.OWN_TRANSFER),
        movement("2026-09-14", "-99", categories.CARD_PAYMENT),
    ]


def test_income_net_and_savings_rate_convert_usd_and_skip_transfers():
    result = summary.build_summary(
        _flow_moves(), [card("A", "2026-09-30")], {"2026-09": rate("2026-09")}, "2026-09"
    )
    assert result.total == Decimal(4000)  # 1000 + 50 US$ * 60; no transfers
    assert result.income == Decimal(5600)  # 5000 + 10 US$ * 60
    assert result.net == Decimal(1600)
    assert result.savings_rate == pytest.approx(1600 / 5600)
    assert result.usd == Decimal(50)  # income US$ do not count as dollars spent
    assert [t.income for t in result.trend if t.month == "2026-09"] == [Decimal(5600)]


def test_month_without_income_has_no_savings_rate():
    result = summary.build_summary(
        [movement("2026-09-05", "1000")], [card("A", "2026-09-30")], {}, "2026-09"
    )
    assert (result.income, result.net, result.savings_rate) == (0, Decimal(-1000), None)


def test_income_in_usd_without_rate_is_excluded():
    moves = [
        movement("2026-09-05", "100"),
        movement("2026-09-10", "-10", categories.SERVICE_PAYMENTS, currency="USD"),
    ]
    result = summary.build_summary(moves, [card("A", "2026-09-30")], {}, "2026-09")
    assert result.income == 0 and result.savings_rate is None


def test_transfers_and_income_do_not_change_spending_numbers():
    spend = [movement("2026-08-10", "100"), movement("2026-09-10", "400", categories.RESTAURANTS)]
    cards = [card("A", "2026-09-30")]
    rates = {"2026-09": rate("2026-09")}
    base = summary.build_summary(spend, cards, rates, "2026-09")
    mixed = summary.build_summary([*spend, *_flow_moves()[2:]], cards, rates, "2026-09")
    for field in ("total", "regular_total", "one_offs", "habitual", "usd", "categories", "changes"):
        assert getattr(mixed, field) == getattr(base, field), field
    assert [t.total for t in mixed.trend] == [t.total for t in base.trend]
    assert mixed.by_account == base.by_account


def test_negligible_income_has_no_savings_rate():
    moves = [
        movement("2026-09-05", "180000"),
        movement("2026-09-10", "-0.41", categories.OTHER_INCOME),
    ]
    result = summary.build_summary(moves, [card("A", "2026-09-30")], {}, "2026-09")
    assert result.income == Decimal("0.41") and result.savings_rate is None
    assert result.net == Decimal("0.41") - Decimal(180000)


def test_small_but_real_income_keeps_negative_savings_rate():
    moves = [movement("2026-09-05", "205787"), movement("2026-09-10", "-100000", categories.SALARY)]
    result = summary.build_summary(moves, [card("A", "2026-09-30")], {}, "2026-09")
    assert result.savings_rate == pytest.approx(-1.05787)


def test_income_only_month_does_not_create_options_or_change_habitual():
    spend = [movement(f"2026-0{m}-10", "100") for m in (4, 5, 6)]
    early = [movement("2026-02-10", "-9000", categories.SALARY)]
    cards = [card("A", "2026-06-30")]
    assert [o.month for o in summary.month_options([*early, *spend], cards)] == [
        "2026-06",
        "2026-05",
        "2026-04",
    ]
    base = summary.build_summary(spend, cards, {}, "2026-06")
    mixed = summary.build_summary([*early, *spend], cards, {}, "2026-06")
    assert mixed.habitual == base.habitual
    assert [t.month for t in mixed.trend] == [t.month for t in base.trend]


def test_by_account_labels_bank_accounts_too():
    bank = AccountInfo("bco:checking:1", "checking", "BCO Checking 1", None)
    moves = [movement("2026-09-10", "500", account="bco:checking:1")]
    result = summary.build_summary(moves, [card("A", "2026-09-30"), bank], {}, "2026-09")
    assert [(a.key, a.label) for a in result.by_account] == [("bco:checking:1", "BCO Checking 1")]


def bank(key, through, kind="checking"):
    return AccountInfo(
        key, kind, f"Account {key}", date.fromisoformat(through) if through else None
    )


def _paid_month():
    return [
        movement("2026-09-05", "1000"),
        movement("2026-09-10", "-5000", categories.SALARY, account="C"),
    ]


class TestIncomeThrough:
    def test_bank_cut_before_month_end_marks_income_partial(self):
        accounts = [card("A", "2026-09-30"), bank("C", "2026-09-15"), bank("S", "2026-09-30")]
        result = summary.build_summary(_paid_month(), accounts, {}, "2026-09")
        assert result.income_through == date(2026, 9, 15)
        assert result.savings_rate is None
        assert result.income == Decimal(5000)  # the known income is still shown

    def test_all_bank_accounts_cover_the_month(self):
        accounts = [card("A", "2026-09-30"), bank("C", "2026-10-15", "savings")]
        result = summary.build_summary(_paid_month(), accounts, {}, "2026-09")
        assert result.income_through is None
        assert result.savings_rate == pytest.approx(0.8)

    def test_without_bank_accounts_or_statements(self):
        no_bank = summary.build_summary(_paid_month(), [card("A", "2026-09-30")], {}, "2026-09")
        unseen = summary.build_summary(
            _paid_month(), [card("A", "2026-09-30"), bank("C", None)], {}, "2026-09"
        )
        assert no_bank.income_through is None and unseen.income_through is None
        assert no_bank.savings_rate == pytest.approx(0.8)


class TestMonthsBeforeCards:
    """Months of a bank statement older than the first card: out of the options and baseline."""

    def _moves(self):
        older_bank = [
            movement(f"2026-0{m}-10", "90000", categories.OTHER, account="C") for m in (3, 4, 5)
        ]
        cards_spend = [movement(f"2026-0{m}-10", "100") for m in (6, 7, 8)]
        return [*older_bank, *cards_spend]

    def test_options_start_with_the_first_card_month(self):
        accounts = [card("A", "2026-08-31"), bank("C", "2026-08-31")]
        options = summary.month_options(self._moves(), accounts)
        assert [o.month for o in options] == ["2026-08", "2026-07", "2026-06"]

    def test_baseline_and_trend_ignore_bank_only_months(self):
        accounts = [card("A", "2026-08-31"), bank("C", "2026-08-31")]
        result = summary.build_summary(self._moves(), accounts, {}, "2026-08")
        assert result.habitual == Decimal(100)
        assert [t.month for t in result.trend] == ["2026-06", "2026-07", "2026-08"]

    def test_without_card_movements_nothing_is_cut(self):
        moves = [movement(f"2026-0{m}-10", "50", account="C") for m in (5, 6)]
        options = summary.month_options(moves, [bank("C", "2026-06-30")])
        assert [o.month for o in options] == ["2026-06", "2026-05"]


class TestIncomeThroughStaleAccounts:
    """An account counts for month M only if its latest cut-off is in month M-1 or later."""

    def _result(self, through, month):
        moves = [
            movement(f"{month}-05", "1000"),
            movement(f"{month}-10", "-5000", categories.SALARY, account="C"),
        ]
        accounts = [card("A", "2026-12-31"), bank("C", through)]
        return summary.build_summary(moves, accounts, {}, month)

    def test_cut_in_the_previous_month_marks_the_month_partial(self):
        result = self._result("2026-08-20", "2026-09")
        assert result.income_through == date(2026, 8, 20)
        assert result.savings_rate is None

    def test_cut_before_the_previous_month_is_ignored(self):
        for month in ("2026-10", "2026-11"):
            result = self._result("2026-08-20", month)
            assert result.income_through is None, month
            assert result.savings_rate == pytest.approx(0.8)

    def test_first_day_of_the_previous_month_still_counts(self):
        assert self._result("2026-09-01", "2026-10").income_through == date(2026, 9, 1)
        assert self._result("2026-08-31", "2026-10").income_through is None


class TestThirdParty:
    """Third-party transfers are not spending, but they reduce what you have left."""

    def _moves(self):
        return [
            movement("2026-09-05", "1000"),
            movement("2026-09-10", "-5000", categories.SALARY),
            movement("2026-09-12", "1500", categories.THIRD_PARTY),
            movement("2026-09-13", "20", categories.THIRD_PARTY, currency="USD"),
            movement("2026-08-12", "999", categories.THIRD_PARTY),
        ]

    def _result(self, moves, month="2026-09"):
        rates = {"2026-09": rate("2026-09")}
        return summary.build_summary(moves, [card("A", "2026-09-30")], rates, month)

    def test_net_subtracts_third_party_converted_to_dop(self):
        result = self._result(self._moves())
        assert result.third_party == Decimal(2700)  # 1500 + 20 US$ * 60; this month only
        assert result.total == Decimal(1000)
        assert result.net == Decimal(5000 - 1000 - 2700)
        assert result.savings_rate == pytest.approx(1300 / 5000)

    def test_a_corrected_credit_in_the_category_reduces_it(self):
        moves = [*self._moves(), movement("2026-09-20", "-200", categories.THIRD_PARTY)]
        assert self._result(moves).third_party == Decimal(2500)

    def test_third_party_stays_out_of_spending_numbers(self):
        spend = [
            movement("2026-08-10", "100"),
            movement("2026-09-10", "400", categories.RESTAURANTS),
        ]
        cards = [card("A", "2026-09-30")]
        rates = {"2026-09": rate("2026-09")}
        base = summary.build_summary(spend, cards, rates, "2026-09")
        mixed = summary.build_summary([*spend, *self._moves()[2:]], cards, rates, "2026-09")
        for field in ("total", "regular_total", "one_offs", "habitual", "usd", "categories"):
            assert getattr(mixed, field) == getattr(base, field), field
        assert [(t.total, t.month) for t in mixed.trend] == [(t.total, t.month) for t in base.trend]
        assert mixed.by_account == base.by_account
        assert base.third_party == 0

    def test_month_with_only_third_party_outflows(self):
        moves = [
            movement("2026-08-05", "100"),
            movement("2026-09-10", "-3000", categories.SALARY),
            movement("2026-09-12", "1000", categories.THIRD_PARTY),
            movement("2026-10-05", "100"),
        ]
        result = summary.build_summary(moves, [card("A", "2026-10-31")], {}, "2026-09")
        assert (result.total, result.third_party) == (0, Decimal(1000))
        assert result.net == Decimal(2000)
        assert result.savings_rate == pytest.approx(2000 / 3000)
        # Groceries shows up through its usual amount; third party is not a spending category.
        assert [(c.category, c.amount) for c in result.categories] == [(categories.GROCERIES, 0)]

    def test_negligible_income_against_third_party_has_no_savings_rate(self):
        moves = [
            movement("2026-09-05", "10"),
            movement("2026-09-10", "-1", categories.OTHER_INCOME),
            movement("2026-09-12", "180000", categories.THIRD_PARTY),
        ]
        assert self._result(moves).savings_rate is None

    def test_income_through_still_hides_savings_rate(self):
        accounts = [card("A", "2026-09-30"), bank("bco:checking:1", "2026-09-15")]
        result = summary.build_summary(
            self._moves(), accounts, {"2026-09": rate("2026-09")}, "2026-09"
        )
        assert result.savings_rate is None
        assert result.net == Decimal(1300)


class TestSelectedAccounts:
    """The Summary of a subset of accounts: everything comes only from the selected ones."""

    ACCOUNTS = [card("A", "2026-09-30"), card("B", "2026-09-30"), bank("C", "2026-09-30")]

    def _moves(self):
        moves = []
        for month in ("2026-06", "2026-07", "2026-08"):
            moves += [movement(f"{month}-05", "100"), movement(f"{month}-06", "1000", account="B")]
        return [
            *moves,
            movement("2026-09-05", "300"),
            movement("2026-09-06", "2000", categories.RESTAURANTS, account="B"),
            movement("2026-09-10", "-5000", categories.SALARY, account="C"),
            movement("2026-09-11", "700", categories.CASH, account="C"),
            # Payment of card A from account C: a transfer on both sides.
            movement("2026-09-12", "300", categories.CARD_PAYMENT, account="C"),
            movement("2026-09-13", "-300", categories.CARD_PAYMENT, account="A"),
            movement("2026-09-14", "400", categories.OWN_TRANSFER, account="C"),
        ]

    def _result(self, selected, month="2026-09"):
        return summary.build_summary(self._moves(), self.ACCOUNTS, {}, month, selected)

    def test_totals_categories_and_by_account_only_from_selected(self):
        result = self._result({"B", "C"})
        assert result.total == Decimal(2700)
        assert result.income == Decimal(5000)
        assert result.net == Decimal(2300)
        assert [c.category for c in result.categories] == [
            categories.RESTAURANTS,
            categories.CASH,
            categories.GROCERIES,
        ]
        assert {a.key for a in result.by_account} == {"B", "C"}

    def test_habitual_baseline_from_selected_only(self):
        assert self._result({"A"}).habitual == Decimal(100)
        assert self._result({"B"}).habitual == Decimal(1000)
        assert self._result(None).habitual == Decimal(1100)

    def test_trend_from_selected_only(self):
        assert [t.total for t in self._result({"A"}).trend] == [Decimal(100)] * 3 + [Decimal(300)]

    def test_without_income_net_and_savings_rate_are_none(self):
        result = self._result({"A", "B"})
        assert result.income == 0
        assert result.net is None and result.savings_rate is None
        assert result.needs_income is True
        assert self._result(None).needs_income is False

    def test_all_accounts_without_income_keep_the_negative_net(self):
        result = summary.build_summary(self._moves(), self.ACCOUNTS, {}, "2026-08", None)
        assert result.net == Decimal(-1100) and result.needs_income is False

    def test_transfers_stay_out_even_with_the_card_unselected(self):
        result = self._result({"C"})
        assert result.total == Decimal(700)
        assert result.net == Decimal(4300)
        assert [c.category for c in result.categories] == [categories.CASH]

    def test_informational_line_counts_outflows_to_unselected_accounts(self):
        only_bank = self._result({"C"})
        assert (only_bank.to_cards, only_bank.to_own) == (Decimal(300), Decimal(0))
        mixed = self._result({"B", "C"})
        assert (mixed.to_cards, mixed.to_own) == (Decimal(300), Decimal(0))
        everything = self._result(None)
        assert (everything.to_cards, everything.to_own) == (0, 0)
        # Selecting every account is the same as selecting none.
        assert self._result({"A", "B", "C"}) == everything

    def test_own_transfers_count_when_a_bank_account_is_unselected(self):
        # Every card selected: the card payment goes to a selected account.
        accounts = [*self.ACCOUNTS, bank("S", "2026-09-30", "savings")]
        result = summary.build_summary(self._moves(), accounts, {}, "2026-09", {"A", "B", "C"})
        assert (result.to_cards, result.to_own) == (Decimal(0), Decimal(400))

    def test_coverage_and_partial_from_selected_accounts(self):
        accounts = [card("A", "2026-09-30"), card("B", "2026-09-13"), bank("C", "2026-09-30")]
        moves = self._moves()
        assert summary.build_summary(moves, accounts, {}, "2026-09").option.partial is True
        only_a = summary.build_summary(moves, accounts, {}, "2026-09", {"A"})
        assert only_a.option.partial is False
        assert [c.key for c in only_a.coverage] == ["A"]
        assert only_a.habitual == Decimal(100)

    def test_bank_only_selection_uses_bank_coverage(self):
        accounts = [card("A", "2026-09-30"), bank("C", "2026-09-15")]
        options = summary.month_options(self._moves(), accounts, {"C"})
        assert [(o.month, o.partial) for o in options][:2] == [
            ("2026-09", True),
            ("2026-08", False),
        ]

    def test_month_options_keep_the_global_span(self):
        everything = summary.month_options(self._moves(), self.ACCOUNTS)
        only_c = summary.month_options(self._moves(), self.ACCOUNTS, {"C"})
        assert [o.month for o in only_c] == [o.month for o in everything]

    def test_income_through_only_from_selected_bank_accounts(self):
        accounts = [card("A", "2026-09-30"), bank("C", "2026-09-30"), bank("D", "2026-09-15")]
        moves = self._moves()
        assert summary.build_summary(moves, accounts, {}, "2026-09").income_through is not None
        result = summary.build_summary(moves, accounts, {}, "2026-09", {"A", "C"})
        assert result.income_through is None


class TestSelectionFlowAndPartial:
    """Flow hidden only without bank accounts; months partial when none is active."""

    def test_bank_in_selection_keeps_net_even_if_cut_before_month_end(self):
        accounts = [card("A", "2026-09-30"), card("B", "2026-09-30"), bank("C", "2026-09-15")]
        moves = [movement("2026-09-05", "1000"), movement("2026-09-08", "200", account="B")]
        result = summary.build_summary(moves, accounts, {}, "2026-09", {"A", "C"})
        assert result.needs_income is False
        assert result.net == Decimal(-1000)  # no income yet, but there is a bank account
        assert result.savings_rate is None

    def test_only_cards_need_income_even_with_cashback(self):
        accounts = [card("A", "2026-09-30"), bank("C", "2026-09-30")]
        moves = [
            movement("2026-09-05", "1000"),
            movement("2026-09-06", "-900", categories.OTHER_INCOME),
        ]
        result = summary.build_summary(moves, accounts, {}, "2026-09", {"A"})
        assert result.needs_income is True
        assert result.net is None and result.savings_rate is None

    def test_selection_without_active_accounts_is_partial_like_all_accounts(self):
        accounts = [card("A", "2026-09-30"), card("OLD", "2026-03-31")]
        moves = [movement("2026-08-10", "100"), movement("2026-09-10", "100", account="OLD")]
        options = summary.month_options(moves, accounts, {"OLD"})
        assert [o.partial for o in options] == [True, True]
        assert summary.month_options(moves, [card("A", "2026-09-30")], None)[0].partial is False


def test_trend_marks_months_in_progress():
    moves = [movement("2026-09-10", "100"), movement("2026-10-10", "100")]
    result = summary.build_summary(moves, BOTH_OCTOBER, {}, "2026-10")
    assert [(t.month, t.partial) for t in result.trend] == [("2026-09", False), ("2026-10", True)]
