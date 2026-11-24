"""AI imports (schema 29): transactions an AI connector read elsewhere, kept until the person
approves them in Review (see `.superpowers/sdd/ai-connector.md`, phase 2).

- **Statements** (`propose_statement`): a whole statement of one of the person's accounts, with
  its printed totals. It is built as the `Statement` a parser would make (`statement_of`) and
  must square exactly like a PDF does (`hosted.uploads.failing_checks`): one that does not is
  refused, with what did not square, so the AI can read it again. One already stored (same
  account, cut-off and currency) is refused as a duplicate. Applying it stores it through
  `ingest.ingest_statement` (document source `ai`), which also reconciles bank alerts.
- **Provisional charges** (`propose_rows`, kind `provisional`): loose charges of one account
  (from a CSV, a screenshot...), without totals to check. Applied, each one is a provisional
  transaction like a bank alert's (`alerts`, source `ai`): its statement confirms it later
  (`live_match`), or it becomes a To review item if it never shows up.
- **Cash** (`propose_rows`, kind `cash`): entries of the cash account, applied through
  `POST /api/cash-box/entries` (`web.proposal_routes`).

Only existing accounts are accepted. Each loose row gets the stored transaction it seems to
repeat (same account, currency and cents within `DUPLICATE_DAYS`), and Review leaves those
unticked. Texts come from the AI: plain text, cut to their maximum.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from michelito import db, importer, ingest
from michelito.analysis import cash_box, catalog, changelog, live_match
from michelito.analysis.spending import Movement
from michelito.hosted.uploads import failing_checks
from michelito.migrations_v28 import EXPLANATION_MAX, TITLE_MAX
from michelito.migrations_v29 import AMOUNT_MAX_CENTS, DESCRIPTION_MAX, PAYLOAD_MAX
from michelito.parsers.common import CREDIT, DEBIT, Section, Statement, Transaction
from michelito.web.proposals import OPEN_MAX, SOURCE_MAX, ProposalError, plain

ROWS_MAX = 300
SECTION_ROWS_MAX = 1000
DUPLICATE_DAYS = 3
FUTURE_DAYS = 1  # a day may be at most this far ahead of today (time zones)
PROVISIONAL_DAYS = 120  # a pending charge older than this belongs in a statement
STATEMENT_YEARS = 3  # a statement's cut-off may be at most this old
OVERLAP_DAYS = 20  # a cut-off this close to a stored one is the same period again
LEAD_DAYS = 45  # a movement may be this much before the start (or the cut-off, without one)
MANUAL = "manual"  # the cash box's institution: never imported into
_SECTION_KEYS = frozenset(
    {
        "currency",
        "previous_balance_cents",
        "closing_balance_cents",
        "minimum_payment_cents",
        "credit_limit_cents",
        "printed_debits_cents",
        "printed_credits_cents",
        "transactions",
    }
)
_TRANSACTION_KEYS = frozenset(
    {"day", "posted_day", "description", "amount_cents", "direction", "reference", "balance_cents"}
)
PARSER = "ai"
SOURCE = "ai"
Direction = Literal["out", "in"]
RowKind = Literal["provisional", "cash"]


@dataclass(frozen=True)
class RowIn:
    day: date
    description: str
    amount_cents: int
    currency: str
    direction: Direction
    category_id: int | None = None


def _cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def _money(cents: int | None) -> Decimal | None:
    return None if cents is None else Decimal(cents) / 100


def _check_day(day: date, today: date, where: str) -> None:
    if day > today + timedelta(days=FUTURE_DAYS) or day.year < 2000:
        raise ProposalError("day", where)


def _account(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    previous = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, key, institution, kind, name FROM accounts WHERE key = ?", (key,)
        ).fetchone()
    finally:
        conn.row_factory = previous
    if row is None:
        raise ProposalError("unknown_account")
    if row["institution"] == MANUAL:
        raise ProposalError("not_a_bank_account")
    return row


def _open_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute("SELECT COUNT(*) FROM ai_proposals WHERE status = 'open'").fetchone()[0]
    )


def _new_proposal(
    conn: sqlite3.Connection,
    kind: str,
    account_key: str,
    source: str,
    title: str,
    explanation: str,
) -> int:
    """Insert the proposal row (inside the caller's transaction)."""
    shown = plain(title, TITLE_MAX)
    if not shown:
        raise ProposalError("title")
    if _open_count(conn) >= OPEN_MAX:
        raise ProposalError("too_many_open")
    cursor = conn.execute(
        "INSERT INTO ai_proposals (created_at, source, title, explanation, kind, account_key) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            changelog.now().isoformat(timespec="seconds"),
            plain(source, SOURCE_MAX) or "MCP",
            shown,
            plain(explanation, EXPLANATION_MAX),
            kind,
            account_key,
        ),
    )
    return int(cursor.lastrowid or 0)


