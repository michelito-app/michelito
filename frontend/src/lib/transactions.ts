// Filters, grouping and edits of the Transactions screen (pure logic).
import { LOCALE, t } from '@/i18n'
import type { EditBody, Kind, Transactions, Tx } from './api'
import { ACCOUNTS_PARAM, selectionFromParams } from './accountFilter'
import { canonicalCategory } from './categories'
import { formatDop, formatSignedDop, formatUsd } from './money'
import { monthName } from './months'

/** How the list is grouped: by day (the default), by category or by merchant. */
export type GroupBy = 'day' | 'category' | 'merchant'

/** Order of the rows inside each group: the API's (date) or largest amount first. */
export type SortBy = 'date' | 'amount'

/** Filters as they live in the URL: `month`, `accounts` (comma-separated keys; the older single
 * `account` is read too), `category`, `q`, `tx` (the fingerprint), `kind` (expense, income or
 * transfer), `group` and `sort`. The last two do not narrow the list, they only present it
 * differently. */
export interface TxFilters {
  month: string | null
  accounts: readonly string[] | null // null: all
  category: string | null
  q: string
  tx: string | null
  kind: Kind | null
  group: GroupBy
  sort: SortBy
  shared: SharedFilter | null // `shared=pending`: shared expenses with something pending
}

/** Shared-expense filter: only the ones with something pending ("you are owed"). */
export type SharedFilter = 'pending'
export const SHARED_PENDING_PARAM = 'pending'

/** "Group by" options; the day is not written to the URL. */
export const GROUP_OPTIONS: readonly { param: string | null; group: GroupBy; label: string }[] = [
  { param: null, group: 'day', label: t('transactions.group.day') },
  { param: 'category', group: 'category', label: t('transactions.group.category') },
  { param: 'merchant', group: 'merchant', label: t('transactions.group.merchant') },
]

/** "Sort" options; the date is not written to the URL. */
export const SORT_OPTIONS: readonly { param: string | null; sort: SortBy; label: string }[] = [
  { param: null, sort: 'date', label: t('transactions.sort.date') },
  { param: 'amount', sort: 'amount', label: t('transactions.sort.amount') },
]

/** Options of the "Type" filter: URL value, API kind and label. */
export const KIND_OPTIONS: readonly { param: string; kind: Kind; label: string }[] = [
  { param: 'expense', kind: 'expense', label: t('transactions.kind.expense') },
  { param: 'income', kind: 'income', label: t('transactions.kind.income') },
  { param: 'transfer', kind: 'transfer', label: t('transactions.kind.transfer') },
]

/** Filters that narrow the list (the ones sent to the API besides the month). */
export type ListFilters = Pick<TxFilters, 'accounts' | 'category' | 'q' | 'kind' | 'shared'>

export type Scope = NonNullable<EditBody['scope']>

/** What the user has chosen in the detail panel. */
export interface Draft {
  category: string
  oneOff: boolean
  scope: Scope
  note: string
}

export interface DayGroup {
  day: string
  label: string
  items: Tx[]
}

const PARAM = {
  month: 'month',
  accounts: ACCOUNTS_PARAM,
  category: 'category',
  q: 'q',
  tx: 'tx',
  kind: 'kind',
  group: 'group',
  sort: 'sort',
  shared: 'shared',
} as const

function groupOf(param: string | null): GroupBy {
  return GROUP_OPTIONS.find((o) => o.param !== null && o.param === param)?.group ?? 'day'
}

function sortOf(param: string | null): SortBy {
  return SORT_OPTIONS.find((o) => o.param !== null && o.param === param)?.sort ?? 'date'
}

function kindOf(param: string | null): Kind | null {
  return KIND_OPTIONS.find((o) => o.param === param)?.kind ?? null
}

function kindParam(kind: Kind | null): string | null {
  return KIND_OPTIONS.find((o) => o.kind === kind)?.param ?? null
}

function value(params: URLSearchParams, key: string): string | null {
  const text = params.get(key)?.trim() ?? ''
  return text === '' ? null : text
}

function optional(text: string | null, map: (text: string) => string): string | null {
  return text === null ? null : map(text)
}

/** Reads the filters from the URL; empty counts as absent. A renamed category is read with its
 * current name. */
