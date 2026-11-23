"""Net worth: holdings valued on a day in RD$, monthly history, the month's change and groups."""

from datetime import date
from decimal import Decimal

from michelito.analysis import net_worth
from michelito.analysis.net_worth import Holding
from michelito.analysis.rates import Rate

RATES = {
    "2026-01": Rate(Decimal("60"), "2026-01", "bcrd"),
    "2026-03": Rate(Decimal("62"), "2026-03", "bcrd"),
}


def _steps(*points: tuple[str, str]):
    """A value that follows the latest point on or before the day (None before the first)."""
    parsed = [(date.fromisoformat(d), Decimal(v)) for d, v in points]

    def value_on(day: date) -> Decimal | None:
        found = [v for d, v in parsed if d <= day]
        return found[-1] if found else None

    return value_on


def test_value_converts_usd_at_the_month_rate() -> None:
    # Arrange
    usd = Holding("visa", "cards", "USD", "debt", _steps(("2026-01-10", "100")))
    # Act
    found = net_worth.value_dop(usd, date(2026, 2, 28), RATES)
    # Assert: February has no rate, so January's (60) applies
    assert found == Decimal("6000")


def test_value_is_none_without_a_rate_for_usd() -> None:
    usd = Holding("visa", "cards", "USD", "debt", _steps(("2025-01-10", "100")))
    assert net_worth.value_dop(usd, date(2025, 2, 28), RATES) is None


def test_history_starts_when_every_holding_is_known() -> None:
    # Arrange: the bank is known from January, the card only from February
    holdings = [
        Holding(
            "bank", "banks", "DOP", "asset", _steps(("2026-01-05", "1000"), ("2026-02-05", "1500"))
        ),
        Holding("card", "cards", "DOP", "debt", _steps(("2026-02-10", "400"))),
    ]
    # Act
    points = net_worth.history(holdings, RATES, date(2026, 3, 15))
    # Assert: January is incomplete and is left out; March ends today
    assert [p.month for p in points] == ["2026-02", "2026-03"]
    assert points[0].day == date(2026, 2, 28)
    assert points[-1].day == date(2026, 3, 15)
    assert points[0].assets == Decimal("1500")
    assert points[0].debts == Decimal("400")
    assert points[0].net == Decimal("1100")


def test_history_ignores_holdings_without_history() -> None:
    # Arrange: what others owe is only known today; it stays out of the history
    holdings = [
        Holding("bank", "banks", "DOP", "asset", _steps(("2026-01-05", "1000"))),
        Holding("owed", "owed", "DOP", "asset", lambda _day: Decimal("200"), historic=False),
    ]
    # Act
    points = net_worth.history(holdings, RATES, date(2026, 2, 10))
    # Assert
    assert [p.net for p in points] == [Decimal("1000"), Decimal("1000")]


def test_history_is_empty_without_holdings() -> None:
    assert net_worth.history([], RATES, date(2026, 2, 10)) == []


def test_month_change_compares_with_the_end_of_last_month() -> None:
    # Arrange
    steps = _steps(("2026-01-05", "1000"), ("2026-03-05", "1300"))
    bank = Holding("bank", "banks", "DOP", "asset", steps)
    # Act
    found = net_worth.month_change(bank, date(2026, 3, 15), RATES)
    # Assert
    assert found == Decimal("300")


def test_month_change_is_none_when_last_month_is_unknown() -> None:
    card = Holding("card", "cards", "DOP", "debt", _steps(("2026-03-05", "400")))
    assert net_worth.month_change(card, date(2026, 3, 15), RATES) is None


def test_totals_by_group_and_side() -> None:
    # Arrange
    holdings = [
        Holding("bank", "banks", "DOP", "asset", _steps(("2026-01-05", "1000"))),
        Holding("cash", "cash", "USD", "asset", _steps(("2026-01-05", "10"))),
        Holding("card", "cards", "DOP", "debt", _steps(("2026-01-05", "300"))),
        Holding("loan", "loans", "DOP", "debt", _steps(("2026-01-05", "200"))),
    ]
    # Act
    found = net_worth.totals(holdings, date(2026, 3, 15), RATES)
    # Assert: US$ at March's rate (62)
    assert found.assets == Decimal("1620")
    assert found.debts == Decimal("500")
    assert found.net == Decimal("1120")
    assert found.groups == {
        "banks": Decimal("1000"),
        "cash": Decimal("620"),
        "cards": Decimal("300"),
        "loans": Decimal("200"),
    }
    assert found.unconverted is False


def test_totals_flag_a_value_without_rate() -> None:
    holdings = [Holding("cash", "cash", "USD", "asset", _steps(("2024-01-05", "10")))]
    found = net_worth.totals(holdings, date(2024, 3, 15), {})
    assert found.unconverted is True
    assert found.net == Decimal("0")


def test_history_starts_at_the_latest_first_known_day() -> None:
    # Arrange: holdings that say from when they are known skip the months before
    bank = Holding("bank", "banks", "DOP", "asset", _steps(("2026-02-05", "10")))
    known = Holding("bank", "banks", "DOP", "asset", bank.value_on, known_from=date(2026, 2, 5))
    # Act
    points = net_worth.history([known], RATES, date(2026, 3, 15))
    # Assert
    assert [p.month for p in points] == ["2026-02", "2026-03"]
