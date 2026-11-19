import { describe, expect, it } from 'vitest'
import { formatDop, formatDopNumber, formatSignedDop, formatUsd } from './money'

describe('formatDopNumber', () => {
  it('shows RD$ amounts without the prefix (the column already says it)', () => {
    expect(formatDopNumber(3420000)).toBe('34,200')
    expect(formatDopNumber(-50000)).toBe('−500')
  })
})

describe('formatSignedDop', () => {
  it('puts the sign before the RD$ prefix', () => {
    expect(formatSignedDop(1150000)).toBe('+RD$ 11,500')
    expect(formatSignedDop(-255000)).toBe('−RD$ 2,550')
    expect(formatSignedDop(0)).toBe('RD$ 0')
  })
})

describe('formatDop', () => {
  it('shows RD$ without decimals and with a thousands separator', () => {
    expect(formatDop(14832000)).toBe('RD$ 148,320')
  })
  it('puts the minus sign (U+2212) before RD$', () => {
    expect(formatDop(-120000)).toBe('−RD$ 1,200')
  })
})

describe('formatUsd', () => {
  it('shows dollars with two decimals', () => {
    expect(formatUsd(1199)).toBe('US$ 11.99')
  })
})
