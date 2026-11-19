// Budget and reserves (pure view logic). The rules live on the server
// (src/michelito/analysis/budget.py and reserves.py); here, the types and how each thing is said.
import { t } from '@/i18n'
import { formatDop } from './money'
import { monthName, monthPhrase } from './months'

export interface BudgetWarning {
  habitual_cents: number
  basis_cents: number
  up: boolean
}

/** One category of the month (GET /api/budget). */
export interface BudgetLine {
  category_id: number
  category: string
  cap_cents: number | null // null: no budget
  manual: boolean
  spent_cents: number // against the cap (without one-off expenses or what reserves cover)
  one_offs_cents: number
  covered_cents: number
  without_rate: number
  over_cents: number // how much it goes over the cap, exact
  passed: boolean // went over by more than max(5 %, RD$ 500): counts as over
  refunds_cents: number // refunded in excess in the month (spending stays at 0)
  habitual_cents: number | null
  warning: BudgetWarning | null
  active: boolean
}

export interface Budget {
  active: boolean
  month: string
  lines: BudgetLine[]
  cap_cents: number
  spent_cents: number
  over_count: number
  over_cents: number
  reference_months: string[]
  filtered: boolean // with an account filter: caps of all accounts, spending of the chosen ones
  missing: string[] // accounts without the month's complete statement
}

export interface ReserveMember {
  fingerprint: string
  day: string
  month: string
  merchant: string
  amount_cents: number
  currency: string
  amount_dop_cents: number | null
}

export interface Reserve {
  id: number
  name: string
  amount_cents: number
  category_id: number
  category: string
  due_month: string
  every_months: number | null // null: only once
  multiple: boolean
  next_due: string | null
  monthly_cents: number
  year_spent_cents: number
  year_estimated_cents: number
  year_without_rate: number
  paid: boolean // the next due date already has its expense linked
  members: ReserveMember[]
}

export interface ReserveSuggestion {
  key: string
  name: string
  amount_cents: number
  category_id: number
  category: string
  due_month: string
  every_months: number
  multiple: boolean
  reason: string
}

export interface Reserves {
  items: Reserve[]
  suggestions: ReserveSuggestion[]
  monthly_cents: number
}

export interface ReserveBody {
  name: string
  amount_cents: number
  category_id: number
  due_month: string
  every_months: number | null
  multiple: boolean
  source?: string | null
}

export interface ReserveRef {
  id: number
  name: string
  category: string
  next_due: string | null
  suggested: boolean
}

/** The detail's "Reserve" section (GET /api/transactions/{fingerprint}/reserve). */
export interface TxReserve {
  reserve: ReserveRef | null
  options: ReserveRef[]
  can_link: boolean
  reason: string
}

export interface MembersResult {
  applied: string[]
  skipped: { fingerprint: string; reason: string; message: string }[]
  entry_id: number | null
}

export interface BudgetOverview {
  active: boolean
  over_count: number | null // null with an account filter: overs are not counted
  over_cents: number
  missing: string[]
  monthly_cents: number
  reserves: number
  upcoming: { id: number; name: string; due_month: string; amount_cents: number }[]
}

export const BUDGET_PATH = '/budget'

/** How often: the three plans the form offers (the server accepts 1 to 12 months). */
export type Schedule = 'yearly' | 'halfYearly' | 'once'
export const SCHEDULES: { value: Schedule; label: string }[] = [
  { value: 'yearly', label: t('budget.schedule.yearly') },
  { value: 'halfYearly', label: t('budget.schedule.halfYearly') },
  { value: 'once', label: t('budget.schedule.once') },
]

export function scheduleMonths(schedule: Schedule): number | null {
  return schedule === 'yearly' ? 12 : schedule === 'halfYearly' ? 6 : null
}

export function scheduleOf(every: number | null): Schedule {
  return every === null ? 'once' : every === 6 ? 'halfYearly' : 'yearly'
}

/** "Every year in January", "Every 6 months (March and September)", "Once, in December 2026". */
export function scheduleText(reserve: Pick<Reserve, 'every_months' | 'due_month'>): string {
  const { every_months: every, due_month: due } = reserve
  if (every === null) return t('budget.scheduleText.once', { month: monthPhrase(due) })
  if (every === 12) return t('budget.scheduleText.yearly', { month: monthName(due) })
  if (every === 6) {
    const second = shiftMonth(due, 6)
    const [a, b] = [due, second].sort((x, y) => Number(x.slice(5)) - Number(y.slice(5)))
    return t('budget.scheduleText.halfYearly', { first: monthName(a), second: monthName(b) })
  }
  return t('budget.scheduleText.every', { every, month: monthPhrase(due) })
}

