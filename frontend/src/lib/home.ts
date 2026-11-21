// The Summary's cards (pure logic): which month opens, the texts of each card, what each card
// shows and where it leads. The components live in components/home.
import { t } from '@/i18n'
import { hrefWithSelection, type Selection, transactionsHref } from './accountFilter'
import type { CategoryLine, Coverage, RecurringItem, Tx } from './api'
import type { BudgetLine } from './budget'
import { BUDGET_PATH } from './budget'
import { formatDop } from './money'
import { chargeText, nextChargeDay } from './recurring'

export const REPORTS_PATH = '/reports'
export const REVIEW_PATH = '/review'
export const RECURRING_PATH = '/recurring'
export const SHARED_GROUPS_PATH = '/shared?view=groups'

// ---- Coverage pill ----

/** "In progress · 2 of 4 accounts closed" or "4 accounts up to date"; null without accounts. */
export function coveragePill(coverage: readonly Coverage[]): string | null {
  if (coverage.length === 0) return null
  const closed = coverage.filter((c) => c.complete).length
  if (closed === coverage.length) return t('home.coverage.allClosed', { count: closed })
  return t('home.coverage.inProgress', { closed, total: coverage.length })
}

// ---- Month spending ----

export type ChangeTone = 'less' | 'more' | 'same'

export interface PaceChange {
  tone: ChangeTone
  text: string
}

/** Up to today against last month up to the same day (or, once the month is `finished`, the
 * whole month against the whole of last month), in whole percent; null when last month had
 * nothing to compare with. */
export function paceChange(
  currentCents: number,
  previousCents: number,
  finished = false,
): PaceChange | null {
  if (previousCents <= 0) return null
  const percent = Math.round((Math.abs(currentCents - previousCents) / previousCents) * 100)
  if (percent === 0) {
    return { tone: 'same', text: finished ? t('home.spending.sameWhole') : t('home.spending.same') }
  }
  if (currentCents < previousCents) {
    const text = finished
      ? t('home.spending.lessWhole', { percent })
      : t('home.spending.less', { percent })
    return { tone: 'less', text }
  }
  const text = finished
    ? t('home.spending.moreWhole', { percent })
    : t('home.spending.more', { percent })
  return { tone: 'more', text }
}

export interface PaceFigures {
  through_day: number
  current_cents: readonly number[]
  total_to_date_cents: number
  previous_same_day_cents: number
  previous_same_day_total_cents: number
  finished: boolean
}

/** The line under the hero number, only when it says something: what was spent without
 * one-offs (when there were one-offs) and the comparison with last month at the same date. An
 * empty month says so honestly. */
export function spendingLine(pace: PaceFigures, totalCents: number, oneOffsCents: number): string | null {
  if (totalCents === 0 && pace.total_to_date_cents === 0) {
    return pace.previous_same_day_total_cents > 0
      ? t('home.spending.empty', { amount: formatDop(pace.previous_same_day_total_cents) })
      : t('home.spending.emptyNoPrevious')
  }
  const regular = pace.current_cents[pace.current_cents.length - 1] ?? 0
  const change = paceChange(regular, pace.previous_same_day_cents, pace.finished)
  const parts = [
    oneOffsCents > 0 ? t('home.spending.regular', { amount: formatDop(regular) }) : null,
    change?.text ?? null,
  ].filter((part): part is string => part !== null)
  return parts.length ? parts.join(' · ') : null
}

export interface CurvePoint {
  day: number
  current: number | null
  previous: number | null
}

/** Both cumulative curves on the same days (1..the longest month): this month only up to today. */
export function curvePoints(
  current: readonly number[],
  previous: readonly number[],
  daysInMonth: number,
): CurvePoint[] {
  const days = Math.max(daysInMonth, previous.length)
  return Array.from({ length: days }, (_, index) => ({
    day: index + 1,
    current: index < current.length ? current[index] : null,
    previous: index < previous.length ? previous[index] : null,
  }))
}

// ---- Flow ----

