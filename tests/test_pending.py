"""Pendientes: quién te debe y a quién debes, sin HTTP (datos inventados)."""

from datetime import date
from decimal import Decimal

from finanzas.analysis import categories as cat
from finanzas.analysis import exchanges, shared
from finanzas.analysis.links import Exchange, Links, Shared, SharedExpense
from finanzas.analysis.rates import Rate
from finanzas.analysis.spending import Movement
from finanzas.web import pending

D = Decimal
TODAY = date(2026, 3, 15)
LABELS = {"visa": "VISA ···1", "pesos": "Corriente ···2", "dolares": "Ahorro ···3"}
RATES = {
    "2026-01": Rate(D("60.00"), "2026-01", "bcrd"),
    "2026-02": Rate(D("62.00"), "2026-02", "bcrd"),
}


def _move(
    day: str,
    amount: str,
    fp: str,
    currency: str = "DOP",
    account: str = "visa",
    note: str = "",
    link: str = "",
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=f"COMERCIO {fp.upper()}",
        description=f"DESCRIPCION {fp.upper()}",
        category=cat.THIRD_PARTY,
        amount=D(amount),
        currency=currency,
        institution="x",
        fingerprint=fp,
        account=account,
        note=note,
        link=link,
    )


def _leg(day: str, amount: str, currency: str, fp: str, note: str = "") -> Movement:
    account = "pesos" if currency == "DOP" else "dolares"
    return _move(day, amount, fp, currency, account, note, link="exchange")


def _build(
    moves: list[Movement],
    found: Links,
    rates: dict[str, Rate] | None = None,
    chosen: frozenset[str] | None = None,
) -> pending.Pending:
    by_month = RATES if rates is None else rates
    return pending.build_pending(
        moves,
        shared.states(moves, found, by_month),
        exchanges.states(moves, found),
        LABELS,
        by_month,
        TODAY,
        chosen,
    )


def _shared_dinner(written_off: bool = False) -> tuple[Movement, Shared]:
    dinner = _move("2026-02-02", "3000", "cena", link="shared", note="Cena con Ana y Luis")
    return dinner, Shared.one(1, "cena", people=3, written_off=written_off)


class TestOwedToMe:
    def test_shared_expense_with_pending(self) -> None:
        dinner, link = _shared_dinner()
        result = _build([dinner], Links(shared=(link,)))

        [item] = result.owed_to_me
        assert (item.kind, item.fingerprint, item.day) == ("shared", "cena", date(2026, 2, 2))
        assert (item.merchant, item.account_label) == ("COMERCIO CENA", "VISA ···1")
        assert (item.pending, item.currency, item.pending_dop) == (D(2000), "DOP", D(2000))
        assert item.who == "Cena con Ana y Luis"  # sin «para quién», la nota
        assert item.age_days == 41
        assert result.i_owe == ()
        assert (result.owed_to_me_dop, result.i_owe_dop, result.net_dop) == (D(2000), 0, D(2000))

    def test_for_whom_wins_over_the_note_and_a_long_note_is_cut(self) -> None:
        gift = _move("2026-02-10", "1000", "regalo", link="shared", note="x" * 80)
        link = Shared.one(1, "regalo", for_other=True, with_whom="Luis")
        long_note = _move("2026-02-11", "500", "otro", link="shared", note="nota " * 20)
        other = Shared.one(2, "otro", for_other=True)

        result = _build([gift, long_note], Links(shared=(link, other)))

        who = {i.fingerprint: i.who for i in result.owed_to_me}
        assert who["regalo"] == "Luis"
        assert len(who["otro"]) <= pending.WHO_CHARS
        assert who["otro"].endswith("…")

    def test_written_off_and_fully_reimbursed_are_left_out(self) -> None:
        dinner, link = _shared_dinner(written_off=True)
        paid = _move("2026-02-05", "1000", "pagado", link="shared")
        back = _move("2026-02-06", "-500", "toke", link="reimbursement")
        done = Shared.one(2, "pagado", people=2, reimbursements=("toke",))

        result = _build([dinner, paid, back], Links(shared=(link, done)))

        assert result.owed_to_me == ()
        assert result.owed_to_me_dop == 0

    def test_exchange_where_you_gave_first(self) -> None:
        # Diste RD$ 120,000 a 60 (US$ 2,000) y te devolvieron US$ 1,500: te deben US$ 500.
        sent = _leg("2026-01-10", "120000", "DOP", "envio", note="Cambio con Pedro")
        back = _leg("2026-01-12", "-1500", "USD", "vuelta")
        found = Links(exchanges=(Exchange(1, ("envio", "vuelta"), agreed_rate=D(60)),))

        result = _build([sent, back], found)

        [item] = result.owed_to_me
        assert (item.kind, item.fingerprint, item.account_label) == (
            "exchange",
            "envio",
            "Corriente ···2",
        )
        assert (item.pending, item.currency) == (D(500), "USD")
        # A la tasa del cambio (la acordada, 60), no a la más reciente (feb, 62).
        assert (item.pending_dop, item.rate) == (D(30000), D(60))
        assert item.who == "Cambio con Pedro"


