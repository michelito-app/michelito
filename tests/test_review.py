"""«Para revisar»: reglas sobre movimientos inventados."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from finanzas.analysis import categories as cat
from finanzas.analysis import review
from finanzas.analysis.rates import Rate
from finanzas.analysis.spending import Movement
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


# Un movimiento viejo para que haya historia (las contrapartes nuevas lo necesitan).
OLD = move("2026-01-02", "100", merchant="COLMADO VIEJO")


class TestUnusualIncome:
    def test_large_income_from_a_new_counterpart(self):
        found = detect([OLD, move("2026-05-10", "-20000", cat.OTHER_INCOME, "CLIENTE NUEVO")])
        assert kinds(found) == [("ingreso_inusual", "CLIENTE NUEVO")]
        assert found[0].amount == Decimal(20000) and found[0].amount_dop == Decimal(20000)
        assert "contraparte nueva" in found[0].reason
        # OLD es del 2 de enero: hay 128 días de historia, no un año.
        assert "en los últimos 128 días" in found[0].reason

    def test_with_a_full_year_of_history_the_reason_says_so(self):
        old = move("2025-01-02", "100", merchant="COLMADO VIEJO")
        [found] = detect([old, move("2026-05-10", "-20000", cat.OTHER_INCOME, "CLIENTE NUEVO")])
        assert "en el último año" in found.reason

    def test_known_counterpart_small_amount_or_no_history_are_not_flagged(self):
        known = [OLD, move("2026-02-10", "-15000", cat.SALARY, "NOMINA")]
        assert detect([*known, move("2026-05-10", "-20000", cat.SALARY, "NOMINA")]) == []
        assert detect([OLD, move("2026-05-10", "-9999", cat.OTHER_INCOME, "CLIENTE")]) == []
        # Sin 60 días de datos antes, todo parecería nuevo.
        assert detect([move("2026-05-10", "-20000", cat.OTHER_INCOME, "CLIENTE")]) == []

    def test_counterpart_seen_over_a_year_ago_is_new_again(self):
        old = move("2025-04-01", "-15000", cat.OTHER_INCOME, "CLIENTE")
        found = detect([old, move("2026-05-10", "-20000", cat.OTHER_INCOME, "CLIENTE")])
        assert kinds(found) == [("ingreso_inusual", "CLIENTE")]


class TestLargeThirdParty:
    def test_from_threshold_up(self):
        bank = "demo:checking:1"
        items = [
            move("2026-05-03", "25000", cat.THIRD_PARTY, "MB A PERSONA", bank),
            move("2026-05-04", "24999", cat.THIRD_PARTY, "MB A OTRA", bank),
            move("2026-04-30", "90000", cat.THIRD_PARTY, "MB A ABRIL", bank),
        ]
        assert kinds(detect(items)) == [("tercero_grande", "MB A PERSONA")]

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
            move("2026-05-22", "500", merchant="CINE"),  # dos días: no
            move("2026-05-25", "300", merchant="BUS"),
            move("2026-05-25", "300", merchant="BUS", account="otra:credit_card"),  # otra cuenta
        ]
        found = detect(items)
        assert kinds(found) == [("duplicado", "PIZZA"), ("duplicado", "CAFE")]
        assert found[0].fingerprint == "PIZZA-2026-05-11-800-0"
        assert "el día anterior" in found[0].reason
        assert "el mismo día" in found[1].reason

    def test_first_charge_in_the_previous_month(self):
        items = [
            move("2026-04-30", "700", merchant="BAR"),
            move("2026-05-01", "700", merchant="BAR"),
        ]
        assert kinds(detect(items)) == [("duplicado", "BAR")]
        assert review.detect(items, "2026-04", rate_for_month=no_rate) == []

    def test_a_daily_toll_is_not_a_duplicate(self):
        """Peaje diario de RD$ 100: se repite (y al día siguiente, menos de RD$ 500 no cuenta)."""
        tolls = [move(f"2026-05-{d:02d}", "100", merchant="PEAJE") for d in range(1, 21)]
        same_day = move("2026-05-20", "100", merchant="PEAJE", seq=1)  # dos pasadas el mismo día
        assert detect([*tolls, same_day]) == []

    def test_a_charge_that_already_recurs_is_skipped_even_when_large(self):
        """Tres cobros iguales en los 60 días anteriores: es un cargo que se repite."""
        usual = [move(f"2026-04-{d:02d}", "900", merchant="PARQUEO") for d in (1, 8, 15)]
        pair = [
            move("2026-05-03", "900", merchant="PARQUEO", seq=1),
            move("2026-05-03", "900", merchant="PARQUEO", seq=2),
        ]
        assert detect([*usual, *pair]) == []
        # Con solo dos antes, el doble cobro sí sale.
        assert kinds(detect([*usual[1:], *pair])) == [("duplicado", "PARQUEO")]

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
        assert kinds(detect(same_day)) == [("duplicado", "KIOSKO")]

    def test_a_real_double_charge_is_flagged(self):
        history = [move("2026-03-15", "4500", merchant="TIENDA X")]
        double = [
            move("2026-05-20", "4500", merchant="TIENDA X"),
            move("2026-05-21", "4500", merchant="TIENDA X"),
        ]
        assert kinds(detect([*history, *double])) == [("duplicado", "TIENDA X")]


class TestOneOffsAndPriceUps:
    def _big(self):
        return move("2026-05-08", "45000", cat.TRAVEL, "AGENCIA FICTICIA")

    def test_one_off_suggestions_are_one_kind(self):
        [found] = detect([self._big()])
        assert found.kind == "unico" and "categoría poco usada" in found.reason
        assert found.reviewed is False

    def test_dismissed_one_off_is_reviewed_not_gone(self):
        big = self._big()
        [found] = detect([big], dismissed={big.fingerprint})
        assert (found.kind, found.reviewed) == ("unico", True)

    def test_price_ups_come_from_recurring_alerts(self):
        charge = move("2026-05-05", "1199", cat.SUBSCRIPTIONS, "STREAMING")
        found = detect([charge], price_ups={charge.fingerprint: "Subió de RD$ 999 a RD$ 1,199"})
        assert kinds(found) == [("subio", "STREAMING")]
        assert found[0].reason == "Subió de RD$ 999 a RD$ 1,199"


def test_history_keeps_dismissed_one_offs_beyond_the_cap_of_five():
    """Seis compras raras: la más chica (descartada) no se pierde por el tope de 5."""
    buys = [
        move("2026-05-08", f"{amount}000", f"Categoria {amount}", f"COMERCIO {amount}")
        for amount in (20, 30, 40, 50, 60, 70)
    ]
    smallest = buys[0]
    found = detect(buys, dismissed={smallest.fingerprint})
    unicos = [(i.merchant, i.reviewed) for i in found if i.kind == "unico"]
    assert len(unicos) == 6
    assert ("COMERCIO 20", True) in unicos
    assert sum(1 for _, reviewed in unicos if not reviewed) == 5


def test_reviewed_marks_are_per_kind_and_order_is_newest_first():
    items = [
        move("2026-05-03", "1200", merchant="CAFE", seq=1),
        move("2026-05-03", "1200", merchant="CAFE", seq=2),
        move("2026-05-10", "30000", cat.THIRD_PARTY, "MB A PERSONA", "b"),
    ]
    found = detect(items, reviewed={("CAFE-2026-05-03-1200-2", "duplicado")})
    assert [(i.kind, i.reviewed) for i in found] == [
        ("tercero_grande", False),
        ("duplicado", True),
    ]
    # La misma huella con otro tipo no cuenta como revisada.
    again = detect(items, reviewed={("CAFE-2026-05-03-1200-2", "tercero_grande")})
    assert [i.reviewed for i in again] == [False, False]
