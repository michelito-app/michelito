"""Shared routes (the ledger): home, contacts, groups, entries and payments.

Every write goes through the change log (`changelog.track`, target type "link", target
`group-<id>` or `contact-<id>`), so it shows in the log with its author and can be undone.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Response

from michelito.analysis import accounts as account_data
from michelito.analysis import (
    changelog,
    ledger,
    ledger_cover,
    ledger_store,
    ledger_suggest,
    links,
    rates,
    shared,
)
from michelito.analysis.links import AlreadyLinked, LinkError
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web import ledger_credit_routes, ledger_view
from michelito.web import links as links_view
from michelito.web.ledger_schemas import (
    AfterOut,
    AliasBody,
    AllocationsBody,
    ContactBody,
    ContactOut,
    ContactPatchBody,
    ContactsOut,
    CoverBody,
    CoverPaymentOut,
    CoverPlanOut,
    DismissCoverBody,
    DismissCoversBody,
    EntryBody,
    GroupBody,
    GroupOut,
    GroupPatchBody,
    LeftoverBody,
    MemberBody,
    MemberUsageOut,
    MergeBody,
    NewPerson,
    PaymentBody,
    PaymentPatchBody,
    PersonOut,
    ProposalOut,
    ProposedOut,
    ShareBody,
    SharedHomeOut,
    SplitOut,
    UsedInOut,
    WriteOffBody,
    money,
)
from michelito.web.schemas import CandidateOut, CurrencyCentsOut, LinkedTxOut, to_cents

Connection = Callable[[], AbstractContextManager[sqlite3.Connection]]
LoadFlow = Callable[[sqlite3.Connection], Sequence[Movement]]
ParseAccounts = Callable[[str | None, Sequence[account_data.AccountInfo]], frozenset[str] | None]
AccountKeys = Annotated[str | None, Query(max_length=2000)]
_CANDIDATE_LIMIT = 30
CoverList = Annotated[str, Query(max_length=500, pattern=r"^[0-9,]*$")]


def _unique(allocations: Sequence[ShareBody]) -> list[tuple[int, Decimal]]:
    """The allocations as (person, amount); the same person twice is refused (a dict would
    keep the last one silently)."""
    ids = [a.contact_id for a in allocations]
    if len(set(ids)) != len(ids):
        raise LinkError(t("analysis.ledger.allocation_twice"))
    return [(a.contact_id, Decimal(a.cents) / 100) for a in allocations]


def plan_out(
    book: ledger_view.Book,
    group: ledger.Group,
    found: ledger_cover.CoverSuggestion,
    plan: ledger_cover.CoverPlan,
) -> CoverPlanOut:
    after = []
    for member in group.members:
        balance = plan.after.person(member.contact_id)
        if member.contact_id == book.ledger.me or balance is None:
            continue
        after.append(
            AfterOut(
                contact_id=member.contact_id,
                name=book.name(member.contact_id),
                balance=money(balance.net),
                leftover=money(dict(balance.leftover)),
            )
        )
    payments = []
    for item in plan.payments:
        proposed = proposal_out(book, group, item.payment.currency, item.payment.day, item.proposal)
        payments.append(
            CoverPaymentOut(
                payment_id=item.payment.id,
                day=item.payment.day.isoformat(),
                amount_cents=to_cents(item.payment.settles),
                currency=item.payment.currency,
                allocations=proposed.allocations,
                rate=proposed.rate,
            )
        )
    return CoverPlanOut(
        text=ledger_view.cover_text(book.ledger, found), payments=payments, after=after
    )


def proposal_out(
    book: ledger_view.Book,
    group: ledger.Group,
    currency: str,
    day: date,
    found: ledger_cover.Proposal,
) -> ProposalOut:
    """The proposed allocations with what each one owed and, when their claims are in the
    other currency, the part converted at the payment month's rate."""
    other = "USD" if currency == "DOP" else "DOP"

    def equivalent(contact: int, value: Decimal) -> CurrencyCentsOut | None:
        if found.rate is None or value <= 0:
            return None
        if not any(contact in e.people and e.currency == other for e in group.entries):
            return None
        converted = ledger.convert(value, currency, other, day, book.rates)
        return (
            None
            if converted is None
            else CurrencyCentsOut(currency=other, cents=to_cents(converted))
        )

    return ProposalOut(
        currency=currency,
        allocations=[
            ProposedOut(
                contact_id=contact,
                name=book.name(contact),
                cents=to_cents(value),
                owed_cents=to_cents(found.owed.get(contact, Decimal(0))),
                equivalent=equivalent(contact, value),
            )
            for contact, value in found.parts
        ],
        rate=ledger_view.rate_out(found.rate),
    )


