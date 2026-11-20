// "To review" (pure logic of the Summary card and of the history in Reports).
// The rules live on the server (src/michelito/analysis/review.py).
import { t } from '@/i18n'
import type { ReviewItem, ReviewKind } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { shortAccountLabel } from './accounts'
import { formatDop, formatUsd } from './money'
import { shortDay } from './months'

/** Label of each kind, in the order of the filters. */
export const KIND_LABELS: Record<ReviewKind, string> = {
  one_off: t('review.kind.oneOff'),
  unusual_income: t('review.kind.unusualIncome'),
  large_third_party: t('review.kind.largeThirdParty'),
  duplicate: t('review.kind.duplicate'),
  price_up: t('review.kind.priceUp'),
  possible_contribution: t('review.kind.possibleContribution'),
  possible_return: t('review.kind.possibleReturn'),
  possible_rule: t('review.kind.possibleRule'),
  possible_reserve: t('review.kind.possibleReserve'),
  possible_payment: t('review.kind.possiblePayment'),
  unconfirmed: t('review.kind.unconfirmed'),
  reversal: t('review.kind.reversal'),
}

export const REVIEW_KINDS = Object.keys(KIND_LABELS) as ReviewKind[]

/** "To review (3)". */
export function cardTitle(count: number): string {
  return t('review.cardTitle', { count })
}

/** Amount in RD$; if it was in dollars, the original too (or only the US$ without a rate). */
export function amountText(item: ReviewItem): string {
  if (item.currency === 'DOP') return formatDop(item.amount_cents)
  const usd = formatUsd(item.amount_cents)
  return item.amount_dop_cents === null ? usd : `${formatDop(item.amount_dop_cents)} · ${usd}`
}

/** Short amount for the Summary row: in RD$ (or only the US$ without a rate). */
export function mainAmountText(item: ReviewItem): string {
  if (item.currency === 'DOP') return formatDop(item.amount_cents)
  return item.amount_dop_cents === null ? formatUsd(item.amount_cents) : formatDop(item.amount_dop_cents)
}

/** The original US$ when the row shows them converted; null if not needed. */
export function originalAmountText(item: ReviewItem): string | null {
  if (item.currency === 'DOP' || item.amount_dop_cents === null) return null
  return formatUsd(item.amount_cents)
}

/** "6 Feb · VISA DEMO ···4242"; a bank account goes short (see `shortAccountLabel`). */
export function metaText(item: ReviewItem): string {
  return `${shortDay(item.day)} · ${shortAccountLabel(item.account_label)}`
}

/** Transactions of the movement's month, with its detail open and the chosen accounts. */
export function itemHref(item: ReviewItem, selection: Selection = null): string {
  return transactionsHref({ month: item.month, tx: item.fingerprint }, selection)
}

/** Accessible name of the link that opens the movement. */
export function openLabel(item: ReviewItem): string {
  return t('review.openLabel', {
    merchant: item.merchant,
    amount: amountText(item),
    day: shortDay(item.day),
    account: item.account_label,
  })
}

/** Accessible name of "Already reviewed" (or of "Not one-off" for a one-off expense). */
export function reviewedLabel(item: ReviewItem): string {
  const merchant = item.merchant
  if (item.kind === 'possible_rule') return t('review.dismissRuleLabel', { merchant })
  return item.kind === 'one_off'
    ? t('review.notOneOffLabel', { merchant })
    : t('review.reviewedLabel', { merchant })
}

/** Path of the PUT that marks (or unmarks) a movement as reviewed. */
export function reviewPath(kind: ReviewKind, fingerprint: string): string {
  return `/api/review/${kind}/${encodeURIComponent(fingerprint)}`
}

/** Stable key of an item: the same fingerprint can show up with two kinds. */
export function itemKey(item: Pick<ReviewItem, 'kind' | 'fingerprint'>): string {
  return `${item.kind}:${item.fingerprint}`
}
