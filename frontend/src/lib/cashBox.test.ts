import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { CashBox, CashLine, Tx } from './api'
import {
  approxText,
  balanceAfter,
  balanceText,
  cashBoxNote,
  cashBoxText,
  deleteWarning,
  depositBody,
  draftDelta,
  draftOfLine,
  emptyDraft,
  entryBody,
  isNegative,
  lastDay,
  lineAmount,
  lineDetail,
  lineHref,
  showCashBox,
  wouldBeNegative,
} from './cashBox'
import {
  cashReviewCount,
  cashSource,
  countsBody,
  fold,
  frequencyText,
  knownConcept,
  matchConcepts,
  scheduleBody,
  upcomingText,
} from './cashBox'
import type { CashConcept } from './api'

function box(overrides: Partial<CashBox> = {}): CashBox {
  return {
    account_key: 'manual:cash-box',
    label: 'Cash box',
    exists: true,
    balances: [
      { currency: 'DOP', amount_cents: 500_000 },
      { currency: 'USD', amount_cents: 20_000 },
    ],
    total_dop_cents: 1_762_000,
    unconverted: [],
    negative: [],
    uncounted: [],
    lines: [],
    balances_today: [],
    schedules: [],
    occurrences: [],
    upcoming: null,
    activated_on: null,
    reconcile_due: false,
    last_reconciled: null,
    ...overrides,
  }
}

function line(overrides: Partial<CashLine> = {}): CashLine {
  return {
    kind: 'expense',
    day: '2026-01-20',
    fingerprint: 'cash-3',
    entry_id: 3,
    currency: 'DOP',
    amount_cents: -150_000,
    dop_cents: -150_000,
    source_amount_cents: 150_000,
    source_currency: 'DOP',
    merchant: 'CAJA FUERTE',
    account_label: 'Cash box',
    category: 'Groceries',
    category_id: 1,
    note: 'Corner store',
    in_flow: true,
    group: null,
    concept: null,
    schedule_id: null,
    state: '',
    ...overrides,
  }
}

function tx(overrides: Partial<Tx> = {}): Tx {
  return {
    fingerprint: 'f1',
    currency: 'DOP',
    can_store: false,
    can_deposit: false,
    cash_box_role: '',
    cash_box_currency: null,
    cash_box_amount_cents: null,
    ...overrides,
  } as Tx
}

describe('cash box texts', () => {
  it('the Summary line only with stored withdrawals', () => {
    expect(cashBoxNote(0)).toBeNull()
    expect(cashBoxNote(500_000)).toBe(t('cashBox.note', { amount: 'RD$ 5,000' }))
  })

  it('balance per currency and ≈ RD$ with what has no rate apart', () => {
    expect(balanceText(box().balances)).toBe('RD$ 5,000 + US$ 200.00')
    expect(balanceText([])).toBe('RD$ 0')
    expect(approxText(box())).toBe(t('cashBox.approx.total', { amount: 'RD$ 17,620' }))
    const without = box({ unconverted: [{ currency: 'USD', amount_cents: 5_000 }] })
    expect(approxText(without)).toBe(
      `${t('cashBox.approx.total', { amount: 'RD$ 17,620' })} ${t('cashBox.approx.withoutRate', { amount: 'US$ 50.00' })}`,
    )
    expect(approxText(without)).toBe('≈ RD$ 17,620 + US$ 50.00 sin tasa') // spanish-ui
    expect(approxText(box({ balances: [{ currency: 'DOP', amount_cents: 1 }] }))).toBeNull()
  })

  it('warns about a negative balance without blocking', () => {
    expect(balanceAfter(box(), 'USD', -40_000)).toBe(-20_000)
    expect(balanceAfter(box(), 'USD', -10_000)).toBeNull()
    expect(balanceAfter(box(), 'EUR', -1)).toBe(-1)
    expect(wouldBeNegative('USD', -20_000)).toBe(
      t('cashBox.wouldBeNegative', { amount: '−US$ 200.00' }),
    )
    expect(isNegative({ currency: 'DOP', amount_cents: -850_000 })).toBe(
      t('cashBox.isNegative', { amount: '−RD$ 8,500' }),
    )
  })

  it('amount and detail of each line', () => {
    expect(lineAmount(line())).toBe('−RD$ 1,500')
    expect(lineAmount(line({ kind: 'stored', amount_cents: 2_000, currency: 'USD' }))).toBe(
      '+US$ 20.00',
    )
    const noRate = line({ kind: 'deposit', amount_cents: null, source_amount_cents: 600_000 })
    expect(lineAmount(noRate)).toBe(t('cashBox.lineAmount.withoutRate', { amount: 'RD$ 6,000' }))
    expect(lineDetail(line())).toBe('Groceries · Corner store')
    expect(lineHref(line({ fingerprint: 'cash-3' }))).toBe('/transactions?month=2026-01&tx=cash-3')
    const deposit = line({
      kind: 'deposit',
      currency: 'USD',
      amount_cents: -10_000,
      source_currency: 'DOP',
      source_amount_cents: 600_000,
      account_label: 'Savings ···999',
      note: '',
    })
    expect(lineDetail(deposit)).toBe(
      `Savings ···999 · ${t('cashBox.lineDetail.atBank', { amount: 'RD$ 6,000' })}`,
    )
  })
})

