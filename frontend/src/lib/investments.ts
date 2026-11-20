// Texts, filters and bodies of Investments (pure logic). The server does the math
// (src/michelito/analysis/investments.py).
import { t } from '@/i18n'
import type {
  CreditRole,
  Investment,
  InvestmentEntry,
  InvestmentList,
  InvestmentStatus,
  RoleBody,
} from './api'
import { formatMoney, parseCents, ROLE_LABELS } from './links'
import { formatDop } from './money'
import { unconvertedNote } from './pending'
import { amountQuery, centsText, fold } from './picker'
import { dateRange } from './months'

export const INVESTMENTS_PATH = '/investments'
export const EMPTY_TEXT = t('investments.empty')
export const EMPTY_CHOSEN_TEXT = t('investments.emptyChosen')
export const STATUS_PARAM = 'status'
export const QUERY_PARAM = 'q'
export const OPEN_PARAM = 'investment'

/** The chip id is also its `?status=` value in the URL. */
export type Chip = 'active' | 'closed' | 'all'

/** Active · Closed (also the written-off ones: nothing more is expected) · All. */
export const CHIPS: readonly { chip: Chip; label: string; statuses: InvestmentStatus[] | null }[] =
  [
    { chip: 'active', label: t('investments.chip.active'), statuses: ['active'] },
    { chip: 'closed', label: t('investments.chip.closed'), statuses: ['closed', 'written_off'] },
    { chip: 'all', label: t('investments.chip.all'), statuses: null },
  ]

const NONE_TEXT: Record<Chip, string> = {
  active: t('investments.none.active'),
  closed: t('investments.none.closed'),
  all: t('investments.none.all'),
}

export const STATUS_LABELS: Record<InvestmentStatus, string> = {
  active: t('investments.status.active'),
  closed: t('investments.status.closed'),
  written_off: t('investments.status.writtenOff'),
}

/** The chip in the URL (`?status=`); an unknown or missing one is "Active". */
export function parseChip(value: string | null): Chip {
  return CHIPS.find((c) => c.chip === value)?.chip ?? 'active'
}

/** The investment expanded in the URL (`?investment=<id>`); null if none or not an id. */
export function parseOpen(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null
  return Number(value)
}

export function noneText(chip: Chip, query: string): string {
  const q = query.trim()
  return q === '' ? NONE_TEXT[chip] : t('investments.noneMatching', { none: NONE_TEXT[chip], query: q })
}

export function emptyText(filtered: boolean): string {
  return filtered ? EMPTY_CHOSEN_TEXT : EMPTY_TEXT
}

/** Does it match the search? An amount ("300000", "300,000") matches if any of its movements
 * or figures starts with those digits; otherwise the text is searched in the name, "With whom"
 * and each movement's merchant (ignoring case and accents). */
export function investmentMatches(investment: Investment, query: string): boolean {
  const amount = amountQuery(query)
  if (amount !== null) {
    const amounts = [
      ...investment.entries.map((e) => e.amount_cents),
      investment.contributed_cents,
      investment.pending_cents,
      investment.returns_cents,
    ]
    return amounts.some((c) => centsText(c).startsWith(amount))
  }
  const needle = fold(query.trim())
  if (needle === '') return true
  const texts = [
    investment.title,
    investment.name,
    investment.with_whom,
    ...investment.entries.map((e) => e.merchant),
  ]
  return texts.some((text) => fold(text).includes(needle))
}

/** The chip's investments that match the search, in the server's order. */
export function filterInvestments(
  all: readonly Investment[],
  chip: Chip,
  query: string,
): Investment[] {
  const statuses = CHIPS.find((c) => c.chip === chip)?.statuses ?? null
  return all.filter(
    (i) => (statuses === null || statuses.includes(i.status)) && investmentMatches(i, query),
  )
}

/** What is listed and, if the expanded one no longer matches on return, it too (in its place). */
export function withPinned(
  all: readonly Investment[],
  shown: readonly Investment[],
  pinned: number | null,
): Investment[] {
  if (pinned === null || shown.some((i) => i.id === pinned)) return [...shown]
  if (!all.some((i) => i.id === pinned)) return [...shown]
  const ids = new Set([...shown.map((i) => i.id), pinned])
  return all.filter((i) => ids.has(i.id))
}

export function chipCounts(all: readonly Investment[]): Record<Chip, number> {
  const count = (chip: Chip) => filterInvestments(all, chip, '').length
  return { active: count('active'), closed: count('closed'), all: all.length }
}

/** "12.5 %" with one decimal (like amounts, with a dot); "—" without time invested. */
export function rateText(rate: number | null): string {
  if (rate === null) return '—'
  return `${(rate * 100).toFixed(1)} %`
}

/** "Pedro · since 2 Dec 2025 · last payment 29 Dec 2025": with whom (if not the title), the
 * dates and the last payment. */
