"""Transaction queries and edits for the web."""

from __future__ import annotations

import sqlite3
import unicodedata
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, get_args

from michelito.analysis import catalog, categories, corrections, rates
from michelito.analysis.accounts import AccountInfo, account_label
from michelito.analysis.categories import Kind
from michelito.analysis.rates import Rate
from michelito.analysis.spending import Movement
from michelito.i18n import t
from michelito.web.installments import Tag
from michelito.web.links import RowLinks
from michelito.web.loans import Tag as LoanTag
from michelito.web.receipts import ReceiptView
from michelito.web.tag_view import TagChip

Scope = Literal["transaction", "merchant"]
SCOPES: tuple[str, ...] = get_args(Scope)
# Shared-expense filter: all, or only those with something pending ("they owe you").
SharedFilter = Literal["shared", "pending"]
# "Type" filter: a category kind, or "neutral" (transfer kinds that count neither as spending nor
# as income) and "third_party" (transfers to other people: they lower what you kept). "transfer"
# (both) stays for old links.
ListKind = Literal["income", "expense", "transfer", "neutral", "third_party"]


@dataclass(frozen=True)
class TxView:
    fingerprint: str
    day: date
    merchant: str
    description: str
    category: str
    kind: Kind
    original_category: str
    account: str
    account_label: str
    amount: Decimal
    currency: str
    amount_dop: Decimal | None  # None: dollars without the month's rate
    one_off: bool
    corrected: bool
    merchant_year_count: int  # the merchant's purchases in the transaction's year
    one_off_reasons: tuple[str, ...] = ()  # suggested as one-off: why
    one_off_dismissed: bool = False  # the user said it is not a one-off
    category_id: int | None = None
    note: str = ""
    gross: Decimal | None = None  # statement amount of a shared expense (amount: your share)
    links: RowLinks = RowLinks()
    provisional: bool = False  # from a bank alert, its statement has not arrived yet
    approved: bool = False  # hosted: it entered because the person approved an email
    cash_state: str = ""  # an unanswered scheduled cash occurrence: "pending" or "unconfirmed"
    receipts: tuple[ReceiptView, ...] = ()  # the merchant receipts linked to it (`web.receipts`)
    installment: Tag | None = None  # the installment plan it is part of (`web.installments`)
    loan: LoanTag | None = None  # the loan it pays (`web.loans`)
    tags: tuple[TagChip, ...] = ()  # the tags it is in (`web.tag_view`)

    @property
    def suggested_one_off(self) -> bool:
        return bool(self.one_off_reasons)


@dataclass(frozen=True)
class Filters:
    month: str
    account: str | None = None
    category: str | None = None
    q: str | None = None
    kind: ListKind | None = None
    accounts: Collection[str] | None = None  # several accounts; None: all
    # Stable reference of the requested category (the caller resolves it, see `catalog`);
    # wins over `category` (a name).
    category_ref: str | None = None
    shared: SharedFilter | None = None
    provisional: bool = False  # only the provisional ones (still without a statement)


def _of_kind(move: Movement, kind: ListKind | None) -> bool:
    if kind is None:
        return True
    if kind == "third_party":
        return move.ref == categories.THIRD_PARTY
    if kind == "neutral":
        return move.kind == "transfer" and move.ref != categories.THIRD_PARTY
    return move.kind == kind


