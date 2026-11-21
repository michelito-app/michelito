import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { afterText, planBody, planPaymentLine } from './coverPlan'
import type { CoverPlan } from './sharedApi'

const ANA = 2
const BETO = 3
const RATE = { value: '61.2100', month: '2025-10' }

const PLAN: CoverPlan = {
  text: '',
  payments: [
    {
      payment_id: 11,
      day: '2025-10-03',
      amount_cents: 12_500_000,
      currency: 'DOP',
      rate: RATE,
      allocations: [
        { contact_id: ANA, name: 'Ana', cents: 11_715_900, owed_cents: 11_715_900, equivalent: null },
        { contact_id: BETO, name: 'Beto', cents: 784_100, owed_cents: 7_615_900, equivalent: { currency: 'USD', cents: 12_810 } },
      ],
    },
    {
      payment_id: 13,
      day: '2025-10-15',
      amount_cents: 2_500_000,
      currency: 'DOP',
      rate: RATE,
      allocations: [
        { contact_id: ANA, name: 'Ana', cents: 0, owed_cents: 0, equivalent: null },
        { contact_id: BETO, name: 'Beto', cents: 2_500_000, owed_cents: 6_831_800, equivalent: { currency: 'USD', cents: 40_843 } },
      ],
    },
  ],
  after: [
    { contact_id: ANA, name: 'Ana', balance: [], leftover: [{ currency: 'DOP', cents: -1200 }] },
    { contact_id: BETO, name: 'Beto', balance: [{ currency: 'USD', cents: 2975 }], leftover: [] },
  ],
}

describe('"Yes" to a suggestion over several payments', () => {
  it('sends every payment with its proposed parts, the zero ones left out', () => {
    expect(planBody(PLAN)).toEqual({
      payments: [
        {
          payment_id: 11,
          allocations: [
            { contact_id: ANA, cents: 11_715_900 },
            { contact_id: BETO, cents: 784_100 },
          ],
        },
        { payment_id: 13, allocations: [{ contact_id: BETO, cents: 2_500_000 }] },
      ],
    })
  })

  it('names each payment and says the balances after', () => {
    expect(planPaymentLine(PLAN.payments[0])).toBe(
      t('shared.plan.payment', { day: '3 oct', amount: 'RD$ 125,000' }),
    )
    expect(afterText(PLAN.after[0])).toBe(t('shared.leftover.settled', { amount: 'RD$ 12' }))
    expect(afterText(PLAN.after[1])).toBe(t('shared.balance.owesYou', { amount: 'US$ 29.75' }))
  })
})
