"""Live sync reconciliation: alerts against cards and statements (see `live_store`).

`reconcile` runs after alerts are stored, after a statement is stored (in a transaction of its
own, once the statement is committed) and after an undo of a provisional's log entry. It is
idempotent: if it fails, the next run does the same work. In order:

1. A held status word now in the parser's table (`STATUSES` was extended) gets its kind.
2. An approved alert on an unknown card is resolved through `cards` (by its last four digits and
   the parser's institution); if no account or more than one has that card, it stays held
   (`unknown_card`), never guessed. One dated before the account's first statement is history
   (`stale`): the statements already cover (or never will) that time.
3. A reversal alert voids the provisional it cancels: same card, currency and exact amount, dated
   from one day before the purchase up to VOID_DAYS after; ties by merchant similarity, then
   the closest date. `voided_by` marks the reversal as used (undoing the void does not redo it).
   A visible provisional gets a logged, undoable `'void'` decision; one that is in a link (a
   shared group, an exchange, an investment...) is not voided: it becomes a To review item
   instead (`live_store.reversals`), so no link is left pointing at nothing. A held alert is
   simply `'voided'`. A decline alert never voids: it is a separate failed attempt.
4. Confirmation: each provisional is looked for among the statement rows of its account (card
   debits not yet claimed by another alert), same currency and exact cents, dated from
   `DAYS_BEFORE` before to `DAYS_AFTER` after the alert. Pairs are taken best first: merchant
   similarity, then the closest date, then the same plastic, then the oldest alert. On a match
   the alert stores the row's content fingerprint. The row takes the provisional's fingerprint
   (`keeps_identity`: its category, notes, links, marks and log stay) only if the provisional
   was already visible and the row belongs to a statement stored in this same run
   (`new_statements`). A row stored earlier (the alert arrived late, or an undone Discard made a
   provisional visible again) keeps its own fingerprint: its own corrections stay with it. A
   discarded provisional is not looked for; a voided one is, and if the statement has the charge
   the void is undone (logged), it is confirmed and it becomes a To review item.

Statement rows are never deleted or rewritten once stored, so a confirmed alert stays confirmed.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

from michelito import alerts
from michelito.alerts.common import status_kind
from michelito.analysis import categories, changelog, live_store, spending
from michelito.analysis.live_store import DAYS_AFTER, DAYS_BEFORE
from michelito.i18n import t

VOID_DAYS = 30
_SIMILARITY_DIGITS = 2  # rounded: tiny differences fall through to the date

_STATUS_OF_KIND = {
    "approved": "unknown_card",
    "declined": "declined",
    "reversed": "reversed",
    "unknown": "unknown_status",
}


@dataclass(frozen=True)
class Candidate:
    """A statement row an alert may be."""

    fingerprint: str
    account: str
    day: date
    amount_cents: int
    currency: str
    description: str
    last4: str | None
    order: int  # load order (a stable tie-break)
    statement_id: int = 0


@dataclass(frozen=True)
class Open:
    """A provisional waiting for its statement row."""

    id: int
    account: str
    day: date
    amount_cents: int
    currency: str
    merchant: str
    last4: str | None


def similarity(alert_merchant: str, description: str) -> float:
    """How alike the alert's merchant and the statement's description are (0 to 1), on the
    cleaned text: the statement usually adds the city or a reference."""
    left, right = categories.clean(alert_merchant), categories.clean(description)
    if not left or not right:
        return 0.0
    if right.startswith(left) or left.startswith(right):
        return 1.0
    return round(SequenceMatcher(None, left, right).ratio(), _SIMILARITY_DIGITS)


def match(opens: Iterable[Open], candidates: Iterable[Candidate]) -> dict[int, Candidate]:
    """Pure matching (step 4): alert id -> the statement row it is. Each row is used once."""
    by_key: defaultdict[tuple[str, str, int], list[Candidate]] = defaultdict(list)
    for row in candidates:
        by_key[(row.account, row.currency, row.amount_cents)].append(row)
    pairs = []
    for alert in opens:
        for row in by_key.get((alert.account, alert.currency, alert.amount_cents), ()):
            offset = (row.day - alert.day).days
            if -DAYS_BEFORE <= offset <= DAYS_AFTER:
                score = (
                    -similarity(alert.merchant, row.description),
                    abs(offset),
                    0 if alert.last4 is not None and alert.last4 == row.last4 else 1,
                    alert.day,
                    alert.id,
                    row.order,
                )
                pairs.append((score, alert.id, row))
    pairs.sort(key=lambda pair: pair[0])
    chosen: dict[int, Candidate] = {}
    used: set[str] = set()
    for _, alert_id, row in pairs:
        if alert_id in chosen or row.fingerprint in used:
            continue
        chosen[alert_id] = row
        used.add(row.fingerprint)
    return chosen


@dataclass(frozen=True)
class Reconciled:
    resolved: int = 0
    voided: int = 0
    confirmed: int = 0


def reconcile(
    conn: sqlite3.Connection, now: str, new_statements: Collection[int] = ()
) -> Reconciled:
    """Steps 1 to 4 (see the module), in the caller's transaction. `new_statements`: the ids of
    the statements stored in this run (the only rows a provisional may hand its identity to)."""
    visible = {
        int(row[0]) for row in conn.execute("SELECT id FROM alerts WHERE status = 'provisional'")
    }
    if not visible and conn.execute("SELECT 1 FROM alerts LIMIT 1").fetchone() is None:
        return Reconciled()
    _restatus(conn, now)
    resolved = _resolve_cards(conn, now)
    voided = _void(conn, now)
    rows = spending.card_fingerprints(conn)
    confirmed = _confirm(conn, rows, visible, frozenset(new_statements), now)
    return Reconciled(resolved, voided, confirmed)


def _restatus(conn: sqlite3.Connection, now: str) -> None:
    rows = conn.execute(
        "SELECT id, parser, bank_status FROM alerts WHERE status = 'unknown_status'"
    ).fetchall()
    for alert_id, name, bank_status in rows:
        parser = alerts.by_name(name)
        if parser is None or bank_status is None:
            continue
        kind = status_kind(bank_status, parser.STATUSES)
        if kind != "unknown":
            conn.execute(
                "UPDATE alerts SET status = ?, updated_at = ? WHERE id = ?",
                (_STATUS_OF_KIND[kind], now, alert_id),
            )


def _resolve_cards(conn: sqlite3.Connection, now: str) -> int:
    rows = conn.execute(
        "SELECT id, parser, last4, day FROM alerts WHERE status = 'unknown_card'"
    ).fetchall()
    resolved = 0
    for alert_id, name, last4, day in rows:
        parser = alerts.by_name(name)
        if parser is None:
            continue
        accounts = conn.execute(
            "SELECT DISTINCT a.key FROM cards c JOIN accounts a ON a.id = c.account_id "
            "WHERE c.last4 = ? AND a.institution = ? AND a.kind = 'credit_card'",
            (last4, parser.INSTITUTION),
        ).fetchall()
        if len(accounts) != 1:
            continue
        key = str(accounts[0][0])
        first = conn.execute(
            "SELECT MIN(COALESCE(s.period_start, s.period_end)) FROM statements s "
            "JOIN accounts a ON a.id = s.account_id WHERE a.key = ?",
            (key,),
        ).fetchone()[0]
        status = "stale" if first is not None and day < first else "provisional"
        conn.execute(
            "UPDATE alerts SET status = ?, account_key = ?, updated_at = ? WHERE id = ?",
            (status, key, now, alert_id),
        )
        resolved += 1
    return resolved


def _void(conn: sqlite3.Connection, now: str) -> int:
    cancels = conn.execute(
        "SELECT r.id, r.last4, r.currency, r.amount_cents, r.day, r.merchant FROM alerts r "
        "WHERE r.status = 'reversed' "
        "AND NOT EXISTS (SELECT 1 FROM alerts t WHERE t.voided_by = r.id) ORDER BY r.day, r.id"
    ).fetchall()
    voided = 0
    for cancel_id, last4, currency, amount, day, merchant in cancels:
        targets = conn.execute(
            "SELECT id, day, merchant, status FROM alerts WHERE status IN "
            "('provisional', 'unknown_card', 'unknown_status') AND voided_by IS NULL "
            "AND last4 = ? AND currency = ? AND amount_cents = ? AND id != ?",
            (last4, currency, amount, cancel_id),
        ).fetchall()
        when = date.fromisoformat(day)
        fitting = [
            (
                -similarity(row[2], merchant),
                abs((when - date.fromisoformat(row[1])).days),
                row[0],
                row[2],
                row[3],
            )
            for row in targets
            if -DAYS_BEFORE <= (when - date.fromisoformat(row[1])).days <= VOID_DAYS
        ]
        if not fitting:
            continue
        _, _, target, target_merchant, target_status = min(fitting)
        # `voided_by` marks the cancelling alert as used: an undo of the void does not redo it.
        conn.execute(
            "UPDATE alerts SET voided_by = ?, updated_at = ? WHERE id = ?",
            (cancel_id, now, target),
        )
        if target_status == "provisional":
            if not live_store.is_linked(conn, live_store.fingerprint(target)):
                _log_void(conn, target, target_merchant, now)
            # Linked: not voided, it is a To review item (`live_store.reversals`).
        else:  # held: never was a transaction
            conn.execute("UPDATE alerts SET status = 'voided' WHERE id = ?", (target,))
        voided += 1
    return voided


def _log_void(
    conn: sqlite3.Connection, target: int, merchant: str, now: str, *, undo: bool = False
) -> None:
    """A visible provisional is cancelled with a `'void'` decision in the change log (or, with
    `undo`, the decision is removed because the statement has the charge), so the user sees it
    in the transaction's history and can undo it."""
    mark = live_store.fingerprint(target)
    pending, voided = t("web.provisional.pending"), t("web.provisional.voided")
    with changelog.track(
        conn,
        "provisional",
        "transaction",
        mark,
        merchant,
        before=voided if undo else pending,
        after=pending if undo else voided,
        merchant=merchant,
        fingerprints=[mark],
    ):
        live_store.decide(conn, mark, None if undo else "void", now)


