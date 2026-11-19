// The cash box in the interface (pure logic). The server does the math
// (src/michelito/analysis/cash_box.py); here only texts and request bodies are built.
import { t } from '@/i18n'
import type {
  CashBox,
  CashCurrency,
  CashEntryBody,
  CashEntryKind,
  CashLine,
  CashLineKind,
  CurrencyAmount,
  DepositBody,
  Tx,
} from './api'
import { formatMoney, parseCents } from './links'
import { formatDop } from './money'

export const CASH_BOX_KEY = 'manual:cash-box'
export const CASH_KIND = 'cash'
export const CASH_BOX_ID = 'cash-box'
export const CASH_BOX_HREF = `/accounts#${CASH_BOX_ID}`
/** Dates of hand-written entries (the same the server validates): from here to today + 31. */
export const FIRST_DAY = '2000-01-01'
const DAYS_AHEAD = 31

/** Today as "YYYY-MM-DD" in local time. */
export function localToday(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** The last day that can be entered: `today` ("YYYY-MM-DD") + 31 days. */
export function lastDay(today: string): string {
  const [year, month, day] = today.split('-').map(Number)
  const limit = new Date(Date.UTC(year, month - 1, day + DAYS_AHEAD))
  return limit.toISOString().slice(0, 10)
}

export const LINE_LABELS: Record<CashLineKind, string> = {
  initial: t('cashBox.line.initial'),
  income: t('cashBox.line.income'),
  expense: t('cashBox.line.expense'),
  stored: t('cashBox.line.stored'),
  deposit: t('cashBox.line.deposit'),
}

/** Title of each form for hand-written entries. */
export const ENTRY_TITLES: Record<CashEntryKind, string> = {
  initial: t('cashBox.entryTitle.initial'),
  income: t('cashBox.entryTitle.income'),
  expense: t('cashBox.entryTitle.expense'),
}

/** "of that, RD$ X went to the cash box"; null without stored withdrawals in the month. */
export function cashBoxNote(cents: number): string | null {
  if (cents <= 0) return null
  return t('cashBox.note', { amount: formatDop(cents) })
}

/** Balance per currency: "RD$ 5,000 + US$ 200.00"; empty, "RD$ 0". */
export function balanceText(balances: readonly CurrencyAmount[]): string {
  const shown = balances.filter((b) => b.amount_cents !== 0)
  if (shown.length === 0) return formatDop(0)
  return shown.map((b) => formatMoney(b.amount_cents, b.currency)).join(' + ')
}

/** "≈ RD$ 17,620" and, if something has no rate, "+ US$ 50.00 without a rate"; null if all is in RD$. */
export function approxText(box: CashBox): string | null {
  const foreign = box.balances.some((b) => b.currency !== 'DOP' && b.amount_cents !== 0)
  if (!foreign) return null
  const aside = box.unconverted
    .filter((u) => u.amount_cents !== 0)
    .map((u) => t('cashBox.approx.withoutRate', { amount: formatMoney(u.amount_cents, u.currency) }))
  return [t('cashBox.approx.total', { amount: formatDop(box.total_dop_cents) }), ...aside].join(' ')
}

/** The balance of `currency` after moving `deltaCents` (negative: out); null if it is not negative. */
export function balanceAfter(box: CashBox, currency: string, deltaCents: number): number | null {
  const now = box.balances.find((b) => b.currency === currency)?.amount_cents ?? 0
  const left = now + deltaCents
  return left < 0 ? left : null
}

/** "The box would be at −US$ 200.00; adjust the initial balance?" (before saving). */
export function wouldBeNegative(currency: string, cents: number): string {
  return t('cashBox.wouldBeNegative', { amount: formatMoney(cents, currency) })
}

/** "The box is at −US$ 200.00; adjust the initial balance?" (already saved). */
export function isNegative(item: CurrencyAmount): string {
  return t('cashBox.isNegative', { amount: formatMoney(item.amount_cents, item.currency) })
}

/** The link to the row in Transactions (its month and the row chosen). */
export function lineHref(line: CashLine): string {
  return `/transactions?month=${line.day.slice(0, 7)}&tx=${encodeURIComponent(line.fingerprint)}`
}

/** The warning before deleting a hand-written entry; if it is in a shared group, it says so. */
export function deleteWarning(group: string | null): string {
  const base = t('cashBox.delete.warning')
  if (group === null) return base
  return t('cashBox.delete.warningInGroup', { base, group })
}

/** Amount of a line with its sign: "+RD$ 5,000", "−US$ 100.00"; without a rate, the credit's. */
export function lineAmount(line: CashLine): string {
  if (line.amount_cents === null) {
    const amount = formatMoney(line.source_amount_cents, line.source_currency)
    return t('cashBox.lineAmount.withoutRate', { amount })
  }
  const text = formatMoney(Math.abs(line.amount_cents), line.currency)
  return `${line.amount_cents < 0 ? '−' : '+'}${text}`
}

/** What a line says under its kind: the account of the withdrawal or deposit, the category and
 * the note of a hand-written entry; for a deposit in another currency, how much it was at the bank. */
export function lineDetail(line: CashLine): string {
  const parts: string[] = []
  if (line.kind === 'stored' || line.kind === 'deposit') parts.push(line.account_label)
  if (line.kind === 'income' || line.kind === 'expense') parts.push(line.category)
  if (line.kind === 'deposit' && line.source_currency !== line.currency) {
    parts.push(
      t('cashBox.lineDetail.atBank', {
        amount: formatMoney(line.source_amount_cents, line.source_currency),
      }),
    )
  }
  if (line.note) parts.push(line.note)
  return parts.join(' · ')
}

export interface EntryDraft {
  kind: CashEntryKind
  day: string
  amount: string
  currency: CashCurrency
  categoryId: number | null
  note: string
}

export function emptyDraft(kind: CashEntryKind, today: string): EntryDraft {
  return { kind, day: today, amount: '', currency: 'DOP', categoryId: null, note: '' }
}

/** The draft of a hand-written line (to edit it). */
export function draftOfLine(line: CashLine): EntryDraft {
  return {
    kind: line.kind as CashEntryKind,
    day: line.day,
    amount: (line.source_amount_cents / 100).toFixed(2),
    currency: line.currency as CashCurrency,
    categoryId: line.category_id,
    note: line.note,
  }
}

/** The request body or the error shown. `today`: for the date range. */
export function entryBody(draft: EntryDraft, today: string): CashEntryBody | string {
  const cents = parseCents(draft.amount)
  if (cents === null) return t('cashBox.error.amount')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.day)) return t('cashBox.error.day')
  if (draft.day < FIRST_DAY || draft.day > lastDay(today)) {
    return t('cashBox.error.dayRange', { first: FIRST_DAY, last: lastDay(today) })
  }
  const body: CashEntryBody = {
    kind: draft.kind,
    day: draft.day,
    amount_cents: cents,
    currency: draft.currency,
  }
  if (draft.kind === 'initial') return body
  return { ...body, category_id: draft.categoryId, note: draft.note.trim() || null }
}

