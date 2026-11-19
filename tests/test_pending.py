"""Pending: who owes you and whom you owe, without HTTP (made-up data)."""

from datetime import date
from decimal import Decimal

from michelito.analysis import categories as cat
from michelito.analysis import exchanges, shared
from michelito.analysis.links import Exchange, Links, Shared, SharedExpense
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from michelito.web import pending

D = Decimal
TODAY = date(2026, 3, 15)
LABELS = {"visa": "VISA ···1", "dop": "Checking ···2", "usd": "Savings ···3"}
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
    account = "dop" if currency == "DOP" else "usd"
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
    dinner = _move("2026-02-02", "3000", "dinner", link="shared", note="Dinner with Ana and Luis")
    return dinner, Shared.one(1, "dinner", people=3, written_off=written_off)


class TestOwedToMe:
    def test_shared_expense_with_pending(self) -> None:
        dinner, link = _shared_dinner()
        result = _build([dinner], Links(shared=(link,)))

        [item] = result.owed_to_me
        assert (item.kind, item.fingerprint, item.day) == ("shared", "dinner", date(2026, 2, 2))
        assert (item.merchant, item.account_label) == ("COMERCIO DINNER", "VISA ···1")
        assert (item.pending, item.currency, item.pending_dop) == (D(2000), "DOP", D(2000))
        assert item.who == "Dinner with Ana and Luis"  # no "for whom": the note
        assert item.age_days == 41
        assert result.i_owe == ()
        assert (result.owed_to_me_dop, result.i_owe_dop, result.net_dop) == (D(2000), 0, D(2000))

    def test_for_whom_wins_over_the_note_and_a_long_note_is_cut(self) -> None:
        gift = _move("2026-02-10", "1000", "gift", link="shared", note="x" * 80)
        link = Shared.one(1, "gift", for_other=True, with_whom="Luis")
        long_note = _move("2026-02-11", "500", "other", link="shared", note="note " * 20)
        other = Shared.one(2, "other", for_other=True)

        result = _build([gift, long_note], Links(shared=(link, other)))

        who = {i.fingerprint: i.who for i in result.owed_to_me}
        assert who["gift"] == "Luis"
        assert len(who["other"]) <= pending.WHO_CHARS
        assert who["other"].endswith("…")

    def test_written_off_and_fully_reimbursed_are_left_out(self) -> None:
        dinner, link = _shared_dinner(written_off=True)
        paid = _move("2026-02-05", "1000", "paid", link="shared")
        back = _move("2026-02-06", "-500", "toke", link="reimbursement")
        done = Shared.one(2, "paid", people=2, reimbursements=("toke",))

        result = _build([dinner, paid, back], Links(shared=(link, done)))

        assert result.owed_to_me == ()
        assert result.owed_to_me_dop == 0

    def test_exchange_where_you_gave_first(self) -> None:
        # You gave RD$ 120,000 at 60 (US$ 2,000) and got US$ 1,500 back: you are owed US$ 500.
        sent = _leg("2026-01-10", "120000", "DOP", "sent", note="Exchange with Pedro")
        back = _leg("2026-01-12", "-1500", "USD", "back")
        found = Links(exchanges=(Exchange(1, ("sent", "back"), agreed_rate=D(60)),))

        result = _build([sent, back], found)

        [item] = result.owed_to_me
        assert (item.kind, item.fingerprint, item.account_label) == (
            "exchange",
            "sent",
            "Checking ···2",
        )
        assert (item.pending, item.currency) == (D(500), "USD")
        # At the exchange's rate (the agreed one, 60), not the latest one (Feb, 62).
        assert (item.pending_dop, item.rate) == (D(30000), D(60))
        assert item.who == "Exchange with Pedro"


