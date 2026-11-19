import { describe, expect, it } from 'vitest'
import type { MonthOption } from './api'
import { adjacentYear, gridYears, moveFocus, monthCells } from './monthGrid'

// Labels as the API sends them (built by the backend's Spanish catalog).
const OPTIONS: MonthOption[] = [ // spanish-data: begin
  { month: '2026-02', label: 'Febrero 2026', partial: true },
  { month: '2026-01', label: 'Enero 2026', partial: false },
  { month: '2025-12', label: 'Diciembre 2025', partial: false },
  { month: '2023-05', label: 'Mayo 2023', partial: false },
] // spanish-data: end

describe('gridYears', () => {
  it('gives the years with data, oldest to newest without repeats', () => {
    expect(gridYears(OPTIONS)).toEqual([2023, 2025, 2026])
  })
  it('without months there are no years', () => {
    expect(gridYears([])).toEqual([])
  })
})

describe('adjacentYear', () => {
  const years = [2023, 2025, 2026]
  it('jumps to the years with data, even across gaps', () => {
    expect(adjacentYear(years, 2025, -1)).toBe(2023)
    expect(adjacentYear(years, 2025, 1)).toBe(2026)
  })
  it('at the ends there is no other year', () => {
    expect(adjacentYear(years, 2023, -1)).toBeNull()
    expect(adjacentYear(years, 2026, 1)).toBeNull()
  })
})

describe('monthCells', () => {
  it('gives the 12 months of the year; only those with data can be picked', () => {
    const cells = monthCells(OPTIONS, 2026, '2026-11')
    expect(cells).toHaveLength(12)
    expect(cells.map((c) => c.month)).toEqual([
      '2026-01',
      '2026-02',
      '2026-03',
      '2026-04',
      '2026-05',
      '2026-06',
      '2026-07',
      '2026-08',
      '2026-09',
      '2026-10',
      '2026-11',
      '2026-12',
    ])
    expect(cells.filter((c) => c.enabled).map((c) => c.month)).toEqual(['2026-01', '2026-02'])
  })
  it('carries the short and the full name', () => {
    const [january] = monthCells(OPTIONS, 2026, '2026-11')
    expect(january.short).toBe('Ene') // spanish-ui
    expect(january.label).toBe(OPTIONS[1].label)
    expect(monthCells(OPTIONS, 2026, '2026-11')[8].label).toBe('Septiembre 2026') // spanish-ui
  })
  it('marks the current month (today’s), with or without data', () => {
    const current = monthCells(OPTIONS, 2026, '2026-11').filter((c) => c.current)
    expect(current.map((c) => c.month)).toEqual(['2026-11'])
    expect(monthCells(OPTIONS, 2025, '2026-11').some((c) => c.current)).toBe(false)
  })
})

describe('moveFocus', () => {
  // Enabled: 0, 1, 4, 7 and 11.
  const enabled = [0, 1, 4, 7, 11]
  const cells = Array.from({ length: 12 }, (_, i) => ({ enabled: enabled.includes(i) }))

  it('moves forward and back skipping months without data', () => {
    expect(moveFocus(cells, 1, 1)).toBe(4)
    expect(moveFocus(cells, 4, -1)).toBe(1)
  })
  it('moves up and down a row (3 columns), skipping disabled ones in the same column', () => {
    expect(moveFocus(cells, 1, 3)).toBe(4)
    expect(moveFocus(cells, 4, 3)).toBe(7)
    expect(moveFocus(cells, 7, -3)).toBe(4)
    expect(moveFocus(cells, 0, 3)).toBe(0)
  })
  it('at the edge it stays where it is', () => {
    expect(moveFocus(cells, 11, 1)).toBe(11)
    expect(moveFocus(cells, 0, -1)).toBe(0)
  })
})
