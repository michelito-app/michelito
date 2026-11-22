"""Synthetic merchant emails (made-up people, orders and amounts).

They imitate the two Amazon emails the readers know, in the shape observed in real ones (never
their content): a plain-text part made of short lines and an HTML part where every link goes
through a redirect whose target is a URL-encoded parameter, the visible order number is preceded
by an invisible direction mark, and amounts are written differently in each part.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from urllib.parse import quote

from michelito.alerts.common import AlertEmail

ORDER_SENDER = "Amazon.com <auto-confirm@amazon.com>"
SHIPMENT_SENDER = "Amazon.com <shipment-tracking@amazon.com>"
ORDER_SUBJECT = "Ordered 6 items: Kitchen, Tools, and more"
SHIPMENT_SUBJECT = "Shipped 3 items: Kitchen"

SIGNED = (
    "mx.google.com; dkim=pass header.i=@amazon.com header.s=s1 header.b=AbCd; "
    "spf=pass smtp.mailfrom=amazon.com; dmarc=pass (p=QUARANTINE) header.from=amazon.com"
)
OTHER_SIGNER = (
    "mx.google.com; dkim=pass header.d=attacker.example; spf=pass; "
    "dmarc=pass header.from=amazon.com"
)

FIRST_ORDER = "111-1111111-1111111"
SECOND_ORDER = "222-2222222-2222222"
SHIPMENT_ID = "Ab1Cd2Ef3"
_MARK = "‫"  # the invisible mark before the visible order number
_SITE = "https://www.amazon.com"


def _redirect(target: str) -> str:
    """A link as the emails write it: the real address is the `U` parameter."""
    return f"{_SITE}/gp/r.html?C=X1&M=urn:rtn:msg:20260214&R=Y2&U={quote(target, safe='')}&H=Z3"


def order_page(order: str) -> str:
    return f"{_SITE}/your-orders/order-details?orderID={order}&ref_=p_btn"


def track_page(order: str, shipment: str = SHIPMENT_ID) -> str:
    return (
        f"{_SITE}/progress-tracker/package?_encoding=UTF8&orderId={order}"
        f"&packageIndex=0&shipmentId={shipment}&vt=NOTIFICATIONS"
    )


def _text_block(order: str, action: str, link: str) -> str:
    return f"Arriving Friday\n\nPERSONA - CIUDAD, ST\n\nOrder #\n{order}\n\n{action}\n{link}\n"


def _html_block(order: str, summary: str, action: str, link: str) -> str:
    return (
        "<table role='presentation'><tr><td>"
        "<span class='rio-text rio-text-1'>Arriving Friday</span><br>"
        f"<span class='rio-text rio-text-2'>{summary}</span><br>"
        "<span class='rio-text rio-text-3'>PERSONA - CIUDAD, ST</span><br>"
        f"<span class='rio-text rio-text-4'><span>Order #</span> <span>{_MARK}{order}</span></span>"
        f"</td></tr><tr><td class='rio-button-cta-primary'>"
        f"<a class='rio-button' href='{_redirect(link)}'>{action}</a></td></tr></table>"
    )


def _html_total(label: str, amount: str) -> str:
    return f"<table><tr><td>{label}</td><td align='right'><b>{amount}</b></td></tr></table>"


def _page(body: str) -> str:
    return (
        "<html><head><style>.rio-asin-image{width:80px}</style></head><body>"
        "<div class='rootContent moduleId-stepTracker'><h2>Persona, thanks!</h2></div>"
        f"<div class='rootContent moduleId-rexMultiOrderCard'>{body}</div>"
        "<div class='rootContent moduleId-transactionalFooter'>"
        f"<a href='{_redirect(_SITE + '/gp/help/customer/display.html?nodeId=1')}'>Privacy</a>"
        "</div></body></html>"
    )


# An order email with two orders: the first has two delivery blocks and one total.
ORDERS = ((FIRST_ORDER, 2, "130.56"), (SECOND_ORDER, 1, "35.80"))


def order_text(orders: tuple[tuple[str, int, str], ...] = ORDERS) -> str:
    parts = ["Your Orders\n\nPersona, thanks for your order!\nOrdered\n\nShipped\n"]
    for order, blocks, total in orders:
        parts.extend(
            _text_block(order, "View or edit order", order_page(order)) for _ in range(blocks)
        )
        # The plain-text part drops a trailing zero: "35.8 USD".
        parts.append(f"Grand Total:\n{float(total):g} USD\n")
    parts.append("©2026 Amazon.com, Inc. or its affiliates.")
    return "\n".join(parts)


def order_html(orders: tuple[tuple[str, int, str], ...] = ORDERS) -> str:
    body = []
    for order, blocks, total in orders:
        body.extend(
            _html_block(order, "3 Kitchen", "View or edit order", order_page(order))
            for _ in range(blocks)
        )
        body.append(_html_total("Grand Total:", f"${total}"))
    return _page("".join(body))


def shipment_text(
    order: str = FIRST_ORDER, total: str = "110.97", link_order: str | None = None
) -> str:
    link = track_page(link_order or order)
    return (
        "Your Orders\n\nPersona, your package was shipped!\nOrdered\n\nShipped\n\n"
        + _text_block(order, "Track package", link)
        + f"\nTotal\n{float(total):g} USD\n\nView related transactions in Your Transactions\n"
        f"{_SITE}/cpe/yourpayments/transactions?transactionTag={order}&ref_=fed\n"
    )


def shipment_html(
    order: str = FIRST_ORDER, total: str = "110.97", link_order: str | None = None
) -> str:
    link = track_page(link_order or order)
    return _page(
        _html_block(order, "3 Kitchen", "Track package", link) + _html_total("Total", f"${total}")
    )


def receipt_email(
    message_id: str = "m-receipt-1",
    *,
    sender: str = ORDER_SENDER,
    subject: str = ORDER_SUBJECT,
    html: str = "",
    text: str = "",
    received: date = date(2026, 2, 14),
    auth: tuple[str, ...] = (SIGNED,),
) -> AlertEmail:
    return AlertEmail(
        message_id=message_id,
        sender=sender,
        subject=subject,
        received_at=datetime(received.year, received.month, received.day, 15, tzinfo=UTC),
        html=html,
        text=text,
        auth_results=auth,
    )


def order_email(message_id: str = "m-order-1", **fields: object) -> AlertEmail:
    values: dict[str, object] = {"html": order_html(), "text": order_text()} | fields
    return receipt_email(message_id, **values)  # type: ignore[arg-type]


def shipment_email(message_id: str = "m-shipment-1", **fields: object) -> AlertEmail:
    values: dict[str, object] = {
        "sender": SHIPMENT_SENDER,
        "subject": SHIPMENT_SUBJECT,
        "html": shipment_html(),
        "text": shipment_text(),
    } | fields
    return receipt_email(message_id, **values)  # type: ignore[arg-type]
