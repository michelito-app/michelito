// Texts and filters of Shared (all the shared groups). Pure.
import { t } from '@/i18n'
import type {
  SharedList,
  SharedListExpense,
  SharedListGroup,
  SharedListRefund,
  SharedStatus,
} from './api'
import { expenseCount, formatMoney, moneyList } from './links'
import { formatDop } from './money'
import { shortDay } from './months'
import { unconvertedNote } from './pending'
import { amountQuery, centsText, fold } from './picker'

export const SHARED_PATH = '/shared'
export const EMPTY_TEXT = t('shared.empty')
export const EMPTY_CHOSEN_TEXT = t('shared.emptyChosen')
export const STATUS_PARAM = 'status'
export const QUERY_PARAM = 'q'
export const GROUP_PARAM = 'group'

/** The chip id is also its `?status=` value in the URL. */
export type Chip = 'all' | 'pending' | 'settled' | 'lost'

export const CHIPS: readonly { chip: Chip; label: string; status: SharedStatus | null }[] = [
  { chip: 'all', label: t('shared.chip.all'), status: null },
  { chip: 'pending', label: t('shared.chip.pending'), status: 'pending' },
  { chip: 'settled', label: t('shared.chip.settled'), status: 'settled' },
  { chip: 'lost', label: t('shared.chip.lost'), status: 'written_off' },
]

const NONE_TEXT: Record<Chip, string> = {
  all: t('shared.none.all'),
  pending: t('shared.none.pending'),
  settled: t('shared.none.settled'),
  lost: t('shared.none.lost'),
}

/** The chip in the URL (`?status=`); an unknown or missing one is "All". */
export function parseChip(value: string | null): Chip {
  return CHIPS.find((c) => c.chip === value)?.chip ?? 'all'
}

/** The group expanded in the URL (`?group=<id>`); null if none or not an id. */
export function parseGroup(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null
  return Number(value)
}

/** What the list says when the chip or the search leave it empty. */
export function noneText(chip: Chip, query: string): string {
  const q = query.trim()
  return q === '' ? NONE_TEXT[chip] : t('shared.noneMatching', { none: NONE_TEXT[chip], query: q })
}

function amounts(group: SharedListGroup): number[] {
  return [
    ...group.expenses.map((e) => e.amount_cents),
    ...group.refunds.map((r) => r.amount_cents),
    ...[...group.paid, ...group.pending, ...group.reimbursed].map((p) => p.cents),
  ]
}

/** Does the group match the search? An amount (as in the pickers: "1000", "1,000",
 * "US$ 29.75") matches if any of its amounts (expenses, refunds, paid, returned or pending)
 * starts with those digits; otherwise the text is searched in the name, "With whom" and each
 * expense's merchant (ignoring case and accents). */
export function groupMatches(group: SharedListGroup, query: string): boolean {
  const amount = amountQuery(query)
  if (amount !== null) return amounts(group).some((c) => centsText(c).startsWith(amount))
  const needle = fold(query.trim())
  if (needle === '') return true
  const texts = [group.title, group.name, group.with_whom, ...group.expenses.map((e) => e.merchant)]
  return texts.some((text) => fold(text).includes(needle))
}

/** The chip's groups that match the search, in the server's order. */
export function filterGroups(
  groups: readonly SharedListGroup[],
  chip: Chip,
  query: string,
): SharedListGroup[] {
  const status = CHIPS.find((c) => c.chip === chip)?.status ?? null
  return groups.filter((g) => (status === null || g.status === status) && groupMatches(g, query))
}

/** What shows without any group: with all accounts, that there are no shared groups yet; with
 * chosen accounts, that none belongs to them. */
export function emptyText(filtered: boolean): string {
  return filtered ? EMPTY_CHOSEN_TEXT : EMPTY_TEXT
}

/** What is listed: the filtered groups and, if the `pinned` group (the one expanded when coming
 * back from its screen) no longer matches the chip or the search, it too, in its place in the
 * server's order (its row says its current status), so the context is not lost. */
export function withPinned(
  all: readonly SharedListGroup[],
  shown: readonly SharedListGroup[],
  pinned: number | null,
): SharedListGroup[] {
  if (pinned === null || shown.some((g) => g.id === pinned)) return [...shown]
  if (!all.some((g) => g.id === pinned)) return [...shown]
  const ids = new Set([...shown.map((g) => g.id), pinned])
  return all.filter((g) => ids.has(g.id))
}

/** How many groups each chip has (to show next to its name). */
export function chipCounts(groups: readonly SharedListGroup[]): Record<Chip, number> {
  const count = (status: SharedStatus) => groups.filter((g) => g.status === status).length
  return {
    all: groups.length,
    pending: count('pending'),
    settled: count('settled'),
    lost: count('written_off'),
  }
}

export interface StatusText {
  main: string // "You are owed US$ 29.75", "Settled" or "Written off"
  approx: string | null // "≈ RD$ 1,845" if there are pending US$ with a rate; without, the note
}

/** The group's status: what you are owed (per currency and, with US$, ≈ RD$ like Pending), or
 * whether it is settled or written off. */
