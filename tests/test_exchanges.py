"""Cambios de divisas: patas, tasa acordada o implícita, pendiente y sugerencias."""

from datetime import date
from decimal import Decimal

import pytest

from finanzas import db
from finanzas.analysis import catalog, exchanges, spending
from finanzas.analysis import categories as cat
from finanzas.analysis.links import Exchange, LinkError, Links, Shared
from finanzas.analysis.rates import Rate
from finanzas.analysis.spending import Movement

D = Decimal
BANKS = frozenset({"pesos", "dolares"})


def _leg(
    day: str,
    amount: str,
    currency: str,
    fp: str,
    account: str | None = None,
    category: str = cat.THIRD_PARTY,
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=fp,
        description=fp,
        category=category,
        amount=D(amount),
        currency=currency,
        institution="x",
        fingerprint=fp,
        account=account or ("pesos" if currency == "DOP" else "dolares"),
    )


def _by_fp(*moves: Movement) -> dict[str, Movement]:
    return {m.fingerprint: m for m in moves}


class TestLegs:
    def test_both_currencies_in_opposite_directions(self) -> None:
        sent = _leg("2026-02-01", "120000", "DOP", "a")
        back = _leg("2026-02-03", "-1500", "USD", "b")
        exchanges.check_legs([sent, back])
        with pytest.raises(LinkError):
            exchanges.check_legs([sent, _leg("2026-02-03", "3000", "USD", "c")])
        with pytest.raises(LinkError):
            exchanges.check_legs([sent, _leg("2026-02-02", "100", "DOP", "d")])
        with pytest.raises(LinkError):  # una moneda en las dos direcciones
            exchanges.check_legs([sent, back, _leg("2026-02-04", "-5", "DOP", "e")])


class TestState:
    def test_agreed_rate_and_pending(self) -> None:
        # Datos inventados: RD$ 120,000 por US$ 1,500 acordados a 62.50 (US$ 1,920).
        sent = _leg("2026-02-01", "120000", "DOP", "a")
        back = _leg("2026-02-03", "-1500", "USD", "b")
        state = exchanges.state(Exchange(1, ("a", "b"), D("62.50")), _by_fp(sent, back))
        assert state is not None
        assert (state.base, state.rate, state.implied_rate) == ("DOP", D("62.50"), D("80.0000"))
        assert (state.pending, state.pending_currency) == (D("420.00"), "USD")
        assert state.pending_dop == D("26250.00")
        assert state.month == "2026-02"

    def test_implied_rate_of_the_first_complete_pair_and_partial_pending(self) -> None:
        # RD$ 63,700 el 1 (dos depósitos el mismo día) por US$ 1,000 el 2: tasa 63.70. Luego
        # otro envío de RD$ 31,850 que todavía no vuelve: pendiente US$ 500.
        legs = (
            _leg("2026-02-01", "-60000", "DOP", "a"),
            _leg("2026-02-01", "-3700", "DOP", "b"),
            _leg("2026-02-02", "1000", "USD", "c"),
            _leg("2026-02-20", "-31850", "DOP", "d"),
        )
        state = exchanges.state(Exchange(1, ("a", "b", "c", "d")), _by_fp(*legs))
        assert state is not None
        assert state.rate == state.implied_rate == D("63.7000")
        assert (state.pending, state.pending_currency, state.pending_dop) == (
            D("500.00"),
            "USD",
            D("31850.00"),
        )

    def test_dollars_first_and_closing(self) -> None:
        sent = _leg("2026-02-01", "2000", "USD", "a")
        back = _leg("2026-02-02", "-100000", "DOP", "b")
        exchange = Exchange(1, ("a", "b"), D("60"))
        state = exchanges.state(exchange, _by_fp(sent, back))
        assert state is not None
        assert (state.base, state.pending, state.pending_currency) == ("USD", D(20000), "DOP")
        closed = exchanges.state(Exchange(1, ("a", "b"), D("60"), closed=True), _by_fp(sent, back))
        assert closed is not None and closed.pending == closed.pending_dop == 0

    def test_over_returned_is_not_pending_and_missing_legs_break_it(self) -> None:
        sent = _leg("2026-02-01", "60000", "DOP", "a")
        back = _leg("2026-02-02", "-1100", "USD", "b")
        state = exchanges.state(Exchange(1, ("a", "b"), D("60")), _by_fp(sent, back))
        assert state is not None and state.pending == 0
        assert exchanges.state(Exchange(1, ("a", "b")), _by_fp(sent)) is None


