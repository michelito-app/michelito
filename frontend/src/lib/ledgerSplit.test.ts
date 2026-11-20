import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import {
  allocationCents,
  allocationDraft,
  coveredText,
  draftAmounts,
  draftOf,
  draftShortfall,
  draftValid,
  equalDraft,
  partsShares,
  paymentLine,
  resplitText,
  setParts,
  splitFields,
  splitLineText,
  splitSummary,
  switchMode,
  togglePerson,
} from './ledger'

const ME = 1
const JAVIER = 2
const GORDO = 3
const ORDER = [ME, JAVIER, GORDO]

describe('partsShares (the server cent rule)', () => {
  it('divides by parts; the leftover goes to the payer', () => {
    expect(partsShares(489_600, ORDER, { [ME]: 1, [JAVIER]: 2, [GORDO]: 3 }, ME)).toEqual([
      { contact_id: ME, cents: 81_600 },
      { contact_id: JAVIER, cents: 163_200 },
      { contact_id: GORDO, cents: 244_800 },
    ])
    expect(partsShares(10_000, [JAVIER, GORDO], { [JAVIER]: 2, [GORDO]: 1 }, GORDO)).toEqual([
      { contact_id: JAVIER, cents: 6_666 },
      { contact_id: GORDO, cents: 3_334 },
    ])
  })

  it('without the payer, the first takes the cents; a missing count is 1 part', () => {
    expect(partsShares(1_000, [JAVIER, GORDO], { [GORDO]: 2 }, ME)).toEqual([
      { contact_id: JAVIER, cents: 334 },
      { contact_id: GORDO, cents: 666 },
    ])
  })
})

describe('switching to exact amounts starts from the current split', () => {
  it('prefills the equal amounts, so it already adds up', () => {
    const exact = switchMode(equalDraft(ORDER), 'exact', 100_000, ME)
    expect(exact.shares).toEqual({ [ME]: '333.34', [JAVIER]: '333.33', [GORDO]: '333.33' })
    expect(draftShortfall(exact, 100_000)).toBe(0)
    expect(draftValid(exact, 100_000)).toBe(true)
  })

  it('prefills the parts amounts', () => {
    const parts = setParts(switchMode(equalDraft(ORDER), 'parts', 4_000, ME), JAVIER, 2)
    const exact = switchMode(parts, 'exact', 4_000, ME)
    expect(exact.shares).toEqual({ [ME]: '10.00', [JAVIER]: '20.00', [GORDO]: '10.00' })
  })

  it('a newly checked person starts at 0 and the shortfall updates; unchecking drops them', () => {
    const exact = switchMode(equalDraft([ME, JAVIER]), 'exact', 1_000, ME)
    const without = togglePerson(exact, JAVIER, ORDER)
    expect(without.people).toEqual([ME])
    expect(draftShortfall(without, 1_000)).toBe(500)
    const back = togglePerson(without, GORDO, ORDER)
    expect(back.people).toEqual([ME, GORDO])
    expect(back.shares[GORDO]).toBe('0.00')
    expect(draftShortfall(back, 1_000)).toBe(500)
  })

  it('keeps the parts when going back to parts, and steps never go under 1', () => {
    const parts = setParts(switchMode(equalDraft(ORDER), 'parts', 900, ME), GORDO, 3)
    expect(setParts(parts, ME, 0).parts?.[ME]).toBe(1)
    const again = switchMode(switchMode(parts, 'equal', 900, ME), 'parts', 900, ME)
    expect(again.parts).toEqual({ [ME]: 1, [JAVIER]: 1, [GORDO]: 3 })
    expect(togglePerson(again, GORDO, ORDER).people).toEqual([ME, JAVIER])
    expect(draftAmounts(again, 500, ME)).toEqual({ [ME]: 100, [JAVIER]: 100, [GORDO]: 300 })
  })
})

describe('a split by parts in requests and texts', () => {
  const entry = {
    split: 'parts' as const,
    splits: [
      { contact_id: ME, name: 'me', is_me: true, cents: 81_600, parts: 1 },
      { contact_id: JAVIER, name: 'Javier', is_me: false, cents: 163_200, parts: 2 },
    ],
  }

  it('round-trips: editing keeps the mode and the parts', () => {
    const draft = draftOf(entry)
    expect(draft).toMatchObject({ mode: 'parts', people: [ME, JAVIER], parts: { [ME]: 1, [JAVIER]: 2 } })
    expect(splitFields(draft)).toEqual({
      split: 'parts',
      parts: [
        { contact_id: ME, parts: 1 },
        { contact_id: JAVIER, parts: 2 },
      ],
    })
    expect(splitSummary(draft, 244_800, 'DOP', [])).toBe(t('shared.add.splitParts', { count: 3 }))
  })

  it('shows "2 parts · RD$ 1,632" in the detail', () => {
    expect(splitLineText(entry.splits[1], 'DOP')).toBe(
      t('shared.detail.partsLine', { count: 2, amount: 'RD$ 1,632' }),
    )
    expect(splitLineText({ cents: 81_600, parts: null }, 'DOP')).toBe('RD$ 816')
  })
})

describe('a payment on behalf of others', () => {
  const payment = {
    from_contact: JAVIER,
    from_name: 'Javier',
    from_me: false,
    to_name: 'me',
    to_me: true,
    amount_cents: 163_200,
    currency: 'DOP',
    allocations: [
      { contact_id: JAVIER, name: 'Javier', is_me: false, cents: 81_600 },
      { contact_id: GORDO, name: 'El Gordo', is_me: false, cents: 81_600 },
    ],
  }

  it('reads "Javier → You · RD$ 1,632 (covers El Gordo)"', () => {
    const line = t('shared.payment.line', { from: 'Javier', to: t('shared.you'), amount: 'RD$ 1,632' })
    expect(paymentLine(payment)).toBe(`${line} ${t('shared.payment.covers', { names: 'El Gordo' })}`)
    const others = { ...payment, allocations: payment.allocations.slice(1) }
    expect(coveredText(others)).toBe(t('shared.payment.covers', { names: 'El Gordo' }))
    expect(paymentLine({ ...payment, allocations: payment.allocations.slice(0, 1) })).toBe(line)
  })

  it('starts each covered person at their balance and checks the typed amounts', () => {
    const members = [
      { id: JAVIER, balance: [{ currency: 'DOP', cents: 81_600 }] },
      { id: GORDO, balance: [{ currency: 'DOP', cents: 81_600 }, { currency: 'USD', cents: 500 }] },
    ]
    expect(allocationDraft(members, [GORDO], 'DOP')).toEqual({ [GORDO]: '816.00' })
    expect(allocationDraft(members, [GORDO], 'USD')).toEqual({ [GORDO]: '5.00' })
    expect(allocationCents([JAVIER, GORDO], { [JAVIER]: '816', [GORDO]: '' })).toEqual({
      [JAVIER]: 81_600,
      [GORDO]: 0,
    })
    expect(allocationCents([JAVIER], { [JAVIER]: 'abc' })).toBeNull()
  })
})

describe('removing someone: each expense as it would be', () => {
  it('reads "You RD$ 450 · Carola RD$ 450"', () => {
    const lines = [
      { name: 'me', is_me: true, cents: 45_000 },
      { name: 'Carola', is_me: false, cents: 45_000 },
    ]
    expect(resplitText(lines, 'DOP')).toBe(`${t('shared.you')} RD$ 450 · Carola RD$ 450`)
  })
})
