""" "To review": rules over made-up transactions."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from michelito.analysis import categories as cat
from michelito.analysis import review
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from tests.test_spending import movement as _movement

MONTH = "2026-05"


def move(
    day: str,
    amount: str,
    category: str = cat.HOME,
    merchant: str = "TIENDA INVENTADA",
    account: str = "demo:credit_card",
    currency: str = "DOP",
    seq: int = 0,
) -> Movement:
    return replace(
        _movement(day, amount, category, merchant, currency),
        fingerprint=f"{merchant}-{day}-{amount}-{seq}",
        account=account,
    )


def no_rate(_month: str) -> Rate | None:
    return None


def detect(movements, **options):
    return review.detect(movements, MONTH, rate_for_month=no_rate, **options)


def kinds(items):
    return [(i.kind, i.merchant) for i in items]


# An old transaction so there is history (new counterparts need it).
OLD = move("2026-01-02", "100", merchant="COLMADO VIEJO")


class TestUnusualIncome:
    def test_large_income_from_a_new_counterpart(self):
        found = detect([OLD, move("2026-05-10", "-20000", cat.OTHER_INCOME, "CLIENTE NUEVO")])
        assert kinds(found) == [("unusual_income", "CLIENTE NUEVO")]
        assert found[0].amount == Decimal(20000) and found[0].amount_dop == Decimal(20000)
        assert "contraparte nueva" in found[0].reason  # spanish-ui
        # OLD is from January 2: there are 128 days of history, not a year.
        assert "en los últimos 128 días" in found[0].reason  # spanish-ui

    def test_with_a_full_year_of_history_the_reason_says_so(self):
        old = move("2025-01-02", "100", merchant="COLMADO VIEJO")
        [found] = detect([old, move("2026-05-10", "-20000", cat.OTHER_INCOME, "CLIENTE NUEVO")])
        assert "en el último año" in found.reason  # spanish-ui

    def test_known_counterpart_small_amount_or_no_history_are_not_flagged(self):
        known = [OLD, move("2026-02-10", "-15000", cat.SALARY, "NOMINA")]
        assert detect([*known, move("2026-05-10", "-20000", cat.SALARY, "NOMINA")]) == []
        assert detect([OLD, move("2026-05-10", "-9999", cat.OTHER_INCOME, "CLIENTE")]) == []
        # Without 60 days of data before, everything would look new.
        assert detect([move("2026-05-10", "-20000", cat.OTHER_INCOME, "CLIENTE")]) == []

    def test_counterpart_seen_over_a_year_ago_is_new_again(self):
        old = move("2025-04-01", "-15000", cat.OTHER_INCOME, "CLIENTE")
        found = detect([old, move("2026-05-10", "-20000", cat.OTHER_INCOME, "CLIENTE")])
        assert kinds(found) == [("unusual_income", "CLIENTE")]


class TestLargeThirdParty:
    def test_from_threshold_up(self):
        bank = "demo:checking:1"
        items = [
            move("2026-05-03", "25000", cat.THIRD_PARTY, "MB A PERSONA", bank),
            move("2026-05-04", "24999", cat.THIRD_PARTY, "MB A OTHER", bank),
            move("2026-04-30", "90000", cat.THIRD_PARTY, "MB A ABRIL", bank),
        ]
        assert kinds(detect(items)) == [("large_third_party", "MB A PERSONA")]

    def test_usd_counts_with_the_rate(self):
        rate = Rate(Decimal("60"), MONTH, "manual")
        item = move("2026-05-03", "500", cat.THIRD_PARTY, "ENVIO", "b", "USD")
        [found] = review.detect([item], MONTH, rate_for_month=lambda _m: rate)
        assert (found.amount, found.currency, found.amount_dop) == (
            Decimal(500),
            "USD",
            Decimal(30000),
        )
        assert review.detect([item], MONTH, rate_for_month=no_rate) == []


class TestDuplicates:
    def test_same_account_merchant_and_amount_same_or_next_day(self):
        items = [
            move("2026-05-03", "1200", merchant="CAFE", seq=1),
            move("2026-05-03", "1200", merchant="CAFE", seq=2),
            move("2026-05-10", "800", merchant="PIZZA"),
            move("2026-05-11", "800", merchant="PIZZA"),
            move("2026-05-20", "500", merchant="CINE"),
            move("2026-05-22", "500", merchant="CINE"),  # two days apart: no
            move("2026-05-25", "300", merchant="BUS"),
            move(
                "2026-05-25", "300", merchant="BUS", account="other:credit_card"
            ),  # another account
        ]
        found = detect(items)
        assert kinds(found) == [("duplicate", "PIZZA"), ("duplicate", "CAFE")]
        assert found[0].fingerprint == "PIZZA-2026-05-11-800-0"
        assert "el día anterior" in found[0].reason  # spanish-ui
        assert "el mismo día" in found[1].reason  # spanish-ui

    def test_first_charge_in_the_previous_month(self):
        items = [
            move("2026-04-30", "700", merchant="BAR"),
            move("2026-05-01", "700", merchant="BAR"),
        ]
        assert kinds(detect(items)) == [("duplicate", "BAR")]
        assert review.detect(items, "2026-04", rate_for_month=no_rate) == []

    def test_a_daily_toll_is_not_a_duplicate(self):
        """A daily RD$ 100 toll: it recurs (and on the next day, under RD$ 500 does not count)."""
        tolls = [move(f"2026-05-{d:02d}", "100", merchant="PEAJE") for d in range(1, 21)]
        same_day = move("2026-05-20", "100", merchant="PEAJE", seq=1)  # two passes on the same day
        assert detect([*tolls, same_day]) == []

    def test_a_charge_that_already_recurs_is_skipped_even_when_large(self):
        """Three equal charges in the previous 60 days: it is a recurring charge."""
        usual = [move(f"2026-04-{d:02d}", "900", merchant="PARQUEO") for d in (1, 8, 15)]
        pair = [
            move("2026-05-03", "900", merchant="PARQUEO", seq=1),
            move("2026-05-03", "900", merchant="PARQUEO", seq=2),
        ]
        assert detect([*usual, *pair]) == []
        # With only two before, the double charge does show.
        assert kinds(detect([*usual[1:], *pair])) == [("duplicate", "PARQUEO")]

    def test_next_day_needs_at_least_500_but_same_day_does_not(self):
        next_day = [
            move("2026-05-10", "499", merchant="KIOSKO"),
            move("2026-05-11", "499", merchant="KIOSKO"),
        ]
        assert detect(next_day) == []
        same_day = [
            move("2026-05-10", "350", merchant="KIOSKO", seq=1),
            move("2026-05-10", "350", merchant="KIOSKO", seq=2),
        ]
        assert kinds(detect(same_day)) == [("duplicate", "KIOSKO")]

    def test_a_real_double_charge_is_flagged(self):
        history = [move("2026-03-15", "4500", merchant="TIENDA X")]
        double = [
            move("2026-05-20", "4500", merchant="TIENDA X"),
            move("2026-05-21", "4500", merchant="TIENDA X"),
        ]
        assert kinds(detect([*history, *double])) == [("duplicate", "TIENDA X")]


class TestOneOffsAndPriceUps:
    def _big(self):
        return move("2026-05-08", "45000", cat.TRAVEL, "AGENCIA FICTICIA")

    def test_one_off_suggestions_are_one_kind(self):
        [found] = detect([self._big()])
        assert found.kind == "one_off" and "categoría poco usada" in found.reason  # spanish-ui
        assert found.reviewed is False

    def test_dismissed_one_off_is_reviewed_not_gone(self):
        big = self._big()
        [found] = detect([big], dismissed={big.fingerprint})
        assert (found.kind, found.reviewed) == ("one_off", True)

    def test_price_ups_come_from_recurring_alerts(self):
        charge = move("2026-05-05", "1199", cat.SUBSCRIPTIONS, "STREAMING")
        reason = "Subió de RD$ 999 a RD$ 1,199"  # spanish-ui
        found = detect([charge], price_ups={charge.fingerprint: reason})
        assert kinds(found) == [("price_up", "STREAMING")]
        assert found[0].reason == reason


def test_history_keeps_dismissed_one_offs_beyond_the_cap_of_five():
    """Six rare purchases: the smallest (dismissed) is not lost to the cap of 5."""
    buys = [
        move("2026-05-08", f"{amount}000", f"Category {amount}", f"COMERCIO {amount}")
        for amount in (20, 30, 40, 50, 60, 70)
    ]
    smallest = buys[0]
    found = detect(buys, dismissed={smallest.fingerprint})
    one_offs = [(i.merchant, i.reviewed) for i in found if i.kind == "one_off"]
    assert len(one_offs) == 6
    assert ("COMERCIO 20", True) in one_offs
    assert sum(1 for _, reviewed in one_offs if not reviewed) == 5


def test_one_offs_are_worked_out_once_per_review(monkeypatch):
    """The pending ones and the dismissed history come from one pass over the history: each
    pass detects the recurring charges and converts every purchase again."""
    buys = [
        move("2026-05-08", f"{amount}000", f"Category {amount}", f"COMERCIO {amount}")
        for amount in (20, 30, 40, 50, 60, 70)
    ]
    largest = buys[-1]
    real = review.one_offs.suggest
    calls = []
    monkeypatch.setattr(
        review.one_offs, "suggest", lambda *a, **k: calls.append(k) or real(*a, **k)
    )

    found = detect(buys, dismissed={largest.fingerprint})

    one_offs = [(i.merchant, i.reviewed) for i in found if i.kind == "one_off"]
    pending = {name for name, reviewed in one_offs if not reviewed}
    assert pending == {f"COMERCIO {amount}" for amount in (20, 30, 40, 50, 60)}
    assert [name for name, reviewed in one_offs if reviewed] == ["COMERCIO 70"]
    assert len(calls) == 1


def test_reviewed_marks_are_per_kind_and_order_is_newest_first():
    items = [
        move("2026-05-03", "1200", merchant="CAFE", seq=1),
        move("2026-05-03", "1200", merchant="CAFE", seq=2),
        move("2026-05-10", "30000", cat.THIRD_PARTY, "MB A PERSONA", "b"),
    ]
    found = detect(items, reviewed={("CAFE-2026-05-03-1200-2", "duplicate")})
    assert [(i.kind, i.reviewed) for i in found] == [
        ("large_third_party", False),
        ("duplicate", True),
    ]
    # The same fingerprint with another kind does not count as reviewed.
    again = detect(items, reviewed={("CAFE-2026-05-03-1200-2", "large_third_party")})
    assert [i.reviewed for i in again] == [False, False]
