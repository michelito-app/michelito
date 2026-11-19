"""Inversiones: cuentas, % anual, moneda, categorías, Resumen y «Para revisar», con movimientos
inventados (sin HTTP)."""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from finanzas import db
from finanzas.analysis import catalog, investments, review, spending
from finanzas.analysis import categories as cat
from finanzas.analysis.accounts import AccountInfo
from finanzas.analysis.links import Investment, InvestmentMember, Links
from finanzas.analysis.rates import Rate
from finanzas.analysis.spending import Movement
from finanzas.web import investment_list, summary

D = Decimal
BANK = "ficticio:savings:999"
RATES = {"2026-01": Rate(D("60"), "2026-01", "bcrd")}
TODAY = date(2026, 4, 1)


def _move(
    day: str,
    amount: str,
    fp: str,
    category: str = cat.THIRD_PARTY,
    currency: str = "DOP",
    merchant: str | None = None,
    description: str | None = None,
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=merchant or fp,
        description=description or fp,
        category=category,
        amount=D(amount),
        currency=currency,
        institution="ficticio",
        fingerprint=fp,
        account=BANK,
    )


def _credit(day: str, amount: str, fp: str, category: str = cat.OTHER_INCOME, **kw) -> Movement:
    return _move(day, f"-{amount}", fp, category=category, **kw)


def _investment(*members: tuple[str, str] | tuple[str, str, str], **kw) -> Investment:
    found = tuple(
        InvestmentMember(m[0], m[1], D(m[2]) if len(m) == 3 else None)  # type: ignore[misc]
        for m in members
    )
    return Investment(1, found, **kw)


@pytest.fixture(scope="module")
def known() -> catalog.Catalog:
    with closing(db.connect(":memory:")) as conn:
        return catalog.load(conn)


def _linked(moves, link: Investment, known: catalog.Catalog, rates=None) -> list[Movement]:
    return list(spending.with_links(moves, Links(investments=(link,)), known, rates=rates))


def _state(moves, link, known, rates=None) -> investments.InvestmentState:
    linked = _linked(moves, link, known, rates)
    return investments.states(linked, Links(investments=(link,)), rates or {})[link.id]


class TestCategories:
    def test_the_link_decides_the_category_of_each_role(self, known) -> None:
        moves = [
            _move("2026-01-02", "300000", "aporte"),
            _credit("2026-01-20", "9000", "rinde"),
            _credit("2026-02-20", "100000", "capital"),
            _credit("2026-03-20", "60000", "mixto"),
        ]
        link = _investment(
            ("aporte", "contribution"),
            ("rinde", "return"),
            ("capital", "capital"),
            ("mixto", "mixed", "50000"),
        )
        aporte, rinde, capital, mixto = _linked(moves, link, known)
        assert (aporte.ref, aporte.kind, aporte.link) == (
            cat.INVESTMENT,
            "transferencia",
            "investment",
        )
        assert (rinde.ref, rinde.kind, rinde.amount) == (cat.INVESTMENT_RETURN, "ingreso", D(-9000))
        assert (capital.ref, capital.kind) == (cat.INVESTMENT_CAPITAL, "transferencia")
        # Del mixto solo el rendimiento es ingreso; `gross` guarda el crédito entero.
        assert (mixto.ref, mixto.amount, mixto.gross) == (
            cat.INVESTMENT_RETURN,
            D(-10000),
            D(-60000),
        )

    def test_a_contribution_that_is_no_longer_a_debit_stays_as_it_was(self, known) -> None:
        moves = [_credit("2026-01-02", "500", "aporte")]
        [same] = _linked(moves, _investment(("aporte", "contribution")), known)
        assert same == moves[0]

    def test_a_mixed_credit_whose_capital_no_longer_fits_counts_as_capital(self, known) -> None:
        moves = [_move("2026-01-02", "1000", "a"), _credit("2026-01-09", "400", "m")]
        _, mixto = _linked(moves, _investment(("a", "contribution"), ("m", "mixed", "500")), known)
        assert (mixto.ref, mixto.amount) == (cat.INVESTMENT_CAPITAL, D(-400))