class TestIOwe:
    def test_exchange_where_they_gave_first(self) -> None:
        # You received RD$ 60,000 at 60 (US$ 1,000) and sent US$ 400: you owe US$ 600.
        came = _leg("2026-02-01", "-60000", "DOP", "deposit")
        sent = _leg("2026-02-03", "400", "USD", "sent")
        found = Links(exchanges=(Exchange(1, ("sent", "deposit"), agreed_rate=D(60)),))

        result = _build([came, sent], found)

        assert result.owed_to_me == ()
        [item] = result.i_owe
        assert (item.fingerprint, item.pending, item.currency) == ("deposit", D(600), "USD")
        assert (result.i_owe_dop, result.net_dop) == (D(36000), D(-36000))

    def test_pending_in_dop_has_no_conversion(self) -> None:
        # You received US$ 1,000 at 60 and returned RD$ 50,000: you owe RD$ 10,000.
        came = _leg("2026-02-01", "-1000", "USD", "deposit")
        sent = _leg("2026-02-02", "50000", "DOP", "sent")
        found = Links(exchanges=(Exchange(1, ("deposit", "sent"), agreed_rate=D(60)),))

        [item] = _build([came, sent], found).i_owe
        assert (item.pending, item.currency, item.pending_dop) == (D(10000), "DOP", D(10000))

    def test_implied_rate_without_an_agreed_one(self) -> None:
        # First pair at 60 (RD$ 60,000 for US$ 1,000) and another RD$ 12,000 deposit the next
        # day: you owe US$ 200, which at the implied rate is RD$ 12,000.
        came = _leg("2026-02-01", "-60000", "DOP", "deposit")
        more = _leg("2026-02-02", "-12000", "DOP", "other")
        sent = _leg("2026-02-01", "1000", "USD", "sent")
        found = Links(exchanges=(Exchange(1, ("deposit", "sent", "other")),))

        [item] = _build([came, more, sent], found).i_owe
        assert (item.pending, item.rate, item.pending_dop) == (D(200), D(60), D(12000))

    def test_same_day_first_pair_follows_the_base_side(self) -> None:
        # Both legs on the same day: the base is the first one added (here the US$ one, which
        # went out). You gave first: you are owed, even though the RD$ leg is a credit.
        sent = _leg("2026-02-01", "1000", "USD", "sent")
        came = _leg("2026-02-01", "-50000", "DOP", "deposit")
        found = Links(exchanges=(Exchange(1, ("sent", "deposit"), agreed_rate=D(60)),))

        result = _build([came, sent], found)  # the order of the movements does not matter

        assert result.i_owe == ()
        [item] = result.owed_to_me
        assert (item.fingerprint, item.pending, item.currency) == ("sent", D(10000), "DOP")

    def test_closed_or_complete_exchanges_are_left_out(self) -> None:
        came = _leg("2026-02-01", "-60000", "DOP", "deposit")
        sent = _leg("2026-02-03", "400", "USD", "sent")
        closed = Links(exchanges=(Exchange(1, ("deposit", "sent"), D(60), closed=True),))
        assert _build([came, sent], closed).i_owe == ()
        # No agreed rate, only the first pair: nothing is pending.
        first_pair = Links(exchanges=(Exchange(1, ("deposit", "sent")),))
        assert _build([came, sent], first_pair).i_owe == ()


