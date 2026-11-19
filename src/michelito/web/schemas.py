"""API JSON models: money in whole cents, ISO dates, rates as text."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool

from michelito.analysis import anomalies, cash_box, catalog, corrections, links
from michelito.analysis import providers as provider_list
from michelito.analysis.anomalies import Direction
from michelito.analysis.categories import Kind
from michelito.analysis.exchanges import ExchangeState
from michelito.analysis.investments import InvestmentState, Status
from michelito.analysis.rates import Rate
from michelito.analysis.recurring import Cadence, PriceChange
from michelito.analysis.recurring_marks import MarkStatus
from michelito.analysis.shared import ExpenseState, SharedState
from michelito.web import accounts as accounts_view
from michelito.web import categories as categories_view
from michelito.web import interest as interest_view
from michelito.web import links as links_view
from michelito.web import one_offs as one_offs_view
from michelito.web import pending as pending_view
from michelito.web import recurring as recurring_view
from michelito.web import summary as summary_view
from michelito.web.recurring_schemas import GroupKey
from michelito.web.transactions import TxView

_RATE_QUANTUM = Decimal("0.0001")


def to_cents(value: Decimal) -> int:
    """The single conversion point to cents: half-even rounding on Decimal."""
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def _cents(value: Decimal | None) -> int | None:
    return None if value is None else to_cents(value)


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


Currency = Literal["DOP", "USD"]


def _currency(code: str) -> Currency:
    """Narrows a movement's currency code to the API type."""
    if code == "DOP":
        return "DOP"
    if code == "USD":
        return "USD"
    raise ValueError(f"unsupported currency: {code}")


class MonthOptionOut(BaseModel):
    month: str
    label: str
    partial: bool

    @classmethod
    def of(cls, option: summary_view.MonthOption) -> MonthOptionOut:
        return cls(month=option.month, label=option.label, partial=option.partial)


class RateOut(BaseModel):
    value: str
    month_used: str
    source: str

    @classmethod
    def of(cls, rate: Rate) -> RateOut:
        return cls(
            value=str(rate.value.quantize(_RATE_QUANTUM)),
            month_used=rate.month_used,
            source=rate.source,
        )


class SavedRateOut(RateOut):
    month: str


class CoverageOut(BaseModel):
    key: str
    label: str
    through: str | None
    complete: bool


class IncomeLineOut(BaseModel):
    category: str
    amount_cents: int  # positive
    count: int


class CategoryLineOut(BaseModel):
    category: str
    amount_cents: int
    habitual_cents: int | None
    diff_cents: int | None
    same: bool
    share: float
    one_offs_cents: int
    purchases: int
    habitual_purchases: int | None


class ChangeOut(BaseModel):
    category: str
    diff_cents: int
    one_offs_cents: int
    purchases: int
    habitual_purchases: int | None


class MonthTotalOut(BaseModel):
    month: str
    label: str
    total_cents: int
    income_cents: int
    partial: bool  # month in progress for the chosen accounts
    spent_flag: Direction | None  # unusual month in spending (see analysis.anomalies)
    spent_habitual_cents: int | None  # None with fewer than three reference months
    income_flag: Direction | None
    income_habitual_cents: int | None


class ContributionOut(BaseModel):
    """A merchant that explains an unusual month ("What happened")."""

    side: Literal["expense", "income"]
    merchant: str
    category: str
    amount_cents: int
    habitual_cents: int
    diff_cents: int
    count: int
    fingerprint: str  # its largest movement of the month; "" if it did not appear
    day: str | None
    description: str

    @classmethod
    def of(cls, c: anomalies.Contribution) -> ContributionOut:
        return cls(
            side=c.side,
            merchant=c.merchant,
            category=c.category,
            amount_cents=to_cents(c.amount),
            habitual_cents=to_cents(c.habitual),
            diff_cents=to_cents(c.diff),
            count=c.count,
            fingerprint=c.fingerprint,
            day=_iso(c.day),
            description=c.description,
        )


class AccountTotalOut(BaseModel):
    key: str
    label: str
    total_cents: int
    usd_cents: int


