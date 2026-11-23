"""Routes of installment plans ("Plan de cuotas").

- `GET /api/installments`: every plan's card.
- `GET /api/transactions/{fingerprint}/installment-draft`: "It is an installment…" prefilled
  from a charge: amount, card, a name and which installment it seems to be (the earlier ones
  paid in a row before it).
- `POST /api/installments`: the plan, from a charge; the charge and the other exact ones (the
  earlier ones too) are linked at once, and a member's installments go into their group.
- `PATCH /api/installments/{id}`: a new name, number of installments or owner (the
  installments already recorded move between the user and the person's group).
- `DELETE /api/installments/{id}`: the plan and the group expenses it recorded.
- `PUT /api/installments/{id}/transactions/{fingerprint}` (`{"number": n}`): "it is installment
  n" for an off-script charge; `DELETE` on the same path: "it is not part of the plan".

Each one is a change-log entry on the transaction (or the plan), so it can be undone.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Collection, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from michelito.analysis import accounts as account_data
from michelito.analysis import (
    changelog,
    installment_match,
    installment_owner,
    installment_store,
    ledger_store,
)
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


class EarlierOut(BaseModel):
    fingerprint: str
    day: str
    description: str
    amount_cents: int
    number: int


class DraftOut(BaseModel):
    fingerprint: str
    name: str
    account_label: str
    amount_cents: int
    currency: str
    month: str
    number: int  # which installment it seems to be
    paid_before: int  # the earlier installments found in a row
    earlier: list[EarlierOut]  # those charges, oldest first, with the number each would be
    number_known: bool  # false: the card's data starts there, the number cannot be deduced
    suggested_contact_id: int | None  # the person the charge is already shared with


PersonName = Annotated[str, Field(min_length=1, max_length=NAME_MAX)]


class OwnerBody(BaseModel):
    """A person already known, or a new one by name; neither: the user's."""

    contact_id: int | None = None
    new_person: PersonName | None = None

    def owner(self) -> installment_owner.Owner:
        return installment_owner.Owner(self.contact_id, self.new_person)


class PlanBody(BaseModel):
    fingerprint: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=NAME_MAX)
    count: Count
    number: Number | None = None  # by default, the draft's
    earlier: list[str] | None = Field(default=None, max_length=COUNT_MAX)  # None: the draft's
    group_id: int | None = None
    contact_id: int | None = None
    new_person: PersonName | None = None


class EditBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    count: Count | None = None
    owner: OwnerBody | None = None  # absent: unchanged; {}: the user's


class LinkBody(BaseModel):
    number: Number


def _charge(flow: Sequence[Movement], fingerprint: str) -> Movement:
    found = next((m for m in flow if m.fingerprint == fingerprint), None)
    if found is None:
        raise HTTPException(404, t("web.unknown_transaction"))
    return found


def _earlier(flow: Sequence[Movement], move: Movement, taken: Collection[str] = ()) -> list[str]:
    """The charge and the identical ones in the months right before it (not already in a
    plan), oldest first."""
    chosen = installment_store.charge_of(move)
    free = [c for c in installment_store.charges(flow) if c.fingerprint not in taken]
    return installment_match.earlier_in_a_row(free, chosen)


def _number_known(flow: Sequence[Movement], move: Movement, chain: Sequence[Movement]) -> bool:
    """Earlier installments were found, or the card has movements the month before: either
    way the first one is in the data."""
    if len(chain) > 1:
        return True
    before = installment_match.month_of_number(move.month, 0)
    return any(m.account == move.account and m.month == before for m in flow)


