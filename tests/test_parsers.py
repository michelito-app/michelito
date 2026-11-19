from datetime import date
from decimal import Decimal

import pytest

from michelito.parsers import (
    banreservas_account,
    bhd_card,
    bhd_savings,
    detect,
    popular_account,
    popular_card,
    popular_web,
)
from michelito.parsers.common import CREDIT, DEBIT, ParseError, validate_statement
from tests import samples
from tests.layout import block, page

# Validation problem when the interest row is lost (the text the app shows).
CREDITS_SHORT = "créditos leídos 5000.00 ≠ impresos 5000.50"  # spanish-ui
# Product names the parsers take from the bank's own labels.
# spanish-data: begin
CHECKING_PRODUCT = "Cuenta corriente"
SAVINGS_PRODUCT = "Cuenta de ahorro"
# spanish-data: end


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        (samples.POPULAR_PAGES, popular_card),
        (samples.BHD_TC_PAGES, bhd_card),
        (samples.BHD_AHORRO_PAGES, bhd_savings),
        (samples.BHD_AHORRO_PORTAL_PAGES, bhd_savings),
        (samples.POPULAR_CUENTA_DOP, popular_account),
        (samples.POPULAR_CUENTA_USD, popular_account),
        (samples.POPULAR_WEB, popular_web),
        (samples.BANRESERVAS, banreservas_account),
        ((samples.UNKNOWN,), None),
        ((), None),
    ],
)
def test_detect_picks_the_right_parser(pages, expected) -> None:
    assert detect(pages) is expected


class TestPopular:
    def test_header_and_sections(self) -> None:
        statement = popular_card.parse(samples.POPULAR_PAGES)
        assert (statement.institution, statement.kind) == ("popular", "credit_card")
        assert statement.product == "VISA PRESTIGE"
        assert statement.identifier == "1234"
        assert statement.period_end == date(2026, 1, 13)
        assert statement.due_date == date(2026, 2, 7)
        assert [s.currency for s in statement.sections] == ["DOP", "USD"]
        dop = statement.sections[0]
        assert dop.previous_balance == Decimal("5000.00")
        assert dop.closing_balance == Decimal("1500.50")
        assert dop.minimum_payment == Decimal("150.00")
        assert dop.credit_limit == Decimal("100000.00")

    def test_transactions(self) -> None:
        dop, usd = popular_card.parse(samples.POPULAR_PAGES).sections
        first, _, payment = dop.transactions
        assert first.transacted_on == date(2025, 12, 14)
        assert first.posted_on == date(2025, 12, 15)
        assert first.description == "COLMADO INVENTADO SANTO DOMINGO"
        assert (first.amount, first.direction, first.mcc) == (Decimal("1200.50"), DEBIT, "5411")
        assert first.reference == "11111111111111111111111"
        assert (payment.amount, payment.direction, payment.mcc) == (
            Decimal("5000.00"),
            CREDIT,
            None,
        )
        assert usd.transactions[0].currency == "USD"
        assert usd.transactions[0].mcc == "5942"

    def test_validates(self) -> None:
        assert validate_statement(popular_card.parse(samples.POPULAR_PAGES)) == ()

    def test_split_unlabeled_footer_of_2020_2025(self) -> None:
        statement = popular_card.parse((samples.POPULAR_DOP_SPLIT_FOOTER,))
        (dop,) = statement.sections
        assert dop.closing_balance == Decimal("1200.50")
        assert dop.minimum_payment == Decimal("150.00")
        assert validate_statement(statement) == ()

    def test_four_value_footer_of_early_2024(self) -> None:
        statement = popular_card.parse((samples.POPULAR_DOP_FOUR_VALUE_FOOTER,))
        (dop,) = statement.sections
        assert (dop.minimum_payment, dop.closing_balance) == (Decimal("150.00"), Decimal("1200.50"))
        assert validate_statement(statement) == ()

    def test_wrong_total_is_reported(self) -> None:
        statement = popular_card.parse((samples.POPULAR_DOP_WRONG_TOTAL,))
        problems = validate_statement(statement)
        assert len(problems) == 1
        assert "1600.50" in problems[0]

    def test_without_header_fails(self) -> None:
        with pytest.raises(ParseError):
            popular_card.parse((samples.POPULAR_TERMS,))


