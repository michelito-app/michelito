"""Investments: accounts, annual %, currency, categories, Summary and "To review", with
synthetic movements (no HTTP)."""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from michelito import db
from michelito.analysis import catalog, investments, review, spending
from michelito.analysis import categories as cat
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.links import Investment, InvestmentMember, Links
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from michelito.web import investment_list, summary

D = Decimal
BANK = "ficticio:savings:999"  # spanish-data
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
        institution="ficticio",  # spanish-data
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
            _move("2026-01-02", "300000", "contrib"),
            _credit("2026-01-20", "9000", "yield"),
            _credit("2026-02-20", "100000", "capital"),
            _credit("2026-03-20", "60000", "mixed"),
        ]
        link = _investment(
            ("contrib", "contribution"),
            ("yield", "return"),
            ("capital", "capital"),
            ("mixed", "mixed", "50000"),
        )
        contrib, earned, capital, mixed = _linked(moves, link, known)
        assert (contrib.ref, contrib.kind, contrib.link) == (
            cat.INVESTMENT,
            "transfer",
            "investment",
        )
        assert (earned.ref, earned.kind, earned.amount) == (
            cat.INVESTMENT_RETURN,
            "income",
            D(-9000),
        )
        assert (capital.ref, capital.kind) == (cat.INVESTMENT_CAPITAL, "transfer")
        # Of the mixed credit only the return is income; `gross` keeps the whole credit.
        assert (mixed.ref, mixed.amount, mixed.gross) == (
            cat.INVESTMENT_RETURN,
            D(-10000),
            D(-60000),
        )

    def test_a_contribution_that_is_no_longer_a_debit_stays_as_it_was(self, known) -> None:
        moves = [_credit("2026-01-02", "500", "contrib")]
        [same] = _linked(moves, _investment(("contrib", "contribution")), known)
        assert same == moves[0]

    def test_a_mixed_credit_whose_capital_no_longer_fits_counts_as_capital(self, known) -> None:
        moves = [_move("2026-01-02", "1000", "a"), _credit("2026-01-09", "400", "m")]
        _, mixed = _linked(moves, _investment(("a", "contribution"), ("m", "mixed", "500")), known)
        assert (mixed.ref, mixed.amount) == (cat.INVESTMENT_CAPITAL, D(-400))


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
        assert state.title == "a1"  # no name nor "with whom": first contribution's merchant

    def test_closes_on_its_own_when_all_the_capital_is_back(self, known) -> None:
        moves = [_move("2026-01-02", "1000", "a"), _credit("2026-03-02", "1100", "m")]
        link = _investment(("a", "contribution"), ("m", "mixed", "1000"), name="Loan")
        state = _state(moves, link, known)
        assert (state.pending, state.returns, state.status) == (0, D(100), "closed")
        assert state.title == "Loan"

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
        # Active: until today (Apr 1 2026, 455 days): 12,000 × 365 / (100,000 × 455).
        assert state.annual_rate(TODAY) == D(12000) * 365 / (D(100000) * 455)

    def test_without_returns_it_is_zero(self, known) -> None:
        moves = [_move("2026-01-01", "100000", "a")]
        assert _state(moves, _investment(("a", "contribution")), known).annual_rate(TODAY) == 0

    def test_everything_the_same_day_has_no_rate(self, known) -> None:
        moves = [_move("2026-04-01", "100000", "a")]
        assert _state(moves, _investment(("a", "contribution")), known).annual_rate(TODAY) is None

    def test_contributions_on_different_days_weigh_by_time_invested(self, known) -> None:
        # 100,000 from Jan 1 and 200,000 more from Jan 31; closed on Mar 1 (59 days after the
        # first contribution): capital-days = 100,000 × 30 + 300,000 × 29.
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
        # Half comes back after 10 days; the other half and the return after 20: closed.
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
    def test_totals_in_dop_only_count_active_and_this_year(self, known) -> None:
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
        assert investment_list.build_list(found, {}, TODAY, frozenset({"other"})).rows == ()


def _accounts() -> list[AccountInfo]:
    return [
        AccountInfo("card", "credit_card", "Tarjeta", date(2026, 1, 31)),  # spanish-data
        AccountInfo(BANK, "savings", "Ahorro", date(2026, 1, 31)),  # spanish-data
    ]


