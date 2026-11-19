from datetime import date
from decimal import Decimal

import pytest

from finanzas.parsers.common import (
    CREDIT,
    DEBIT,
    Line,
    ParseError,
    Section,
    Statement,
    Transaction,
    Word,
    column_positions,
    group_lines,
    is_amount,
    nearest_column,
    normalize,
    parse_amount,
    parse_date,
    resolve_day_month,
    validate_section,
    validate_statement,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2,764.81", Decimal("2764.81")),
        ("0.15", Decimal("0.15")),
        ("203,517.37", Decimal("203517.37")),
        ("1234.50", Decimal("1234.50")),
        ("-5,000.00", Decimal("-5000.00")),
        ("5,000.00-", Decimal("-5000.00")),
    ],
)
def test_parse_amount(text: str, expected: Decimal) -> None:
    assert is_amount(text)
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["1,38.40", "12", "RD$", "0.00CKS", "1.5", ""])
def test_rejects_non_amounts(text: str) -> None:
    assert not is_amount(text)
    with pytest.raises(ParseError):
        parse_amount(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("13/10/2026", date(2026, 10, 13)), ("2026-08-31", date(2026, 8, 31))],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text) == expected


def test_parse_date_rejects_garbage() -> None:
    with pytest.raises(ParseError):
        parse_date("31-31-2026")


@pytest.mark.parametrize(
    ("text", "reference", "expected"),
    [
        ("15/12", date(2026, 1, 13), date(2025, 12, 15)),
        ("10/01", date(2026, 1, 26), date(2026, 1, 10)),
        ("02/01", date(2025, 12, 30), date(2026, 1, 2)),
        ("29/02", date(2024, 3, 13), date(2024, 2, 29)),
        ("08/10", date(2024, 3, 15), date(2023, 10, 8)),
        ("14/01", date(2026, 1, 13), date(2026, 1, 14)),
        ("21/01", date(2026, 1, 13), date(2025, 1, 21)),
    ],
)
def test_resolve_day_month_picks_nearest_year(text: str, reference: date, expected: date) -> None:
    assert resolve_day_month(text, reference) == expected


@pytest.mark.parametrize("text", ["31/02", "xx", "15-12"])
def test_resolve_day_month_rejects_invalid(text: str) -> None:
    with pytest.raises(ParseError):
        resolve_day_month(text, date(2026, 1, 1))


def test_normalize_strips_accents() -> None:
    assert normalize("Débitos CRÉDITOS Número") == "debitos creditos numero"


def test_group_lines_clusters_by_top_and_sorts_by_x() -> None:
    words = [
        Word("b", 50, 55, 10.0),
        Word("a", 0, 5, 11.5),
        Word("c", 0, 5, 20.0),
    ]
    lines = group_lines(words)
    assert [line.text for line in lines] == ["a b", "c"]


def test_column_positions_and_nearest_column() -> None:
    header = Line(
        (Word("Concepto", 0, 40, 0), Word("Débitos", 100, 135, 0), Word("Créditos", 150, 190, 0))
    )
    columns = column_positions(header, ("debitos", "creditos"))
    assert columns == {"debitos": 135, "creditos": 190}
    assert nearest_column(Word("1.00", 110, 133, 5), columns) == "debitos"
    assert nearest_column(Word("1.00", 170, 191, 5), columns) == "creditos"
    assert column_positions(Line((Word("Débitos", 0, 5, 0),)), ("debitos", "creditos")) is None


def test_nearest_column_rejects_ambiguous_positions() -> None:
    columns = {"debitos": 135.0, "creditos": 190.0}
    with pytest.raises(ParseError):
        nearest_column(Word("1.00", 140, 162, 5), columns)


def _tx(amount: str, direction: str) -> Transaction:
    return Transaction(
        transacted_on=date(2026, 1, 1),
        posted_on=None,
        description="X",
        amount=Decimal(amount),
        direction=direction,
        currency="DOP",
        reference=None,
        mcc=None,
        raw_line="X",
    )


def _section(**overrides: object) -> Section:
    values: dict[str, object] = {
        "currency": "DOP",
        "previous_balance": Decimal("100"),
        "closing_balance": Decimal("150"),
        "minimum_payment": None,
        "credit_limit": None,
        "printed_debits": Decimal("80"),
        "printed_credits": Decimal("30"),
        "transactions": (_tx("80", DEBIT), _tx("30", CREDIT)),
    }
    values.update(overrides)
    return Section(**values)  # type: ignore[arg-type]


def test_validate_liability_section_passes() -> None:
    assert validate_section(_section(), liability=True) == ()


def test_validate_asset_section_uses_opposite_sign() -> None:
    section = _section(closing_balance=Decimal("50"))
    assert validate_section(section, liability=False) == ()


def test_validate_reports_each_mismatch() -> None:
    section = _section(
        printed_debits=Decimal("81"), printed_credits=Decimal("31"), closing_balance=Decimal("1")
    )
    problems = validate_section(section, liability=True)
    assert len(problems) == 3
    assert all(problem.startswith("DOP:") for problem in problems)


def test_validate_requires_some_printed_total() -> None:
    section = _section(
        printed_debits=None, printed_credits=None, previous_balance=None, closing_balance=None
    )
    assert validate_section(section, liability=True) == (
        "DOP: no hay totales impresos para validar",
    )


def test_validate_statement_without_sections() -> None:
    statement = Statement("p", "bank", "credit_card", "X", "1234", date(2026, 1, 1), None, ())
    assert validate_statement(statement) == ("el estado no tiene secciones",)
    assert statement.is_liability