class TestLoad:
    def test_linked_legs_are_currency_exchange_not_income_or_third_party(self) -> None:
        known = catalog.load(db.connect(":memory:"))
        deposit = _leg("2026-02-12", "-63700", "DOP", "a", category=cat.OTHER_INCOME)
        sent = _leg("2026-02-13", "1000", "USD", "b", category=cat.THIRD_PARTY)
        other = _leg("2026-02-13", "500", "DOP", "c")
        found = Links(exchanges=(Exchange(1, ("a", "b")),))
        linked = spending.with_links([deposit, sent, other], found, known, BANKS)
        assert [(m.ref, m.kind, m.link) for m in linked] == [
            (cat.CURRENCY_EXCHANGE, "transferencia", "exchange"),
            (cat.CURRENCY_EXCHANGE, "transferencia", "exchange"),
            (cat.THIRD_PARTY, "transferencia", ""),
        ]
        assert [m.amount for m in linked] == [D(-63700), D(1000), D(500)]

    def test_card_legs_are_never_relabeled(self) -> None:
        known = catalog.load(db.connect(":memory:"))
        deposit = _leg("2026-02-12", "-63700", "DOP", "a", category=cat.OTHER_INCOME)
        card = _leg("2026-02-13", "1000", "USD", "b", account="tarjeta")
        found = Links(exchanges=(Exchange(1, ("a", "b")),))
        linked, untouched = spending.with_links([deposit, card], found, known, BANKS)
        assert untouched == card
        assert linked.link == "exchange"  # dormido: el cambio no cuadra, pero sigue enlazado

    def test_a_leg_of_an_exchange_missing_its_other_side_stays_linked(self) -> None:
        known = catalog.load(db.connect(":memory:"))
        deposit = _leg("2026-02-12", "-63700", "DOP", "a", category=cat.OTHER_INCOME)
        found = Links(exchanges=(Exchange(1, ("a", "gone")),))
        [linked] = spending.with_links([deposit], found, known, BANKS)
        assert (linked.ref, linked.kind) == (cat.CURRENCY_EXCHANGE, "transferencia")
        assert exchanges.states([linked], found) == {}


RATES = {"2026-02": Rate(D("63.70"), "2026-02", "bcrd")}


def _rate(month: str) -> Rate | None:
    return RATES.get(month)


class TestSuggestions:
    def test_a_big_movement_with_a_counterpart_at_the_official_rate(self) -> None:
        deposit = _leg("2026-02-12", "-63700", "DOP", "dep", category=cat.OTHER_INCOME)
        sent = _leg("2026-02-13", "1000", "USD", "usd")
        far = _leg("2026-03-20", "1000", "USD", "far")
        found = exchanges.suggestions([deposit, sent, far], Links(), BANKS, _rate)
        assert found == {"dep": "usd", "usd": "dep"}

    def test_thresholds(self) -> None:
        small = _leg("2026-02-12", "-19000", "DOP", "small", category=cat.OTHER_INCOME)
        tiny = _leg("2026-02-13", "298.27", "USD", "tiny")  # RD$ 19,000 a 63.70
        assert exchanges.suggestions([small, tiny], Links(), BANKS, _rate) == {}
        # Tasa fuera del ±5 % pero cubre más de la mitad: sí.
        deposit = _leg("2026-02-12", "-50000", "DOP", "dep", category=cat.OTHER_INCOME)
        cheap = _leg("2026-02-13", "600", "USD", "cheap")  # 83.3 por US$, RD$ 38,220
        assert exchanges.suggestions([deposit, cheap], Links(), BANKS, _rate) == {
            "dep": "cheap",
            "cheap": "dep",
        }
        # Ni tasa ni parte: no.
        crumbs = _leg("2026-02-13", "200", "USD", "crumbs")  # RD$ 12,740
        assert "dep" not in exchanges.suggestions([deposit, crumbs], Links(), BANKS, _rate)

    def test_excluded_movements_and_existing_links(self) -> None:
        sent = _leg("2026-02-13", "1000", "USD", "usd")
        salary = _leg("2026-02-12", "-63700", "DOP", "sal", category=cat.SALARY)
        own = _leg("2026-02-12", "-63700", "DOP", "own", category=cat.OWN_TRANSFER)
        assert exchanges.suggestions([sent, salary, own], Links(), BANKS, _rate) == {}
        deposit = _leg("2026-02-12", "-63700", "DOP", "dep", category=cat.OTHER_INCOME)
        busy = Links(shared=(Shared.one(1, "otra", people=2, reimbursements=("dep",)),))
        assert exchanges.suggestions([sent, deposit], busy, BANKS, _rate) == {}

    def test_same_direction_or_currency_is_not_an_exchange(self) -> None:
        deposit = _leg("2026-02-12", "-63700", "DOP", "dep", category=cat.OTHER_INCOME)
        received = _leg("2026-02-13", "-1000", "USD", "usd", category=cat.OTHER_INCOME)
        assert exchanges.suggestions([deposit, received], Links(), BANKS, _rate) == {}