# Loose rows ----------------------------------------------------------------------------------


Index = dict[tuple[str, bool, int], list[tuple[date, str]]]


def index_of(candidates: Sequence[Movement]) -> Index:
    """The candidates by (currency, money out, cents), each with its day and fingerprint."""
    found: Index = {}
    for movement in candidates:
        if movement.fingerprint:
            key = (movement.currency, movement.amount > 0, _cents(abs(movement.amount)))
            found.setdefault(key, []).append((movement.day, movement.fingerprint))
    return found


def duplicate_of(row: RowIn, index: Index) -> str:
    """The stored transaction this row seems to repeat (fingerprint), or ''."""
    for day, fingerprint in index.get((row.currency, row.direction == "out", row.amount_cents), []):
        if abs((day - row.day).days) <= DUPLICATE_DAYS:
            return fingerprint
    return ""


def _candidates(flow: Sequence[Movement], kind: RowKind, account_key: str) -> list[Movement]:
    if kind == "cash":
        return [m for m in flow if m.fingerprint.startswith(cash_box.FINGERPRINT_PREFIX)]
    return [m for m in flow if m.account == account_key]


def _check_rows(
    conn: sqlite3.Connection, kind: RowKind, rows: Sequence[RowIn], today: date
) -> list[RowIn]:
    if not 1 <= len(rows) <= ROWS_MAX:
        raise ProposalError("rows", f"between 1 and {ROWS_MAX}")
    known = catalog.load(conn)
    checked = []
    for index, row in enumerate(rows):
        where = f"rows[{index}]"
        _check_day(row.day, today, where)
        description = plain(row.description, DESCRIPTION_MAX)
        if not description:
            raise ProposalError("description", where)
        if not 1 <= row.amount_cents <= AMOUNT_MAX_CENTS:
            raise ProposalError("amount", where)
        if row.currency not in ("DOP", "USD"):
            raise ProposalError("currency", where)
        if kind == "provisional" and row.direction != "out":
            raise ProposalError("provisional_charges_only", where)
        if kind == "provisional" and row.day < today - timedelta(days=PROVISIONAL_DAYS):
            raise ProposalError("too_old_for_pending", where)
        if row.category_id is not None:
            category = known.by_id(row.category_id)
            wanted = "income" if row.direction == "in" else "expense"
            if kind != "cash" or category is None or category.kind != wanted:
                raise ProposalError("category", where)
        checked.append(
            RowIn(
                row.day,
                description,
                row.amount_cents,
                row.currency,
                row.direction,
                row.category_id,
            )
        )
    return checked


def propose_rows(
    conn: sqlite3.Connection,
    flow: Sequence[Movement],
    today: date,
    source: str,
    title: str,
    explanation: str,
    kind: RowKind,
    account_key: str,
    rows: Sequence[RowIn],
) -> int:
    """Save one open `provisional` or `cash` proposal; its id (`ProposalError` if anything in
    it does not hold). `account_key` only for provisional charges: an existing account that is
    not the cash one."""
    if kind == "provisional":
        _account(conn, account_key)
    else:
        account_key = ""
    checked = _check_rows(conn, kind, rows, today)
    index = index_of(_candidates(flow, kind, account_key))
    with conn:
        proposal_id = _new_proposal(conn, kind, account_key, source, title, explanation)
        conn.executemany(
            "INSERT INTO ai_import_rows (proposal_id, day, description, amount_cents, currency, "
            "direction, category_id, duplicate_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    proposal_id,
                    r.day.isoformat(),
                    r.description,
                    r.amount_cents,
                    r.currency,
                    r.direction,
                    r.category_id,
                    duplicate_of(r, index),
                )
                for r in checked
            ],
        )
    return proposal_id


