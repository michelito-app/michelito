// Summary texts and tones, computed from the /api/summary response.
import type { AccountTotal, CategoryLine, Change, Coverage, MonthTotal, Rate } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { THIRD_PARTY } from './categories'
import { LOCALE, t } from '@/i18n'
import { formatDop, formatSignedDop, formatUsd } from './money'
import { longDay, monthName, monthPhrase, shortDay } from './months'

/** Same as the server's SAME_FLOOR and SAME_SHARE: "same" when |diff| < max(RD$ 500, 5 %). */
const SAME_FLOOR_CENTS = 50_000
const SAME_SHARE = 0.05

export type Tone = 'up' | 'down' | 'same' | 'none'

export interface Diff {
  tone: Tone
  text: string
}

/** A category's difference against the usual: "+RD$ 7,129", "same", "new" when there was no
 * spending in it before (repeating the amount says nothing), "—" when the month is not compared. */
export function categoryDiff(line: CategoryLine): Diff {
  if (line.diff_cents === null) return { tone: 'none', text: '—' }
  if (line.same) return { tone: 'same', text: t('summary.diff.same') }
  const isNew = line.habitual_cents === 0 && line.diff_cents > 0
  const text = isNew ? t('summary.diff.new') : formatSignedDop(line.diff_cents)
  if (line.diff_cents > 0 && line.one_offs_cents > 0) return { tone: 'up', text: t('summary.diff.oneOff', { text }) }
  return { tone: line.diff_cents > 0 ? 'up' : 'down', text }
}

/** Bar width (0..100) against the largest category; refunds do not overflow it. */
export function barWidth(amountCents: number, maxCents: number): number {
  if (maxCents <= 0) return 0
  return Math.min(100, Math.max(0, (amountCents / maxCents) * 100))
}

/** A KPI's sentence against the month's usual. */
export function versusHabitual(amountCents: number, habitualCents: number): Diff {
  const diff = amountCents - habitualCents
  const floor = Math.max(SAME_FLOOR_CENTS, Math.abs(habitualCents) * SAME_SHARE)
  if (Math.abs(diff) < floor) {
    return { tone: 'same', text: t('summary.versus.same', { habitual: formatDop(habitualCents) }) }
  }
  const amount = formatDop(Math.abs(diff))
  if (diff > 0) return { tone: 'up', text: t('summary.versus.more', { amount }) }
  return { tone: 'down', text: t('summary.versus.less', { amount }) }
}

/** "Delivery +RD$ 4,400". */
export function changeTitle(change: Change): string {
  return `${change.category} ${formatSignedDop(change.diff_cents)}`
}

function purchasesText(count: number): string {
  return t('summary.purchases', { count })
}

/** A sentence that explains the change: a one-off expense, the number of purchases or the amount. */
export function changeDetail(change: Change): string {
  if (change.diff_cents > 0 && change.one_offs_cents > 0) {
    return t('summary.change.oneOff', { amount: formatDop(change.one_offs_cents) })
  }
  if (change.purchases === 0) return t('summary.change.noPurchases')
  const habitual = change.habitual_purchases
  if (habitual !== null && habitual !== change.purchases) {
    return t('summary.change.purchasesVsHabitual', { purchases: purchasesText(change.purchases), habitual })
  }
  return change.diff_cents > 0 ? t('summary.change.sameMore') : t('summary.change.sameLess')
}

/** "complete", "through 13 Oct" or "no data". */
export function coverageText(coverage: Coverage): string {
  if (coverage.complete) return t('summary.coverage.complete')
  return coverage.through
    ? t('summary.coverage.through', { day: shortDay(coverage.through) })
    : t('summary.coverage.noData')
}

/** "63.4000" → "63.40"; keeps up to 4 decimals when it has them. */
export function rateText(value: string): string {
  return Number(value).toLocaleString(LOCALE, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
    useGrouping: false,
  })
}

/** A notice when the rate used is from another month: "August rate". */
export function rateNote(rate: Rate, month: string): string | null {
  return rate.month_used === month ? null : t('summary.rate.otherMonth', { month: monthName(rate.month_used) })
}

const RATE_INPUT = /^\d+(\.\d{1,4})?$/