class SummaryOut(BaseModel):
    option: MonthOptionOut
    coverage: list[CoverageOut]
    total_cents: int
    income_cents: int
    third_party_cents: int  # the month's third-party transfers in RD$ (outflow positive)
    net_cents: int | None  # income - expenses - third party; None: only cards chosen
    savings_rate: float | None
    income_through: str | None  # ISO; None if every bank account covers the month
    regular_total_cents: int
    one_offs_cents: int
    habitual_cents: int | None
    usd_cents: int
    usd_in_dop_cents: int | None
    rate: RateOut | None
    categories: list[CategoryLineOut]
    changes: list[ChangeOut]
    trend: list[MonthTotalOut]
    by_account: list[AccountTotalOut]
    needs_income: bool  # no bank account chosen (only cards): no flow to show
    to_cards_cents: int  # card payments from the chosen ones if some card is not chosen (approx.)
    to_own_cents: (
        int  # "Between my accounts" leaving the chosen ones if some is not chosen (approx.)
    )
    owed_cents: int  # owed to you: pending on the month's shared expenses (RD$)
    exchanges_pending_cents: int  # the month's open currency exchanges: pending in RD$
    what_happened: list[ContributionOut]  # "What happened" if the month is unusual
    invested_cents: (
        int  # the month's investment contributions (RD$): not subtracted from what you kept
    )
    cash_box_cents: (
        int  # the month's withdrawals stored in the cash box (RD$): not subtracted either
    )
    incomes: list[IncomeLineOut]  # the month's income by category (crypto apart), largest first

    @classmethod
    def of(cls, s: summary_view.Summary) -> SummaryOut:
        return cls(
            option=MonthOptionOut.of(s.option),
            coverage=[
                CoverageOut(key=c.key, label=c.label, through=_iso(c.through), complete=c.complete)
                for c in s.coverage
            ],
            total_cents=to_cents(s.total),
            income_cents=to_cents(s.income),
            third_party_cents=to_cents(s.third_party),
            net_cents=_cents(s.net),
            savings_rate=s.savings_rate,
            income_through=_iso(s.income_through),
            regular_total_cents=to_cents(s.regular_total),
            one_offs_cents=to_cents(s.one_offs),
            habitual_cents=_cents(s.habitual),
            usd_cents=to_cents(s.usd),
            usd_in_dop_cents=_cents(s.usd_in_dop),
            rate=None if s.rate is None else RateOut.of(s.rate),
            categories=[
                CategoryLineOut(
                    category=c.category,
                    amount_cents=to_cents(c.amount),
                    habitual_cents=_cents(c.habitual),
                    diff_cents=_cents(c.diff),
                    same=c.same,
                    share=c.share,
                    one_offs_cents=to_cents(c.one_offs),
                    purchases=c.purchases,
                    habitual_purchases=c.habitual_purchases,
                )
                for c in s.categories
            ],
            changes=[
                ChangeOut(
                    category=c.category,
                    diff_cents=to_cents(c.diff),
                    one_offs_cents=to_cents(c.one_offs),
                    purchases=c.purchases,
                    habitual_purchases=c.habitual_purchases,
                )
                for c in s.changes
            ],
            trend=[
                MonthTotalOut(
                    month=t.month,
                    label=t.label,
                    total_cents=to_cents(t.total),
                    income_cents=to_cents(t.income),
                    partial=t.partial,
                    spent_flag=t.spent_flag,
                    spent_habitual_cents=_cents(t.spent_habitual),
                    income_flag=t.income_flag,
                    income_habitual_cents=_cents(t.income_habitual),
                )
                for t in s.trend
            ],
            by_account=[
                AccountTotalOut(
                    key=a.key,
                    label=a.label,
                    total_cents=to_cents(a.total),
                    usd_cents=to_cents(a.usd),
                )
                for a in s.by_account
            ],
            needs_income=s.needs_income,
            to_cards_cents=to_cents(s.to_cards),
            to_own_cents=to_cents(s.to_own),
            owed_cents=to_cents(s.owed),
            exchanges_pending_cents=to_cents(s.exchanges_pending),
            what_happened=[ContributionOut.of(c) for c in s.what_happened],
            invested_cents=to_cents(s.invested),
            cash_box_cents=to_cents(s.to_cash_box),
            incomes=[
                IncomeLineOut(category=i.category, amount_cents=to_cents(i.amount), count=i.count)
                for i in s.income_lines
            ],
        )


class LinkedTxOut(BaseModel):
    """Another transaction mentioned in the detail (reimbursement, leg, suggestion)."""

    fingerprint: str
    day: str
    merchant: str
    account_label: str
    amount_cents: int  # as on the statement; a credit is negative
    currency: str
    # A credit in the expense's other currency: its value in the expense's currency (positive),
    # or null without a rate. `converted_currency` is null when the credit is already in it.
    converted_cents: int | None = None
    converted_currency: str | None = None
    description: str = ""  # as it appears on the statement

    @classmethod
    def of(cls, v: links_view.LinkedTx) -> LinkedTxOut:
        return cls(
            fingerprint=v.fingerprint,
            day=v.day.isoformat(),
            merchant=v.merchant,
            account_label=v.account_label,
            amount_cents=to_cents(v.amount),
            currency=v.currency,
            converted_cents=None if v.converted is None else to_cents(v.converted),
            converted_currency=v.converted_currency,
            description=v.description,
        )