export function parseFilters(params: URLSearchParams): TxFilters {
  return {
    month: value(params, PARAM.month),
    accounts: selectionFromParams(params),
    category: optional(value(params, PARAM.category), canonicalCategory),
    q: value(params, PARAM.q) ?? '',
    tx: value(params, PARAM.tx),
    kind: kindOf(value(params, PARAM.kind)),
    group: groupOf(value(params, PARAM.group)),
    sort: sortOf(value(params, PARAM.sort)),
    shared: value(params, PARAM.shared) === SHARED_PENDING_PARAM ? 'pending' : null,
  }
}

function paramText(filters: TxFilters, key: keyof TxFilters): string | null {
  switch (key) {
    case 'kind':
      return kindParam(filters.kind)
    case 'group':
      return GROUP_OPTIONS.find((o) => o.group === filters.group)?.param ?? null
    case 'sort':
      return SORT_OPTIONS.find((o) => o.sort === filters.sort)?.param ?? null
    case 'accounts':
      return filters.accounts === null ? null : filters.accounts.join(',')
    case 'shared':
      return filters.shared === 'pending' ? SHARED_PENDING_PARAM : null
    default:
      return filters[key]
  }
}

/** The filters as URL parameters, without the empty ones or the defaults. */
export function toParams(filters: TxFilters): URLSearchParams {
  const params = new URLSearchParams()
  for (const key of Object.keys(PARAM) as (keyof TxFilters)[]) {
    const text = paramText(filters, key)?.trim()
    if (text) params.set(PARAM[key], text)
  }
  return params
}

/** Does anything narrow the list besides the month? */
export function hasNarrowing(filters: TxFilters): boolean {
  return (
    filters.accounts !== null ||
    filters.category !== null ||
    filters.kind !== null ||
    filters.shared !== null ||
    filters.q.trim() !== ''
  )
}

/** Clears accounts, category, kind, shared and search; keeps the month, the chosen row, the
 * grouping and the sort. */
export function clearFilters(filters: TxFilters): TxFilters {
  return { ...filters, accounts: null, category: null, q: '', kind: null, shared: null }
}

/** Path of /api/transactions with the filters set. */
export function apiPath(month: string, filters: ListFilters): string {
  const params = new URLSearchParams({ month })
  if (filters.accounts) params.set('accounts', filters.accounts.join(','))
  if (filters.category) params.set('category', filters.category)
  if (filters.q.trim()) params.set('q', filters.q.trim())
  if (filters.kind) params.set('kind', filters.kind)
  if (filters.shared) params.set('shared', filters.shared)
  return `/api/transactions?${params}`
}

const WEEKDAY = new Intl.DateTimeFormat(LOCALE, { weekday: 'long', timeZone: 'UTC' })

/** "2026-09-26" → the weekday, the day and the month name ("Saturday 26 September" in es). */
export function dayLabel(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  const name = WEEKDAY.format(new Date(Date.UTC(year, month - 1, day)))
  const weekday = name.charAt(0).toUpperCase() + name.slice(1)
  return t('transactions.dayLabel', { weekday, day, month: monthName(iso.slice(0, 7)) })
}

const SHORT_WEEKDAY = new Intl.DateTimeFormat(LOCALE, { weekday: 'short', timeZone: 'UTC' })

/** The local date as "YYYY-MM-DD". */
export function isoToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** The day before an ISO date. */
function previousDay(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day - 1)).toISOString().slice(0, 10)
}

/** Short day header for the phone list: "Hoy", "Ayer" or "mar 12 nov" (`today`: ISO date). */
export function compactDayLabel(iso: string, today: string): string {
  if (iso === today) return t('transactions.day.today')
  if (iso === previousDay(today)) return t('transactions.day.yesterday')
  const [year, month, day] = iso.split('-').map(Number)
  const weekday = SHORT_WEEKDAY.format(new Date(Date.UTC(year, month - 1, day))).replace('.', '')
  return t('transactions.day.short', {
    weekday,
    day,
    month: monthName(iso.slice(0, 7)).slice(0, 3),
  })
}

/** How many settings the phone's filter sheet holds that differ from the default (kind,
 * category, the shared filter, grouping and sort). */
export function activeFilterCount(filters: TxFilters): number {
  return [
    filters.kind !== null,
    filters.category !== null,
    filters.shared !== null,
    filters.group !== 'day',
    filters.sort !== 'date',
  ].filter(Boolean).length
}

/** Groups consecutive rows of the same day; the API already sends them newest first. */
export function groupByDay(items: Tx[]): DayGroup[] {
  return items.reduce<DayGroup[]>((groups, item) => {
    const last = groups[groups.length - 1]
    if (last && last.day === item.day) {
      return [...groups.slice(0, -1), { ...last, items: [...last.items, item] }]
    }
    return [...groups, { day: item.day, label: dayLabel(item.day), items: [item] }]
  }, [])
}

