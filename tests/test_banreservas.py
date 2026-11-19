from datetime import date
from decimal import Decimal

import pytest

from finanzas.parsers import (
    banreservas_cuenta,
    bhd_ahorro,
    bhd_tc,
    detect,
    popular_cuenta,
    popular_tc,
    popular_web,
)
from finanzas.parsers.common import CREDIT, DEBIT, ParseError, validate_statement
from tests import samples
from tests.layout import placed

OTHER_SAMPLES = (
    samples.POPULAR_PAGES,
    samples.BHD_TC_PAGES,
    samples.BHD_AHORRO_PAGES,
    samples.POPULAR_CUENTA_DOP,
    samples.POPULAR_CUENTA_USD,
    samples.POPULAR_WEB,
    (samples.UNKNOWN,),
    (),
)
OTHER_PARSERS = (popular_tc, bhd_tc, bhd_ahorro, popular_cuenta, popular_web)


def _rows(*rows: samples.BanreservasRow, **options) -> tuple:
    return samples.banreservas(rows, **options)


class TestMatches:
    def test_detects_the_statement(self) -> None:
        assert detect(samples.BANRESERVAS) is banreservas_cuenta

    def test_does_not_match_other_samples(self) -> None:
        for other in OTHER_SAMPLES:
            assert not banreservas_cuenta.matches(other)

    def test_no_other_parser_matches_it(self) -> None:
        for parser in OTHER_PARSERS:
            assert not parser.matches(samples.BANRESERVAS)


class TestHeader:
    def test_account_and_period(self) -> None:
        statement = banreservas_cuenta.parse(samples.BANRESERVAS)
        assert (statement.parser, statement.institution) == ("banreservas_cuenta", "banreservas")
        assert (statement.kind, statement.product) == ("savings", "Cuenta de ahorro")
        assert statement.identifier == "0000000000"
        assert statement.period_start == date(2026, 1, 1)
        assert statement.period_end == date(2026, 1, 31)
        assert statement.due_date is None
        assert not statement.is_liability

    def test_currency_is_pesos_unless_it_says_dollars(self) -> None:
        (section,) = banreservas_cuenta.parse(samples.BANRESERVAS).sections
        assert section.currency == "DOP"
        pages = samples.banreservas(samples.BANRESERVAS_ROWS, period="01/01/2026 - 01/02/2026 US$")
        (section,) = banreservas_cuenta.parse(pages).sections
        assert section.currency == "USD"
        assert {t.currency for t in section.transactions} == {"USD"}


