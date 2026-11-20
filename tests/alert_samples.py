"""Synthetic bank alert emails (made-up holders, merchants, amounts and card digits).

They imitate Popular's purchase alert: an HTML greeting with the holder, the card product and
its last four digits, then a table with amount, currency, date, merchant and status. The exact
wording of the real statuses is unknown: the fixtures use the ones in the parser's table plus
one it does not know.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from email.header import Header
from email.message import EmailMessage

from michelito.alerts.common import AlertEmail

SENDER = "Banco Popular <notificaciones@popularenlinea.com>"  # spanish-data
CARD = "5151"
OTHER_CARD = "9991"

# Authentication-Results as Gmail writes them (topmost header): the bank's DKIM passes, fails,
# or a different domain signed. FORGED is what a sender could add below the receiver's.
SIGNED = (
    "mx.google.com; dkim=pass header.i=@popularenlinea.com header.s=s1 header.b=AbCd; "
    "spf=pass smtp.mailfrom=popularenlinea.com; dmarc=pass header.from=popularenlinea.com"
)
_DMARC = "dmarc=pass (p=REJECT) header.from=popularenlinea.com"
SIGNED_SUBDOMAIN = (
    f"mx.google.com; dkim=pass header.d=mail.popularenlinea.com header.s=s1; {_DMARC}"
)
DKIM_FAILED = f"mx.google.com; dkim=fail header.d=popularenlinea.com; spf=softfail; {_DMARC}"
OTHER_SIGNER = f"mx.google.com; dkim=pass header.d=attacker.example; spf=pass; {_DMARC}"
FORGED = f"mx.google.com; dkim=pass header.d=popularenlinea.com; {_DMARC}"
UNTRUSTED_RECEIVER = f"mx.attacker.example; dkim=pass header.d=popularenlinea.com; {_DMARC}"
# Adversarial headers (all written as the topmost, by "mx.google.com" unless said otherwise).
NO_DMARC = "mx.google.com; dkim=pass header.d=popularenlinea.com; dmarc=fail header.from=x.com"
DMARC_OTHER_FROM = (
    "mx.google.com; dkim=pass header.d=popularenlinea.com; dmarc=pass header.from=attacker.example"
)
PASS_IN_COMMENT = (
    "mx.google.com; dkim=fail (dkim=pass header.d=popularenlinea.com) header.d=attacker.example; "
    f"{_DMARC}"
)
SEMICOLON_IN_COMMENT = (
    "mx.google.com; spf=pass (; dkim=pass header.d=popularenlinea.com) smtp.mailfrom=x.example; "
    f"{_DMARC}"
)
SEMICOLON_IN_QUOTES = (
    f'mx.google.com; spf=pass reason="; dkim=pass header.d=popularenlinea.com"; {_DMARC}'
)
QUOTED_DOMAIN = f'mx.google.com; dkim=pass header.d="popularenlinea.com"; {_DMARC}'
EVIL_WITH_COMMENT = f"mx.google.com; dkim=pass header.d=evil.example (popularenlinea.com); {_DMARC}"
MULTIPLE_CLAUSES = (
    "mx.google.com; dkim=fail header.d=popularenlinea.com; dkim=pass header.d=other.example; "
    f"dkim=pass header.i=@popularenlinea.com; arc=pass; {_DMARC}"
)
VERSIONED_METHOD = f"mx.google.com; dkim/2=pass header.d=popularenlinea.com; {_DMARC}"
ID_IN_COMMENT = (
    f"mx.attacker.example (mx.google.com); dkim=pass header.d=popularenlinea.com; {_DMARC}"
)
UNCLOSED_COMMENT = f"mx.google.com; dkim=pass (header.d=popularenlinea.com; {_DMARC}"

# spanish-data: begin (synthetic alerts in the bank's language)
SUBJECT = "Notificación de Consumo"
_GREETING = (
    "<p>Estimado(a) MARIA FICTICIA PEREZ:</p>"
    "<p>Le informamos que se ha realizado un consumo con su tarjeta VISA ORO FICTICIA "
    "terminada en {card}.</p>"
)
_HORIZONTAL = (
    "<table border='1'><tr><th>Monto</th><th>Moneda</th><th>Fecha</th><th>Comercio</th>"
    "<th>Estatus</th></tr><tr><td>{amount}</td><td>{currency}</td><td>{day}</td>"
    "<td>{merchant}</td><td>{status}</td></tr></table>"
)
_VERTICAL = (
    "<table><tr><td>Monto:</td><td>{amount}</td></tr><tr><td>Moneda:</td><td>{currency}</td></tr>"
    "<tr><td>Fecha:</td><td>{day}</td></tr><tr><td>Comercio:</td><td>{merchant}</td></tr>"
    "<tr><td>Estatus:</td><td>{status}</td></tr></table>"
)
_FOOTER = "<p>Si no reconoce esta transacción, llame a su banco.</p>"
_TEXT = (
    "Estimado(a) MARIA FICTICIA PEREZ:\n"
    "Le informamos que se ha realizado un consumo con su tarjeta terminada en {card}.\n"
    "Monto: {amount}\nMoneda: {currency}\nFecha: {day}\nComercio: {merchant}\n"
    "Estatus: {status}\n"
)
APPROVED = "Aprobada"
DECLINED = "Declinada"
REVERSED = "Reversada"
UNKNOWN_STATUS = "En proceso"
# The currency cell as the real alerts write it.
PESOS = "Peso dominicano"
DOLLARS = "Dólar estadounidense"
# spanish-data: end


def alert_html(
    *,
    amount: str = "1,250.00",
    currency: str = PESOS,
    day: str = "14/02/2026 10:32",
    merchant: str = "SUPERMERCADO FICTICIO",
    status: str = APPROVED,
    card: str = CARD,
    layout: str = "horizontal",
) -> str:
    table = _HORIZONTAL if layout == "horizontal" else _VERTICAL
    body = table.format(amount=amount, currency=currency, day=day, merchant=merchant, status=status)
    # The bank wraps everything in layout tables: the data table is nested.
    return (
        "<html><head><style>td { color: #333 }</style></head><body>"
        f"<table><tr><td>{_GREETING.format(card=card)}{body}{_FOOTER}</td></tr></table>"
        "</body></html>"
    )


def alert_text(**fields: str) -> str:
    values = {
        "amount": "1,250.00",
        "currency": PESOS,
        "day": "14/02/2026",
        "merchant": "SUPERMERCADO FICTICIO",
        "status": APPROVED,
        "card": CARD,
    } | fields
    return _TEXT.format(**values)


def alert_email(
    message_id: str = "m-alert-1",
    *,
    html: str | None = None,
    text: str = "",
    subject: str = SUBJECT,
    sender: str = SENDER,
    received: date = date(2026, 2, 14),
    auth: tuple[str, ...] = (SIGNED,),
    **fields: str,
) -> AlertEmail:
    return AlertEmail(
        message_id=message_id,
        sender=sender,
        subject=subject,
        received_at=datetime(received.year, received.month, received.day, 15, tzinfo=UTC),
        html=alert_html(**fields) if html is None else html,
        text=text,
        auth_results=auth,
    )


def raw_alert(
    html: str | None = None,
    text: str | None = None,
    auth: tuple[str, ...] = (SIGNED,),
    charset: str = "utf-8",
    **fields: str,
) -> bytes:
    """The same alert as a raw RFC 822 message (what a forwarding endpoint receives); `auth`:
    its Authentication-Results headers, topmost first; `charset`: the one both parts are
    encoded in (and declare)."""
    message = EmailMessage()
    for value in auth:
        message["Authentication-Results"] = value
    message["From"] = SENDER
    message["To"] = "someone@example.com"
    message["Subject"] = SUBJECT
    message["Date"] = "Sat, 14 Feb 2026 10:33:00 -0400"
    message["Message-ID"] = "<synthetic-alert-1@example.com>"
    message.set_content(alert_text(**fields) if text is None else text, charset=charset)
    message.add_alternative(
        alert_html(**fields) if html is None else html, subtype="html", charset=charset
    )
    return bytes(message)


def raw_mislabeled(html: str, declared: str | None) -> bytes:
    """A single HTML part whose bytes are windows-1252, declaring `declared` (or nothing)."""
    head = "\r\n".join(
        [
            f"Authentication-Results: {SIGNED}",
            f"From: {SENDER}",
            f"Subject: {Header(SUBJECT, 'utf-8').encode()}",
            "Date: Sat, 14 Feb 2026 10:33:00 -0400",
            "Message-ID: <synthetic-alert-2@example.com>",
            "MIME-Version: 1.0",
            "Content-Type: text/html" + (f"; charset={declared}" if declared else ""),
            "Content-Transfer-Encoding: 8bit",
        ]
    )
    return head.encode("ascii") + b"\r\n\r\n" + html.encode("cp1252")