/** Sort value by amount: the absolute RD$ amount; without a rate it is not compared and goes last. */
function amountKey(tx: Tx): number {
  return tx.amount_dop_cents === null ? -1 : Math.abs(tx.amount_dop_cents)
}

/** Rows in the requested order. By date it is the API's (newest first); by amount, largest
 * first, keeping the API's order for equal amounts. The received list is not touched. */
export function sortItems(items: Tx[], sort: SortBy): Tx[] {
  if (sort === 'date') return items
  return [...items].sort((a, b) => amountKey(b) - amountKey(a))
}

/** Groups by day; when sorting by amount, sorts inside each day. */
export function dayGroups(items: Tx[], sort: SortBy): DayGroup[] {
  const groups = groupByDay(items)
  return sort === 'date' ? groups : groups.map((g) => ({ ...g, items: sortItems(g.items, sort) }))
}

/** Totals of some rows, with the same rules /api/transactions uses for the header. */
export function totalsOf(items: Tx[]): Transactions {
  const spent = items.filter((t) => t.kind === 'expense')
  const sum = (rows: Tx[]) => rows.reduce((total, t) => total + (t.amount_dop_cents ?? 0), 0)
  return {
    items,
    count: items.length,
    total_cents: sum(spent),
    income_cents: -sum(items.filter((t) => t.kind === 'income')),
    unconverted_usd_cents: spent
      .filter((t) => t.amount_dop_cents === null)
      .reduce((total, t) => total + t.amount_cents, 0),
  }
}

/** A group of the by-category or by-merchant view, with its totals. */
export interface FieldGroup {
  key: string
  items: Tx[]
  totals: Transactions
}

/** What is compared to put the groups with the most spending first (for equal RD$ spending, the
 * one with more US$ without a rate): then the ones with the most income and, among those with
 * neither (transfers), the ones that moved the most money. */
function groupRank(totals: Transactions): number[] {
  const moved = totals.items.reduce((total, t) => total + Math.abs(t.amount_dop_cents ?? 0), 0)
  return [totals.total_cents, totals.unconverted_usd_cents, totals.income_cents, moved]
}

function compareRanks(a: number[], b: number[]): number {
  const index = a.findIndex((value, i) => value !== b[i])
  return index === -1 ? 0 : b[index] - a[index]
}

/** Groups by category or merchant, largest total first; rows follow the requested order. */
export function fieldGroups(items: Tx[], field: 'category' | 'merchant', sort: SortBy): FieldGroup[] {
  // Local accumulator: it never leaves the function, so it is filled in place.
  const byKey = new Map<string, Tx[]>()
  for (const t of items) {
    const rows = byKey.get(t[field])
    if (rows) rows.push(t)
    else byKey.set(t[field], [t])
  }
  return [...byKey.entries()]
    .map(([key, rows]) => ({ key, items: sortItems(rows, sort), totals: totalsOf(rows) }))
    .sort((a, b) => compareRanks(groupRank(a.totals), groupRank(b.totals)))
}

/** Count · total · income · unconverted: the same parts as the header, per group. */
export function groupLine(group: FieldGroup): string {
  const parts = totalsParts(group.totals)
  return [parts.count, parts.total, parts.income, parts.unconverted].filter(Boolean).join(' · ')
}

/** PATCH body with only what changed; `null` if there is nothing to save. With the merchant
 * scope the category is sent even if unchanged: that creates the rule. */
export function editBody(tx: Tx, draft: Draft): EditBody | null {
  const categoryChanged = draft.category !== tx.category
  const sendCategory = categoryChanged || draft.scope === 'merchant'
  const oneOffChanged = draft.oneOff !== tx.one_off
  const noteChanged = draft.note.trim() !== tx.note
  if (!sendCategory && !oneOffChanged && !noteChanged) return null
  return {
    ...(sendCategory && { category: draft.category }),
    ...(oneOffChanged && { one_off: draft.oneOff }),
    ...(noteChanged && { note: draft.note.trim() }),
    scope: draft.scope,
  }
}

/** Maximum length of a note (same as the server). */
export const NOTE_MAX = 500

/** Purchases from the merchant in the transaction's year ("6 purchases in 2026"). */
export function historyText(tx: Tx): string {
  return t('transactions.history', { count: tx.merchant_year_count, year: tx.day.slice(0, 4) })
}

