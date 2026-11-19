// One-off expense suggestions (pure logic of the Summary card and the detail panel).
import { t } from '@/i18n'
import type { OneOffSuggestion } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { shortAccountLabel } from './accounts'
import { formatDop, formatUsd } from './money'
import { shortDay } from './months'

/** "Possible one-off expenses (3)". */
export function cardTitle(count: number): string {
  return t('summary.oneOffs.cardTitle', { count })
}

/** Amount in RD$; when it was in dollars, the original too. */
export function amountText(item: OneOffSuggestion): string {
  const dop = formatDop(item.amount_dop_cents)
  return item.currency === 'DOP' ? dop : `${dop} · ${formatUsd(item.amount_cents)}`
}

/** "6 Feb · VISA DEMO ···4242"; a bank account goes short ("6 Feb · Savings ···0300"). */
export function metaText(item: OneOffSuggestion): string {
  return `${shortDay(item.day)} · ${shortAccountLabel(item.account_label)}`
}

/** Transactions of the purchase month, with its detail open and the chosen accounts. */
export function transactionHref(item: OneOffSuggestion, selection: Selection = null): string {
  return transactionsHref({ month: item.day.slice(0, 7), tx: item.fingerprint }, selection)
}

/** Accessible name of the link that opens the purchase in Transactions (with the full account). */
export function openLabel(item: OneOffSuggestion): string {
  const when = `${shortDay(item.day)} · ${item.account_label}`
  return t('summary.oneOffs.openLabel', { merchant: item.merchant, amount: amountText(item), when })
}

/** Path of the PUT that dismisses (or restores) a suggestion. */
export function dismissPath(fingerprint: string): string {
  return `/api/one-off-suggestions/${encodeURIComponent(fingerprint)}`
}

/** Accessible name of "It is one-off" on a merchant's row. */
export function confirmLabel(item: OneOffSuggestion): string {
  return t('summary.oneOffs.confirmLabel', { merchant: item.merchant })
}

/** Accessible name of "Not one-off" on a merchant's row. */
export function dismissLabel(item: OneOffSuggestion): string {
  return t('summary.oneOffs.dismissLabel', { merchant: item.merchant })
}
