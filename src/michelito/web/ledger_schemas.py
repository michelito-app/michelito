"""JSON models of Shared (the ledger): money in whole cents, ISO dates.

Balances are from the user's point of view: positive, owed to the user; negative, the user owes.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from michelito.web.schemas import Currency, CurrencyCentsOut, LinkedTxOut, to_cents

Cents = Annotated[int, Field(gt=0, le=10**13)]
ShareCents = Annotated[int, Field(ge=0, le=10**13)]
Name = Annotated[str, Field(max_length=80)]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


def money(values: Mapping[str, Decimal]) -> list[CurrencyCentsOut]:
    """By currency, RD$ before US$, only non-zero."""
    return [
        CurrencyCentsOut(currency=c, cents=to_cents(v))
        for c, v in sorted(values.items())
        if to_cents(v) != 0
    ]


class ContactOut(BaseModel):
    id: int
    name: str
    is_me: bool
    aliases: list[str]


class BankNameOut(BaseModel):
    """A name seen in incoming transfers that is not a contact yet ("seen in your bank")."""

    name: str
    raw: str
    count: int
    last_day: str


class ContactsOut(BaseModel):
    contacts: list[ContactOut]  # the user first, then by name
    bank_names: list[BankNameOut]
    recent_payers: list[int]  # who paid recently (for "Paid by"), most recent first


class PersonGroupOut(BaseModel):
    group_id: int
    group_name: str
    archived: bool
    balance: list[CurrencyCentsOut]
    written_off: bool


class PersonOut(BaseModel):
    """A contact across groups (the Personas row and the person view)."""

    id: int
    name: str
    aliases: list[str]
    balance: list[CurrencyCentsOut]
    group_count: int
    groups: list[PersonGroupOut]


class GroupRowOut(BaseModel):
    id: int
    name: str
    archived: bool
    balance: list[CurrencyCentsOut]  # owed minus owing (do not show: it cancels people)
    owed_to_me: list[CurrencyCentsOut]  # what the people who owe the user add up to
    i_owe: list[CurrencyCentsOut]  # what the user owes the people they owe
    people: list[str]  # every member but the user
    last_day: str | None
    unattributed: int


class TotalOut(BaseModel):
    currency: str
    owed_to_me_cents: int
    i_owe_cents: int


class SuggestionOut(LinkedTxOut):
    """ "these dinners look shared": a transaction to split."""


class SharedHomeOut(BaseModel):
    totals: list[TotalOut]
    people: list[PersonOut]
    groups: list[GroupRowOut]
    review_people: bool  # "Review your people" (once, after the migration)
    suggestions: list[SuggestionOut]  # when there are no groups


class MemberOut(BaseModel):
    id: int
    name: str
    is_me: bool
    written_off: bool
    balance: list[CurrencyCentsOut]  # what they owe the user in this group (net)


class SplitOut(BaseModel):
    contact_id: int
    name: str
    is_me: bool
    cents: int
    parts: int | None = None  # a split by parts: their number of parts


SplitMode = Literal["equal", "exact", "parts"]


class EffectOut(BaseModel):
    """The entry's effect on the user: "owe" (debes), "lent" (prestaste) or "none"."""

    kind: Literal["owe", "lent", "none"]
    cents: int


class EntryOut(BaseModel):
    kind: Literal["entry"] = "entry"
    id: int
    day: str
    description: str
    amount_cents: int
    currency: str
    paid_by: int
    paid_by_name: str
    paid_by_me: bool
    category_id: int | None
    split: SplitMode
    splits: list[SplitOut]
    effect: EffectOut
    my_share_cents: int
    pending_cents: int  # still owed to the user for this entry
    written_off_cents: int
    debt_pending_cents: int  # what the user still owes for it
    transaction: LinkedTxOut | None  # the user's linked transaction


class AllocationOut(BaseModel):
    contact_id: int
    name: str
    is_me: bool
    cents: int


