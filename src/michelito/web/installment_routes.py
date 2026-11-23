"""Routes of installment plans ("Plan de cuotas").

- `GET /api/installments`: every plan's card.
- `GET /api/transactions/{fingerprint}/installment-draft`: "It is an installment…" prefilled
  from a charge: amount, card, a name and which installment it seems to be (the earlier ones
  paid in a row before it).
- `POST /api/installments`: the plan, from a charge; the charge and the other exact ones (the
  earlier ones too) are linked at once, and a member's installments go into their group.
- `DELETE /api/installments/{id}`: the plan and the group expenses it recorded.
- `PUT /api/installments/{id}/transactions/{fingerprint}` (`{"number": n}`): "it is installment
  n" for an off-script charge; `DELETE` on the same path: "it is not part of the plan".

Each one is a change-log entry on the transaction (or the plan), so it can be undone.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from michelito.analysis import accounts as account_data
from michelito.analysis import changelog, installment_match, installment_store, ledger_store
from michelito.analysis.links import LinkError
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.migrations_v25 import COUNT_MAX, NAME_MAX
from michelito.web import edit_log
from michelito.web import installments as view

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
LOG_KIND = "installment"
Count = Annotated[int, Field(ge=2, le=COUNT_MAX)]
Number = Annotated[int, Field(ge=1, le=COUNT_MAX)]


class InstallmentOut(BaseModel):
    number: int
    month: str
    state: view.State
    fingerprint: str | None


class PlanOut(BaseModel):
    id: int
    name: str
    account_label: str
    amount_cents: int
    currency: str
    count: int
    paid: int
    remaining_cents: int
    first_month: str
    last_month: str
    group_id: int | None
    contact_id: int | None
    group_name: str | None
    contact_name: str | None
    receipt_id: int | None
    missing: list[int]
    installments: list[InstallmentOut]

    @classmethod
    def of(cls, v: view.PlanView) -> PlanOut:
        plan = v.plan
        return cls(
            id=plan.id,
            name=plan.name,
            account_label=v.account_label,
            amount_cents=plan.amount_cents,
            currency=plan.currency,
            count=plan.count,
            paid=v.paid,
            remaining_cents=v.remaining_cents,
            first_month=plan.first_month,
            last_month=plan.last_month,
            group_id=plan.group_id,
            contact_id=plan.contact_id,
            group_name=v.group_name,
            contact_name=v.contact_name,
            receipt_id=plan.receipt_id,
            missing=list(v.missing),
            installments=[
                InstallmentOut(
                    number=i.number, month=i.month, state=i.state, fingerprint=i.fingerprint
                )
                for i in v.installments
            ],
        )


class DraftOut(BaseModel):
    fingerprint: str
    name: str
    account_label: str
    amount_cents: int
    currency: str
    month: str
    number: int  # which installment it seems to be
    paid_before: int  # the earlier installments found in a row


class PlanBody(BaseModel):
    fingerprint: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=NAME_MAX)
    count: Count
    number: Number | None = None  # by default, the draft's
    group_id: int | None = None
    contact_id: int | None = None


class LinkBody(BaseModel):
    number: Number


def _charge(flow: Sequence[Movement], fingerprint: str) -> Movement:
    found = next((m for m in flow if m.fingerprint == fingerprint), None)
    if found is None:
        raise HTTPException(404, t("web.unknown_transaction"))
    return found


def _earlier(flow: Sequence[Movement], move: Movement) -> list[str]:
    chosen = installment_store.charge_of(move)
    return installment_match.earlier_in_a_row(installment_store.charges(flow), chosen)


def _name(move: Movement) -> str:
    """A starting name: the merchant (data, not interface text)."""
    return (move.merchant or move.description)[:NAME_MAX].strip() or move.description[:NAME_MAX]


def register(app: FastAPI, connection: Connection, load_flow: LoadFlow) -> None:
    @contextmanager
    def tracked(
        conn: sqlite3.Connection, move: Movement, before: str, after: str
    ) -> Iterator[None]:
        try:
            with (
                conn,
                changelog.track(
                    conn,
                    LOG_KIND,
                    "transaction",
                    move.fingerprint,
                    edit_log.subject(move),
                    before=before,
                    after=after,
                    merchant=move.merchant,
                    fingerprints=[move.fingerprint],
                ),
            ):
                yield
        except LinkError as error:
            raise HTTPException(409, str(error)) from None
        except LookupError:
            raise HTTPException(404, t("web.installments.unknown")) from None

    def plan_out(conn: sqlite3.Connection, plan_id: int) -> PlanOut:
        flow = load_flow(conn)
        found = next(
            (
                v
                for v in view.views(conn, flow, account_data.account_infos(conn))
                if v.plan.id == plan_id
            ),
            None,
        )
        if found is None:
            raise HTTPException(404, t("web.installments.unknown"))
        return PlanOut.of(found)

    def plan_of(conn: sqlite3.Connection, plan_id: int) -> installment_store.Plan:
        found = next((p for p in installment_store.load(conn) if p.id == plan_id), None)
        if found is None:
            raise HTTPException(404, t("web.installments.unknown"))
        return found

    def label(plan_name: str, number: int | None = None) -> str:
        if number is None:
            return t("web.installments.log_plan", name=plan_name)
        return t("web.installments.log_number", name=plan_name, number=number)

    @app.get("/api/installments")
    def get_plans() -> list[PlanOut]:
        with connection() as conn:
            flow = load_flow(conn)
            return [PlanOut.of(v) for v in view.views(conn, flow, account_data.account_infos(conn))]

    @app.get("/api/transactions/{fingerprint}/installment-draft")
    def get_draft(fingerprint: str) -> DraftOut:
        with connection() as conn:
            flow = load_flow(conn)
            move = _charge(flow, fingerprint)
            earlier = _earlier(flow, move)
            labels = {i.key: i.label for i in account_data.account_infos(conn)}
        charge = installment_store.charge_of(move)
        return DraftOut(
            fingerprint=fingerprint,
            name=_name(move),
            account_label=labels.get(move.account, move.account),
            amount_cents=abs(charge.cents),
            currency=move.currency,
            month=move.month,
            number=len(earlier),
            paid_before=len(earlier) - 1,
        )

    @app.post("/api/installments", status_code=201)
    def post_plan(body: PlanBody) -> PlanOut:
        with connection() as conn:
            flow = load_flow(conn)
            move = _charge(flow, body.fingerprint)
            charge = installment_store.charge_of(move)
            matcher = installment_match.matcher_of(move.description)
            if not installment_store.can_be_installment(move) or not matcher:
                raise HTTPException(409, t("web.installments.not_a_charge"))
            if body.contact_id is not None and body.contact_id == ledger_store.me_id(conn):
                raise HTTPException(409, t("analysis.installments.not_a_member"))
            if move.fingerprint in installment_store.taken(conn):
                raise HTTPException(409, t("analysis.installments.charge_taken"))
            number = body.number if body.number is not None else len(_earlier(flow, move))
            if number > body.count:
                raise HTTPException(422, t("web.installments.number_over_count"))
            now = changelog.now().isoformat()
            with tracked(conn, move, t("web.installments.none"), label(body.name.strip())):
                plan_id = installment_store.create(
                    conn,
                    name=body.name,
                    account=move.account,
                    matcher=matcher,
                    amount_cents=charge.cents,
                    currency=move.currency,
                    count=body.count,
                    first_month=installment_match.month_of_number(move.month, 2 - number),
                    now=now,
                    group_id=body.group_id,
                    contact_id=body.contact_id,
                )
                installment_store.confirm(conn, plan_id, move, number, now)
                installment_store.reconcile(conn, flow, now)
            return plan_out(conn, plan_id)

    @app.delete("/api/installments/{plan_id}", status_code=204)
    def delete_plan(plan_id: int) -> Response:
        with connection() as conn:
            plan = plan_of(conn, plan_id)
            flow = load_flow(conn)
            anchor = next((m for m in flow if m.fingerprint in plan.links.values()), None)
            if anchor is None:
                with (
                    conn,
                    changelog.track(conn, LOG_KIND, "link", f"installment-{plan_id}", plan.name),
                ):
                    installment_store.delete(conn, plan_id)
            else:
                with tracked(conn, anchor, label(plan.name), t("web.installments.none")):
                    installment_store.delete(conn, plan_id)
        return Response(status_code=204)

    @app.put("/api/installments/{plan_id}/transactions/{fingerprint}")
    def put_link(plan_id: int, fingerprint: str, body: LinkBody) -> PlanOut:
        with connection() as conn:
            plan = plan_of(conn, plan_id)
            move = _charge(load_flow(conn), fingerprint)
            now = changelog.now().isoformat()
            with tracked(conn, move, t("web.installments.none"), label(plan.name, body.number)):
                installment_store.confirm(conn, plan_id, move, body.number, now)
            return plan_out(conn, plan_id)

    @app.delete("/api/installments/{plan_id}/transactions/{fingerprint}")
    def delete_link(plan_id: int, fingerprint: str) -> PlanOut:
        with connection() as conn:
            plan = plan_of(conn, plan_id)
            move = _charge(load_flow(conn), fingerprint)
            number = next((n for n, fp in plan.links.items() if fp == fingerprint), None)
            now = changelog.now().isoformat()
            with tracked(conn, move, label(plan.name, number), t("web.installments.none")):
                installment_store.unlink(conn, plan_id, fingerprint, now)
            return plan_out(conn, plan_id)
