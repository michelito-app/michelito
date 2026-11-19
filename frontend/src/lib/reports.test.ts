import { describe, expect, it } from 'vitest'
import type { CompareCell, MonthOption } from './api'
import { cellClass, cellHref, cellTitle, orderedRange, parseRange, rangeQuery } from './reports'

const CELL: CompareCell = { amount_cents: 900_000, habitual_cents: 400_000, flag: 'up', level: 3 }
const MONTHS: MonthOption[] = [
  { month: '2026-02', label: 'Febrero 2026', partial: true },
  { month: '2026-01', label: 'Enero 2026', partial: false },
]

describe('celdas', () => {
  it('subida en terracota por intensidad; bajada con borde verde', () => {
    expect(cellClass('Supermercado', CELL)).toBe('bg-[#E4B8A3]')
    expect(cellClass('Supermercado', { ...CELL, level: 1 })).toBe('bg-[#F7E9E2]')
    expect(cellClass('gastos', { ...CELL, flag: 'down', level: 0 })).toContain('--color-down')
    expect(cellClass('Supermercado', { ...CELL, flag: null })).toBe('')
  })

  it('ingresos, terceros y lo que quedó no se colorean', () => {
    expect(cellClass('ingresos', CELL)).toBe('')
    expect(cellClass('terceros', CELL)).toBe('')
    expect(cellClass('neto', CELL)).toBe('')
  })

  it('ayuda con lo habitual', () => {
    expect(cellTitle(CELL)).toBe('Lo habitual: RD$ 4,000 · más alto que lo habitual')
    expect(cellTitle({ ...CELL, flag: null })).toBe('Lo habitual: RD$ 4,000')
    expect(cellTitle({ ...CELL, habitual_cents: null, flag: null })).toBe('Este mes no se compara')
  })

  it('cada celda abre Transacciones del mes, la categoría y las cuentas', () => {
    expect(cellHref('Salud', '2026-01', ['k'])).toBe('/transacciones?mes=2026-01&categoria=Salud&cuentas=k')
    expect(cellHref('ingresos', '2026-01', null)).toBe('/transacciones?mes=2026-01&tipo=ingresos')
    expect(cellHref('gastos', '2026-01', null)).toBe('/transacciones?mes=2026-01&tipo=gastos')
    expect(cellHref('terceros', '2026-01', null, 'A terceros')).toBe(
      '/transacciones?mes=2026-01&categoria=A+terceros',
    )
    expect(cellHref('neto', '2026-01', null)).toBeNull()
    expect(cellHref('ingreso:Cripto', '2026-01', null)).toBe(
      '/transacciones?mes=2026-01&tipo=ingresos&categoria=Cripto',
    )
    expect(cellClass('ingreso:Cripto', CELL)).toBe('')
  })
})

describe('rango', () => {
  it('lee desde/hasta solo si son meses con datos', () => {
    const params = new URLSearchParams({ desde: '2026-01', hasta: '2030-01' })
    expect(parseRange(params, MONTHS)).toEqual({ from: '2026-01', to: null })
  })

  it('arma la consulta y ordena un rango al revés', () => {
    expect(rangeQuery({ from: null, to: null })).toBe('')
    expect(rangeQuery({ from: '2026-01', to: '2026-02' })).toBe('?from=2026-01&to=2026-02')
    expect(orderedRange({ from: '2026-02', to: '2026-01' })).toEqual({ from: '2026-01', to: '2026-02' })
  })
})
