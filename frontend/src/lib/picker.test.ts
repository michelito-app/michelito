import { describe, expect, it } from 'vitest'
import type { Candidate } from './api'
import { matches, partition, shownCandidates } from './picker'

function option(fingerprint: string, overrides: Partial<Candidate> = {}): Candidate {
  return {
    fingerprint,
    day: '2026-02-04',
    merchant: 'TOKE DE PERSONA',
    description: 'TOKE DE PERSONA FICTICIA',
    account_label: 'Corriente 777',
    amount_cents: -100_000,
    currency: 'DOP',
    primary: true,
    ...overrides,
  }
}

const ids = (items: Candidate[]) => items.map((c) => c.fingerprint)

describe('partition', () => {
  it('muestra las primeras cinco primarias y deja el resto tras «Ver más»', () => {
    const items = [
      option('a'),
      option('b', { primary: false }),
      ...['c', 'd', 'e', 'f', 'g'].map((fp) => option(fp)),
    ]
    const { visible, more } = partition(items)
    expect(ids(visible)).toEqual(['a', 'c', 'd', 'e', 'f'])
    expect(ids(more)).toEqual(['b', 'g'])
  })

  it('sin primarias, todo va tras «Ver más»', () => {
    const { visible, more } = partition([option('a', { primary: false })])
    expect(visible).toEqual([])
    expect(ids(more)).toEqual(['a'])
  })
})

describe('matches', () => {
  const big = option('big', { amount_cents: -100_050 })

  it('un monto coincide si alguno de sus montos empieza por esas cifras', () => {
    expect(matches(big, '1000')).toBe(true)
    expect(matches(big, '1,000')).toBe(true)
    expect(matches(big, '1000.50')).toBe(true)
    expect(matches(big, '1000.5')).toBe(true)
    expect(matches(big, 'RD$ 1,000')).toBe(true)
    expect(matches(big, '1000.6')).toBe(false)
    expect(matches(big, '200')).toBe(false)
  })

  it('también mira el monto convertido', () => {
    const usd = option('usd', { amount_cents: -6_000, currency: 'USD', converted_cents: 382_200 })
    expect(matches(usd, '60')).toBe(true)
    expect(matches(usd, '3822')).toBe(true)
  })

  it('el texto busca en comercio, descripción y cuenta, sin mayúsculas ni acentos', () => {
    expect(matches(big, 'toke')).toBe(true)
    expect(matches(big, 'ficticia')).toBe(true)
    expect(matches(big, 'corriente')).toBe(true)
    expect(matches(option('x', { merchant: 'CAFÉ' }), 'cafe')).toBe(true)
    expect(matches(big, 'farmacia')).toBe(false)
  })
})

describe('shownCandidates', () => {
  it('la búsqueda mira toda la lista, no solo lo visible', () => {
    const items = [
      ...['a', 'b', 'c', 'd', 'e'].map((fp) => option(fp)),
      option('hidden', { primary: false, merchant: 'DEPOSITO RARO', description: 'DEP' }),
    ]
    expect(ids(shownCandidates(items, '').visible)).not.toContain('hidden')
    const found = shownCandidates(items, 'raro')
    expect(ids(found.visible)).toEqual(['hidden'])
    expect(found.more).toEqual([])
  })
})