/** Validates a hand-typed rate (a decimal comma is accepted); null when it is not usable. */
export function parseRate(input: string): string | null {
  const value = input.trim().replace(',', '.')
  if (!RATE_INPUT.test(value) || Number(value) <= 0) return null
  return value
}

/** Note under an account in "By account": the currency and, when there were dollars, the rate. */
export function accountNote(account: AccountTotal, rate: Rate | null): string {
  if (account.usd_cents === 0) return 'RD$'
  const usd = formatUsd(account.usd_cents)
  return rate
    ? t('summary.account.withRate', { usd, rate: rateText(rate.value) })
    : t('summary.account.noRate', { usd })
}

const RANKS = [
  t('summary.trend.rank.highest'),
  t('summary.trend.rank.second'),
  t('summary.trend.rank.third'),
]

/** The month of the bar at `index` (the index Recharts hands over on click), or null. */
export function trendMonthAt(trend: MonthTotal[], index: number | string | undefined): string | null {
  if (index === undefined) return null
  const i = Number(index)
  if (!Number.isInteger(i) || i < 0 || i >= trend.length) return null
  return trend[i].month
}

/** Text summary of the 12-month chart (spending), for screen readers. */
export function trendSummary(trend: MonthTotal[], month: string): string {
  if (trend.length === 0) return t('summary.trend.empty')
  const first = trend[0].month
  const last = trend[trend.length - 1].month
  const chosen = trend.find((t) => t.month === month)
  if (trend.length === 1) {
    return t('summary.trend.single', {
      month: monthPhrase(first),
      amount: formatDop(trend[0].total_cents),
    })
  }
  const range = t('summary.trend.range', { from: monthPhrase(first), to: monthPhrase(last) })
  if (!chosen) return range
  const higher = trend.filter((t) => t.total_cents > chosen.total_cents).length
  const lower = trend.filter((t) => t.total_cents < chosen.total_cents).length
  const rank =
    higher > 0 && lower === 0
      ? t('summary.trend.rank.lowest')
      : (RANKS[higher] ?? t('summary.trend.rank.nth', { n: higher + 1, total: trend.length }))
  return t('summary.trend.chosen', {
    range,
    month: monthName(month),
    amount: formatDop(chosen.total_cents),
    rank,
  })
}

/** Where the one-off expenses are: "In Health", "In Health and Travel", "In 3 categories". */
export function oneOffsText(lines: CategoryLine[]): string | null {
  const names = lines.filter((l) => l.one_offs_cents > 0).map((l) => l.category)
  if (names.length === 0) return null
  if (names.length > 2) return t('summary.oneOffs.many', { count: names.length })
  return t('summary.oneOffs.in', { names: joinPhrases(names) })
}

/** "a", "a and b", "a, b and c" (not `Intl.ListFormat`: its Spanish "y" turns into "e"). */
export function joinPhrases(items: readonly string[]): string {
  if (items.length <= 1) return items.join('')
  return t('summary.list.and', {
    head: items.slice(0, -1).join(t('summary.list.separator')),
    last: items[items.length - 1],
  })
}

/** Incomplete-month notice, with how far each account that does not cover it reaches. */
export function partialNote(label: string, coverage: Coverage[]): string {
  const missing = coverage
    .filter((c) => !c.complete)
    .map((c) =>
      c.through
        ? t('summary.partial.through', { account: c.label, day: longDay(c.through) })
        : t('summary.partial.noData', { account: c.label }),
    )
  if (missing.length === 0) return t('summary.partial.note', { label })
  return t('summary.partial.noteWithDetail', { label, detail: joinPhrases(missing) })
}

/** "84 %" of what came in stayed; "—" when the month has no income worth counting. */
export function savingsText(rate: number | null): string {
  if (rate === null) return '—'
  const percent = Math.round(rate * 100)
  return t('summary.percent', { value: percent < 0 ? `−${Math.abs(percent)}` : percent })
}

/** "Through 15 Jan" when a bank account ends before the end of the month; otherwise nothing. */
export function incomeThroughNote(incomeThrough: string | null): string | null {
  return incomeThrough === null ? null : t('summary.income.through', { day: shortDay(incomeThrough) })
}