class TestBhdCreditCard:
    def test_header_and_summary(self) -> None:
        statement = bhd_card.parse(samples.BHD_TC_PAGES)
        assert (statement.institution, statement.kind) == ("bhd", "credit_card")
        assert (statement.product, statement.identifier) == ("MC BLACK", "9999")
        assert statement.period_end == date(2026, 1, 26)
        assert statement.due_date == date(2026, 2, 20)
        dop, usd = statement.sections
        assert (dop.previous_balance, dop.closing_balance) == (
            Decimal("1000.00"),
            Decimal("2500.00"),
        )
        assert (dop.credit_limit, usd.credit_limit) == (Decimal("100000.00"), Decimal("2000.00"))
        assert (dop.minimum_payment, usd.minimum_payment) == (Decimal("125.00"), Decimal("5.00"))
        assert (usd.printed_debits, usd.printed_credits) == (Decimal("30.00"), Decimal("10.00"))

    def test_debits_and_credits_by_column(self) -> None:
        dop, usd = bhd_card.parse(samples.BHD_TC_PAGES).sections
        assert [t.direction for t in dop.transactions] == [DEBIT, DEBIT, CREDIT]
        assert dop.transactions[0].description == "SUPERMERCADO FICTICIO SANTO DOMINGO-DO"
        assert dop.transactions[0].transacted_on == date(2025, 12, 28)
        assert dop.transactions[2].description == "PAGO DEBITO A CUENTA MBP"
        assert [t.direction for t in usd.transactions] == [DEBIT, CREDIT]

    def test_validates(self) -> None:
        assert validate_statement(bhd_card.parse(samples.BHD_TC_PAGES)) == ()

    def test_garbled_dollar_title_still_splits_currencies(self) -> None:
        pages = (
            samples.BHD_TC_SUMMARY,
            samples.BHD_TC_MOVEMENTS_GARBLED,
            samples.BHD_TC_CONTINUED_USD_ONLY,
        )
        statement = bhd_card.parse(pages)
        dop, usd = statement.sections
        assert [t.currency for t in usd.transactions] == ["USD", "USD"]
        assert len(dop.transactions) == 3
        refund = dop.transactions[2]
        assert (refund.reference, refund.description) == ("66666666666666666666666", "DEVOLUCION")
        assert validate_statement(statement) == ()

    def test_missing_dates_fail(self) -> None:
        with pytest.raises(ParseError):
            bhd_card.parse((samples.BHD_TC_MOVEMENTS,))


