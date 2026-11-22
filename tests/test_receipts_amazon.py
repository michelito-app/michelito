"""The Amazon readers (`receipts.amazon`): order confirmations and shipments, from synthetic
emails only."""

from decimal import Decimal

import pytest

from michelito import receipts
from michelito.alerts.common import AlertParseError
from michelito.receipts import amazon
from tests import receipt_samples as samples


def test_an_order_email_gives_one_receipt_per_order() -> None:
    found = amazon.parse(samples.order_email())

    assert [(r.kind, r.orders, r.amount, r.currency) for r in found] == [
        ("order", (samples.FIRST_ORDER,), Decimal("130.56"), "USD"),
        ("order", (samples.SECOND_ORDER,), Decimal("35.80"), "USD"),
    ]
    assert {r.parser for r in found} == {"amazon_order"}
    assert {r.merchant for r in found} == {"Amazon"}


def test_the_summary_and_count_come_from_the_subject() -> None:
    first = amazon.parse(samples.order_email())[0]

    assert first.item_count == 6
    assert first.summary == "Kitchen, Tools, and more"


def test_a_subject_without_a_count_leaves_it_unknown() -> None:
    first = amazon.parse(samples.order_email(subject="Ordered: your items"))[0]

    assert first.item_count is None
    assert first.summary == ""


@pytest.mark.parametrize("part", ["html", "text"])
def test_either_part_alone_is_enough_for_an_order(part: str) -> None:
    body = getattr(samples, f"order_{part}")()
    email = samples.order_email(**{"html": "", "text": ""} | {part: body})

    found = amazon.parse(email)

    assert [(r.orders, r.amount) for r in found] == [
        ((samples.FIRST_ORDER,), Decimal("130.56")),
        ((samples.SECOND_ORDER,), Decimal("35.80")),
    ]


def test_a_shipment_gives_its_amount_and_identifier() -> None:
    (found,) = amazon.parse(samples.shipment_email())

    assert found.kind == "shipment"
    assert found.parser == "amazon_shipment"
    assert found.orders == (samples.FIRST_ORDER,)
    assert found.reference == samples.SHIPMENT_ID
    assert found.amount == Decimal("110.97")
    assert found.item_count == 3
    assert found.summary == "Kitchen"


@pytest.mark.parametrize("part", ["html", "text"])
def test_either_part_alone_is_enough_for_a_shipment(part: str) -> None:
    body = getattr(samples, f"shipment_{part}")()
    email = samples.shipment_email(**{"html": "", "text": ""} | {part: body})

    (found,) = amazon.parse(email)

    assert (found.orders, found.reference, found.amount) == (
        (samples.FIRST_ORDER,),
        samples.SHIPMENT_ID,
        Decimal("110.97"),
    )


def test_a_shipment_across_two_orders_keeps_both_numbers() -> None:
    # One package with items of two orders: the visible number and the tracking link differ.
    email = samples.shipment_email(
        html=samples.shipment_html(link_order=samples.SECOND_ORDER),
        text=samples.shipment_text(link_order=samples.SECOND_ORDER),
    )

    (found,) = amazon.parse(email)

    assert found.orders == (samples.FIRST_ORDER, samples.SECOND_ORDER)


def test_the_invisible_mark_is_not_part_of_the_order_number() -> None:
    (found,) = amazon.parse(samples.shipment_email(text=""))

    assert found.orders[0] == samples.FIRST_ORDER
    assert all(character.isdigit() or character == "-" for character in found.orders[0])


@pytest.mark.parametrize(
    ("written", "amount"),
    [("35.8 USD", "35.80"), ("$1,234.56", "1234.56"), ("700 USD", "700.00"), ("$0.99", "0.99")],
)
def test_amounts_as_each_part_writes_them(written: str, amount: str) -> None:
    assert amazon.read_amount(written) == Decimal(amount)


@pytest.mark.parametrize("written", ["", "USD", "12.345 USD", "-5.00 USD", "$0.00", "5 EUR"])
def test_an_amount_that_is_not_one_is_refused(written: str) -> None:
    with pytest.raises(AlertParseError) as error:
        amazon.read_amount(written)

    assert error.value.field == "amount"


def test_the_order_page_link_is_built_not_copied() -> None:
    first = amazon.parse(samples.order_email())[0]

    assert first.link == (
        f"https://www.amazon.com/gp/css/summary/print.html?orderID={samples.FIRST_ORDER}"
    )


