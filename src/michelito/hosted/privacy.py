"""The public privacy page, `GET /privacy` (hosted mode), which Google requires to publish the
OAuth app: server-rendered HTML, so it reads the same without JavaScript (Google's checker runs
none). The Spanish text is the catalog's (`i18n/es_privacy.py`); the English one, with the same
keys, is `ENGLISH` here. Every statement must match the code and the README's hosted sections.

It opens no database and needs no session (the provider resolves no database outside `/api`).
The CSP (`deploy/Caddyfile`) allows styles only from the same origin (`style-src 'self'`, no
inline `<style>`), so its few rules are served at `/privacy.css`. Everything inserted is
escaped; the contact address comes from `MICHELITO_OPS_EMAIL` and is shown only if it is one.
"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

from michelito import i18n

PATH = "/privacy"
CSS_PATH = "/privacy.css"
CONTACT_ENV = "MICHELITO_OPS_EMAIL"
UPDATED = "2026-11-22"
POLICY_URL = "https://developers.google.com/terms/api-services-user-data-policy"
# A plain address: nothing that could mean something in HTML or in a `mailto:` link.
_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}")

# Each section: its key and how many numbered paragraphs it has; a list when `True`.
SECTIONS: tuple[tuple[str, int, bool], ...] = (
    ("who", 1, False),
    ("stored", 6, True),
    ("gmail", 5, False),
    ("protect", 3, False),
    ("others", 6, True),
    ("keep", 3, False),
)

ENGLISH: Mapping[str, str] = {
    "privacy.title": "Privacy at Michelito",
    "privacy.updated": "Last updated: {date}.",
    "privacy.back": "Back to Michelito",
    "privacy.who.title": "Who we are",
    "privacy.who.1": (
        "Michelito (michelito.app) is a personal finance app run by its author. This policy "
        "covers the app at michelito.app, where each person signs in to their own account. The "
        "demo (demo.michelito.app) uses only made-up data."
    ),
    "privacy.stored.title": "What we store",
    "privacy.stored.1": "Your account's email address.",
    "privacy.stored.2": (
        "Your sessions and devices: the browser, the system and the date of the last activity. "
        "We never store your IP address."
    ),
    "privacy.stored.3": (
        "What comes out of the statements you upload or forward (transactions, balances and "
        "accounts), and your corrections and notes."
    ),
    "privacy.stored.4": (
        "From bank and merchant emails, forwarded or read from Gmail, only the fields we take "
        "out of them: amounts, dates, merchant, order number, a short summary and the link to "
        "the order. We never store the body of an email."
    ),
    "privacy.stored.5": (
        "Forwarded PDFs are read and deleted. A quarantined email is kept encrypted for 30 "
        "days; a statement waiting for your password or your approval, up to 90 days."
    ),
    "privacy.stored.6": "Your bank's PDF password, only if you choose to store it.",
    "privacy.gmail.title": "Gmail (Google user data)",
    "privacy.gmail.1": (
        "Connecting Gmail is optional. If you connect it, Michelito asks only for read-only "
        "access (gmail.readonly): it cannot send, delete or change anything in your mailbox."
    ),
    "privacy.gmail.2": (
        "We ask Gmail only for the messages of the merchant senders the app knows (today, "
        "Amazon's order and shipment confirmations) from the last 12 months. From each one we "
        "keep only the amount, the date, the merchant, the order number, a short summary and "
        "the link to the order; never the body or the attachments."
    ),
    "privacy.gmail.3": (
        "The access Google gives us (a refresh token) is stored encrypted inside your database. "
        "Disconnecting Gmail in Settings revokes it at Google and deletes it; you can also "
        "remove the access from your Google account. Receipts already read stay in your "
        "account, like the rest of your data."
    ),
    "privacy.gmail.4": (
        "We use Google user data only to show you your own receipts next to your transactions. "
        "We do not sell it, we do not use it for advertising or to train artificial "
        "intelligence or machine-learning models, and we do not transfer it to anyone, except "
        "as needed to provide this feature, for security, or when the law requires it. No "
        "person reads it, except with your consent, for security, or when the law requires it."
    ),
    "privacy.gmail.5": (
        "Michelito's use and transfer of information received from Google APIs adheres to the "
        "{policy}, including the Limited Use requirements."
    ),
    "privacy.gmail.policy": "Google API Services User Data Policy",
    "privacy.protect.title": "How we protect it",
    "privacy.protect.1": (
        "Each account has its own database, encrypted with AES-256 (SQLCipher) under its own "
        "key. That key is stored encrypted under a master key of the server. Everything travels "
        "over HTTPS."
    ),
    "privacy.protect.2": (
        "That is why the server can read your data: it needs to, to receive your forwarded "
        "emails while you are away and so that losing a device does not lose your data. There "
        "is no mode in which not even we can read it."
    ),
    "privacy.protect.3": (
        "Backups, encrypted, are kept in Cloudflare R2 and deleted after 30 days."
    ),
    "privacy.others.title": "Who else handles data",
    "privacy.others.1": "The provider of the virtual server the app runs on.",
    "privacy.others.2": (
        "Cloudflare: it receives the emails you forward (Email Routing) and keeps the encrypted "
        "backups (R2)."
    ),
    "privacy.others.3": "Resend: it sends the sign-in codes (it gets your email and the code).",
    "privacy.others.4": "Google: only if you connect Gmail.",
    "privacy.others.5": (
        "There is no analytics, no advertising and no tracking cookies. The only cookies are "
        "the ones the app needs to work: your session's, one that recognizes a browser you "
        "signed in from before, and one used when sharing PDFs from the phone."
    ),
    "privacy.others.6": "No artificial intelligence service receives your data.",
    "privacy.keep.title": "How long, and deleting",
    "privacy.keep.1": "We keep your data while your account exists.",
    "privacy.keep.2": (
        "When your account is deleted, its key is destroyed at once and its data becomes "
        "unreadable. In the backups it becomes unreadable and is gone within 30 days at most. "
        "To delete your account, write to us."
    ),
    "privacy.keep.3": (
        "Disconnecting Gmail revokes Michelito's access to your mailbox. Deleting your account "
        "revokes it too."
    ),
    "privacy.contact.title": "Contact",
    "privacy.contact.email": "For any question about your data, write to {email}.",
    "privacy.contact.none": (
        "For any question about your data, write to us at the app's support address."
    ),
    "privacy.changes.title": "Changes",
    "privacy.changes.1": "If this policy changes, we update this page and the date above.",
}

CSS = """body{margin:0;background:#fbfaf7;color:#1f2328;font:16px/1.6 system-ui,-apple-system,\
"Segoe UI",sans-serif}main{max-width:42rem;margin:0 auto;padding:1.5rem 1rem 3rem}\
h1{font-size:1.75rem;line-height:1.25;margin:1rem 0 .25rem}h2{font-size:1.15rem;margin:1.75rem 0 \
.25rem}article+article{margin-top:3rem;border-top:1px solid #ddd8cc;padding-top:1rem}\
a{color:#0b5f4a}a:focus-visible{outline:2px solid #0b5f4a;outline-offset:2px}\
.meta{color:#5b606a;font-size:.9rem}ul{padding-left:1.25rem}li{margin:.25rem 0}\
@media (prefers-color-scheme:dark){body{background:#16181c;color:#e6e4df}a{color:#7fd1b9}\
a:focus-visible{outline-color:#7fd1b9}.meta{color:#a3a7ad}article+article{border-color:#33363c}}
"""


def contact(environ: Mapping[str, str] | None = None) -> str | None:
    """The address to write to (`MICHELITO_OPS_EMAIL`), when it is one."""
    found = (environ if environ is not None else os.environ).get(CONTACT_ENV, "").strip()
    return found if len(found) <= 254 and _ADDRESS.fullmatch(found) else None  # noqa: PLR2004


def _text(messages: Mapping[str, str], key: str, **safe: str) -> str:
    """The message escaped (it is text, never an attribute), with already-safe HTML for its
    placeholders."""
    return html.escape(messages[key], quote=False).format(**safe)


def _article(messages: Mapping[str, str], lang: str, email: str | None) -> str:
    """One language's text (its `id` is the language, for the link between them)."""

    def text(key: str, **safe: str) -> str:
        return _text(messages, key, **safe)

    link = f'<a href="{html.escape(POLICY_URL)}" rel="noopener">{text("privacy.gmail.policy")}</a>'
    parts = [
        f'<article id="{lang}" lang="{lang}">',
        f"<h1>{text('privacy.title')}</h1>",
        f'<p class="meta">{text("privacy.updated", date=UPDATED)}</p>',
    ]
    for section, count, listed in SECTIONS:
        parts.append(f"<h2>{text(f'privacy.{section}.title')}</h2>")
        items = [text(f"privacy.{section}.{n}", policy=link) for n in range(1, count + 1)]
        if listed:
            parts.append("<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>")
        else:
            parts.extend(f"<p>{item}</p>" for item in items)
    parts.append(f"<h2>{text('privacy.contact.title')}</h2>")
    if email is None:
        parts.append(f"<p>{text('privacy.contact.none')}</p>")
    else:
        address = html.escape(email)
        mail = f'<a href="mailto:{address}">{address}</a>'
        parts.append(f"<p>{text('privacy.contact.email', email=mail)}</p>")
    parts.append(f"<h2>{text('privacy.changes.title')}</h2>")
    parts.append(f"<p>{text('privacy.changes.1')}</p>")
    parts.append("</article>")
    return "".join(parts)


def page(email: str | None) -> str:
    """The whole page: Spanish first, then English."""
    spanish = i18n.MESSAGES
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_text(spanish, 'privacy.title')}</title>"
        f'<link rel="stylesheet" href="{CSS_PATH}"></head><body><main>'
        f'<p class="meta"><a href="/">{_text(spanish, "privacy.back")}</a> · '
        f'<a href="#en" lang="en">{_text(spanish, "privacy.other_language")}</a></p>'
        f"{_article(spanish, 'es', email)}"
        f"{_article(ENGLISH, 'en', email)}"
        "</main></body></html>"
    )


def register(app: FastAPI, email: str | None) -> None:
    """The page and its stylesheet; both public, neither opens anything."""
    body = page(email)

    @app.get(PATH, include_in_schema=False)
    def get_privacy() -> HTMLResponse:
        return HTMLResponse(body)

    @app.get(CSS_PATH, include_in_schema=False)
    def get_privacy_css() -> Response:
        return Response(CSS, media_type="text/css")
