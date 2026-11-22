import { describe, expect, it } from 'vitest'
import type { LinkedTx } from './api'
import type { ChosenPerson } from './ledger'
import {
  afterPaying,
  type ChosenCredit,
  type ChosenExpense,
  creditGroupBody,
  defaultName,
  parseCents,
  personOf,
  searchExpenses,
  splitPreview,
} from './creditGroup'

const tx = (fingerprint: string, merchant: string, cents: number, currency = 'DOP'): LinkedTx => ({
  fingerprint,
  day: '2026-03-01',
  merchant,
  account_label: 'Checking',
  amount_cents: cents,
  currency,
  description: `${merchant} CITY`,
})

const dinner: ChosenExpense = { kind: 'tx', key: 'd', tx: tx('d', 'Fake Grill', 200000) }
const taxi: ChosenExpense = {
  kind: 'cash',
  key: 'cash-1',
  description: 'Taxi',
  amount_cents: 90000,
  currency: 'DOP',
  day: '2026-03-02',
}
const ana: ChosenPerson = { key: 'c2', label: 'Ana', person: { contact_id: 2 } }
const luis: ChosenPerson = { key: 'nluis', label: 'Luis', person: { name: 'Luis' } }
const credit = (who: ChosenPerson, cents: number, fp = `p${cents}`): ChosenCredit => ({
  tx: tx(fp, 'TRANSFER', -cents),
  payer: who,
})

describe('personOf', () => {
  it('keeps an existing contact', () => {
    expect(personOf({ contact_id: 7, name: 'Ana', alias: null })).toEqual({
      key: 'c7',
      label: 'Ana',
      person: { contact_id: 7 },
    })
  })

  it('creates a new person with the bank text as alias', () => {
    expect(personOf({ contact_id: null, name: 'Rosa Made', alias: 'ROSA MADE' })?.person).toEqual({
      name: 'Rosa Made',
      alias: 'ROSA MADE',
    })
  })

  it('returns null without a guess', () => {
    expect(personOf(null)).toBeNull()
  })
})

describe('searchExpenses', () => {
  const options = [tx('a', 'Fake Grill', 200000), tx('b', 'Pretend Pharmacy', 85050)]

  it('matches merchant words without accents or case', () => {
    expect(searchExpenses(options, 'grill').map((o) => o.fingerprint)).toEqual(['a'])
  })

  it('matches the amount as typed', () => {
    expect(searchExpenses(options, '850').map((o) => o.fingerprint)).toEqual(['b'])
    expect(searchExpenses(options, '2,000').map((o) => o.fingerprint)).toEqual(['a'])
  })

  it('returns everything for an empty query', () => {
    expect(searchExpenses(options, '  ')).toHaveLength(2)
  })
})

describe('parseCents', () => {
  it.each([
    ['900', 90000],
    ['1,250.5', 125050],
    ['0', null],
    ['abc', null],
    ['1.234', null],
  ])('%s → %s', (text, cents) => {
    expect(parseCents(text)).toBe(cents)
  })
})

describe('defaultName', () => {
  it('uses the first expense', () => {
    expect(defaultName([dinner, taxi])).toBe('Fake Grill')
    expect(defaultName([taxi])).toBe('Taxi')
    expect(defaultName([])).toBe('')
  })
})

describe('splitPreview', () => {
  it('proposes "their share is what they paid" when equal parts do not settle it', () => {
    const preview = splitPreview([dinner], [credit(ana, 85000)])
    expect(preview).toMatchObject({
      currency: 'DOP',
      totalCents: 200000,
      paidCents: 85000,
      people: 2,
      equalCents: 100000,
      paidAllowed: true,
      equalSettles: false,
      mineCents: 115000,
      defaultSplit: 'paid',
    })
  })

  it('proposes equal parts when they already settle it', () => {
    const preview = splitPreview([dinner, taxi], [credit(ana, 96667), credit(luis, 96666)])
    expect(preview.equalSettles).toBe(true)
    expect(preview.defaultSplit).toBe('equal')
  })

  it('counts a person once when they sent two transfers', () => {
    expect(splitPreview([dinner], [credit(ana, 50000, 'x'), credit(ana, 50000, 'y')]).people).toBe(2)
  })

  it('does not allow "what they paid" over the expenses or across currencies', () => {
    expect(splitPreview([taxi], [credit(ana, 100000)]).paidAllowed).toBe(false)
    const usd: ChosenExpense = { kind: 'tx', key: 'u', tx: tx('u', 'Shop', 3000, 'USD') }
    const preview = splitPreview([usd], [credit(ana, 1000)])
    expect(preview.currency).toBeNull()
    expect(preview.defaultSplit).toBe('equal')
  })
})

describe('creditGroupBody', () => {
  it('builds the request with bank and cash expenses', () => {
    expect(creditGroupBody('  Trip ', 'paid', [dinner, taxi], [credit(ana, 85000, 'p1')])).toEqual({
      name: 'Trip',
      split: 'paid',
      payments: [{ fingerprint: 'p1', person: { contact_id: 2 } }],
      expenses: [
        { fingerprint: 'd' },
        { amount_cents: 90000, currency: 'DOP', day: '2026-03-02', description: 'Taxi' },
      ],
    })
  })
})

describe('afterPaying', () => {
  it('paying what the user owed settles it', () => {
    expect(afterPaying(-220000, 220000)).toEqual({ kind: 'settled', cents: 0 })
  })

  it('paying less leaves the rest owed by the user', () => {
    expect(afterPaying(-300000, 220000)).toEqual({ kind: 'owe', cents: 80000 })
  })

  it('paying someone who owed nothing makes them owe it back', () => {
    expect(afterPaying(0, 220000)).toEqual({ kind: 'owes', cents: 220000 })
  })
})
