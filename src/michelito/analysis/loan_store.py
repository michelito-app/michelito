"""Loans as stored (schemas 26 and 27, `migrations_v26` and `v27`; the schedule is in
`loan_schedule`).

- `load` gives every loan with its contract, rates, the bank's installments, real balances,
  statement lines and linked payments; `taken` and `dismissed`, what the matching needs to
  know about the links.
- `create`, `update`, `delete`; `set_rate`/`delete_rate`, `set_installment`/
  `delete_installment`, `set_balance`/`delete_balance`;
  `add_statement_lines` (what a loan statement parser stores).
- `link` ("it is a payment of this loan", by hand) and `unlink` (it is not: refused, so it is
  not linked again).
- `reconcile` links every charge whose description has a loan's number, from any account.

Nothing here commits: the caller wraps it in `with conn:` (and the change log).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from michelito.analysis import ledger_store, loan_match
from michelito.analysis.links import LinkError
from michelito.analysis.loan_schedule import Anchor, Contract, Installment, Rate, StatementLine
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.migrations_v26 import NAME_MAX, NUMBER_MAX, RATE_MAX_BP, TERM_MAX
from michelito.migrations_v27 import INSTALLMENT_MAX_CENTS

_CENTS = 100
_BP = 100  # rate_bp per percent


@dataclass(frozen=True)
class Loan:
    id: int
    name: str
    number: str
    currency: str
    contract: Contract
    rates: tuple[Rate, ...] = ()
    installments: tuple[Installment, ...] = ()  # what the bank charges, from a day on
    anchors: tuple[Anchor, ...] = ()
    statement_lines: tuple[StatementLine, ...] = ()
    links: dict[str, str] = field(default_factory=dict)  # fingerprint -> origin


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'loans'"
    ).fetchone()
    return row is not None


def amount_of(cents: int) -> Decimal:
    return Decimal(cents) / _CENTS


def cents_of(amount: Decimal) -> int:
    return int((amount * _CENTS).to_integral_value())


def _grouped(conn: sqlite3.Connection, query: str) -> dict[int, list[tuple]]:
    found: dict[int, list[tuple]] = {}
    for row in conn.execute(query):
        found.setdefault(int(row[0]), []).append(tuple(row[1:]))
    return found


def _installments(conn: sqlite3.Connection) -> dict[int, list[tuple]]:
    """The bank's installments (none before schema 27)."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'loan_installments'"
    ).fetchone()
    if row is None:
        return {}
    return _grouped(
        conn,
        "SELECT loan_id, effective, installment_cents FROM loan_installments ORDER BY effective",
    )


def load(conn: sqlite3.Connection) -> list[Loan]:
    if not _has_tables(conn):
        return []
    rates = _grouped(conn, "SELECT loan_id, effective, rate_bp FROM loan_rates ORDER BY effective")
    installments = _installments(conn)
    balances = _grouped(conn, "SELECT loan_id, day, balance_cents FROM loan_balances ORDER BY day")
    lines = _grouped(
        conn,
        "SELECT loan_id, day, principal_cents, interest_cents, balance_cents, other_cents "
        "FROM loan_statement_lines ORDER BY day, id",
    )
    links = _grouped(conn, "SELECT loan_id, fingerprint, origin FROM loan_links")
    rows = conn.execute(
        "SELECT id, name, number, currency, principal_cents, term, start_date FROM loans "
        "ORDER BY id"
    ).fetchall()
    return [
        Loan(
            id=int(r[0]),
            name=str(r[1]),
            number=str(r[2]),
            currency=str(r[3]),
            contract=Contract(amount_of(int(r[4])), int(r[5]), date.fromisoformat(str(r[6]))),
            rates=tuple(
                Rate(date.fromisoformat(day), Decimal(bp) / _BP) for day, bp in rates.get(r[0], [])
            ),
            installments=tuple(
                Installment(date.fromisoformat(day), amount_of(c))
                for day, c in installments.get(r[0], [])
            ),
            anchors=tuple(
                Anchor(date.fromisoformat(day), amount_of(c)) for day, c in balances.get(r[0], [])
            ),
            statement_lines=tuple(
                StatementLine(
                    date.fromisoformat(day),
                    amount_of(p),
                    amount_of(i),
                    amount_of(b),
                    amount_of(o),
                )
                for day, p, i, b, o in lines.get(r[0], [])
            ),
            links={str(fp): str(origin) for fp, origin in links.get(r[0], [])},
        )
        for r in rows
    ]