class TestTotals:
    def test_shared_dollars_without_any_rate_go_apart_but_exchanges_never(self) -> None:
        came = _leg("2026-02-01", "-60000", "DOP", "deposit")
        sent = _leg("2026-02-03", "400", "USD", "sent")
        found = Links(exchanges=(Exchange(1, ("deposit", "sent"), agreed_rate=D(60)),))
        hotel = _move("2026-02-04", "300", "hotel", "USD", link="shared")
        link = Shared.one(2, "hotel", people=3)

        result = _build([came, sent, hotel], Links(shared=(link,), exchanges=found.exchanges), {})

        [owe] = result.i_owe
        assert (owe.pending_dop, owe.rate) == (D(36000), D(60))  # the exchange's, always
        assert (result.i_owe_dop, result.unconverted_i_owe) == (D(36000), 0)
        [stay] = result.owed_to_me
        assert (stay.pending, stay.pending_dop, stay.rate) == (D(200), None, None)
        assert (result.owed_to_me_dop, result.unconverted_owed_to_me) == (0, D(200))
        assert result.rate is None

    def test_shared_dollars_with_a_reimbursement_in_dop(self) -> None:
        # A US$ 100 hotel split in two; you got RD$ 1,240 back in February (at 62: US$ 20).
        hotel = _move("2026-01-20", "100", "hotel", "USD", link="shared")
        back = _move("2026-02-10", "-1240", "toke", "DOP", "dop", link="reimbursement")
        link = Shared.one(1, "hotel", people=2, reimbursements=("toke",))

        result = _build([hotel, back], Links(shared=(link,)))

        [item] = result.owed_to_me
        assert (item.pending, item.currency) == (D(30), "USD")
        # What is left, at the latest rate (Feb, 62), which is the one used.
        assert (item.pending_dop, item.rate) == (D(1860), D(62))
        assert result.rate is not None and result.rate.month_used == "2026-02"

    def test_a_dormant_shared_link_is_left_out(self) -> None:
        # The expense is gone (or is no longer an expense): the link lies dormant.
        gone = Shared.one(1, "gone", people=2)
        no_longer = _move("2026-02-01", "1000", "other")  # no link="shared"
        found = Links(shared=(gone, Shared.one(2, "other", people=2)))

        assert _build([no_longer], found).owed_to_me == ()

    def test_account_filter(self) -> None:
        dinner, link = _shared_dinner()
        came = _leg("2026-02-01", "-60000", "DOP", "deposit")
        sent = _leg("2026-02-03", "400", "USD", "sent")
        found = Links(
            shared=(link,), exchanges=(Exchange(1, ("deposit", "sent"), agreed_rate=D(60)),)
        )
        moves = [dinner, came, sent]

        only_dollars = _build(moves, found, chosen=frozenset({"usd"}))
        assert only_dollars.owed_to_me == ()  # the expense is on the VISA
        assert [i.fingerprint for i in only_dollars.i_owe] == ["sent"]  # its leg in that account
        only_card = _build(moves, found, chosen=frozenset({"visa"}))  # no leg
        assert [i.fingerprint for i in only_card.owed_to_me] == ["dinner"]
        assert only_card.i_owe == ()

    def test_an_exchange_across_selected_and_other_accounts(self) -> None:
        # The first leg is in an account that is not chosen: the row is the chosen account's,
        # once, even though the exchange has several legs in it.
        came = _leg("2026-02-01", "-60000", "DOP", "deposit")
        sent = _leg("2026-02-03", "300", "USD", "sent")
        again = _leg("2026-02-05", "100", "USD", "again")
        found = Links(exchanges=(Exchange(1, ("deposit", "sent", "again"), agreed_rate=D(60)),))

        result = _build([came, sent, again], found, chosen=frozenset({"usd"}))

        [item] = result.i_owe
        assert (item.fingerprint, item.account_label) == ("sent", "Savings ···3")
        assert (item.pending, item.day) == (D(600), date(2026, 2, 1))  # since the first leg
        assert result.owed_to_me == ()

    def test_oldest_first(self) -> None:
        newer = _move("2026-02-20", "900", "newer", link="shared")
        older = _move("2026-01-05", "900", "older", link="shared")
        sent = _leg("2026-01-20", "120000", "DOP", "sent")
        back = _leg("2026-01-22", "-1500", "USD", "back")
        found = Links(
            shared=(
                Shared.one(1, "newer", people=3),
                Shared.one(2, "older", people=3),
            ),
            exchanges=(Exchange(3, ("sent", "back"), agreed_rate=D(60)),),
        )

        result = _build([newer, older, sent, back], found)

        assert [i.fingerprint for i in result.owed_to_me] == ["older", "sent", "newer"]


class TestGroups:
    """A group of several expenses is a single row: its title, how many expenses and what is
    pending per currency (≈ RD$ at the latest rate)."""

    def _trip(self) -> tuple[list[Movement], Links]:
        flights = _move("2026-01-10", "100", "flights", currency="USD", link="shared")
        agency = _move("2026-02-01", "12000", "agency", account="dop", link="shared")
        link = Shared(
            1,
            (SharedExpense("flights", for_other=True), SharedExpense("agency", people=2)),
            with_whom="Carola and Rafael",
            name="Fictional Island trip",
        )
        return [flights, agency], Links(shared=(link,))

    def test_one_row_per_group_with_both_currencies(self) -> None:
        moves, found = self._trip()
        [item] = _build(moves, found).owed_to_me
        assert (item.fingerprint, item.merchant, item.who, item.expense_count) == (
            "flights",
            "Fictional Island trip",
            "Carola and Rafael",
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
        [item] = _build(moves, found, chosen=frozenset({"dop"})).owed_to_me
        assert item.account_label == LABELS["dop"]
        assert _build(moves, found, chosen=frozenset({"usd"})).owed_to_me == ()
