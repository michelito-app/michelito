// Types of the local API (src/michelito/web/schemas.py): money in whole cents, ISO dates and
// the rate as text with 4 decimals.
import type { LedgerRef } from './sharedApi'

export interface MonthOption {
  month: string
  label: string
  partial: boolean
}

export interface Rate {
  value: string
  month_used: string
  source: string
}

export interface SavedRate extends Rate {
  month: string
}

export interface Coverage {
  key: string
  label: string
  through: string | null
  complete: boolean
}

export interface CategoryLine {
  category: string
  amount_cents: number
  habitual_cents: number | null
  diff_cents: number | null
  same: boolean
  share: number
  one_offs_cents: number
  purchases: number
  habitual_purchases: number | null
}

export interface Change {
  category: string
  diff_cents: number
  one_offs_cents: number
  purchases: number
  habitual_purchases: number | null
}

/** Kind of a category: only expenses count as spending; transfers count as nothing. */
export type Kind = 'income' | 'expense' | 'transfer'

/** GET /api/categories: hidden ones too (the pickers leave them out). */
export interface Category {
  id: number
  name: string
  kind: Kind
  color: string | null // null: automatic color (by rank in the Summary)
  hidden: boolean
  builtin: boolean // system category: cannot be deleted nor change kind
  builtin_key: string | null // stable identity of a system category ("THIRD_PARTY")
  keywords: string[]
  count_year: number
}

export interface CategoryBody {
  name: string
  kind: Kind
  color?: string | null
  keywords?: string[]
}

/** What is absent does not change; `color: null` goes back to the automatic color. */
export interface CategoryPatch {
  name?: string
  kind?: Kind
  color?: string | null
  hidden?: boolean
  keywords?: string[]
}

/** POST /api/categories/{id}/preview: what saving those keywords would move. */
export interface KeywordPreview {
  count: number
  total_cents: number // in RD$, without the US$ that have no rate
  unconverted_usd_cents: number
  conflicts: number
}

export interface MonthTotal {
  month: string
  label: string
  total_cents: number // expenses
  income_cents: number
  partial: boolean // month in progress for the selected accounts: drawn in the light color
  // Unusual month against the usual (> max(30 %, RD$ 10,000) against the median of the 6
  // previous complete months); null if it is not or is not compared.
  spent_flag: Direction | null
  spent_habitual_cents: number | null // null with fewer than three reference months
  income_flag: Direction | null
  income_habitual_cents: number | null
}

export type Direction = 'up' | 'down'

/** A merchant that explains an unusual month ("What happened"). */
export interface Contribution {
  side: 'expense' | 'income'
  merchant: string
  category: string
  amount_cents: number // the merchant's amount in the month, RD$
  habitual_cents: number // its median in the reference months
  diff_cents: number
  count: number
  fingerprint: string // its largest transaction of the month; "" if it did not appear
  day: string | null
  description: string
}

export interface AccountTotal {
  key: string
  label: string
  total_cents: number
  usd_cents: number
}

export interface Summary {
  option: MonthOption
  coverage: Coverage[]
  total_cents: number // expenses
  income_cents: number
  third_party_cents: number // transfers to third parties in the month: not spending, but money going out
  net_cents: number | null // income − expenses − third parties; null: only cards selected
  savings_rate: number | null // null if the income is negligible or incomplete
  income_through: string | null // ISO: a bank account that ends before the end of the month
  regular_total_cents: number
  one_offs_cents: number
  habitual_cents: number | null
  usd_cents: number
  usd_in_dop_cents: number | null
  rate: Rate | null
  categories: CategoryLine[]
  changes: Change[]
  trend: MonthTotal[]
  by_account: AccountTotal[]
  needs_income: boolean // no bank account selected (cards only): no flow to show
  to_cards_cents: number // card payments from the selected accounts if some card is missing (approx.)
  to_own_cents: number // "Between my accounts" leaving the selected ones if some is missing (approx.)
  owed_cents: number // owed to you: pending from the month's shared expenses (RD$)
  exchanges_pending_cents: number // open currency exchanges of the month: pending in RD$
  what_happened: Contribution[] // "What happened": empty if the month is not unusual
  invested_cents: number // contributions to investments in the month (RD$): they do not reduce what was left over
  cash_box_cents: number // withdrawals of the month stored in the cash box (RD$): they do not reduce it either
  incomes: IncomeLine[] // income of the month per category (crypto apart), largest first
  provisional_cents: number // of the month's spending, what is still without a statement (RD$)
}

