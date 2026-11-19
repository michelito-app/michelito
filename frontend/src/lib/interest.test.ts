import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { DuePayment, Interest, StatementLine } from './api'
import {
  interestYear,
  minimumText,
  nextDueText,
  payNote,
  payText,
  verdictText,
  yearTotalText,
} from './interest'
import { shortDay } from './months'

const AMOUNTS = ['RD$ 45,123', 'US$ 31.97'].join(t('summary.interest.amountsSeparator'))
const DAY = shortDay('2026-12-14')

function toPay(patch: Partial<DuePayment> = {}): DuePayment {
  return {
    due_date: '2026-12-14',
    amounts: [
      { currency: 'DOP', cents: 4512345 },
      { currency: 'USD', cents: 3197 },
    ],
    minimums: [
      { currency: 'DOP', cents: 225000 },
      { currency: 'USD', cents: 2500 },
    ],
    text: 'server sentence',
    ...patch,
  }
}

function line(patch: Partial<StatementLine> = {}): StatementLine {
  return {
    period_start: '2026-10-21',
    period_end: '2026-11-20',
    currency: 'DOP',
    charges_cents: 1000000,
    payments_cents: 0,
    balance_cents: 1415000,
    due_date: '2026-12-14',
    minimum_payment_cents: 71000,
    paid_full: null,
    left_over_cents: null,
    paid_late: false,
    next_interest_cents: 0,
    printout: false,
    ...patch,
  }
}

function interest(patch: Partial<Interest> = {}): Interest {
  return {
    year: 2026,
    lines: [],
    total_dop_cents: 0,
    unconverted_usd_cents: 0,
    next_due: null,
    ...patch,
  }
}

describe('payText', () => {
  it('says how much to pay in each currency and before when', () => {
    expect(payText(toPay(), '2026-12-01')).toBe(
      t('summary.interest.pay', { amounts: AMOUNTS, day: DAY }),
    )
  })

  it('the due date itself is still "before"', () => {
    expect(payText(toPay(), '2026-12-14')).toBe(
      t('summary.interest.pay', { amounts: AMOUNTS, day: DAY }),
    )
  })

  it('when the due date has passed, it says it is overdue', () => {
    expect(payText(toPay(), '2026-12-15')).toBe(
      t('summary.interest.payOverdue', { amounts: AMOUNTS, day: DAY }),
    )
  })

  it('with a currency it cannot show it uses the server sentence', () => {
    const odd = toPay({ amounts: [{ currency: 'EUR', cents: 1000 }], text: 'server sentence' })
    expect(payText(odd, '2026-12-01')).toBe('server sentence')
  })
})

describe('payNote', () => {
  it('short line for the account list', () => {
    expect(payNote(toPay(), '2026-12-01')).toBe(
      t('summary.interest.note', { amounts: AMOUNTS, day: DAY }),
    )
    expect(payNote(toPay(), '2026-12-20')).toBe(
      t('summary.interest.noteOverdue', { amounts: AMOUNTS, day: DAY }),
    )
  })
})

describe('minimumText', () => {
  it('joins the minimums of each currency', () => {
    expect(minimumText(toPay())).toBe(
      t('summary.interest.minimum', {
        amounts: ['RD$ 2,250', 'US$ 25.00'].join(t('summary.interest.amountsSeparator')),
      }),
    )
  })

  it('without printed minimums it says nothing', () => {
    expect(minimumText(toPay({ minimums: [] }))).toBeNull()
  })
})

describe('verdictText', () => {
  it('the last statement has no verdict', () => {
    expect(verdictText(line())).toBeNull()
  })

  it('paid in full', () => {
    expect(verdictText(line({ paid_full: true }))).toEqual({
      text: t('summary.interest.paidFull'),
      tone: 'paid',
      interest: null,
    })
  })

  it('paid late: the balance was covered but after the due date', () => {
    expect(
      verdictText(
        line({
          paid_full: false,
          paid_late: true,
          left_over_cents: 1415000,
          next_interest_cents: 28740,
        }),
      ),
    ).toEqual({
      text: t('summary.interest.paidLate'),
      tone: 'owed',
      interest: t('summary.interest.charged', { amount: 'RD$ 287' }),
    })
  })

  it('what was left unpaid and the interest the next statement charged', () => {
    expect(
      verdictText(line({ paid_full: false, left_over_cents: 615000, next_interest_cents: 28740 })),
    ).toEqual({
      text: t('summary.interest.leftOver', { amount: 'RD$ 6,150' }),
      tone: 'owed',
      interest: t('summary.interest.charged', { amount: 'RD$ 287' }),
    })
  })

  it('in dollars with two decimals', () => {
    const usd = line({
      currency: 'USD',
      paid_full: false,
      left_over_cents: 1050,
      next_interest_cents: 123,
    })
    expect(verdictText(usd)).toEqual({
      text: t('summary.interest.leftOver', { amount: 'US$ 10.50' }),
      tone: 'owed',
      interest: t('summary.interest.charged', { amount: 'US$ 1.23' }),
    })
  })

  it('interest without a verdict (credit balance) shows only the interest', () => {
    expect(verdictText(line({ balance_cents: 0, next_interest_cents: 5000 }))).toEqual({
      text: null,
      tone: 'owed',
      interest: t('summary.interest.charged', { amount: 'RD$ 50' }),
    })
  })
})

describe('interestYear', () => {
  it('the year of the month being viewed', () => {
    expect(interestYear('2026-01')).toBe(2026)
  })
})

describe('yearTotalText', () => {
  it('the year\'s total in RD$', () => {
    expect(yearTotalText(interest({ total_dop_cents: 2350700 }))).toBe('RD$ 23,507')
  })
})

describe('nextDueText', () => {
  it('the next payment so no interest accrues', () => {
    const next = { ...toPay(), key: 'popular:credit_card', label: 'VISA ···1234' }
    expect(nextDueText(next)).toBe(t('summary.interest.next', { amounts: AMOUNTS, day: DAY }))
    const odd = { ...next, amounts: [{ currency: 'EUR', cents: 1 }] }
    expect(nextDueText(odd)).toBe(t('summary.interest.nextServer', { text: 'server sentence' }))
  })
})
