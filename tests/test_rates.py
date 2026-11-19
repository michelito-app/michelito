from decimal import Decimal

import pytest

from michelito import db
from michelito.analysis import rates
from michelito.analysis.rates import Rate


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def test_rate_falls_back_to_previous_month(conn):
    rates.store_bcrd(conn, {"2026-08": Decimal("63.10")})
    stored = rates.load(conn)

    assert rates.rate_for(stored, "2026-09") == Rate(Decimal("63.10"), "2026-08", "bcrd")
    assert rates.rate_for(stored, "2026-07") is None


def test_exact_month_wins_over_earlier_one(conn):
    rates.store_bcrd(conn, {"2026-08": Decimal("63.10"), "2026-09": Decimal("63.40")})

    assert rates.rate_for(rates.load(conn), "2026-09") == Rate(Decimal("63.40"), "2026-09", "bcrd")


def test_manual_rate_survives_bcrd_import(conn):
    rates.set_manual(conn, "2026-09", Decimal("64"))

    saved = rates.store_bcrd(conn, {"2026-09": Decimal("63.4"), "2026-10": Decimal("63.9")})

    stored = rates.load(conn)
    assert saved == 1
    assert stored["2026-09"] == Rate(Decimal("64"), "2026-09", "manual")
    assert stored["2026-10"].source == "bcrd"


def test_bcrd_import_refreshes_bcrd_months(conn):
    rates.store_bcrd(conn, {"2026-09": Decimal("63.4")})

    assert rates.store_bcrd(conn, {"2026-09": Decimal("63.5")}) == 1
    assert rates.load(conn)["2026-09"].value == Decimal("63.5")


def test_manual_overrides_bcrd_month(conn):
    rates.store_bcrd(conn, {"2026-09": Decimal("63.4")})
    rates.set_manual(conn, "2026-09", Decimal("64"))

    assert rates.load(conn)["2026-09"] == Rate(Decimal("64"), "2026-09", "manual")


def test_rate_is_stored_as_text_with_four_decimals(conn):
    rates.set_manual(conn, "2026-09", Decimal("64"))

    row = conn.execute("SELECT dop_per_usd FROM exchange_rates").fetchone()
    assert row[0] == "64.0000"


def test_to_dop():
    rate = Rate(Decimal("63.40"), "2026-09", "bcrd")

    assert rates.to_dop(Decimal("11.99"), "USD", rate) == Decimal("760.166")
    assert rates.to_dop(Decimal(5), "USD", None) is None
    assert rates.to_dop(Decimal(5), "DOP", None) == Decimal(5)
    assert rates.to_dop(Decimal(5), "DOP", rate) == Decimal(5)