/** "2026-11" + 3 → "2027-02". */
export function shiftMonth(month: string, count: number): string {
  const index = Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7)) - 1 + count
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, '0')}`
}

/** "Due in March 2026" or "Already due" (a one-time reserve already past). */
export function dueText(reserve: Pick<Reserve, 'next_due'>): string {
  return reserve.next_due === null
    ? t('budget.due.past')
    : t('budget.due.in', { month: monthPhrase(reserve.next_due) })
}

/** Written RD$ amounts ("3,500", "3500.50", "RD$ 3,500") to cents; null if it is not a valid amount. */
export function parseDopAmount(text: string): number | null {
  const clean = text.replace(/RD\$|\s/g, '').replace(/,/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  return Math.round(Number(clean) * 100)
}

/** The cap as written in the field ("16500"); empty without a cap. */
export function capInput(cents: number | null): string {
  return cents === null ? '' : String(Math.round(cents / 100))
}

/** What the bar shows: "RD$ 12,000 of RD$ 10,000" or "RD$ 4,000 · no budget". */
export function spentText(line: Pick<BudgetLine, 'spent_cents' | 'cap_cents'>): string {
  const spent = formatDop(line.spent_cents)
  if (line.cap_cents === null) return t('budget.spent.noCap', { spent })
  return t('budget.spent.ofCap', { spent, cap: formatDop(line.cap_cents) })
}

/** Width of the bar in % (0 to 100) and whether it went over the cap. */
export function barShare(line: Pick<BudgetLine, 'spent_cents' | 'cap_cents'>): {
  share: number
  over: boolean
} {
  if (line.cap_cents === null) return { share: 0, over: false }
  if (line.cap_cents <= 0) {
    const spent = line.spent_cents > 0
    return { share: spent ? 100 : 0, over: spent }
  }
  const ratio = line.spent_cents / line.cap_cents
  return { share: Math.max(0, Math.min(100, Math.round(ratio * 100))), over: ratio > 1 }
}

/** What goes beside the bar: one-off expenses, what is covered and what is in US$ without a rate. */
export function asideNotes(
  line: Pick<BudgetLine, 'one_offs_cents' | 'covered_cents' | 'without_rate'> &
    Partial<Pick<BudgetLine, 'refunds_cents'>>,
): string[] {
  const notes = []
  if (line.refunds_cents) {
    notes.push(t('budget.aside.refunds', { amount: formatDop(line.refunds_cents) }))
  }
  if (line.one_offs_cents) {
    notes.push(t('budget.aside.oneOffs', { amount: formatDop(line.one_offs_cents) }))
  }
  if (line.covered_cents) {
    notes.push(t('budget.aside.covered', { amount: formatDop(line.covered_cents) }))
  }
  if (line.without_rate) notes.push(t('budget.aside.withoutRate', { count: line.without_rate }))
  return notes
}

/** "Delivery's usual went up to RD$ 25,000; update the cap?". */
export function warningText(line: Pick<BudgetLine, 'category' | 'warning' | 'cap_cents'>): string {
  const found = line.warning
  if (!found) return ''
  const category = line.category
  if (found.habitual_cents === 0) return t('budget.warning.droppedToZero', { category })
  const amount = formatDop(found.habitual_cents)
  if (line.cap_cents === null) {
    return found.up
      ? t('budget.warning.upSetCap', { category, amount })
      : t('budget.warning.downSetCap', { category, amount })
  }
  return found.up
    ? t('budget.warning.upUpdateCap', { category, amount })
    : t('budget.warning.downUpdateCap', { category, amount })
}

/** "Budget: 2 categories over (+RD$ 4,800)" or "Budget: everything within the cap"; with an
 * account filter they are not counted (the caps are for all accounts) and with partial data it
 * does not claim everything is within. */
export function overviewText(
  overview: Pick<BudgetOverview, 'over_count' | 'over_cents'> &
    Partial<Pick<BudgetOverview, 'missing'>>,
): string {
  if (overview.over_count === null) return t('budget.overview.filtered')
  if (overview.over_count === 0) {
    return overview.missing?.length ? t('budget.overview.noneYet') : t('budget.overview.allWithin')
  }
  return t('budget.overview.over', {
    count: overview.over_count,
    amount: formatDop(overview.over_cents),
  })
}

/** "after setting aside for your reserves (RD$ 2,600/month): RD$ 14,400"; null without reserves
 * or without "You kept". The main number does not change. */
export function afterReservesNote(netCents: number | null, monthlyCents: number): string | null {
  if (netCents === null || monthlyCents <= 0) return null
  return t('budget.afterReserves', {
    monthly: formatDop(monthlyCents),
    left: formatDop(netCents - monthlyCents),
  })
}

/** "This year: RD$ 3,400 of RD$ 3,500". */
export function yearText(
  reserve: Pick<Reserve, 'year_spent_cents' | 'year_estimated_cents'>,
): string {
  return t('budget.year', {
    spent: formatDop(reserve.year_spent_cents),
    estimated: formatDop(reserve.year_estimated_cents),
  })
}

/** The body to create a reserve from a suggestion. */
export function bodyFromSuggestion(item: ReserveSuggestion): ReserveBody {
  return {
    name: item.name,
    amount_cents: item.amount_cents,
    category_id: item.category_id,
    due_month: item.due_month,
    every_months: item.every_months,
    multiple: item.multiple,
    source: item.key,
  }
}

/** "Create reserve “December: Entertainment” for ≈ RD$ 18,000 (due in December)?". */
export function suggestionText(item: ReserveSuggestion): string {
  return t('budget.suggestion', {
    name: item.name,
    amount: formatDop(item.amount_cents),
    month: monthName(item.due_month),
  })
}

/** "3 linked to «Christmas»" and, if any was skipped, how many and why. */
export function membersResultText(result: MembersResult, name: string): string {
  const head = t('budget.members.linked', { count: result.applied.length, name })
  if (result.skipped.length === 0) return t('budget.members.done', { head })
  const reasons = [...new Set(result.skipped.map((s) => s.message))].join('; ')
  const skipped = t('budget.members.skipped', { count: result.skipped.length })
  return t('budget.members.withSkipped', { head, skipped, reasons })
}

/** "Partial data: the statement of VISA ···4242 is missing"; null if none is missing. */
export function missingText(missing: readonly string[]): string | null {
  if (missing.length === 0) return null
  return t('budget.missing', { accounts: missing.join(', ') })
}

/** The line next to the caps with an account filter. */
export const FILTERED_NOTE = t('budget.filteredNote')