export function statusText(group: SharedListGroup): StatusText {
  if (group.status === 'settled') return { main: t('shared.status.settled'), approx: null }
  if (group.status === 'written_off') return { main: t('shared.status.lost'), approx: null }
  const main = t('shared.status.owed', { amount: moneyList(group.pending) })
  // US$ without any rate: said instead of making up the equivalent (like Pending).
  const unconverted = unconvertedNote(group.unconverted_usd_cents)
  if (unconverted !== null) return { main, approx: unconverted }
  const usd = group.pending.some((p) => p.currency === 'USD')
  const dop = group.pending_dop_cents
  return {
    main,
    approx: usd && dop !== null ? t('shared.approx', { amount: formatDop(dop) }) : null,
  }
}

/** "They paid you back RD$ 300 too much" if something was left after settling everything;
 * otherwise null. */
export function excessText(group: SharedListGroup): string | null {
  return group.excess.length ? t('shared.excess', { amount: moneyList(group.excess) }) : null
}

function dayWithYear(iso: string): string {
  return `${shortDay(iso)} ${iso.slice(0, 4)}`
}

/** Dates of the expenses (month names from the UI locale): "20 Dec 2025", "3 Feb – 7 Feb 2026"
 * or, across years, "18 Dec 2025 – 9 Jan 2026". */
export function dateRange(first: string, last: string): string {
  if (first === last) return dayWithYear(first)
  if (first.slice(0, 4) === last.slice(0, 4)) return `${shortDay(first)} – ${dayWithYear(last)}`
  return `${dayWithYear(first)} – ${dayWithYear(last)}`
}

/** "Luis · 2 expenses · 3 Feb – 7 Feb 2026": with whom (unless already the title), how many
 * expenses and their dates. */
export function groupMeta(group: SharedListGroup): string {
  const who = group.with_whom === group.title ? '' : group.with_whom
  const range = dateRange(group.first_day, group.last_day)
  const parts = [who, expenseCount(group.expenses.length), range]
  return parts.filter((part) => part !== '').join(' · ')
}

/** "You paid RD$ 4,350 · they paid you back RD$ 2,175" (or "· nothing paid back"). */
export function moneyLine(group: SharedListGroup): string {
  const back = group.reimbursed.length
    ? t('shared.moneyLine.paidBack', { amount: moneyList(group.reimbursed) })
    : t('shared.moneyLine.nothingBack')
  return t('shared.moneyLine', { paid: moneyList(group.paid), back })
}

/** The status of an expense in the group: "Settled", "Pending RD$ 2,000" or "Written off". */
export function expenseState(expense: SharedListExpense): string {
  if (expense.written_off_cents > 0) return t('shared.status.lost')
  if (expense.pending_cents === 0) return t('shared.status.settled')
  return t('shared.expensePending', {
    amount: formatMoney(expense.pending_cents, expense.currency),
  })
}

/** Where a refund came from: "TOKE DE ANA · Checking ···2" or "By hand · Marta · cash". */
export function refundLabel(refund: SharedListRefund): string {
  if (!refund.manual) {
    return [refund.description, refund.account_label].filter((p) => p !== '').join(' · ')
  }
  const where = refund.account_label === '' ? t('shared.refund.cash') : refund.account_label
  return [t('shared.refund.manual'), refund.description, where].filter((p) => p !== '').join(' · ')
}

export interface Figure {
  key: 'owed' | 'year' | 'open'
  label: string
  value: string
  extra: string | null
}

/** The three figures on top: owed to you (like Pending), what was paid back this year and how
 * many groups are still open. US$ without a rate go apart, without making anything up. */
export function sharedFigures(list: SharedList): Figure[] {
  return [
    {
      key: 'owed',
      label: t('shared.figure.owed'),
      value: t('shared.approx', { amount: formatDop(list.owed_dop_cents) }),
      extra: unconvertedNote(list.unconverted.owed_usd_cents),
    },
    {
      key: 'year',
      label: t('shared.figure.year'),
      value: t('shared.approx', { amount: formatDop(list.reimbursed_year_dop_cents) }),
      extra: unconvertedNote(list.unconverted.reimbursed_usd_cents),
    },
    {
      key: 'open',
      label: t('shared.figure.open'),
      value: t('shared.figure.openCount', { count: list.open_count }),
      extra: null,
    },
  ]
}

/** The Shared URL with the chip, the search and the expanded group (without empty or default
 * values), keeping the other parameters (the accounts). */
export function sharedParams(
  current: URLSearchParams,
  next: { chip?: Chip; query?: string; group?: number | null },
): URLSearchParams {
  const copy = new URLSearchParams(current)
  const put = (key: string, value: string | null) => {
    if (value === null || value === '') copy.delete(key)
    else copy.set(key, value)
  }
  if (next.chip !== undefined) put(STATUS_PARAM, next.chip === 'all' ? null : next.chip)
  if (next.query !== undefined) put(QUERY_PARAM, next.query)
  if (next.group !== undefined) put(GROUP_PARAM, next.group === null ? null : String(next.group))
  return copy
}
