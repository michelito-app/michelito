"""Transactions: loads, categorizes and aggregates the saved transactions.

Cards and bank accounts (savings and checking) are loaded. What counts as an expense:
- Credit card debits (purchases, interest, fees).
- Bank account debits recognized by a rule (taxes, bank fees, insurance, cash, loans; see
  `categories.categorize_bank`). The rest are "transfers to third parties": not an expense,
  but the Summary subtracts them from what you have left.
- Card refunds and credits that are not payments subtract (negative amount), just like an
  insurer's reimbursement in a bank account (Health, negative).
- Card promotion credits (cashback, bonuses) are income ("other income").
- Bank account credits are income ("salary" or "other income"; negative), except a reversal
  ("DEV …"): it takes the category of the debit it cancels (`reversals`) or, without one,
  subtracts from "transfers to third parties".
- Card payments and transfers between my accounts are transfers: they don't count.
- A shared expense counts only for your share (`shared`); the credits that reimburse it are
  "reimbursement" and the legs of a currency exchange, "currency exchange" (`links`): neither is
  income or expense.
- In an investment (`links`, `investments`) the contribution is "investments" (a transfer: it
  doesn't subtract from what you have left), the yield "investment returns" (income) and the
  return of capital "capital return" (a transfer); of a mixed credit only the yield part is
  income (`amount`; `gross` keeps the whole credit).
- The cash box (`cash_box`) is one more account: its inflows (income) and outflows (expense)
  entered by hand are its own transactions; a withdrawal stored in it or a deposit that came
  out of it is "cash box" (a transfer: neither expense nor income, it doesn't subtract from what
  you have left).

Each currency is aggregated separately; nothing is converted.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from michelito.analysis import (
    accounts,
    cash_box,
    cash_box_store,
    catalog,
    categories,
    corrections,
    coverage,
    investments,
    links,
    reversals,
    shared,
    transfers,
)
from michelito.analysis.rates import Rate
from michelito.analysis.rates import load as load_rates
from michelito.parsers.common import CREDIT

# A card without a statement close in this time (relative to the most recent one) is taken as
# closed and doesn't limit how far the data is complete.
_ACTIVE_WINDOW = timedelta(days=45)

# The order (date, statement close, position in the statement) doesn't depend on ids, so the
# fingerprints of two identical charges on the same day are assigned the same after reparsing.
_TRANSACTIONS = """
SELECT t.statement_id, t.transacted_on, t.description, t.amount_cents, t.direction,
       t.currency, t.mcc,
       a.institution, a.kind, a.key AS account
FROM transactions t
JOIN statements s ON s.id = t.statement_id
JOIN accounts a ON a.id = s.account_id
WHERE a.kind {kinds}
ORDER BY t.transacted_on, s.period_end, s.currency, t.sequence
"""
_CARD_TRANSACTIONS = _TRANSACTIONS.format(kinds="= 'credit_card'")
_BANK_TRANSACTIONS = _TRANSACTIONS.format(kinds="IN ('savings', 'checking')")

_IDENTITY = ("account", "transacted_on", "description", "amount_cents", "direction", "currency")

_CUTS_BY_CARD = """
SELECT MIN(s.period_end), MAX(s.period_end)
FROM statements s JOIN accounts a ON a.id = s.account_id
WHERE a.kind = 'credit_card'
GROUP BY a.id
"""


@dataclass(frozen=True)
class Movement:
    day: date
    merchant: str
    description: str
    category: str
    amount: Decimal  # positive: expense; negative: refund or credit
    currency: str
    institution: str
    fingerprint: str = ""
    one_off: bool = False  # extraordinary expense: left out of averages
    corrected: bool = False  # the user set the category
    account: str = ""  # the card's accounts.key
    original_category: str = ""  # category before corrections (learned rule or MCC)
    # Stable references (`catalog.Category.ref`) when `category` / `original_category` are the
    # display name; empty: the name is the reference (that's how tests build them). Logic
    # compares `ref`, never the name: renaming doesn't change it.
    category_key: str = ""
    original_key: str = ""
    category_kind: categories.Kind | None = None  # kind of a user category
    note: str = ""  # the user's free-form note
    # Link (`links`): "shared" (shared expense: `amount` is what counts as your expense and
    # `gross` the statement amount), "reimbursement" (a credit that reimburses one), "exchange"
    # (a leg of a currency exchange) or "investment" (a contribution or credit of an investment;
    # in a mixed credit `amount` is only the yield and `gross` the whole credit). Empty: none.
    link: str = ""
    gross: Decimal | None = None

    @property
    def ref(self) -> str:
        return self.category_key or self.category

    @property
    def original_ref(self) -> str:
        return self.original_key or self.original_category

    @property
    def kind(self) -> categories.Kind:
        """The transaction's kind: its category gives it, so correcting the category changes it."""
        return self.category_kind or categories.kind_of(self.ref)

    @property
    def month(self) -> str:
        return self.day.strftime("%Y-%m")