class CandidateOut(LinkedTxOut):
    """An option of a picker, in display order. `primary`: it goes in the visible part (the UI
    shows the first ones and leaves the rest behind "See more")."""

    primary: bool

    @classmethod
    def ranked(cls, v: links_view.LinkedTx, primary: bool) -> CandidateOut:
        return cls(**LinkedTxOut.of(v).model_dump(), primary=primary)


def _linked(v: links_view.LinkedTx | None) -> LinkedTxOut | None:
    return None if v is None else LinkedTxOut.of(v)


class ManualOut(BaseModel):
    id: int
    amount_cents: int
    day: str
    person: str
    place: str  # "" = cash
    currency: str  # the money's


class GroupExpenseOut(LinkedTxOut):
    """A group expense: its split and its state after applying reimbursements (its currency)."""

    people: int | None
    my_share_cents: int | None
    for_other: bool
    share_cents: int  # your part according to the split
    counted_cents: int  # what counts as your spending
    reimbursed_cents: int  # what was applied (oldest to newest)
    pending_cents: int  # owed to you on this expense
    written_off_cents: int


class SharedTotalOut(BaseModel):
    """The figures of the group's expenses in one currency."""

    currency: Currency
    share_cents: int
    reimbursed_cents: int
    pending_cents: int
    written_off_cents: int


class GroupRefOut(BaseModel):
    """A group in a list ("Add it to a group", suggestions): title and what is pending."""

    id: int
    title: str  # the name, else "With whom", else the first expense's merchant
    name: str
    with_whom: str
    first_fingerprint: str  # the first expense: opens the group screen
    expense_count: int
    pending: list[CurrencyCentsOut]  # by currency (RD$ before US$)
    last_split: SplitOut  # the split of the last expense added: proposed when adding another

    @classmethod
    def ref(cls, st: SharedState) -> GroupRefOut:
        last = st.link.expenses[-1]
        return cls(
            id=st.id,
            title=st.title,
            name=st.link.name,
            with_whom=st.link.with_whom,
            first_fingerprint=st.first.fingerprint,
            expense_count=len(st.expenses),
            pending=_currency_cents(sorted(st.pending.items())),
            last_split=SplitOut(
                people=last.people,
                my_share_cents=None if last.my_share is None else to_cents(last.my_share),
                for_other=last.for_other,
            ),
        )


class InvestmentRefOut(BaseModel):
    """An investment in a list ("Add to an existing one", the Transactions row): title, status
    and capital still to come back, in its currency."""

    id: int
    title: str  # the name, else "With whom", else the first contribution's merchant
    name: str
    with_whom: str
    status: Status
    currency: str
    first_fingerprint: str  # the first contribution: opens the investment screen
    pending_cents: int  # capital still to come back, in `currency`

    @classmethod
    def ref(cls, st: InvestmentState) -> InvestmentRefOut:
        return cls(
            id=st.id,
            title=st.title,
            name=st.link.name,
            with_whom=st.link.with_whom,
            status=st.status,
            currency=st.currency,
            first_fingerprint=st.first.fingerprint,
            pending_cents=to_cents(st.pending),
        )


class InvestmentHintOut(InvestmentRefOut):
    """The "Another contribution to…?" or "A return from…?" hint for a row."""

    kind: Literal["possible_contribution", "possible_return"]


class SplitOut(BaseModel):
    people: int | None
    my_share_cents: int | None
    for_other: bool


class SharedOut(GroupRefOut):
    """A shared group: its expenses (each with its split and state), what was paid back and
    what is pending by currency, and its reimbursements."""

    written_off: bool  # "They won't pay me back" (the whole group)
    expenses: list[GroupExpenseOut]  # oldest to newest
    totals: list[SharedTotalOut]
    excess: list[CurrencyCentsOut]  # paid back in excess after settling everything: does not count
    unconverted: list[
        str
    ]  # reimbursements (fingerprint or "manual:<id>") that did not count: no rate
    reimbursements: list[LinkedTxOut]
    manual: list[ManualOut]

    @classmethod
    def of(cls, view: links_view.GroupView) -> SharedOut:
        st = view.state
        link = st.link
        return cls(
            **GroupRefOut.ref(st).model_dump(),
            written_off=link.written_off,
            expenses=[_group_expense(e, tx) for e, tx in view.expenses],
            totals=[
                SharedTotalOut(
                    currency=_currency(t.currency),
                    share_cents=to_cents(t.share),
                    reimbursed_cents=to_cents(t.reimbursed),
                    pending_cents=to_cents(t.pending),
                    written_off_cents=to_cents(t.written_off),
                )
                for t in st.totals
            ],
            excess=_currency_cents(list(st.excess_by)),
            unconverted=list(st.unconverted),
            reimbursements=[LinkedTxOut.of(c) for c in view.credits],
            manual=[
                ManualOut(
                    id=m.id,
                    amount_cents=to_cents(m.amount),
                    day=m.day.isoformat(),
                    person=m.person,
                    place=m.place,
                    currency=m.currency,
                )
                for m in link.manual
            ],
        )