class TestRows:
    def test_rows_are_returned_oldest_first(self) -> None:
        (section,) = banreservas_cuenta.parse(samples.BANRESERVAS).sections
        days = [t.transacted_on for t in section.transactions]
        assert days == sorted(days)
        assert len(section.transactions) == len(samples.BANRESERVAS_ROWS)
        assert all(t.posted_on == t.transacted_on for t in section.transactions)

    def test_signs_and_columns_give_the_direction(self) -> None:
        (section,) = banreservas_cuenta.parse(samples.BANRESERVAS).sections
        first, tax, *_, interest, last = section.transactions
        assert (first.direction, first.amount) == (CREDIT, Decimal("25000.00"))
        assert (tax.direction, tax.amount) == (DEBIT, Decimal("3.75"))
        assert (interest.direction, interest.amount) == (CREDIT, Decimal("12.34"))
        assert (last.direction, last.amount) == (DEBIT, Decimal("26000.00"))
        assert last.balance == Decimal("1408.59")

    def test_continuation_lines_join_their_row(self) -> None:
        (section,) = banreservas_cuenta.parse(samples.BANRESERVAS).sections
        descriptions = [t.description for t in section.transactions]
        assert descriptions == [
            "TRANSFERENCIA DE PERSONA INVENTADA OTRO APELLIDO",
            "COBRO IMP DGII 0.15%_IMPUESTO INV",
            "TRANSFERENCIA A MENGANO INVENTADO PEREZ",
            "COMISION PAGO AL INSTANTE BCRD",
            "PAGOS AL INSTANTE BCRD A ZUTANO FICTICIO RODRIGUEZ",
            "PAGO INTERES INVENTADO",
            "TRANSFERENCIA",
        ]

    def test_rows_split_across_pages(self) -> None:
        rows = samples.BANRESERVAS_ROWS
        statement = banreservas_cuenta.parse(samples.banreservas(rows[:3], rows[3:]))
        (section,) = statement.sections
        assert len(section.transactions) == len(rows)
        assert validate_statement(statement) == ()

    @pytest.mark.parametrize("repeat_header", [True, False])
    def test_description_continued_on_the_next_page(self, repeat_header: bool) -> None:
        rows = samples.BANRESERVAS_ROWS
        cut = (*rows[2][:1], rows[2][1][:1], *rows[2][2:])  # solo "PAGOS AL INSTANTE"
        pages = samples.banreservas(
            (*rows[:2], cut), rows[3:], carried=rows[2][1][1:], repeat_header=repeat_header
        )
        (section,) = banreservas_cuenta.parse(pages).sections
        assert [t.description for t in section.transactions] == [
            t.description
            for t in banreservas_cuenta.parse(samples.BANRESERVAS).sections[0].transactions
        ]

    def test_footer_text_is_not_a_continuation(self) -> None:
        (first,) = samples.BANRESERVAS
        bottom = max(line.words[0].top for line in first)
        footer = placed(
            (bottom + 13.4, " " * 29 + "Página 1 de 1"),
        )
        (section,) = banreservas_cuenta.parse((first + footer,)).sections
        assert section.transactions[0].description.endswith("OTRO APELLIDO")

    def test_text_right_of_the_description_column_is_not_a_continuation(self) -> None:
        (first,) = samples.BANRESERVAS
        bottom = max(line.words[0].top for line in first)
        note = placed((bottom + 13.4, " " * 64 + "NOTA"))  # empieza en la columna Débito
        (section,) = banreservas_cuenta.parse((first + note,)).sections
        assert section.transactions[0].description.endswith("OTRO APELLIDO")

    def test_currency_ignores_row_descriptions(self) -> None:
        row = ("28/01/2026", ("TRANSFERENCIA", "CAMBIO DIVISAS USD"), "-26,000.00", None,
               "1,408.59")  # fmt: skip
        (section,) = banreservas_cuenta.parse(_rows(row, *samples.BANRESERVAS_ROWS[1:])).sections
        assert section.currency == "DOP"
        assert section.transactions[-1].description == "TRANSFERENCIA CAMBIO DIVISAS USD"