@dataclass(frozen=True)
class MerchantTotal:
    name: str
    total: Decimal
    purchases: int


@dataclass(frozen=True)
class CategoryChange:
    category: str
    current: Decimal
    average: Decimal


def load_movements(
    conn: sqlite3.Connection,
    holders: Sequence[str] | transfers.Holders = (),
    known: catalog.Catalog | None = None,
) -> tuple[Movement, ...]:
    """Expense transactions, with the user's corrections already applied.

    `holders` as in `load_all`: without them, a transfer to an own account stays a transfer to
    third parties (not an expense, but not "between my accounts" either).
    """
    return tuple(m for m in load_all(conn, holders, known) if m.kind == "expense")


def load_all(
    conn: sqlite3.Connection,
    holders: Sequence[str] | transfers.Holders = (),
    known: catalog.Catalog | None = None,
) -> tuple[Movement, ...]:
    """Every card and bank account transaction (expenses, income, transfers).

    Transfers are detected (see `transfers`): card payments and transactions between the
    user's accounts, recognized by a holder's name in `holders` (normalized with
    `categories.clean`; or a `transfers.Holders`, which also brings own account numbers) or by
    the number of another own account.
    Portal printouts don't repeat days already covered (see `coverage`).
    In a bank account, the default category comes from `categories.categorize_bank`; a reversal
    ("DEV …") takes its debit's (see `reversals`).
    The user's corrections always win over what was detected; in a bank account, a merchant's
    only if its kind fits the direction (see `_bank_kinds`).

    Order: 1. corrections (the transaction's wins over the merchant's); 2. detected transfers;
    3. the user's keywords (`catalog`; in a bank, only if the kind fits the direction, like a
    merchant rule); 4. rules, MCC and learned merchants.
    `known`: the catalog to use (by default the database's; another one, to preview keywords).
    Each transaction comes out with its category's current name and its reference.
    """
    known = known or catalog.load(conn)
    cards = list(conn.execute(_CARD_TRANSACTIONS))
    # Before counting occurrences: a repeated printout row must not shift the fingerprints.
    covered = coverage.bank_coverage(conn)
    banks = [
        row
        for row in conn.execute(_BANK_TRANSACTIONS)
        if covered.keeps(row["statement_id"], date.fromisoformat(row["transacted_on"]))
    ]
    learned = categories.learn_merchants(
        (row["description"], row["mcc"]) for row in cards if not _is_payment(row)
    )
    fixes = corrections.load(conn, known)
    seen: Counter[tuple[object, ...]] = Counter()
    movements = []
    for row in (*cards, *banks):
        identity = tuple(row[key] for key in _IDENTITY)
        movements.append(_movement(row, learned, fixes, seen[identity]))
        seen[identity] += 1
    infos = accounts.account_infos(conn)
    detected = transfers.detect_transfers(
        movements, infos, holders, card_last4=transfers.last4_by_card_account(conn)
    )
    kinds = {info.key: info.kind for info in infos}
    found = [
        _with_detected(m, detected[m.fingerprint])
        if m.fingerprint in detected
        else _with_keyword(m, known, kinds.get(m.account))
        for m in movements
    ]
    # At the end: a reversal takes the debit's final category (detected or corrected).
    reversed_ = reversals.pair_reversals(found, infos)
    paired = [_with_reversal(m, reversed_.get(m.fingerprint), fixes) for m in found]
    # What was entered by hand in the cash box, after detecting transfers and reversals: it
    # doesn't come from a statement (see `cash_box`).
    manual = [_manual_movement(e, fixes) for e in cash_box_store.load_entries(conn)]
    named = tuple(_named(m, known) for m in (*paired, *(m for m in manual if m is not None)))
    # Last: the user's links (shared expenses, reimbursements and exchanges) win.
    bank_keys = {info.key for info in infos if info.kind in accounts.BANK_KINDS}
    return with_links(named, links.load(conn), known, bank_keys, load_rates(conn))


