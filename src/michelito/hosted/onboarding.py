"""What a new hosted account needs after the gate: whether it is open, where to land, the setup
checklist and the first review of the top merchants. Everything comes from the account's own
database (the request's connection, through the workspace seam) and is deterministic.

- **Gate**: open as soon as one statement is stored (only statements that square are).
- **Landing**: the newest month with expenses (`summary.month_options`), else the newest closing.
- **Checklist**: more months (done at `MONTHS_GOAL`), another account (done at two), automate the
  next ones (done once a forwarded email arrived, `hosted.inbox`) and the months missing per
  account, as `michelito report`
  computes them (`report.missing_months`). Hidden once completed or dismissed.
- **First review**: the top `TOP_MERCHANTS` merchants by total spend (in RD$, US$ at the month's
  rate), each with its category; "Correct" marks its transactions reviewed (the same
  `reviewed_fingerprints` that `michelito new --mark-reviewed` fills), "Change" goes through the
  usual correction (a merchant rule). Hidden once dismissed or every merchant was handled.

The two "dismissed" flags live in the account's own database (`onboarding_flags`). Both
"Correct" (`reviewed_fingerprints`) and the flags are recorded in the change log and can be
undone from it, like any other edit.

"To review" has no item that asks to confirm a category: its items are
detections (one-offs, duplicates, price rises, possible investments, rules...). So "Correct"
marks the merchant's transactions reviewed in the queue of new transactions
(`reviewed_fingerprints`, the one `michelito new` and Claude's review read), and leaves every
"To review" item where it is: what was not reviewed stays there. A category-confirmation item
kind in "To review" would need a schema change of the shared database and is left for later.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from michelito import config, report
from michelito.analysis import catalog, rates
from michelito.analysis.accounts import account_infos
from michelito.analysis.spending import Movement
from michelito.db import PRINTOUT_PARSERS
from michelito.hosted import inbox_store
from michelito.web import summary

MONTHS_GOAL = 3
TOP_MERCHANTS = 10
FLAGS = ("first_review_closed", "checklist_dismissed")


@dataclass(frozen=True)
class Missing:
    bank: str
    kind: str
    identifier: str  # last four characters
    month: str  # YYYY-MM


@dataclass(frozen=True)
class Checklist:
    months: int
    accounts: int
    more_months_done: bool
    other_account_done: bool
    missing: tuple[Missing, ...]
    visible: bool
    automate_done: bool = False


@dataclass(frozen=True)
class State:
    open: bool
    landing: str | None  # YYYY-MM
    checklist: Checklist
    first_review: bool  # the card is still to be shown


@dataclass(frozen=True)
class Merchant:
    merchant: str
    total: Decimal  # RD$
    count: int
    category: str
    category_id: int | None
    fingerprint: str  # one of its transactions (the correction goes through it)
    fingerprints: tuple[str, ...]


def flags(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(str(row[0]) for row in conn.execute("SELECT key FROM onboarding_flags"))


def set_flag(conn: sqlite3.Connection, key: str) -> None:
    """Nothing commits: the caller wraps it (and its change-log entry) in `with conn:`."""
    if key not in FLAGS:
        raise ValueError(f"unknown flag: {key}")
    conn.execute(
        "INSERT INTO onboarding_flags (key, set_at) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
        (key, datetime.now(UTC).isoformat(timespec="seconds")),
    )


def is_open(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT EXISTS (SELECT 1 FROM statements)").fetchone()[0] == 1


def build_state(conn: sqlite3.Connection, flow: Sequence[Movement]) -> State:
    opened = is_open(conn)
    marked = flags(conn)
    checklist = _checklist(conn, "checklist_dismissed" in marked)
    if not opened:
        return State(False, None, checklist, False)
    options = summary.month_options(flow, account_infos(conn))
    landing = options[0].month if options else _newest_closing(conn)
    pending = any(not _handled(conn, m) for m in top_merchants(conn, flow))
    first_review = "first_review_closed" not in marked and pending
    return State(True, landing, checklist, first_review)


def _newest_closing(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT max(period_end) FROM statements").fetchone()
    return str(row[0])[:7] if row and row[0] else None


def _checklist(conn: sqlite3.Connection, dismissed: bool) -> Checklist:
    months = conn.execute(
        "SELECT COUNT(DISTINCT substr(period_end, 1, 7)) FROM statements"
    ).fetchone()[0]
    accounts = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    missing = tuple(_missing(conn))
    more = months >= MONTHS_GOAL
    other = accounts >= 2
    automated = _automated(conn)
    visible = not dismissed and not (more and other and automated and not missing)
    return Checklist(int(months), int(accounts), more, other, missing, visible, automated)


def _automated(conn: sqlite3.Connection) -> bool:
    """A forwarded email arrived (the inbox's tables exist only once forwarding was used)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inbox_messages'"
    ).fetchone()
    return exists is not None and inbox_store.has_arrivals(conn)


