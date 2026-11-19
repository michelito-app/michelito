from datetime import date
from decimal import Decimal

import pytest

from michelito import db
from michelito.analysis import categories as cat
from michelito.analysis import corrections, spending, transfers
from michelito.analysis.accounts import AccountInfo
from michelito.analysis.spending import Movement
from michelito.config import default_paths
from michelito.parsers import popular_account
from tests import samples
from tests.test_spending import _add_bank_rows, seed

OWN = AccountInfo(
    key="bhd:savings:555-0042",
    kind="savings",
    label="BHD Ahorro",  # spanish-data
    through=None,
)
OTHER = AccountInfo(key="popular:checking:700-1234567", kind="checking", label="P", through=None)
CARD = AccountInfo(key="bhd:credit_card", kind="credit_card", label="BHD", through=None)
ACCOUNTS = (OWN, OTHER, CARD)


def mv(
    day: str,
    description: str,
    amount: str,
    account: str = OWN.key,
    currency: str = "DOP",
    category: str = cat.OTHER,
    mark: str = "",
) -> Movement:
    return Movement(
        day=date.fromisoformat(day),
        merchant=description,
        description=description,
        category=category,
        amount=Decimal(amount),
        currency=currency,
        institution="x",
        fingerprint=mark or f"{account}|{day}|{description}|{amount}",
        account=account,
        original_category=category,
    )


def card_payment(day: str, amount: str, currency: str = "DOP") -> Movement:
    return mv(day, "SU PAGO GRACIAS", f"-{amount}", CARD.key, currency, cat.CARD_PAYMENT)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    seed(connection)
    yield connection
    connection.close()