def add_provisionals(
    conn: sqlite3.Connection, proposal_id: int, account_key: str, row_ids: Sequence[int]
) -> dict[int, str]:
    """Store the chosen rows as provisional charges of the account and reconcile them (one may
    be confirmed at once by a statement already stored); their fingerprints by row id."""
    now = changelog.now().isoformat(timespec="seconds")
    made: dict[int, str] = {}
    with conn:
        for row_id in row_ids:
            row = conn.execute(
                "SELECT day, description, amount_cents, currency FROM ai_import_rows "
                "WHERE id = ? AND proposal_id = ?",
                (row_id, proposal_id),
            ).fetchone()
            if row is None:
                continue
            cursor = conn.execute(
                "INSERT INTO alerts (message_id, source, parser, received_at, status, "
                "bank_status, account_key, day, amount_cents, currency, merchant, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, 'provisional', 'approved', ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{SOURCE}-{proposal_id}-{row_id}",
                    SOURCE,
                    PARSER,
                    now,
                    account_key,
                    row[0],
                    row[2],
                    row[3],
                    row[1],
                    now,
                    now,
                ),
            )
            made[row_id] = f"alert-{int(cursor.lastrowid or 0)}"
        live_match.reconcile(conn, now)
    return made


# Statements ----------------------------------------------------------------------------------


def _decimal_cents(value: Any, where: str, allow_negative: bool = True) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProposalError("amount", where)
    if abs(value) > AMOUNT_MAX_CENTS or (not allow_negative and value <= 0):
        raise ProposalError("amount", where)
    return Decimal(value) / 100


def _non_negative(value: Any, where: str) -> Decimal | None:
    found = _decimal_cents(value, where)
    if found is not None and found < 0:
        raise ProposalError("amount", where)
    return found


def _day(value: Any, where: str, required: bool = True) -> date | None:
    if value is None and not required:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ProposalError("day", where) from None


def _identifier(conn: sqlite3.Connection, account: sqlite3.Row, card_last4: Any) -> str:
    if account["kind"] != "credit_card":
        return str(account["key"]).split(":", 2)[2]
    if card_last4 is not None:
        known = conn.execute(
            "SELECT 1 FROM cards WHERE account_id = ? AND last4 = ?",
            (account["id"], str(card_last4)),
        ).fetchone()
        if known is None:  # only a card the account already has
            raise ProposalError("card_last4")
        return str(card_last4)
    row = conn.execute(
        "SELECT last4 FROM cards WHERE account_id = ? ORDER BY last_seen DESC LIMIT 1",
        (account["id"],),
    ).fetchone()
    if row is None:
        raise ProposalError("card_last4")
    return str(row[0])


def _product(conn: sqlite3.Connection, account: sqlite3.Row) -> str:
    row = conn.execute(
        "SELECT product FROM statements WHERE account_id = ? ORDER BY period_end DESC LIMIT 1",
        (account["id"],),
    ).fetchone()
    return str(row[0]) if row and row[0] else str(account["name"])


def _transaction(item: Any, currency: str, where: str) -> Transaction:
    if not isinstance(item, Mapping) or set(item) - _TRANSACTION_KEYS:
        raise ProposalError("transaction", where)
    description = plain(str(item.get("description", "")), DESCRIPTION_MAX)
    if not description:
        raise ProposalError("description", where)
    direction = item.get("direction")
    if direction not in (DEBIT, CREDIT):
        raise ProposalError("direction", where)
    amount = _decimal_cents(item.get("amount_cents"), where, allow_negative=False)
    if amount is None:
        raise ProposalError("amount", where)
    reference = item.get("reference")
    return Transaction(
        transacted_on=_day(item.get("day"), where) or date.min,
        posted_on=_day(item.get("posted_day"), where, required=False),
        description=description,
        amount=amount,
        direction=direction,
        currency=currency,
        reference=plain(str(reference), 40) or None if reference is not None else None,
        mcc=None,
        raw_line=description,
        balance=_decimal_cents(item.get("balance_cents"), where),
    )


def _section(raw: Any, index: int) -> Section:
    where = f"sections[{index}]"
    if not isinstance(raw, Mapping) or set(raw) - _SECTION_KEYS:
        raise ProposalError("section", where)
    currency = raw.get("currency")
    if currency not in ("DOP", "USD"):
        raise ProposalError("currency", where)
    items = raw.get("transactions")
    if not isinstance(items, list) or len(items) > SECTION_ROWS_MAX:
        raise ProposalError("transactions", where)
    return Section(
        currency=currency,
        previous_balance=_decimal_cents(raw.get("previous_balance_cents"), where),
        closing_balance=_decimal_cents(raw.get("closing_balance_cents"), where),
        minimum_payment=_non_negative(raw.get("minimum_payment_cents"), where),
        credit_limit=_non_negative(raw.get("credit_limit_cents"), where),
        printed_debits=_non_negative(raw.get("printed_debits_cents"), where),
        printed_credits=_non_negative(raw.get("printed_credits_cents"), where),
        transactions=tuple(
            _transaction(item, currency, f"{where}.transactions[{n}]")
            for n, item in enumerate(items)
        ),
    )


