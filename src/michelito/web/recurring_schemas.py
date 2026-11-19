"""JSON models of "Is recurring..." (from a transaction) and of "Join with..." / "Separate"."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from michelito.analysis.recurring import Cadence
from michelito.analysis.recurring_marks import KEY_MAX, MarkStatus

GroupKey = Literal["housing", "loans", "utilities", "insurance", "subscriptions", "fees", "other"]


class TxRecurringBody(BaseModel):
    """ "Is recurring...": cadence (monthly by default), optional group and, for a loan, the
    installments left (absent or null: not recorded)."""

    cadence: Cadence = "monthly"
    group: GroupKey | None = None
    installments_left: int | None = Field(default=None, ge=0, le=600)


class TxRecurringOut(BaseModel):
    """The transaction for Recurring: whether it can be marked and, if it already is, where."""

    eligible: bool  # an expense debit that is not a top-up
    reason: str  # why it cannot be marked (empty if it can)
    key: str  # the series (merchant or provider) it is marked with
    name: str
    currency: str
    recurring: bool  # shown in Recurring (detected or marked, not "Not recurring")
    mark: MarkStatus | None
    group: str  # the group it appears in (empty if it does not)
    loan: bool  # its category is Loans (installments are offered)


class JoinBody(BaseModel):
    """ "Join with...": the merchants of series `merchant` move to series `target`."""

    merchant: str = Field(min_length=1, max_length=KEY_MAX)
    target: str = Field(min_length=1, max_length=KEY_MAX)


class SeparateBody(BaseModel):
    """ "Separate": the merchant goes back to its own series."""

    merchant: str = Field(min_length=1, max_length=KEY_MAX)