class TestIOwe:
    def test_exchange_where_they_gave_first(self) -> None:
        # Te depositaron RD$ 60,000 a 60 (US$ 1,000) y enviaste US$ 400: debes US$ 600.
        came = _leg("2026-02-01", "-60000", "DOP", "deposito")
        sent = _leg("2026-02-03", "400", "USD", "envio")
        found = Links(exchanges=(Exchange(1, ("envio", "deposito"), agreed_rate=D(60)),))

        result = _build([came, sent], found)

        assert result.owed_to_me == ()
        [item] = result.i_owe
        assert (item.fingerprint, item.pending, item.currency) == ("deposito", D(600), "USD")
        assert (result.i_owe_dop, result.net_dop) == (D(36000), D(-36000))

    def test_pending_in_pesos_has_no_conversion(self) -> None:
        # Te depositaron US$ 1,000 a 60 y devolviste RD$ 50,000: debes RD$ 10,000.
        came = _leg("2026-02-01", "-1000", "USD", "deposito")
        sent = _leg("2026-02-02", "50000", "DOP", "envio")
        found = Links(exchanges=(Exchange(1, ("deposito", "envio"), agreed_rate=D(60)),))

        [item] = _build([came, sent], found).i_owe
        assert (item.pending, item.currency, item.pending_dop) == (D(10000), "DOP", D(10000))

    def test_implied_rate_without_an_agreed_one(self) -> None:
        # Primer par a 60 (RD$ 60,000 por US$ 1,000) y otro depósito de RD$ 12,000 el día
        # siguiente: debes US$ 200, que a la tasa implícita son RD$ 12,000.
        came = _leg("2026-02-01", "-60000", "DOP", "deposito")
        more = _leg("2026-02-02", "-12000", "DOP", "otro")
        sent = _leg("2026-02-01", "1000", "USD", "envio")
        found = Links(exchanges=(Exchange(1, ("deposito", "envio", "otro")),))

        [item] = _build([came, more, sent], found).i_owe
        assert (item.pending, item.rate, item.pending_dop) == (D(200), D(60), D(12000))

    def test_same_day_first_pair_follows_the_base_side(self) -> None:
        # Las dos patas el mismo día: la base es la primera agregada (aquí, la de US$, que
        # salió). Tú diste primero: te deben, aunque la de RD$ sea un crédito.
        sent = _leg("2026-02-01", "1000", "USD", "envio")
        came = _leg("2026-02-01", "-50000", "DOP", "deposito")
        found = Links(exchanges=(Exchange(1, ("envio", "deposito"), agreed_rate=D(60)),))

        result = _build([came, sent], found)  # el orden de los movimientos no importa

        assert result.i_owe == ()
        [item] = result.owed_to_me
        assert (item.fingerprint, item.pending, item.currency) == ("envio", D(10000), "DOP")

    def test_closed_or_complete_exchanges_are_left_out(self) -> None:
        came = _leg("2026-02-01", "-60000", "DOP", "deposito")
        sent = _leg("2026-02-03", "400", "USD", "envio")
        closed = Links(exchanges=(Exchange(1, ("deposito", "envio"), D(60), closed=True),))
        assert _build([came, sent], closed).i_owe == ()
        # Sin tasa acordada, solo el primer par: el pendiente es 0.
        first_pair = Links(exchanges=(Exchange(1, ("deposito", "envio")),))
        assert _build([came, sent], first_pair).i_owe == ()


