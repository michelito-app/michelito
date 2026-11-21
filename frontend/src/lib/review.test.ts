import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { shortAccountLabel } from './accounts'
import { shortDay } from './months'
import type { ReviewItem } from './api'
import {
  amountText,
  cardTitle,
  itemHref,
  itemKey,
  KIND_LABELS,
  mainAmountText,
  metaText,
  openLabel,
  originalAmountText,
  REVIEW_KINDS,
  reviewedLabel,
  reviewPath,
} from './review'

const TRANSFER: ReviewItem = {
  kind: 'large_third_party',
  fingerprint: 'a/b c',
  day: '2026-02-13',
  month: '2026-02',
  merchant: 'TRANSFERENCIA A PERSONA',
  description: 'TRANSFERENCIA A PERSONA FICTICIA',
  account_label: 'FICTICIO Cuenta corriente 777-0', // spanish-data
  amount_cents: 100_000,
  currency: 'USD',
  amount_dop_cents: 6_370_000,
  reason: 'Third-party transfer of RD$ 63,700',
  reviewed: false,
}

describe('to review', () => {
  it('title and kinds', () => {
    expect(cardTitle(3)).toBe(t('review.cardTitle', { count: 3 }))
    expect(cardTitle(3)).toBe('Para revisar (3)') // spanish-ui
    expect(REVIEW_KINDS).toEqual([
      'one_off',
      'unusual_income',
      'large_third_party',
      'duplicate',
      'price_up',
      'possible_contribution',
      'possible_return',
      'possible_rule',
      'possible_reserve',
      'possible_payment',
      'possible_cover',
      'unconfirmed',
      'reversal',
    ])
    expect(KIND_LABELS.duplicate).toBe(t('review.kind.duplicate'))
  })

  it('amount in RD$ and, if it was in dollars, the original too', () => {
    expect(amountText(TRANSFER)).toBe('RD$ 63,700 · US$ 1,000.00')
    expect(amountText({ ...TRANSFER, amount_dop_cents: null })).toBe('US$ 1,000.00')
    expect(amountText({ ...TRANSFER, currency: 'DOP', amount_cents: 500_000 })).toBe('RD$ 5,000')
  })

  it('in the short row: RD$ on top and the original US$ apart', () => {
    expect(mainAmountText(TRANSFER)).toBe('RD$ 63,700')
    expect(originalAmountText(TRANSFER)).toBe('US$ 1,000.00')
    expect(mainAmountText({ ...TRANSFER, amount_dop_cents: null })).toBe('US$ 1,000.00')
    expect(originalAmountText({ ...TRANSFER, amount_dop_cents: null })).toBeNull()
    const dop = { ...TRANSFER, currency: 'DOP', amount_cents: 500_000 }
    expect(mainAmountText(dop)).toBe('RD$ 5,000')
    expect(originalAmountText(dop)).toBeNull()
  })

  it('date and short account', () => {
    expect(metaText(TRANSFER)).toBe(
      `${shortDay('2026-02-13')} · ${shortAccountLabel(TRANSFER.account_label)}`,
    )
    expect(metaText(TRANSFER)).toBe('13 feb · Corriente ···7770') // spanish-ui
    expect(openLabel(TRANSFER)).toBe(
      t('review.openLabel', {
        merchant: 'TRANSFERENCIA A PERSONA',
        amount: 'RD$ 63,700 · US$ 1,000.00',
        day: shortDay('2026-02-13'),
        account: TRANSFER.account_label,
      }),
    )
  })

  it('links and paths', () => {
    expect(itemHref(TRANSFER, ['k'])).toBe('/transactions?month=2026-02&tx=a%2Fb+c&accounts=k')
    expect(reviewPath('duplicate', 'a/b c')).toBe('/api/review/duplicate/a%2Fb%20c')
    expect(itemKey(TRANSFER)).toBe('large_third_party:a/b c')
  })

  it('the button of a one-off expense is "Not one-off"', () => {
    const merchant = 'TRANSFERENCIA A PERSONA'
    expect(reviewedLabel(TRANSFER)).toBe(t('review.reviewedLabel', { merchant }))
    expect(reviewedLabel({ ...TRANSFER, kind: 'one_off' })).toBe(
      t('review.notOneOffLabel', { merchant }),
    )
    expect(reviewedLabel({ ...TRANSFER, kind: 'possible_rule' })).toBe(
      t('review.dismissRuleLabel', { merchant }),
    )
  })
})
