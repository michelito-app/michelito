from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from finanzas import db
from finanzas.analysis import categories as cat
from finanzas.analysis import one_off_dismissals as dismissals
from finanzas.analysis import one_offs
from finanzas.analysis.rates import Rate
from finanzas.analysis.recurring_marks import Mark
from finanzas.analysis.spending import Movement
from tests.test_spending import movement as _movement

MONTH = "2026-05"
RATE = Rate(Decimal("60"), "2026-05", "manual")


def movement(
    day: str,
    amount: str,
    category: str = cat.HOME,
    merchant: str = "TIENDA INVENTADA",
    currency: str = "DOP",
    description: str | None = None,
    **changes: object,
) -> Movement:
    base = _movement(day, amount, category, merchant, currency)
    return replace(
        base,
        fingerprint=f"{merchant}-{day}-{amount}",
        description=description or merchant,
        account="demo:credit_card",
        **changes,
    )


def history(category: str = cat.HOME, amount: str = "3000", count: int = 4) -> list[Movement]:
    """Compras normales de la categoría en meses anteriores, en comercios distintos."""
    return [
        movement(f"2026-0{m}-10", amount, category, merchant=f"COMERCIO {m}")
        for m in range(1, count + 1)
    ]


def no_rate(_month: str) -> Rate | None:
    return None


def fixed_rate(_month: str) -> Rate | None:
    return RATE


def suggest(movements, month=MONTH, rate_for_month=no_rate, dismissed=frozenset()):
    return one_offs.suggest(movements, month, rate_for_month=rate_for_month, dismissed=dismissed)


def test_big_purchase_in_a_new_merchant_is_suggested() -> None:
    big = movement("2026-05-12", "30000", merchant="MUEBLERIA INVENTADA")
    [found] = suggest([*history(), big])
    assert found.fingerprint == big.fingerprint
    assert (found.day, found.merchant, found.amount, found.amount_dop) == (
        big.day,
        "MUEBLERIA INVENTADA",
        Decimal("30000"),
        Decimal("30000"),
    )
    assert found.reasons == ("10.0 veces tu compra típica en Hogar y electrónica", "comercio nuevo")
    assert found.score == Decimal(10)


def test_small_purchases_are_not_suggested() -> None:
    small = movement("2026-05-12", "9999.99", merchant="MUEBLERIA INVENTADA")
    assert suggest([*history(amount="500"), small]) == []


def test_usd_converted_with_the_month_rate() -> None:
    big = movement("2026-05-12", "200", merchant="TIENDA USD", currency="USD")
    assert suggest([*history(), big]) == []  # sin tasa no se puede comparar en RD$
    [found] = suggest([*history(), big], rate_for_month=fixed_rate)
    assert found.amount_dop == Decimal("12000")
    assert found.currency == "USD"


def test_purchase_close_to_the_category_median_is_not_suggested() -> None:
    usual = movement("2026-05-12", "20000", merchant="MUEBLERIA INVENTADA")
    assert suggest([*history(amount="8000"), usual]) == []


def test_few_category_items_make_the_category_unusual() -> None:
    big = movement("2026-05-12", "15000", cat.TRAVEL, merchant="AGENCIA INVENTADA")
    [found] = suggest([*history(cat.TRAVEL, count=2), big])
    assert found.reasons == ("categoría poco usada", "comercio nuevo")
    assert found.score == Decimal("1.5")  # monto / MIN_AMOUNT_DOP: comparable con las razones


def test_frequent_merchant_needs_to_triple_its_median() -> None:
    regular = [
        movement(day, "5000", merchant="FERRETERIA FIJA")
        for day in ("2026-01-03", "2026-01-20", "2026-03-15")
    ]
    usual = movement("2026-05-12", "14000", merchant="FERRETERIA FIJA")
    assert suggest([*history(amount="1000"), *regular, usual]) == []
    big = movement("2026-05-12", "16000", merchant="FERRETERIA FIJA")
    [found] = suggest([*history(amount="1000"), *regular, big])
    assert "3.2 veces lo usual en FERRETERIA FIJA" in found.reasons


