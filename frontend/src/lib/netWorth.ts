// Net worth on the Accounts screen (pure logic). The server values every holding in RD$ and
// builds the monthly history (src/michelito/web/net_worth.py); this picks the period, the
// changes and the summary's shares.
import { t } from '@/i18n'
import { dueNote } from './accounts'
import type { Loan, NetWorth, NetWorthGroup, NetWorthHolding, NetWorthPoint } from './api'
import { formatMoney } from './links'
import { formatDop } from './money'

export type Period = '1M' | '3M' | '1A' | 'ALL'
export type Side = 'asset' | 'debt'

export const PERIODS: readonly Period[] = ['1M', '3M', '1A', 'ALL']

/** Points shown per period: the months asked for plus the one they start from. */
const POINTS: Record<Exclude<Period, 'ALL'>, number> = { '1M': 2, '3M': 4, '1A': 13 }

const DEBTS: ReadonlySet<NetWorthGroup> = new Set(['cards', 'loans', 'owing'])

export function sideOf(group: NetWorthGroup): Side {
  return DEBTS.has(group) ? 'debt' : 'asset'
}

/** The last points of the history for the period (all of them if there are fewer). */
export function pointsFor(history: readonly NetWorthPoint[], period: Period): NetWorthPoint[] {
  if (period === 'ALL') return [...history]
  return history.slice(-POINTS[period])
}

/** Net worth's change over the points shown (null with fewer than two). */
export function changeOf(points: readonly NetWorthPoint[]): number | null {
  if (points.length < 2) return null
  return points[points.length - 1].net_cents - points[0].net_cents
}

/** Does this change help net worth? A rise helps an asset and hurts a debt. */
export function isGood(cents: number, side: Side): boolean {
  return side === 'asset' ? cents > 0 : cents < 0
}

/** The month's change with an arrow and the amount; nothing without a change. */
export function changeLine(cents: number | null): string | null {
  if (cents === null || cents === 0) return null
  return t('accounts.change.month', {
    arrow: cents > 0 ? '↑' : '↓',
    amount: formatDop(Math.abs(cents)),
  })
}

/** An account's change in RD$, adding its currencies (null when none is known). */
export function holdingChange(holdings: readonly NetWorthHolding[], key: string): number | null {
  const known = holdings
    .filter((h) => h.key === key && h.change_dop_cents !== null)
    .map((h) => h.change_dop_cents ?? 0)
  return known.length === 0 ? null : known.reduce((a, b) => a + b, 0)
}

export interface Share {
  group: NetWorthGroup
  total_cents: number
  share: number // of the side's total, 0..1
}

/** Each side split by group, largest first; empty groups are left out. */
export function shares(worth: NetWorth, side: Side): Share[] {
  const mine = worth.groups.filter((g) => g.side === side && g.total_cents > 0)
  const total = mine.reduce((sum, g) => sum + g.total_cents, 0)
  return mine
    .map((g) => ({ group: g.group, total_cents: g.total_cents, share: g.total_cents / total }))
    .sort((a, b) => b.total_cents - a.total_cents)
}

const GROUP_NAMES = {
  cards: () => t('accounts.group.cards'),
  loans: () => t('accounts.group.loans'),
  banks: () => t('accounts.group.banks'),
  cash: () => t('accounts.group.cash'),
  investments: () => t('accounts.group.investments'),
  owed: () => t('accounts.group.owed'),
  owing: () => t('accounts.group.owing'),
} satisfies Record<NetWorthGroup, () => string>

/** The group's name, as the catalog says it. */
export function groupName(group: NetWorthGroup): string {
  return GROUP_NAMES[group]()
}

const PERIOD_CHANGES = {
  '1M': () => t('accounts.netWorth.in.1M'),
  '3M': () => t('accounts.netWorth.in.3M'),
  '1A': () => t('accounts.netWorth.in.1A'),
  ALL: () => t('accounts.netWorth.in.ALL'),
} satisfies Record<Period, () => string>

/** The period the change covers ("in 3 months"). */
export function periodPhrase(period: Period): string {
  return PERIOD_CHANGES[period]()
}

const PERIOD_NAMES = {
  '1M': () => t('accounts.netWorth.period.1M'),
  '3M': () => t('accounts.netWorth.period.3M'),
  '1A': () => t('accounts.netWorth.period.1A'),
  ALL: () => t('accounts.netWorth.period.ALL'),
} satisfies Record<Period, () => string>

export function periodName(period: Period): string {
  return PERIOD_NAMES[period]()
}

/** Days ahead in which an installment or a card payment is worth a notice on its row. */
export const NOTICE_DAYS = 8
const DAY_MS = 86_400_000

/** The next installment and when it is due, if within NOTICE_DAYS. */
export function loanNotice(
  loan: Pick<Loan, 'next_due' | 'next_payment_cents' | 'currency'>,
  today: string,
): string | null {
  if (loan.next_due === null || loan.next_payment_cents === null) return null
  const days = Math.round((Date.parse(loan.next_due) - Date.parse(today)) / DAY_MS)
  if (days < 0 || days > NOTICE_DAYS) return null
  return t('accounts.row.loanDue', {
    amount: formatMoney(loan.next_payment_cents, loan.currency),
    when: dueNote(loan.next_due, today),
  })
}
