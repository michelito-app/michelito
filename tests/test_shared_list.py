"""Compartidos: todos los grupos, su estado, orden, totales y «Nuevo grupo…», sin HTTP."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from finanzas.analysis import categories as cat
from finanzas.analysis import shared
from finanzas.analysis.links import Links, ManualEntry, Shared, SharedExpense
from finanzas.analysis.rates import Rate
from finanzas.analysis.spending import Movement
from finanzas.web import shared_list

D = Decimal
TODAY = date(2026, 3, 15)
LABELS = {"visa": "VISA ···1", "pesos": "Corriente ···2"}
RATES = {
    "2025-12": Rate(D("58.00"), "2025-12", "bcrd"),
    "2026-02": Rate(D("62.00"), "2026-02", "bcrd"),
}


def _move(
    day: str,
    amount: str,
    fp: str,
    currency: str = "DOP",
    account: str = "visa",
    category: str = cat.RESTAURANTS,
    link: str = "",
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=f"COMERCIO {fp.upper()}",
        description=f"DESCRIPCION {fp.upper()}",
        category=category,
        amount=D(amount),
        currency=currency,
        institution="x",
        fingerprint=fp,
        account=account,
        link=link,
    )


def _expense(day: str, amount: str, fp: str, **kw) -> Movement:
    return _move(day, amount, fp, link="shared", **kw)


def _credit(day: str, amount: str, fp: str, **kw) -> Movement:
    return _move(
        day,
        f"-{amount}",
        fp,
        account="pesos",
        category=cat.OTHER_INCOME,
        link="reimbursement",
        **kw,
    )


def _build(
    moves: list[Movement],
    groups: tuple[Shared, ...],
    rates: dict[str, Rate] | None = None,
    chosen: frozenset[str] | None = None,
) -> shared_list.SharedList:
    by_month = RATES if rates is None else rates
    states = shared.states(moves, Links(shared=groups), by_month)
    return shared_list.build_shared_list(moves, states, LABELS, by_month, TODAY, chosen)


def _three_groups() -> tuple[list[Movement], tuple[Shared, ...]]:
    """Una cena con pendiente, un regalo saldado y un taxi dado por perdido."""
    moves = [
        _expense("2026-02-02", "3000", "cena"),
        _expense("2026-01-10", "1000", "regalo"),
        _credit("2026-01-20", "1000", "pago-regalo"),
        _expense("2026-02-20", "600", "taxi"),
    ]
    groups = (
        Shared.one(1, "cena", people=3, with_whom="Ana y Luis"),
        Shared.one(
            2, "regalo", for_other=True, name="Regalo Luis", reimbursements=("pago-regalo",)
        ),
        Shared.one(3, "taxi", people=2, written_off=True),
    )
    return moves, groups


class TestStatus:
    def test_pending_settled_and_written_off(self) -> None:
        moves, groups = _three_groups()
        rows = {r.state.id: r for r in _build(moves, groups).rows}

        assert rows[1].status == "pending"
        assert rows[2].status == "settled"
        assert rows[3].status == "written_off"
        assert rows[1].pending == (("DOP", D(2000)),)
        assert rows[2].pending == () and rows[3].pending == ()

    def test_a_written_off_group_that_was_already_paid_is_settled(self) -> None:
        moves = [_expense("2026-02-02", "1000", "g"), _credit("2026-02-03", "500", "c")]
        link = Shared.one(1, "g", people=2, written_off=True, reimbursements=("c",))

        [row] = _build(moves, (link,)).rows

        assert row.status == "settled"


class TestOrderAndFilter:
    def test_newest_activity_first_counting_refunds(self) -> None:
        moves, groups = _three_groups()
        # El reembolso del regalo llega después del taxi: pasa a ser lo más reciente.
        moves[2] = _credit("2026-03-01", "1000", "pago-regalo")

        rows = _build(moves, groups).rows

        assert [r.state.id for r in rows] == [2, 3, 1]
        assert rows[0].last_activity == date(2026, 3, 1)

    def test_ties_go_to_the_newest_group(self) -> None:
        moves = [_expense("2026-02-02", "100", "a"), _expense("2026-02-02", "100", "b")]
        groups = (Shared.one(1, "a", people=2), Shared.one(2, "b", people=2))

        assert [r.state.id for r in _build(moves, groups).rows] == [2, 1]

    def test_a_group_counts_if_any_expense_is_from_the_chosen_accounts(self) -> None:
        moves = [
            _expense("2026-02-01", "1000", "a"),
            _expense("2026-02-05", "500", "b", account="pesos"),
            _expense("2026-02-06", "900", "c"),
        ]
        groups = (
            Shared(1, (SharedExpense("a", people=2), SharedExpense("b", people=2))),
            Shared.one(2, "c", people=3),
        )

        found = _build(moves, groups, chosen=frozenset({"pesos"}))

        assert [r.state.id for r in found.rows] == [1]
        assert found.owed_dop == D(750)
        assert found.open_count == 1


class TestRows:
    def test_paid_refunds_and_dates(self) -> None:
        cash = ManualEntry(9, D(300), date(2026, 2, 10), "DOP", "Ana", "")
        moves = [
            _expense("2026-02-02", "3000", "cena"),
            _expense("2026-01-15", "900", "cine"),
            _credit("2026-02-05", "1000", "toke"),
        ]
        link = Shared(
            1,
            (SharedExpense("cena", people=3), SharedExpense("cine", people=3)),
            reimbursements=("toke",),
            manual=(cash,),
        )

        [row] = _build(moves, (link,)).rows

        assert (row.first_day, row.last_day) == (date(2026, 1, 15), date(2026, 2, 2))
        assert row.last_activity == date(2026, 2, 10)
        assert row.paid == (("DOP", D(3900)),)
        assert row.reimbursed == (("DOP", D(1300)),)
        credit, manual = row.refunds
        assert (credit.key, credit.description, credit.account_label) == (
            "toke",
            "COMERCIO TOKE",
            "Corriente ···2",
        )
        assert (manual.key, manual.manual, manual.description) == ("manual:9", True, "Ana")
        # Lo devuelto salda primero el cine (el más viejo): RD$ 600 de él y 700 de la cena.
        assert row.pending == (("DOP", D(1300)),)

    def test_pending_in_dollars_uses_the_latest_rate_like_pendientes(self) -> None:
        moves = [_expense("2026-02-02", "59.50", "hotel", currency="USD")]

        found = _build(moves, (Shared.one(1, "hotel", people=2),))

        [row] = found.rows
        assert row.pending == (("USD", D("29.75")),)
        assert row.pending_dop == D("1844.50")  # 29.75 × 62 (la de febrero, la más reciente)
        assert found.owed_dop == D("1844.50")
        assert found.rate == RATES["2026-02"]

    def test_without_any_rate_the_dollars_go_apart(self) -> None:
        moves = [
            _expense("2026-02-02", "59.50", "hotel", currency="USD"),
            _expense("2026-02-03", "1000", "cena"),
        ]
        groups = (Shared.one(1, "hotel", people=2), Shared.one(2, "cena", people=2))

        found = _build(moves, groups, rates={})

        hotel = next(r for r in found.rows if r.state.id == 1)
        assert (hotel.pending_dop, hotel.unconverted_usd) == (None, D("29.75"))
        assert (found.owed_dop, found.unconverted_owed_usd) == (D(500), D("29.75"))

    def test_excess_is_kept_from_the_state(self) -> None:
        moves = [_expense("2026-02-02", "1000", "g"), _credit("2026-02-03", "800", "c")]
        [row] = _build(moves, (Shared.one(1, "g", people=2, reimbursements=("c",)),)).rows

        assert row.status == "settled"
        assert row.state.excess == {"DOP": D(300)}
        assert row.reimbursed == (("DOP", D(800)),)


class TestReimbursedThisYear:
    def test_only_refunds_of_this_year_at_the_rate_of_their_month(self) -> None:
        moves = [
            _expense("2025-12-01", "100", "hotel", currency="USD"),
            _credit("2025-12-20", "20", "viejo", currency="USD"),  # del año pasado: fuera
            _credit("2026-01-10", "30", "enero", currency="USD"),  # enero no tiene: diciembre
            _expense("2026-02-01", "1000", "cena"),
        ]
        cash = ManualEntry(1, D(500), date(2026, 2, 5), "DOP", "Ana", "")
        groups = (
            Shared.one(1, "hotel", people=2, reimbursements=("viejo", "enero")),
            Shared.one(2, "cena", people=2, manual=(cash,)),
        )

        found = _build(moves, groups)

        assert found.reimbursed_year_dop == D("1740.00") + D(500)  # 30 × 58 + RD$ 500
        assert found.unconverted_reimbursed_usd == 0

    def test_without_a_rate_the_dollars_go_apart(self) -> None:
        moves = [
            _expense("2026-01-01", "100", "hotel", currency="USD"),
            _credit("2026-01-10", "30", "enero", currency="USD"),
        ]
        groups = (Shared.one(1, "hotel", people=2, reimbursements=("enero",)),)

        found = _build(moves, groups, rates={})

        assert (found.reimbursed_year_dop, found.unconverted_reimbursed_usd) == (0, D(30))


def _picked(moves: list[Movement], found: Links, **kw) -> list[tuple[str, bool]]:
    rates = kw.pop("rates", RATES)
    picked = shared_list.new_candidates(moves, found, TODAY, rates, **kw)
    return [(c.move.fingerprint, c.suggested) for c in picked]


class TestNewCandidates:
    def test_unlinked_expenses_of_the_last_120_days_newest_first(self) -> None:
        moves = [
            _move("2026-03-10", "500", "nuevo"),
            _move("2026-01-01", "700", "viejo"),
            _move("2025-11-14", "800", "fuera"),  # 121 días antes de hoy
            _move("2026-02-01", "300", "compartido", link="shared"),
            _move("2026-02-02", "-300", "credito", category=cat.OTHER_INCOME),
            _move("2026-02-03", "5000", "cajero", category=cat.CASH),
            _move("2026-02-04", "2000", "prestamo", category=cat.LOANS),
            _move("2026-02-05", "8000", "pago", category=cat.CARD_PAYMENT),
            _move("2026-02-06", "1000", "propia", category=cat.OWN_TRANSFER),
            _move("2026-02-07", "6000", "divisas", category=cat.CURRENCY_EXCHANGE),
        ]
        found = Links(shared=(Shared.one(1, "compartido", people=2),))

        assert _picked(moves, found) == [("nuevo", False), ("viejo", False)]

    def test_an_expense_in_another_link_and_other_accounts_are_left_out(self) -> None:
        moves = [_move("2026-03-01", "500", "a"), _move("2026-03-02", "500", "b", account="pesos")]
        found = Links(shared=(Shared.one(1, "x", people=2, reimbursements=("a",)),))

        assert _picked(moves, found) == [("b", False)]
        assert _picked(moves, Links(), chosen=frozenset({"visa"})) == [("a", False)]

    def test_suggested_from_rd_2000_in_a_shareable_category(self) -> None:
        moves = [
            _move("2026-03-01", "2000", "justo"),
            _move("2026-03-02", "1999.99", "casi"),
            _move("2026-03-03", "9000", "pasaje", category=cat.TRANSPORT),
            _move("2026-03-04", "15000", "dgii", category=cat.GOVERNMENT),
            _move("2026-03-05", "2500", "super", category=cat.GROCERIES),
        ]

        assert dict(_picked(moves, Links())) == {
            "justo": True,
            "casi": False,
            "pasaje": False,
            "dgii": False,
            "super": True,
        }

    def test_dollars_at_the_rate_of_their_month_and_without_one_not_suggested(self) -> None:
        moves = [
            _move("2026-02-10", "33", "sobre", currency="USD"),  # 33 × 62 = 2,046
            _move("2026-02-11", "32", "bajo", currency="USD"),  # 32 × 62 = 1,984
            _move("2026-03-12", "40", "marzo", currency="USD"),  # sin tasa de marzo: la de febrero
        ]
        no_rate = [_move("2026-01-12", "500", "sin-tasa", currency="USD")]

        assert dict(_picked(moves, Links())) == {"sobre": True, "bajo": False, "marzo": True}
        assert _picked(no_rate, Links(), rates={}) == [("sin-tasa", False)]

    def test_suggested_first_then_the_rest_each_newest_first(self) -> None:
        moves = [
            _move("2026-03-10", "100", "chico-nuevo", category=cat.GOVERNMENT),
            _move("2026-01-05", "3000", "grande-viejo"),
            _move("2026-02-01", "50", "chico-viejo"),
            _move("2026-03-01", "4000", "grande-nuevo", category=cat.TRAVEL),
        ]

        assert _picked(moves, Links()) == [
            ("grande-nuevo", True),
            ("grande-viejo", True),
            ("chico-nuevo", False),
            ("chico-viejo", False),
        ]

    def test_a_renamed_category_still_counts_by_its_ref(self) -> None:
        renamed = replace(
            _move("2026-03-01", "2500", "cena"),
            category="Comer fuera",
            category_key=cat.RESTAURANTS,
        )
        named_like = replace(
            _move("2026-03-02", "2500", "taxi", category=cat.TRANSPORT),
            category=cat.RESTAURANTS,
            category_key=cat.TRANSPORT,
        )

        assert dict(_picked([renamed, named_like], Links())) == {"cena": True, "taxi": False}
