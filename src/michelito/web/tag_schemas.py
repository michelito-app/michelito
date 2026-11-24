"""Bodies and answers of the tag routes (`web.tag_routes`). Amounts in integer cents; RD$
amounts are `None` for dollars without the month's rate."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from michelito.analysis.spending import Movement
from michelito.analysis.tags import Member
from michelito.web.schemas import to_cents
from michelito.web.tag_view import Detail, TagChip, cents

Fingerprint = Annotated[str, StringConstraints(min_length=1, max_length=80)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=80)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
FINGERPRINTS_MAX = 500


class TagBody(BaseModel):
    name: Name
    color: Color | None = None


class TagPatch(BaseModel):
    name: Name | None = None
    color: Color | None = None


class FingerprintsBody(BaseModel):
    fingerprints: list[Fingerprint] = Field(min_length=1, max_length=FINGERPRINTS_MAX)


class OneOffBody(BaseModel):
    one_off: bool


class TagChipOut(BaseModel):
    id: int
    name: str
    color: str | None
    derived: bool

    @classmethod
    def of(cls, chip: TagChip) -> TagChipOut:
        return cls(id=chip.id, name=chip.name, color=chip.color, derived=chip.derived)


class TagSummaryOut(BaseModel):
    id: int
    name: str
    color: str | None
    group_id: int | None
    spent_cents: int
    still_to_pay_cents: int
    unconverted: int  # members in dollars without the month's rate (listed, not added)
    count: int
    first: str | None
    last: str | None

    @classmethod
    def of(cls, d: Detail) -> TagSummaryOut:
        total = d.total
        return cls(
            id=d.tag.id,
            name=d.tag.name,
            color=d.tag.color,
            group_id=d.tag.group_id,
            spent_cents=cents(total.spent),
            still_to_pay_cents=cents(total.still_to_pay),
            unconverted=total.unconverted,
            count=total.count,
            first=None if total.first is None else total.first.isoformat(),
            last=None if total.last is None else total.last.isoformat(),
        )


class RowOut(BaseModel):
    fingerprint: str
    day: str
    merchant: str
    description: str
    category: str
    amount_cents: int
    currency: str
    amount_dop_cents: int | None
    one_off: bool
    counted: bool  # adds to a tag's total (expenses and their refunds)


def row_fields(move: Movement, dop: int | None, counted: bool) -> dict:
    return {
        "fingerprint": move.fingerprint,
        "day": move.day.isoformat(),
        "merchant": move.merchant,
        "description": move.description,
        "category": move.category,
        "amount_cents": to_cents(move.amount),
        "currency": move.currency,
        "amount_dop_cents": dop,
        "one_off": move.one_off,
        "counted": counted,
    }


class MemberOut(RowOut):
    derived: bool  # comes from its group, loan or plan: untag it there
    via: str  # "manual" | "group" | "loan" | "installment"

    @classmethod
    def of(cls, m: Member, dop: int | None) -> MemberOut:
        return cls(**row_fields(m.move, dop, m.counted), derived=m.derived, via=m.via)


class CategoryAmountOut(BaseModel):
    category: str
    amount_cents: int


class TargetOut(BaseModel):
    kind: str  # "loan" | "installment"
    id: int
    name: str
    has_payout: bool  # its money reached the account: the purchase counts, not the payments
    still_to_pay_cents: int


class TagOut(TagSummaryOut):
    members: list[MemberOut]
    by_category: list[CategoryAmountOut]
    targets: list[TargetOut] = Field(default_factory=list)


class CandidateOut(RowOut):
    likely: bool  # a one-off, or among the largest expenses in the tag's categories
    tagged: bool


class CandidatesOut(BaseModel):
    from_: str = Field(serialization_alias="from")
    to: str
    items: list[CandidateOut]


class AddedOut(BaseModel):
    added: int
    entry_id: int | None


class RemovedOut(BaseModel):
    removed: int
    entry_id: int | None


class ChangedOut(BaseModel):
    changed: int
    entry_id: int | None