def plan(conn: sqlite3.Connection, loan_id: int) -> Loan:
    found = next((loan for loan in load(conn) if loan.id == loan_id), None)
    if found is None:
        raise LookupError(loan_id)
    return found


def taken(conn: sqlite3.Connection) -> dict[str, int]:
    if not _has_tables(conn):
        return {}
    return {
        str(r[0]): int(r[1]) for r in conn.execute("SELECT fingerprint, loan_id FROM loan_links")
    }


def dismissed(conn: sqlite3.Connection) -> set[tuple[int, str]]:
    if not _has_tables(conn):
        return set()
    rows = conn.execute("SELECT loan_id, fingerprint FROM loan_dismissals")
    return {(int(r[0]), str(r[1])) for r in rows}


def _number(conn: sqlite3.Connection, typed: str, loan_id: int | None = None) -> str:
    number = loan_match.clean_number(typed)
    if not loan_match.MIN_LENGTH <= len(number) <= NUMBER_MAX:
        raise LinkError(t("analysis.loans.number_length", min=loan_match.MIN_LENGTH))
    for other_id, other in conn.execute("SELECT id, number FROM loans"):
        if int(other_id) != loan_id and loan_match.same_number(str(other), number):
            raise LinkError(t("analysis.loans.number_taken"))
    return number


def _check_contract(principal_cents: int, term: int) -> None:
    if principal_cents <= 0:
        raise LinkError(t("analysis.loans.principal_positive"))
    if not 1 <= term <= TERM_MAX:
        raise LinkError(t("analysis.loans.term_range", max=TERM_MAX))


def _check_rate(rate_bp: int) -> None:
    if not 0 <= rate_bp <= RATE_MAX_BP:
        raise LinkError(t("analysis.loans.rate_range"))


def create(
    conn: sqlite3.Connection,
    *,
    name: str,
    number: str,
    currency: str,
    principal_cents: int,
    rate_bp: int,
    term: int,
    start: date,
    now: str,
    installment_cents: int | None = None,
) -> int:
    """A new loan with its contract; its rate (and the bank's installment, if given) is in
    force from the start."""
    clean = _number(conn, number)
    _check_contract(principal_cents, term)
    _check_rate(rate_bp)
    cursor = conn.execute(
        "INSERT INTO loans (name, number, currency, principal_cents, term, start_date, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ledger_store.clean_name(name, limit=NAME_MAX),
            clean,
            currency,
            principal_cents,
            term,
            start.isoformat(),
            now,
            now,
        ),
    )
    loan_id = int(cursor.lastrowid or 0)
    set_rate(conn, loan_id, start, rate_bp)
    if installment_cents is not None:
        set_installment(conn, loan_id, start, installment_cents)
    return loan_id