describe('forms', () => {
  it('builds the body of an entry or the error', () => {
    const draft = {
      ...emptyDraft('expense', '2026-01-20'),
      amount: '1,500.50',
      note: ' x ',
      concept: ' Corner store ',
    }
    expect(entryBody(draft, '2026-02-07')).toEqual({
      kind: 'expense',
      day: '2026-01-20',
      amount_cents: 150_050,
      currency: 'DOP',
      category_id: null,
      note: 'x',
      concept: 'Corner store',
    })
    expect(entryBody({ ...draft, concept: '  ' }, '2026-02-07')).toBe(t('cashBox.error.concept'))
    // An entry written before concepts can be edited without one.
    expect(entryBody({ ...draft, concept: '' }, '2026-02-07', true)).not.toBeTypeOf('string')
    expect(entryBody({ ...draft, repeat: true, frequency: 'weekly' }, '2026-02-07')).toMatchObject({
      repeat: { frequency: 'weekly' },
    })
    expect(
      entryBody({ ...draft, repeat: true, endMode: 'after', times: '0' }, '2026-02-07'),
    ).toBe(t('cashBox.error.times', { max: 1000 }))
    expect(entryBody({ ...draft, amount: '0' }, '2026-02-07')).toBe(t('cashBox.error.amount'))
    expect(entryBody({ ...draft, day: '' }, '2026-02-07')).toBe(t('cashBox.error.day'))
    const range = t('cashBox.error.dayRange', { first: '2000-01-01', last: '2026-03-10' })
    expect(entryBody({ ...draft, day: '2062-01-20' }, '2026-02-07')).toBe(range)
    expect(entryBody({ ...draft, day: '1999-12-31' }, '2026-02-07')).toBe(range)
    expect(lastDay('2026-12-15')).toBe('2027-01-15')
    const initial = {
      ...emptyDraft('initial', '2026-01-01'),
      amount: '200',
      currency: 'USD' as const,
    }
    expect(entryBody(initial, '2026-02-07')).toEqual({
      kind: 'initial',
      day: '2026-01-01',
      amount_cents: 20_000,
      currency: 'USD',
    })
  })

  it('the balance change of what is saved (editing does not count the previous)', () => {
    const body = {
      kind: 'expense' as const,
      day: '2026-01-20',
      amount_cents: 200_000,
      currency: 'DOP' as const,
    }
    expect(draftDelta(body)).toBe(-200_000)
    expect(draftDelta(body, line())).toBe(-50_000)
    expect(draftDelta({ ...body, kind: 'income' })).toBe(200_000)
    expect(draftOfLine(line())).toMatchObject({ amount: '1500.00', categoryId: 1, note: 'Corner store' })
  })

  it('a deposit in another currency carries the currency and, if given, the amount', () => {
    expect(depositBody(tx(), 'DOP', '50')).toEqual({})
    expect(depositBody(tx(), 'USD', '')).toEqual({ currency: 'USD' })
    expect(depositBody(tx(), 'USD', '98.50')).toEqual({ currency: 'USD', amount_cents: 9_850 })
    expect(depositBody(tx(), 'USD', 'x')).toBe(t('cashBox.error.amount'))
  })
})

describe('transaction detail', () => {
  it('says what happens and when it is shown', () => {
    expect(showCashBox(tx())).toBe(false)
    expect(showCashBox(tx({ can_store: true }))).toBe(true)
    expect(cashBoxText(tx({ can_store: true }))).toBe(t('cashBox.tx.canStore'))
    expect(cashBoxText(tx())).toBe(t('cashBox.tx.canDeposit'))
    expect(cashBoxText(tx({ cash_box_role: 'stored' }))).toBe(t('cashBox.tx.stored'))
    expect(cashBoxText(tx({ cash_box_role: 'deposit', cash_box_currency: 'DOP' }))).toBe(
      t('cashBox.tx.deposit'),
    )
    const usd = tx({
      cash_box_role: 'deposit',
      cash_box_currency: 'USD',
      cash_box_amount_cents: 10_000,
    })
    expect(cashBoxText(usd)).toBe(
      t('cashBox.tx.depositTaken', { taken: t('cashBox.tx.taken', { amount: 'US$ 100.00' }) }),
    )
    expect(cashBoxText({ ...usd, cash_box_amount_cents: null })).toBe(
      t('cashBox.tx.depositTaken', { taken: t('cashBox.tx.withoutRate') }),
    )
  })
})