def with_links(
    movements: Sequence[Movement],
    found: links.Links,
    known: catalog.Catalog,
    banks: Collection[str] | None = None,
    rates: Mapping[str, Rate] | None = None,
) -> tuple[Movement, ...]:
    """Applies the links: without any, returns the same transactions.

    - Each expense of a shared group (if it is still a positive expense) counts for what
      `shared.group_state` says (its share and its part of what was written off); `gross` keeps
      the statement amount.
    - A credit linked as a reimbursement is always "reimbursement", even when the link is
      dormant (its expense no longer appears or stopped being an expense): it stays linked
      until removed. The exception: one in the expense's other currency without a rate for its
      month stays as it was.
    - The legs of an exchange are always "currency exchange" (also when the exchange is missing
      a leg or no longer balances), except those not from a bank account.
    - In an investment, a contribution (if it is still a debit) is "investments"; a credit,
      "investment returns" or "capital return" by its kind; a mixed one is "investment returns"
      for the part that isn't capital (`gross`, the whole credit). If the capital part is no
      longer smaller than the credit (the statement changed), it all counts as capital. Capital
      returned beyond what was contributed up to that day is a gain: it counts as "investment
      returns" (income).
    `banks`: bank accounts (an exchange's legs can only be from them; None: all).
    `rates`: rates by month, to count a reimbursement in the expense's other currency (without
    them, a reimbursement in another currency doesn't lower what you are owed).
    """
    if not found.shared and not found.exchanges and not found.investments and not found.cash_boxes:
        return tuple(movements)
    by_fp = {m.fingerprint: m for m in movements}
    counted: dict[str, Decimal] = {}
    credits = {
        credit
        for link in found.shared
        for credit in link.reimbursements
        if credit in by_fp and by_fp[credit].amount < 0
    }
    for link in found.shared:
        present = [
            move
            for e in link.expenses
            if (move := by_fp.get(e.fingerprint)) is not None
            and move.kind == "expense"
            and move.amount > 0
        ]
        if not present:
            continue
        state = shared.group_state(link, present, by_fp, rates or {})
        counted.update((e.fingerprint, e.counted) for e in state.expenses)
        # A credit in the other currency without a rate doesn't lower any expense: it doesn't
        # stop being income either (otherwise that money would vanish from the totals).
        credits -= state.uncounted
    legs = {
        leg
        for exchange in found.exchanges
        for leg in exchange.legs
        if leg in by_fp and (banks is None or by_fp[leg].account in banks)
    }
    invested = {
        member.fingerprint: member
        for investment in found.investments
        for member in investment.members
        if member.fingerprint in by_fp
    }
    capitals: dict[str, Decimal] = {}
    for investment in found.investments:
        pairs = [(by_fp[m.fingerprint], m) for m in investment.members if m.fingerprint in by_fp]
        capitals.update(investments.effective_capitals(pairs, rates or {}))
    boxed = {m.fingerprint: m.role for box in found.cash_boxes for m in box.members}
    return tuple(
        _invested(m, invested[m.fingerprint], capitals.get(m.fingerprint), known)
        if m.fingerprint in invested
        else _boxed(m, boxed[m.fingerprint], known)
        if m.fingerprint in boxed
        else _linked(m, counted, credits, legs, known)
        for m in movements
    )


