"""Routing a forwarded email inside the account's encrypted database (hosted mode).

`receive` reads the message's structure (`inbound_mail`) and sends it one of five ways:

- **Gmail's forwarding confirmation** (from `forwarding-noreply@google.com`, authenticated for
  google.com): its code, its link (rebuilt from an allowlisted pattern) and the Gmail address
  that asked are kept to show them. Nothing is confirmed here: the person does it in Gmail, so
  nobody can point someone else's forwarding at this address unnoticed.
- **A known bank sender** (the senders of `config.DEFAULT_SOURCES`), authenticated for that
  sender's domain: a bank alert goes through the live-sync pipeline (`live_store.record`, then
  `live_match.reconcile`) as provisional transactions; each PDF attachment is queued, sealed
  (`inbox_store.inbox_waiting`), to be read by the same in-memory pipeline as an upload
  (`uploads.examine` in the isolated worker, then `uploads.store`: only statements that
  square persist). A locked PDF is read with the bank's stored password if the person chose to
  store one; otherwise (or if it is wrong) it waits, sealed, until the person types it.
  Whatever happens, the PDF is deleted once read.
- **A merchant's receipt** (the senders of `michelito.receipts`), authenticated for that
  sender's domain: read in memory, only its fields are stored (`receipt_store.record`) and it
  is matched to the transactions (`receipt_match`). It adds detail to a transaction and never
  creates one, so it does not wait for the person; its attachments are ignored.
- **Someone else's genuine mail** looks exactly like the person's own, so what would be a
  *first* for this account waits for the person: an approved purchase alert on a card no
  statement of theirs has shown goes to quarantine (`unknown_card`), and a statement that
  squares but is of an account (or card) they do not have yet is held (`new_account`) until
  they approve it. Their first statement of an account comes through the upload gate.
- **Anything else** (an unknown sender, or a bank's address that did not authenticate):
  **quarantine**: only its sender's domain, date and attachment count are readable; nothing in
  it is opened until the person approves it (it is routed as if the bank had authenticated it,
  never to Gmail's confirmation panel, and what enters is recorded as approved, marked in the
  transactions and can be taken back: `take_back`) or discards it.

**Idempotency** is by trust class (`key`): an authenticated message by its Message-ID, a
quarantined one by a hash of its bytes, an approved one by its Message-ID apart. A forged
message that reuses a genuine one's Message-ID can therefore never make the genuine one a
"duplicate"; discarding a quarantined message forgets its key.

**Which authentication counts** (`passes`). Forwarding breaks SPF (the forwarder's servers are
not the bank's) but keeps DKIM (the bank's signature covers headers and body, which Gmail's
forwarding does not change), and DMARC passes through DKIM alignment. Two verdicts exist:

1. the **Worker's**: the `ARC-Authentication-Results` that Cloudflare's own receiving server
   wrote when the message arrived, which the Worker passes on in the signed request (`auth`)
   only once it checked that Cloudflare's ARC set is the newest one and its seal verifies
   (`deploy/email-worker/worker.js`), and which is read here only if its authserv-id is one we
   trust (`TRUSTED_AUTHSERV`);
2. the **forwarded message's own** topmost header, when it is Gmail's (`mx.google.com`).

The Worker's verdict is **required** and is the one that counts: anyone who knows the address
can write any header into the message itself (including one that claims to be Gmail's), but
not into what Cloudflare sealed, and the HMAC proves the request came from the Worker. The
inner header may only **veto**: when Gmail's verdict is present and does not authenticate the
bank, the message goes to quarantine. Both need DKIM and DMARC to pass for the sender's domain
(`authres.authenticated`), and the From address must be the bank's.

Problems are returned as `notices` (kind, key) for the caller to email once the transaction
committed; nothing here sends email or logs anything but data-free fingerprints.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from statistics import median

from michelito import alerts, config, db, receipts
from michelito.alerts import authres
from michelito.alerts.common import AlertEmail, AlertParseError
from michelito.analysis import (
    changelog,
    live_match,
    live_store,
    receipt_match,
    receipt_store,
    spending,
)
from michelito.db import PRINTOUT_PARSERS
from michelito.hosted import inbound_mail, inbox_store, pdf_worker, uploads
from michelito.hosted.inbox_store import Sealer
from michelito.i18n import t

log = logging.getLogger(__name__)

SUPPORTED_BANKS = ("popular", "bhd", "banreservas")
OTHER_BANK = "other"
TRUSTED_AUTHSERV = ("mx.cloudflare.net",)
GMAIL_RECEIVER = "mx.google.com"
SOURCE = "forwarding"
FORWARDED_NAME = "forwarded-statement.pdf"  # the attachment's own name is never kept
OVERDUE_TOLERANCE = 5  # days after the usual cut-off before a statement counts as late
_FROM = re.compile(r"from:(\S+@\S+)")

# Outcomes of a statement that ends with a problem -> the notice it sends.
PROBLEM_NOTICES = {
    uploads.INVALID: "invalid",
    uploads.UNSUPPORTED: "unsupported",
    uploads.UNREADABLE: "unreadable",
    uploads.TOO_COMPLEX: "unreadable",
}


def bank_senders(sources: Iterable[config.Source] = config.DEFAULT_SOURCES) -> dict[str, str]:
    """Sender address -> bank, from the statement and alert sources whose bank is read."""
    found: dict[str, str] = {}
    for source in sources:
        if not (source.interpret or source.alerts):
            continue
        bank = source.name.split("_")[0]
        if bank not in SUPPORTED_BANKS:
            continue
        for match in _FROM.finditer(source.query):
            found[match.group(1).lower()] = bank
    return found


SENDERS = bank_senders()


@dataclass(frozen=True)
class Proof:
    worker: authres.Verdict
    inner: authres.Verdict | None  # Gmail's own verdict, when the message carries it


def proof(auth: str, email: AlertEmail | None, trusted: tuple[str, ...]) -> Proof:
    worker = authres.trusted_verdict([auth] if auth else [], trusted)
    headers = () if email is None else email.auth_results
    inner = None
    if headers and authres.authserv_id(headers[0]) == GMAIL_RECEIVER:
        inner = authres.trusted_verdict(headers, (GMAIL_RECEIVER,))
    return Proof(worker, inner)


def passes(found: Proof, sender_domain: str, wanted: str) -> bool:
    """The From domain is `wanted` (or a subdomain), the Worker's verdict authenticates it and
    the message's own Gmail verdict, if present, does not contradict it."""
    if not authres.covers(sender_domain, wanted):
        return False
    if not authres.authenticated(found.worker, wanted):
        return False
    return found.inner is None or authres.authenticated(found.inner, wanted)