describe('delete', () => {
  it('warns if it leaves a shared group', () => {
    expect(deleteWarning(null)).toBe(t('cashBox.delete.warning'))
    expect(deleteWarning('Ana')).toBe(
      t('cashBox.delete.warningInGroup', { base: t('cashBox.delete.warning'), group: 'Ana' }),
    )
  })
})

describe('the cash account (schema 23)', () => {
  const concepts: CashConcept[] = [
    {
      concept: 'Corner store',
      kind: 'expense',
      currency: 'DOP',
      category_id: 4,
      last_day: '2026-02-01',
    },
    { concept: 'Rent', kind: 'income', currency: 'USD', category_id: 9, last_day: '2026-01-01' },
  ]

  it('matches concepts without case or accents, of the same kind', () => {
    expect(fold('  Cáfe   DEL  día ')).toBe('cafe del dia') // spanish-ui
    expect(matchConcepts(concepts, 'expense', 'corner').map((c) => c.concept)).toEqual([
      'Corner store',
    ])
    expect(matchConcepts(concepts, 'expense', 'rent')).toEqual([])
    expect(knownConcept(concepts, 'income', ' rent ')?.currency).toBe('USD')
    expect(knownConcept(concepts, 'income', 'ren')).toBeNull()
  })

  it('describes frequencies and the next one due', () => {
    expect(frequencyText('weekly', '2026-11-27')).toContain('viernes') // spanish-ui
    expect(frequencyText('monthly', '2026-01-31')).toBe(t('cashBox.frequencyShort.monthlyLast'))
    expect(frequencyText('monthly', '2026-01-15')).toBe(
      t('cashBox.frequencyShort.monthly', { day: 15 }),
    )
    const text = upcomingText({
      schedule_id: 1,
      kind: 'payment',
      concept: 'Cleaning',
      day: '2026-11-27',
      amount_cents: 300_000,
      currency: 'DOP',
    })
    const day = 'vie' // spanish-ui
    expect(text).toBe(t('cashBox.upcoming', { concept: 'Cleaning', amount: 'RD$ 3,000', day }))
  })

  it('builds a schedule body', () => {
    const draft = {
      ...emptyDraft('income', '2026-11-01'),
      amount: '3000',
      concept: 'Rent',
      frequency: 'monthly' as const,
      endMode: 'on' as const,
      endDay: '2027-11-01',
    }
    expect(scheduleBody(draft)).toEqual({
      kind: 'collection',
      concept: 'Rent',
      amount_cents: 300_000,
      currency: 'DOP',
      category_id: null,
      frequency: 'monthly',
      start_day: '2026-11-01',
      end_day: '2027-11-01',
      max_count: null,
    })
    expect(scheduleBody({ ...draft, concept: '' })).toBe(t('cashBox.error.concept'))
  })

  it('builds the reconcile counts', () => {
    expect(countsBody({ DOP: '1,500', USD: '' })).toEqual([
      { currency: 'DOP', amount_cents: 150_000 },
    ])
    expect(countsBody({ DOP: '0' })).toEqual([{ currency: 'DOP', amount_cents: 0 }])
    expect(countsBody({})).toBe(t('cashBox.error.count'))
    expect(countsBody({ DOP: '-5' })).toBe(t('cashBox.error.count'))
  })

  it('counts what to review', () => {
    expect(cashReviewCount(undefined)).toBe(0)
    expect(cashReviewCount(box({ reconcile_due: true }))).toBe(1)
  })
})

describe('the cash schedules in «Upcoming»', () => {
  it('gives each active schedule with its next date, signed', () => {
    const base = {
      concept: 'Cleaning',
      amount_cents: 300_000,
      currency: 'DOP' as const,
      category: 'x',
      category_id: null,
      frequency: 'weekly' as const,
      start_day: '2026-11-06',
      end_day: null,
      max_count: null,
      finished: false,
    }
    const source = cashSource(
      [
        { ...base, id: 1, kind: 'payment', paused: false, next_due: '2026-11-27' },
        { ...base, id: 2, kind: 'collection', paused: false, next_due: '2026-11-25' },
        { ...base, id: 3, kind: 'payment', paused: true, next_due: null },
      ],
      '/accounts',
    )
    expect(source('2026-11-21')).toEqual([
      { key: 'cash|1', name: 'Cleaning', day: '2026-11-27', amount: '−RD$ 3,000', href: '/accounts' },
      { key: 'cash|2', name: 'Cleaning', day: '2026-11-25', amount: '+RD$ 3,000', href: '/accounts' },
    ])
  })
})
