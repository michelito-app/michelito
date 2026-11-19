import { describe, expect, it } from 'vitest'
import type { Candidate } from './api'
import { matches, partition, shownCandidates } from './picker'

function option(fingerprint: string, overrides: Partial<Candidate> = {}): Candidate {
  return {
    fingerprint,
    day: '2026-02-04',
    merchant: 'TOKE DE PERSONA',
    description: 'TOKE DE PERSONA FICTICIA',
    account_label: 'Corriente 777', // spanish-data
    amount_cents: -100_000,
    currency: 'DOP',
    primary: true,
    ...overrides,
  }
}

const ids = (items: Candidate[]) => items.map((c) => c.fingerprint)

describe('partition', () => {
  it('shows the first five primary ones and leaves the rest behind "See more"', () => {
    const items = [
      option('a'),
      option('b', { primary: false }),
      ...['c', 'd', 'e', 'f', 'g'].map((fp) => option(fp)),
    ]
    const { visible, more } = partition(items)
    expect(ids(visible)).toEqual(['a', 'c', 'd', 'e', 'f'])
    expect(ids(more)).toEqual(['b', 'g'])
  })

  it('without primary ones, everything goes behind "See more"', () => {
    const { visible, more } = partition([option('a', { primary: false })])
    expect(visible).toEqual([])
    expect(ids(more)).toEqual(['a'])
  })
})

describe('matches', () => {
  const big = option('big', { amount_cents: -100_050 })

  it('an amount matches if any of its amounts starts with those digits', () => {
    expect(matches(big, '1000')).toBe(true)
    expect(matches(big, '1,000')).toBe(true)
    expect(matches(big, '1000.50')).toBe(true)
    expect(matches(big, '1000.5')).toBe(true)
    expect(matches(big, 'RD$ 1,000')).toBe(true)
    expect(matches(big, '1000.6')).toBe(false)
    expect(matches(big, '200')).toBe(false)
  })

  it('also looks at the converted amount', () => {
    const usd = option('usd', { amount_cents: -6_000, currency: 'USD', converted_cents: 382_200 })
    expect(matches(usd, '60')).toBe(true)
    expect(matches(usd, '3822')).toBe(true)
  })

  it('text searches merchant, description and account, ignoring case and accents', () => {
    expect(matches(big, 'toke')).toBe(true)
    expect(matches(big, 'ficticia')).toBe(true)
    expect(matches(big, 'corriente')).toBe(true) // spanish-data
    expect(matches(option('x', { merchant: 'CAFÉ' }), 'cafe')).toBe(true)
    expect(matches(big, 'pharmacy')).toBe(false)
  })
})

describe('shownCandidates', () => {
  it('the search looks at the whole list, not only what is visible', () => {
    const items = [
      ...['a', 'b', 'c', 'd', 'e'].map((fp) => option(fp)),
      option('hidden', { primary: false, merchant: 'DEPOSITO RARE', description: 'DEP' }),
    ]
    expect(ids(shownCandidates(items, '').visible)).not.toContain('hidden')
    const found = shownCandidates(items, 'rare')
    expect(ids(found.visible)).toEqual(['hidden'])
    expect(found.more).toEqual([])
  })
})