def vouched(domain: str) -> authres.Verdict:
    """The verdict of a quarantined message the person approved: they vouch for its sender."""
    return authres.Verdict(dkim=(domain,), dmarc_from=(domain,))


@dataclass
class Result:
    route: str  # duplicate, unreadable, confirmation, bank, receipt, quarantine
    queued: int = 0  # PDFs waiting to be read
    notices: list[tuple[str, str]] = field(default_factory=list)


def _day() -> str:
    return datetime.now(UTC).date().isoformat()


# Idempotency keys by trust class: an authenticated message by its Message-ID, a quarantined
# one by its bytes, an approved one by its Message-ID apart. So a forged message that reuses a
# real one's Message-ID never makes the real one a "duplicate".
TRUSTED, QUARANTINED, APPROVED = "trusted", "quarantine", "approved"


def key(kind: str, digest: str) -> str:
    return f"{kind}:{digest}"


def receive(
    conn: sqlite3.Connection,
    sealer: Sealer,
    raw: bytes,
    auth: str,
    trusted: tuple[str, ...] = TRUSTED_AUTHSERV,
) -> Result:
    """Record a forwarded message (see the module); PDFs are only queued (`drain` reads them)."""
    inbox_store.ensure(conn)
    try:
        inbound = inbound_mail.parse(raw)
    except inbound_mail.Unreadable:
        with conn:
            inbox_store.add_event(conn, "message", "unreadable")
        return Result("unreadable")
    found = proof(auth, inbound.email, trusted)
    bank = SENDERS.get(inbound.sender)
    gmail = inbound.sender == inbound_mail.GMAIL_SENDER
    authentic = key(TRUSTED, inbound.message_key)
    if gmail and passes(found, inbound.sender_domain, inbound_mail.GMAIL_DOMAIN):
        if inbox_store.seen(conn, authentic):
            return Result("duplicate")
        return _confirmation(conn, inbound, authentic)
    if bank is not None and passes(found, inbound.sender_domain, inbound.sender_domain):
        if inbox_store.seen(conn, authentic):
            return Result("duplicate")
        return _bank(conn, sealer, inbound, raw, bank, found.worker, authentic, approved=False)
    merchant = inbound.sender in receipts.SENDERS
    if merchant and passes(found, inbound.sender_domain, inbound.sender_domain):
        if inbox_store.seen(conn, authentic):
            return Result("duplicate")
        return _receipt(conn, inbound, found.worker, authentic)
    known = bank is not None or gmail
    reason = "unauthenticated" if known or merchant else "unknown_sender"
    return _quarantine(conn, sealer, inbound, raw, reason, claims_bank=known)