class TestTotals:
    def test_shared_dollars_without_any_rate_go_apart_but_exchanges_never(self) -> None:
        came = _leg("2026-02-01", "-60000", "DOP", "deposito")
        sent = _leg("2026-02-03", "400", "USD", "envio")
        found = Links(exchanges=(Exchange(1, ("deposito", "envio"), agreed_rate=D(60)),))
        hotel = _move("2026-02-04", "300", "hotel", "USD", link="shared")
        link = Shared.one(2, "hotel", people=3)

        result = _build([came, sent, hotel], Links(shared=(link,), exchanges=found.exchanges), {})

        [owe] = result.i_owe
        assert (owe.pending_dop, owe.rate) == (D(36000), D(60))  # la del cambio, siempre
        assert (result.i_owe_dop, result.unconverted_i_owe) == (D(36000), 0)
        [stay] = result.owed_to_me
        assert (stay.pending, stay.pending_dop, stay.rate) == (D(200), None, None)
        assert (result.owed_to_me_dop, result.unconverted_owed_to_me) == (0, D(200))
        assert result.rate is None

    def test_shared_dollars_with_a_reimbursement_in_pesos(self) -> None:
        # Hotel de US$ 100 entre dos; te devolvieron RD$ 1,240 en febrero (a 62: US$ 20).
        hotel = _move("2026-01-20", "100", "hotel", "USD", link="shared")
        back = _move("2026-02-10", "-1240", "toke", "DOP", "pesos", link="reimbursement")
        link = Shared.one(1, "hotel", people=2, reimbursements=("toke",))

        result = _build([hotel, back], Links(shared=(link,)))

        [item] = result.owed_to_me
        assert (item.pending, item.currency) == (D(30), "USD")
        # Lo que falta, a la tasa más reciente (feb, 62), que es la que se usó.
        assert (item.pending_dop, item.rate) == (D(1860), D(62))
        assert result.rate is not None and result.rate.month_used == "2026-02"

    def test_a_dormant_shared_link_is_left_out(self) -> None:
        # El gasto ya no aparece (o dejó de ser gasto): el vínculo queda dormido.
        gone = Shared.one(1, "ya-no-esta", people=2)
        no_longer = _move("2026-02-01", "1000", "otro")  # sin link="shared"
        found = Links(shared=(gone, Shared.one(2, "otro", people=2)))

        assert _build([no_longer], found).owed_to_me == ()

    def test_account_filter(self) -> None:
        dinner, link = _shared_dinner()
        came = _leg("2026-02-01", "-60000", "DOP", "deposito")
        sent = _leg("2026-02-03", "400", "USD", "envio")
        found = Links(
            shared=(link,), exchanges=(Exchange(1, ("deposito", "envio"), agreed_rate=D(60)),)
        )
        moves = [dinner, came, sent]

        only_dollars = _build(moves, found, chosen=frozenset({"dolares"}))
        assert only_dollars.owed_to_me == ()  # el gasto es de la VISA
        assert [i.fingerprint for i in only_dollars.i_owe] == ["envio"]  # su pata de esa cuenta
        only_card = _build(moves, found, chosen=frozenset({"visa"}))  # ninguna pata
        assert [i.fingerprint for i in only_card.owed_to_me] == ["cena"]
        assert only_card.i_owe == ()

    def test_an_exchange_across_selected_and_other_accounts(self) -> None:
        # La primera pata es de una cuenta no elegida: la fila es la de la cuenta elegida, una
        # sola vez, aunque el cambio tenga varias patas en ella.
        came = _leg("2026-02-01", "-60000", "DOP", "deposito")
        sent = _leg("2026-02-03", "300", "USD", "envio")
        again = _leg("2026-02-05", "100", "USD", "otra")
        found = Links(exchanges=(Exchange(1, ("deposito", "envio", "otra"), agreed_rate=D(60)),))

        result = _build([came, sent, again], found, chosen=frozenset({"dolares"}))

        [item] = result.i_owe
        assert (item.fingerprint, item.account_label) == ("envio", "Ahorro ···3")
        assert (item.pending, item.day) == (D(600), date(2026, 2, 1))  # desde la primera pata
        assert result.owed_to_me == ()

    def test_oldest_first(self) -> None:
        newer = _move("2026-02-20", "900", "nuevo", link="shared")
        older = _move("2026-01-05", "900", "viejo", link="shared")
        sent = _leg("2026-01-20", "120000", "DOP", "envio")
        back = _leg("2026-01-22", "-1500", "USD", "vuelta")
        found = Links(
            shared=(
                Shared.one(1, "nuevo", people=3),
                Shared.one(2, "viejo", people=3),
            ),
            exchanges=(Exchange(3, ("envio", "vuelta"), agreed_rate=D(60)),),
        )

        result = _build([newer, older, sent, back], found)

        assert [i.fingerprint for i in result.owed_to_me] == ["viejo", "envio", "nuevo"]


class TestGroups:
    """Un grupo de varios gastos es una sola fila: su título, cuántos gastos y lo pendiente por
    moneda (≈ RD$ con la tasa más reciente)."""

    def _trip(self) -> tuple[list[Movement], Links]:
        flights = _move("2026-01-10", "100", "vuelos", currency="USD", link="shared")
        agency = _move("2026-02-01", "12000", "agencia", account="pesos", link="shared")
        link = Shared(
            1,
            (SharedExpense("vuelos", for_other=True), SharedExpense("agencia", people=2)),
            with_whom="Carola y Rafael",
            name="Viaje Isla Ficticia",
        )
        return [flights, agency], Links(shared=(link,))

    def test_one_row_per_group_with_both_currencies(self) -> None:
        moves, found = self._trip()
        [item] = _build(moves, found).owed_to_me
        assert (item.fingerprint, item.merchant, item.who, item.expense_count) == (
            "vuelos",
            "Viaje Isla Ficticia",
            "Carola y Rafael",
            2,
        )
        assert item.parts == (("DOP", D(6000)), ("USD", D(100)))
        assert item.pending_dop == D(6000) + D(100) * D("62.00")
        assert (item.day, item.age_days) == (date(2026, 1, 10), 64)

    def test_without_a_rate_the_dollars_stay_aside(self) -> None:
        moves, found = self._trip()
        result = _build(moves, found, rates={})
        [item] = result.owed_to_me
        assert item.pending_dop == D(6000)
        assert result.unconverted_owed_to_me == D(100)

    def test_a_group_counts_if_any_expense_is_in_the_chosen_accounts(self) -> None:
        moves, found = self._trip()
        [item] = _build(moves, found, chosen=frozenset({"pesos"})).owed_to_me
        assert item.account_label == LABELS["pesos"]
        assert _build(moves, found, chosen=frozenset({"dolares"})).owed_to_me == ()