def statement_of(
    conn: sqlite3.Connection, account_key: str, payload: Mapping[str, Any]
) -> Statement:
    """The `Statement` a parser would make of the AI's reading, for one existing account
    (`ProposalError` for anything malformed). It is not validated here."""
    account = _account(conn, account_key)
    sections = payload.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 2:
        raise ProposalError("sections", "one or two (one per currency)")
    built = tuple(_section(raw, i) for i, raw in enumerate(sections))
    if len({s.currency for s in built}) != len(built):
        raise ProposalError("sections", "one per currency")
    statement = Statement(
        parser=PARSER,
        institution=str(account["institution"]),
        kind=str(account["kind"]),
        product=_product(conn, account),
        identifier=_identifier(conn, account, payload.get("card_last4")),
        period_end=_day(payload.get("period_end"), "period_end") or date.min,
        due_date=_day(payload.get("due_date"), "due_date", required=False),
        sections=built,
        period_start=_day(payload.get("period_start"), "period_start", required=False),
    )
    if db.account_key(statement) != account_key:  # it would be stored in another account
        raise ProposalError("account_shape")
    return statement


def _shown(amount: Decimal | None) -> str:
    return "not given" if amount is None else f"{amount:.2f}"


def squares(statement: Statement) -> list[str]:
    """What does not square, for the AI: each failing check with the totals it read (its own
    numbers) next to the printed ones; empty when the statement squares."""
    failing = failing_checks(statement)
    if not failing:
        return []
    found = []
    for index, section in enumerate(statement.sections, start=1):
        debits = sum((t.amount for t in section.transactions if t.direction == DEBIT), Decimal(0))
        credits = sum((t.amount for t in section.transactions if t.direction == CREDIT), Decimal(0))
        names = [f.split(":", 1)[1] for f in failing if f.startswith(f"section{index}:")]
        if names:
            found.append(
                f"section {index} ({section.currency}): {', '.join(names)} failed; read "
                f"debits {_shown(debits)}, credits {_shown(credits)}; printed debits "
                f"{_shown(section.printed_debits)}, credits {_shown(section.printed_credits)}, "
                f"previous balance {_shown(section.previous_balance)}, closing balance "
                f"{_shown(section.closing_balance)}"
            )
    return found or list(failing)


def _check_dates(statement: Statement, today: date) -> None:
    """The cut-off within `STATEMENT_YEARS` and not ahead, the start before it, and every
    movement between the start (or the cut-off) less `LEAD_DAYS` and the cut-off."""
    end = statement.period_end
    _check_day(end, today, "period_end")
    if end < today - timedelta(days=365 * STATEMENT_YEARS):
        raise ProposalError("too_old", "period_end")
    start = statement.period_start
    if start is not None and start > end:
        raise ProposalError("day", "period_start")
    earliest = (start or end) - timedelta(days=LEAD_DAYS)
    for index, section in enumerate(statement.sections):
        for number, item in enumerate(section.transactions):
            days = [item.transacted_on, *([item.posted_on] if item.posted_on else [])]
            if any(d < earliest or d > end for d in days):
                raise ProposalError("day", f"sections[{index}].transactions[{number}]")


def _check_currencies(conn: sqlite3.Connection, account_key: str, statement: Statement) -> None:
    """An account that has statements gets only the currencies it already has."""
    used = {
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT s.currency FROM statements s JOIN accounts a ON a.id = s.account_id "
            "WHERE a.key = ?",
            (account_key,),
        )
    }
    if used and any(s.currency not in used for s in statement.sections):
        raise ProposalError("currency", "the account never had it")


def _stored_already(conn: sqlite3.Connection, account_key: str, statement: Statement) -> bool:
    """A stored statement of the same account, card and currency whose cut-off is within
    `OVERLAP_DAYS` of this one (the same period read again)."""
    marks = ",".join("?" * len(statement.sections))
    card = statement.identifier if statement.kind == "credit_card" else None
    row = conn.execute(
        "SELECT 1 FROM statements s JOIN accounts a ON a.id = s.account_id "
        "LEFT JOIN cards c ON c.id = s.card_id WHERE a.key = ? "
        "AND abs(julianday(s.period_end) - julianday(?)) < ? "
        f"AND s.currency IN ({marks}) AND (? IS NULL OR c.last4 = ?) LIMIT 1",
        (
            account_key,
            statement.period_end.isoformat(),
            OVERLAP_DAYS,
            *(s.currency for s in statement.sections),
            card,
            card,
        ),
    ).fetchone()
    return row is not None