_RECEIPT_OUTCOMES = {"stored": "receipt_read", "known": "receipt_known", "failed": "receipt_failed"}


def _receipt(
    conn: sqlite3.Connection, inbound: inbound_mail.Inbound, verdict: authres.Verdict, seen: str
) -> Result:
    """A merchant's receipt (`michelito.receipts`), authenticated for its sender: read in
    memory, only its fields are stored (attachments are ignored) and it is matched to the
    transactions. It never creates one, so nothing here needs the person's approval."""
    email = inbound.email
    with conn:
        if not inbox_store.mark_seen(conn, seen, "receipt"):
            return Result("duplicate")
        # The address that was let in must be the one the reader sees (a message can carry
        # two From headers).
        if email is None or email.sender_address != inbound.sender:
            inbox_store.add_event(conn, "receipt", _RECEIPT_OUTCOMES["failed"])
            return Result("receipt")
        found = dataclasses.replace(
            email,
            message_id=_receipt_id(email.message_id, inbound.message_key),
            verified=verdict,
            trusted_authserv=(),
        )
        try:
            outcome = receipt_store.record(conn, found, SOURCE, _stamp())
        except Exception as exc:  # noqa: BLE001 - one bad message must not fail the request
            log.warning("reading a merchant receipt failed (%s)", type(exc).__name__)
            outcome = "failed"
        inbox_store.add_event(conn, "receipt", _RECEIPT_OUTCOMES[outcome])
    if outcome == "stored":
        _match_receipts(conn)
    return Result("receipt")


_MESSAGE_ID = re.compile(r"[\x21-\x7e]{1,200}")


def _receipt_id(message_id: str, key: str) -> str:
    """What identifies the email: its `Message-ID` if it is a plain token that fits (it becomes
    a search in the person's Gmail), else the hash of the message."""
    plain = _MESSAGE_ID.fullmatch(message_id) is not None and '"' not in message_id
    return message_id if plain else key


def _confirmation(conn: sqlite3.Connection, inbound: inbound_mail.Inbound, seen: str) -> Result:
    found = inbound_mail.gmail_confirmation(inbound)
    with conn:
        if not inbox_store.mark_seen(conn, seen, "confirmation"):
            return Result("duplicate")
        inbox_store.add_confirmation(
            conn, found.code, found.link, inbound.received_at, found.requester
        )
        inbox_store.add_event(conn, "confirmation", "received")
    return Result("confirmation")


def _quarantine(
    conn: sqlite3.Connection,
    sealer: Sealer,
    inbound: inbound_mail.Inbound,
    raw: bytes,
    reason: str,
    claims_bank: bool,
) -> Result:
    held = key(QUARANTINED, inbound.raw_key)
    with conn:
        if not inbox_store.mark_seen(conn, held, "quarantine"):
            return Result("duplicate")
        kept = inbox_store.add_quarantine(
            conn,
            sealer,
            inbound.sender_domain,
            inbound.received_at,
            inbound.attachments,
            reason,
            raw,
            claims_bank=claims_bank,
            seen_key=held,
        )
        if not kept:  # nothing kept: the same message may come again
            conn.execute("DELETE FROM inbox_messages WHERE message_key = ?", (held,))
        inbox_store.add_event(conn, "quarantine", "held" if kept else "full")
    notice = ("quarantine", _day()) if kept else ("full", _day())
    return Result("quarantine", notices=[notice])