class TestValidation:
    def test_balances_reconcile(self) -> None:
        statement = banreservas_cuenta.parse(samples.BANRESERVAS)
        (section,) = statement.sections
        assert section.previous_balance == Decimal("10000.00")
        assert section.closing_balance == Decimal("1408.59")
        assert validate_statement(statement) == ()

    def test_header_balance_is_not_the_closing_balance(self) -> None:
        # El balance de la cabecera es el del día del reporte: no se usa.
        statement = banreservas_cuenta.parse(samples.banreservas(samples.BANRESERVAS_ROWS))
        assert statement.sections[0].closing_balance != Decimal("1500.00")

    def test_broken_chain_is_invalid(self) -> None:
        problems = validate_statement(banreservas_cuenta.parse(samples.BANRESERVAS_BROKEN_CHAIN))
        assert problems
        assert any("imprime balance" in p for p in problems)

    def test_partial_month_is_a_printout(self) -> None:
        statement = banreservas_cuenta.parse(samples.BANRESERVAS_PARTIAL)
        assert statement.parser == banreservas_cuenta.PARTIAL_NAME == "banreservas_parcial"
        assert statement.identifier == "0000000000"
        # Cubre del inicio del periodo al día del reporte.
        assert (statement.period_start, statement.period_end) == (
            date(2026, 1, 1),
            date(2026, 1, 27),
        )
        (section,) = statement.sections
        assert section.closing_balance == Decimal("27408.59")  # el de la cabecera
        assert len(section.transactions) == len(samples.BANRESERVAS_ROWS) - 1
        assert validate_statement(statement) == ()

    def test_full_month_is_official(self) -> None:
        assert banreservas_cuenta.parse(samples.BANRESERVAS).parser == "banreservas_cuenta"

    def test_report_on_the_last_day_is_still_partial(self) -> None:
        statement = banreservas_cuenta.parse(
            _rows(*samples.BANRESERVAS_ROWS, report="31/01/2026", balance="1,408.59")
        )
        assert statement.parser == banreservas_cuenta.PARTIAL_NAME
        assert statement.period_end == date(2026, 1, 31)

    def test_partial_header_balance_must_match_the_newest_row(self) -> None:
        pages = _rows(*samples.BANRESERVAS_ROWS[1:], report="27/01/2026", balance="1.00")
        problems = validate_statement(banreservas_cuenta.parse(pages))
        assert any("balance al corte" in p for p in problems)

    def test_partial_row_after_the_report_is_an_error(self) -> None:
        with pytest.raises(ParseError, match="fuera del periodo"):
            banreservas_cuenta.parse(
                _rows(*samples.BANRESERVAS_ROWS, report="27/01/2026", balance="1,408.59")
            )

    def test_report_on_the_printed_end_day_is_complete(self) -> None:
        statement = banreservas_cuenta.parse(_rows(*samples.BANRESERVAS_ROWS, report="01/02/2026"))
        assert statement.period_end == date(2026, 1, 31)

    def test_row_on_the_printed_end_day_is_outside_the_period(self) -> None:
        # Ese día es el primero del estado siguiente: contarlo aquí lo contaría dos veces.
        late = ("01/02/2026", ("TRANSFERENCIA",), "-1.00", None, "1,407.59")
        with pytest.raises(ParseError, match="fuera del periodo"):
            banreservas_cuenta.parse(_rows(late, *samples.BANRESERVAS_ROWS))

    def test_period_must_end_after_it_starts(self) -> None:
        pages = samples.banreservas(samples.BANRESERVAS_ROWS, period="01/01/2026 - 01/01/2026")
        with pytest.raises(ParseError, match="periodo"):
            banreservas_cuenta.parse(pages)

    def test_no_movements_is_an_error(self) -> None:
        with pytest.raises(ParseError, match="movimientos"):
            banreservas_cuenta.parse(_rows())

    def test_row_outside_the_period_is_an_error(self) -> None:
        late = ("02/02/2026", ("TRANSFERENCIA",), "-1.00", None, "1,407.59")
        with pytest.raises(ParseError, match="fuera del periodo"):
            banreservas_cuenta.parse(_rows(late, *samples.BANRESERVAS_ROWS))

    def test_debit_without_minus_is_an_error(self) -> None:
        row = ("28/01/2026", ("TRANSFERENCIA",), "26,000.00", None, "1,408.59")
        with pytest.raises(ParseError, match="débito"):
            banreservas_cuenta.parse(_rows(row, *samples.BANRESERVAS_ROWS[1:]))

    def test_credit_with_minus_is_an_error(self) -> None:
        row = ("20/01/2026", ("PAGO INTERES INVENTADO",), None, "-12.34", "27,408.59")
        rows = samples.BANRESERVAS_ROWS
        with pytest.raises(ParseError, match="crédito"):
            banreservas_cuenta.parse(_rows(rows[0], row, *rows[2:]))

    def test_row_with_both_or_no_amount_is_an_error(self) -> None:
        both = ("28/01/2026", ("TRANSFERENCIA",), "-1.00", "1.00", "1,408.59")
        none = ("28/01/2026", ("TRANSFERENCIA",), None, None, "1,408.59")
        for bad in (both, none):
            with pytest.raises(ParseError):
                banreservas_cuenta.parse(_rows(bad, *samples.BANRESERVAS_ROWS[1:]))

    @pytest.mark.parametrize("end", [69, 90, 112])  # débito, crédito, balance
    def test_money_outside_a_row_is_an_error(self, end: int) -> None:
        # Un monto en un renglón sin fecha sería un movimiento perdido en silencio.
        (first,) = samples.BANRESERVAS
        stray = placed((252.5, " " * (end - 5) + "-9.99"))
        with pytest.raises(ParseError, match="fuera de una fila"):
            banreservas_cuenta.parse((first + stray,))

    def test_amount_inside_a_description_is_text(self) -> None:
        row = ("28/01/2026", ("TRANSFERENCIA", "REF 5.00"), "-26,000.00", None, "1,408.59")
        (section,) = banreservas_cuenta.parse(_rows(row, *samples.BANRESERVAS_ROWS[1:])).sections
        assert section.transactions[-1].description == "TRANSFERENCIA REF 5.00"

    def test_missing_period_is_an_error(self) -> None:
        pages = samples.banreservas(samples.BANRESERVAS_ROWS, period="sin periodo")
        with pytest.raises(ParseError, match="periodo"):
            banreservas_cuenta.parse(pages)

    def test_empty_document_is_an_error(self) -> None:
        with pytest.raises(ParseError):
            banreservas_cuenta.parse(())