/** Detail of the "Whole merchant" option: a credit does not count purchases. */
export function merchantScopeNote(tx: Tx): string {
  return tx.amount_cents < 0
    ? t('transactions.merchantScope.future')
    : t('transactions.merchantScope.withHistory', { history: historyText(tx) })
}

/** One-off badge: marked by the user, or suggested and not decided yet. */
export function oneOffBadge(tx: Tx): string | null {
  if (tx.one_off) return t('transactions.badge.oneOff')
  return tx.suggested_one_off ? t('transactions.badge.suggestedOneOff') : null
}

/** Suggestion action in the detail: dismiss the suggestion ("Not one-off") or undo a dismissal
 * ("Suggest again"). Nothing if it is already marked as a one-off expense. */
export function oneOffAction(tx: Tx): 'dismiss' | 'restore' | null {
  if (tx.one_off) return null
  if (tx.one_off_dismissed) return 'restore'
  return tx.suggested_one_off ? 'dismiss' : null
}

export interface TotalsParts {
  count: string
  total: string | null // null when the list has no expenses (e.g. only income)
  income: string | null
  unconverted: string | null
}

/** Parts of the header: count · RD$ total · income · US$ without a rate. The total is expenses
 * only. */
export function totalsParts(data: Transactions): TotalsParts {
  return {
    count: t('transactions.count', { count: data.count }),
    total:
      data.items.length === 0 || data.items.some((t) => t.kind === 'expense')
        ? formatDop(data.total_cents)
        : null,
    income:
      data.income_cents > 0
        ? t('transactions.totals.income', { amount: formatDop(data.income_cents) })
        : null,
    unconverted:
      data.unconverted_usd_cents > 0
        ? t('transactions.totals.unconverted', { amount: formatUsd(data.unconverted_usd_cents) })
        : null,
  }
}

export interface AmountLines {
  main: string
  original: string | null
  credit: boolean // refund of an expense
}

/** Tone of the amount: income (green), refund (credit) or neutral (expenses and transfers). */
export type AmountTone = 'income' | 'credit' | 'plain'

export function amountTone(tx: Tx): AmountTone {
  if (tx.kind === 'income') return 'income'
  return tx.kind === 'expense' && tx.amount_cents < 0 ? 'credit' : 'plain'
}

/** Incoming money is shown as positive: credits arrive with a negative sign. */
function signedUsd(cents: number): string {
  const text = formatUsd(-cents)
  return cents <= 0 ? `+${text}` : text
}

/** Amount of a row: in RD$ (or US$ without a rate) and, below, the original in US$. Income
 * gets "+"; a refund, "−" and the credit tone. */
export function amountLines(tx: Tx): AmountLines {
  const credit = amountTone(tx) === 'credit'
  const income = tx.kind === 'income'
  const usd = income ? signedUsd : formatUsd
  if (tx.amount_dop_cents === null) {
    return { main: usd(tx.amount_cents), original: t('transactions.amount.noRate'), credit }
  }
  const original =
    tx.gross_cents !== null && tx.gross_cents !== tx.amount_cents
      ? t('transactions.amount.gross', {
          amount: tx.currency === 'DOP' ? formatDop(tx.gross_cents) : formatUsd(tx.gross_cents),
        })
      : tx.currency === 'DOP'
        ? null
        : usd(tx.amount_cents)
  const main = income ? formatSignedDop(-tx.amount_dop_cents) : formatDop(tx.amount_dop_cents)
  return { main, original, credit }
}

/** Color class of the amount by its tone. */
export const AMOUNT_TONE_CLASS: Record<AmountTone, string | null> = {
  income: 'text-primary',
  credit: 'text-down',
  plain: null,
}

/** Where the amount comes from, for the detail. */
export function originText(tx: Tx): string {
  if (tx.currency === 'DOP') return t('transactions.origin.dop')
  if (tx.amount_dop_cents === null) return t('transactions.origin.noRate')
  return t('transactions.origin.converted', { amount: formatUsd(tx.amount_cents) })
}

/** Badge of the rows that are not an expense. */
export function kindBadge(tx: Tx): string | null {
  if (tx.kind === 'income') return t('transactions.badge.income')
  if (tx.kind === 'transfer') return t('transactions.badge.transfer')
  return null
}

/** Is the row (even partly) outside the viewport? At the top, the sticky day or group header
 * (`top`) is discounted. */
export function outOfView(
  rect: { top: number; bottom: number },
  viewportHeight: number,
  top = 48,
): boolean {
  return rect.top < top || rect.bottom > viewportHeight
}