def _known_card(conn: sqlite3.Connection, last4: str) -> bool:
    return conn.execute("SELECT 1 FROM cards WHERE last4 = ?", (last4,)).fetchone() is not None


def _alert_of(
    email: AlertEmail | None, inbound: inbound_mail.Inbound, verdict: authres.Verdict
) -> AlertEmail | None:
    if email is None or inbound.pdfs:
        return None
    found = dataclasses.replace(
        email,
        message_id=(email.message_id or inbound.message_key)[:200],
        verified=verdict,
        trusted_authserv=(),
    )
    return found if alerts.detect(found) is not None else None


def _unknown_card(conn: sqlite3.Connection, alert: AlertEmail) -> bool:
    """An approved purchase on a card this account has never had in a statement: a genuine
    bank alert of someone else's card forwarded here would look exactly like this."""
    parser = alerts.detect(alert)
    try:
        parsed = None if parser is None else parser.parse(alert)
    except AlertParseError:
        return False  # recorded as a failure (data-free), never a transaction
    return parsed is not None and parsed.kind == "approved" and not _known_card(conn, parsed.last4)


def _bank(
    conn: sqlite3.Connection,
    sealer: Sealer,
    inbound: inbound_mail.Inbound,
    raw: bytes,
    bank: str,
    verdict: authres.Verdict,
    seen: str,
    approved: bool,
) -> Result:
    alert = _alert_of(inbound.email, inbound, verdict)
    if alert is not None and not approved and _unknown_card(conn, alert):
        return _quarantine(conn, sealer, inbound, raw, "unknown_card", claims_bank=True)
    result = Result("bank")
    with conn:
        if not inbox_store.mark_seen(conn, seen, "bank"):
            return Result("duplicate")
        if alert is not None:
            outcome = live_store.record(conn, alert, SOURCE, _stamp())
            inbox_store.add_event(conn, "alert", _ALERT_OUTCOMES[outcome], bank)
            if approved and outcome == "stored":
                inbox_store.add_approval(conn, "alert", alert.message_id, inbound.sender_domain)
        for pdf in inbound.pdfs:
            if inbox_store.add_waiting(
                conn,
                sealer,
                bank,
                inbound.received_at,
                pdf,
                approved=approved,
                sender_domain=inbound.sender_domain,
            ):
                result.queued += 1
            else:
                inbox_store.add_event(conn, "statement", "full", bank)
                result.notices.append(("full", _day()))
        if alert is None and not inbound.pdfs:
            inbox_store.add_event(conn, "message", "ignored", bank)
    if alert is not None:
        with conn:
            live_match.reconcile(conn, _stamp())
        _match_receipts(conn)  # a new provisional may be a receipt's
    return result


def _match_receipts(conn: sqlite3.Connection) -> None:
    """Match the stored receipts in a transaction of their own: whatever goes wrong with them
    must never undo what the bank's mail brought nor fail the request (the Worker would send
    the same message again). The next message does the same work."""
    try:
        with conn:
            receipt_match.reconcile_stored(conn, _stamp())
    except Exception as exc:  # noqa: BLE001 - receipts are an extra
        log.warning("matching merchant receipts failed (%s)", type(exc).__name__)


_ALERT_OUTCOMES = {"stored": "provisional", "known": "duplicate", "failed": "failed"}


def _stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# Reading the waiting PDFs.


@dataclass
class Unlocked:
    opened: int = 0
    left: int = 0
    held: int = 0  # read, but of an account not known yet: waiting for approval
    notices: list[tuple[str, str]] = field(default_factory=list)


