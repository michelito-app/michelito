"""Bank-alert parsing: Popular's purchase alert (synthetic fixtures, `tests.alert_samples`)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from michelito import alerts
from michelito.alerts import inspect, popular_purchase
from michelito.alerts.common import AlertParseError, failure_fingerprint, parse_amount, parse_day
from tests import alert_samples as samples


def test_an_approved_rd_purchase() -> None:
    found = popular_purchase.parse(samples.alert_email())
    assert found.kind == "approved"
    assert (found.last4, found.amount, found.currency) == (samples.CARD, Decimal("1250.00"), "DOP")
    assert found.day == date(2026, 2, 14)
    assert found.merchant == "SUPERMERCADO FICTICIO"


def test_a_us_purchase() -> None:
    email = samples.alert_email(amount="49.99", currency="US", merchant="TIENDA ONLINE FICTICIA")
    found = popular_purchase.parse(email)
    assert (found.amount, found.currency, found.kind) == (Decimal("49.99"), "USD", "approved")


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (samples.APPROVED, "approved"),
        (samples.DECLINED, "declined"),
        (samples.REVERSED, "reversed"),
        ("APROBADA.", "approved"),  # spanish-data
        (samples.UNKNOWN_STATUS, "unknown"),
    ],
)
def test_statuses_map_through_a_small_table(status: str, kind: str) -> None:
    assert popular_purchase.parse(samples.alert_email(status=status)).kind == kind


def test_an_unknown_status_is_never_approved() -> None:
    waiting = "Pendiente de confirmar"  # spanish-data
    found = popular_purchase.parse(samples.alert_email(status=waiting))
    assert found.kind == "unknown"


def test_html_entities_and_extra_whitespace() -> None:
    email = samples.alert_email(
        amount="&nbsp; 3,000.50 &nbsp;",
        currency=" RD$ ",
        merchant="  CAF&Eacute;   &amp;  PAN\n  FICTICIO ",
        day="  05/02/2026   ",
        status="  Aprobada  ",  # spanish-data
    )
    found = popular_purchase.parse(email)
    assert found.amount == Decimal("3000.50")
    assert found.currency == "DOP"
    assert found.merchant == "CAFÉ & PAN FICTICIO"  # spanish-data
    assert found.day == date(2026, 2, 5)


def test_a_vertical_table() -> None:
    found = popular_purchase.parse(samples.alert_email(layout="vertical", currency="US"))
    assert (found.currency, found.amount, found.last4) == ("USD", Decimal("1250.00"), samples.CARD)


def test_a_text_only_body() -> None:
    email = samples.alert_email(html="", text=samples.alert_text(amount="75.00", currency="US"))
    found = popular_purchase.parse(email)
    assert (found.amount, found.currency) == (Decimal("75.00"), "USD")


def test_matches_only_the_purchase_alert() -> None:
    assert popular_purchase.matches(samples.alert_email())
    assert alerts.detect(samples.alert_email()) is popular_purchase
    other = samples.alert_email(subject="Su estado de cuenta")  # spanish-data
    assert not popular_purchase.matches(other)
    stranger = samples.alert_email(sender="Someone <x@example.com>")
    assert alerts.detect(stranger) is None


@pytest.mark.parametrize(
    ("html", "field"),
    [
        ("<html><body><p>Hola</p></body></html>", "table"),  # spanish-data
        (samples.alert_html(card="xx"), "card"),
        (samples.alert_html(amount="mil pesos"), "amount"),  # spanish-data
        (samples.alert_html(currency="EUR"), "currency"),
        (samples.alert_html(day="ayer"), "date"),  # spanish-data
        (samples.alert_html(merchant=" "), "merchant"),
        (samples.alert_html(status=" "), "status"),
    ],
)
def test_an_unknown_layout_names_the_failed_field(html: str, field: str) -> None:
    email = samples.alert_email(html=html)
    with pytest.raises(AlertParseError) as caught:
        popular_purchase.parse(email)
    assert caught.value.field == field


def test_the_failure_fingerprint_is_data_free() -> None:
    email = samples.alert_email(html=samples.alert_html(currency="EUR", merchant="SECRETO SA"))
    with pytest.raises(AlertParseError) as caught:
        popular_purchase.parse(email)
    found = failure_fingerprint(email, popular_purchase.NAME, caught.value)
    assert found == {
        "sender_domain": "popularenlinea.com",
        "alert_type": "popular_purchase",
        "failed_field": "currency",
        "layout": "horizontal",
        "has_html": "yes",
        "has_text": "no",
    }
    text = json.dumps(found)
    for value in ("SECRETO", samples.CARD, "1,250", "MARIA", "EUR"):
        assert value not in text


def test_amounts_and_dates() -> None:
    assert parse_amount("RD$1,234.56") == Decimal("1234.56")
    assert parse_amount("700") == Decimal("700.00")
    assert parse_day("2026-02-01") == date(2026, 2, 1)
    assert parse_day("01-02-2026 08:15:00 PM") == date(2026, 2, 1)
    for bad in ("", "0.00", "1.2.3", "-5.00"):
        with pytest.raises(AlertParseError):
            parse_amount(bad)


def test_from_bytes_reads_a_raw_message_in_memory() -> None:
    email = alerts.from_bytes(samples.raw_alert(amount="12.00", currency="US"))
    assert email.message_id == "synthetic-alert-1@example.com"
    assert email.sender_address == "notificaciones@popularenlinea.com"
    found = popular_purchase.parse(email)
    assert (found.amount, found.currency) == (Decimal("12.00"), "USD")


def test_inspect_prints_only_structure(capsys: pytest.CaptureFixture[str]) -> None:
    raw = samples.raw_alert(merchant="FARMACIA SECRETA", amount="9,876.54")
    report = inspect.describe(raw)
    assert report["parser"] == "popular_purchase"
    assert report["parsed"] is True
    assert report["fields"] == dict.fromkeys(inspect.FIELDS, True)
    inspect.main(["-"], stdin=raw)
    printed = capsys.readouterr().out
    for value in ("FARMACIA", "SECRETA", "9,876", samples.CARD, "MARIA", "2026"):
        assert value not in printed
    assert "parsed: yes" in printed


def test_inspect_reports_a_failure_without_values(capsys: pytest.CaptureFixture[str]) -> None:
    raw = samples.raw_alert(html=samples.alert_html(currency="EUR"), text="")
    report = inspect.describe(raw)
    assert report["parsed"] is False
    assert report["failure"]["failed_field"] == "currency"  # type: ignore[index]
    assert report["fields"]["currency"] is False  # type: ignore[index]
    assert report["fields"]["amount"] is True  # type: ignore[index]
    inspect.main(["-"], stdin=raw)
    assert "EUR" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("cell", "code"),
    [
        (samples.PESOS, "DOP"),
        ("PESO DOMINICANO", "DOP"),  # spanish-data
        ("pesos", "DOP"),  # spanish-data
        ("RD$", "DOP"),
        ("DOP", "DOP"),
        (samples.DOLLARS, "USD"),
        ("DOLAR ESTADOUNIDENSE", "USD"),  # spanish-data
        ("dólares", "USD"),  # spanish-data
        ("US$", "USD"),
        ("USD", "USD"),
    ],
)
def test_the_currency_cell_is_read_by_its_folded_name(cell: str, code: str) -> None:
    assert popular_purchase.parse(samples.alert_email(currency=cell)).currency == code
