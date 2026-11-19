import { describe, expect, it } from 'vitest'
import type { MonthOption } from './api'
import { adjacentYear, gridYears, moveFocus, monthCells } from './monthGrid'

const OPTIONS: MonthOption[] = [
  { month: '2026-02', label: 'Febrero 2026', partial: true },
  { month: '2026-01', label: 'Enero 2026', partial: false },
  { month: '2025-12', label: 'Diciembre 2025', partial: false },
  { month: '2023-05', label: 'Mayo 2023', partial: false },
]

describe('gridYears', () => {
  it('da los años con datos, del más viejo al más nuevo y sin repetir', () => {
    expect(gridYears(OPTIONS)).toEqual([2023, 2025, 2026])
  })
  it('sin meses no hay años', () => {
    expect(gridYears([])).toEqual([])
  })
})

describe('adjacentYear', () => {
  const years = [2023, 2025, 2026]
  it('salta a los años con datos, aunque haya huecos', () => {
    expect(adjacentYear(years, 2025, -1)).toBe(2023)
    expect(adjacentYear(years, 2025, 1)).toBe(2026)
  })
  it('en los extremos no hay otro año', () => {
    expect(adjacentYear(years, 2023, -1)).toBeNull()
    expect(adjacentYear(years, 2026, 1)).toBeNull()
  })
})

describe('monthCells', () => {
  it('da los 12 meses del año; solo los que tienen datos se pueden elegir', () => {
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
  it('lleva el nombre corto y el completo', () => {
    const [january] = monthCells(OPTIONS, 2026, '2026-11')
    expect(january.short).toBe('Ene')
    expect(january.label).toBe('Enero 2026')
    expect(monthCells(OPTIONS, 2026, '2026-11')[8].label).toBe('Septiembre 2026')
  })
  it('marca el mes en curso (el de hoy), tenga datos o no', () => {
    const current = monthCells(OPTIONS, 2026, '2026-11').filter((c) => c.current)
    expect(current.map((c) => c.month)).toEqual(['2026-11'])
    expect(monthCells(OPTIONS, 2025, '2026-11').some((c) => c.current)).toBe(false)
  })
})

describe('moveFocus', () => {
  // Habilitados: 0, 1, 4, 7 y 11.
  const enabled = [0, 1, 4, 7, 11]
  const cells = Array.from({ length: 12 }, (_, i) => ({ enabled: enabled.includes(i) }))

  it('avanza y retrocede saltando los meses sin datos', () => {
    expect(moveFocus(cells, 1, 1)).toBe(4)
    expect(moveFocus(cells, 4, -1)).toBe(1)
  })
  it('sube y baja de fila (3 columnas), saltando los deshabilitados en la misma columna', () => {
    expect(moveFocus(cells, 1, 3)).toBe(4)
    expect(moveFocus(cells, 4, 3)).toBe(7)
    expect(moveFocus(cells, 7, -3)).toBe(4)
    expect(moveFocus(cells, 0, 3)).toBe(0)
  })
  it('en el borde se queda donde está', () => {
    expect(moveFocus(cells, 11, 1)).toBe(11)
    expect(moveFocus(cells, 0, -1)).toBe(0)
  })
})
