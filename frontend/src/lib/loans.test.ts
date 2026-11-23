import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { Loan } from './api'
import {
  balanceText,
  differenceText,
  emptyForm,
  formOf,
  installmentText,
  interestLine,
  loanAccountKey,
  loanBody,
  loanEdit,
  loanIdOf,
  loanTag,
  parseRate,
  progress,
  rateText,
  remainingLine,
} from './loans'

const LOAN: Loan = {
  id: 7,
  name: 'Car loan',
  number: '1234567890',
  currency: 'DOP',
  principal_cents: 10_000_000,
  term: 12,
  start_date: '2026-01-15',
  rate_bp: 1250,
  rates: [{ effective: '2026-01-15', rate_bp: 1250 }],
  installment_cents: null,
  installments: [],
  balances: [],
  balance_cents: 7_500_000,
  paid_cents: 2_665_464,
  interest_statements_cents: 110_000,
  interest_estimated_cents: 93_000,
  installments_left: 9,
  next_due: '2026-05-15',
  next_payment_cents: 888_488,
  end_date: '2027-01-15',
  statement_months: 1,
  payments: [],
  differences: [],
  schedule: [],
}

describe('loans', () => {
  it('a loan is an account of the Accounts list with its own key', () => {
    expect(loanAccountKey(7)).toBe('loan-7')
    expect(loanIdOf('loan-7')).toBe(7)
    expect(loanIdOf('bank:savings')).toBeNull()
    expect(loanIdOf('loan-x')).toBeNull()
  })

  it('its balance reads negative, like a card', () => {
    expect(balanceText(LOAN)).toBe('−RD$ 75,000')
    expect(balanceText({ ...LOAN, balance_cents: 0 })).toBe('RD$ 0')
  })

  it("the bank's installment shows its cents", () => {
    expect(installmentText(775_666, 'DOP')).toBe('RD$ 7,756.66')
    expect(installmentText(12_000, 'USD')).toBe('US$ 120.00')
  })

  it('the share already paid off', () => {
    expect(progress(LOAN)).toBe(0.25)
    expect(progress({ ...LOAN, balance_cents: 20_000_000 })).toBe(0)
  })

  it('rates go in hundredths of a percent', () => {
    expect(rateText(1250)).toBe('12.5 %')
    expect(rateText(1200)).toBe('12 %')
    expect(parseRate('12,5')).toBe(1250)
    expect(parseRate(' 9.75 % ')).toBe(975)
    expect(parseRate('0')).toBe(0)
    expect(parseRate('101')).toBeNull()
    expect(parseRate('abc')).toBeNull()
  })

  it('what is left and when it ends', () => {
    expect(remainingLine(LOAN)).toBe(
      t('loans.card.remaining', { count: 9, month: 'enero 2027' }),
    )
    expect(remainingLine({ ...LOAN, installments_left: 0, end_date: null })).toBe(
      t('loans.card.paidOff'),
    )
  })

  it('interest paid says what comes from statements and what is estimated', () => {
    expect(interestLine(LOAN)).toBe(
      t('loans.card.interestMixed', {
        total: 'RD$ 2,030',
        statements: 'RD$ 1,100',
        estimated: 'RD$ 930',
      }),
    )
    expect(interestLine({ ...LOAN, interest_statements_cents: 0 })).toBe(
      t('loans.card.interestEstimated', { total: 'RD$ 930' }),
    )
  })

  it('a difference says what the statement and the payments or contract say', () => {
    expect(
      differenceText(LOAN, {
        kind: 'payments',
        month: '2026-02',
        expected_cents: 888_488,
        found_cents: 700_000,
        fingerprints: ['a'],
      }),
    ).toBe(
      t('loans.difference.payments', {
        month: 'febrero 2026',
        expected: 'RD$ 8,885',
        found: 'RD$ 7,000',
      }),
    )
  })

  it('a row paying a loan says which one', () => {
    expect(loanTag({ loan: { loan_id: 7, name: 'Carro' } })).toBe(
      t('loans.row.tag', { name: 'Carro' }),
    )
    expect(loanTag({ loan: null })).toBeNull()
  })

  it('the new loan form checks every field and builds the body', () => {
    const form = {
      ...emptyForm('2026-11-23'),
      name: ' Carro ',
      number: '12-3456-7890',
      principal: '100,000',
      rate: '12.5',
      term: '60',
      start: '2026-01-15',
    }
    expect(loanBody(form)).toEqual({
      error: null,
      body: {
        name: 'Carro',
        number: '12-3456-7890',
        currency: 'DOP',
        principal_cents: 10_000_000,
        rate_bp: 1250,
        term: 60,
        start_date: '2026-01-15',
      },
    })
    expect(loanBody({ ...form, installment: '9,000.50' }).body?.installment_cents).toBe(900_050)
    expect(loanBody({ ...form, installment: 'x' }).error).toBe(t('loans.form.error.installment'))
    expect(loanBody({ ...form, name: '' }).error).toBe(t('loans.form.error.name'))
    expect(loanBody({ ...form, number: '12' }).error).toBe(t('loans.form.error.number'))
    expect(loanBody({ ...form, principal: '0' }).error).toBe(t('loans.form.error.principal'))
    expect(loanBody({ ...form, rate: 'x' }).error).toBe(t('loans.form.error.rate'))
    expect(loanBody({ ...form, term: '0' }).error).toBe(t('loans.form.error.term'))
    expect(loanBody({ ...form, start: '' }).error).toBe(t('loans.form.error.start'))
  })

  it('editing sends only what changed', () => {
    const form = formOf(LOAN)
    expect(loanEdit(LOAN, form)).toEqual({ error: null, body: {} })
    expect(loanEdit(LOAN, { ...form, name: 'Carro', term: '24' })).toEqual({
      error: null,
      body: { name: 'Carro', term: 24 },
    })
  })

  it("editing sets, changes or clears the bank's installment from the start", () => {
    expect(loanEdit(LOAN, { ...formOf(LOAN), installment: '9000' })).toEqual({
      error: null,
      body: { installment_cents: 900_000 },
    })
    const fixed: Loan = {
      ...LOAN,
      installment_cents: 900_000,
      installments: [
        { effective: '2026-01-15', installment_cents: 900_000 },
        { effective: '2026-06-01', installment_cents: 950_000 },
      ],
    }
    expect(formOf(fixed).installment).toBe('9000')
    expect(loanEdit(fixed, formOf(fixed))).toEqual({ error: null, body: {} })
    expect(loanEdit(fixed, { ...formOf(fixed), installment: ' ' })).toEqual({
      error: null,
      body: { installment_cents: null },
    })
    expect(loanEdit(fixed, { ...formOf(fixed), installment: '0' }).error).toBe(
      t('loans.form.error.installment'),
    )
  })
})