def _boxed(item: Movement, role: str, known: catalog.Catalog) -> Movement:
    """A stored withdrawal (if it is still a debit) or a deposit from the box (if it is still a
    credit) is "cash box"; if the statement changed, it stays as it was."""
    if (role == "stored" and item.amount > 0) or (role == "deposit" and item.amount < 0):
        return _relabeled(item, categories.CASH_BOX, known, "cash_box")
    return item


def _manual_movement(
    entry: cash_box.ManualEntry, fixes: corrections.Corrections
) -> Movement | None:
    """An inflow (income) or outflow (expense) entered in the box, as a transaction of its
    account; the initial balance is not a flow transaction. The category set by hand (when
    entering or correcting it) wins; merchant rules and keywords don't apply."""
    if entry.kind == "initial":
        return None
    mark = entry.fingerprint
    original = cash_box.DEFAULT_CATEGORY[entry.kind]
    chosen = fixes.transaction_category(mark)
    return Movement(
        day=entry.day,
        merchant=cash_box.MERCHANT,
        description=cash_box.DESCRIPTIONS[entry.kind],
        category=chosen or original,
        amount=-entry.amount if entry.kind == "income" else entry.amount,
        currency=entry.currency,
        institution="manual",
        fingerprint=mark,
        one_off=fixes.is_one_off(mark),
        note=fixes.note_for(mark),
        corrected=chosen is not None and chosen != original,
        account=entry.account_key,
        original_category=original,
    )


def _invested(
    item: Movement,
    member: links.InvestmentMember,
    capital: Decimal | None,
    known: catalog.Catalog,
) -> Movement:
    """An investment transaction with the category its kind gives (see `with_links`). A
    contribution that is no longer a debit, or a credit that is no longer a credit, stays as it
    was. `capital`: the capital part that counts (`investments.effective_capitals`): what was
    returned beyond what was contributed is yield."""
    if member.role == "contribution":
        if item.amount <= 0:
            return item
        return _relabeled(item, categories.INVESTMENT, known, "investment")
    if item.amount >= 0:
        return item
    if member.role == "return":
        return _relabeled(item, categories.INVESTMENT_RETURN, known, "investment")
    if capital is None:
        capital = -item.amount if member.role == "capital" else (member.capital or -item.amount)
    if capital >= -item.amount:
        return _relabeled(item, categories.INVESTMENT_CAPITAL, known, "investment")
    if capital <= 0:
        return _relabeled(item, categories.INVESTMENT_RETURN, known, "investment")
    relabeled = _relabeled(item, categories.INVESTMENT_RETURN, known, "investment")
    return replace(relabeled, amount=item.amount + capital, gross=item.amount)


def _linked(
    item: Movement,
    counted: Mapping[str, Decimal],
    credits: Collection[str],
    legs: Collection[str],
    known: catalog.Catalog,
) -> Movement:
    if item.fingerprint in counted:
        return replace(item, amount=counted[item.fingerprint], gross=item.amount, link="shared")
    if item.fingerprint in credits:
        return _relabeled(item, categories.REIMBURSEMENT, known, "reimbursement")
    if item.fingerprint in legs:
        return _relabeled(item, categories.CURRENCY_EXCHANGE, known, "exchange")
    return item


def _relabeled(item: Movement, ref: str, known: catalog.Catalog, link: str) -> Movement:
    return replace(
        item,
        category=known.name_of(ref),
        category_key=ref,
        category_kind=known.kind_of(ref),
        corrected=False,
        link=link,
    )