class TestLoadHolders:
    def test_missing_file_is_empty(self, tmp_path) -> None:
        # Used to be `== ()`: now names and numbers apart, both empty.
        assert transfers.load_holders(tmp_path / "holders.txt") == transfers.Holders()

    def test_normalizes_and_skips_blank_lines(self, tmp_path) -> None:
        path = tmp_path / "holders.txt"
        path.write_text(
            "  María  Pérez-Inventada \n\n\nJUAN PÉREZ\nmaría pérez inventada\n"  # spanish-data
        )
        # `load_holders` used to return the tuple of names; now names and numbers apart.
        assert transfers.load_holders(path).names == ("MARIA PEREZ INVENTADA", "JUAN PEREZ")

    def test_digit_only_lines_are_own_account_numbers(self, tmp_path) -> None:
        path = tmp_path / "holders.txt"
        path.write_text("MARIA PEREZ INVENTADA\n000-123456-7\n 0099887766 \n12345\n12 34 56 78\n")
        loaded = transfers.load_holders(path)
        # "12345": digits only, but too short for an account number; ignored.
        assert loaded.names == ("MARIA PEREZ INVENTADA",)
        assert loaded.numbers == (1234567, 99887766, 12345678)

    def test_missing_file_has_no_numbers(self, tmp_path) -> None:
        assert transfers.load_holders(tmp_path / "holders.txt").numbers == ()

    def test_paths_expose_holders_file(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("MICHELITO_DATA_DIR", str(tmp_path))
        assert default_paths().holders == tmp_path / "holders.txt"


class TestPairing:
    def test_debit_matching_a_card_payment_within_days(self) -> None:
        debit = mv("2026-01-08", "TRANSF INVENTADA XYZ", "5000")
        found = transfers.detect_transfers(
            [card_payment("2026-01-05", "5000"), debit], ACCOUNTS, ()
        )
        assert found[debit.fingerprint] == cat.CARD_PAYMENT

    def test_payment_before_debit_also_pairs(self) -> None:
        debit = mv("2026-01-02", "TRANSF INVENTADA XYZ", "5000")
        found = transfers.detect_transfers(
            [card_payment("2026-01-05", "5000"), debit], ACCOUNTS, ()
        )
        assert found[debit.fingerprint] == cat.CARD_PAYMENT

    def test_six_days_apart_does_not_pair(self) -> None:
        debit = mv("2026-01-11", "TRANSF INVENTADA XYZ", "5000")
        found = transfers.detect_transfers(
            [card_payment("2026-01-05", "5000"), debit], ACCOUNTS, ()
        )
        assert debit.fingerprint not in found

    def test_exactly_five_days_pairs(self) -> None:
        debit = mv("2026-01-10", "TRANSF INVENTADA XYZ", "5000")
        found = transfers.detect_transfers(
            [card_payment("2026-01-05", "5000"), debit], ACCOUNTS, ()
        )
        assert found[debit.fingerprint] == cat.CARD_PAYMENT

    def test_different_amount_or_currency_does_not_pair(self) -> None:
        other_amount = mv("2026-01-06", "TRANSF INVENTADA XYZ", "5000.01")
        other_currency = mv("2026-01-06", "OTRA COSA ABC", "5000", currency="USD")
        found = transfers.detect_transfers(
            [card_payment("2026-01-05", "5000"), other_amount, other_currency], ACCOUNTS, ()
        )
        assert other_amount.fingerprint not in found
        assert other_currency.fingerprint not in found

    def test_each_payment_pairs_with_one_debit(self) -> None:
        first = mv("2026-01-06", "TRANSF INVENTADA UNO", "5000")
        second = mv("2026-01-07", "TRANSF INVENTADA DOS", "5000")
        found = transfers.detect_transfers(
            [card_payment("2026-01-05", "5000"), first, second], ACCOUNTS, ()
        )
        assert found[first.fingerprint] == cat.CARD_PAYMENT
        assert second.fingerprint not in found

    def test_credit_never_pairs(self) -> None:
        credit = mv("2026-01-06", "DEPOSITO INVENTADO", "-5000")
        found = transfers.detect_transfers(
            [card_payment("2026-01-05", "5000"), credit], ACCOUNTS, ()
        )
        assert credit.fingerprint not in found

    def test_card_payments_are_reported(self) -> None:
        payment = card_payment("2026-01-05", "5000")
        assert transfers.detect_transfers([payment], ACCOUNTS, ()) == {
            payment.fingerprint: cat.CARD_PAYMENT
        }


class TestPhrasing:
    @pytest.mark.parametrize(
        "text",
        [
            "PAGO DE TC 5100 XXXX XXXX 9999",
            "PAGO TARJETA INVENTADA",
            "Pago a Tarjeta",  # spanish-data
        ],
    )
    def test_card_payment_wording_without_pairing(self, text) -> None:
        debit = mv("2026-01-10", text, "3000")
        found = transfers.detect_transfers([debit], ACCOUNTS, ())
        assert found[debit.fingerprint] == cat.CARD_PAYMENT

    def test_payment_wording_on_a_credit_is_not_a_card_payment(self) -> None:
        credit = mv("2026-01-10", "PAGO INTERESES CA", "-0.50")
        assert transfers.detect_transfers([credit], ACCOUNTS, ()) == {}

    def test_plain_payment_without_card_word_is_not_detected(self) -> None:
        debit = mv("2026-01-10", "PAGO SERVICIO INVENTADO", "300")
        assert transfers.detect_transfers([debit], ACCOUNTS, ()) == {}


class TestHolders:
    def test_holder_name_means_own_transfer(self) -> None:
        sent = mv("2026-01-10", "TRANSF A MARIA PEREZ INVENTADA", "900")
        received = mv(
            "2026-01-11",
            "Transferencia de María Pérez Inventada",  # spanish-data
            "-900",
        )
        found = transfers.detect_transfers([sent, received], ACCOUNTS, ("MARIA PEREZ INVENTADA",))
        assert found == {sent.fingerprint: cat.OWN_TRANSFER, received.fingerprint: cat.OWN_TRANSFER}

    def test_holder_must_be_a_whole_word_match(self) -> None:
        other = mv("2026-01-10", "TRANSF A MARIA PEREZ INVENTADAS", "900")
        assert transfers.detect_transfers([other], ACCOUNTS, ("MARIA PEREZ INVENTADA",)) == {}

    def test_without_holders_nothing_is_detected(self) -> None:
        assert (
            transfers.detect_transfers([mv("2026-01-10", "MARIA PEREZ", "9")], ACCOUNTS, ()) == {}
        )

    def test_blank_holder_is_ignored(self) -> None:
        assert (
            transfers.detect_transfers([mv("2026-01-10", "ALGO", "9")], ACCOUNTS, ("", " ")) == {}
        )


class TestAccountNumbers:
    def test_last_four_of_another_account(self) -> None:
        sent = mv("2026-01-10", "TRANSF CTA XXX4567 INVENTADA", "900")
        found = transfers.detect_transfers([sent], ACCOUNTS, ())
        assert found[sent.fingerprint] == cat.OWN_TRANSFER

    def test_last_four_as_masked_number(self) -> None:
        sent = mv("2026-01-10", "TRANSF A CUENTA ****4567", "900")
        assert transfers.detect_transfers([sent], ACCOUNTS, ())[sent.fingerprint] == (
            cat.OWN_TRANSFER
        )

    def test_never_matches_the_account_itself(self) -> None:
        own = mv("2026-01-10", "TRANSF CTA 555-0042", "900", account=OWN.key)
        assert transfers.detect_transfers([own], ACCOUNTS, ()) == {}

    def test_short_digit_groups_are_not_numbers(self) -> None:
        # "999-1" and "555-0042": only the 4-digit group counts, and a lone "1" does not.
        short = AccountInfo(key="bhd:savings:999-1", kind="savings", label="S", through=None)
        text = mv("2026-01-10", "COMPRA 1 TIENDA", "9")
        assert transfers.detect_transfers([text], (OWN, short), ()) == {}

    def test_full_account_number_does_not_match_on_purpose(self) -> None:
        full = mv("2026-01-10", "TRANSF CTA 001234567 INVENTADA", "900")
        assert transfers.detect_transfers([full], ACCOUNTS, ()) == {}

    def test_card_purchases_are_never_own_transfers(self) -> None:
        store = mv("2026-01-10", "TIENDA 4567 INVENTADA", "900", account=CARD.key)
        named = mv("2026-01-10", "TIENDA MARIA PEREZ INVENTADA", "900", account=CARD.key)
        found = transfers.detect_transfers([store, named], ACCOUNTS, ("MARIA PEREZ INVENTADA",))
        assert found == {}

    def test_token_must_match_whole(self) -> None:
        partial = mv("2026-01-10", "REF 14567 INVENTADA", "900")
        assert transfers.detect_transfers([partial], ACCOUNTS, ()) == {}

    def test_card_last_four_from_the_cards_table(self) -> None:
        sent = mv("2026-01-10", "TRANSF INVENTADA 9999", "900", account=OWN.key)
        found = transfers.detect_transfers([sent], ACCOUNTS, (), card_last4={CARD.key: ("9999",)})
        assert found[sent.fingerprint] == cat.OWN_TRANSFER

    def test_card_last_four_never_matches_that_card(self) -> None:
        own = mv("2026-01-10", "COMPRA 9999 INVENTADA", "900", account=CARD.key)
        assert (
            transfers.detect_transfers([own], ACCOUNTS, (), card_last4={CARD.key: ("9999",)}) == {}
        )


class TestLoadAll:
    def _by_text(self, conn, holders=()) -> dict[str, Movement]:
        return {m.description: m for m in spending.load_all(conn, holders)}

    def test_existing_callers_work_without_holders(self, conn) -> None:
        assert spending.load_all(conn) == spending.load_all(conn, ())

    def test_card_payment_wording_in_bank_is_transfer_not_expense(self, conn) -> None:
        debit = self._by_text(conn)["PAGO DE TC 5100 XXXX XXXX 9999"]
        assert (debit.kind, debit.category) == ("transfer", cat.CARD_PAYMENT)
        assert debit.fingerprint not in {m.fingerprint for m in spending.load_movements(conn)}

    def test_pairing_at_three_days_but_not_six(self, conn) -> None:
        # Popular received a 5,000.00 payment on 01/05.
        _add_bank_rows(
            conn,
            [
                ("2026-01-08", "ENVIO INVENTADO TRES DIAS", "debit", "500000"),
                ("2026-01-11", "ENVIO INVENTADO SEIS DIAS", "debit", "500000"),
            ],
        )
        found = self._by_text(conn)
        assert found["ENVIO INVENTADO TRES DIAS"].category == cat.CARD_PAYMENT
        # Used to be "expense": unpaired, a debit without a rule is a third-party transfer.
        assert found["ENVIO INVENTADO SEIS DIAS"].category == cat.THIRD_PARTY

    def test_holder_makes_own_transfer(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-12", "ENVIO A MARIA PEREZ INVENTADA", "debit", "70000")])
        movement = self._by_text(conn, ("MARIA PEREZ INVENTADA",))["ENVIO A MARIA PEREZ INVENTADA"]
        assert (movement.category, movement.kind) == (cat.OWN_TRANSFER, "transfer")
        assert movement.original_category == cat.OWN_TRANSFER
        # Used to be "expense": without holders, the transfer goes to a third party.
        assert self._by_text(conn)["ENVIO A MARIA PEREZ INVENTADA"].category == cat.THIRD_PARTY

    def test_card_last_four_in_a_bank_description(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-12", "ENVIO A PRODUCTO 1234 INVENTADO", "debit", "70000")])
        movement = self._by_text(conn)["ENVIO A PRODUCTO 1234 INVENTADO"]
        assert movement.category == cat.OWN_TRANSFER

    def test_user_correction_wins_and_keeps_detected_original(self, conn) -> None:
        mark = self._by_text(conn)["PAGO DE TC 5100 XXXX XXXX 9999"].fingerprint
        corrections.set_transaction_category(conn, mark, cat.GROCERIES)
        fixed = self._by_text(conn)["PAGO DE TC 5100 XXXX XXXX 9999"]
        assert (fixed.category, fixed.corrected) == (cat.GROCERIES, True)
        assert fixed.original_category == cat.CARD_PAYMENT
        assert fixed.fingerprint == mark

    def test_merchant_correction_wins_over_detection(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-12", "ENVIO A MARIA PEREZ INVENTADA", "debit", "70000")])
        movement = self._by_text(conn, ("MARIA PEREZ INVENTADA",))["ENVIO A MARIA PEREZ INVENTADA"]
        corrections.set_merchant_category(conn, movement.merchant, cat.HEALTH)
        fixed = self._by_text(conn, ("MARIA PEREZ INVENTADA",))["ENVIO A MARIA PEREZ INVENTADA"]
        assert (fixed.category, fixed.corrected) == (cat.HEALTH, True)

    def test_fingerprints_do_not_change(self, conn) -> None:
        plain = {m.description: m.fingerprint for m in spending.load_all(conn)}
        with_holders = {m.description: m.fingerprint for m in spending.load_all(conn, ("X Y",))}
        assert plain == with_holders


def test_undecodable_holders_file_counts_as_empty(tmp_path) -> None:
    path = tmp_path / "holders.txt"
    path.write_bytes(b"\xff\xfe\x00bad\n")
    # Used to be `== ()`: now it returns names and numbers apart, both empty.
    assert transfers.load_holders(path) == transfers.Holders((), ())


class TestHolderNumbers:
    """Own account numbers written in holders.txt."""

    HOLDERS = transfers.Holders(("MARIA PEREZ INVENTADA",), (88001234567,))

    def test_number_in_a_description_is_an_own_transfer(self) -> None:
        sent = mv("2026-01-10", "MB a 0088001234567 OTRA PERSONA", "900")
        received = mv("2026-01-11", "LBTR/IB/ 88001234567 BANCO BHD", "-900")
        found = transfers.detect_transfers([sent, received], ACCOUNTS, self.HOLDERS)
        assert found == {sent.fingerprint: cat.OWN_TRANSFER, received.fingerprint: cat.OWN_TRANSFER}

    def test_other_numbers_and_fragments_do_not_count(self) -> None:
        other = mv("2026-01-10", "MB a 0088001234568 OTRA PERSONA", "900")
        fragment = mv("2026-01-10", "MB a 880012345670 OTRA PERSONA", "900")
        found = transfers.detect_transfers([other, fragment], ACCOUNTS, self.HOLDERS)
        assert found == {}

    def test_not_on_card_rows(self) -> None:
        store = mv("2026-01-10", "TIENDA 88001234567", "900", account=CARD.key)
        assert transfers.detect_transfers([store], ACCOUNTS, self.HOLDERS) == {}

    def test_number_of_the_row_account_itself_does_not_count(self) -> None:
        # OTHER is 700-1234567: listed in holders.txt, it does not make its own rows own transfers.
        holders = transfers.Holders((), (7001234567,))
        own = mv("2026-01-10", "REF 7001234567 PAGO", "900", account=OTHER.key)
        elsewhere = mv("2026-01-10", "REF 7001234567 PAGO", "900", account=OWN.key)
        found = transfers.detect_transfers([own, elsewhere], ACCOUNTS, holders)
        assert found == {elsewhere.fingerprint: cat.OWN_TRANSFER}

    def test_load_all_reads_numbers_too(self, conn) -> None:
        _add_bank_rows(conn, [("2026-01-12", "MB a 0088001234567 OTRA PERSONA", "debit", "70000")])
        found = {m.description: m for m in spending.load_all(conn, self.HOLDERS)}
        assert found["MB a 0088001234567 OTRA PERSONA"].category == cat.OWN_TRANSFER
        plain = {m.description: m for m in spending.load_all(conn)}
        assert plain["MB a 0088001234567 OTRA PERSONA"].category == cat.THIRD_PARTY


class TestHolderCutAnywhere:
    """The bank cuts the name mid-text: "… FULANO DE TA BANCO BHD …"."""

    HOLDER = ("MARIA PEREZ LOPEZ",)

    def _own(self, text: str, holders=HOLDER) -> bool:
        item = mv("2026-01-12", text, "900")
        return transfers.detect_transfers([item], ACCOUNTS, holders) == {
            item.fingerprint: cat.OWN_TRANSFER
        }

    def test_lbtr_with_the_name_cut_mid_word_and_more_text(self) -> None:
        text = "LBTR/IB/ VIA LBTR 0000000002 FULANO DE TA BANCO BHD INVENTADO"
        assert self._own(text, ("FULANO DE TAL",))

    @pytest.mark.parametrize(
        "text",
        [
            "MB a 001 MARIA PEREZ LO BANCO",  # 2 words and the cut third one
            "MB a 001 MARIA PEREZ L",  # at the end of the text, even a single letter
            "MB a 001 MARIA PEREZ",  # cut right after the second word, at the end
            "MB a 001 MARIA PER BANCO BHD",  # the second word cut (3+ letters)
            "MB a 001 MARIA PEREZ LOPEZ BANCO",  # whole
        ],
    )
    def test_cut_names_match(self, text: str) -> None:
        assert self._own(text)

    @pytest.mark.parametrize(
        "text",
        [
            "MB a 001 MARIA PEREZ INVENTADAS",  # a whole word that is not LOPEZ
            "MB a 001 MARIA PEREZ GOMEZ BANCO",  # another person with the same first and last name
            "MB a 001 MARIA PEREZ BANCO BHD",  # cut at a whole word and another field follows
            "MB a 001 MARIA PE BANCO",  # a cut under 3 letters after a single word
            "MB a 001 MARIA PERALTA",  # not a prefix of PEREZ
            "MB a 001 MARIA",  # one word is not enough
            "MB a 001 MARIAN PEREZ LOPEZ",  # the first word must be whole
        ],
    )
    def test_other_texts_do_not_match(self, text: str) -> None:
        assert not self._own(text)

    @pytest.mark.parametrize(
        "text",
        [
            "TOKE A JUAN PEREZ DE LA CRUZ",  # "DE" is a particle, not a cut DELGADO
            "MB A JUAN PEREZ D BANCO",  # a single letter mid-text is not a cut
        ],
    )
    def test_particles_and_single_letters_mid_text_are_not_cuts(self, text: str) -> None:
        assert not self._own(text, ("JUAN PEREZ DELGADO",))

    def test_particle_or_letter_at_the_end_is_still_a_cut(self) -> None:
        assert self._own("MB A JUAN PEREZ DE", ("JUAN PEREZ DELGADO",))
        assert self._own("MB A JUAN PEREZ D", ("JUAN PEREZ DELGADO",))

    def test_holder_word_that_is_a_particle_still_counts_whole(self) -> None:
        assert self._own("FULANO DE TA BANCO", ("FULANO DE TAL",))

    def test_two_word_holder_cut_in_its_second_word(self) -> None:
        assert self._own("MB a 001 JUAN PER BANCO", ("JUAN PEREZ",))
        assert not self._own("MB a 001 JUAN PERALTA", ("JUAN PEREZ",))


class TestHolderPrefix:
    def test_first_two_words_of_the_holder_match(self) -> None:
        # The bank cuts the name: "FULANO DE" for "FULANO DE TAL".
        cut = mv("2026-01-12", "MB DESDE 000000003 FULANO DE", "-900")
        found = transfers.detect_transfers([cut], ACCOUNTS, ("FULANO DE TAL",))
        assert found == {cut.fingerprint: cat.OWN_TRANSFER}

    def test_word_cut_in_the_middle_still_matches(self) -> None:
        cut = mv("2026-01-12", "MB DESDE 000000003 FULANO DE TA", "-900")
        found = transfers.detect_transfers([cut], ACCOUNTS, ("FULANO DE TAL",))
        assert found == {cut.fingerprint: cat.OWN_TRANSFER}

    def test_one_word_is_not_enough(self) -> None:
        first = mv("2026-01-12", "MB DESDE 000000003 FULANO", "-900")
        assert transfers.detect_transfers([first], ACCOUNTS, ("FULANO DE TAL",)) == {}

    def test_single_word_holder_needs_the_whole_word(self) -> None:
        exact = mv("2026-01-12", "ENVIO A INVENTADO", "900")
        longer = mv("2026-01-12", "ENVIO A INVENTADOS", "900")
        found = transfers.detect_transfers([exact, longer], ACCOUNTS, ("INVENTADO",))
        assert found == {exact.fingerprint: cat.OWN_TRANSFER}


class TestFullAccountNumber:
    def test_full_number_with_leading_zeros(self) -> None:
        # OTHER is 700-1234567: the full number without dashes, with or without leading zeros.
        sent = mv("2026-01-10", "MB A 0007001234567 INVENTADO", "900", account=OWN.key)
        found = transfers.detect_transfers([sent], ACCOUNTS, ())
        assert found == {sent.fingerprint: cat.OWN_TRANSFER}

    def test_full_number_of_the_row_account_does_not_count(self) -> None:
        own = mv("2026-01-10", "MB A 7001234567 INVENTADO", "900", account=OTHER.key)
        assert transfers.detect_transfers([own], ACCOUNTS, ()) == {}

    def test_short_tokens_are_not_full_numbers(self) -> None:
        tiny = AccountInfo(key="bco:savings:000000003", kind="savings", label="T", through=None)
        short = mv("2026-01-10", "REF 03 INVENTADA", "900", account=OWN.key)
        assert transfers.detect_transfers([short], (OWN, tiny), ()) == {}

    def test_never_on_card_rows(self) -> None:
        store = mv("2026-01-10", "TIENDA 7001234567", "900", account=CARD.key)
        assert transfers.detect_transfers([store], ACCOUNTS, ()) == {}


class TestOwnAccountWording:
    @pytest.mark.parametrize(
        "text",
        [
            "TRANSFERENCIA A CUENTA PROPIA",
            "Transf. a cta. propia",  # spanish-data
            "DE CUENTA PROPIA",
        ],
    )
    def test_own_account_wording_is_an_own_transfer(self, text) -> None:
        moved = mv("2026-01-10", text, "200")
        assert transfers.detect_transfers([moved], ACCOUNTS, ()) == {
            moved.fingerprint: cat.OWN_TRANSFER
        }

    def test_not_on_cards_or_inside_other_words(self) -> None:
        card = mv("2026-01-10", "PAGO CUENTA PROPIA", "200", account=CARD.key)
        other = mv("2026-01-10", "CUENTA PROPIAS INVENTADA", "200")
        assert transfers.detect_transfers([card, other], ACCOUNTS, ()) == {}


@pytest.fixture
def popular(conn):
    """The usual synthetic accounts plus the Popular ones (DOP checking and USD savings)."""
    for index, pages in enumerate((samples.POPULAR_CUENTA_DOP, samples.POPULAR_CUENTA_USD)):
        with conn:
            conn.execute(
                "INSERT INTO gmail_messages VALUES (?, 'bank', 'x', 'y', 'z', 1, 'z')",
                (f"p{index}",),
            )
            document_id = conn.execute(
                "INSERT INTO documents (message_id, source, filename, path, sha256, size, "
                "received_at, status) VALUES (?, 'bank', 'f.pdf', 'p', ?, 1, 'z', 'parsed')",
                (f"p{index}", f"sp{index}"),
            ).lastrowid
            db.store_statement(conn, document_id, popular_account.parse(pages))
    return conn


# The Popular sample's incoming transfer from the (cut) holder name.
POPULAR_INCOMING = "MB desde 000000003 FULANO DE"  # spanish-data


class TestPopularShapes:
    def _by_text(self, conn, holders=()) -> dict[str, Movement]:
        return {m.description: m for m in spending.load_all(conn, holders)}

    def test_cut_holder_name_on_an_incoming_transfer(self, popular) -> None:
        found = self._by_text(popular, ("Fulano de Tal",))  # spanish-data
        assert found[POPULAR_INCOMING].category == cat.OWN_TRANSFER
        # Used to be "expense": a transfer to someone else is a third-party transfer.
        assert found["MB a 0000000001 PERSONA INVENTADA"].category == cat.THIRD_PARTY
        assert self._by_text(popular)[POPULAR_INCOMING].kind == "income"

    def test_registered_full_number_without_holders(self, popular) -> None:
        with popular:
            popular.execute(
                "INSERT INTO accounts (institution, kind, key, name) "
                "VALUES ('bco', 'savings', 'bco:savings:000000003', 'BCO Ahorro')"  # spanish-data
            )
        found = self._by_text(popular)
        assert found[POPULAR_INCOMING].category == cat.OWN_TRANSFER
        # Used to be "expense": a transfer to someone else is a third-party transfer.
        assert found["MB a 0000000001 PERSONA INVENTADA"].category == cat.THIRD_PARTY

    def test_own_account_wording_in_usd_savings(self, popular) -> None:
        moved = self._by_text(popular)["TRANSFERENCIA A CUENTA PROPIA"]
        assert (moved.category, moved.kind) == (cat.OWN_TRANSFER, "transfer")
        assert moved.fingerprint not in {m.fingerprint for m in spending.load_movements(popular)}


class TestReversalReferences:
    """A reversal's reference (DEV …) carries random digits: they are not an own account."""

    def test_reference_digits_are_not_an_own_account(self) -> None:
        back = mv("2026-01-12", "DEV LBTR E765432.ADEV0042CAS", "-900")
        found = transfers.detect_transfers([back], ACCOUNTS, (), card_last4={CARD.key: ("0042",)})
        assert found == {}
        listed = transfers.Holders(numbers=(7001234567,))
        long_ref = mv("2026-01-12", "DEV LBTR 7001234567 ADEV", "-900")
        assert transfers.detect_transfers([long_ref], ACCOUNTS, listed) == {}

    def test_the_same_digits_still_count_outside_a_reversal(self) -> None:
        sent = mv("2026-01-12", "MB A 0042 INVENTADO", "-900")
        found = transfers.detect_transfers([sent], ACCOUNTS, (), card_last4={CARD.key: ("0042",)})
        assert found == {sent.fingerprint: cat.OWN_TRANSFER}

    def test_holder_name_or_wording_still_counts_in_a_reversal(self) -> None:
        back = mv("2026-01-12", "DEV LBTR MARIA PEREZ INVENTADA", "-900")
        found = transfers.detect_transfers([back], ACCOUNTS, ("MARIA PEREZ INVENTADA",))
        assert found == {back.fingerprint: cat.OWN_TRANSFER}


class TestBanreservasShapes:
    def test_transfer_naming_the_holder_is_own(self) -> None:
        received = mv("2026-01-03", "TRANSFERENCIA DE FULANO DE TAL", "-25000")
        sent = mv("2026-01-10", "TRANSFERENCIA A FULANO DE TAL", "5000")
        instant = mv("2026-01-15", "PAGOS AL INSTANTE BCRD A FULANO DE TAL", "2500")
        found = transfers.detect_transfers([received, sent, instant], ACCOUNTS, ("FULANO DE TAL",))
        assert found == {
            received.fingerprint: cat.OWN_TRANSFER,
            sent.fingerprint: cat.OWN_TRANSFER,
            instant.fingerprint: cat.OWN_TRANSFER,
        }

    def test_bare_transfer_paying_a_card_is_a_card_payment(self) -> None:
        # No counterpart in the text: only the amount matching the card payment tells.
        bare = mv("2026-01-28", "TRANSFERENCIA", "26000")
        found = transfers.detect_transfers(
            [bare, card_payment("2026-01-29", "26000")], ACCOUNTS, ("FULANO DE TAL",)
        )
        assert found[bare.fingerprint] == cat.CARD_PAYMENT

    def test_bare_transfer_alone_is_not_detected(self) -> None:
        bare = mv("2026-01-28", "TRANSFERENCIA", "26000")
        assert transfers.detect_transfers([bare], ACCOUNTS, ("FULANO DE TAL",)) == {}