/** A category's income of the month, in RD$ (positive). */
export interface IncomeLine {
  category: string
  amount_cents: number
  count: number
}

/** Another transaction mentioned in the detail (a reimbursement, a leg, a suggestion). */
export interface LinkedTx {
  fingerprint: string
  day: string
  merchant: string
  account_label: string
  amount_cents: number // the statement's; a credit is negative
  currency: string
  // A credit in the expense's other currency: what it is worth in the expense's (null if the rate
  // is missing).
  converted_cents?: number | null
  converted_currency?: string | null
  description?: string // as it appears on the statement
}

/** An option of a link picker, in the server's order; `primary`: shown in view (the interface
 * shows the first ones and leaves the rest behind "See more"). */
export interface Candidate extends LinkedTx {
  primary: boolean
}

export interface ExchangeInfo {
  id: number
  rate: string // RD$ per US$ in use, 4 decimals
  implied_rate: string
  agreed_rate: string | null
  closed: boolean
  base: 'DOP' | 'USD'
  totals: CurrencyCents[]
  pending_cents: number
  pending_currency: 'DOP' | 'USD'
  pending_dop_cents: number
  needs_agreed_rate: boolean // no agreed rate and only the first pair: the pending amount says nothing
  legs: LinkedTx[]
}

export type LinkKind =
  | ''
  | 'shared'
  | 'reimbursement'
  | 'group'
  | 'exchange'
  | 'investment'
  | 'cash_box'
  | 'reserve'

export type InvestmentStatus = 'active' | 'closed' | 'written_off'
export type InvestmentRole = 'contribution' | 'return' | 'capital' | 'mixed'
export type CreditRole = Exclude<InvestmentRole, 'contribution'>

/** An investment in a list: title (name, "With whom" or merchant) and capital still to return. */
export interface InvestmentRef {
  id: number
  title: string
  name: string
  with_whom: string
  status: InvestmentStatus
  currency: string // that of the first contribution
  first_fingerprint: string // the first contribution: opens the investment's screen
  pending_cents: number // capital still to return, in `currency`
}

/** "Is it another contribution to…?" or "Is it a payment from…?" of a row. */
export interface InvestmentHint extends InvestmentRef {
  kind: 'possible_contribution' | 'possible_return'
}

/** An entry of an investment, in its currency. */
export interface InvestmentEntry {
  fingerprint: string
  day: string
  merchant: string
  description: string
  account_label: string
  role: InvestmentRole
  amount_cents: number // positive
  currency: string
  capital_cents: number // capital part of a credit (contribution: 0)
  return_cents: number // return part of a credit (contribution: 0)
  excess_cents: number // capital returned beyond what was contributed: it is in return_cents
  counted: boolean // false: in another currency without any rate, it does not add up
}

/** An investment with its figures (in its currency) and its entries. */
export interface Investment extends InvestmentRef {
  written_off: boolean
  first_day: string
  last_activity: string
  last_credit: string | null
  contributed_cents: number
  capital_returned_cents: number
  returns_cents: number // includes what was returned in excess (excess_cents)
  excess_cents: number // capital returned beyond what was contributed: counts as return
  annual_rate: number | null // fraction (0.12 = 12 %); null without invested time
  pending_dop_cents: number | null // capital still to return ≈ RD$; null: US$ without a rate
  unconverted_count: number
  entries: InvestmentEntry[] // by date
}

/** Every investment (`GET /api/investments`) and its totals in ≈ RD$. */
export interface InvestmentList {
  pending_dop_cents: number
  returns_year_dop_cents: number
  year: number
  active_count: number
  unconverted: { pending_usd_cents: number; returns_usd_cents: number } // US$ without a rate
  rate: Rate | null
  investments: Investment[] // latest activity first
}