def test_nothing_is_read_without_the_senders_signature() -> None:
    with pytest.raises(AlertParseError) as error:
        amazon.parse(samples.order_email(auth=(samples.OTHER_SIGNER,)))

    assert error.value.field == "authentication"


def test_an_order_email_without_a_total_fails_on_the_amount() -> None:
    text = samples.order_text().replace("Grand Total:", "Something else:")

    with pytest.raises(AlertParseError) as error:
        amazon.parse(samples.order_email(html="", text=text))

    assert error.value.field == "amount"


def test_a_total_without_an_order_number_fails_on_the_order() -> None:
    with pytest.raises(AlertParseError) as error:
        amazon.parse(samples.order_email(html="", text="Grand Total:\n10.00 USD\n"))

    assert error.value.field == "order"


def test_two_order_numbers_under_one_total_fail_on_the_order() -> None:
    text = samples.order_text(((samples.FIRST_ORDER, 1, "10.00"),)).replace(
        "Grand Total:",
        f"Order #\n{samples.SECOND_ORDER}\n\nGrand Total:",
    )

    with pytest.raises(AlertParseError) as error:
        amazon.parse(samples.order_email(html="", text=text))

    assert error.value.field == "order"


def test_a_shipment_without_its_identifier_still_reads() -> None:
    text = samples.shipment_text().replace(f"&shipmentId={samples.SHIPMENT_ID}", "")

    (found,) = amazon.parse(samples.shipment_email(html="", text=text))

    assert found.reference == ""
    assert found.amount == Decimal("110.97")


def test_a_link_to_another_site_is_never_read_as_an_order() -> None:
    forged = (
        samples.shipment_text()
        .replace(
            "https://www.amazon.com/progress-tracker",
            "https://amazon.com.attacker.example/progress-tracker",
        )
        .replace("orderId=" + samples.FIRST_ORDER, "orderId=" + samples.SECOND_ORDER)
    )

    (found,) = amazon.parse(samples.shipment_email(html="", text=forged))

    assert found.orders == (samples.FIRST_ORDER,)
    assert found.reference == ""


def test_a_body_too_large_is_refused() -> None:
    with pytest.raises(AlertParseError) as error:
        amazon.parse(samples.order_email(html="<p>" + "x" * 300_000 + "</p>", text=""))

    assert error.value.field == "size"


def test_text_fields_are_bounded() -> None:
    subject = "Ordered 2 items: " + "Kitchen, " * 200

    first = amazon.parse(samples.order_email(subject=subject))[0]

    assert len(first.summary) <= receipts.SUMMARY_MAX


@pytest.mark.parametrize(
    ("email", "name"),
    [
        (samples.order_email(), "amazon_order"),
        (samples.shipment_email(), "amazon_shipment"),
        (samples.order_email(sender="Amazon <store-news@amazon.com>"), None),
        (samples.order_email(sender="Amazon <auto-confirm@amazon.com.attacker.example>"), None),
        (samples.order_email(subject="Your Amazon.com order has shipped"), None),
    ],
)
def test_which_reader_takes_an_email(email: object, name: str | None) -> None:
    found = receipts.detect(email)  # type: ignore[arg-type]

    assert (None if found is None else found.NAME) == name


@pytest.mark.parametrize("written", ["$٣٥.٨٠", "٣٥.٨٠ USD", "$" + "9" * 12 + ".00"])
def test_other_scripts_digits_and_absurd_amounts_are_refused(written: str) -> None:
    with pytest.raises(AlertParseError):
        amazon.read_amount(written)


def test_an_order_number_in_other_digits_is_not_one() -> None:
    odd = samples.FIRST_ORDER.replace("1", "١")
    text = samples.shipment_text().replace(samples.FIRST_ORDER, odd)

    with pytest.raises(AlertParseError) as error:
        amazon.parse(samples.shipment_email(html="", text=text))

    assert error.value.field == "order"


def test_a_redirect_on_another_site_is_not_followed() -> None:
    # The wrapper looks like the merchant's redirect but lives elsewhere.
    html = samples.shipment_html(link_order=samples.SECOND_ORDER).replace(
        "https://www.amazon.com/gp/r.html", "https://tracker.attacker.example/gp/r.html"
    )

    (found,) = amazon.parse(samples.shipment_email(html=html, text=""))

    assert found.orders == (samples.FIRST_ORDER,)
    assert found.reference == ""
