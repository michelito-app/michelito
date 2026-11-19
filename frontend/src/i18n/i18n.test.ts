import { describe, expect, it } from 'vitest'
import { AREAS, es } from './es'
import { message, pieces, t, template } from './index'

describe('t', () => {
  it('returns the Spanish message for a key', () => {
    expect(t('common.cancel')).toBe('Cancelar') // spanish-ui
  })

  it('picks the plural form by count and fills the placeholders', () => {
    expect(t('common.transactions', { count: 1 })).toBe('1 transacción') // spanish-ui
    expect(t('common.transactions', { count: 3 })).toBe('3 transacciones') // spanish-ui
    expect(t('common.transactions', { count: 0 })).toBe('0 transacciones') // spanish-ui
    // CLDR puts a million in "many" for Spanish; without that form it falls back to "other".
    expect(t('common.transactions', { count: 1_000_000 })).toBe('1000000 transacciones') // spanish-ui
  })

  it('uses the zero form only for exactly 0, and leaves unknown placeholders as written', () => {
    const plural = { zero: 'none', one: '{count} thing', other: '{count} things' }
    expect(template(plural, { count: 0 })).toBe('none')
    expect(template(plural, { count: 2 })).toBe('{count} things')
    expect(pieces('a {x} b')).toEqual([
      { text: 'a ', name: null },
      { text: '{x}', name: 'x' },
      { text: ' b', name: null },
    ])
    expect(message('common.save')).toBe('Guardar') // spanish-ui
  })
})

describe('the es catalog', () => {
  it('prefixes every key with its area and repeats none', () => {
    const seen = new Set<string>()
    for (const [area, messages] of Object.entries(AREAS)) {
      for (const key of Object.keys(messages)) {
        expect(key.startsWith(`${area}.`), key).toBe(true)
        expect(seen.has(key), key).toBe(false)
        seen.add(key)
      }
    }
    expect(Object.keys(es).length).toBe(seen.size)
  })

  it('has no empty message', () => {
    for (const [key, value] of Object.entries(es)) {
      const forms = typeof value === 'string' ? [value] : Object.values(value)
      for (const form of forms) expect(form.trim(), key).not.toBe('')
    }
  })
})

// Type checks only (never called): a key must exist and a message's params are required.
export function typeChecks(): string[] {
  return [
    // @ts-expect-error unknown key
    t('common.missing'),
    // @ts-expect-error a plural message needs its count
    t('common.transactions'),
    // @ts-expect-error a message without placeholders takes no params
    t('common.cancel', { x: 1 }),
  ]
}