def _group_expense(e: ExpenseState, tx: links_view.LinkedTx) -> GroupExpenseOut:
    split = e.split
    return GroupExpenseOut(
        **LinkedTxOut.of(tx).model_dump(),
        people=split.people,
        my_share_cents=None if split.my_share is None else to_cents(split.my_share),
        for_other=split.for_other,
        share_cents=to_cents(e.share),
        counted_cents=to_cents(e.counted),
        reimbursed_cents=to_cents(e.reimbursed),
        pending_cents=to_cents(e.pending),
        written_off_cents=to_cents(e.written_off),
    )


class ExchangeOut(BaseModel):
    """A currency exchange: its legs, the rate and what is pending."""

    id: int
    rate: str  # RD$ per US$ in use (agreed or implied), 4 decimals
    implied_rate: str
    agreed_rate: str | None
    closed: bool
    base: Currency  # currency of the oldest leg
    totals: list[CurrencyCentsOut]
    pending_cents: int
    pending_currency: Currency
    pending_dop_cents: int
    # Without an agreed rate and with only the first pair: the pending amount means nothing (the
    # UI asks for the agreed rate).
    needs_agreed_rate: bool
    legs: list[LinkedTxOut]

    @classmethod
    def of(cls, st: ExchangeState, legs: tuple[links_view.LinkedTx, ...]) -> ExchangeOut:
        agreed = st.exchange.agreed_rate
        return cls(
            id=st.exchange.id,
            rate=str(st.rate.quantize(_RATE_QUANTUM)),
            implied_rate=str(st.implied_rate.quantize(_RATE_QUANTUM)),
            agreed_rate=None if agreed is None else str(agreed.quantize(_RATE_QUANTUM)),
            closed=st.exchange.closed,
            base=_currency(st.base),
            totals=[
                CurrencyCentsOut(currency=c, cents=to_cents(v))
                for c, v in sorted(st.totals.items())
            ],
            pending_cents=to_cents(st.pending),
            pending_currency=_currency(st.pending_currency),
            pending_dop_cents=to_cents(st.pending_dop),
            needs_agreed_rate=agreed is None and st.first_pair_only and not st.exchange.closed,
            legs=[LinkedTxOut.of(leg) for leg in legs],
        )


