"""Meses atípicos y "Qué pasó" (datos inventados)."""

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzas.analysis import anomalies
from finanzas.analysis.accounts import AccountInfo
from finanzas.web import summary
from finanzas.web.schemas import SummaryOut
from tests.test_spending import movement as _movement


def move(day, amount, merchant="COLMADO INVENTADO", category="Supermercado", account="A"):
    return replace(
        _movement(day, amount, category, merchant=merchant),
        account=account,
        fingerprint=f"{day}-{merchant}-{amount}",
    )


def entry(day, amount, merchant="COLMADO INVENTADO"):
    item = move(day, amount, merchant)
    return anomalies.Entry(item, Decimal(amount))


class TestDeviation:
    @pytest.mark.parametrize(
        ("value", "habitual", "expected"),
        [
            (130_000, 100_000, None),  # 30 % justo: no es atípico
            (130_001, 100_000, "up"),
            (69_999, 100_000, "down"),
            (19_000, 10_000, None),  # +90 % pero menos de RD$ 10,000
            (20_001, 10_000, "up"),
            (0, 10_001, "down"),
        ],
    )
    def test_threshold_is_max_of_share_and_floor(self, value, habitual, expected):
        assert anomalies.deviation(Decimal(value), Decimal(habitual)) == expected

    def test_custom_floor_for_categories(self):
        assert anomalies.deviation(Decimal(1500), Decimal(400), floor=Decimal(1000)) == "up"
        assert anomalies.deviation(Decimal(1300), Decimal(400), floor=Decimal(1000)) is None


class TestHabitual:
    def test_median_needs_three_months(self):
        assert anomalies.habitual([Decimal(1), Decimal(2)]) is None
        assert anomalies.habitual([Decimal(1), Decimal(9), Decimal(2)]) == Decimal(2)


class TestContributions:
    BASE = ("2026-01", "2026-02", "2026-03")

    def _baseline(self):
        return {
            month: [entry(f"{month}-05", "5000"), entry(f"{month}-09", "2000", "FARMACIA FICTICIA")]
            for month in self.BASE
        }

    def test_up_ranks_merchants_by_excess_and_links_the_biggest_movement(self):
        current = [
            entry("2026-04-05", "5000"),
            entry("2026-04-09", "2500", "FARMACIA FICTICIA"),
            entry("2026-04-10", "30000", "AGENCIA FICTICIA"),
            entry("2026-04-20", "12000", "AGENCIA FICTICIA"),
            entry("2026-04-21", "9000", "TIENDA INVENTADA"),
        ]
        found = anomalies.contributions(current, self._baseline(), "up", "gasto")
        assert [(c.merchant, c.diff) for c in found] == [
            ("AGENCIA FICTICIA", Decimal(42000)),
            ("TIENDA INVENTADA", Decimal(9000)),
            ("FARMACIA FICTICIA", Decimal(500)),
        ]
        top = found[0]
        assert top.fingerprint == "2026-04-10-AGENCIA FICTICIA-30000"
        assert (top.amount, top.habitual, top.count, top.side) == (
            Decimal(42000),
            Decimal(0),
            2,
            "gasto",
        )
        assert top.day == date(2026, 4, 10)

    def test_down_lists_what_did_not_come_even_without_a_movement(self):
        current = [entry("2026-04-09", "2000", "FARMACIA FICTICIA")]
        [missing] = anomalies.contributions(current, self._baseline(), "down", "ingreso")
        assert (missing.merchant, missing.diff, missing.amount) == (
            "COLMADO INVENTADO",
            Decimal(-5000),
            Decimal(0),
        )
        assert missing.fingerprint == "" and missing.day is None and missing.count == 0

    def test_limit_and_tie_break_by_name(self):
        current = [entry("2026-04-01", "100", name) for name in ("D", "C", "B", "A")]
        found = anomalies.contributions(current, {}, "up", "gasto")
        assert [c.merchant for c in found] == ["A", "B", "C"]


def card(key, through):
    return AccountInfo(key, "credit_card", f"Tarjeta {key}", date.fromisoformat(through))


def bank(key, through):
    return AccountInfo(key, "checking", f"Cuenta {key}", date.fromisoformat(through))


def _history(spent_last="10000"):
    """Seis meses de RD$ 10,000 de gasto y RD$ 50,000 de nómina; el último cambia."""
    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    moves = []
    for month in months[:-1]:
        moves.append(move(f"{month}-05", "10000"))
        moves.append(move(f"{month}-15", "-50000", "NOMINA INVENTADA", "Salario", "BANK"))
    moves.append(move("2026-07-05", spent_last))
    moves.append(move("2026-07-06", "30000", "AGENCIA FICTICIA", "Viajes"))
    return moves