class TestBhdSavings:
    def test_header(self) -> None:
        statement = bhd_savings.parse(samples.BHD_AHORRO_PAGES)
        assert (statement.institution, statement.kind) == ("bhd", "savings")
        assert statement.identifier == "999-1"
        assert statement.period_end == date(2026, 1, 31)
        (section,) = statement.sections
        assert section.currency == "DOP"
        assert section.previous_balance == Decimal("10000.00")
        assert section.closing_balance == Decimal("12000.50")
        assert (section.printed_debits, section.printed_credits) == (
            Decimal("3000.00"),
            Decimal("5000.50"),
        )

    def test_transactions(self) -> None:
        (section,) = bhd_savings.parse(samples.BHD_AHORRO_PAGES).sections
        received, payment, interest = section.transactions
        assert (received.direction, received.reference) == (CREDIT, "1234567890")
        assert received.description == "TRANSFERENCIA RECIBIDA"
        assert (payment.direction, payment.reference) == (DEBIT, None)
        assert payment.description == "PAGO DE TC 5100 XXXX XXXX 9999"
        assert (interest.amount, interest.transacted_on) == (Decimal("0.50"), date(2026, 1, 31))

    def test_validates(self) -> None:
        assert validate_statement(bhd_savings.parse(samples.BHD_AHORRO_PAGES)) == ()

    def test_missing_label_fails(self) -> None:
        with pytest.raises(ParseError):
            bhd_savings.parse((samples.UNKNOWN,))

    def test_2025_layout(self) -> None:
        pages = (samples.BHD_AHORRO_2025,)
        assert detect(pages) is bhd_savings
        statement = bhd_savings.parse(pages)
        assert (statement.identifier, statement.period_end) == ("999-1", date(2025, 5, 31))
        (section,) = statement.sections
        assert (section.currency, section.previous_balance) == ("DOP", Decimal("10000.00"))
        assert section.closing_balance == Decimal("12000.50")
        assert validate_statement(statement) == ()

    def test_printed_final_balance_catches_a_wrong_last_row(self) -> None:
        rows = tuple(
            "                                                12,999.99"
            if row.strip() == "12,000.50"
            else row
            for row in samples.BHD_AHORRO_2025_ROWS
        )
        problems = validate_statement(bhd_savings.parse((page(*rows),)))
        assert any("12999.99" in problem for problem in problems)

    def test_missing_printed_totals_fail(self) -> None:
        truncated = samples.BHD_AHORRO[:-2]
        with pytest.raises(ParseError, match="printed debit and credit totals"):
            bhd_savings.parse((truncated,))

    def test_dropped_row_is_caught_by_printed_sums(self) -> None:
        without_interest = tuple(
            line for line in samples.BHD_AHORRO if "INTERESES" not in line.text
        )
        problems = validate_statement(bhd_savings.parse((without_interest,)))
        assert any(CREDITS_SHORT in p for p in problems)

    def test_printed_counts_are_not_trusted(self) -> None:
        # The bank sometimes prints a count that does not match the rows (e.g.
        # "3CREDITOS" with two credits) even though the sums balance to the cent.
        rows = tuple(row.replace("2CREDITOS", "3CREDITOS") for row in samples.BHD_AHORRO_2025_ROWS)
        assert validate_statement(bhd_savings.parse((page(*rows),))) == ()


def _portal_with(old: str, new: str) -> tuple:
    rows = tuple(row.replace(old, new) for row in samples.BHD_AHORRO_PORTAL_ROWS)
    assert rows != samples.BHD_AHORRO_PORTAL_ROWS
    return (page(*rows),)