class TxOut(BaseModel):
    fingerprint: str
    day: str
    merchant: str
    description: str
    category: str
    category_id: int | None  # None: a category that no longer exists (should not happen)
    kind: Kind
    original_category: str
    account: str
    account_label: str
    amount_cents: int
    currency: str
    amount_dop_cents: int | None
    one_off: bool
    corrected: bool
    merchant_year_count: int
    suggested_one_off: bool
    one_off_reasons: list[str]
    one_off_dismissed: bool
    note: str
    # Links: "shared" (amount_cents is your part; gross_cents, the statement amount),
    # "reimbursement", "exchange" or "" (none).
    link: str
    link_id: int | None  # id of the saved link (also when dormant)
    can_share: bool  # can be marked as a shared expense
    can_reimburse: bool  # can be the reimbursement of a shared expense
    can_exchange: bool  # can be a leg of a currency exchange
    gross_cents: int | None
    pending_cents: int  # owed to you on this expense (in a shared group); 0 otherwise
    # The row's shared group, as expense or as reimbursement (null: none or dormant).
    shared: SharedOut | None
    reimbursement_of: LinkedTxOut | None  # the first expense of the group it reimburses
    suggested_group: GroupRefOut | None  # "Reimbursement of <group>?"
    exchange: ExchangeOut | None
    suggested_exchange_with: LinkedTxOut | None
    can_invest: bool  # a bank debit that can be a contribution ("It is an investment…")
    can_invest_credit: bool  # a bank credit that can come from an investment
    # The row's investment (null: none or no contributions present), its role in it
    # ("contribution", "return", "capital", "mixed") and, in a mixed one, the capital part.
    investment: InvestmentRefOut | None
    investment_role: str
    investment_capital_cents: int | None
    suggested_investment: InvestmentHintOut | None
    # Cash box: whether it can be marked as a stored withdrawal or a deposit, its role
    # ("stored", "deposit" or "") and, in a deposit, the currency and what left the box (null:
    # no rate).
    can_store: bool
    can_deposit: bool
    cash_box_role: str
    cash_box_currency: str | None
    cash_box_amount_cents: int | None
    # A movement entered by hand in the box: its id (null if it comes from a statement).
    cash_entry_id: int | None

    @classmethod
    def of(cls, v: TxView) -> TxOut:
        row = v.links
        return cls(
            fingerprint=v.fingerprint,
            day=v.day.isoformat(),
            merchant=v.merchant,
            description=v.description,
            category=v.category,
            category_id=v.category_id,
            kind=v.kind,
            original_category=v.original_category,
            account=v.account,
            account_label=v.account_label,
            amount_cents=to_cents(v.amount),
            currency=v.currency,
            amount_dop_cents=_cents(v.amount_dop),
            one_off=v.one_off,
            corrected=v.corrected,
            merchant_year_count=v.merchant_year_count,
            suggested_one_off=v.suggested_one_off,
            one_off_reasons=list(v.one_off_reasons),
            one_off_dismissed=v.one_off_dismissed,
            note=v.note,
            link=row.kind,
            link_id=row.link_id,
            can_share=row.can_share,
            can_reimburse=row.can_reimburse,
            can_exchange=row.can_exchange,
            gross_cents=_cents(v.gross),
            pending_cents=0 if row.expense is None else to_cents(row.expense.pending),
            shared=None if row.group is None else SharedOut.of(row.group),
            reimbursement_of=_linked(row.reimbursement_of),
            suggested_group=None
            if row.suggested_group is None
            else GroupRefOut.ref(row.suggested_group),
            exchange=None
            if row.exchange is None
            else ExchangeOut.of(row.exchange, row.exchange_legs),
            suggested_exchange_with=_linked(row.suggested_exchange_with),
            can_invest=row.can_invest,
            can_invest_credit=row.can_invest_credit,
            investment=None if row.investment is None else InvestmentRefOut.ref(row.investment),
            investment_role=row.investment_role,
            investment_capital_cents=_cents(row.investment_capital),
            suggested_investment=None
            if row.suggested_investment is None
            else InvestmentHintOut(
                **InvestmentRefOut.ref(row.suggested_investment.state).model_dump(),
                kind=row.suggested_investment.kind,
            ),
            can_store=row.can_store,
            can_deposit=row.can_deposit,
            cash_box_role=row.cash_box_role,
            cash_box_currency=row.cash_box_currency,
            cash_box_amount_cents=_cents(row.cash_box_amount),
            cash_entry_id=cash_box.entry_id(v.fingerprint),
        )


class OneOffSuggestionOut(BaseModel):
    fingerprint: str
    day: str
    merchant: str
    description: str
    account_label: str
    amount_cents: int
    currency: str
    amount_dop_cents: int
    reasons: list[str]

    @classmethod
    def of(cls, v: one_offs_view.SuggestionView) -> OneOffSuggestionOut:
        s = v.suggestion
        return cls(
            fingerprint=s.fingerprint,
            day=s.day.isoformat(),
            merchant=s.merchant,
            description=s.description,
            account_label=v.account_label,
            amount_cents=to_cents(s.amount),
            currency=s.currency,
            amount_dop_cents=to_cents(s.amount_dop),
            reasons=list(s.reasons),
        )


class DismissBody(BaseModel):
    dismissed: StrictBool


class DismissOut(BaseModel):
    fingerprint: str
    dismissed: bool


_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
Name = Annotated[str, Field(min_length=1, max_length=catalog.NAME_MAX)]
Color = Annotated[str, Field(pattern=_COLOR_PATTERN)]
Keywords = Annotated[
    list[Annotated[str, Field(max_length=catalog.KEYWORD_MAX)]],
    Field(max_length=catalog.KEYWORDS_MAX),
]


class CategoryOut(BaseModel):
    id: int
    name: str
    kind: Kind
    color: str | None  # None: the automatic color (by rank in the Summary)
    hidden: bool
    builtin: bool
    builtin_key: str | None  # stable identity of a system category ("THIRD_PARTY")
    keywords: list[str]
    count_year: int

    @classmethod
    def of(cls, v: categories_view.CategoryView) -> CategoryOut:
        c = v.category
        return cls(
            id=c.id,
            name=c.name,
            kind=c.kind,
            color=c.color,
            hidden=c.hidden,
            builtin=c.builtin,
            builtin_key=c.builtin_key,
            keywords=list(c.keywords),
            count_year=v.count_year,
        )


class CategoryBody(BaseModel):
    name: Name
    kind: Kind
    color: Color | None = None
    keywords: Keywords = []


class CategoryPatch(BaseModel):
    """Absent fields do not change; `color: null` goes back to the automatic color."""

    name: Name | None = None
    kind: Kind | None = None
    color: Color | None = None
    hidden: StrictBool | None = None
    keywords: Keywords | None = None


class PreviewBody(BaseModel):
    keywords: Keywords