def update(
    conn: sqlite3.Connection,
    loan_id: int,
    now: str,
    *,
    name: str | None = None,
    number: str | None = None,
    principal_cents: int | None = None,
    term: int | None = None,
    start: date | None = None,
) -> None:
    """A new name, number (the automatic links go; `reconcile` finds the new ones) or contract.
    A new start date moves the starting rate (and the bank's installment from the start) with
    it; never past a later rate change."""
    found = plan(conn, loan_id)
    if principal_cents is not None or term is not None:
        _check_contract(
            principal_cents if principal_cents is not None else cents_of(found.contract.principal),
            term if term is not None else found.contract.term,
        )
    changes: dict[str, object] = {}
    if name is not None:
        changes["name"] = ledger_store.clean_name(name, limit=NAME_MAX)
    if number is not None:
        clean = _number(conn, number, loan_id)
        if clean != found.number:
            changes["number"] = clean
            conn.execute(
                "DELETE FROM loan_links WHERE loan_id = ? AND origin = 'automatic'", (loan_id,)
            )
    if principal_cents is not None:
        changes["principal_cents"] = principal_cents
    if term is not None:
        changes["term"] = term
    if start is not None and start != found.contract.start:
        if any(found.contract.start < r.effective <= start for r in found.rates):
            raise LinkError(t("analysis.loans.start_after_rate"))
        changes["start_date"] = start.isoformat()
        conn.execute(
            "UPDATE loan_rates SET effective = ? WHERE loan_id = ? AND effective = ?",
            (start.isoformat(), loan_id, found.contract.start.isoformat()),
        )
        if not any(found.contract.start < i.effective <= start for i in found.installments):
            conn.execute(
                "UPDATE loan_installments SET effective = ? WHERE loan_id = ? AND effective = ?",
                (start.isoformat(), loan_id, found.contract.start.isoformat()),
            )
    changes["updated_at"] = now
    columns = ", ".join(f"{column} = ?" for column in changes)
    conn.execute(f"UPDATE loans SET {columns} WHERE id = ?", (*changes.values(), loan_id))  # noqa: S608 (fixed column names)


def delete(conn: sqlite3.Connection, loan_id: int) -> None:
    """The loan and what hangs from it; the payments stay as they are."""
    plan(conn, loan_id)
    conn.execute("DELETE FROM loans WHERE id = ?", (loan_id,))


def set_rate(conn: sqlite3.Connection, loan_id: int, effective: date, rate_bp: int) -> None:
    _check_rate(rate_bp)
    conn.execute(
        "INSERT INTO loan_rates (loan_id, effective, rate_bp) VALUES (?, ?, ?) "
        "ON CONFLICT (loan_id, effective) DO UPDATE SET rate_bp = excluded.rate_bp",
        (loan_id, effective.isoformat(), rate_bp),
    )


def delete_rate(conn: sqlite3.Connection, loan_id: int, effective: date) -> None:
    """A rate change; the starting rate (the contract's) stays."""
    found = plan(conn, loan_id)
    if effective <= found.contract.start:
        raise LinkError(t("analysis.loans.starting_rate"))
    conn.execute(
        "DELETE FROM loan_rates WHERE loan_id = ? AND effective = ?",
        (loan_id, effective.isoformat()),
    )


def set_installment(
    conn: sqlite3.Connection, loan_id: int, effective: date, installment_cents: int
) -> None:
    """What the bank charges each month from `effective` on (replaces that day's)."""
    if not 0 < installment_cents <= INSTALLMENT_MAX_CENTS:
        raise LinkError(t("analysis.loans.installment_positive"))
    conn.execute(
        "INSERT INTO loan_installments (loan_id, effective, installment_cents) VALUES (?, ?, ?) "
        "ON CONFLICT (loan_id, effective) DO UPDATE SET "
        "installment_cents = excluded.installment_cents",
        (loan_id, effective.isoformat(), installment_cents),
    )


def delete_installment(conn: sqlite3.Connection, loan_id: int, effective: date) -> None:
    conn.execute(
        "DELETE FROM loan_installments WHERE loan_id = ? AND effective = ?",
        (loan_id, effective.isoformat()),
    )


def set_balance(conn: sqlite3.Connection, loan_id: int, day: date, balance_cents: int) -> None:
    if balance_cents < 0:
        raise LinkError(t("analysis.loans.balance_negative"))
    conn.execute(
        "INSERT INTO loan_balances (loan_id, day, balance_cents) VALUES (?, ?, ?) "
        "ON CONFLICT (loan_id, day) DO UPDATE SET balance_cents = excluded.balance_cents",
        (loan_id, day.isoformat(), balance_cents),
    )


def delete_balance(conn: sqlite3.Connection, loan_id: int, day: date) -> None:
    conn.execute(
        "DELETE FROM loan_balances WHERE loan_id = ? AND day = ?", (loan_id, day.isoformat())
    )