export interface InvestmentPatch {
  name?: string | null
  with_whom?: string | null
  written_off?: boolean
}

/** The role of a credit; `capital_cents` only in a mixed one (0 < capital < credit). */
export interface RoleBody {
  role: CreditRole
  capital_cents?: number
}

export interface Tx {
  fingerprint: string
  day: string
  merchant: string
  description: string
  category: string
  category_id: number | null
  kind: Kind
  original_category: string
  account: string
  account_label: string
  amount_cents: number
  currency: string
  amount_dop_cents: number | null
  one_off: boolean
  corrected: boolean
  merchant_year_count: number
  suggested_one_off: boolean // looks like a one-off expense (local rules); see one_off_reasons
  one_off_reasons: string[]
  one_off_dismissed: boolean // the user said "Not one-off"; it can be suggested again
  note: string
  // Links: "shared" (a group entry: amount_cents is your share; gross_cents, the statement
  // amount), "reimbursement" (a group payment), "group" (your share of an expense someone else
  // paid: no bank), "exchange", "investment", "cash_box", "reserve" or "".
  link: LinkKind // also when the link is dormant (its expense or a leg no longer appears)
  link_id: number | null
  can_share: boolean // server rules: it can be added to a group ("I paid it")
  can_reimburse: boolean // a credit that can be a payment received in a group
  can_exchange: boolean // it can be a leg of a currency exchange
  gross_cents: number | null
  pending_cents: number // owed to you from this expense
  ledger: LedgerRef | null // the row's place in a shared group
  exchange: ExchangeInfo | null
  suggested_exchange_with: LinkedTx | null
  can_invest: boolean // a bank debit that can be a contribution ("It is an investment…")
  can_invest_credit: boolean // a bank credit that can come from an investment
  investment: InvestmentRef | null // the row's investment
  investment_role: InvestmentRole | '' // its role in it
  investment_capital_cents: number | null // in a mixed credit, the capital part
  suggested_investment: InvestmentHint | null
  can_store: boolean // a withdrawal (a cash debit) that can be stored in the cash box
  can_deposit: boolean // a bank credit that can come from the cash box
  cash_box_role: CashBoxRole | ''
  // In a cash-box deposit: the currency in which it left the box and how much (null: no rate).
  cash_box_currency: string | null
  cash_box_amount_cents: number | null
  cash_entry_id: number | null // recorded by hand in the box (it can be edited and deleted)
  provisional: boolean // from a bank alert: its statement has not arrived yet (badge)
}

export type CashBoxRole = 'stored' | 'deposit'
export type CashEntryKind = 'initial' | 'income' | 'expense'
export type CashLineKind = CashEntryKind | CashBoxRole
export type CashCurrency = 'DOP' | 'USD'

export interface CurrencyAmount {
  currency: string
  amount_cents: number
}

/** An entry into or out of the cash box; `amount_cents` signed in the box's currency (+ in,
 * − out; null: a deposit in another currency without a rate, it does not lower the balance). */
export interface CashLine {
  kind: CashLineKind
  day: string
  fingerprint: string
  entry_id: number | null // recorded by hand: it can be edited and deleted
  currency: string
  amount_cents: number | null
  dop_cents: number | null // ≈ RD$ at its month's rate
  source_amount_cents: number // the transaction as it appears, positive
  source_currency: string
  merchant: string
  account_label: string
  category: string
  category_id: number | null
  note: string
  in_flow: boolean // appears in Transactions (everything but the opening balance)
  group: string | null // the shared group it is in: deleting it removes it from the group
}

/** GET /api/cash-box: balance per currency, ≈ RD$ and its entries. */
export interface CashBox {
  account_key: string
  label: string
  exists: boolean
  balances: CurrencyAmount[] // RD$ first
  total_dop_cents: number
  unconverted: CurrencyAmount[] // without a rate
  negative: CurrencyAmount[] // currencies below zero: a notice is shown
  uncounted: string[] // deposits without a rate
  lines: CashLine[] // the most recent first
}