def test_merchant_seen_once_still_counts_as_new() -> None:
    once = movement("2026-02-03", "11000", merchant="MUEBLERIA INVENTADA")
    big = movement("2026-05-12", "30000", merchant="MUEBLERIA INVENTADA")
    [found] = suggest([*history(), once, big])
    assert found.fingerprint == big.fingerprint
    assert "comercio poco frecuente" in found.reasons


def test_history_only_looks_back_one_year() -> None:
    old = [movement(f"2025-0{m}-10", "30000", merchant="MUEBLERIA INVENTADA") for m in (1, 2, 3)]
    big = movement("2026-05-12", "30000", merchant="MUEBLERIA INVENTADA")
    assert len(suggest([*old, *history(), big])) == 1


def test_one_offs_dismissed_credits_and_non_expenses_are_skipped() -> None:
    base = movement("2026-05-12", "30000", merchant="MUEBLERIA INVENTADA")
    assert suggest([*history(), replace(base, one_off=True)]) == []
    assert suggest([*history(), base], dismissed=frozenset({base.fingerprint})) == []
    assert suggest([*history(), replace(base, amount=Decimal("-30000"))]) == []
    income = replace(base, category=cat.OTHER_INCOME)
    assert suggest([*history(), income]) == []
    transfer = replace(base, category=cat.OWN_TRANSFER)
    assert suggest([*history(), transfer]) == []


def test_third_party_transfers_and_loan_payments_are_not_suggested() -> None:
    sent = movement("2026-05-12", "30000", cat.THIRD_PARTY, merchant="MB A")
    assert suggest([*history(), sent]) == []
    # Un pago de préstamo es gasto, pero grande y raro por naturaleza: nunca es "único".
    loan = movement("2026-05-12", "30000", cat.LOANS, merchant="AUT PAGO")
    assert suggest([*history(cat.LOANS), loan]) == []
    assert suggest([loan]) == []


def test_bank_insurer_reimbursement_is_not_suggested() -> None:
    refund = movement("2026-05-12", "-30000", cat.HEALTH, merchant="REEMBOLSO MAPFRE")
    assert suggest([*history(cat.HEALTH), refund]) == []


def test_marked_one_offs_do_not_count_as_history() -> None:
    marked = [
        movement(f"2026-0{m}-10", "30000", merchant=f"OTRO {m}", one_off=True) for m in (1, 2, 3)
    ]
    big = movement("2026-05-12", "30000", merchant="MUEBLERIA INVENTADA")
    [found] = suggest([*history(), *marked, big])
    assert found.reasons[0] == "10.0 veces tu compra típica en Hogar y electrónica"


def test_recurring_charges_are_not_suggested() -> None:
    # Anual: sin la regla de recurrentes, la categoría y el comercio casi no tienen historia.
    yearly = [
        movement(day, "40000", cat.INSURANCE, merchant="SEGURO INVENTADO")
        for day in ("2025-05-15", "2026-05-12")
    ]
    assert suggest(yearly) == []
    assert len(suggest(yearly[1:])) == 1


@pytest.mark.parametrize(
    "description",
    [
        "TIENDA INVENTADA CUOTA 3",
        "TIENDA INVENTADA 03/12",
        "CUOTAS TIENDA INVENTADA",
        "TIENDA INVENTADA CUOTA 2",
        "TIENDA INVENTADA 3 / 6",
    ],
)
def test_installments_are_not_suggested(description: str) -> None:
    big = movement("2026-05-12", "30000", merchant="MUEBLERIA", description=description)
    assert suggest([*history(), big]) == []


@pytest.mark.parametrize(
    "description", ["FARMACIA 24/7", "COMPRA 12/05 AMAZON", "KM 10/5", "TIENDA 1/1", "TIENDA 5/99"]
)
def test_slashes_that_are_not_installments(description: str) -> None:
    assert one_offs.is_installment(description) is False


@pytest.mark.parametrize("description", ["03/12", "CUOTA 2", "TIENDA 12/12", "TIENDA 1/60"])
def test_installment_patterns(description: str) -> None:
    assert one_offs.is_installment(description) is True