def drain(
    conn: sqlite3.Connection, sealer: Sealer, limits: pdf_worker.Limits | None = None
) -> Unlocked:
    """Read every queued PDF: without a password, then with the bank's stored one. What opens
    is read and deleted (or held, for an account not known yet); what stays locked waits for
    the person's password."""
    inbox_store.ensure(conn)
    done = Unlocked()
    for item in inbox_store.waiting(conn, state="queued"):
        stored = _stored(conn, sealer, item.bank)
        candidates = ["", stored] if stored else [""]
        opened = _settle(conn, sealer, item, candidates, limits, done)
        if not opened:
            reason = "wrong" if stored else "missing"
            with conn:
                inbox_store.lock_waiting(conn, item.id, reason)
                inbox_store.add_event(conn, "statement", f"password_{reason}", item.bank)
            done.notices.append((f"password_{reason}", f"{item.bank}:{_day()}"))
            done.left += 1
    return done


def unlock(
    conn: sqlite3.Connection,
    sealer: Sealer,
    bank: str,
    password: str,
    limits: pdf_worker.Limits | None = None,
) -> Unlocked:
    """Try the password the person typed on every waiting PDF of that bank."""
    inbox_store.ensure(conn)
    done = Unlocked()
    for item in inbox_store.waiting(conn, state="password", bank=bank):
        if not _settle(conn, sealer, item, [password], limits, done):
            done.left += 1
    return done


def _stored(conn: sqlite3.Connection, sealer: Sealer, bank: str) -> str | None:
    try:
        return inbox_store.password(conn, sealer, bank)
    except inbox_store.SealError:
        log.error("a stored PDF password did not open; it is ignored")
        return None


def _new_account(conn: sqlite3.Connection, examined: uploads.Examined) -> bool:
    """Whether a statement that squared is of an account (or a card) this person has never
    had: the first one only enters by an upload or by their explicit approval."""
    for statement in examined.squared:
        known = conn.execute(
            "SELECT id FROM accounts WHERE key = ?", (db.account_key(statement),)
        ).fetchone()
        if known is None:
            return True
        if statement.kind == "credit_card":
            last4 = statement.identifier  # as `db` stores the card
            card = conn.execute(
                "SELECT 1 FROM cards WHERE account_id = ? AND last4 = ?", (known[0], last4)
            ).fetchone()
            if card is None:
                return True
    return False