class TestCandidates:
    def test_opposite_direction_other_currency_within_30_days(self) -> None:
        deposit = _leg("2026-02-12", "-63700", "DOP", "dep", category=cat.OTHER_INCOME)
        moves = [
            deposit,
            _leg("2026-03-14", "10", "USD", "late"),  # 30 días después: entra
            _leg("2026-03-15", "10", "USD", "too-late"),
            _leg("2026-02-01", "-10", "USD", "same-direction"),
            _leg("2026-02-01", "10", "DOP", "same-currency"),
            _leg("2026-02-01", "10", "USD", "card", account="tarjeta"),
            _leg("2026-02-01", "10", "USD", "pay", category=cat.CARD_PAYMENT),
            _leg("2026-02-02", "10", "USD", "near"),
        ]
        found = exchanges.candidates(deposit, moves, Links(), BANKS)
        assert [c.move.fingerprint for c in found] == ["near", "late"]
        assert not any(c.primary for c in found)  # sin tasa, todo tras «Ver más»

    def test_starting_an_exchange_ranks_by_the_gap_to_the_month_rate(self) -> None:
        # RD$ 63,700 recibidos; el mes está a 63.70. US$ 1,000 es la tasa exacta; US$ 980 está a
        # 2% (primaria); US$ 900 a ~11% (tras «Ver más») aunque sea del mismo día.
        deposit = _leg("2026-02-12", "-63700", "DOP", "dep", category=cat.OTHER_INCOME)
        moves = [
            deposit,
            _leg("2026-02-12", "900", "USD", "far-rate"),
            _leg("2026-02-20", "980", "USD", "close"),
            _leg("2026-02-25", "1000", "USD", "exact"),
        ]
        found = exchanges.candidates(deposit, moves, Links(), BANKS, rate_for_month=_rate)
        assert [(c.move.fingerprint, c.primary) for c in found] == [
            ("exact", True),
            ("close", True),
            ("far-rate", False),
        ]

    def test_legs_can_be_added_on_either_side_of_an_existing_exchange(self) -> None:
        a = _leg("2026-02-01", "-63700", "DOP", "a", category=cat.CURRENCY_EXCHANGE)
        b = _leg("2026-02-02", "1000", "USD", "b", category=cat.CURRENCY_EXCHANGE)
        more_pesos = _leg("2026-02-10", "-1000", "DOP", "more")
        more_dollars = _leg("2026-02-11", "20", "USD", "dollars")
        wrong = _leg("2026-02-11", "20", "DOP", "wrong")
        found = Links(exchanges=(Exchange(1, ("a", "b")),))
        state = exchanges.state(found.exchanges[0], _by_fp(a, b))
        options = exchanges.candidates(
            a, [a, b, more_pesos, more_dollars, wrong], found, BANKS, state
        )
        # Sin pendiente (solo el primer par): los dos lados, todo tras «Ver más».
        assert [(c.move.fingerprint, c.primary) for c in options] == [
            ("more", False),
            ("dollars", False),
        ]

    def test_with_pending_only_the_missing_side_and_what_fits_first(self) -> None:
        # Diste RD$ 127,400 en dos envíos; volvieron US$ 1,000 a 63.70: faltan US$ 1,000 de
        # vuelta. Solo depósitos en US$; los que caben en 1,050 van delante (primero el que
        # completa) y los más grandes, tras «Ver más».
        a = _leg("2026-02-01", "63700", "DOP", "a", category=cat.CURRENCY_EXCHANGE)
        b = _leg("2026-02-02", "-1000", "USD", "b", category=cat.CURRENCY_EXCHANGE)
        c = _leg("2026-02-03", "63700", "DOP", "c", category=cat.CURRENCY_EXCHANGE)
        moves = [
            a,
            b,
            c,
            _leg("2026-02-04", "-400", "USD", "part"),  # cabe, cerca
            _leg("2026-02-20", "-990", "USD", "completes"),  # lo completa (±5%), más lejos
            _leg("2026-02-05", "-1100", "USD", "too-big"),  # más que el pendiente + 5%
            _leg("2026-02-05", "500", "USD", "wrong-direction"),
            _leg("2026-02-05", "63700", "DOP", "other-side"),
            _leg("2026-04-01", "-500", "USD", "far"),
        ]
        found = Links(exchanges=(Exchange(1, ("a", "b", "c")),))
        state = exchanges.state(found.exchanges[0], _by_fp(a, b, c))
        assert state is not None
        assert (state.pending, state.pending_currency) == (D("1000.00"), "USD")
        options = exchanges.candidates(a, moves, found, BANKS, state, _rate)
        assert [(o.move.fingerprint, o.primary) for o in options] == [
            ("completes", True),
            ("part", True),
            ("too-big", False),
        ]

    def test_a_leg_slightly_over_the_pending_stays_behind_see_more(self) -> None:
        # Faltan US$ 1,000 y llegan US$ 1,060 (el diferencial del banco): no cabe con 5 %, pero
        # se puede agregar desde «Ver más».
        a = _leg("2026-02-01", "63700", "DOP", "a", category=cat.CURRENCY_EXCHANGE)
        b = _leg("2026-02-02", "-1000", "USD", "b", category=cat.CURRENCY_EXCHANGE)
        c = _leg("2026-02-03", "63700", "DOP", "c", category=cat.CURRENCY_EXCHANGE)
        spread = _leg("2026-02-04", "-1060", "USD", "spread")
        found = Links(exchanges=(Exchange(1, ("a", "b", "c")),))
        state = exchanges.state(found.exchanges[0], _by_fp(a, b, c))
        options = exchanges.candidates(a, [a, b, c, spread], found, BANKS, state, _rate)
        assert [(o.move.fingerprint, o.primary) for o in options] == [("spread", False)]

    def test_no_pending_beyond_the_first_pair_lists_both_sides_behind_see_more(self) -> None:
        # Sin tasa acordada: RD$ 63,700 por US$ 500 (127.40) y luego otros US$ 500 de vuelta.
        # Volvió de más: el pendiente es 0 aunque haya patas después del primer par.
        a = _leg("2026-02-01", "63700", "DOP", "a", category=cat.CURRENCY_EXCHANGE)
        b = _leg("2026-02-02", "-500", "USD", "b", category=cat.CURRENCY_EXCHANGE)
        c = _leg("2026-02-10", "-500", "USD", "c", category=cat.CURRENCY_EXCHANGE)
        found = Links(exchanges=(Exchange(1, ("a", "b", "c")),))
        state = exchanges.state(found.exchanges[0], _by_fp(a, b, c))
        assert state is not None
        assert (state.pending, state.first_pair_only) == (D(0), False)
        more = [_leg("2026-02-05", "-20", "USD", "u"), _leg("2026-02-06", "100", "DOP", "p")]
        options = exchanges.candidates(a, [a, b, c, *more], found, BANKS, state, _rate)
        assert [(o.move.fingerprint, o.primary) for o in options] == [("u", False), ("p", False)]

    def test_a_closed_exchange_lists_both_sides_behind_see_more(self) -> None:
        a = _leg("2026-02-01", "63700", "DOP", "a", category=cat.CURRENCY_EXCHANGE)
        b = _leg("2026-02-02", "-500", "USD", "b", category=cat.CURRENCY_EXCHANGE)
        found = Links(exchanges=(Exchange(1, ("a", "b"), D("63.70"), closed=True),))
        state = exchanges.state(found.exchanges[0], _by_fp(a, b))
        assert state is not None and state.pending == 0
        more = [_leg("2026-02-05", "-500", "USD", "u"), _leg("2026-02-06", "100", "DOP", "p")]
        options = exchanges.candidates(a, [a, b, *more], found, BANKS, state)
        assert [(o.move.fingerprint, o.primary) for o in options] == [("u", False), ("p", False)]
