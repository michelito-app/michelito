import { describe, expect, it } from 'vitest'
import type { MonthOption } from './api'
import { lastDay, localToday, longDay, monthName, neighbors, resolveMonth, returnTarget, shortDay } from './months'

const OPTIONS: MonthOption[] = [
  { month: '2026-10', label: 'Octubre 2026', partial: true },
  { month: '2026-09', label: 'Septiembre 2026', partial: false },
  { month: '2026-08', label: 'Agosto 2026', partial: false },
]

describe('monthName', () => {
  it('da el nombre del mes en minúsculas', () => {
    expect(monthName('2026-09')).toBe('septiembre')
    expect(monthName('2026-01')).toBe('enero')
  })
})

describe('lastDay', () => {
  it('cuenta los días del mes, con años bisiestos', () => {
    expect(lastDay('2026-09')).toBe(30)
    expect(lastDay('2028-02')).toBe(29)
    expect(lastDay('2026-12')).toBe(31)
  })
})

describe('shortDay / longDay', () => {
  it('abrevian el mes para los indicadores de cobertura', () => {
    expect(shortDay('2026-10-13')).toBe('13 oct')
    expect(shortDay('2026-01-02')).toBe('2 ene')
  })
  it('escriben el mes completo en frases', () => {
    expect(longDay('2026-10-13')).toBe('13 de octubre')
  })
})

describe('resolveMonth', () => {
  it('usa el mes pedido si existe', () => {
    expect(resolveMonth(OPTIONS, '2026-08')).toBe('2026-08')
  })
  it('sin mes (o uno desconocido) elige el más reciente completo', () => {
    expect(resolveMonth(OPTIONS, null)).toBe('2026-09')
    expect(resolveMonth(OPTIONS, '2020-01')).toBe('2026-09')
  })
  it('si todos son parciales elige el más reciente', () => {
    const partial = OPTIONS.map((o) => ({ ...o, partial: true }))
    expect(resolveMonth(partial, null)).toBe('2026-10')
  })
  it('sin meses no hay mes', () => {
    expect(resolveMonth([], '2026-09')).toBeNull()
  })
})

describe('neighbors', () => {
  it('el anterior es más viejo y el siguiente más nuevo (la lista va de nuevo a viejo)', () => {
    expect(neighbors(OPTIONS, '2026-09')).toEqual({ older: '2026-08', newer: '2026-10' })
  })
  it('en los extremos no hay vecino', () => {
    expect(neighbors(OPTIONS, '2026-10')).toEqual({ older: '2026-09', newer: null })
    expect(neighbors(OPTIONS, '2026-08')).toEqual({ older: null, newer: '2026-09' })
  })
})

describe('returnTarget', () => {
  it('ofrece volver al mes por defecto cuando se mira otro', () => {
    expect(returnTarget(OPTIONS, '2026-08')?.month).toBe('2026-09')
  })
  it('no ofrece nada si ya se está en el mes por defecto', () => {
    expect(returnTarget(OPTIONS, '2026-09')).toBeNull()
    expect(returnTarget([], '2026-09')).toBeNull()
  })
})

describe('localToday', () => {
  it('fecha local con ceros', () => {
    expect(localToday(new Date(2026, 1, 5, 23, 30))).toBe('2026-02-05')
  })
})
