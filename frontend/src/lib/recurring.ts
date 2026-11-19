// Texts and grouping of the Recurring screen (API: GET /api/recurring).
import { t } from '@/i18n'
import type {
  AlertKind,
  GroupTotal,
  MarkBody,
  MarkStatus,
  Recurring,
  RecurringGroupKey,
  RecurringItem,
  TxRecurringBody,
} from './api'
import { formatDop, formatUsd } from './money'
import { monthName, shortDay } from './months'

export type AlertTone = 'up' | 'neutral'
export type BadgeTone = AlertTone | 'positive' | 'muted'

export const MAX_INSTALLMENTS = 600

/** The groups that can be picked by hand, in screen order (not the installments one: having
 * installments noted puts an item there). */
export const GROUP_OPTIONS: { key: RecurringGroupKey; label: string }[] = [
  { key: 'housing', label: t('recurring.group.housing') },
  { key: 'loans', label: t('recurring.group.loans') },
  { key: 'utilities', label: t('recurring.group.utilities') },
  { key: 'insurance', label: t('recurring.group.insurance') },
  { key: 'subscriptions', label: t('recurring.group.subscriptions') },
  { key: 'fees', label: t('recurring.group.fees') },
  { key: 'other', label: t('recurring.group.other') },
]
const LOANS_GROUP: RecurringGroupKey = 'loans'

const STATUS_BADGE: Record<RecurringItem['status'], string | null> = {
  active: null,
  inactive: t('recurring.badge.inactive'),
  cancelled: t('recurring.badge.cancelled'),
  ended: t('recurring.badge.ended'),
}
const UP_BADGES = new Set([t('recurring.badge.rose'), t('recurring.badge.chargedAgain')])
const MUTED_BADGES = new Set([
  t('recurring.badge.inactive'),
  t('recurring.badge.cancelled'),
  t('recurring.badge.ended'),
])

function inCurrency(cents: number, currency: string): string {
  return currency === 'USD' ? formatUsd(cents) : formatDop(cents)
}

/** The row's badges, from the most urgent to the calmest. `month` ("YYYY-MM") is the month that
 * decides "new" and "went up" (null to mark neither); `firstMonth` is the month of the first
 * transaction, where nothing is new. Only active items get those two. */
export function badgesOf(
  item: RecurringItem,
  month: string | null,
  firstMonth: string | null = null,
): string[] {
  const change = item.price_change
  const left = item.installments_left
  const status = STATUS_BADGE[item.status]
  const active = item.status === 'active'
  const rose =
    active &&
    month !== null &&
    change !== null &&
    change.after_cents > change.before_cents &&
    change.day.slice(0, 7) === month
  const isNew =
    active && month !== null && month !== firstMonth && item.first_day.slice(0, 7) === month
  return [
    item.charged_after_cancel ? t('recurring.badge.chargedAgain') : null,
    rose ? t('recurring.badge.rose') : null,
    isNew ? t('recurring.badge.new') : null,
    item.variable ? t('recurring.badge.variable') : null,
    left !== null && left > 0 ? installmentsText(left, item.group_key === LOANS_GROUP) : null,
    status,
  ].filter((badge): badge is string => badge !== null)
}

/** Installments left ("3 left"); a loan says it its own way. */
function installmentsText(left: number, loan = false): string {
  return loan
    ? t('recurring.badge.loanLeft', { count: left })
    : t('recurring.badge.installmentsLeft', { count: left })
}

/** Whether `badge` is an installments-left badge (of either form). */
function isInstallmentsBadge(badge: string): boolean {
  const number = /\d+/.exec(badge)
  if (number === null) return false
  const left = Number(number[0])
  return badge === installmentsText(left) || badge === installmentsText(left, true)
}

/** Tone of a badge from `badgesOf`. */
export function badgeTone(badge: string): BadgeTone {
  if (UP_BADGES.has(badge)) return 'up'
  if (MUTED_BADGES.has(badge)) return 'muted'
  if (isInstallmentsBadge(badge)) return 'positive'
  return 'neutral'
}

/** Tone of a month's alert: rises and charges after cancelling call for attention. */
export function alertTone(kind: AlertKind): AlertTone {
  return kind === 'new' ? 'neutral' : 'up'
}