def _settle(
    conn: sqlite3.Connection,
    sealer: Sealer,
    item: inbox_store.Waiting,
    candidates: list[str],
    limits: pdf_worker.Limits | None,
    done: Unlocked,
) -> bool:
    """Read one waiting PDF with the first password that opens it; False if none does (it
    stays). Opened, it is stored if it squares (or held, for a new account) and deleted."""
    try:
        pdf = sealer.open("waiting", item.uid, item.sealed)
        pages = inbox_store.held_pages(sealer, item)
    except inbox_store.SealError:
        log.error("a waiting statement did not open; it is dropped")
        with conn:
            inbox_store.drop_waiting(conn, item.id)
        return True
    examined = None
    if pages is not None:  # held and now approved: read before, no password needed again
        examined = uploads.examine_pages(uploads.pages_of(pages))
    else:
        for password in candidates:
            examined = uploads.examine(pdf, password, limits)
            if examined.state != uploads.LOCKED:
                break
    if examined is None or examined.state == uploads.LOCKED:
        return False
    state = examined.state
    if state == uploads.SQUARED and not item.approved and _new_account(conn, examined):
        with conn:
            inbox_store.hold_waiting(conn, sealer, item, uploads.pages_json(examined.pages))
            inbox_store.add_event(conn, "statement", "new_account", examined.bank or item.bank)
        done.notices.append(("new_account", _day()))
        done.held += 1
        done.opened += 1  # it did open: it now waits for approval, not for a password
        return True
    if state == uploads.SQUARED:
        try:
            state = uploads.store(conn, FORWARDED_NAME, pdf, examined, datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 - only the class name is logged
            log.error("a forwarded statement could not be stored: %s", type(exc).__name__)
            state = uploads.UNREADABLE
        if state == uploads.NO_LOAN:  # by mail there is no screen to say which loan is missing
            state = uploads.UNSUPPORTED
    else:
        uploads.log_failure(examined.fingerprint)
    with conn:
        inbox_store.drop_waiting(conn, item.id)
        if state in (uploads.SQUARED, uploads.DUPLICATE):
            if item.approved and state == uploads.SQUARED:
                digest = hashlib.sha256(pdf).hexdigest()
                inbox_store.add_approval(conn, "statement", digest, item.sender_domain)
            for read in examined.reads:
                inbox_store.add_event(
                    conn, "statement", state, read.bank, read.month, read.identifier, read.kind
                )
        else:
            inbox_store.add_event(conn, "statement", state, examined.bank or item.bank)
    if state in PROBLEM_NOTICES:
        done.notices.append((PROBLEM_NOTICES[state], _day()))
    done.opened += 1
    return True


# The person's decisions.


def approve(conn: sqlite3.Connection, sealer: Sealer, item_id: int) -> Result | None:
    """Route a quarantined message as if its sender had authenticated (the person vouches for
    it); None if there is no such item. Its PDFs are queued (the caller drains them) and what
    enters is recorded as approved. Never routed to Gmail's confirmation panel: an approved
    confirmation is just dropped (it was not verified as Gmail's)."""
    inbox_store.ensure(conn)
    found = inbox_store.quarantined(conn, item_id)
    if not found:
        return None
    item = found[0]
    try:
        raw = sealer.open("quarantine", item.uid, item.sealed)
        inbound = inbound_mail.parse(raw)
    except (inbox_store.SealError, inbound_mail.Unreadable):
        with conn:
            inbox_store.drop_quarantine(conn, item.id)
        return Result("unreadable")
    if inbound.sender == inbound_mail.GMAIL_SENDER:
        result = Result("ignored")
    else:
        bank = SENDERS.get(inbound.sender, OTHER_BANK)
        seen = key(APPROVED, inbound.message_key)
        verdict = vouched(inbound.sender_domain)
        result = _bank(conn, sealer, inbound, raw, bank, verdict, seen, approved=True)
    # Only now (a crash before this leaves it in quarantine; approving again finds it handled).
    with conn:
        inbox_store.drop_quarantine(conn, item.id, forget=False)
    return result


def discard(conn: sqlite3.Connection, item_id: int) -> bool:
    """Delete a quarantined message, and its key: the same message may be received again."""
    inbox_store.ensure(conn)
    with conn:
        return inbox_store.drop_quarantine(conn, item_id)


def approve_held(conn: sqlite3.Connection, item_id: int) -> bool:
    """A statement of a new account, approved by the person: read again (`drain`) and stored."""
    inbox_store.ensure(conn)
    with conn:
        return inbox_store.approve_waiting(conn, item_id)


def discard_waiting(conn: sqlite3.Connection, item_id: int) -> bool:
    inbox_store.ensure(conn)
    with conn:
        return inbox_store.drop_waiting(conn, item_id)


class Linked(Exception):
    """What entered by approval is in use (a link, a shared group, a note): take it out first."""


def take_back(conn: sqlite3.Connection, approval_id: int, now: str) -> bool:
    """Undo an approval: an alert's provisional is discarded (a logged decision, undoable from
    the log); a statement's rows are removed, only if none of its transactions is linked,
    noted, or confirmed a provisional. False if there is no such approval."""
    inbox_store.ensure(conn)
    found = inbox_store.approvals(conn, approval_id)
    if not found:
        return False
    approval = found[0]
    if approval.kind == "alert":
        _discard_alert(conn, approval, now)
    else:
        _remove_statement(conn, approval)
    return True


def _discard_alert(conn: sqlite3.Connection, approval: inbox_store.Approval, now: str) -> None:
    row = conn.execute(
        "SELECT id, merchant FROM alerts WHERE message_id = ?", (approval.ref,)
    ).fetchone()
    with conn:
        if row is not None:
            mark = live_store.fingerprint(int(row[0]))
            if live_store.is_linked(conn, mark):
                raise Linked
            with changelog.track(
                conn,
                "provisional",
                "transaction",
                mark,
                str(row[1]),
                before=t("web.provisional.pending"),
                after=t("web.provisional.discarded"),
                merchant=str(row[1]),
                fingerprints=[mark],
            ):
                live_store.decide(conn, mark, "discard", now)
        inbox_store.drop_approval(conn, approval.id)


def _remove_statement(conn: sqlite3.Connection, approval: inbox_store.Approval) -> None:
    document = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (approval.ref,)).fetchone()
    if document is None:
        with conn:
            inbox_store.drop_approval(conn, approval.id)
        return
    ids = {
        int(r[0])
        for r in conn.execute("SELECT id FROM statements WHERE document_id = ?", (document[0],))
    }
    prints = spending.statement_fingerprints(conn, ids)
    noted = any(
        conn.execute("SELECT 1 FROM transaction_notes WHERE fingerprint = ?", (p,)).fetchone()
        for p in prints
    )
    # A row that confirmed a provisional took the alert's identity (`alert-<id>`).
    confirmed = any(live_store.is_provisional(p) for p in prints)
    if noted or confirmed or any(live_store.is_linked(conn, p) for p in prints):
        raise Linked
    with conn:
        rows = conn.execute(
            "SELECT id, account_id FROM statements WHERE document_id = ?", (document[0],)
        ).fetchall()
        for statement_id, _ in rows:
            conn.execute("DELETE FROM transactions WHERE statement_id = ?", (statement_id,))
        conn.execute("DELETE FROM statements WHERE document_id = ?", (document[0],))
        conn.execute("DELETE FROM document_parts WHERE document_id = ?", (document[0],))
        conn.execute("DELETE FROM documents WHERE id = ?", (document[0],))
        # The account (and card) it brought, if nothing else uses them now.
        for account_id in {account for _, account in rows}:
            conn.execute(
                "DELETE FROM cards WHERE account_id = ? AND id NOT IN "
                "(SELECT card_id FROM statements WHERE card_id IS NOT NULL)",
                (account_id,),
            )
            conn.execute(
                "DELETE FROM accounts WHERE id = ? AND id NOT IN "
                "(SELECT account_id FROM statements) AND id NOT IN (SELECT account_id FROM cards)",
                (account_id,),
            )
        inbox_store.drop_approval(conn, approval.id)
        inbox_store.add_event(conn, "statement", "taken_back")