export function investmentMeta(investment: Investment): string {
  const who = investment.with_whom === investment.title ? '' : investment.with_whom
  const range = dateRange(investment.first_day, investment.last_activity)
  const credit = investment.last_credit
  const last = credit
    ? t('investments.meta.lastCredit', { day: dateRange(credit, credit) })
    : t('investments.meta.noCredits')
  return [who, range, last].filter((part) => part !== '').join(' · ')
}

export interface Stat {
  key: 'contributed' | 'returned' | 'pending' | 'returns' | 'rate'
  label: string
  value: string
}

/** The figures of an investment, in its currency. */
export function investmentStats(investment: Investment): Stat[] {
  const money = (cents: number) => formatMoney(cents, investment.currency)
  return [
    {
      key: 'contributed',
      label: t('investments.stat.contributed'),
      value: money(investment.contributed_cents),
    },
    {
      key: 'returned',
      label: t('investments.stat.returned'),
      value: money(investment.capital_returned_cents),
    },
    { key: 'pending', label: t('investments.stat.pending'), value: money(investment.pending_cents) },
    { key: 'returns', label: t('investments.stat.returns'), value: money(investment.returns_cents) },
    { key: 'rate', label: t('investments.stat.rate'), value: rateText(investment.annual_rate) },
  ]
}

/** "Return", "Capital returned" or "Mixed: RD$ 50,000 of capital + RD$ 10,000 of return". */
export function entryRole(entry: InvestmentEntry): string {
  const extra =
    entry.excess_cents > 0
      ? t('investments.entry.excess', { amount: formatMoney(entry.excess_cents, entry.currency) })
      : ''
  if (entry.role !== 'mixed') return `${ROLE_LABELS[entry.role]}${extra}`
  return t('investments.entry.mixed', {
    capital: formatMoney(entry.capital_cents, entry.currency),
    returns: formatMoney(entry.return_cents, entry.currency),
    extra,
  })
}

/** Warning if more capital came back than was contributed: the excess counts as a return. */
export function excessWarning(investment: Investment): string | null {
  if (investment.excess_cents <= 0) return null
  const amount = formatMoney(investment.excess_cents, investment.currency)
  return t('investments.excessWarning', { amount })
}

/** Warning if a movement in another currency does not add up for lack of a rate. */
export function unconvertedWarning(investment: Investment): string | null {
  const count = investment.unconverted_count
  if (count === 0) return null
  return t('investments.unconvertedWarning', { count })
}

export interface Figure {
  key: 'pending' | 'year' | 'active'
  label: string
  value: string
  extra: string | null
}

/** The three figures on top (≈ RD$); US$ without a rate go apart, without making anything up. */
export function investmentFigures(list: InvestmentList): Figure[] {
  return [
    {
      key: 'pending',
      label: t('investments.figure.pending'),
      value: t('investments.figure.approx', { amount: formatDop(list.pending_dop_cents) }),
      extra: unconvertedNote(list.unconverted.pending_usd_cents),
    },
    {
      key: 'year',
      label: t('investments.figure.year'),
      value: t('investments.figure.approx', { amount: formatDop(list.returns_year_dop_cents) }),
      extra: unconvertedNote(list.unconverted.returns_usd_cents),
    },
    {
      key: 'active',
      label: t('investments.figure.active'),
      value: t('investments.figure.activeCount', { count: list.active_count }),
      extra: null,
    },
  ]
}

/** The Investments URL with the chip, the search and the expanded one (without empty or default
 * values), keeping the other parameters (the accounts). */
export function investmentParams(
  current: URLSearchParams,
  next: { chip?: Chip; query?: string; open?: number | null },
): URLSearchParams {
  const copy = new URLSearchParams(current)
  const put = (key: string, value: string | null) => {
    if (value === null || value === '') copy.delete(key)
    else copy.set(key, value)
  }
  if (next.chip !== undefined) put(STATUS_PARAM, next.chip === 'active' ? null : next.chip)
  if (next.query !== undefined) put(QUERY_PARAM, next.query)
  if (next.open !== undefined) put(OPEN_PARAM, next.open === null ? null : String(next.open))
  return copy
}

/** Body for a credit's role, or the error shown. A mixed one needs the capital part: greater
 * than 0 and less than the credit (the rest is a return). */
export function roleBody(
  role: CreditRole,
  capital: string,
  amountCents: number,
): { body: RoleBody } | { error: string } {
  if (role !== 'mixed') return { body: { role } }
  const cents = parseCents(capital)
  if (cents === null) return { error: t('investments.role.capitalMissing') }
  if (cents >= amountCents) return { error: t('investments.role.capitalTooBig') }
  return { body: { role, capital_cents: cents } }
}

/** "of that, RD$ X went to investments"; null without contributions in the month. */
export function investedNote(investedCents: number): string | null {
  if (investedCents <= 0) return null
  return t('investments.investedNote', { amount: formatDop(investedCents) })
}