def _waiting(conn: sqlite3.Connection, account_key: str, statement: Statement) -> bool:
    """An open proposal of the same account and cut-off."""
    row = conn.execute(
        "SELECT 1 FROM ai_proposals p JOIN ai_import_statements i ON i.proposal_id = p.id "
        "WHERE p.status = 'open' AND p.account_key = ? AND i.period_end = ?",
        (account_key, statement.period_end.isoformat()),
    ).fetchone()
    return row is not None


def propose_statement(
    conn: sqlite3.Connection,
    today: date,
    source: str,
    title: str,
    explanation: str,
    account_key: str,
    payload: Mapping[str, Any],
) -> int:
    """Save one open `statement` proposal; its id. `ProposalError`: malformed, about another
    account, `not_squared` (with what did not square) or `duplicate_statement`."""
    statement = statement_of(conn, account_key, payload)
    _check_dates(statement, today)
    _check_currencies(conn, account_key, statement)
    problems = squares(statement)
    if problems:
        raise ProposalError("not_squared", "; ".join(problems))
    if _stored_already(conn, account_key, statement):
        raise ProposalError("duplicate_statement")
    if _waiting(conn, account_key, statement):
        raise ProposalError("already_proposed")
    stored = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    if len(stored) > PAYLOAD_MAX:
        raise ProposalError("too_large")
    with conn:
        proposal_id = _new_proposal(conn, "statement", account_key, source, title, explanation)
        conn.execute(
            "INSERT INTO ai_import_statements (proposal_id, period_start, period_end, "
            "currencies, transactions, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (
                proposal_id,
                statement.period_start.isoformat() if statement.period_start else None,
                statement.period_end.isoformat(),
                ",".join(s.currency for s in statement.sections),
                sum(len(s.transactions) for s in statement.sections),
                stored,
            ),
        )
    return proposal_id


@dataclass(frozen=True)
class SectionSummary:
    """What Review shows of a statement's section, to judge it before storing it."""

    currency: str
    transactions: int
    debits_cents: int | None  # the printed totals
    credits_cents: int | None
    closing_cents: int | None
    # Whether its previous balance is the closing balance of the account's latest stored
    # statement in that currency (None: nothing to compare).
    continues: bool | None


def section_summaries(
    conn: sqlite3.Connection, account_key: str, payload: Mapping[str, Any]
) -> list[SectionSummary]:
    found = []
    end = str(payload.get("period_end", ""))
    for raw in payload.get("sections", []):
        if not isinstance(raw, Mapping):
            continue
        last = conn.execute(
            "SELECT s.closing_balance_cents FROM statements s JOIN accounts a "
            "ON a.id = s.account_id WHERE a.key = ? AND s.currency = ? AND s.period_end < ? "
            "ORDER BY s.period_end DESC LIMIT 1",
            (account_key, raw.get("currency"), end),
        ).fetchone()
        previous = raw.get("previous_balance_cents")
        continues = (
            None if last is None or last[0] is None or previous is None else last[0] == previous
        )
        found.append(
            SectionSummary(
                str(raw.get("currency", "")),
                len(raw.get("transactions") or []),
                raw.get("printed_debits_cents"),
                raw.get("printed_credits_cents"),
                raw.get("closing_balance_cents"),
                continues,
            )
        )
    return found


def payload_of(conn: sqlite3.Connection, proposal_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT payload FROM ai_import_statements WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()
    return {} if row is None else dict(json.loads(row[0]))


def store_statement(conn: sqlite3.Connection, proposal_id: int, account_key: str) -> str:
    """Store an approved statement proposal like a document: `parsed`, `duplicate`, `invalid`
    or `error` (it is built and checked again: the database may have changed)."""
    row = conn.execute(
        "SELECT payload FROM ai_import_statements WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()
    if row is None:
        return "error"
    statement = statement_of(conn, account_key, json.loads(row[0]))
    if _stored_already(conn, account_key, statement):
        status = "duplicate"
        with conn:
            conn.execute(
                "UPDATE ai_import_statements SET document_status = ? WHERE proposal_id = ?",
                (status, proposal_id),
            )
        return status
    content = f"{PARSER}-proposal-{proposal_id}\n{row[0]}".encode()
    registered = importer.register_ai(
        conn, f"ai-{statement.period_end.isoformat()}", content, changelog.now()
    )
    status = ingest.ingest_statement(conn, registered.document_id, PARSER, statement)
    with conn:
        conn.execute(
            "UPDATE ai_import_statements SET document_status = ? WHERE proposal_id = ?",
            (status, proposal_id),
        )
    return status