def _with_keyword(item: Movement, known: catalog.Catalog, account_kind: str | None) -> Movement:
    """The longest matching keyword decides, unless the user corrected the transaction."""
    if item.corrected:
        return item
    allowed = _kinds_for(account_kind, item.amount < 0)
    text = categories.clean(item.description)
    for hit in known.keyword_hits(text):
        if allowed is None or hit.category.kind in allowed:
            ref = hit.category.ref
            return replace(item, category=ref, original_category=ref)
    return item


def _named(item: Movement, known: catalog.Catalog) -> Movement:
    """With the category's current name and its stable reference."""
    ref, original = item.ref, item.original_ref
    return replace(
        item,
        category=known.name_of(ref),
        category_key=ref,
        original_category=known.name_of(original),
        original_key=original,
        category_kind=known.kind_of(ref),
    )


def _with_detected(item: Movement, category: str | None) -> Movement:
    """What was detected (transfer or reversal) is the default category; a correction replaces
    it."""
    if category is None:
        return item
    chosen = item.category if item.corrected else category
    return replace(item, category=chosen, original_category=category)


def _with_reversal(
    item: Movement, category: str | None, fixes: corrections.Corrections
) -> Movement:
    """A paired reversal takes its debit's final category.

    Only that transaction's own correction beats it: reversals share a merchant key
    ("DEV LBTR"), so a merchant rule (or one for the previous key) doesn't count.
    """
    if category is None:
        return item
    own = fixes.transaction_category(item.fingerprint)
    return replace(
        item, category=own or category, corrected=own is not None, original_category=category
    )


def _is_payment(row: sqlite3.Row) -> bool:
    return row["direction"] == CREDIT and categories.is_payment(row["description"])


def _is_promotion(row: sqlite3.Row) -> bool:
    return row["direction"] == CREDIT and categories.is_promotion(row["description"])


def _movement(
    row: sqlite3.Row, learned: dict[str, str], fixes: corrections.Corrections, occurrence: int
) -> Movement:
    day = date.fromisoformat(row["transacted_on"])
    mark = corrections.fingerprint(
        row["account"],
        day,
        row["description"],
        row["amount_cents"],
        row["direction"],
        row["currency"],
        occurrence,
    )
    legacy = categories.merchant_key(row["description"])
    if row["kind"] == "credit_card":
        merchant, chosen = legacy, fixes.category_for(mark, legacy)
    else:
        merchant = categories.bank_merchant_key(row["description"])
        previous = categories.previous_bank_key(row["description"])
        chosen = fixes.category_for(mark, merchant, _bank_kinds(row), (previous, legacy))
    amount = Decimal(row["amount_cents"]) / 100
    if row["kind"] != "credit_card":
        original = categories.categorize_bank(row["description"], row["direction"])
    elif _is_payment(row):
        original = categories.CARD_PAYMENT
    elif _is_promotion(row):
        original = categories.OTHER_INCOME
    else:
        original = categories.categorize(row["description"], row["mcc"], learned)
    return Movement(
        day=day,
        merchant=merchant,
        description=row["description"],
        category=chosen or original,
        amount=-amount if row["direction"] == CREDIT else amount,
        currency=row["currency"],
        institution=row["institution"],
        fingerprint=mark,
        one_off=fixes.is_one_off(mark),
        note=fixes.note_for(mark),
        corrected=chosen is not None,
        account=row["account"],
        original_category=original,
    )


def _bank_kinds(row: sqlite3.Row) -> tuple[categories.Kind, ...] | None:
    """Kinds a merchant rule can give a bank transaction; on cards, all of them.

    The same counterpart sends and receives ("LBTR JUAN PEREZ"), and a previous key was just
    the channel ("PAGO DE", "MB A"): without this limit, a rule meant for a deposit would also
    change the debits.
    """
    return _kinds_for(row["kind"], row["direction"] == CREDIT)


def _kinds_for(account_kind: str | None, credit: bool) -> tuple[categories.Kind, ...] | None:
    if account_kind in (None, "credit_card"):
        return None
    if credit:
        return ("income", "transfer")
    return ("expense", "transfer")