class PreviewOut(BaseModel):
    count: int
    total_cents: int
    unconverted_usd_cents: int
    conflicts: int

    @classmethod
    def of(cls, p: categories_view.Preview) -> PreviewOut:
        return cls(
            count=p.count,
            total_cents=to_cents(p.total),
            unconverted_usd_cents=to_cents(p.unconverted_usd),
            conflicts=p.conflicts,
        )


class TransactionsOut(BaseModel):
    items: list[TxOut]
    count: int
    total_cents: int  # the list's spending, only rows converted to RD$
    income_cents: int  # the list's income in RD$, as a positive number
    unconverted_usd_cents: int  # US$ spending without the month's rate: not in total_cents


class StatementLineOut(BaseModel):
    period_start: str | None
    period_end: str
    currency: str
    charges_cents: int | None
    payments_cents: int | None
    balance_cents: int | None
    due_date: str | None
    minimum_payment_cents: int | None
    paid_full: bool | None
    left_over_cents: int | None
    paid_late: bool
    next_interest_cents: int
    printout: bool  # a portal printout (Transactions), not a bank statement

    @classmethod
    def of(cls, line: accounts_view.StatementLine) -> StatementLineOut:
        return cls(
            period_start=_iso(line.period_start),
            period_end=line.period_end.isoformat(),
            currency=line.currency,
            charges_cents=_cents(line.charges),
            payments_cents=_cents(line.payments),
            balance_cents=_cents(line.balance),
            due_date=_iso(line.due_date),
            minimum_payment_cents=_cents(line.minimum_payment),
            paid_full=line.paid_full,
            left_over_cents=_cents(line.left_over),
            paid_late=line.paid_late,
            next_interest_cents=to_cents(line.next_interest),
            printout=line.printout,
        )


class CurrencyCentsOut(BaseModel):
    currency: str
    cents: int


class DuePaymentOut(BaseModel):
    due_date: str
    amounts: list[CurrencyCentsOut]
    minimums: list[CurrencyCentsOut]
    text: str

    @classmethod
    def of(cls, p: accounts_view.DuePayment) -> DuePaymentOut:
        return cls(
            due_date=p.due_date.isoformat(),
            amounts=_currency_cents(p.amounts),
            minimums=_currency_cents(p.minimums),
            text=accounts_view.due_text(p),
        )


def _currency_cents(values: list[tuple[str, Decimal]]) -> list[CurrencyCentsOut]:
    return [CurrencyCentsOut(currency=c, cents=to_cents(v)) for c, v in values]


class AccountOut(BaseModel):
    key: str
    kind: str
    label: str
    cut_day: int | None
    currencies: list[str]
    latest: list[StatementLineOut]
    missing_statement: bool
    statements: list[StatementLineOut]
    to_pay: DuePaymentOut | None

    @classmethod
    def of(cls, v: accounts_view.AccountView) -> AccountOut:
        return cls(
            key=v.key,
            kind=v.kind,
            label=v.label,
            cut_day=v.cut_day,
            currencies=v.currencies,
            latest=[StatementLineOut.of(x) for x in v.latest],
            missing_statement=v.missing_statement,
            statements=[StatementLineOut.of(x) for x in v.statements],
            to_pay=None if v.to_pay is None else DuePaymentOut.of(v.to_pay),
        )


class InterestLineOut(BaseModel):
    key: str
    label: str
    currency: str
    total_cents: int


class NextDueOut(DuePaymentOut):
    key: str
    label: str


class InterestOut(BaseModel):
    year: int
    lines: list[InterestLineOut]
    total_dop_cents: int
    unconverted_usd_cents: int
    next_due: NextDueOut | None

    @classmethod
    def of(cls, y: interest_view.InterestYear) -> InterestOut:
        due = y.next_due
        return cls(
            year=y.year,
            lines=[
                InterestLineOut(
                    key=x.key, label=x.label, currency=x.currency, total_cents=to_cents(x.total)
                )
                for x in y.lines
            ],
            total_dop_cents=to_cents(y.total_dop),
            unconverted_usd_cents=to_cents(y.unconverted_usd),
            next_due=None
            if due is None
            else NextDueOut(**DuePaymentOut.of(due).model_dump(), key=due.key, label=due.label),
        )


class EditBody(BaseModel):
    category: str | None = None  # by name (as before); `category_id` wins if both come
    category_id: int | None = None
    one_off: bool | None = None
    scope: Literal["transaction", "merchant"] = "transaction"
    note: str | None = Field(default=None, max_length=corrections.NOTE_MAX)  # "" clears it
    # Absent = leave it; null = no longer shared (unlinks its reimbursements).
    shared: SharedBody | None = None
    written_off: StrictBool | None = None  # "They won't pay me back"


Person = Annotated[str, Field(max_length=links.PERSON_MAX)]