class TestBhdSavingsPortal:
    """The savings statement downloaded from the BHD portal (not by email)."""

    def test_header_matches_the_email_statement(self) -> None:
        portal = bhd_savings.parse(samples.BHD_AHORRO_PORTAL_PAGES)
        email = bhd_savings.parse(samples.BHD_AHORRO_PAGES)
        assert (portal.parser, portal.institution, portal.kind) == (
            email.parser,
            email.institution,
            email.kind,
        )
        assert (portal.identifier, portal.period_end) == (email.identifier, email.period_end)
        (section,) = portal.sections
        (email_section,) = email.sections
        assert section.currency == "DOP"
        assert (section.previous_balance, section.closing_balance) == (
            email_section.previous_balance,
            email_section.closing_balance,
        )
        assert (section.printed_debits, section.printed_credits) == (
            Decimal("3000.00"),
            Decimal("5000.50"),
        )

    def test_transactions(self) -> None:
        (section,) = bhd_savings.parse(samples.BHD_AHORRO_PORTAL_PAGES).sections
        received, payment, interest = section.transactions
        assert (received.direction, received.amount) == (CREDIT, Decimal("5000.00"))
        assert (received.reference, received.description) == ("1234567", "TRANSFERENCIA RECIBIDA")
        assert received.transacted_on == date(2026, 1, 5)
        assert (payment.direction, payment.amount) == (DEBIT, Decimal("3000.00"))
        assert (payment.reference, payment.description) == (
            "7654321",
            "PAGO DE TC 5100 XXXX XXXX 9999",
        )
        assert (interest.direction, interest.amount) == (CREDIT, Decimal("0.50"))
        assert (interest.reference, interest.description) == (None, "PAGO INTERESES CA")
        assert interest.transacted_on == date(2026, 1, 31)

    def test_same_movements_as_the_email_statement(self) -> None:
        def movements(pages):
            (section,) = bhd_savings.parse(pages).sections
            return [
                (t.transacted_on, t.amount, t.direction, t.description)
                for t in section.transactions
            ]

        assert movements(samples.BHD_AHORRO_PORTAL_PAGES) == movements(samples.BHD_AHORRO_PAGES)

    def test_validates(self) -> None:
        assert validate_statement(bhd_savings.parse(samples.BHD_AHORRO_PORTAL_PAGES)) == ()

    def test_column_decides_the_direction(self) -> None:
        # Interest printed in the debit column is read as a debit and no longer balances.
        pages = _portal_with("0.00        0.50", "0.50        0.00")
        (section,) = bhd_savings.parse(pages).sections
        assert section.transactions[-1].direction == DEBIT
        problems = validate_statement(bhd_savings.parse(pages))
        assert any(CREDITS_SHORT in p for p in problems)

    def test_dropped_row_is_invalid(self) -> None:
        rows = tuple(r for r in samples.BHD_AHORRO_PORTAL_ROWS if "INTERESES" not in r)
        problems = validate_statement(bhd_savings.parse((page(*rows),)))
        assert any(CREDITS_SHORT in p for p in problems)

    def test_month_not_yet_closed_is_invalid(self) -> None:
        # "Balance final" at 0.00 with a row on the cut day: not the month in progress
        # (see test_bhd_partial), so it does not balance and is not stored; storing it would
        # block storing the full month's statement (it would be a duplicate).
        rows = tuple(
            "                                                   0.00"
            if row.strip() == "12,000.50"
            else row
            for row in samples.BHD_AHORRO_PORTAL_ROWS
        )
        problems = validate_statement(bhd_savings.parse((page(*rows),)))
        assert any("≠ balance al corte 0.00" in problem for problem in problems)  # spanish-ui

    def test_amounts_in_both_columns_fail(self) -> None:
        with pytest.raises(ParseError, match="exactly one column"):
            bhd_savings.parse(_portal_with("0.00        0.50", "0.10        0.50"))

    def test_no_amount_in_either_column_fails(self) -> None:
        with pytest.raises(ParseError, match="exactly one column"):
            bhd_savings.parse(_portal_with("0.00        0.50", "0.00        0.00"))


def test_popular_page_with_movements_but_no_header_fails() -> None:
    orphan = page(
        *block("""
        15/12  14/12 11111111111111111111111 COLMADO INVENTADO SANTO DOMINGO   1,200.50
    """)
    )
    with pytest.raises(ParseError, match="without a card header"):
        popular_card.parse((samples.POPULAR_DOP, orphan))


def test_bhd_dates_must_follow_their_label() -> None:
    label = "Fecha de corte"  # spanish-data
    unlabeled = tuple(line for line in samples.BHD_TC_SUMMARY if label not in line.text)
    with pytest.raises(ParseError, match="closing date and the due date"):
        bhd_card.parse((unlabeled, samples.BHD_TC_MOVEMENTS))