def test_ratio_outranks_a_rare_category() -> None:
    usual = history(amount="1000")
    ratio = movement("2026-05-12", "40000", merchant="MUEBLERIA INVENTADA")  # 40 veces
    rare = movement("2026-05-13", "15000", cat.TRAVEL, merchant="AGENCIA INVENTADA")
    found = suggest([*usual, ratio, rare])
    assert [f.merchant for f in found] == ["MUEBLERIA INVENTADA", "AGENCIA INVENTADA"]


YEARLY = ("2025-05-15", "2026-05-12")


def yearly_fee() -> list[Movement]:
    return [movement(day, "40000", cat.INSURANCE, merchant="SEGURO INVENTADO") for day in YEARLY]


@pytest.mark.parametrize(
    "mark",
    [
        Mark("confirmed", None, None, None),
        Mark("cancelled", None, None, None),
        Mark(None, 6, None, None),
    ],
)
def test_recurring_marks_exclude_the_merchant(mark: Mark) -> None:
    single = yearly_fee()[1:]  # un solo cobro: detect() no lo ve recurrente
    assert len(suggest(single)) == 1
    marks = {("SEGURO INVENTADO", "DOP"): mark}
    assert one_offs.suggest(single, MONTH, rate_for_month=no_rate, dismissed=(), marks=marks) == []
    other_currency = {("SEGURO INVENTADO", "USD"): mark}
    assert (
        len(
            one_offs.suggest(
                single, MONTH, rate_for_month=no_rate, dismissed=(), marks=other_currency
            )
        )
        == 1
    )


def test_not_recurring_mark_overrides_detection() -> None:
    assert suggest(yearly_fee()) == []
    marks = {("SEGURO INVENTADO", "DOP"): Mark("dismissed", None, None, None)}
    found = one_offs.suggest(yearly_fee(), MONTH, rate_for_month=no_rate, dismissed=(), marks=marks)
    assert [f.merchant for f in found] == ["SEGURO INVENTADO"]


def test_only_the_month_is_suggested_ordered_by_score_and_capped() -> None:
    unused = (cat.TRAVEL, cat.EDUCATION, cat.HEALTH, cat.PETS, cat.INSURANCE, cat.PROFESSIONAL)
    bigs = [
        movement(f"2026-05-{10 + i:02d}", str(12000 + 1000 * i), category, f"NUEVO {i}")
        for i, category in enumerate((*unused, cat.GOVERNMENT))
    ]
    other_month = movement("2026-04-20", "90000", cat.OTHER, merchant="NUEVO ABRIL")
    found = suggest([*history(), *bigs, other_month])
    assert len(found) == one_offs.MAX_PER_MONTH
    assert [f.merchant for f in found] == ["NUEVO 6", "NUEVO 5", "NUEVO 4", "NUEVO 3", "NUEVO 2"]


def test_dismissals_round_trip() -> None:
    conn = db.connect(":memory:")
    try:
        assert dismissals.load(conn) == frozenset()
        dismissals.set_dismissed(conn, "abc", True)
        dismissals.set_dismissed(conn, "abc", True)  # idempotente
        assert dismissals.load(conn) == frozenset({"abc"})
        dismissals.set_dismissed(conn, "abc", False)
        assert dismissals.load(conn) == frozenset()
    finally:
        conn.close()


def test_bank_counterpart_history_is_its_own():
    # Antes todo "MB a …" era el comercio "MB A": un envío grande a alguien nuevo parecía
    # frecuente por los envíos a otras personas. Ahora cada contraparte tiene su historia.
    from finanzas.analysis import corrections, spending
    from tests.test_spending import _add_bank_rows, seed

    conn = db.connect(":memory:")
    seed(conn)
    regular = [
        (f"2026-0{m}-05", "MB a 0123456789 JUAN PEREZ", "debit", "300000") for m in (1, 2, 3, 4)
    ]
    _add_bank_rows(
        conn, [*regular, ("2026-05-10", "MB a 0999999999 MARIA GOMEZ", "debit", "6000000")]
    )
    with conn:
        corrections.set_merchant_category(conn, "MB A 0123456789", cat.HOME)
        corrections.set_merchant_category(conn, "MB A 0999999999", cat.HOME)
    found = suggest(spending.load_all(conn))
    assert [(s.merchant, s.reasons[-1]) for s in found] == [("MB A 0999999999", "comercio nuevo")]
    conn.close()