def _missing(conn: sqlite3.Connection) -> list[Missing]:
    """Months without a statement per account (the printouts are not closings), as
    `michelito report` lists them."""
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
        ends[row["key"]].append(date.fromisoformat(row["period_end"]))
        about[row["key"]] = (row["institution"], row["kind"], str(row["ident"])[-4:])
    found = []
    for key, closings in ends.items():
        bank, kind, ident = about[key]
        for month in report.missing_months(sorted(set(closings)), config.COMMIT_FROM):
            found.append(Missing(bank, kind, ident, month))
    return found


def top_merchants(
    conn: sqlite3.Connection, flow: Sequence[Movement], limit: int = TOP_MERCHANTS
) -> list[Merchant]:
    """The merchants with the most spending (RD$), largest first; ties by name."""
    by_month = rates.load(conn)
    known = catalog.load(conn)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    moves: dict[str, list[Movement]] = defaultdict(list)
    for move in flow:
        if move.kind != "expense" or move.amount <= 0 or not move.merchant:
            continue
        value = _dop(move, by_month)
        if value is None:
            continue
        totals[move.merchant] += value
        moves[move.merchant].append(move)
    ranked = sorted(totals, key=lambda name: (-totals[name], name))[:limit]
    result = []
    for name in ranked:
        items = sorted(moves[name], key=lambda m: (m.day, m.fingerprint), reverse=True)
        found = known.by_ref(items[0].ref)
        result.append(
            Merchant(
                merchant=name,
                total=totals[name],
                count=len(items),
                category=items[0].category,
                category_id=found.id if found else None,
                fingerprint=items[0].fingerprint,
                fingerprints=tuple(m.fingerprint for m in items if m.fingerprint),
            )
        )
    return result


def _dop(move: Movement, by_month: dict[str, rates.Rate]) -> Decimal | None:
    if move.currency == "DOP":
        return move.amount
    rate = rates.rate_for(by_month, move.month)
    return None if rate is None else move.amount * rate.value


def reviewed_fingerprints(conn: sqlite3.Connection) -> frozenset[str]:
    rows = conn.execute("SELECT fingerprint FROM reviewed_fingerprints")
    return frozenset(str(row[0]) for row in rows)


def _handled(conn: sqlite3.Connection, merchant: Merchant) -> bool:
    """Reviewed ("Correct") or given a merchant rule ("Change")."""
    if merchant_has_rule(conn, merchant.merchant):
        return True
    return set(merchant.fingerprints) <= reviewed_fingerprints(conn)


def merchant_has_rule(conn: sqlite3.Connection, merchant: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM merchant_categories WHERE merchant = ?", (merchant,)
    ).fetchone()
    return row is not None


def mark_reviewed(conn: sqlite3.Connection, fingerprints: Sequence[str]) -> None:
    """Nothing commits: the caller wraps it (and its change-log entry) in `with conn:`."""
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    conn.executemany(
        "INSERT INTO reviewed_fingerprints (fingerprint, reviewed_at) VALUES (?, ?) "
        "ON CONFLICT(fingerprint) DO NOTHING",
        [(fp, stamp) for fp in fingerprints],
    )


def merchant_status(conn: sqlite3.Connection, merchant: Merchant) -> str:
    """ "rule", "reviewed" or "pending"."""
    if merchant_has_rule(conn, merchant.merchant):
        return "rule"
    if merchant.fingerprints and set(merchant.fingerprints) <= reviewed_fingerprints(conn):
        return "reviewed"
    return "pending"