class TestPopularAccount:
    def test_checking_header(self) -> None:
        statement = popular_account.parse(samples.POPULAR_CUENTA_DOP)
        assert (statement.parser, statement.institution) == ("popular_account", "popular")
        assert (statement.kind, statement.product) == ("checking", CHECKING_PRODUCT)
        assert statement.identifier == "123456789"
        assert statement.period_end == date(2026, 1, 15)
        assert statement.due_date is None
        (section,) = statement.sections
        assert section.currency == "DOP"
        assert section.previous_balance == Decimal("10000.00")
        assert section.closing_balance == Decimal("64998.50")
        assert section.printed_credits == Decimal("60000.00")
        assert section.printed_debits == Decimal("5001.50")

    def test_checking_movements_across_pages(self) -> None:
        (section,) = popular_account.parse(samples.POPULAR_CUENTA_DOP).sections
        assert len(section.transactions) == 5
        salary, transfer, tax, wire, deposit = section.transactions
        assert salary.transacted_on == date(2025, 12, 20)
        assert salary.description == "PAGO DE NOMINA EMPRESA FICTICIA"
        assert (salary.amount, salary.direction, salary.currency) == (
            Decimal("50000.00"),
            CREDIT,
            "DOP",
        )
        assert (transfer.transacted_on, transfer.posted_on) == (
            date(2025, 12, 21),
            date(2025, 12, 22),
        )
        assert (transfer.amount, transfer.direction) == (Decimal("1000.00"), DEBIT)
        assert tax.amount == Decimal("1.50")
        assert tax.description.endswith("Del 26/12/2025 Al 01/01/2026")  # spanish-data
        assert wire.description == (
            "LBTR/IB/ VIA LBTR 0000000002, FULANO DE TAL BANCO INVENTADO S.A. CAS0000000001"
        )
        assert (deposit.amount, deposit.direction) == (Decimal("10000.00"), CREDIT)
        assert deposit.transacted_on == date(2026, 1, 11)

    def test_checking_validates(self) -> None:
        assert validate_statement(popular_account.parse(samples.POPULAR_CUENTA_DOP)) == ()

    def test_footer_text_is_not_part_of_the_last_movement(self) -> None:
        (section,) = popular_account.parse(samples.POPULAR_CUENTA_DOP).sections
        assert all("LINEA DE AYUDA" not in t.description for t in section.transactions)
        footer = "Pie de página"  # spanish-data
        assert all(footer not in t.description for t in section.transactions)
        assert all("promocional" not in t.description for t in section.transactions)

    def test_savings_in_dollars_with_interest(self) -> None:
        statement = popular_account.parse(samples.POPULAR_CUENTA_USD)
        assert (statement.kind, statement.product) == ("savings", SAVINGS_PRODUCT)
        assert statement.identifier == "987654321"
        assert statement.period_end == date(2026, 10, 31)
        (section,) = statement.sections
        assert section.currency == "USD"
        assert {t.currency for t in section.transactions} == {"USD"}
        assert section.printed_credits == Decimal("500.25")  # deposits + interest paid
        assert section.printed_debits == Decimal("200.00")
        assert validate_statement(statement) == ()

    def test_wrong_closing_balance_is_reported(self) -> None:
        statement = popular_account.parse(samples.POPULAR_CUENTA_WRONG_CLOSING)
        (problem,) = validate_statement(statement)
        assert "balance al corte 65998.50" in problem  # spanish-ui

    def test_dropped_movement_is_caught(self) -> None:
        statement = popular_account.parse(samples.POPULAR_CUENTA_DOP[:1])
        problems = validate_statement(statement)
        assert any("débitos leídos" in p for p in problems)  # spanish-ui
        assert any("créditos leídos" in p for p in problems)  # spanish-ui

    def test_missing_summary_fails(self) -> None:
        date_line = "15 de enero de 2026"  # spanish-data
        pages = (page("CTA CTE PERSONAL INVENTADA 123456789", date_line),)
        with pytest.raises(ParseError):
            popular_account.parse(pages)

    def test_does_not_claim_card_or_bhd_statements(self) -> None:
        assert not popular_account.matches(samples.POPULAR_PAGES)
        assert not popular_account.matches(samples.BHD_AHORRO_PAGES)
        assert not popular_account.matches((samples.UNKNOWN,))

    def test_checking_period_starts_after_the_opening_balance_date(self) -> None:
        statement = popular_account.parse(samples.POPULAR_CUENTA_DOP)
        assert statement.period_start == date(2025, 12, 16)