def _confirm(
    conn: sqlite3.Connection,
    rows: list[tuple[sqlite3.Row, str]],
    visible: set[int],
    new_statements: frozenset[int],
    now: str,
) -> int:
    opens = [
        Open(
            id=row[0],
            account=row[1],
            day=date.fromisoformat(row[2]),
            amount_cents=row[3],
            currency=row[4],
            merchant=row[5],
            last4=row[6],
        )
        for row in conn.execute(
            "SELECT al.id, al.account_key, al.day, al.amount_cents, al.currency, al.merchant, "
            "al.last4 FROM alerts al LEFT JOIN provisional_decisions d "
            "ON d.fingerprint = 'alert-' || al.id AND d.decision = 'discard' "
            "WHERE al.status = 'provisional' AND d.fingerprint IS NULL"
        )
    ]
    if not opens:
        return 0
    claimed = {
        str(row[0])
        for row in conn.execute(
            "SELECT statement_fingerprint FROM alerts WHERE statement_fingerprint IS NOT NULL"
        )
    }
    plastics = {
        int(row[0]): row[1]
        for row in conn.execute(
            "SELECT s.id, c.last4 FROM statements s LEFT JOIN cards c ON c.id = s.card_id"
        )
    }
    candidates = [
        Candidate(
            fingerprint=fp,
            account=row["account"],
            day=date.fromisoformat(row["transacted_on"]),
            amount_cents=row["amount_cents"],
            currency=row["currency"],
            description=row["description"],
            last4=plastics.get(row["statement_id"]),
            order=order,
            statement_id=int(row["statement_id"]),
        )
        for order, (row, fp) in enumerate(rows)
        if row["direction"] == "debit" and fp not in claimed
    ]
    found = match(opens, candidates)
    decisions = live_store.decisions(conn)
    merchants = {alert.id: alert.merchant for alert in opens}
    for alert_id, row in found.items():
        if decisions.get(live_store.fingerprint(alert_id)) == "void":
            # The bank said "reversed" but the statement has the charge: the void is undone.
            _log_void(conn, alert_id, merchants[alert_id], now, undo=True)
        keeps = alert_id in visible and row.statement_id in new_statements
        conn.execute(
            "UPDATE alerts SET status = 'confirmed', statement_fingerprint = ?, "
            "keeps_identity = ?, updated_at = ? WHERE id = ?",
            (row.fingerprint, 1 if keeps else 0, now, alert_id),
        )
    return len(found)
