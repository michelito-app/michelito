"""Routes of loans.

- `GET /api/loans`: every loan's card.
- `POST /api/loans`: a loan from its contract and number; every charge with the number is
  linked at once (earlier ones too).
- `PATCH /api/loans/{id}`: name, number (relinks) or contract. `DELETE`: the loan (the payments
  stay as they are).
- `PUT|DELETE /api/loans/{id}/rates/{effective}`: a rate from that day on.
- `PUT|DELETE /api/loans/{id}/balances/{day}`: the real balance on that day (from the bank).
- `PUT|DELETE /api/loans/{id}/transactions/{fingerprint}`: "it is a payment of this loan" / "it
  is not" (not linked again).
- `GET /api/loans/{id}/candidates`: recent charges in its currency, not in a loan, to link by
  hand (`q` filters by description).

Each change is a change-log entry, so it can be undone. No route changes spending: each payment
stays that month's expense.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from michelito.analysis import accounts as account_data
from michelito.analysis import changelog, loan_store
from michelito.analysis.links import LinkError
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.migrations_v26 import NAME_MAX, NUMBER_MAX, RATE_MAX_BP, TERM_MAX
from michelito.web import edit_log
from michelito.web import loans as view

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
Today = Callable[[], date]
LOG_KIND = "loan"
CANDIDATE_DAYS = 120
CANDIDATES_MAX = 60
Cents = Annotated[int, Field(gt=0, le=10**13)]
RateBp = Annotated[int, Field(ge=0, le=RATE_MAX_BP)]
Term = Annotated[int, Field(ge=1, le=TERM_MAX)]


def _cents(amount: Decimal) -> int:
    return loan_store.cents_of(amount)


def _bp(annual: Decimal) -> int:
    """A percent rate in hundredths of a percent (12.5 -> 1250)."""
    return loan_store.cents_of(annual)


class RateOut(BaseModel):
    effective: str
    rate_bp: int


class BalanceOut(BaseModel):
    day: str
    balance_cents: int


class RowOut(BaseModel):
    number: int
    due: str
    payment_cents: int
    interest_cents: int
    principal_cents: int
    other_cents: int
    balance_cents: int
    rate_bp: int
    source: Literal["contract", "statement"]


class PaymentOut(BaseModel):
    fingerprint: str
    day: str
    description: str
    account_label: str
    amount_cents: int
    origin: str


class DifferenceOut(BaseModel):
    kind: Literal["payments", "contract"]
    month: str
    expected_cents: int
    found_cents: int
    fingerprints: list[str]


class LoanOut(BaseModel):
    id: int
    name: str
    number: str
    currency: str
    principal_cents: int
    term: int
    start_date: str
    rate_bp: int  # in force today
    rates: list[RateOut]
    balances: list[BalanceOut]
    balance_cents: int  # today
    paid_cents: int  # the linked payments
    interest_statements_cents: int  # interest paid per the loan statements
    interest_estimated_cents: int  # ... and estimated from the contract (months without one)
    installments_left: int
    next_due: str | None
    next_payment_cents: int | None
    end_date: str | None
    statement_months: int
    payments: list[PaymentOut]
    differences: list[DifferenceOut]
    schedule: list[RowOut]

    @classmethod
    def of(cls, v: view.LoanView) -> LoanOut:
        loan, found = v.loan, v.summary
        upcoming = found.next_payment
        return cls(
            id=loan.id,
            name=loan.name,
            number=loan.number,
            currency=loan.currency,
            principal_cents=_cents(loan.contract.principal),
            term=loan.contract.term,
            start_date=loan.contract.start.isoformat(),
            rate_bp=_bp(v.rate),
            rates=[
                RateOut(effective=r.effective.isoformat(), rate_bp=_bp(r.annual))
                for r in loan.rates
            ],
            balances=[
                BalanceOut(day=a.day.isoformat(), balance_cents=_cents(a.balance))
                for a in loan.anchors
            ],
            balance_cents=_cents(found.balance),
            paid_cents=_cents(v.paid),
            interest_statements_cents=_cents(found.interest_from_statements),
            interest_estimated_cents=_cents(found.interest_estimated),
            installments_left=found.installments_left,
            next_due=None if upcoming is None else upcoming.due.isoformat(),
            next_payment_cents=None if upcoming is None else _cents(upcoming.payment),
            end_date=None if found.end is None else found.end.isoformat(),
            statement_months=len({line.day.strftime("%Y-%m") for line in loan.statement_lines}),
            payments=[
                PaymentOut(
                    fingerprint=p.fingerprint,
                    day=p.day.isoformat(),
                    description=p.description,
                    account_label=p.account_label,
                    amount_cents=_cents(p.amount),
                    origin=p.origin,
                )
                for p in v.payments
            ],
            differences=[
                DifferenceOut(
                    kind=d.kind,
                    month=d.month,
                    expected_cents=_cents(d.expected),
                    found_cents=_cents(d.found),
                    fingerprints=list(d.fingerprints),
                )
                for d in v.differences
            ],
            schedule=[
                RowOut(
                    number=r.number,
                    due=r.due.isoformat(),
                    payment_cents=_cents(r.payment),
                    interest_cents=_cents(r.interest),
                    principal_cents=_cents(r.principal),
                    other_cents=_cents(r.other),
                    balance_cents=_cents(r.balance),
                    rate_bp=_bp(r.rate),
                    source=r.source,
                )
                for r in found.rows
            ],
        )


class CandidateOut(BaseModel):
    fingerprint: str
    day: str
    description: str
    account_label: str
    amount_cents: int


Name = Annotated[str, Field(min_length=1, max_length=NAME_MAX)]
Number = Annotated[str, Field(min_length=1, max_length=NUMBER_MAX)]


class LoanBody(BaseModel):
    name: Name
    number: Number
    currency: Literal["DOP", "USD"] = "DOP"
    principal_cents: Cents
    rate_bp: RateBp
    term: Term
    start_date: date


class EditBody(BaseModel):
    name: Name | None = None
    number: Number | None = None
    principal_cents: Cents | None = None
    term: Term | None = None
    start_date: date | None = None


class RateBody(BaseModel):
    rate_bp: RateBp


class BalanceBody(BaseModel):
    balance_cents: Annotated[int, Field(ge=0, le=10**13)]


def _movement(flow: Sequence[Movement], fingerprint: str) -> Movement:
    found = next((m for m in flow if m.fingerprint == fingerprint), None)
    if found is None:
        raise HTTPException(404, t("web.unknown_transaction"))
    return found


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow, today: Today) -> None:
    @contextmanager
    def tracked(
        conn: sqlite3.Connection,
        target_type: str,
        target: str,
        subject: str,
        *,
        before: str | None = None,
        after: str | None = None,
        move: Movement | None = None,
    ) -> Iterator[None]:
        try:
            with (
                conn,
                changelog.track(
                    conn,
                    LOG_KIND,
                    target_type,
                    target,
                    subject,
                    before=before,
                    after=after,
                    merchant=None if move is None else move.merchant,
                    fingerprints=() if move is None else [move.fingerprint],
                ),
            ):
                yield
        except LinkError as error:
            raise HTTPException(409, str(error)) from None
        except LookupError:
            raise HTTPException(404, t("web.loans.unknown")) from None

    def loan_of(conn: sqlite3.Connection, loan_id: int) -> loan_store.Loan:
        try:
            return loan_store.plan(conn, loan_id)
        except LookupError:
            raise HTTPException(404, t("web.loans.unknown")) from None

    def loan_out(conn: sqlite3.Connection, loan_id: int) -> LoanOut:
        loan = loan_of(conn, loan_id)
        flow = load_flow(conn)
        return LoanOut.of(view.view(loan, flow, account_data.account_infos(conn), today()))

    @contextmanager
    def on_loan(conn: sqlite3.Connection, loan: loan_store.Loan) -> Iterator[None]:
        with tracked(conn, "link", f"loan-{loan.id}", loan.name):
            yield

    @app.get("/api/loans")
    def get_loans() -> list[LoanOut]:
        with connection() as conn:
            flow = load_flow(conn)
            infos = account_data.account_infos(conn)
            return [LoanOut.of(v) for v in view.views(conn, flow, infos, today())]

    @app.post("/api/loans", status_code=201)
    def post_loan(body: LoanBody) -> LoanOut:
        with connection() as conn:
            flow = load_flow(conn)
            now = changelog.now().isoformat()
            with tracked(conn, "link", "loan-new", body.name.strip()):
                loan_id = loan_store.create(
                    conn,
                    name=body.name,
                    number=body.number,
                    currency=body.currency,
                    principal_cents=body.principal_cents,
                    rate_bp=body.rate_bp,
                    term=body.term,
                    start=body.start_date,
                    now=now,
                )
                loan_store.reconcile(conn, flow, now)
            return loan_out(conn, loan_id)

    @app.patch("/api/loans/{loan_id}")
    def patch_loan(loan_id: int, body: EditBody) -> LoanOut:
        with connection() as conn:
            loan = loan_of(conn, loan_id)
            flow = load_flow(conn)
            now = changelog.now().isoformat()
            with on_loan(conn, loan):
                loan_store.update(
                    conn,
                    loan_id,
                    now,
                    name=body.name,
                    number=body.number,
                    principal_cents=body.principal_cents,
                    term=body.term,
                    start=body.start_date,
                )
                loan_store.reconcile(conn, flow, now)
            return loan_out(conn, loan_id)

    @app.delete("/api/loans/{loan_id}", status_code=204)
    def delete_loan(loan_id: int) -> Response:
        with connection() as conn:
            loan = loan_of(conn, loan_id)
            with on_loan(conn, loan):
                loan_store.delete(conn, loan_id)
        return Response(status_code=204)

    @app.put("/api/loans/{loan_id}/rates/{effective}")
    def put_rate(loan_id: int, effective: date, body: RateBody) -> LoanOut:
        with connection() as conn:
            loan = loan_of(conn, loan_id)
            with on_loan(conn, loan):
                loan_store.set_rate(conn, loan_id, effective, body.rate_bp)
            return loan_out(conn, loan_id)

    @app.delete("/api/loans/{loan_id}/rates/{effective}")
    def delete_rate(loan_id: int, effective: date) -> LoanOut:
        with connection() as conn:
            loan = loan_of(conn, loan_id)
            with on_loan(conn, loan):
                loan_store.delete_rate(conn, loan_id, effective)
            return loan_out(conn, loan_id)

    @app.put("/api/loans/{loan_id}/balances/{day}")
    def put_balance(loan_id: int, day: date, body: BalanceBody) -> LoanOut:
        with connection() as conn:
            loan = loan_of(conn, loan_id)
            with on_loan(conn, loan):
                loan_store.set_balance(conn, loan_id, day, body.balance_cents)
            return loan_out(conn, loan_id)

    @app.delete("/api/loans/{loan_id}/balances/{day}")
    def delete_balance(loan_id: int, day: date) -> LoanOut:
        with connection() as conn:
            loan = loan_of(conn, loan_id)
            with on_loan(conn, loan):
                loan_store.delete_balance(conn, loan_id, day)
            return loan_out(conn, loan_id)

    @app.put("/api/loans/{loan_id}/transactions/{fingerprint}")
    def put_link(loan_id: int, fingerprint: str) -> LoanOut:
        with connection() as conn:
            loan = loan_of(conn, loan_id)
            move = _movement(load_flow(conn), fingerprint)
            now = changelog.now().isoformat()
            label = t("web.loans.log_payment", name=loan.name)
            with tracked(
                conn,
                "transaction",
                fingerprint,
                edit_log.subject(move),
                before=t("web.loans.none"),
                after=label,
                move=move,
            ):
                loan_store.link(conn, loan_id, move, now)
            return loan_out(conn, loan_id)

    @app.delete("/api/loans/{loan_id}/transactions/{fingerprint}")
    def delete_link(loan_id: int, fingerprint: str) -> LoanOut:
        with connection() as conn:
            loan = loan_of(conn, loan_id)
            move = _movement(load_flow(conn), fingerprint)
            now = changelog.now().isoformat()
            label = t("web.loans.log_payment", name=loan.name)
            with tracked(
                conn,
                "transaction",
                fingerprint,
                edit_log.subject(move),
                before=label,
                after=t("web.loans.none"),
                move=move,
            ):
                loan_store.unlink(conn, loan_id, fingerprint, now)
            return loan_out(conn, loan_id)

    @app.get("/api/loans/{loan_id}/candidates")
    def get_candidates(
        loan_id: int, q: Annotated[str | None, Field(max_length=80)] = None
    ) -> list[CandidateOut]:
        with connection() as conn:
            loan = loan_of(conn, loan_id)
            flow = load_flow(conn)
            busy = loan_store.taken(conn)
            labels = {i.key: i.label for i in account_data.account_infos(conn)}
        since = today() - timedelta(days=CANDIDATE_DAYS)
        needle = (q or "").strip().casefold()
        found = [
            m
            for m in flow
            if m.day >= since
            and m.fingerprint not in busy
            and loan_store.can_be_payment(m, loan)
            and needle in m.description.casefold()
        ]
        found.sort(key=lambda m: (m.day, m.fingerprint), reverse=True)
        return [
            CandidateOut(
                fingerprint=m.fingerprint,
                day=m.day.isoformat(),
                description=m.description,
                account_label=labels.get(m.account, m.account),
                amount_cents=_cents(loan_store.payment_amount(m)),
            )
            for m in found[:CANDIDATES_MAX]
        ]