class TestPopularWeb:
    def test_account_identity_matches_the_official_statement(self) -> None:
        web = popular_web.parse(samples.POPULAR_WEB)
        official = popular_account.parse(samples.POPULAR_CUENTA_DOP)
        assert (web.parser, web.institution, web.kind, web.identifier) == (
            "popular_web",
            official.institution,
            official.kind,
            official.identifier,
        )
        assert web.product == official.product
        assert (web.period_start, web.period_end) == (date(2026, 1, 12), date(2026, 1, 20))
        assert web.due_date is None

    def test_rows_amounts_signs_and_references(self) -> None:
        (section,) = popular_web.parse(samples.POPULAR_WEB).sections
        assert section.currency == "DOP"
        rows = section.transactions
        assert [(t.transacted_on, t.amount, t.direction) for t in rows] == [
            (date(2026, 1, 12), Decimal("10000.00"), CREDIT),
            (date(2026, 1, 16), Decimal("1500.00"), DEBIT),
            (date(2026, 1, 17), Decimal("2000.00"), CREDIT),
            (date(2026, 1, 19), Decimal("2.25"), DEBIT),
            (date(2026, 1, 20), Decimal("500.00"), CREDIT),
        ]
        assert [t.balance for t in rows] == [
            Decimal(v) for v in ("64998.50", "63498.50", "65498.50", "65496.25", "65996.25")
        ]
        assert all(t.posted_on == t.transacted_on for t in rows)  # the posting date
        assert [t.reference for t in rows] == [
            "0000000000001",
            "0000000000002",
            None,
            "0000000000003",
            "0000000000004 0001",
        ]

    def test_wrapped_descriptions_join_the_right_row(self) -> None:
        (section,) = popular_web.parse(samples.POPULAR_WEB).sections
        assert [t.description for t in section.transactions] == [
            "MB DESDE 000000003 FULANO DE",
            "PAGO TARJETA TIENDA FICTICIA S.R.L. SANTO DOMINGO",
            "DEPOSITO CHEQUE Y EFECTIVO",
            "IMPUESTO 0.15% DGII 1 TRANS POR $ 1,500.00 DEL 16/01/2026 AL 16/01/2026",
            "TRANSFERENCIA RECIBIDA DE PERSONA INVENTADA",
        ]

    def test_opening_and_closing_come_from_the_chain(self) -> None:
        statement = popular_web.parse(samples.POPULAR_WEB)
        (section,) = statement.sections
        assert section.previous_balance == Decimal("54998.50")
        assert section.closing_balance == Decimal("65996.25")
        assert (section.printed_debits, section.printed_credits) == (
            Decimal("1502.25"),
            Decimal("12500.00"),
        )
        assert validate_statement(statement) == ()

    def test_broken_chain_is_reported(self) -> None:
        statement = popular_web.parse(samples.POPULAR_WEB_BROKEN_CHAIN)
        problems = validate_statement(statement)
        assert problems
        assert any("2026-01-17" in problem for problem in problems)

    def test_savings_header(self) -> None:
        account = "Cuenta de Ahorro / 987654321"  # spanish-data
        pages = samples.popular_web(samples.WEB_ROWS, account=account)
        statement = popular_web.parse(pages)
        assert (statement.kind, statement.identifier) == ("savings", "987654321")
        assert statement.product == SAVINGS_PRODUCT

    def test_dollar_amounts(self) -> None:
        rows = tuple(
            (*r[:5], r[5].replace("$", "US$"), r[6].replace("$", "US$")) for r in samples.WEB_ROWS
        )
        (section,) = popular_web.parse(samples.popular_web(rows)).sections
        assert section.currency == "USD"
        assert {t.currency for t in section.transactions} == {"USD"}

    def test_negative_balance_has_the_sign_in_front(self) -> None:
        statement = popular_web.parse(samples.POPULAR_WEB_OVERDRAFT)
        (section,) = statement.sections
        assert section.currency == "DOP"
        assert [t.balance for t in section.transactions] == [
            Decimal(v) for v in ("10.00", "-5.40", "-6.40", "13.60")
        ]
        assert [(t.amount, t.direction) for t in section.transactions] == [
            (Decimal("10.00"), CREDIT),
            (Decimal("15.40"), DEBIT),
            (Decimal("1.00"), DEBIT),
            (Decimal("20.00"), CREDIT),
        ]
        assert (section.previous_balance, section.closing_balance) == (
            Decimal("0.00"),
            Decimal("13.60"),
        )
        assert validate_statement(statement) == ()

    def test_overdraft_chain_that_breaks_below_zero_is_reported(self) -> None:
        rows = list(samples.WEB_ROWS_OVERDRAFT)
        rows[2] = (*rows[2][:6], "-$7.40")
        problems = validate_statement(popular_web.parse(samples.popular_web(tuple(rows))))
        assert any("2026-02-07" in problem for problem in problems)

    @pytest.mark.parametrize("symbol", ["$", "RD$", "US$"])
    def test_leading_minus_amount_is_a_debit(self, symbol: str) -> None:
        rows = (
            ("05/02/2026", "05/02/2026", None, None, ("UNO",), f"{symbol}10.00", f"{symbol}10.00"),
            ("06/02/2026", "06/02/2026", None, None, ("DOS",), f"-{symbol}4.00", f"{symbol}6.00"),
        )
        (section,) = popular_web.parse(samples.popular_web(rows)).sections
        assert section.transactions[1].direction == DEBIT
        assert section.transactions[1].amount == Decimal("4.00")

    def test_money_with_both_minus_signs_fails(self) -> None:
        last = (*samples.WEB_ROWS[-1][:5], "-$500.00-", "$65,996.25")
        with pytest.raises(ParseError):
            popular_web.parse(samples.popular_web((*samples.WEB_ROWS[:-1], last)))

    def test_bare_dollar_takes_the_given_currency(self) -> None:
        (section,) = popular_web.parse(samples.POPULAR_WEB, currency="USD").sections
        assert section.currency == "USD"
        assert {t.currency for t in section.transactions} == {"USD"}

    def test_explicit_symbol_that_contradicts_the_given_currency_fails(self) -> None:
        rows = tuple(
            (*r[:5], r[5].replace("$", "US$"), r[6].replace("$", "US$")) for r in samples.WEB_ROWS
        )
        assert popular_web.parse(samples.popular_web(rows), currency="USD").sections
        with pytest.raises(ParseError, match="USD"):
            popular_web.parse(samples.popular_web(rows), currency="DOP")

    def test_unknown_currency_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="EUR"):
            popular_web.parse(samples.POPULAR_WEB, currency="EUR")

    def test_row_that_does_not_parse_fails_instead_of_vanishing(self) -> None:
        last = (*samples.WEB_ROWS[-1][:5], "500.00", "$65,996.25")  # amount without a symbol
        with pytest.raises(ParseError):
            popular_web.parse(samples.popular_web((*samples.WEB_ROWS[:-1], last)))

    @pytest.mark.parametrize("index", [0, -1])
    def test_money_line_that_is_not_a_row_fails(self, index: int) -> None:
        rows = list(samples.WEB_ROWS)
        rows[index] = ("??/01/2026", "??/01/2026", *rows[index][2:])  # unreadable date
        with pytest.raises(ParseError, match="a line with an amount outside a row"):
            popular_web.parse(samples.popular_web(tuple(rows)))

    def test_row_with_too_few_words_fails(self) -> None:
        pages = samples.popular_web(((*samples.WEB_ROWS[0][:4], (), "", ""),))
        with pytest.raises(ParseError):
            popular_web.parse(pages)

    def test_without_rows_fails(self) -> None:
        with pytest.raises(ParseError):
            popular_web.parse(samples.popular_web(()))

    def test_matches_only_printouts(self) -> None:
        assert popular_web.matches(samples.POPULAR_WEB)
        assert popular_web.matches(samples.POPULAR_WEB_LATER)
        for other in (
            samples.POPULAR_PAGES,
            samples.BHD_TC_PAGES,
            samples.BHD_AHORRO_PAGES,
            samples.POPULAR_CUENTA_DOP,
            samples.POPULAR_CUENTA_USD,
            (samples.UNKNOWN,),
            (),
        ):
            assert not popular_web.matches(other)
        for parser in (popular_card, bhd_card, bhd_savings, popular_account):
            assert not parser.matches(samples.POPULAR_WEB)