const CADENCE_TEXT: Record<RecurringItem['cadence'], string> = {
  monthly: t('recurring.cadence.monthly'),
  yearly: t('recurring.cadence.yearly'),
}

export function cadenceText(item: RecurringItem): string {
  return CADENCE_TEXT[item.cadence]
}

/** Since when it charges: "2025-12-05" → the short month and the two-digit year ("dic 25"). */
export function sinceText(item: RecurringItem): string {
  const month = item.first_day.slice(0, 7)
  return t('recurring.since', { month: monthName(month).slice(0, 3), year: month.slice(2, 4) })
}

/** The last charge: "2026-02-05" → its short day ("5 feb"). */
export function lastChargeText(item: RecurringItem): string {
  return t('recurring.lastCharge', { day: shortDay(item.last_day) })
}

export interface CostLines {
  main: string
  detail: string
}

/** Monthly cost in RD$ and, below it, the original charge when it says something more. */
export function costLines(item: RecurringItem): CostLines {
  const yearly = item.cadence === 'yearly'
  if (item.monthly_cents === null) {
    const monthly = yearly ? Math.round(item.typical_cents / 12) : item.typical_cents
    return {
      main: inCurrency(monthly, item.currency),
      detail: t('recurring.cost.perMonthNoRate'),
    }
  }
  const main = formatDop(item.monthly_cents)
  if (yearly)
    return {
      main,
      detail: t('recurring.cost.perYear', {
        amount: inCurrency(item.typical_cents, item.currency),
      }),
    }
  if (item.currency === 'USD') {
    return {
      main,
      detail: t('recurring.cost.perMonthAmount', { amount: formatUsd(item.typical_cents) }),
    }
  }
  return {
    main,
    detail: item.variable ? t('recurring.cost.averagePerMonth') : t('recurring.cost.perMonth'),
  }
}

/** Loans: the extra payments made this year (null when there were none). */
export function extrasText(
  item: Pick<RecurringItem, 'extras_year_cents' | 'currency'>,
): string | null {
  if (item.extras_year_cents <= 0) return null
  return t('recurring.extras', { amount: inCurrency(item.extras_year_cents, item.currency) })
}

/** The series' merchants when it is not a single one with its own name: "LUZ PAGO, LUZ WB". */
export function membersText(item: Pick<RecurringItem, 'members' | 'name'>): string | null {
  if (item.members.length === 1 && item.members[0] === item.name) return null
  return item.members.join(', ')
}

export interface JoinTarget {
  key: string
  name: string
}

/** What a recurring item can be joined with: the others on the screen (without repeating the
 * key of another currency) and the listed providers not already there, by name. */
export function joinTargets(overview: Recurring, item: RecurringItem): JoinTarget[] {
  const found = new Map<string, string>()
  for (const other of [...overview.items, ...overview.dismissed]) {
    if (other.merchant !== item.merchant) found.set(other.merchant, other.name)
  }
  for (const provider of overview.providers) {
    if (provider.key !== item.merchant && !found.has(provider.key))
      found.set(provider.key, provider.name)
  }
  return [...found]
    .map(([key, name]) => ({ key, name }))
    .sort((a, b) => a.name.localeCompare(b.name, 'es'))
}

/** Body of "It is recurring…": the group and the installments only when chosen. */
export function txRecurringBody(
  cadence: TxRecurringBody['cadence'],
  group: RecurringGroupKey | '',
  installments: number | null,
): TxRecurringBody {
  return {
    cadence,
    ...(group === '' ? {} : { group }),
    ...(installments === null ? {} : { installments_left: installments }),
  }
}

/** Monthly and yearly totals ("RD$ 3,264 … · RD$ 39,165 …"). */
export function totalLine(monthlyCents: number, yearlyCents: number): string {
  return t('recurring.totalLine', {
    monthly: formatDop(monthlyCents),
    yearly: formatDop(yearlyCents),
  })
}

export interface Section {
  group: string
  /** null when the group has no active charge. */
  total: GroupTotal | null
  items: RecurringItem[]
}

/** Groups in the order the API sends them; inside each one, active items first (inactive,
 * cancelled and ended ones last, in their order). */