class SplitBody(BaseModel):
    """Exactly one form: `people` ("We were N"), `my_share_cents` or `for_other`."""

    people: int | None = Field(default=None, ge=2, le=100)
    my_share_cents: int | None = Field(default=None, gt=0, le=10**12)
    for_other: StrictBool = False


class SharedBody(SplitBody):
    """The expense's split. If the expense is not in a group: `link_id` adds it to that group;
    without it, a new one is created (`with_whom`: "With whom", optional)."""

    link_id: int | None = None
    with_whom: Person | None = None


class GroupPatch(BaseModel):
    """Absent fields do not change; "" or null clears the name or "With whom"."""

    name: Person | None = None
    with_whom: Person | None = None
    written_off: StrictBool | None = None


class GroupExpenseBody(BaseModel):
    fingerprint: str = Field(min_length=1, max_length=64)
    split: SplitBody


class ManualBody(BaseModel):
    amount_cents: int = Field(gt=0, le=10**12)
    day: date
    person: Person | None = None
    place: Person | None = None  # empty or "Efectivo": in cash
    currency: Currency | None = None  # null: that of the group's oldest expense


class ReimbursementBody(BaseModel):
    """An imported credit (`credit`, its fingerprint) or one entered by hand (`manual`)."""

    credit: str | None = Field(default=None, min_length=1, max_length=64)
    manual: ManualBody | None = None


class GroupCandidateOut(GroupRefOut):
    primary: bool


class CandidatesOut(BaseModel):
    credits: list[CandidateOut]  # credits that can reimburse this expense's group
    groups: list[GroupCandidateOut]  # groups with something pending that this credit can reimburse
    places: list[str]  # "where" values used before in manual reimbursements


Fingerprints = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=64)]], Field(min_length=1, max_length=50)
]
AgreedRate = Annotated[Decimal, Field(gt=0, lt=Decimal("1e6"), allow_inf_nan=False)]


class ExchangeBody(BaseModel):
    """Legs of the new exchange (at least one in each currency) and the agreed rate, if any."""

    fingerprints: Fingerprints
    agreed_rate: AgreedRate | None = None


class LegsBody(BaseModel):
    fingerprints: Fingerprints


class ExchangePatch(BaseModel):
    """Absent fields do not change; `agreed_rate: null` goes back to the implied rate."""

    agreed_rate: AgreedRate | None = None
    closed: StrictBool | None = None


class RateBody(BaseModel):
    value: Decimal = Field(gt=0, lt=Decimal("1e6"), allow_inf_nan=False)


class MarkBody(BaseModel):
    merchant: str = Field(min_length=1, max_length=200)
    currency: Currency
    status: MarkStatus | None
    # Absent = leave the installments; explicit null = clear them (see `model_fields_set`).
    installments_left: int | None = Field(default=None, ge=0, le=600)
    # The "Group in Recurring" chosen by hand, likewise: absent leaves it, null goes back to the
    # category's.
    group: GroupKey | None = None


class PriceChangeOut(BaseModel):
    before_cents: int
    after_cents: int
    day: str

    @classmethod
    def of(cls, change: PriceChange) -> PriceChangeOut:
        return cls(
            before_cents=to_cents(change.before),
            after_cents=to_cents(change.after),
            day=change.day.isoformat(),
        )


class RecurringItemOut(BaseModel):
    merchant: str
    currency: Currency
    category: str
    group: str
    cadence: Cadence
    status: recurring_view.Status
    typical_cents: int  # in the charge's original currency
    variable: bool
    monthly_cents: int | None  # RD$
    yearly_cents: int | None  # RD$
    first_day: str
    last_day: str
    charges: int
    price_change: PriceChangeOut | None
    installments_left: int | None
    mark: MarkStatus | None
    charged_after_cancel: bool
    name: str  # visible name (the provider's); `merchant` is the key it is marked with
    members: list[str]  # the series' merchants (more than one: it can be "Split")
    provider: bool  # a provider from the list
    extras_year_cents: int  # loans: the year's extra payments, in the charge's currency
    group_key: str  # stable group key (empty in Installments)

    @classmethod
    def of(cls, v: recurring_view.RecurringView) -> RecurringItemOut:
        return cls(
            name=v.name or v.merchant,
            members=list(v.members or (v.merchant,)),
            provider=v.provider,
            extras_year_cents=to_cents(v.extras_year),
            group_key=v.group_key,
            merchant=v.merchant,
            currency=_currency(v.currency),
            category=v.category,
            group=v.group,
            cadence=v.cadence,
            status=v.status,
            typical_cents=to_cents(v.typical),
            variable=v.variable,
            monthly_cents=_cents(v.monthly_dop),
            yearly_cents=_cents(v.yearly_dop),
            first_day=v.first_day.isoformat(),
            last_day=v.last_day.isoformat(),
            charges=v.charges,
            price_change=None if v.price_change is None else PriceChangeOut.of(v.price_change),
            installments_left=v.installments_left,
            mark=v.mark,
            charged_after_cancel=v.charged_after_cancel,
        )