class TestSummary:
    def test_a_contribution_does_not_take_from_what_you_kept(self, known) -> None:
        moves = [
            _move("2026-01-05", "500", "food", category=cat.GROCERIES),
            _credit("2026-01-15", "50000", "payroll", category=cat.SALARY),
            _move("2026-01-20", "30000", "contrib"),
            _credit("2026-01-25", "1000", "yield"),
            _credit("2026-01-28", "5000", "capital"),
        ]
        moves[0] = replace(moves[0], account="card")
        before = summary.build_summary(moves, _accounts(), {}, "2026-01")
        assert before.third_party == D(30000) and before.invested == 0
        link = _investment(("contrib", "contribution"), ("yield", "return"), ("capital", "capital"))
        linked = _linked(moves, link, known)
        after = summary.build_summary(linked, _accounts(), {}, "2026-01")
        assert (after.third_party, after.invested) == (0, D(30000))
        # The return is income; the capital coming back is not.
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
            _move("2026-01-21", "1500", "small", merchant="MB A 0000000066"),
            _credit("2026-01-22", "9000", "payout", description="TRANSF DE PEDRO INVERSOR"),
            _credit("2026-01-23", "300", "small-from", description="TRANSF DE PEDRO INVERSOR"),
            _credit("2026-01-24", "9000", "unrelated", description="DEPOSITO CLIENTE"),
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
        assert ("large_third_party", "a1") not in found  # already a contribution
        # The second large transfer to the same destination is proposed (and is not listed as a
        # large transfer); the small one is not. The credit with the name is proposed as a
        # return; the small one is not.
        assert ("possible_contribution", "a2") in found and ("large_third_party", "a2") not in found
        assert not any(i.fingerprint == "small" for i in items)
        assert ("possible_return", "payout") in found
        assert not any(i.fingerprint in ("small-from", "unrelated") for i in items)
        hint = next(i for i in items if i.kind == "possible_contribution")
        assert (hint.investment_id, hint.reason) == (
            1,
            "¿Es otro aporte a Pedro Inversor?",  # spanish-ui
        )
        # Proposing does not link: the movements stay unlinked.
        linked = spending.with_links(moves, Links(investments=(link,)), known)
        assert {m.fingerprint for m in linked if m.link} == {"a1"}

    def test_returned_capital_is_not_an_unusual_income(self, known) -> None:
        old = _move("2025-10-01", "100", "old", category=cat.GROCERIES)
        moves = [
            old,
            _move("2025-11-02", "300000", "a1"),
            _credit("2026-01-22", "300000", "capital"),
            _credit("2026-01-23", "20000", "yield"),
        ]
        before = review.detect(moves, "2026-01", rate_for_month=lambda _m: None)
        unusual = {i.fingerprint for i in before if i.kind == "unusual_income"}
        assert unusual == {"capital", "yield"}
        link = _investment(("a1", "contribution"), ("capital", "capital"), ("yield", "return"))
        items = self._items(moves, link, known)
        assert not [i for i in items if i.kind == "unusual_income"]

    def test_only_bank_accounts_are_suggested(self, known) -> None:
        moves = self._moves()
        link = _investment(("a1", "contribution"), with_whom="Pedro Inversor")
        found = Links(investments=(link,))
        linked = list(spending.with_links(moves, found, known))
        states = investments.states(linked, found, {})
        assert investments.suggestions(linked, found, states, {}, banks=()) == {}


class TestExcessCapital:
    def test_capital_back_beyond_what_was_put_in_is_a_return(self, known) -> None:
        # A 100,000 contribution and 150,000 back: 50,000 is profit.
        moves = [_move("2026-01-01", "100000", "a"), _credit("2026-01-31", "150000", "c")]
        link = _investment(("a", "contribution"), ("c", "capital"))
        state = _state(moves, link, known)
        assert (state.capital_returned, state.excess, state.returns) == (
            D(100000),
            D(50000),
            D(50000),
        )
        assert (state.pending, state.status) == (0, "closed")
        # 50,000 on 100,000 over 30 days.
        assert state.annual_rate(TODAY) == D(50000) * 365 / (D(100000) * 30)
        # In the Summary and the reports, the excess is income (investment returns).
        _, back = _linked(moves, link, known)
        assert (back.ref, back.amount, back.gross) == (
            cat.INVESTMENT_RETURN,
            D(-50000),
            D(-150000),
        )

    def test_a_later_contribution_does_not_inflate_the_rate(self, known) -> None:
        # Then: another 100,000 contribution on Jan 31 and a 5,000 return on Mar 2.
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
        # On the same day the contribution goes before the credit: 150,000 of 200,000 back.
        assert (state.contributed, state.capital_returned, state.excess) == (
            D(200000),
            D(150000),
            0,
        )
        assert (state.pending, state.returns) == (D(50000), D(5000))
        # Capital-days: 100,000 × 30 + 50,000 × 60 (Jan 31 to Apr 1): never negative.
        days = D(100000) * 30 + D(50000) * 60
        assert investments.capital_days(state.counted, state.end(TODAY)) == days
        assert state.annual_rate(TODAY) == D(5000) * 365 / days

    def test_returned_first_then_contributed_keeps_the_capital_from_going_negative(
        self, known
    ) -> None:
        # 150,000 back from a 100,000 contribution; a month later another 100,000 that stays
        # fully invested (the running capital used to sit at -50,000 and subtract it).
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
        # spanish-data: begin
        assert self._suggest(known, "Juan Pérez", sent, "TRANSF DE JUAN GARCIA") == {}
        assert self._suggest(known, "Juan Pérez", sent, "PAGO JUAN SUPERMERCADO") == {}
        assert "c" in self._suggest(known, "Juan Pérez", sent, "TRANSF DE JUAN PEREZ")
        # spanish-data: end

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
        # spanish-data: begin
        assert investments.names_match("Ana María Gómez", "TOKE DE MARIA GOMEZ")
        assert not investments.names_match("Ana María Gómez", "TOKE DE MARIA")
        # spanish-data: end
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

        assert ("large_third_party", "a2") not in detect(())
        after = detect({("a2", "possible_contribution")})
        assert after[("possible_contribution", "a2")] is True  # reviewed: only in the history
        assert after[("large_third_party", "a2")] is False  # shows up again as what it is


def test_the_history_computes_the_investment_hints_once(
    known, monkeypatch: pytest.MonkeyPatch
) -> None:
    from michelito.web import review as review_view

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