ACCOUNTS = [card("A", "2026-07-31"), bank("BANK", "2026-07-31")]


class TestSummaryFlags:
    def test_trend_marks_atypical_months_against_previous_complete_months(self):
        result = summary.build_summary(_history(), ACCOUNTS, {}, "2026-07")
        july = result.trend[-1]
        assert july.month == "2026-07"
        assert (july.spent_flag, july.spent_habitual) == ("up", Decimal(10000))
        # La nómina no llegó en julio: ingreso atípico a la baja.
        assert (july.income_flag, july.income_habitual) == ("down", Decimal(50000))
        # Con menos de tres meses anteriores no se marca nada.
        assert [t.spent_flag for t in result.trend[:3]] == [None, None, None]
        assert result.trend[3].spent_flag is None  # abril: igual que lo habitual

    def test_what_happened_explains_both_sides(self):
        result = summary.build_summary(_history(), ACCOUNTS, {}, "2026-07")
        sides = [(c.side, c.merchant, c.diff) for c in result.what_happened]
        assert sides == [
            ("gasto", "AGENCIA FICTICIA", Decimal(30000)),
            ("ingreso", "NOMINA INVENTADA", Decimal(-50000)),
        ]
        assert result.what_happened[0].category == "Viajes"

    def test_normal_month_has_nothing_to_explain(self):
        moves = [m for m in _history() if m.merchant != "AGENCIA FICTICIA"]
        moves.append(move("2026-07-15", "-50000", "NOMINA INVENTADA", "Salario", "BANK"))
        result = summary.build_summary(moves, ACCOUNTS, {}, "2026-07")
        assert result.trend[-1].spent_flag is None and result.trend[-1].income_flag is None
        assert result.what_happened == []

    def test_partial_month_is_never_flagged(self):
        accounts = [card("A", "2026-07-20"), bank("BANK", "2026-07-31")]
        result = summary.build_summary(_history(), accounts, {}, "2026-07")
        assert result.trend[-1].partial and result.trend[-1].spent_flag is None
        assert result.what_happened == []

    def test_income_cut_by_the_bank_is_not_flagged(self):
        accounts = [card("A", "2026-07-31"), bank("BANK", "2026-07-10")]
        result = summary.build_summary(_history(), accounts, {}, "2026-07")
        assert result.trend[-1].income_flag is None
        assert result.trend[-1].spent_flag == "up"

    def test_honors_the_account_filter(self):
        result = summary.build_summary(_history(), ACCOUNTS, {}, "2026-07", ["BANK"])
        assert result.trend[-1].spent_flag is None
        assert [c.side for c in result.what_happened] == ["ingreso"]


def test_api_shape_of_flags_and_what_happened():
    body = SummaryOut.of(summary.build_summary(_history(), ACCOUNTS, {}, "2026-07")).model_dump()
    july = body["trend"][-1]
    assert (july["spent_flag"], july["spent_habitual_cents"]) == ("up", 1_000_000)
    assert (july["income_flag"], july["income_habitual_cents"]) == ("down", 5_000_000)
    assert body["trend"][0]["spent_habitual_cents"] is None
    first = body["what_happened"][0]
    assert first == {
        "side": "gasto",
        "merchant": "AGENCIA FICTICIA",
        "category": "Viajes",
        "amount_cents": 3_000_000,
        "habitual_cents": 0,
        "diff_cents": 3_000_000,
        "count": 1,
        "fingerprint": "2026-07-06-AGENCIA FICTICIA-30000",
        "day": "2026-07-06",
        "description": "AGENCIA FICTICIA",
    }
    assert body["what_happened"][1]["day"] is None


def test_los_umbrales_de_la_interfaz_son_los_del_servidor():
    # La leyenda del gráfico del Resumen repite los umbrales: no deben separarse.
    source = (Path(__file__).parents[1] / "frontend" / "src" / "lib" / "anomalies.ts").read_text(
        encoding="utf-8"
    )
    share = re.search(r"ATYPICAL_SHARE = ([\d.]+)", source)
    floor = re.search(r"ATYPICAL_FLOOR_CENTS = ([\d_]+)", source)
    assert share and floor
    assert Decimal(share.group(1)) == anomalies.ANOMALY_SHARE
    assert Decimal(floor.group(1).replace("_", "")) / 100 == anomalies.ANOMALY_FLOOR