# Late statements and the status card.


@dataclass(frozen=True)
class Overdue:
    account: str  # accounts.key (never shown: identifies the notice)
    bank: str
    kind: str
    identifier: str  # last four characters
    expected: date  # the usual cut-off after the last statement


def overdue(conn: sqlite3.Connection, today: date) -> list[Overdue]:
    """Accounts whose next statement is later than usual: the newest closing plus the median of
    the last gaps between closings (a month when there is only one), plus `OVERDUE_TOLERANCE`
    days."""
    marks = ", ".join("?" for _ in PRINTOUT_PARSERS)
    rows = conn.execute(
        "SELECT a.key, a.institution, a.kind, coalesce(c.last4, a.key) AS ident, s.period_end "
        "FROM statements s JOIN accounts a ON a.id = s.account_id "
        "LEFT JOIN cards c ON c.id = s.card_id "
        f"WHERE s.parser NOT IN ({marks}) ORDER BY a.key, s.period_end",
        PRINTOUT_PARSERS,
    ).fetchall()
    ends: dict[str, list[date]] = defaultdict(list)
    about: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        ends[row[0]].append(date.fromisoformat(row[4]))
        about[row[0]] = (row[1], row[2], "".join(c for c in str(row[3]) if c.isalnum())[-4:])
    found = []
    for key, closings in ends.items():
        unique = sorted(set(closings))
        gaps = [(b - a).days for a, b in zip(unique, unique[1:], strict=False)][-6:]
        usual = int(median(gaps)) if gaps else 31
        expected = unique[-1] + timedelta(days=max(usual, 20))
        if today > expected + timedelta(days=OVERDUE_TOLERANCE):
            bank, kind, ident = about[key]
            found.append(Overdue(key, bank, kind, ident, expected))
    return found
