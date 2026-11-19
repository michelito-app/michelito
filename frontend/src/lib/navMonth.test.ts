import { describe, expect, it } from 'vitest'
import { navHref } from './navMonth'

describe('navHref', () => {
  it('without a chosen month, the link goes as is', () => {
    expect(navHref('/', null)).toBe('/')
    expect(navHref('/transactions', null)).toBe('/transactions')
  })
  it('with another month, Summary and Transactions carry it', () => {
    expect(navHref('/', '2025-12')).toBe('/?month=2025-12')
    expect(navHref('/transactions', '2025-12')).toBe('/transactions?month=2025-12')
  })
  it('the other screens carry no month', () => {
    expect(navHref('/pending', '2025-12')).toBe('/pending')
    expect(navHref('/accounts', '2025-12')).toBe('/accounts')
  })
})