class TestTotals:
    def test_totals_pending_and_last_credit(self, known) -> None:
        moves = [
            _move("2026-01-02", "300000", "a1"),
            _move("2026-01-15", "100000", "a2"),
            _credit("2026-01-30", "9000", "r1"),
            _credit("2026-02-28", "60000", "m1"),
        ]
        link = _investment(
            ("a1", "contribution"),
            ("a2", "contribution"),
            ("r1", "return"),
            ("m1", "mixed", "50000"),
        )
        state = _state(moves, link, known)
        assert state.contributed == D(400000)
        assert state.capital_returned == D(50000)
        assert state.pending == D(350000)
        assert state.returns == D(19000)
        assert state.last_credit == date(2026, 2, 28)
        assert state.status == "active"
        assert state.title == "a1"  # sin nombre ni «Con quién»: el comercio del primer aporte

    def test_closes_on_its_own_when_all_the_capital_is_back(self, known) -> None:
        moves = [_move("2026-01-02", "1000", "a"), _credit("2026-03-02", "1100", "m")]
        link = _investment(("a", "contribution"), ("m", "mixed", "1000"), name="Préstamo")
        state = _state(moves, link, known)
        assert (state.pending, state.returns, state.status) == (0, D(100), "closed")
        assert state.title == "Préstamo"

    def test_more_capital_back_than_contributed_never_goes_negative(self, known) -> None:
        moves = [_move("2026-01-02", "1000", "a"), _credit("2026-03-02", "1500", "c")]
        state = _state(moves, _investment(("a", "contribution"), ("c", "capital")), known)
        assert (state.pending, state.status) == (0, "closed")

    def test_written_off_until_the_capital_comes_back(self, known) -> None:
        moves = [_move("2026-01-02", "1000", "a")]
        link = _investment(("a", "contribution"), written_off=True, with_whom="Pedro")
        state = _state(moves, link, known)
        assert (state.status, state.title) == ("written_off", "Pedro")
        back = [*moves, _credit("2026-02-02", "1000", "c")]
        lost = _investment(("a", "contribution"), ("c", "capital"), written_off=True)
        assert _state(back, lost, known).status == "closed"

    def test_without_present_contributions_there_is_no_investment(self, known) -> None:
        moves = [_credit("2026-01-09", "400", "r")]
        link = _investment(("a", "contribution"), ("r", "return"))
        linked = _linked(moves, link, known)
        assert investments.states(linked, Links(investments=(link,)), {}) == {}


class TestAnnualRate:
    def test_one_contribution_and_one_return_over_a_year(self, known) -> None:
        moves = [_move("2025-01-01", "100000", "a"), _credit("2025-12-01", "12000", "r")]
        state = _state(moves, _investment(("a", "contribution"), ("r", "return")), known)
        # Activa: hasta hoy (1 abr 2026, 455 días): 12,000 × 365 / (100,000 × 455).
        assert state.annual_rate(TODAY) == D(12000) * 365 / (D(100000) * 455)

    def test_without_returns_it_is_zero(self, known) -> None:
        moves = [_move("2026-01-01", "100000", "a")]
        assert _state(moves, _investment(("a", "contribution")), known).annual_rate(TODAY) == 0

    def test_everything_the_same_day_has_no_rate(self, known) -> None:
        moves = [_move("2026-04-01", "100000", "a")]
        assert _state(moves, _investment(("a", "contribution")), known).annual_rate(TODAY) is None

    def test_contributions_on_different_days_weigh_by_time_invested(self, known) -> None:
        # 100,000 desde el 1 ene y 200,000 más desde el 31 ene; cerrada el 1 mar (59 días
        # desde el primer aporte): capital-días = 100,000 × 30 + 300,000 × 29.
        moves = [
            _move("2026-01-01", "100000", "a1"),
            _move("2026-01-31", "200000", "a2"),
            _credit("2026-03-01", "309000", "m"),
        ]
        link = _investment(("a1", "contribution"), ("a2", "contribution"), ("m", "mixed", "300000"))
        state = _state(moves, link, known)
        assert state.status == "closed"
        days = D(100000) * 30 + D(300000) * 29
        assert investments.capital_days(state.counted, state.end(TODAY)) == days
        assert state.annual_rate(TODAY) == D(9000) * 365 / days

    def test_capital_already_back_stops_counting(self, known) -> None:
        # La mitad vuelve a los 10 días; la otra mitad y el rendimiento a los 20: cerrada.
        moves = [
            _move("2026-01-01", "1000", "a"),
            _credit("2026-01-11", "500", "c"),
            _credit("2026-01-21", "600", "m"),
        ]
        link = _investment(("a", "contribution"), ("c", "capital"), ("m", "mixed", "500"))
        state = _state(moves, link, known)
        days = D(1000) * 10 + D(500) * 10
        assert investments.capital_days(state.counted, state.end(TODAY)) == days
        assert state.annual_rate(TODAY) == D(100) * 365 / days