def list_transactions(
    movements: Sequence[Movement],
    accounts: Sequence[AccountInfo],
    rates_by_month: Mapping[str, Rate],
    filters: Filters,
    suggested: Mapping[str, tuple[str, ...]] | None = None,
    dismissed: Collection[str] = (),
    known: catalog.Catalog | None = None,
    link_rows: Callable[[Collection[str]], Mapping[str, RowLinks]] | None = None,
) -> list[TxView]:
    """The month's transactions, newest first (load order within a day).

    `suggested`: reasons of the rows suggested as one-off, by fingerprint; `dismissed`:
    fingerprints whose suggestion the user dismissed; `known`, the catalog (for each
    category's id); `link_rows`, the link data of some fingerprints (`web.links.row_links`).
    """
    reasons = suggested or {}
    labels = {info.key: info.label for info in accounts}
    needle = _fold(filters.q or "").strip()
    # An old link may carry the former name of a renamed category.
    category = None if filters.category is None else categories.canonical(filters.category)
    year_counts = Counter(
        (m.merchant, m.day.year) for m in movements if m.amount > 0 and m.kind == "expense"
    )
    selected = [
        m
        for m in movements
        if m.month == filters.month
        and (filters.account is None or m.account == filters.account)
        and (filters.accounts is None or m.account in filters.accounts)
        and _in_category(m, filters.category_ref, category)
        and _of_kind(m, filters.kind)
        and (not needle or _matches(m, needle))
        and (not filters.provisional or m.provisional)
    ]
    selected.sort(key=lambda m: m.day, reverse=True)  # stable: keeps the load order
    rows = link_rows([m.fingerprint for m in selected]) if link_rows else {}
    if filters.shared is not None:
        selected = [m for m in selected if _in_shared(rows.get(m.fingerprint), filters.shared)]
    return [
        TxView(
            fingerprint=m.fingerprint,
            day=m.day,
            merchant=m.merchant,
            description=m.description,
            category=m.category,
            kind=m.kind,
            original_category=m.original_category,
            account=m.account,
            account_label=account_label(labels, m.account),
            amount=m.amount,
            currency=m.currency,
            amount_dop=rates.to_dop(m.amount, m.currency, rates.rate_for(rates_by_month, m.month)),
            one_off=m.one_off,
            corrected=m.corrected,
            merchant_year_count=year_counts[(m.merchant, m.day.year)],
            one_off_reasons=reasons.get(m.fingerprint, ()),
            one_off_dismissed=m.fingerprint in dismissed,
            category_id=_id_of(known, m.ref),
            note=m.note,
            gross=m.gross,
            links=rows.get(m.fingerprint, RowLinks()),
            provisional=m.provisional,
            cash_state=m.cash_state,
        )
        for m in selected
    ]


def _in_shared(row: RowLinks | None, wanted: SharedFilter) -> bool:
    """In a group (an entry the user paid, or a group movement); "pending": owed to the user."""
    found = None if row is None else row.ledger
    if found is None or found.entry is None:
        return False
    return wanted == "shared" or found.entry.pending > 0


def _matches(item: Movement, needle: str) -> bool:
    """The search looks at the merchant, the description and the note."""
    return any(needle in _fold(text) for text in (item.merchant, item.description, item.note))


def _in_category(item: Movement, ref: str | None, name: str | None) -> bool:
    if ref is not None:
        return item.ref == ref
    return name is None or item.category == name


def _id_of(known: catalog.Catalog | None, ref: str) -> int | None:
    found = None if known is None else known.by_ref(ref)
    return None if found is None else found.id


def find(movements: Sequence[Movement], fingerprint: str) -> Movement:
    for movement in movements:
        if movement.fingerprint == fingerprint:
            return movement
    raise LookupError(t("web.unknown_transaction_fingerprint", fingerprint=fingerprint))


def apply_edit(
    conn: sqlite3.Connection,
    movement: Movement,
    category: str | int | None,
    one_off: bool | None,
    scope: Scope,
    note: str | None = None,
) -> None:
    """Save the edit inside the caller's database transaction (`with conn:`).

    `category`: id or analysis reference (`catalog.Category.ref`). With merchant scope, the new
    rule replaces the transaction's own correction, if any (otherwise that correction would
    keep winning). `None` leaves that field alone; an empty note deletes it.
    """
    if scope not in SCOPES:
        raise ValueError(t("web.tx.unknown_scope", scope=scope))
    if category is not None:
        catalog.resolve_ref(conn, category)  # fail before writing anything
    if note is not None:
        corrections.set_note(conn, movement.fingerprint, note)
    if one_off is not None and one_off != movement.one_off:
        corrections.set_one_off(conn, movement.fingerprint, one_off)
    if category is None:
        return
    if scope == "merchant":
        corrections.set_transaction_category(conn, movement.fingerprint, None)
        corrections.set_merchant_category(conn, movement.merchant, category)
    else:
        corrections.set_transaction_category(conn, movement.fingerprint, category)


def _fold(text: str) -> str:
    """Lowercase without accents, for comparing."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