export interface CashEntryBody {
  kind: CashEntryKind
  day: string
  amount_cents: number
  currency: CashCurrency
  category_id?: number | null
  note?: string | null
}

export interface DepositBody {
  currency?: CashCurrency | null
  amount_cents?: number | null
}

/** A purchase of the month that looks like a one-off expense (GET /api/one-off-suggestions). */
export interface OneOffSuggestion {
  fingerprint: string
  day: string
  merchant: string
  description: string
  account_label: string
  amount_cents: number // in the original currency
  currency: string
  amount_dop_cents: number
  reasons: string[]
}

/** Saved analysis of a month (GET /api/insights). */
export interface Insight {
  month: string
  label: string
  text: string // Markdown, up to 4000 characters
  accounts: string[] | null // accounts analyzed; null: all
  created_at: string
  updated_at: string
  stale: boolean // the data changed since this analysis
}

/** A cell of "Compare months" (GET /api/reports/compare). */
export interface CompareCell {
  amount_cents: number
  habitual_cents: number | null // null: the month is not compared
  flag: Direction | null // it departs from its row's usual
  level: number // 1 to 3 for a rise; 0 otherwise
}

export interface CompareRow {
  key: string // "income", "expenses", "third_party", "net" or the category name
  label: string
  cells: CompareCell[]
}

export interface Comparison {
  months: MonthOption[] // oldest to newest
  totals: CompareRow[]
  categories: CompareRow[]
  incomes: CompareRow[] // income per category (key `income:<name>`)
}

/** What the user decides about a provisional missing from its statement (PUT /api/provisional). */
export type ProvisionalDecision = 'discard' | 'keep' | null

/** "To review" kinds (src/michelito/analysis/review.py). */
export type ReviewKind =
  | 'one_off'
  | 'unusual_income'
  | 'large_third_party'
  | 'duplicate'
  | 'price_up'
  | 'possible_contribution'
  | 'possible_return'
  | 'possible_rule'
  | 'possible_reserve'
  | 'possible_payment'
  | 'unconfirmed'
  | 'reversal'

/** A transaction to review (GET /api/review and /api/review/history). */
export interface ReviewItem {
  kind: ReviewKind
  fingerprint: string
  day: string
  month: string
  merchant: string
  description: string
  account_label: string
  amount_cents: number // in the original currency, positive
  currency: string
  amount_dop_cents: number | null // null: US$ without a rate
  reason: string
  reviewed: boolean
  investment_id?: number | null // possible contribution or payment: the proposed investment
  category_id?: number | null // possible rule: the proposed category
  reserve_id?: number | null // possible reserve: the proposed reserve
  group_id?: number | null // possible payment: the group
  contact_id?: number | null // possible payment: who pays (null: unattributed)
  payment_id?: number | null // possible payment: the unlinked payment it reconciles
  provisional?: boolean // still provisional (from a bank alert): it can be discarded
}

export interface ReviewMark {
  kind: ReviewKind
  fingerprint: string
  reviewed: boolean
}

export interface DismissBody {
  dismissed: boolean
}

export interface DismissResult {
  fingerprint: string
  dismissed: boolean
}

export interface Transactions {
  items: Tx[]
  count: number
  total_cents: number // expenses of the list, only rows converted to RD$
  income_cents: number // income of the list in RD$, positive
  unconverted_usd_cents: number // US$ without the month's rate
}

export interface StatementLine {
  period_start: string | null
  period_end: string
  currency: string
  charges_cents: number | null
  payments_cents: number | null
  balance_cents: number | null
  due_date: string | null
  minimum_payment_cents: number | null
  paid_full: boolean | null // null: no verdict (last cutoff or no balance)
  left_over_cents: number | null // what was left unpaid when paid_full is false
  paid_late: boolean // the balance was covered, but after the due date
  next_interest_cents: number // interest charged on the next statement
  printout: boolean // a print of the portal's Transactions, not a bank statement
}