export interface FlowBar {
  /** Share of the bar that went out (0..1) and that stayed. */
  out: number
  kept: number
  /** More went out than came in: the bar is what went out and the excess is marked. */
  over: boolean
}

/** One bar for in, out and kept: the whole bar is the larger of what came in and went out. */
export function flowBar(inCents: number, outCents: number): FlowBar {
  const top = Math.max(inCents, outCents, 0)
  if (top === 0) return { out: 0, kept: 0, over: false }
  if (outCents > inCents) return { out: 1, kept: Math.max(inCents, 0) / top, over: true }
  return { out: outCents / top, kept: (inCents - outCents) / top, over: false }
}

// ---- Budget ----

/** The categories with a cap closest to it (spent over cap), at most `count`. */
export function closestToCap(lines: readonly BudgetLine[], count = 3): BudgetLine[] {
  return lines
    .filter((line) => line.active && line.cap_cents !== null && line.cap_cents > 0)
    .map((line) => ({ line, ratio: line.spent_cents / (line.cap_cents ?? 1) }))
    .sort((a, b) => b.ratio - a.ratio || a.line.category.localeCompare(b.line.category))
    .slice(0, count)
    .map(({ line }) => line)
}

/** Width of a budget bar (0..100). */
export function capShare(line: Pick<BudgetLine, 'spent_cents' | 'cap_cents'>): number {
  if (!line.cap_cents || line.cap_cents <= 0) return 0
  return Math.min(100, Math.max(0, (line.spent_cents / line.cap_cents) * 100))
}

// ---- Upcoming ----

/** Something due soon, from any source (recurring charges today; scheduled cash later). */
export interface UpcomingItem {
  key: string
  name: string
  day: string // ISO
  amount: string
  href: string
}

/** A source of upcoming items: whatever it reads, it answers with items due from `today`. */
export type UpcomingSource = (today: string) => UpcomingItem[]

export const UPCOMING_DAYS = 7

/** "YYYY-MM-DD" plus `days`. */
export function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