export function sections(overview: Recurring): Section[] {
  const groups = [...new Set(overview.items.map((i) => i.group))]
  return groups.map((group) => {
    const members = overview.items.filter((i) => i.group === group)
    return {
      group,
      total: overview.groups.find((g) => g.group === group) ?? null,
      items: [
        ...members.filter((i) => i.status === 'active'),
        ...members.filter((i) => i.status !== 'active'),
      ],
    }
  })
}

/** Changes the mark without touching the installments (`installments_left` is not sent). */
export function statusBody(item: RecurringItem, status: MarkStatus | null): MarkBody {
  return { merchant: item.merchant, currency: item.currency, status }
}

/** Notes (or clears, with null) the installments left and keeps the current mark. */
export function installmentsBody(item: RecurringItem, left: number | null): MarkBody {
  return { ...statusBody(item, item.mark), installments_left: left }
}

/** Picks the group by hand ('' goes back to the category's) and keeps the current mark. */
export function groupBody(item: RecurringItem, group: RecurringGroupKey | ''): MarkBody {
  return { ...statusBody(item, item.mark), group: group === '' ? null : group }
}

/** The merchants that can be separated: all but the one that names the series (a join's
 * target is not separated from itself). */
export function separableMembers(item: Pick<RecurringItem, 'members' | 'merchant'>): string[] {
  if (item.members.length < 2) return []
  return item.members.filter((member) => member !== item.merchant)
}

/** An integer from 0 to 600, or null when the text is not one. */
export function parseInstallments(text: string): number | null {
  const trimmed = text.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const value = Number(trimmed)
  return value <= MAX_INSTALLMENTS ? value : null
}

export interface UpcomingCharge {
  item: RecurringItem
  /** Expected date of the next charge ("YYYY-MM-DD"). */
  day: string
}

/** Step limit when estimating (100 years of monthly charges). */
const MAX_STEPS = 1200

type ChargeDates = Pick<RecurringItem, 'first_day' | 'last_day' | 'cadence'>

function monthEnd(year: number, index: number): number {
  return new Date(Date.UTC(year, index + 1, 0)).getUTCDate()
}

/** Day of the month it usually charges: the last charge's, unless that one falls on the end of a
 * short month and the series started on a later day (a charge on the 31st that was the 28th in
 * February). */
export function typicalDay(item: Pick<RecurringItem, 'first_day' | 'last_day'>): number {
  const [year, month, last] = item.last_day.split('-').map(Number)
  const first = Number(item.first_day.slice(8, 10))
  return last === monthEnd(year, month - 1) && first > last ? first : last
}

/** The next charge estimated from `today` ("YYYY-MM-DD"): the last one plus a month (or a year)
 * on its typical day, without going past the month's end, as many times as needed not to fall
 * before today. */
export function nextChargeDay(item: ChargeDates, today: string): string {
  const [year, month] = item.last_day.split('-').map(Number)
  const day = typicalDay(item)
  const step = item.cadence === 'yearly' ? 12 : 1
  // Months since January of year 0, to step forward without fighting year changes.
  let at = year * 12 + month - 1
  let candidate = item.last_day
  for (let steps = 0; steps < MAX_STEPS; steps += 1) {
    at += step
    const [y, index] = [Math.floor(at / 12), at % 12]
    candidate = new Date(Date.UTC(y, index, Math.min(day, monthEnd(y, index))))
      .toISOString()
      .slice(0, 10)
    if (candidate >= today) break
  }
  return candidate
}

/** The `count` nearest active charges from `today`, nearest first. */
export function upcomingCharges(
  items: readonly RecurringItem[],
  today: string,
  count = 3,
): UpcomingCharge[] {
  return items
    .filter((item) => item.status === 'active')
    .map((item) => ({ item, day: nextChargeDay(item, today) }))
    .sort((a, b) => a.day.localeCompare(b.day) || a.item.merchant.localeCompare(b.item.merchant))
    .slice(0, count)
}

/** Typical amount of a charge in its currency: "US$ 11.99", "RD$ 2,500". */
export function chargeText(item: Pick<RecurringItem, 'typical_cents' | 'currency'>): string {
  return inCurrency(item.typical_cents, item.currency)
}

/** Note of the Summary card when there are no alerts to show; null when there are. */
export function cardNote(overview: Recurring): string | null {
  if (overview.items.length === 0) return t('recurring.card.none')
  return overview.alerts.length === 0 ? t('recurring.card.noChanges') : null
}
