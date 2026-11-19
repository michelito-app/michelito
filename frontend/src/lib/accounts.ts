// Grouping, selection and texts of the Accounts screen (pure logic).
import { t } from '@/i18n'
import type { Account, StatementLine } from './api'
import { formatDop, formatUsd } from './money'
import { monthName, shortDay } from './months'

const CREDIT_CARD = 'credit_card'
const DASH = '—'
const SYMBOLS: Record<string, string> = { DOP: 'RD$', USD: 'US$' }
const DAY_MS = 86_400_000

export interface AccountGroups {
  cards: Account[]
  others: Account[]
}

export interface Status {
  text: string
  missing: boolean
}

/** Is it a credit card? Only cards have a due date and a minimum payment. */
export function isCreditCard(account: Account): boolean {
  return account.kind === CREDIT_CARD
}

/** Headings for charges and credits: purchases and payments only exist on credit cards. */
export function movementLabels(account: Account): {
  charges: string
  payments: string
} {
  return isCreditCard(account)
    ? { charges: t('accounts.labels.purchases'), payments: t('accounts.labels.payments') }
    : { charges: t('accounts.labels.debits'), payments: t('accounts.labels.credits') }
}

/** Splits "Visa ···1234" into the name and "···1234" so the last digits never wrap. */
export function splitLabel(label: string): { name: string; tail: string } {
  const at = label.indexOf('···')
  if (at < 0) return { name: label, tail: '' }
  return { name: label.slice(0, at).trimEnd(), tail: label.slice(at) }
}

// Bank account type from its stored name, which is the bank's own Spanish text
// ("POPULAR Cuenta de ahorro 100200300"): the patterns match that text. // spanish-data
const BANK_TYPES: readonly { pattern: RegExp; word: () => string }[] = [
  { pattern: /\bahorros?\b/i, word: () => t('accounts.bankType.savings') }, // spanish-data
  { pattern: /\bcorriente\b/i, word: () => t('accounts.bankType.checking') }, // spanish-data
]
const TRAILING_NUMBER = /(\d[\d-]*)\s*$/

/** Short name for narrow rows: a bank account becomes its type and the last 4 digits of its
 * number ("<type> ···0300"); cards ("MC BLACK ···0000") and anything unrecognised stay as they are.
 * The full name is still available as `title`. */
export function shortAccountLabel(label: string): string {
  if (label.includes('···')) return label
  const word = BANK_TYPES.find((type) => type.pattern.test(label))?.word()
  const digits = TRAILING_NUMBER.exec(label)?.[1].replace(/\D/g, '') ?? ''
  if (!word || digits === '') return label
  return `${word} ···${digits.slice(-4)}`
}

/** Credit cards on one side; debit, savings and the rest on the other. */
export function groupAccounts(accounts: readonly Account[]): AccountGroups {
  return {
    cards: accounts.filter(isCreditCard),
    others: accounts.filter((a) => !isCreditCard(a)),
  }
}

/** The requested account if it exists; otherwise the first card (or the first account). */
export function resolveAccount(
  accounts: readonly Account[],
  requested: string | null,
): Account | null {
  return (
    accounts.find((a) => a.key === requested) ??
    accounts.find(isCreditCard) ??
    accounts[0] ??
    null
  )
}

/** Amount in the line's currency; "—" when the statement does not have it. */
export function amountText(cents: number | null, currency: string): string {
  if (cents === null) return DASH
  return currency === 'USD' ? formatUsd(cents) : formatDop(cents)
}

/** Cut day and currencies, e.g. "… 20 · RD$ … US$". */
export function cutLine(account: Account): string {
  if (account.cut_day === null) return t('accounts.noStatementsYet')
  const currencies = account.currencies
    .map((c) => SYMBOLS[c] ?? c)
    .join(t('accounts.currencyJoin'))
  return t('accounts.cutLine', { day: account.cut_day, currencies })
}

/** The statement period ("21 sep – 20 oct"); without a known start, only its end; a portal
 * printout says so and which days it covers. */
export function periodText(line: StatementLine): string {
  const end = shortDay(line.period_end)
  if (line.printout) {
    const start = line.period_start ? shortDay(line.period_start) : end
    return t('accounts.period.printout', { start, end })
  }
  return line.period_start
    ? t('accounts.period.range', { start: shortDay(line.period_start), end })
    : t('accounts.period.until', { end })
}

/** The cut column: the cut day; a portal printout has no cut ("—"). */
export function cutText(line: StatementLine): string {
  return line.printout ? DASH : shortDay(line.period_end)
}

function lastCut(account: Account): string | null {
  return account.latest[0]?.period_end ?? null
}

/** Month of the missing statement (the one after the last cut), or null when up to date. */
export function missingMonth(account: Account): string | null {
  const cut = lastCut(account)
  if (!account.missing_statement || cut === null) return null
  const next = (Number(cut.slice(5, 7)) % 12) + 1
  return monthName(`2000-${String(next).padStart(2, '0')}`)
}

/** Status line of the account in the list. */
export function statusText(account: Account): Status {
  const cut = lastCut(account)
  if (cut === null) return { text: t('accounts.noStatementsYet'), missing: false }
  const missing = missingMonth(account)
  if (missing === null) {
    return { text: t('accounts.status.upToDate', { day: shortDay(cut) }), missing: false }
  }
  return {
    text: t('accounts.status.missing', { day: shortDay(cut), month: missing }),
    missing: true,
  }
}

function dayNumber(iso: string): number {
  return Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)))
}

/** How long until the due date; once it has passed, only which cut it belongs to. */
export function dueNote(due: string, today: string, cut?: string): string {
  const days = Math.round((dayNumber(due) - dayNumber(today)) / DAY_MS)
  if (days === 0) return t('accounts.due.today')
  if (days === 1) return t('accounts.due.tomorrow')
  if (days > 1) return t('accounts.due.inDays', { days })
  return cut ? t('accounts.due.ofStatement', { day: shortDay(cut) }) : ''
}

/** Note under the statements table. */
export function footnote(account: Account): string {
  const missing = missingMonth(account)
  if (missing !== null) {
    return t('accounts.footnote.missing', { month: missing })
  }
  if (account.currencies.length > 1) return t('accounts.footnote.twoCurrencies')
  return t('accounts.footnote.default')
}
