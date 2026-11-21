import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { ReviewItem } from './api'
import {
  approxText,
  conversionText,
  convertCents,
  leftoverText,
  memberBalanceText,
  rateText,
} from './ledger'
import { itemHref } from './review'

const RATE = { value: '63.7000', month: '2026-02' }

describe('two currencies, exchange leftovers and paying for others', () => {
  // RD$ show without cents (formatDop), like the rest of the interface.
  it('says the total line in the currency the server chose, or nothing', () => {
    expect(approxText({ currency: 'DOP', cents: -2078 })).toBe(
      t('shared.total.owe', { amount: 'RD$ 21' }),
    )
    expect(approxText({ currency: 'USD', cents: 5400 })).toBe(
      t('shared.total.owed', { amount: 'US$ 54.00' }),
    )
    expect(approxText({ currency: 'USD', cents: 0 })).toBe(t('shared.total.even'))
    expect(approxText(null)).toBeNull()
  })

  it('shows an exchange leftover as settled, or next to a balance', () => {
    const leftover = [{ currency: 'DOP', cents: -2078 }]
    expect(memberBalanceText({ balance: [], leftover })).toBe(
      t('shared.leftover.settled', { amount: 'RD$ 21' }),
    )
    const owing = { balance: [{ currency: 'USD', cents: 1000 }], leftover }
    expect(memberBalanceText(owing)).toBe(
      `${t('shared.balance.owesYou', { amount: 'US$ 10.00' })} ${t('shared.leftover.also', { amount: 'RD$ 21' })}`,
    )
    expect(memberBalanceText({ balance: [] })).toBe(t('shared.balance.settled'))
    expect(leftoverText([], true)).toBeNull()
  })

  it('writes the rate and the conversion of a proposed part', () => {
    expect(rateText(RATE)).toBe(t('shared.rate.line', { value: '63.70', month: 'feb' }))
    const part = { cents: 4_008_705, equivalent: { currency: 'USD', cents: 62_931 } }
    expect(conversionText(part, 'DOP', RATE)).toBe(
      t('shared.rate.conversion', {
        amount: 'RD$ 40,087',
        converted: 'US$ 629.31',
        rate: rateText(RATE),
      }),
    )
    expect(conversionText({ ...part, equivalent: null }, 'DOP', RATE)).toBeNull()
    expect(conversionText(part, 'DOP', null)).toBeNull()
  })

  it('converts cents both ways for display', () => {
    expect(convertCents(4_008_705, 'DOP', 'USD', RATE)).toBe(62_931)
    expect(convertCents(62_931, 'USD', 'DOP', RATE)).toBe(4_008_705)
    expect(convertCents(100, 'DOP', 'DOP', RATE)).toBe(100)
  })

  it('a "paid for others?" item opens its group with the payment', () => {
    const item = {
      kind: 'possible_cover',
      fingerprint: 'ledger-payment-7',
      month: '2026-02',
      group_id: 3,
      payment_id: 7,
    } as ReviewItem
    expect(itemHref(item)).toBe('/shared/3?cover=7')
  })
})