export interface CurrencyCents {
  currency: string
  cents: number
}

/** What to pay before the due date to avoid interest. `text` is the server's sentence; the
 * interface builds its own and uses it only as a fallback. */
export interface DuePayment {
  due_date: string
  amounts: CurrencyCents[]
  minimums: CurrencyCents[]
  text: string
}

export interface Account {
  key: string
  kind: string
  label: string
  cut_day: number | null
  currencies: string[]
  latest: StatementLine[]
  missing_statement: boolean
  statements: StatementLine[]
  to_pay: DuePayment | null
}

export interface InterestLine {
  key: string
  label: string
  currency: string
  total_cents: number
}

export interface NextDue extends DuePayment {
  key: string
  label: string
}

export interface Interest {
  year: number
  lines: InterestLine[]
  total_dop_cents: number // does not include the US$ without a rate
  unconverted_usd_cents: number
  next_due: NextDue | null // the next payment with a due date from today on
}

/** Something pending (`GET /api/pending`): a shared expense or a currency exchange. */
export interface PendingItem {
  kind: 'shared' | 'exchange'
  fingerprint: string // that of the group's first expense or of the first leg: opens its screen
  day: string
  merchant: string
  account_label: string
  who: string // the group's "With whom" or the note (trimmed); may be empty
  pending_cents: number
  currency: 'DOP' | 'USD'
  pending_dop_cents: number | null // null: in US$ without any rate
  age_days: number
  rate: string | null // RD$ per US$ of `pending_dop_cents`: the exchange's or the most recent one
  expense_count: number // expenses of the group (1 for an exchange)
  parts: CurrencyCents[] // what is pending per currency
  link_id?: number | null // a group: its id (opens /shared/<id>)
}

/** Who owes you and whom you owe, across all months. In RD$, each exchange at its own rate and
 * the shared ones in US$ at the most recent one (`rate`). */
export interface Pending {
  owed_to_me_dop_cents: number
  i_owe_dop_cents: number
  net_dop_cents: number
  unconverted_usd_cents: { owed_to_me: number; i_owe: number } // US$ without any rate
  rate_month: string | null
  rate: Rate | null
  owed_to_me: PendingItem[]
  i_owe: PendingItem[]
}

export interface EditBody {
  category?: string | null
  category_id?: number
  one_off?: boolean | null
  scope?: 'transaction' | 'merchant'
  note?: string
}

/** PATCH /api/transactions: the category ("only this one") of several at once, with a reason. */
export interface BatchBody {
  fingerprints: string[]
  category_id: number
  reason?: string
}

export type SkipReason = 'linked' | 'cash_box' | 'direction' | 'unchanged' | 'unknown'

export interface BatchResult {
  applied: string[]
  skipped: { fingerprint: string; reason: SkipReason; message: string }[]
  entry_id: number | null // the log entry (null if nothing changed)
}

export interface RateBody {
  value: string | number
}

export interface PriceChange {
  before_cents: number
  after_cents: number
  day: string
}

export type RecurringStatus = 'active' | 'inactive' | 'cancelled' | 'ended'
export type MarkStatus = 'confirmed' | 'dismissed' | 'cancelled'
export type AlertKind = 'new' | 'price_up' | 'charged_after_cancel'

export interface RecurringItem {
  merchant: string
  currency: string
  category: string
  group: string
  cadence: 'monthly' | 'yearly'
  status: RecurringStatus
  typical_cents: number // in the charge's original currency
  variable: boolean
  monthly_cents: number | null // RD$; null without a rate for the US$
  yearly_cents: number | null
  first_day: string
  last_day: string
  charges: number
  price_change: PriceChange | null
  installments_left: number | null
  mark: MarkStatus | null
  charged_after_cancel: boolean
  name: string // visible name (the provider's); `merchant` is the key it is marked with
  members: string[] // the merchants of the series (more than one: it can be "Separated")
  provider: boolean // a provider from the list
  extras_year_cents: number // loans: extra payments of the year, in the charge's currency
  group_key: string // stable key of the group ('' for installments)
}