def add_statement_lines(
    conn: sqlite3.Connection,
    loan_id: int,
    lines: Iterable[StatementLine],
    document: str | None,
    now: str,
) -> int:
    """Store a loan statement's payments (the same line again is ignored); how many are new."""
    plan(conn, loan_id)
    added = 0
    for line in lines:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO loan_statement_lines (loan_id, day, principal_cents, "
            "interest_cents, other_cents, balance_cents, document, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                loan_id,
                line.day.isoformat(),
                cents_of(line.principal),
                cents_of(line.interest),
                cents_of(line.other),
                cents_of(line.balance),
                document,
                now,
            ),
        )
        added += cursor.rowcount
    return added


def payment_amount(move: Movement) -> Decimal:
    """What left the account (for a shared one, the statement amount)."""
    return move.gross if move.gross is not None else move.amount


def can_be_payment(move: Movement, loan: Loan) -> bool:
    """A charge from a statement (a provisional changes fingerprint), not an exchange or an
    investment, in the loan's currency, for a positive amount."""
    return (
        not move.provisional
        and move.link not in ("exchange", "investment")
        and bool(move.fingerprint)
        and move.currency == loan.currency
        and payment_amount(move) > 0
    )


def link(conn: sqlite3.Connection, loan_id: int, move: Movement, now: str) -> None:
    """ "It is a payment of this loan", whatever its description."""
    loan = plan(conn, loan_id)
    if not can_be_payment(move, loan):
        raise LinkError(t("analysis.loans.not_a_payment"))
    owner = taken(conn).get(move.fingerprint)
    if owner is not None and owner != loan_id:
        raise LinkError(t("analysis.loans.payment_taken"))
    conn.execute(
        "INSERT INTO loan_links (loan_id, fingerprint, origin, linked_at) "
        "VALUES (?, ?, 'confirmed', ?) "
        "ON CONFLICT (loan_id, fingerprint) DO UPDATE SET origin = 'confirmed'",
        (loan_id, move.fingerprint, now),
    )
    conn.execute(
        "DELETE FROM loan_dismissals WHERE loan_id = ? AND fingerprint = ?",
        (loan_id, move.fingerprint),
    )


def unlink(conn: sqlite3.Connection, loan_id: int, fingerprint: str, now: str) -> None:
    """It is not a payment of this loan: the link goes and it is not linked again."""
    plan(conn, loan_id)
    conn.execute(
        "DELETE FROM loan_links WHERE loan_id = ? AND fingerprint = ?", (loan_id, fingerprint)
    )
    conn.execute(
        "INSERT OR IGNORE INTO loan_dismissals (loan_id, fingerprint, dismissed_at) "
        "VALUES (?, ?, ?)",
        (loan_id, fingerprint, now),
    )


def reconcile(conn: sqlite3.Connection, flow: Sequence[Movement], now: str) -> int:
    """Link every charge whose description has a loan's number; how many were linked."""
    loans = load(conn)
    if not loans:
        return 0
    busy = taken(conn)
    refused = dismissed(conn)
    added = 0
    for move in flow:
        if move.fingerprint in busy:
            continue
        for loan in loans:
            if (loan.id, move.fingerprint) in refused or not can_be_payment(move, loan):
                continue
            if loan_match.mentions(move.description, loan.number):
                conn.execute(
                    "INSERT INTO loan_links (loan_id, fingerprint, origin, linked_at) "
                    "VALUES (?, ?, 'automatic', ?)",
                    (loan.id, move.fingerprint, now),
                )
                busy[move.fingerprint] = loan.id
                added += 1
                break
    return added


def reconcile_stored(conn: sqlite3.Connection, now: str) -> int:
    """`reconcile` against the whole flow as stored, loaded only if there is a loan. For the
    places that store statements outside a board request (the sync, the forwarding inbox)."""
    from michelito.analysis import spending  # noqa: PLC0415 (it loads every analysis module)

    if not load(conn):
        return 0
    return reconcile(conn, spending.load_all(conn), now)