/** Whole days from `today` to `day`. */
export function daysBetween(today: string, day: string): number {
  return Math.round((Date.parse(`${day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000)
}

/** "today", "tomorrow", "in 3 days". */
export function dueText(today: string, day: string): string {
  const days = daysBetween(today, day)
  if (days <= 0) return t('home.upcoming.today')
  if (days === 1) return t('home.upcoming.tomorrow')
  return t('home.upcoming.inDays', { count: days })
}

/** The recurring charges as an upcoming source. */
export function recurringSource(items: readonly RecurringItem[], href: string): UpcomingSource {
  return (today) =>
    items
      .filter((item) => item.status === 'active')
      .map((item) => ({
        key: `recurring|${item.merchant}|${item.currency}`,
        name: item.name,
        day: nextChargeDay(item, today),
        amount: chargeText(item),
        href,
      }))
}

/** Every source's items due within `days` of `today`, nearest first. */
export function upcoming(
  sources: readonly UpcomingSource[],
  today: string,
  days = UPCOMING_DAYS,
): UpcomingItem[] {
  const last = addDays(today, days)
  return sources
    .flatMap((source) => source(today))
    .filter((item) => item.day >= today && item.day <= last)
    .sort((a, b) => a.day.localeCompare(b.day) || a.name.localeCompare(b.name))
}

// ---- Latest transactions ----

/** The newest `count` transactions, newest first. */
export function latest(items: readonly Tx[], count = 5): Tx[] {
  return [...items]
    .sort((a, b) => b.day.localeCompare(a.day) || a.fingerprint.localeCompare(b.fingerprint))
    .slice(0, count)
}

// ---- Categories ----

/** Five hues apart plus grey for «Otras»; each passes 3:1 against white. */
export const SLICE_COLORS = ['#1F6F5C', '#3D74A8', '#9A6B1F', '#7A5AA6', '#A8553A'] as const
export const OTHERS_COLOR = '#80868F'

export interface Slice {
  key: string
  label: string
  cents: number
  share: number // 0..1
  color: string
  category: string | null // null: «Otras»
}

/** The top `count` categories with spending, and the rest as «Otras». */
export function slices(lines: readonly CategoryLine[], count = 5): Slice[] {
  const spent = lines.filter((line) => line.amount_cents > 0)
  const total = spent.reduce((sum, line) => sum + line.amount_cents, 0)
  if (total === 0) return []
  const sorted = [...spent].sort((a, b) => b.amount_cents - a.amount_cents || a.category.localeCompare(b.category))
  const top = sorted.slice(0, count).map((line, index) => ({
    key: line.category,
    label: line.category,
    cents: line.amount_cents,
    share: line.amount_cents / total,
    color: SLICE_COLORS[index],
    category: line.category,
  }))
  const rest = sorted.slice(count).reduce((sum, line) => sum + line.amount_cents, 0)
  if (rest === 0) return top
  return [
    ...top,
    {
      key: '__others__',
      label: t('home.categories.others'),
      cents: rest,
      share: rest / total,
      color: OTHERS_COLOR,
      category: null,
    },
  ]
}

/** A slice's list: the month's expenses of that category (or all of them, grouped, for «Otras»). */
export function sliceHref(slice: Slice, month: string, selection: Selection): string {
  return slice.category === null
    ? transactionsHref({ month, kind: 'expense', group: 'category' }, selection)
    : transactionsHref({ month, category: slice.category, kind: 'expense' }, selection)
}

// ---- Destinations ----

export function monthSpendingHref(month: string, selection: Selection): string {
  return transactionsHref({ month, kind: 'expense' }, selection)
}

export function txHref(tx: { day: string; fingerprint: string }, selection: Selection): string {
  return transactionsHref({ month: tx.day.slice(0, 7), tx: tx.fingerprint }, selection)
}

export function reportsMonthHref(month: string, selection: Selection): string {
  return hrefWithSelection(REPORTS_PATH, { month }, selection)
}

export function reviewHref(month: string, selection: Selection): string {
  return hrefWithSelection(REVIEW_PATH, { month }, selection)
}

export function budgetHref(month: string, selection: Selection): string {
  return hrefWithSelection(BUDGET_PATH, { month }, selection)
}

export function recurringHref(selection: Selection): string {
  return hrefWithSelection(RECURRING_PATH, {}, selection)
}

// ---- The grid ----

/** How many columns each card takes in a grid of `cols`, in order (`Infinity`: a whole row),
 * stretching a card over whatever its row would leave empty (the next card does not fit, or it
 * is the last one): no row ends with a hole. */
export function fillRows(spans: readonly number[], cols: number): number[] {
  const wanted = spans.map((span) => Math.min(span, cols))
  const result = [...wanted]
  let used = 0
  wanted.forEach((span, index) => {
    if (used + span > cols) used = 0
    used += span
    const next = wanted[index + 1]
    if (next === undefined || used + next > cols) {
      result[index] = span + (cols - used)
      used = 0
    }
  })
  return result
}

// ---- Invitations ----

export type Invitation = 'budget' | 'recurring' | 'shared'

/** By usefulness: a budget first, then the recurring charges, then sharing. */
export const INVITATIONS: readonly Invitation[] = ['budget', 'recurring', 'shared']
export const MAX_INVITATIONS = 2
export const DISMISSED_KEY = 'michelito.home.dismissed'

/** The invitations to show: those that apply and were not dismissed, at most two. */
export function visibleInvitations(
  applicable: ReadonlySet<Invitation>,
  dismissed: readonly string[],
): Invitation[] {
  return INVITATIONS.filter((kind) => applicable.has(kind) && !dismissed.includes(kind)).slice(
    0,
    MAX_INVITATIONS,
  )
}

/** The stored dismissed invitations, ignoring anything that is not a list of known ones. */
export function parseDismissed(raw: string | null): Invitation[] {
  if (raw === null) return []
  try {
    const value: unknown = JSON.parse(raw)
    if (!Array.isArray(value)) return []
    return value.filter((v): v is Invitation => INVITATIONS.includes(v as Invitation))
  } catch {
    return []
  }
}
