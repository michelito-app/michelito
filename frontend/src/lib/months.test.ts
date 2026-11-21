import { describe, expect, it } from 'vitest'
import type { MonthOption } from './api'
import { lastDay, localToday, longDay, monthName, neighbors, resolveMonth, returnTarget, shortDay } from './months'

// Labels as the API sends them (built by the backend's Spanish catalog).
const OPTIONS: MonthOption[] = [ // spanish-data: begin
  { month: '2026-10', label: 'Octubre 2026', partial: true },
  { month: '2026-09', label: 'Septiembre 2026', partial: false },
  { month: '2026-08', label: 'Agosto 2026', partial: false },
] // spanish-data: end

describe('monthName', () => {
  it('gives the month name in lowercase', () => {
    expect(monthName('2026-09')).toBe('septiembre') // spanish-ui
    expect(monthName('2026-01')).toBe('enero') // spanish-ui
  })
})

describe('lastDay', () => {
  it('counts the days of the month, with leap years', () => {
    expect(lastDay('2026-09')).toBe(30)
    expect(lastDay('2028-02')).toBe(29)
    expect(lastDay('2026-12')).toBe(31)
  })
})

describe('shortDay / longDay', () => {
  it('abbreviate the month for the coverage chips', () => {
    expect(shortDay('2026-10-13')).toBe('13 oct') // spanish-ui
    expect(shortDay('2026-01-02')).toBe('2 ene') // spanish-ui
  })
  it('write the full month in phrases', () => {
    expect(longDay('2026-10-13')).toBe('13 de octubre') // spanish-ui
  })
})

describe('resolveMonth', () => {
  it('uses the requested month if it exists', () => {
    expect(resolveMonth(OPTIONS, '2026-08')).toBe('2026-08')
  })
  it('without a month (or an unknown one) picks the newest one, in progress', () => {
    expect(resolveMonth(OPTIONS, null)).toBe('2026-10')
    expect(resolveMonth(OPTIONS, '2020-01')).toBe('2026-10')
  })
  it('without months there is no month', () => {
    expect(resolveMonth([], '2026-09')).toBeNull()
  })
})

describe('neighbors', () => {
  it('the previous one is older and the next one newer (the list goes new to old)', () => {
    expect(neighbors(OPTIONS, '2026-09')).toEqual({ older: '2026-08', newer: '2026-10' })
  })
  it('at the ends there is no neighbor', () => {
    expect(neighbors(OPTIONS, '2026-10')).toEqual({ older: '2026-09', newer: null })
    expect(neighbors(OPTIONS, '2026-08')).toEqual({ older: null, newer: '2026-09' })
  })
})

describe('returnTarget', () => {
  it('offers going back to the default month when another one is viewed', () => {
    expect(returnTarget(OPTIONS, '2026-08')?.month).toBe('2026-10')
  })
  it('offers nothing when already on the default month', () => {
    expect(returnTarget(OPTIONS, '2026-10')).toBeNull()
    expect(returnTarget([], '2026-09')).toBeNull()
  })
})

describe('localToday', () => {
  it('local date with zero padding', () => {
    expect(localToday(new Date(2026, 1, 5, 23, 30))).toBe('2026-02-05')
  })
})