class TestCurrency:
    def test_other_currency_counts_at_the_rate_of_its_month(self, known) -> None:
        moves = [
            _move("2026-01-02", "60000", "a"),
            _credit("2026-01-30", "10", "usd", currency="USD"),
        ]
        link = _investment(("a", "contribution"), ("usd", "return"))
        state = _state(moves, link, known, RATES)
        assert (state.currency, state.returns, state.unconverted) == ("DOP", D(600), ())

    def test_the_rate_of_an_earlier_month_is_the_fallback(self, known) -> None:
        moves = [
            _move("2026-01-02", "60000", "a"),
            _credit("2026-03-30", "10", "usd", currency="USD"),
        ]
        state = _state(moves, _investment(("a", "contribution"), ("usd", "return")), known, RATES)
        assert state.returns == D(600)

    def test_without_any_rate_it_goes_apart(self, known) -> None:
        moves = [
            _move("2026-01-02", "60000", "a"),
            _credit("2026-01-30", "10", "usd", currency="USD"),
        ]
        state = _state(moves, _investment(("a", "contribution"), ("usd", "return")), known)
        assert state.returns == 0
        assert [e.fingerprint for e in state.unconverted] == ["usd"]

    def test_the_currency_is_the_one_of_the_first_contribution(self, known) -> None:
        moves = [
            _move("2026-01-05", "60000", "dop"),
            _move("2026-01-02", "1000", "usd", currency="USD"),
        ]
        link = _investment(("dop", "contribution"), ("usd", "contribution"))
        state = _state(moves, link, known, RATES)
        assert (state.currency, state.contributed) == ("USD", D(2000))


class TestList:
    def test_totals_in_pesos_only_count_active_and_this_year(self, known) -> None:
        moves = [
            _move("2025-06-01", "100000", "a"),
            _credit("2025-12-01", "5000", "old"),
            _credit("2026-02-01", "3000", "new"),
            _credit("2026-02-15", "10", "usd", currency="USD"),
        ]
        link = _investment(
            ("a", "contribution"), ("old", "return"), ("new", "return"), ("usd", "return")
        )
        found = {1: _state(moves, link, known)}
        listed = investment_list.build_list(found, {}, TODAY)
        assert (listed.pending_dop, listed.returns_year_dop) == (D(100000), D(3000))
        assert listed.unconverted_returns_usd == D(10)
        assert listed.active_count == 1
        lost = {1: _state(moves[:1], _investment(("a", "contribution"), written_off=True), known)}
        assert investment_list.build_list(lost, {}, TODAY).pending_dop == 0
        assert investment_list.build_list(found, {}, TODAY, frozenset({"otra"})).rows == ()


def _accounts() -> list[AccountInfo]:
    return [
        AccountInfo("card", "credit_card", "Tarjeta", date(2026, 1, 31)),
        AccountInfo(BANK, "savings", "Ahorro", date(2026, 1, 31)),
    ]


