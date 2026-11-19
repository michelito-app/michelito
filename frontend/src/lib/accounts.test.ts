import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { Account, StatementLine } from './api'
import {
  amountText,
  cutLine,
  cutText,
  dueNote,
  footnote,
  groupAccounts,
  isCreditCard,
  missingMonth,
  movementLabels,
  periodText,
  resolveAccount,
  shortAccountLabel,
  splitLabel,
  statusText,
} from './accounts'

function line(patch: Partial<StatementLine> = {}): StatementLine {
  return {
    period_start: '2026-09-21',
    period_end: '2026-10-20',
    currency: 'DOP',
    charges_cents: 7231000,
    payments_cents: 6600000,
    balance_cents: 7526000,
    due_date: '2026-11-14',
    minimum_payment_cents: 376000,
    paid_full: null,
    left_over_cents: null,
    paid_late: false,
    next_interest_cents: 0,
    printout: false,
    ...patch,
  }
}

function account(patch: Partial<Account> = {}): Account {
  const latest = patch.latest ?? [line()]
  return {
    key: 'popular:credit_card',
    kind: 'credit_card',
    label: 'VISA ···1234',
    cut_day: 20,
    currencies: ['DOP'],
    latest,
    missing_statement: false,
    statements: latest,
    to_pay: null,
    ...patch,
  }
}

const SAVINGS = account({
  key: 'bhd:savings:1',
  kind: 'savings',
  label: 'Savings 1',
})
const VISA = account({ key: 'visa', label: 'Visa' })
const MC = account({ key: 'mc', label: 'Mastercard' })

describe('groupAccounts', () => {
  it('separates credit cards from the rest, keeping the order', () => {
    expect(groupAccounts([VISA, SAVINGS, MC])).toEqual({
      cards: [VISA, MC],
      others: [SAVINGS],
    })
  })
  it('leaves a group empty when there are no accounts of that kind', () => {
    expect(groupAccounts([VISA])).toEqual({ cards: [VISA], others: [] })
  })
})

describe('resolveAccount', () => {
  it('uses the requested account when it exists', () => {
    expect(resolveAccount([SAVINGS, VISA, MC], 'mc')).toBe(MC)
    expect(resolveAccount([VISA, SAVINGS], 'bhd:savings:1')).toBe(SAVINGS)
  })
  it('without an account (or with an unknown one) picks the first credit card', () => {
    expect(resolveAccount([SAVINGS, VISA, MC], null)).toBe(VISA)
    expect(resolveAccount([SAVINGS, VISA, MC], 'missing')).toBe(VISA)
  })
  it('without cards picks the first account; without accounts, none', () => {
    expect(resolveAccount([SAVINGS], null)).toBe(SAVINGS)
    expect(resolveAccount([], 'visa')).toBeNull()
  })
})

describe('movementLabels', () => {
  it('uses purchases and payments only on credit cards', () => {
    expect(movementLabels(VISA)).toEqual({
      charges: t('accounts.labels.purchases'),
      payments: t('accounts.labels.payments'),
    })
    expect(movementLabels(SAVINGS)).toEqual({
      charges: t('accounts.labels.debits'),
      payments: t('accounts.labels.credits'),
    })
  })
})

describe('splitLabel', () => {
  it('splits the name from the last digits', () => {
    expect(splitLabel('Visa ···1234')).toEqual({
      name: 'Visa',
      tail: '···1234',
    })
  })
  it('leaves a label without digits untouched', () => {
    expect(splitLabel('Savings BHD')).toEqual({ name: 'Savings BHD', tail: '' })
  })
})

describe('isCreditCard', () => {
  it('tells credit cards from savings and debit accounts', () => {
    expect(isCreditCard(VISA)).toBe(true)
    expect(isCreditCard(SAVINGS)).toBe(false)
  })
})

describe('amountText', () => {
  it("formats in the line's currency", () => {
    expect(amountText(7526000, 'DOP')).toBe('RD$ 75,260')
    expect(amountText(41230, 'USD')).toBe('US$ 412.30')
  })
  it('shows a dash when the statement has no amount', () => {
    expect(amountText(null, 'DOP')).toBe('—')
  })
})

describe('cutLine', () => {
  it('says the cut day and the currencies', () => {
    expect(cutLine(account())).toBe(t('accounts.cutLine', { day: 20, currencies: 'RD$' }))
    expect(cutLine(account({ cut_day: 5, currencies: ['DOP', 'USD'] }))).toBe(
      'Corta el día 5 · RD$ y US$', // spanish-ui
    )
  })
  it('without statements does not make up a cut day', () => {
    expect(cutLine(account({ cut_day: null, currencies: [], latest: [] }))).toBe(
      t('accounts.noStatementsYet'),
    )
  })
})

