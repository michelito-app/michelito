import { describe, expect, it } from 'vitest'
import { formatDop, formatPesos, formatSignedDop, formatUsd } from './money'

describe('formatPesos', () => {
  it('muestra pesos sin el prefijo RD$ (la columna ya lo dice)', () => {
    expect(formatPesos(3420000)).toBe('34,200')
    expect(formatPesos(-50000)).toBe('−500')
  })
})

describe('formatSignedDop', () => {
  it('antepone el signo al prefijo RD$', () => {
    expect(formatSignedDop(1150000)).toBe('+RD$ 11,500')
    expect(formatSignedDop(-255000)).toBe('−RD$ 2,550')
    expect(formatSignedDop(0)).toBe('RD$ 0')
  })
})

describe('formatDop', () => {
  it('muestra pesos sin decimales y con separador de miles', () => {
    expect(formatDop(14832000)).toBe('RD$ 148,320')
  })
  it('pone el signo menos (U+2212) delante de RD$', () => {
    expect(formatDop(-120000)).toBe('−RD$ 1,200')
  })
})

describe('formatUsd', () => {
  it('muestra dólares con dos decimales', () => {
    expect(formatUsd(1199)).toBe('US$ 11.99')
  })
})