def _active_cards(conn: sqlite3.Connection) -> list[tuple[date, date]]:
    """First and last statement close of each card that still receives statements."""
    cuts = [
        (date.fromisoformat(first), date.fromisoformat(last))
        for first, last in conn.execute(_CUTS_BY_CARD)
    ]
    if not cuts:
        return []
    newest = max(last for _, last in cuts)
    return [(first, last) for first, last in cuts if newest - last <= _ACTIVE_WINDOW]


def complete_through(conn: sqlite3.Connection) -> date | None:
    """Last day with data from every active card (the oldest close among them)."""
    cards = _active_cards(conn)
    return min(last for _, last in cards) if cards else None


def first_full_month(conn: sqlite3.Connection) -> str | None:
    """First month fully covered by every active card.

    A card's first statement brings only the end of the month before its close; the close's
    month is complete with the next statement.
    """
    cards = _active_cards(conn)
    return max(first for first, _ in cards).strftime("%Y-%m") if cards else None


def last_full_month(through: date) -> str:
    """Last month fully covered up to `through`."""
    if (through + timedelta(days=1)).month != through.month:
        return through.strftime("%Y-%m")
    return (through.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def months_back(last: str, count: int) -> tuple[str, ...]:
    year, month = (int(part) for part in last.split("-"))
    found: list[str] = []
    for _ in range(count):
        found.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return tuple(reversed(found))


def _select(movements: Iterable[Movement], currency: str, months: Sequence[str]) -> list[Movement]:
    wanted = set(months)
    return [m for m in movements if m.currency == currency and m.month in wanted]


def monthly_totals(
    movements: Iterable[Movement], currency: str, months: Sequence[str]
) -> dict[str, Decimal]:
    totals = dict.fromkeys(months, Decimal(0))
    for item in _select(movements, currency, months):
        totals[item.month] += item.amount
    return totals


def by_category(
    movements: Iterable[Movement], currency: str, months: Sequence[str]
) -> list[tuple[str, Decimal]]:
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    for item in _select(movements, currency, months):
        totals[item.category] += item.amount
    return sorted(((name, total) for name, total in totals.items() if total), key=_by_amount)


def monthly_by_category(
    movements: Iterable[Movement], currency: str, months: Sequence[str]
) -> dict[str, dict[str, Decimal]]:
    """Spending of each category in each month; months without spending stay at zero."""
    table: dict[str, dict[str, Decimal]] = {}
    for item in _select(movements, currency, months):
        row = table.setdefault(item.category, dict.fromkeys(months, Decimal(0)))
        row[item.month] += item.amount
    return table


def top_merchants(
    movements: Iterable[Movement], currency: str, months: Sequence[str], limit: int
) -> list[MerchantTotal]:
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    purchases: Counter[str] = Counter()
    for item in _select(movements, currency, months):
        totals[item.merchant] += item.amount
        if item.amount > 0:
            purchases[item.merchant] += 1
    ranked = sorted(totals.items(), key=_by_amount)[:limit]
    return [MerchantTotal(name, total, purchases[name]) for name, total in ranked]


def compare_month(
    movements: Sequence[Movement], currency: str, month: str, baseline: Sequence[str]
) -> list[CategoryChange]:
    """The month's spending by category against the monthly average of `baseline`.

    One-off expenses count in the month, but not in the average.
    """
    current = dict(by_category(movements, currency, (month,)))
    before = dict(by_category(regular(movements), currency, baseline))
    periods = Decimal(len(baseline) or 1)
    changes = [
        CategoryChange(name, current.get(name, Decimal(0)), before.get(name, Decimal(0)) / periods)
        for name in current.keys() | before.keys()
    ]
    return sorted(changes, key=lambda c: (-(c.current - c.average), c.category))


def regular(movements: Iterable[Movement]) -> list[Movement]:
    """Transactions without the one-off expenses: the basis of any average."""
    return [m for m in movements if not m.one_off]


def _by_amount(item: tuple[str, Decimal]) -> tuple[Decimal, str]:
    return (-item[1], item[0])
