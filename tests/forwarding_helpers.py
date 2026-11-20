"""Synthetic forwarded emails and signed inbound requests for the email-forwarding tests.

Every message is made up: the senders are the banks' public addresses from
`config.DEFAULT_SOURCES`, the statements are `tests.samples` pages turned into PDFs
(`tests.synthetic_pdf`), the alerts come from `tests.alert_samples` and Gmail's confirmation
email imitates its shape with a made-up code. Nothing is sent anywhere: the requests go to a
`TestClient` (or, for the e2e server, to 127.0.0.1).
"""

from __future__ import annotations

import base64
import json
import secrets
import sqlite3
import time
from email.message import EmailMessage

from michelito import db
from michelito.hosted import forwarding, uploads
from michelito.parsers import detect
from michelito.parsers.common import Page
from tests import alert_samples, samples, synthetic_pdf

SECRET = b"made-up-inbound-secret-0123456789abcdef"
POPULAR_STATEMENTS = "estados@popularenlinea.com"  # spanish-data
BHD_STATEMENTS = "servicios@bhd.com.do"
GMAIL = "forwarding-noreply@google.com"
STRANGER = "billing@unknown-sender.example"
PASSWORD = synthetic_pdf.E2E_PASSWORD
# A made-up Gmail confirmation code (a staircase: no real code looks like it).
GMAIL_CODE = "123456789"
GMAIL_LINK = "https://mail-settings.google.com/mail/vf-%5Bmade-up%5D-made-up-link"


def know_accounts(conn: sqlite3.Connection, *page_sets: tuple[Page, ...]) -> None:
    """Give the person the accounts (and cards) of these synthetic statements, as an earlier
    upload would have, without storing the statements themselves."""
    for pages in page_sets:
        parser = detect(pages)
        assert parser is not None
        examined = uploads._parse_all(parser, pages)
        with conn:
            for statement in examined.squared:
                db._card_id(conn, db._account_id(conn, statement), statement)


EVERY_ACCOUNT = (samples.POPULAR_PAGES, samples.BHD_TC_PAGES, samples.BHD_AHORRO_PAGES)


def worker_auth(domain: str, dkim: bool = True, dmarc: bool = True) -> str:
    """What Cloudflare's receiving server writes for a forwarded message: SPF fails (the
    forwarder is not the bank), DKIM and DMARC pass through the bank's signature."""
    dkim_result = "pass" if dkim else "fail"
    dmarc_result = "pass" if dmarc else "fail"
    return (
        f"mx.cloudflare.net; dkim={dkim_result} header.d={domain} header.s=s1; "
        f"spf=fail smtp.mailfrom=forwarder.example; dmarc={dmarc_result} header.from={domain}"
    )


def popular_card(password: str | None = None) -> bytes:
    return synthetic_pdf.build(samples.POPULAR_PAGES, password)


def bhd_card() -> bytes:
    """BHD's card statement, locked with `PASSWORD`."""
    return synthetic_pdf.build(samples.BHD_TC_PAGES, PASSWORD)


def bhd_savings() -> bytes:
    return synthetic_pdf.build(samples.BHD_AHORRO_PAGES)


def wrong_total() -> bytes:
    return synthetic_pdf.build((samples.POPULAR_DOP_WRONG_TOTAL,))


def other_bank() -> bytes:
    return synthetic_pdf.build((samples.UNKNOWN,))


def statement_email(
    sender: str,
    *pdfs: bytes,
    message_id: str | None = None,
    names: tuple[str, ...] = (),
    inner_auth: str | None = None,
) -> bytes:
    message = EmailMessage()
    if inner_auth is not None:
        message["Authentication-Results"] = inner_auth
    message["From"] = f"Bank <{sender}>"
    message["To"] = "person@example.com"
    message["Subject"] = "Statement"
    message["Date"] = "Mon, 02 Feb 2026 08:00:00 -0400"
    message["Message-ID"] = f"<{message_id or secrets.token_hex(8)}@example.com>"
    message.set_content("Your statement is attached.")
    for number, pdf in enumerate(pdfs):
        name = names[number] if number < len(names) else f"statement-{number}.pdf"
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename=name)
    return bytes(message)


def alert_email(message_id: str | None = None, **fields: str) -> bytes:
    message = EmailMessage()
    message["From"] = alert_samples.SENDER
    message["To"] = "person@example.com"
    message["Subject"] = alert_samples.SUBJECT
    message["Date"] = "Sat, 14 Feb 2026 10:33:00 -0400"
    message["Message-ID"] = f"<{message_id or secrets.token_hex(8)}@example.com>"
    message.set_content(alert_samples.alert_text(**fields))
    message.add_alternative(alert_samples.alert_html(**fields), subtype="html")
    return bytes(message)


def gmail_confirmation(message_id: str | None = None, link: str = GMAIL_LINK) -> bytes:
    message = EmailMessage()
    message["From"] = f"Gmail Team <{GMAIL}>"
    message["To"] = "person@example.com"
    message["Subject"] = f"(#{GMAIL_CODE}) Gmail Forwarding Confirmation"
    message["Date"] = "Mon, 02 Feb 2026 08:00:00 -0000"
    message["Message-ID"] = f"<{message_id or secrets.token_hex(8)}@example.com>"
    message.set_content(
        "someone@example.com has requested to automatically forward mail to your address.\n"
        f"Confirmation code: {GMAIL_CODE}\n\n"
        f"To allow it, click the link below:\n{link}\n"
    )
    return bytes(message)


def signed(
    recipient: str,
    raw: bytes,
    auth: str,
    secret: bytes = SECRET,
    at: float | None = None,
    nonce: str | None = None,
) -> tuple[bytes, dict[str, str]]:
    """The body and headers of a request as the Email Worker signs it."""
    body = json.dumps(
        {"recipient": recipient, "raw": base64.b64encode(raw).decode("ascii"), "auth": auth}
    ).encode()
    stamp = str(int(time.time() if at is None else at))
    chosen = nonce or secrets.token_urlsafe(18)
    return body, {
        "Content-Type": "application/json",
        "X-Michelito": "1",
        forwarding.TIMESTAMP_HEADER: stamp,
        forwarding.NONCE_HEADER: chosen,
        forwarding.SIGNATURE_HEADER: forwarding.sign(secret, stamp, chosen, body),
        forwarding.PREAUTH_HEADER: forwarding.preauth(secret, stamp, chosen, len(body)),
    }