class TestSummary:
    def test_a_contribution_does_not_take_from_what_you_kept(self, known) -> None:
        moves = [
            _move("2026-01-05", "500", "comida", category=cat.GROCERIES),
            _credit("2026-01-15", "50000", "nomina", category=cat.SALARY),
            _move("2026-01-20", "30000", "aporte"),
            _credit("2026-01-25", "1000", "rinde"),
            _credit("2026-01-28", "5000", "capital"),
        ]
        moves[0] = replace(moves[0], account="card")
        before = summary.build_summary(moves, _accounts(), {}, "2026-01")
        assert before.third_party == D(30000) and before.invested == 0
        link = _investment(("aporte", "contribution"), ("rinde", "return"), ("capital", "capital"))
        linked = _linked(moves, link, known)
        after = summary.build_summary(linked, _accounts(), {}, "2026-01")
        assert (after.third_party, after.invested) == (0, D(30000))
        # El rendimiento es ingreso; el capital que vuelve, no.
        assert after.income == before.income - D(5000)
        assert after.net == after.income - D(500)


class TestReview:
    def _moves(self) -> list[Movement]:
        return [
            _move("2026-01-02", "300000", "a1", merchant="MB A 0000000066"),
            _move(
                "2026-01-20",
                "100000",
                "a2",
                merchant="MB A 0000000066",
                description="MB a 0000000066 PEDRO",
            ),
            _move("2026-01-21", "1500", "chico", merchant="MB A 0000000066"),
            _credit("2026-01-22", "9000", "cobro", description="TRANSF DE PEDRO INVERSOR"),
            _credit("2026-01-23", "300", "chico-de", description="TRANSF DE PEDRO INVERSOR"),
            _credit("2026-01-24", "9000", "otro", description="DEPOSITO CLIENTE"),
        ]

    def _items(self, moves, link, known) -> list[review.Item]:
        found = Links(investments=(link,))
        linked = list(spending.with_links(moves, found, known))
        states = investments.states(linked, found, {})
        hints = {
            fp: review.Hint(s.kind, s.reason, s.state.id)
            for fp, s in investments.suggestions(linked, found, states, {}).items()
        }
        return review.detect(linked, "2026-01", rate_for_month=lambda _m: None, hints=hints)

    def test_contributions_are_not_large_transfers_and_suggestions_never_link(self, known) -> None:
        moves = self._moves()
        link = _investment(("a1", "contribution"), with_whom="Pedro Inversor")
        items = self._items(moves, link, known)
        found = {(i.kind, i.fingerprint) for i in items}
        assert ("tercero_grande", "a1") not in found  # ya es un aporte
        # El segundo envío grande al mismo destino se propone (y no sale como transferencia
        # grande); el chico no. El crédito con el nombre se propone como cobro; el chico, no.
        assert ("aporte_posible", "a2") in found and ("tercero_grande", "a2") not in found
        assert not any(i.fingerprint == "chico" for i in items)
        assert ("cobro_posible", "cobro") in found
        assert not any(i.fingerprint in ("chico-de", "otro") for i in items)
        hint = next(i for i in items if i.kind == "aporte_posible")
        assert (hint.investment_id, hint.reason) == (1, "¿Es otro aporte a Pedro Inversor?")
        # Proponer no enlaza: los movimientos siguen sin vínculo.
        linked = spending.with_links(moves, Links(investments=(link,)), known)
        assert {m.fingerprint for m in linked if m.link} == {"a1"}

    def test_returned_capital_is_not_an_unusual_income(self, known) -> None:
        old = _move("2025-10-01", "100", "viejo", category=cat.GROCERIES)
        moves = [
            old,
            _move("2025-11-02", "300000", "a1"),
            _credit("2026-01-22", "300000", "capital"),
            _credit("2026-01-23", "20000", "rinde"),
        ]
        before = review.detect(moves, "2026-01", rate_for_month=lambda _m: None)
        unusual = {i.fingerprint for i in before if i.kind == "ingreso_inusual"}
        assert unusual == {"capital", "rinde"}
        link = _investment(("a1", "contribution"), ("capital", "capital"), ("rinde", "return"))
        items = self._items(moves, link, known)
        assert not [i for i in items if i.kind == "ingreso_inusual"]

    def test_only_bank_accounts_are_suggested(self, known) -> None:
        moves = self._moves()
        link = _investment(("a1", "contribution"), with_whom="Pedro Inversor")
        found = Links(investments=(link,))
        linked = list(spending.with_links(moves, found, known))
        states = investments.states(linked, found, {})
        assert investments.suggestions(linked, found, states, {}, banks=()) == {}


