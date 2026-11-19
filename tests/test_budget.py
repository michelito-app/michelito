"""Presupuesto por categoría (lógica pura de `analysis.budget`). Datos inventados."""

from decimal import Decimal as D

import pytest

from finanzas.analysis import budget
from finanzas.analysis.budget import Cap, Item

FOOD, FUN = 1, 2


def item(month: str, category: int, dop: str | None, **flags: bool) -> Item:
    fp = f"{month}-{category}-{dop}-{len(flags)}-{sorted(flags.items())}"
    return Item(fp, month, category, None if dop is None else D(dop), **flags)


@pytest.mark.parametrize(
    ("habitual", "cap"),
    [
        (None, None),
        (D(0), None),
        (D(120), D(500)),  # algo de gasto: al menos RD$ 500
        (D(16_249), D(16_000)),
        (D(16_250), D(16_500)),  # la mitad sube
        (D("24_810.40"), D(25_000)),
    ],
)
def test_round_cap_to_500(habitual: D | None, cap: D | None) -> None:
    assert budget.round_cap(habitual) == cap


def test_habitual_is_the_median_of_the_last_complete_months_without_one_offs() -> None:
    months = ["2025-09", "2025-10", "2025-11", "2025-12"]
    items = [
        item("2025-09", FOOD, "10000"),
        item("2025-10", FOOD, "12000"),
        item("2025-11", FOOD, "11000"),
        item("2025-12", FOOD, "30000", one_off=True),  # gasto único: fuera de lo habitual
        item("2025-12", FOOD, "9000"),
        item("2025-12", FOOD, "50000", reserved=True),  # cubierto por una reserva: fuera
        item("2025-10", FUN, "4000"),
        item("2025-10", FUN, None),  # US$ sin tasa: no suma
    ]
    usual = budget.habitual(items, months)
    assert usual[FOOD] == D(10_500)  # mediana de 10, 12, 11 y 9 mil
    assert usual[FUN] == D(0)  # mediana de 0, 4000, 0, 0
    assert budget.habitual(items, []) == {}
    assert budget.reference_months([f"2025-{m:02d}" for m in range(1, 13)]) == [
        f"2025-{m:02d}" for m in range(7, 13)
    ]


def test_initial_caps_start_at_the_rounded_habitual() -> None:
    caps = budget.initial_caps([FOOD, FUN, 3], {FOOD: D("16475"), FUN: D(0)})
    assert caps == [
        Cap(FOOD, D(16_500), False, D(16_500)),
        Cap(FUN, None, False, D(0)),  # sin gasto: «Sin presupuesto»
        Cap(3, None, False, D(0)),
    ]


def test_one_off_and_reserved_stay_out_of_the_cap_and_there_is_no_carry_over() -> None:
    caps = {FOOD: Cap(FOOD, D(10_000), False, D(10_000))}
    items = [
        item("2026-01", FOOD, "6000"),
        item("2026-01", FOOD, "2000"),
        item("2026-01", FOOD, "-500"),  # una devolución resta
        item("2026-01", FOOD, "45000", one_off=True),
        item("2026-01", FOOD, "8000", reserved=True),
        item("2026-01", FOOD, None),
        # Diciembre pasó del tope por mucho: enero empieza de cero (sin arrastre).
        item("2025-12", FOOD, "25000"),
    ]
    [line] = budget.lines(items, "2026-01", caps, {FOOD: D(10_000)}, [FOOD])
    assert (line.spent, line.one_offs, line.covered, line.without_rate) == (
        D(7_500),
        D(45_000),
        D(8_000),
        1,
    )
    assert line.over == 0
    [december] = budget.lines(items, "2025-12", caps, {FOOD: D(10_000)}, [FOOD])
    assert december.over == D(15_000)


def test_lines_are_sorted_by_excess_and_totals_count_the_passed() -> None:
    caps = {
        FOOD: Cap(FOOD, D(10_000), True, None),
        FUN: Cap(FUN, D(1_000), True, None),
        3: Cap(3, None, True, None),
    }
    items = [
        item("2026-01", FOOD, "12000"),
        item("2026-01", FUN, "4000"),
        item("2026-01", 3, "9000"),  # sin presupuesto: nunca pasa
        item("2026-01", 4, "100"),  # sin fila: se muestra igual
    ]
    found = budget.lines(items, "2026-01", caps, {}, [FOOD, FUN, 3, 5])
    assert [line.category_id for line in found][:2] == [FUN, FOOD]
    assert {line.category_id: line.active for line in found} == {
        FUN: True,
        FOOD: True,
        3: True,
        4: True,
        5: False,
    }
    totals = budget.totals(found)
    assert (totals.cap, totals.spent, totals.over_count, totals.over) == (
        D(11_000),
        D(16_000),
        2,
        D(5_000),
    )


def test_warning_only_on_untouched_caps_and_only_on_real_changes() -> None:
    auto = Cap(FOOD, D(20_000), False, D(20_000))
    assert budget.warning(auto, D(20_400)) is None  # RD$ 20,500: menos del 10 %
    assert budget.warning(auto, D(21_000)) is None  # +RD$ 1,000 es menos del 10 %
    rise = budget.warning(auto, D(25_100))
    assert rise is not None and (rise.habitual, rise.basis, rise.up) == (D(25_000), D(20_000), True)
    drop = budget.warning(auto, D(14_000))
    assert drop is not None and not drop.up
    assert budget.warning(Cap(FOOD, D(20_000), True, D(20_000)), D(40_000)) is None  # a mano
    # Sin presupuesto al activar (no había gasto) y ahora sí hay: avisa.
    empty = budget.warning(Cap(FUN, None, False, D(0)), D(3_000))
    assert empty is not None and empty.habitual == D(3_000)


def test_passed_only_beyond_the_margin_but_the_exact_difference_shows() -> None:
    caps = {
        FOOD: Cap(FOOD, D(25_000), True, None),  # pasa 4 %: un cambio de tasa
        FUN: Cap(FUN, D(5_000), True, None),  # pasa RD$ 400: menos de RD$ 500
        3: Cap(3, D(20_000), True, None),  # pasa 10 %: sí
    }
    items = [
        item("2026-01", FOOD, "26000"),
        item("2026-01", FUN, "5400"),
        item("2026-01", 3, "22000"),
    ]
    found = {line.category_id: line for line in budget.lines(items, "2026-01", caps, {}, [])}
    assert [found[c].over for c in (FOOD, FUN, 3)] == [D(1_000), D(400), D(2_000)]
    assert [found[c].passed for c in (FOOD, FUN, 3)] == [False, False, True]
    totals = budget.totals(found.values())
    assert (totals.over_count, totals.over) == (1, D(2_000))


def test_net_refunds_show_as_zero_spent_with_the_refund_aside() -> None:
    caps = {FOOD: Cap(FOOD, D(5_000), True, None)}
    items = [item("2026-01", FOOD, "2000"), item("2026-01", FOOD, "-12737")]
    [line] = budget.lines(items, "2026-01", caps, {}, [FOOD])
    assert (line.spent, line.refunds, line.over, line.passed) == (D(0), D(10_737), D(0), False)
    assert budget.totals([line]).spent == D(0)
