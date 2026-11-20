"""Problem emails to the account's own person (not only the owner), for email forwarding.

Only on problems: a message in quarantine, a statement whose password is missing or wrong, an
unsupported bank, a statement that does not square or cannot be read, and a statement that did
not arrive when it usually does. Each email is **data-free**: the kind of problem and a link to
the app; never an amount, a name, a sender, a file name or a figure.

Each (kind, key) is notified once (`inbox_store.take_notice`: the key is the UTC day for most
kinds, the account and expected date for a late statement), one call sends at most one email
per kind, and notices never use the last `RESERVE` emails of the day's cap, so sign-in codes
always have room. They go through the
same `Dispatcher` as sign-in codes (in the background).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime

from michelito import db
from michelito.hosted import inbox, inbox_store
from michelito.hosted.auth import SignIn
from michelito.hosted.mailer import Dispatcher, Email
from michelito.i18n import t

log = logging.getLogger(__name__)

RESERVE = 20
KINDS = (
    "quarantine",
    "password_missing",
    "password_wrong",
    "unsupported",
    "invalid",
    "unreadable",
    "overdue",
    "full",
    "new_account",
)


@dataclass(frozen=True)
class Notices:
    dispatcher: Dispatcher
    url: str  # the app's public address

    def email(self, to: str, kind: str) -> Email:
        if kind not in KINDS:
            raise ValueError(f"unknown notice: {kind}")
        return Email(
            to,
            t("forwarding.notice.subject"),
            t(
                "forwarding.notice.body",
                problem=t(f"forwarding.notice.{kind}"),
                link=f"{self.url.rstrip('/')}/settings",
            ),
        )

    def _room(self) -> bool:
        day = datetime.now(UTC).date().isoformat()
        limit = max(0, self.dispatcher.daily_limit - RESERVE)
        return self.dispatcher.ledger.mail_available(day, limit)

    def send(self, conn: sqlite3.Connection, to: str, found: Iterable[tuple[str, str]]) -> int:
        """At most one email per kind for the (kind, key) pairs not notified before; returns how
        many went out. Commits its own bookkeeping (call it outside any open transaction)."""
        by_kind: dict[str, list[str]] = {}
        for kind, key in dict.fromkeys(found):
            by_kind.setdefault(kind, []).append(key)
        sent = 0
        for kind, keys in by_kind.items():
            if not self._room():
                break
            inbox_store.ensure(conn)
            with conn:
                fresh = [key for key in keys if inbox_store.take_notice(conn, kind, key)]
            if fresh and self.dispatcher.submit(self.email(to, kind)):
                sent += 1
        return sent


def send_overdue(service: SignIn, notices: Notices, today: date) -> tuple[int, int]:
    """The daily check (`michelito forwarding-check`): for every account with a forwarding
    address, email it once per late statement (`inbox.overdue`). Returns (emails sent,
    accounts that could not be opened); one account that fails never stops the others, and
    only the error's class name is logged."""
    sent = failed = 0
    for account in service.store.forwarding_accounts():
        try:
            workspace = service.workspace_of(account)
            with closing(db.connect(workspace.database, workspace.key)) as conn:
                late = inbox.overdue(conn, today)
                found = [("overdue", f"{o.account}:{o.expected.isoformat()}") for o in late]
                sent += notices.send(conn, account.email, found)
        except Exception as exc:  # noqa: BLE001 - see above
            log.error("an account could not be checked for late statements: %s", type(exc).__name__)
            failed += 1
    return sent, failed