class TestExcessCapital:
    def test_capital_back_beyond_what_was_put_in_is_a_return(self, known) -> None:
        # Aporte de 100,000 y devolución de 150,000: 50,000 son ganancia.
        moves = [_move("2026-01-01", "100000", "a"), _credit("2026-01-31", "150000", "c")]
        link = _investment(("a", "contribution"), ("c", "capital"))
        state = _state(moves, link, known)
        assert (state.capital_returned, state.excess, state.returns) == (
            D(100000),
            D(50000),
            D(50000),
        )
        assert (state.pending, state.status) == (0, "closed")
        # 50,000 sobre 100,000 durante 30 días.
        assert state.annual_rate(TODAY) == D(50000) * 365 / (D(100000) * 30)
        # En el Resumen y los reportes, el exceso es ingreso ("Rendimientos").
        _, back = _linked(moves, link, known)
        assert (back.ref, back.amount, back.gross) == (
            cat.INVESTMENT_RETURN,
            D(-50000),
            D(-150000),
        )

    def test_a_later_contribution_does_not_inflate_the_rate(self, known) -> None:
        # Después: otro aporte de 100,000 el 31 ene y un rendimiento de 5,000 el 2 mar.
        moves = [
            _move("2026-01-01", "100000", "a1"),
            _credit("2026-01-31", "150000", "c"),
            _move("2026-01-31", "100000", "a2"),
            _credit("2026-03-02", "5000", "r"),
        ]
        link = _investment(
            ("a1", "contribution"), ("c", "capital"), ("a2", "contribution"), ("r", "return")
        )
        state = _state(moves, link, known)
        # El mismo día, el aporte va antes que el crédito: devuelve 150,000 de 200,000.
        assert (state.contributed, state.capital_returned, state.excess) == (
            D(200000),
            D(150000),
            0,
        )
        assert (state.pending, state.returns) == (D(50000), D(5000))
        # Capital-días: 100,000 × 30 + 50,000 × 60 (31 ene a 1 abr): nunca negativo.
        days = D(100000) * 30 + D(50000) * 60
        assert investments.capital_days(state.counted, state.end(TODAY)) == days
        assert state.annual_rate(TODAY) == D(5000) * 365 / days

    def test_returned_first_then_contributed_keeps_the_capital_from_going_negative(
        self, known
    ) -> None:
        # Devolución de 150,000 de un aporte de 100,000; un mes después, otro de 100,000 que
        # sigue invertido entero (antes el capital corrido quedaba en −50,000 y lo restaba).
        moves = [
            _move("2026-01-01", "100000", "a1"),
            _credit("2026-01-31", "150000", "c"),
            _move("2026-02-28", "100000", "a2"),
            _credit("2026-03-30", "5000", "r"),
        ]
        link = _investment(
            ("a1", "contribution"), ("c", "capital"), ("a2", "contribution"), ("r", "return")
        )
        state = _state(moves, link, known)
        assert (state.excess, state.returns, state.pending) == (D(50000), D(55000), D(100000))
        days = D(100000) * 30 + D(100000) * (date(2026, 4, 1) - date(2026, 2, 28)).days
        assert investments.capital_days(state.counted, state.end(TODAY)) == days
        assert state.annual_rate(TODAY) == D(55000) * 365 / days