/** Under the saved %: what it measures or why it is not computed. */
export function savingsNote(rate: number | null, incomeThrough: string | null): string {
  if (incomeThrough !== null) {
    return t('summary.savings.incomeThrough', { day: shortDay(incomeThrough) })
  }
  if (rate === null) return t('summary.savings.noIncome')
  return t('summary.savings.note')
}

/** What was left: good when not negative; red (the rising tone) when overspent. */
export function netTone(netCents: number): 'good' | 'up' {
  return netCents < 0 ? 'up' : 'good'
}

/** Sentence under "You kept". */
export function netDetail(netCents: number, thirdPartyCents = 0): string {
  const sent = thirdPartyCents !== 0
  if (netCents >= 0) return sent ? t('summary.net.lessThirdParty') : t('summary.net.incomeLessSpending')
  const amount = formatDop(-netCents)
  return sent ? t('summary.net.overSent', { amount }) : t('summary.net.overspent', { amount })
}

/** The month's transactions in the third-party transfers category (with the chosen accounts).
 * `name`: its current name (`builtinName`), in case the user renamed it. */
export function thirdPartyHref(
  month: string,
  selection: Selection = null,
  name: string = THIRD_PARTY,
): string {
  return transactionsHref({ month, category: name }, selection)
}

/** "See what it was spent on": the month's expenses in Transactions, grouped by category (with
 * the chosen accounts). */
export function spendingHref(month: string, selection: Selection = null): string {
  return transactionsHref({ month, kind: 'expense', group: 'category' }, selection)
}

/** Note of "You kept" and "% saved" when the chosen accounts have no income. */
export const NO_FLOW_NOTE = t('summary.noFlow')

/** The "You kept" figure: "—" without a flow (the chosen accounts have no income). */
export function netText(netCents: number | null): string {
  return netCents === null ? '—' : formatDop(netCents)
}

/** What left the chosen accounts for other accounts of yours (it is not subtracted from
 * anything): "Payments to your cards RD$ 8,000 · Moved to your other accounts RD$ 400"; null if
 * nothing. */
export function ownMovesNote(toCardsCents: number, toOwnCents: number): string | null {
  const parts = [
    toCardsCents > 0 ? t('summary.ownMoves.toCards', { amount: formatDop(toCardsCents) }) : null,
    toOwnCents > 0 ? t('summary.ownMoves.toOwn', { amount: formatDop(toOwnCents) }) : null,
  ].filter((p): p is string => p !== null)
  return parts.length ? parts.join(' · ') : null
}

/** Note of the third-party transfers card. */
export function thirdPartyNote(thirdPartyCents: number): string {
  return thirdPartyCents === 0 ? t('summary.thirdParty.none') : t('summary.thirdParty.note')
}

/** How many rows each Summary card shows before "See all N". */
export const CATEGORY_LIMIT = 8
export const REVIEW_LIMIT = 4
export const ACCOUNT_LIMIT = 4

export interface Split<T> {
  shown: T[]
  rest: T[]
}

/** The first `limit` rows and the rest; with "all" open, everything goes in `shown`. */
export function splitTop<T>(items: readonly T[], limit: number, all = false): Split<T> {
  if (all || items.length <= limit) return { shown: [...items], rest: [] }
  return { shown: items.slice(0, limit), rest: items.slice(limit) }
}

/** The accounts with the most movement first (the month's spending in RD$). */
export function byMovement(accounts: readonly AccountTotal[]): AccountTotal[] {
  return [...accounts].sort((a, b) => b.total_cents - a.total_cents)
}

/** Income of the month chosen in the chart, for screen readers. */
export function trendIncomeNote(trend: MonthTotal[], month: string): string | null {
  const chosen = trend.find((t) => t.month === month)
  if (!chosen) return null
  if (chosen.income_cents <= 0) return t('summary.trend.noIncome', { month: monthName(month) })
  return t('summary.trend.income', {
    month: monthName(month),
    amount: formatDop(chosen.income_cents),
  })
}

/** "RD$ X still without a statement": how much of the month's spending comes from bank alerts and still
 * waits for its statement (it is already counted); null when nothing does. */
export function provisionalNote(provisionalCents: number): string | null {
  if (provisionalCents <= 0) return null
  return t('summary.provisional', { amount: formatDop(provisionalCents) })
}