/** How much the balance changes with what is about to be saved (negative: out). `previous`: the
 * line being edited, which stops counting. */
export function draftDelta(body: CashEntryBody, previous: CashLine | null = null): number {
  const signed = body.kind === 'expense' ? -body.amount_cents : body.amount_cents
  const before = previous && previous.currency === body.currency ? (previous.amount_cents ?? 0) : 0
  return signed - before
}

/** A deposit of `tx` that leaves the box in `currency` (the credit's unless another is chosen)
 * and, in another currency, for `amount` (empty: at the month's rate). */
export function depositBody(tx: Tx, currency: CashCurrency, amount: string): DepositBody | string {
  if (currency === tx.currency) return {}
  if (amount.trim() === '') return { currency }
  const cents = parseCents(amount)
  if (cents === null) return t('cashBox.error.amount')
  return { currency, amount_cents: cents }
}

/** What the detail of a transaction tied to the box says. */
export function cashBoxText(tx: Tx): string {
  if (tx.cash_box_role === 'stored') return t('cashBox.tx.stored')
  if (tx.cash_box_role === 'deposit') {
    if (tx.cash_box_currency && tx.cash_box_currency !== tx.currency) {
      const taken =
        tx.cash_box_amount_cents === null
          ? t('cashBox.tx.withoutRate')
          : t('cashBox.tx.taken', {
              amount: formatMoney(tx.cash_box_amount_cents, tx.cash_box_currency),
            })
      return t('cashBox.tx.depositTaken', { taken })
    }
    return t('cashBox.tx.deposit')
  }
  if (tx.can_store) return t('cashBox.tx.canStore')
  return t('cashBox.tx.canDeposit')
}

/** Does the detail show the cash box section? */
export function showCashBox(tx: Tx): boolean {
  return tx.can_store || tx.can_deposit || tx.cash_box_role !== ''
}