export interface GroupTotal {
  group: string
  monthly_cents: number
  yearly_cents: number
  count: number
}

export interface RecurringAlert {
  kind: AlertKind
  merchant: string
  currency: string
  detail: string
  name: string
}

export interface Provider {
  key: string
  name: string
}

export interface Recurring {
  as_of: string | null
  first_month: string | null // month of the first transaction
  monthly_cents: number
  groups: GroupTotal[]
  items: RecurringItem[]
  dismissed: RecurringItem[]
  alerts: RecurringAlert[]
  providers: Provider[] // the fixed list (targets of "Join with…")
}

export type RecurringGroupKey =
  | 'housing'
  | 'loans'
  | 'utilities'
  | 'insurance'
  | 'subscriptions'
  | 'fees'
  | 'other'

/** "It is recurring…" from a transaction (POST /api/transactions/{fingerprint}/recurring). */
export interface TxRecurringBody {
  cadence: 'monthly' | 'yearly'
  group?: RecurringGroupKey | null
  installments_left?: number | null
}

/** What the transaction is for Recurring (GET /api/transactions/{fingerprint}/recurring). */
export interface TxRecurring {
  eligible: boolean
  reason: string // why it cannot be marked ('' if it can)
  key: string
  name: string
  currency: string
  recurring: boolean // already appears in Recurring
  mark: MarkStatus | null
  group: string
  loan: boolean // Loans category: installments are offered
}

/** "Join with…": the merchants of series `merchant` move to series `target`. */
export interface JoinBody {
  merchant: string
  target: string
}

/** `installments_left` absent = do not touch the installments; null = remove them. */
export interface MarkBody {
  merchant: string
  currency: string
  status: MarkStatus | null
  installments_left?: number | null
  /** "Group in Recurring": absent leaves it; null goes back to the category's. */
  group?: RecurringGroupKey | null
}

export class ApiError extends Error {
  readonly status: number
  /** The server's machine-readable reason (`X-Michelito-Error`), when it gives one. */
  readonly code: string | null

  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.status = status
    this.code = code
  }
}

const ERROR_HEADER = 'X-Michelito-Error'

const WRITE_METHODS = new Set(['PATCH', 'PUT', 'POST', 'DELETE'])
const NO_CONTENT = 204

/** Requests `path` from the API; writes carry `X-Michelito: 1` and a JSON body. A 204 (no body)
 * returns `undefined`. */
/** Dispatched on every 401: in hosted mode the session ended (expired or signed out elsewhere)
 * and the mode gate goes back to the sign-in screen. */
export const SIGNED_OUT_EVENT = 'michelito:signed-out'
const UNAUTHORIZED = 401

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  headers.set('X-Michelito', '1')
  if (WRITE_METHODS.has(method)) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, method, headers })
  if (response.status === UNAUTHORIZED) window.dispatchEvent(new Event(SIGNED_OUT_EVENT))
  if (!response.ok) {
    const code = response.headers.get(ERROR_HEADER)
    throw new ApiError(response.status, await errorDetail(response), code)
  }
  if (response.status === NO_CONTENT) return undefined as T
  return (await response.json()) as T
}

/** Like `request`, but the response is text (e.g. the Markdown dossier), with its headers. */
export async function requestText(path: string): Promise<{ text: string; headers: Headers }> {
  const response = await fetch(path, { headers: { 'X-Michelito': '1' } })
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
  return { text: await response.text(), headers: response.headers }
}

/** FastAPI error message: a text `detail`, or pydantic's validation list (its `msg` values are
 * joined). If nothing usable is there, the status text. */
export async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    const message = detailMessage(body.detail)
    if (message) return message
  } catch {
    // The response was not JSON: the status text is used.
  }
  return response.statusText || `error ${response.status}`
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return null
  const messages = detail
    .map((item: unknown) =>
      typeof item === 'object' && item !== null && 'msg' in item ? item.msg : null,
    )
    .filter((msg): msg is string => typeof msg === 'string' && msg !== '')
  return messages.length ? messages.join('; ') : null
}
