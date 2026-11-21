import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { afterText, planBody, planPaymentLine } from './coverPlan'
import type { CoverPlan } from './sharedApi'

const ANA = 2
const BETO = 3
const RATE = { value: '58.9000', month: '2025-10' }

const PLAN: CoverPlan = {
  text: '',
  payments: [
    {
      payment_id: 11,
      day: '2025-10-03',
      amount_cents: 9_800_000,
      currency: 'DOP',
      rate: RATE,
      allocations: [
        { contact_id: ANA, name: 'Ana', cents: 8_835_589, owed_cents: 8_835_589, equivalent: null },
        { contact_id: BETO, name: 'Beto', cents: 964_411, owed_cents: 5_835_589, equivalent: { currency: 'USD', cents: 16_374 } },
      ],
    },
    {
      payment_id: 13,
      day: '2025-10-15',
      amount_cents: 2_000_000,
      currency: 'DOP',
      rate: RATE,
      allocations: [
        { contact_id: ANA, name: 'Ana', cents: 0, owed_cents: 0, equivalent: null },
        { contact_id: BETO, name: 'Beto', cents: 2_000_000, owed_cents: 4_871_178, equivalent: { currency: 'USD', cents: 33_956 } },
      ],
    },
  ],
  after: [
    { contact_id: ANA, name: 'Ana', balance: [], leftover: [{ currency: 'DOP', cents: -1200 }] },
    { contact_id: BETO, name: 'Beto', balance: [{ currency: 'USD', cents: 6301 }], leftover: [] },
  ],
}

describe('"Yes" to a suggestion over several payments', () => {
  it('sends every payment with its proposed parts, the zero ones left out', () => {
    expect(planBody(PLAN)).toEqual({
      payments: [
        {
          payment_id: 11,
          allocations: [
            { contact_id: ANA, cents: 8_835_589 },
            { contact_id: BETO, cents: 964_411 },
          ],
        },
        { payment_id: 13, allocations: [{ contact_id: BETO, cents: 2_000_000 }] },
      ],
    })
  })

  it('names each payment and says the balances after', () => {
    expect(planPaymentLine(PLAN.payments[0])).toBe(
      t('shared.plan.payment', { day: '3 oct', amount: 'RD$ 98,000' }),
    )
    expect(afterText(PLAN.after[0])).toBe(t('shared.leftover.settled', { amount: 'RD$ 12' }))
    expect(afterText(PLAN.after[1])).toBe(t('shared.balance.owesYou', { amount: 'US$ 63.01' }))
  })
})