describe('periodText', () => {
  it('writes the statement period with short days', () => {
    expect(periodText(line())).toBe('21 sep – 20 oct')
  })
  it('without a known start (first stored statement) says until when', () => {
    expect(periodText(line({ period_start: null }))).toBe(t('accounts.period.until', { end: '20 oct' }))
  })
  it('a printout says so and which days it covers', () => {
    const printout = line({ printout: true, period_start: '2026-10-12', period_end: '2026-10-20' })
    expect(periodText(printout)).toBe(
      t('accounts.period.printout', { start: '12 oct', end: '20 oct' }),
    )
  })
})

describe('cutText', () => {
  it('a statement shows its cut day', () => {
    expect(cutText(line())).toBe('20 oct')
  })
  it('a portal printout is not a cut', () => {
    expect(cutText(line({ printout: true }))).toBe('—')
  })
})

describe('missingMonth', () => {
  it('is the month after the last cut, with its full name', () => {
    expect(missingMonth(account({ missing_statement: true }))).toBe('noviembre') // spanish-ui
  })
  it('wraps from December to January', () => {
    const december = account({
      missing_statement: true,
      latest: [line({ period_end: '2026-12-20' })],
    })
    expect(missingMonth(december)).toBe('enero') // spanish-ui
  })
  it('has no missing month when the account is up to date', () => {
    expect(missingMonth(account())).toBeNull()
  })
})

describe('statusText', () => {
  it('up to date: the last cut', () => {
    expect(statusText(account())).toEqual({
      text: t('accounts.status.upToDate', { day: '20 oct' }),
      missing: false,
    })
  })
  it('with a missing statement, says which one', () => {
    expect(statusText(account({ missing_statement: true }))).toEqual({
      text: 'Último estado del 20 oct · falta el estado de noviembre', // spanish-ui
      missing: true,
    })
  })
  it('without statements', () => {
    expect(statusText(account({ latest: [], statements: [] }))).toEqual({
      text: t('accounts.noStatementsYet'),
      missing: false,
    })
  })
})

describe('dueNote', () => {
  it('counts the days left', () => {
    expect(dueNote('2026-11-30', '2026-11-14')).toBe(t('accounts.due.inDays', { days: 16 }))
    expect(dueNote('2026-11-15', '2026-11-14')).toBe(t('accounts.due.tomorrow'))
    expect(dueNote('2026-11-14', '2026-11-14')).toBe(t('accounts.due.today'))
  })
  it('a past date only says which cut it belongs to', () => {
    expect(dueNote('2026-11-07', '2026-11-14', '2026-10-13')).toBe(
      t('accounts.due.ofStatement', { day: '13 oct' }),
    )
  })
})

describe('footnote', () => {
  it('explains the missing statement', () => {
    expect(footnote(account({ missing_statement: true }))).toBe(
      t('accounts.footnote.missing', { month: 'noviembre' }), // spanish-ui
    )
  })
  it('explains the two currencies', () => {
    expect(footnote(account({ currencies: ['DOP', 'USD'] }))).toBe(
      t('accounts.footnote.twoCurrencies'),
    )
  })
  it('by default, the difference from the calendar month', () => {
    expect(footnote(account())).toBe(
      t('accounts.footnote.default'),
    )
  })
})

describe('shortAccountLabel', () => {
  it('savings account: type and last 4 digits of the number', () => {
    const savings = t('accounts.bankType.savings')
    expect(shortAccountLabel('POPULAR Cuenta de ahorro 100200300')).toBe(`${savings} ···0300`) // spanish-data
    expect(shortAccountLabel('BHD Cuenta de ahorro 1234567')).toBe(`${savings} ···4567`) // spanish-data
  })

  it('checking account; the number may have dashes', () => {
    const checking = t('accounts.bankType.checking')
    expect(shortAccountLabel('POPULAR Cuenta corriente 400500600')).toBe(`${checking} ···0600`) // spanish-data
    expect(shortAccountLabel('FICTICIO Cuenta corriente 777-0')).toBe(`${checking} ···7770`) // spanish-data
  })

  it('cards stay as they are', () => {
    expect(shortAccountLabel('MC BLACK ···0000')).toBe('MC BLACK ···0000')
    expect(shortAccountLabel('VISA DEMO ···4242')).toBe('VISA DEMO ···4242')
  })

  it('anything unrecognised (no type or no number) stays the same', () => {
    expect(shortAccountLabel('Ahorro BHD')).toBe('Ahorro BHD') // spanish-data
    expect(shortAccountLabel('BANCO Préstamo 123456')).toBe('BANCO Préstamo 123456') // spanish-data
    expect(shortAccountLabel('ficticio:checking:1')).toBe('ficticio:checking:1')
  })
})