class TestSuggestionNoise:
    def _suggest(self, known, with_whom: str, contribution: str, credit: str, amount="9000"):
        moves = [
            _move("2026-01-02", "300000", "a", description=contribution),
            _credit("2026-01-20", amount, "c", description=credit),
        ]
        link = _investment(("a", "contribution"), with_whom=with_whom)
        found = Links(investments=(link,))
        linked = list(spending.with_links(moves, found, known))
        states = investments.states(linked, found, {})
        return investments.suggestions(linked, found, states, {})

    def test_one_shared_first_name_is_not_enough(self, known) -> None:
        sent = "MB a 0000000066 JUAN PEREZ"
        assert self._suggest(known, "Juan Pérez", sent, "TRANSF DE JUAN GARCIA") == {}
        assert self._suggest(known, "Juan Pérez", sent, "PAGO JUAN SUPERMERCADO") == {}
        assert "c" in self._suggest(known, "Juan Pérez", sent, "TRANSF DE JUAN PEREZ")

    def test_only_the_destination_account_as_a_whole_word(self, known) -> None:
        sent = "MB a 0000000066 SOCIO REF 202601"
        assert self._suggest(known, "", sent, "NOMINA 2026012345") == {}
        assert self._suggest(known, "", sent, "DEP 00000000667") == {}
        assert "c" in self._suggest(known, "", sent, "DEV DE 0000000066 SOCIO")

    def test_returns_below_one_percent_of_what_was_put_in_are_not_proposed(self, known) -> None:
        sent, back = "MB a 0000000066 PEDRO", "TRANSF DE PEDRO"
        assert self._suggest(known, "Pedro", sent, back, amount="2999") == {}
        assert "c" in self._suggest(known, "Pedro", sent, back, amount="3000")

    def test_names_match(self) -> None:
        assert investments.names_match("Pedro", "TRANSF DE PEDRO")
        assert investments.names_match("Ana María Gómez", "TOKE DE MARIA GOMEZ")
        assert not investments.names_match("Ana María Gómez", "TOKE DE MARIA")
        assert not investments.names_match("", "TRANSF")

    def test_the_contribution_threshold_is_the_one_of_review(self) -> None:
        assert investments.LARGE_CONTRIBUTION_DOP == review.LARGE_THIRD_PARTY_DOP


class TestReviewedProposals:
    def test_a_reviewed_proposal_is_not_proposed_again_nor_hides_the_rest(self, known) -> None:
        moves = TestReview()._moves()
        link = _investment(("a1", "contribution"), with_whom="Pedro Inversor")
        found = Links(investments=(link,))
        linked = list(spending.with_links(moves, found, known))
        states = investments.states(linked, found, {})
        hints = {
            fp: review.Hint(s.kind, s.reason, s.state.id)
            for fp, s in investments.suggestions(linked, found, states, {}).items()
        }

        def detect(reviewed):
            items = review.detect(
                linked, "2026-01", rate_for_month=lambda _m: None, hints=hints, reviewed=reviewed
            )
            return {(i.kind, i.fingerprint): i.reviewed for i in items}

        assert ("tercero_grande", "a2") not in detect(())
        after = detect({("a2", "aporte_posible")})
        assert after[("aporte_posible", "a2")] is True  # revisada: solo en el historial
        assert after[("tercero_grande", "a2")] is False  # vuelve a salir lo que es


def test_the_history_computes_the_investment_hints_once(
    known, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finanzas.web import review as review_view

    moves = TestReview()._moves()
    link = _investment(("a1", "contribution"), with_whom="Pedro Inversor")
    found = Links(investments=(link,))
    linked = tuple(spending.with_links(moves, found, known))
    calls = []
    real = investments.states
    monkeypatch.setattr(investments, "states", lambda *a: calls.append(1) or real(*a))
    ctx = review_view.Context(
        flow=linked,
        accounts=_accounts(),
        rates={},
        marks={},
        reviewed=(),
        dismissed=(),
        links=found,
    )
    review_view.history(ctx, ["2025-11", "2025-12", "2026-01"])
    assert calls == [1]