class GroupTotalOut(BaseModel):
    group: str
    monthly_cents: int
    yearly_cents: int
    count: int


class AlertOut(BaseModel):
    kind: recurring_view.AlertKind
    merchant: str
    currency: Currency
    detail: str
    name: str


class ProviderOut(BaseModel):
    key: str
    name: str


class RecurringOut(BaseModel):
    as_of: str | None
    first_month: str | None
    monthly_cents: int
    groups: list[GroupTotalOut]
    items: list[RecurringItemOut]
    dismissed: list[RecurringItemOut]
    alerts: list[AlertOut]
    providers: list[ProviderOut]  # the fixed list (targets of "Merge with…")

    @classmethod
    def of(cls, o: recurring_view.Overview) -> RecurringOut:
        return cls(
            providers=[ProviderOut(key=p.key, name=p.name) for p in provider_list.PROVIDERS],
            as_of=_iso(o.as_of),
            first_month=o.first_month,
            monthly_cents=to_cents(o.monthly_dop),
            groups=[
                GroupTotalOut(
                    group=g.group,
                    monthly_cents=to_cents(g.monthly_dop),
                    yearly_cents=to_cents(g.yearly_dop),
                    count=g.count,
                )
                for g in o.groups
            ],
            items=[RecurringItemOut.of(v) for v in o.items],
            dismissed=[RecurringItemOut.of(v) for v in o.dismissed],
            alerts=[
                AlertOut(
                    kind=a.kind,
                    merchant=a.merchant,
                    currency=_currency(a.currency),
                    detail=a.detail,
                    name=a.name or a.merchant,
                )
                for a in o.alerts
            ],
        )


class PendingItemOut(BaseModel):
    kind: Literal["shared", "exchange"]
    fingerprint: str  # the group's first expense or the first leg: opens its screen
    day: str
    merchant: str  # a group: its title (name, "With whom" or the first expense's merchant)
    account_label: str
    who: str
    pending_cents: int
    currency: Currency
    pending_dop_cents: int | None  # None: in US$ without any rate
    age_days: int
    rate: str | None  # RD$ per US$ of `pending_dop_cents`: the exchange's or the latest
    expense_count: int  # the group's expenses (1 in an exchange)
    parts: list[CurrencyCentsOut]  # what is pending by currency (a group can have both)

    @classmethod
    def of(cls, item: pending_view.PendingItem) -> PendingItemOut:
        return cls(
            kind=item.kind,
            fingerprint=item.fingerprint,
            day=item.day.isoformat(),
            merchant=item.merchant,
            account_label=item.account_label,
            who=item.who,
            pending_cents=to_cents(item.pending),
            currency=_currency(item.currency),
            pending_dop_cents=_cents(item.pending_dop),
            age_days=item.age_days,
            rate=None if item.rate is None else str(item.rate.quantize(_RATE_QUANTUM)),
            expense_count=item.expense_count,
            parts=_currency_cents(list(item.parts))
            if item.parts
            else _currency_cents([(item.currency, item.pending)]),
        )


class UnconvertedOut(BaseModel):
    owed_to_me: int
    i_owe: int


class PendingOut(BaseModel):
    owed_to_me_dop_cents: int
    i_owe_dop_cents: int
    net_dop_cents: int
    unconverted_usd_cents: UnconvertedOut  # US$ without any rate: apart from the RD$ figures
    rate_month: str | None  # month of the latest rate (the one for shared US$ items)
    rate: RateOut | None
    owed_to_me: list[PendingItemOut]
    i_owe: list[PendingItemOut]

    @classmethod
    def of(cls, p: pending_view.Pending) -> PendingOut:
        owed = [PendingItemOut.of(i) for i in p.owed_to_me]
        owing = [PendingItemOut.of(i) for i in p.i_owe]
        # The figures add the rows' cents: they match what is shown.
        owed_total = sum(i.pending_dop_cents or 0 for i in owed)
        owing_total = sum(i.pending_dop_cents or 0 for i in owing)
        return cls(
            owed_to_me_dop_cents=owed_total,
            i_owe_dop_cents=owing_total,
            net_dop_cents=owed_total - owing_total,
            unconverted_usd_cents=UnconvertedOut(
                owed_to_me=to_cents(p.unconverted_owed_to_me),
                i_owe=to_cents(p.unconverted_i_owe),
            ),
            rate_month=None if p.rate is None else p.rate.month_used,
            rate=None if p.rate is None else RateOut.of(p.rate),
            owed_to_me=owed,
            i_owe=owing,
        )