def load_book(
    conn: sqlite3.Connection, flow: Sequence[Movement], today: date | None = None
) -> ledger_view.Book:
    infos = account_data.account_infos(conn)
    by_month = rates.load(conn)
    book = ledger_store.load(conn)
    return ledger_view.Book(
        ledger=book,
        states=ledger.states(book, by_month),
        movements=flow,
        links=links.load(conn),
        labels={a.key: a.label for a in infos},
        rates=by_month,
        banks=frozenset(a.key for a in infos if a.kind in account_data.BANK_KINDS),
        today=today or date.today(),
    )


@contextmanager
def errors() -> Iterator[None]:
    try:
        yield
    except AlreadyLinked as exc:
        raise HTTPException(409, str(exc)) from None
    except LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc) or t("web.unknown_group")) from None


def _group_name(conn: sqlite3.Connection, group_id: int) -> str:
    row = conn.execute("SELECT name FROM ledger_groups WHERE id = ?", (group_id,)).fetchone()
    return t("web.ledger.group_number", id=group_id) if row is None else str(row[0])


def _contact_name(conn: sqlite3.Connection, contact_id: int) -> str:
    row = conn.execute("SELECT name FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    return t("web.ledger.contact_number", id=contact_id) if row is None else str(row[0])


def _day(text: str | None, default: date) -> date:
    if text is None:
        return default
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise HTTPException(422, t("web.ledger.invalid_day")) from None


def _splits(amount: Decimal, paid_by: int, body: EntryBody) -> tuple[ledger.Split, ...]:
    return ledger_store.build_splits(
        amount,
        paid_by,
        body.split,
        body.people,
        {s.contact_id: Decimal(s.cents) / 100 for s in body.shares},
        {p.contact_id: p.parts for p in body.parts},
    )


def usage_out(conn: sqlite3.Connection, group_id: int, contact_id: int) -> MemberUsageOut:
    """Where a person appears in a group (before "Remove"), with why they would stay and, for
    each expense they have a share in, how it would be split without them."""
    usage = ledger_store.member_usage(conn, group_id, contact_id)
    name = _contact_name(conn, contact_id)
    book = ledger_store.load(conn)
    group = book.group(group_id)
    preview = ledger_store.resplit_preview(conn, group_id, contact_id) if usage.shares else {}

    def plain(u: ledger_store.UsedIn) -> UsedInOut:
        return UsedInOut(
            id=u.id,
            day=u.day.isoformat(),
            description=u.description,
            amount_cents=to_cents(u.amount),
            currency=u.currency,
        )

    def item(u: ledger_store.UsedIn) -> UsedInOut:
        entry = None if group is None else group.entry(u.id)
        after = preview.get(u.id, ())
        payer = None if entry is None else entry.paid_by
        return UsedInOut(
            id=u.id,
            day=u.day.isoformat(),
            description=u.description,
            amount_cents=to_cents(u.amount),
            currency=u.currency,
            after=[
                SplitOut(
                    contact_id=s.contact_id,
                    name=book.name(s.contact_id),
                    is_me=s.contact_id == book.me,
                    cents=to_cents(s.share),
                    parts=s.parts,
                )
                for s in after
            ],
            to_payer=bool(after) and all(s.contact_id == payer for s in after),
            paid_by_name=book.name(payer),
            paid_by_me=payer == book.me,
        )

    return MemberUsageOut(
        contact_id=contact_id,
        name=name,
        shares=[item(u) for u in usage.shares],
        paid=[plain(u) for u in usage.paid],
        payments=[plain(u) for u in usage.payments],
        free=usage.free,
        resplittable=usage.resplittable,
        message="" if usage.free else ledger_store.usage_text(name, usage),
    )


def register(  # noqa: C901, PLR0915 (one closure per route, like `web.app`)
    app: FastAPI,
    connection: Connection,
    load_flow: LoadFlow,
    parse_accounts: ParseAccounts,
    today: Callable[[], date],
) -> None:
    @contextmanager
    def tracked(
        conn: sqlite3.Connection,
        kind: str,
        target: str,
        subject: str,
        fingerprints: Sequence[str] = (),
    ) -> Iterator[None]:
        with (
            errors(),
            conn,
            changelog.track(conn, kind, "link", target, subject, fingerprints=fingerprints),
        ):
            yield

    def group_response(conn: sqlite3.Connection, group_id: int) -> GroupOut:
        book = load_book(conn, load_flow(conn), today())
        found = ledger_view.group_out(book, group_id)
        if found is None:
            raise HTTPException(404, t("web.unknown_group"))
        return found

    def person_id(conn: sqlite3.Connection, person: NewPerson) -> int:
        if person.contact_id is not None:
            if (
                conn.execute("SELECT 1 FROM contacts WHERE id = ?", (person.contact_id,)).fetchone()
                is None
            ):
                raise LookupError(t("analysis.ledger.unknown_contact", id=person.contact_id))
            if person.alias:
                ledger_store.add_alias(conn, person.contact_id, person.alias)
            return person.contact_id
        if not person.name:
            raise LinkError(t("analysis.ledger.name_required"))
        return ledger_store.contact_for(conn, person.name, person.alias)

    # --- Reading ------------------------------------------------------------------------

    @app.get("/api/shared")
    def get_shared() -> SharedHomeOut:
        """People and groups with their balances (see `web.ledger_view.home`)."""
        with connection() as conn:
            book = load_book(conn, load_flow(conn), today())
        return ledger_view.home(book, today())

    @app.get("/api/shared/contacts")
    def get_contacts() -> ContactsOut:
        with connection() as conn:
            book = load_book(conn, load_flow(conn), today())
        return ledger_view.contacts(book)

    @app.get("/api/shared/people/{contact_id}")
    def get_person(contact_id: int) -> PersonOut:
        with connection() as conn:
            book = load_book(conn, load_flow(conn), today())
        found = ledger_view.person_out(book, contact_id)
        if found is None:
            raise HTTPException(404, t("analysis.ledger.unknown_contact", id=contact_id))
        return found

    @app.get("/api/shared/groups/{group_id}")
    def get_group(group_id: int) -> GroupOut:
        with connection() as conn:
            return group_response(conn, group_id)

    @app.get("/api/shared/expense-candidates")
    def get_expense_candidates(accounts: AccountKeys = None) -> list[CandidateOut]:
        """ "I paid it": recent expenses not in a group, likely ones first (`primary`)."""
        with connection() as conn:
            flow = load_flow(conn)
            book = load_book(conn, flow, today())
            selected = parse_accounts(accounts, account_data.account_infos(conn))
        found = ledger_suggest.expense_candidates(flow, book.links, today(), book.rates, selected)[
            :_CANDIDATE_LIMIT
        ]
        return [
            CandidateOut.ranked(links_view.linked_tx(c.move, book.labels), c.likely) for c in found
        ]

    @app.get("/api/shared/payment-candidates")
    def get_payment_candidates(
        contact_id: int,
        received: bool,
        amount_cents: Annotated[int, Query(gt=0)],
        day: str,
        currency: str = "DOP",
    ) -> list[LinkedTxOut]:
        """ "Is it in your bank yet?": up to 3 transactions for a payment (see `ledger_suggest`)."""
        with connection() as conn:
            flow = load_flow(conn)
            book = load_book(conn, flow, today())
        found = ledger_suggest.payment_candidates(
            flow,
            book.links,
            book.banks,
            received=received,
            amount=Decimal(amount_cents) / 100,
            currency=currency,
            day=_day(day, today()),
            contact=book.ledger.contacts.get(contact_id),
        )
        return [LinkedTxOut.of(links_view.linked_tx(m, book.labels)) for m in found]

    # --- Contacts -----------------------------------------------------------------------

    @app.post("/api/shared/contacts", status_code=201)
    def post_contact(body: ContactBody) -> ContactOut:
        with connection() as conn:
            with tracked(conn, "contact", "contact-new", body.name):
                found = ledger_store.contact_for(conn, body.name, body.alias)
            contact = ledger_store.load(conn).contacts[found]
        return ContactOut(
            id=contact.id, name=contact.name, is_me=False, aliases=list(contact.aliases)
        )

    @app.patch("/api/shared/contacts/{contact_id}")
    def patch_contact(contact_id: int, body: ContactPatchBody) -> ContactsOut:
        with connection() as conn:
            subject = _contact_name(conn, contact_id)
            with tracked(conn, "contact_rename", f"contact-{contact_id}", subject):
                ledger_store.rename_contact(conn, contact_id, body.name)
            return ledger_view.contacts(load_book(conn, load_flow(conn), today()))

    @app.post("/api/shared/contacts/{contact_id}/aliases")
    def post_alias(contact_id: int, body: AliasBody) -> ContactsOut:
        with connection() as conn:
            subject = _contact_name(conn, contact_id)
            with tracked(conn, "contact_alias", f"contact-{contact_id}", subject):
                ledger_store.add_alias(conn, contact_id, body.alias)
            return ledger_view.contacts(load_book(conn, load_flow(conn), today()))

    @app.delete("/api/shared/contacts/{contact_id}/aliases/{alias}")
    def delete_alias(contact_id: int, alias: str) -> ContactsOut:
        with connection() as conn:
            subject = _contact_name(conn, contact_id)
            with tracked(conn, "contact_alias", f"contact-{contact_id}", subject):
                ledger_store.remove_alias(conn, contact_id, alias)
            return ledger_view.contacts(load_book(conn, load_flow(conn), today()))

    @app.post("/api/shared/contacts/{contact_id}/merge")
    def post_merge(contact_id: int, body: MergeBody) -> ContactsOut:
        """`contact_id` becomes `into` everywhere (its name stays as an alias)."""
        with connection() as conn:
            subject = _contact_name(conn, contact_id)
            with tracked(conn, "contact_merge", f"contact-{body.into}", subject):
                ledger_store.merge_contacts(conn, contact_id, body.into)
            return ledger_view.contacts(load_book(conn, load_flow(conn), today()))

    @app.post("/api/shared/review-people/done", status_code=204)
    def post_review_done() -> Response:
        """ "Review your people" was seen: it is not offered again."""
        subject = t("web.ledger.review_people")
        with connection() as conn, tracked(conn, "review_people", "contact-all", subject):
            ledger_store.set_review_people(conn, False)
        return Response(status_code=204)

    # --- Groups -------------------------------------------------------------------------

    @app.post("/api/shared/groups", status_code=201)
    def post_group(body: GroupBody) -> GroupOut:
        with connection() as conn:
            with tracked(conn, "group_new", "group-new", body.name):
                people = [person_id(conn, p) for p in body.people]
                found = ledger_store.create_group(conn, body.name, people, body.category_id)
            return group_response(conn, found)

    @app.patch("/api/shared/groups/{group_id}")
    def patch_group(group_id: int, body: GroupPatchBody) -> GroupOut:
        given = body.model_fields_set
        with connection() as conn:
            with tracked(conn, "group", f"group-{group_id}", _group_name(conn, group_id)):
                ledger_store.update_group(
                    conn,
                    group_id,
                    name=body.name,
                    archived=body.archived,
                    category_id=body.category_id if "category_id" in given else ...,
                )
            return group_response(conn, group_id)

    @app.post("/api/shared/groups/{group_id}/members")
    def post_member(group_id: int, body: MemberBody) -> GroupOut:
        with connection() as conn:
            with tracked(conn, "group_member", f"group-{group_id}", _group_name(conn, group_id)):
                ledger_store.add_member(conn, group_id, person_id(conn, body))
            return group_response(conn, group_id)

    @app.get("/api/shared/groups/{group_id}/members/{contact_id}/usage")
    def get_member_usage(group_id: int, contact_id: int) -> MemberUsageOut:
        """Where the person appears in the group, before removing them."""
        with connection() as conn, errors():
            return usage_out(conn, group_id, contact_id)

    @app.delete("/api/shared/groups/{group_id}/members/{contact_id}")
    def delete_member(group_id: int, contact_id: int, resplit: bool = False) -> GroupOut:
        """Remove a person. With `resplit` someone who only has shares leaves those expenses
        too (each split again among the rest keeping its mode): one change, one undo."""
        with connection() as conn:
            kind = "group_member_resplit" if resplit else "group_member"
            with tracked(conn, kind, f"group-{group_id}", _group_name(conn, group_id)):
                ledger_store.remove_member(conn, group_id, contact_id, resplit=resplit)
            return group_response(conn, group_id)

    @app.post("/api/shared/groups/{group_id}/write-off")
    def post_write_off(group_id: int, body: WriteOffBody) -> GroupOut:
        """ "They won't pay me" for one person (or everyone left), or back."""
        with connection() as conn:
            with tracked(conn, "write_off", f"group-{group_id}", _group_name(conn, group_id)):
                ledger_store.set_written_off(conn, group_id, body.contact_id, body.written_off)
            return group_response(conn, group_id)

    # --- Entries ------------------------------------------------------------------------

    def entry_args(conn: sqlite3.Connection, group_id: int, body: EntryBody) -> dict:
        me = ledger_store.ensure_me(conn)
        if body.fingerprint is not None:
            flow = load_flow(conn)
            move = next((m for m in flow if m.fingerprint == body.fingerprint), None)
            if move is None:
                raise LookupError(t("web.unknown_transaction"))
            links_view.check_shareable(links.load(conn), move)
            amount = shared.gross(move)
            args: dict = {
                "paid_by": me,
                "amount": amount,
                "currency": move.currency,
                "day": move.day,
                "description": body.description or move.merchant or move.description,
                "fingerprint": move.fingerprint,
            }
        else:
            if body.amount_cents is None:
                raise LinkError(t("analysis.links.amount_positive"))
            if not body.description:
                raise LinkError(t("web.ledger.description_required"))
            amount = Decimal(body.amount_cents) / 100
            args = {
                "paid_by": body.paid_by if body.paid_by is not None else me,
                "amount": amount,
                "currency": body.currency,
                "day": _day(body.day, today()),
                "description": body.description,
            }
        group = conn.execute(
            "SELECT category_id FROM ledger_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if group is None:
            raise LookupError(t("analysis.links.unknown_group", id=group_id))
        args["category_id"] = body.category_id if body.category_id is not None else group[0]
        args["mode"] = body.split
        args["splits"] = _splits(amount, args["paid_by"], body)
        return args

    @app.post("/api/shared/groups/{group_id}/entries", status_code=201)
    def post_entry(group_id: int, body: EntryBody) -> GroupOut:
        fingerprints = [body.fingerprint] if body.fingerprint else []
        with connection() as conn:
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_entry", f"group-{group_id}", subject, fingerprints):
                ledger_store.add_entry(conn, group_id, **entry_args(conn, group_id, body))
            return group_response(conn, group_id)

    @app.put("/api/shared/entries/{entry_id}")
    def put_entry(entry_id: int, body: EntryBody) -> GroupOut:
        with connection() as conn, errors():
            group_id = ledger_store.entry_group(conn, entry_id)
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_entry", f"group-{group_id}", subject):
                linked = conn.execute(
                    "SELECT fingerprint FROM ledger_links WHERE entry_id = ?", (entry_id,)
                ).fetchone()
                stored = conn.execute(
                    "SELECT amount_cents, paid_by FROM ledger_entries WHERE id = ?", (entry_id,)
                ).fetchone()
                keep: dict = {}
                if linked is not None or body.amount_cents is None:  # the bank's, or unchanged
                    keep["amount_cents"] = int(stored[0])
                if linked is not None or body.paid_by is None:
                    keep["paid_by"] = int(stored[1])
                body = body.model_copy(update=keep)
                args = entry_args(conn, group_id, body.model_copy(update={"fingerprint": None}))
                if linked is not None:
                    args.update(_linked_fields(conn, load_flow(conn), str(linked[0]), body))
                    args["splits"] = _splits(args["amount"], args["paid_by"], body)
                kept = _kept_splits(conn, entry_id, body, args)
                if kept is not None:
                    args["splits"], args["mode"] = kept
                ledger_store.update_entry(
                    conn, entry_id, **{k: v for k, v in args.items() if k != "fingerprint"}
                )
            return group_response(conn, group_id)

    def _kept_splits(
        conn: sqlite3.Connection, entry_id: int, body: EntryBody, args: dict
    ) -> tuple[list, str] | None:
        """An equal split asked again with the same people, amount and payer keeps the stored
        shares (and mode): editing the description never moves a cent."""
        stored = next(
            (e for g in ledger_store.load(conn).groups for e in g.entries if e.id == entry_id),
            None,
        )
        if stored is None or body.split != "equal":
            return None
        same = (
            set(body.people) == set(stored.people)
            and args["amount"] == stored.amount
            and args["paid_by"] == stored.paid_by
        )
        return (list(stored.splits), stored.split_mode) if same else None

    def _linked_fields(
        conn: sqlite3.Connection, flow: Sequence[Movement], fingerprint: str, body: EntryBody
    ) -> dict:
        """A linked entry keeps the bank's amount, date and payer."""
        move = next((m for m in flow if m.fingerprint == fingerprint), None)
        row = conn.execute(
            "SELECT e.amount_cents, e.currency, e.day, e.paid_by FROM ledger_entries e "
            "JOIN ledger_links l ON l.entry_id = e.id WHERE l.fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        amount = Decimal(row[0]) / 100 if move is None else shared.gross(move)
        return {
            "amount": amount,
            "currency": row[1] if move is None else move.currency,
            "day": date.fromisoformat(row[2]) if move is None else move.day,
            "paid_by": int(row[3]),
            "description": body.description or (move.merchant if move else ""),
        }

    @app.delete("/api/shared/entries/{entry_id}")
    def delete_entry(entry_id: int) -> GroupOut:
        with connection() as conn, errors():
            group_id = ledger_store.entry_group(conn, entry_id)
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_entry_delete", f"group-{group_id}", subject):
                ledger_store.delete_entry(conn, entry_id)
            return group_response(conn, group_id)

    # --- Payments -----------------------------------------------------------------------

    def payment_tx(conn: sqlite3.Connection, fingerprint: str, received: bool) -> Movement:
        flow = load_flow(conn)
        move = next((m for m in flow if m.fingerprint == fingerprint), None)
        if move is None:
            raise LookupError(t("web.unknown_transaction"))
        infos = account_data.account_infos(conn)
        banks = {a.key for a in infos if a.kind in account_data.BANK_KINDS}
        links_view.check_payment_tx(links.load(conn), move, received, banks)
        return move

    @app.post("/api/shared/groups/{group_id}/payments", status_code=201)
    def post_payment(group_id: int, body: PaymentBody) -> GroupOut:
        """ "Record payment". With `fingerprint` the transaction reconciles it: for a payment
        received the credit is what was received (the amount given, if different, is what was
        sent); for one paid the debit is what was sent."""
        fingerprints = [body.fingerprint] if body.fingerprint else []
        with connection() as conn:
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_payment", f"group-{group_id}", subject, fingerprints):
                me = ledger_store.ensure_me(conn)
                amount = Decimal(body.amount_cents) / 100
                sent = None if body.sent_cents is None else Decimal(body.sent_cents) / 100
                if body.fingerprint is not None:
                    received = body.to_contact == me
                    move = payment_tx(conn, body.fingerprint, received)
                    if move.currency != body.currency:
                        raise LinkError(t("web.ledger.payment_currency"))
                    value = abs(move.amount)
                    if received:
                        amount, sent = value, (amount if amount != value else sent)
                    else:
                        sent = value if value != amount else None
                ledger_store.add_payment(
                    conn,
                    group_id,
                    from_contact=body.from_contact,
                    to_contact=body.to_contact,
                    amount=amount,
                    currency=body.currency,
                    day=_day(body.day, today()),
                    sent=sent,
                    fingerprint=body.fingerprint,
                    allocations=_allocations(body, amount),
                )
            return group_response(conn, group_id)

    def _allocations(body: PaymentBody, amount: Decimal) -> dict[int, Decimal] | None:
        """The allocations as given; when the bank's received amount differs from what was
        typed (they were typed to add up to it), they are fitted to it with the ledger's one
        rule (`ledger.fit_allocations`: the payer's own part first)."""
        if not body.allocations:
            return None
        given = _unique(body.allocations)
        if body.from_contact is None:
            raise LinkError(t("analysis.ledger.allocations_need_payer"))
        if amount == Decimal(body.amount_cents) / 100:  # as typed: they must add up (store)
            return dict(given)
        return dict(ledger.fit_allocations(given, body.from_contact, amount))

    @app.get("/api/shared/groups/{group_id}/allocation-proposal")
    def get_allocation_proposal(
        group_id: int,
        from_contact: int,
        amount_cents: Annotated[int, Query(gt=0, le=10**13)],
        day: str,
        currency: str = "DOP",
        covers: CoverList = "",
        payment_id: int | None = None,
    ) -> ProposalOut:
        """ "Also pays for…": the default allocations (`ledger_cover.propose_allocations`: the
        payer's own balance first, then each person in `covers` in that order) for a new
        payment, or for `payment_id` at its own position."""
        if currency not in ledger.CURRENCIES:
            raise HTTPException(422, t("analysis.links.currency_choice"))
        with connection() as conn:
            book = load_book(conn, load_flow(conn), today())
        group = book.ledger.group(group_id)
        if group is None:
            raise HTTPException(404, t("web.unknown_group"))
        if payment_id is not None and group.payment(payment_id) is None:
            raise HTTPException(404, t("analysis.ledger.unknown_payment", id=payment_id))
        when = _day(day, today())
        found = ledger_cover.propose_allocations(
            group,
            book.ledger.me,
            book.rates,
            payer=from_contact,
            amount=Decimal(amount_cents) / 100,
            currency=currency,
            day=when,
            covers=[int(c) for c in covers.split(",") if c],
            payment_id=payment_id,
        )
        return proposal_out(book, group, currency, when, found)

    @app.put("/api/shared/payments/{payment_id}/allocations")
    def put_allocations(payment_id: int, body: AllocationsBody) -> GroupOut:
        """ "Also paid for…" on a payment another person made to the user: replaces who it is
        for in one change (one undo); none given, all of it is the payer's again."""
        with connection() as conn, errors():
            group_id = ledger_store.payment_group(conn, payment_id)
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_payment", f"group-{group_id}", subject):
                ledger_store.set_allocations(conn, payment_id, dict(_unique(body.allocations)))
            return group_response(conn, group_id)

    @app.get("/api/shared/groups/{group_id}/cover-proposal")
    def get_cover_proposal(group_id: int) -> CoverPlanOut:
        """ "Yes" to the group's suggestion: each of its payments proposed in order (payer
        first, each counting what the previous ones covered) and the balances after."""
        with connection() as conn:
            book = load_book(conn, load_flow(conn), today())
        group = book.ledger.group(group_id)
        state = book.states.get(group_id)
        if group is None or state is None:
            raise HTTPException(404, t("web.unknown_group"))
        found = ledger_cover.cover_suggestion(state, book.ledger.me)
        if found is None:
            raise HTTPException(404, t("analysis.ledger.no_cover"))
        plan = ledger_cover.propose_cover(group, book.ledger.me, book.rates, found)
        return plan_out(book, group, found, plan)

    @app.put("/api/shared/groups/{group_id}/cover")
    def put_cover(group_id: int, body: CoverBody) -> GroupOut:
        """ "Yes" confirmed: every payment's allocations replaced in ONE change (one undo)."""
        with connection() as conn:
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_payment", f"group-{group_id}", subject):
                ids = [p.payment_id for p in body.payments]
                if len(set(ids)) != len(ids):
                    raise LinkError(t("analysis.ledger.allocation_twice"))
                ledger_store.require_payments_of(conn, group_id, ids)
                for item in body.payments:
                    given = dict(_unique(item.allocations))
                    ledger_store.set_allocations(conn, item.payment_id, given)
            return group_response(conn, group_id)

    @app.put("/api/shared/groups/{group_id}/cover-dismissed")
    def put_covers_dismissed(group_id: int, body: DismissCoversBody) -> GroupOut:
        """ "No" to the group's suggestion: kept for each of its payments, as one change."""
        with connection() as conn:
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_payment", f"group-{group_id}", subject):
                ledger_store.require_payments_of(conn, group_id, body.payment_ids)
                for payment_id in dict.fromkeys(body.payment_ids):
                    ledger_store.set_cover_dismissed(conn, payment_id, body.dismissed)
            return group_response(conn, group_id)

    @app.put("/api/shared/payments/{payment_id}/cover-dismissed")
    def put_cover_dismissed(payment_id: int, body: DismissCoverBody) -> GroupOut:
        """ "Was that payment for someone else too?" answered "No" (kept; undoable)."""
        with connection() as conn, errors():
            group_id = ledger_store.payment_group(conn, payment_id)
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_payment", f"group-{group_id}", subject):
                ledger_store.set_cover_dismissed(conn, payment_id, body.dismissed)
            return group_response(conn, group_id)

    @app.post("/api/shared/groups/{group_id}/exchange-leftover")
    def post_exchange_leftover(group_id: int, body: LeftoverBody) -> GroupOut:
        """Whether a person's exchange leftovers count as settled in the group."""
        with connection() as conn:
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_member", f"group-{group_id}", subject):
                ledger_store.set_leftover_settled(conn, group_id, body.contact_id, body.settled)
            return group_response(conn, group_id)

    @app.patch("/api/shared/payments/{payment_id}")
    def patch_payment(payment_id: int, body: PaymentPatchBody) -> GroupOut:
        """Assign an unattributed payment, accept the difference, link or unlink its
        transaction."""
        with connection() as conn, errors():
            group_id = ledger_store.payment_group(conn, payment_id)
            fingerprints = [body.fingerprint] if body.fingerprint else []
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_payment", f"group-{group_id}", subject, fingerprints):
                if body.from_contact is not None:
                    ledger_store.assign_payment(conn, payment_id, body.from_contact)
                if body.accepted is not None:
                    ledger_store.update_payment(conn, payment_id, accepted=body.accepted)
                if body.unlink:
                    row = conn.execute(
                        "SELECT fingerprint FROM ledger_links WHERE payment_id = ?", (payment_id,)
                    ).fetchone()
                    if row is None:
                        raise LookupError(t("analysis.ledger.not_linked"))
                    ledger_store.unlink(conn, str(row[0]))
                if body.fingerprint is not None:
                    link_existing(conn, payment_id, body.fingerprint)
            return group_response(conn, group_id)

    def link_existing(conn: sqlite3.Connection, payment_id: int, fingerprint: str) -> None:
        me = ledger_store.ensure_me(conn)
        row = conn.execute(
            "SELECT to_contact, amount_cents, sent_cents, currency FROM ledger_payments "
            "WHERE id = ?",
            (payment_id,),
        ).fetchone()
        received = int(row[0]) == me
        move = payment_tx(conn, fingerprint, received)
        if move.currency != row[3]:
            raise LinkError(t("web.ledger.payment_currency"))
        value = abs(move.amount)
        current = Decimal(row[1]) / 100
        if received and value != current:
            ledger_store.update_payment(
                conn, payment_id, amount=value, sent=current if row[2] is None else ...
            )
        elif not received and value != current:
            ledger_store.update_payment(conn, payment_id, sent=value)
        ledger_store.link_payment(conn, payment_id, fingerprint)

    @app.delete("/api/shared/payments/{payment_id}")
    def delete_payment(payment_id: int) -> GroupOut:
        with connection() as conn, errors():
            group_id = ledger_store.payment_group(conn, payment_id)
            subject = _group_name(conn, group_id)
            with tracked(conn, "group_payment_delete", f"group-{group_id}", subject):
                ledger_store.delete_payment(conn, payment_id)
            return group_response(conn, group_id)

    ledger_credit_routes.register(
        app,
        connection,
        load_flow,
        today,
        ledger_credit_routes.Helpers(
            tracked, person_id, payment_tx, group_response, _day, load_book
        ),
    )