class PaymentOut(BaseModel):
    kind: Literal["payment"] = "payment"
    id: int
    day: str
    from_contact: int | None  # null: unattributed
    from_name: str
    to_contact: int
    to_name: str
    from_me: bool
    to_me: bool
    amount_cents: int  # received
    currency: str
    sent_cents: int | None
    difference_cents: int | None  # sent - received (null: unknown or equal)
    accepted: bool
    note: str
    excess_cents: int
    unconverted: bool
    transaction: LinkedTxOut | None
    # Who it is for ("Paid for others"), the principal first; one line when it is all theirs.
    allocations: list[AllocationOut] = Field(default_factory=list)


class UsedInOut(BaseModel):
    id: int
    day: str
    description: str
    amount_cents: int
    currency: str
    # An expense the person has a share in: how it would be split without them, and whether it
    # becomes the payer's alone (nobody else left: what the person owed for it is gone).
    after: list[SplitOut] = Field(default_factory=list)
    to_payer: bool = False
    paid_by_name: str = ""
    paid_by_me: bool = False


class MemberUsageOut(BaseModel):
    """Where a person appears in a group, before removing them (`resplittable`: only shares,
    so "Remove from N expense(s) and the group" applies; `message`: why else they stay)."""

    contact_id: int
    name: str
    shares: list[UsedInOut]
    paid: list[UsedInOut]
    payments: list[UsedInOut]
    free: bool
    resplittable: bool
    message: str


class GroupOut(BaseModel):
    id: int
    name: str
    archived: bool
    category_id: int | None
    members: list[MemberOut]  # the user first
    balance: list[CurrencyCentsOut]  # the group's net for the user
    owed_to_me: list[CurrencyCentsOut]
    i_owe: list[CurrencyCentsOut]
    excess: list[CurrencyCentsOut]
    unattributed: list[PaymentOut]
    timeline: list[EntryOut | PaymentOut]  # most recent first


# --- Requests -------------------------------------------------------------------------------


class NewPerson(BaseModel):
    """A person for a group: an existing contact or a new one (`alias`: as the bank prints it)."""

    contact_id: int | None = None
    name: Name | None = None
    alias: Name | None = None


class GroupBody(BaseModel):
    name: Name
    people: list[NewPerson] = Field(default_factory=list, max_length=50)
    category_id: int | None = None


class GroupPatchBody(BaseModel):
    name: Name | None = None
    archived: bool | None = None
    category_id: int | None = None


class MemberBody(NewPerson):
    pass


class WriteOffBody(BaseModel):
    contact_id: int | None = None  # null: everyone left
    written_off: bool


class ShareBody(BaseModel):
    contact_id: int
    cents: ShareCents


class PartsBody(BaseModel):
    contact_id: int
    parts: Annotated[int, Field(ge=1, le=999)]


class EntryBody(BaseModel):
    """An expense. With `fingerprint` ("I paid it") the amount, date and description come from
    the transaction and the user is the payer."""

    fingerprint: str | None = Field(default=None, max_length=200)
    paid_by: int | None = None
    amount_cents: Cents | None = None
    currency: Currency = "DOP"
    day: Day | None = None
    description: Annotated[str, Field(max_length=120)] | None = None
    category_id: int | None = None
    split: SplitMode = "equal"
    people: list[int] = Field(default_factory=list, max_length=50)  # equal
    shares: list[ShareBody] = Field(default_factory=list, max_length=50)  # exact
    parts: list[PartsBody] = Field(default_factory=list, max_length=50)  # parts


class PaymentBody(BaseModel):
    from_contact: int | None = None
    to_contact: int
    amount_cents: Cents
    currency: Currency = "DOP"
    day: Day
    sent_cents: Cents | None = None
    fingerprint: str | None = Field(default=None, max_length=200)
    # "Also pays for…": who it is for, adding up to `amount_cents` (the payer included).
    allocations: list[ShareBody] = Field(default_factory=list, max_length=50)


class PaymentPatchBody(BaseModel):
    from_contact: int | None = None  # assign an unattributed payment
    accepted: bool | None = None  # "Accept difference"
    fingerprint: str | None = Field(default=None, max_length=200)  # link a transaction
    unlink: bool = False


class ContactBody(BaseModel):
    name: Name
    alias: Name | None = None


class ContactPatchBody(BaseModel):
    name: Name


class AliasBody(BaseModel):
    alias: Name


class MergeBody(BaseModel):
    into: int