def _numbers(
    flow: Sequence[Movement], move: Movement, body: PlanBody, taken: Collection[str]
) -> tuple[int, list[Movement], list[Movement]]:
    """Which installment the charge is, and the earlier charges checked and unchecked."""
    by_fp = {m.fingerprint: m for m in flow}
    chain = [by_fp[fp] for fp in _earlier(flow, move, taken)[:-1]]
    chosen = set(body.earlier) if body.earlier is not None else {m.fingerprint for m in chain}
    checked = [m for m in chain if m.fingerprint in chosen]
    unchecked = [m for m in chain if m.fingerprint not in chosen]
    if body.number is not None:
        number = body.number
    elif checked:
        number = installment_match.number_for(checked[0].month, move.month)
    else:
        number = 1
    return number, checked, unchecked


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
            earlier = _earlier(flow, move, installment_store.taken(conn))
            labels = {i.key: i.label for i in account_data.account_infos(conn)}
            suggested = installment_owner.suggested(conn, fingerprint)
        by_fp = {m.fingerprint: m for m in flow}
        chain = [by_fp[fp] for fp in earlier]
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
            earlier=[
                EarlierOut(
                    fingerprint=m.fingerprint,
                    day=m.day.isoformat(),
                    description=m.description,
                    amount_cents=abs(installment_store.charge_of(m).cents),
                    number=index + 1,
                )
                for index, m in enumerate(chain[:-1])
            ],
            number_known=_number_known(flow, move, chain),
            suggested_contact_id=suggested,
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
            taken = installment_store.taken(conn)
            if move.fingerprint in taken:
                raise HTTPException(409, t("analysis.installments.charge_taken"))
            number, checked, unchecked = _numbers(flow, move, body, taken)
            if number > body.count:
                raise HTTPException(422, t("web.installments.number_over_count"))
            now = changelog.now().isoformat()
            first_month = installment_match.month_of_number(move.month, 2 - number)
            with tracked(conn, move, t("web.installments.none"), label(body.name.strip())):
                group_id, contact_id = body.group_id, body.contact_id
                if group_id is None:
                    owner = installment_owner.Owner(body.contact_id, body.new_person)
                    group_id, contact_id = installment_owner.resolve(conn, owner, move.fingerprint)
                plan_id = installment_store.create(
                    conn,
                    name=body.name,
                    account=move.account,
                    matcher=matcher,
                    amount_cents=charge.cents,
                    currency=move.currency,
                    count=body.count,
                    first_month=first_month,
                    now=now,
                    group_id=group_id,
                    contact_id=contact_id,
                )
                installment_store.confirm(conn, plan_id, move, number, now)
                for earlier in checked:
                    n = installment_match.number_for(first_month, earlier.month)
                    if 1 <= n <= body.count and n != number:
                        installment_store.confirm(conn, plan_id, earlier, n, now)
                for earlier in unchecked:
                    installment_store.dismiss(conn, plan_id, earlier.fingerprint, now)
                installment_store.reconcile(conn, flow, now)
            return plan_out(conn, plan_id)

    @contextmanager
    def tracked_plan(
        conn: sqlite3.Connection,
        plan: installment_store.Plan,
        flow: Sequence[Movement],
        after: str,
    ) -> Iterator[None]:
        """A change to the whole plan, logged on one of its charges (or the plan itself)."""
        anchor = next((m for m in flow if m.fingerprint in plan.links.values()), None)
        if anchor is not None:
            with tracked(conn, anchor, label(plan.name), after):
                yield
            return
        try:
            with (
                conn,
                changelog.track(conn, LOG_KIND, "link", f"installment-{plan.id}", plan.name),
            ):
                yield
        except LinkError as error:
            raise HTTPException(409, str(error)) from None

    @app.delete("/api/installments/{plan_id}", status_code=204)
    def delete_plan(plan_id: int) -> Response:
        with connection() as conn:
            plan = plan_of(conn, plan_id)
            with tracked_plan(conn, plan, load_flow(conn), t("web.installments.none")):
                installment_store.delete(conn, plan_id)
        return Response(status_code=204)

    @app.patch("/api/installments/{plan_id}")
    def patch_plan(plan_id: int, body: EditBody) -> PlanOut:
        with connection() as conn:
            plan = plan_of(conn, plan_id)
            flow = load_flow(conn)
            now = changelog.now().isoformat()
            with tracked_plan(conn, plan, flow, label((body.name or plan.name).strip())):
                installment_store.update(conn, plan_id, now, name=body.name, count=body.count)
                if body.owner is not None:
                    anchor = next(iter(plan.links.values()), None)
                    group_id, contact_id = installment_owner.resolve(
                        conn, body.owner.owner(), anchor
                    )
                    installment_owner.set_owner(conn, plan_id, group_id, contact_id, flow)
            return plan_out(conn, plan_id)

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
