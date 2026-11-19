import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { CompareCell, MonthOption } from './api'
import { cellClass, cellHref, cellTitle, orderedRange, parseRange, rangeQuery } from './reports'

const CELL: CompareCell = { amount_cents: 900_000, habitual_cents: 400_000, flag: 'up', level: 3 }
const MONTHS: MonthOption[] = [
  { month: '2026-02', label: 'February 2026', partial: true },
  { month: '2026-01', label: 'January 2026', partial: false },
]

describe('cells', () => {
  it('a rise in terracotta by intensity; a fall with a green border', () => {
    expect(cellClass('Groceries', CELL)).toBe('bg-[#E4B8A3]')
    expect(cellClass('Groceries', { ...CELL, level: 1 })).toBe('bg-[#F7E9E2]')
    expect(cellClass('expenses', { ...CELL, flag: 'down', level: 0 })).toContain('--color-down')
    expect(cellClass('Groceries', { ...CELL, flag: null })).toBe('')
  })

  it('income, third parties and what was left are not coloured', () => {
    expect(cellClass('income', CELL)).toBe('')
    expect(cellClass('third_party', CELL)).toBe('')
    expect(cellClass('net', CELL)).toBe('')
  })

  it('help with the usual', () => {
    expect(cellTitle(CELL)).toBe(t('reports.cell.higher', { habitual: 'RD$ 4,000' }))
    expect(cellTitle({ ...CELL, flag: 'down' })).toBe(t('reports.cell.lower', { habitual: 'RD$ 4,000' }))
    expect(cellTitle({ ...CELL, flag: null })).toBe(t('reports.cell.habitual', { habitual: 'RD$ 4,000' }))
    expect(cellTitle({ ...CELL, habitual_cents: null, flag: null })).toBe(t('reports.cell.notCompared'))
  })

  it('each cell opens Transactions with the month, the category and the accounts', () => {
    expect(cellHref('Health', '2026-01', ['k'])).toBe('/transactions?month=2026-01&category=Health&accounts=k')
    expect(cellHref('income', '2026-01', null)).toBe('/transactions?month=2026-01&kind=income')
    expect(cellHref('expenses', '2026-01', null)).toBe('/transactions?month=2026-01&kind=expense')
    expect(cellHref('third_party', '2026-01', null, 'To others')).toBe(
      '/transactions?month=2026-01&category=To+others',
    )
    expect(cellHref('net', '2026-01', null)).toBeNull()
    expect(cellHref('income:Crypto', '2026-01', null)).toBe(
      '/transactions?month=2026-01&kind=income&category=Crypto',
    )
    expect(cellClass('income:Crypto', CELL)).toBe('')
  })
})

describe('range', () => {
  it('reads from/to only when they are months with data', () => {
    const params = new URLSearchParams({ from: '2026-01', to: '2030-01' })
    expect(parseRange(params, MONTHS)).toEqual({ from: '2026-01', to: null })
  })

  it('builds the query and orders a reversed range', () => {
    expect(rangeQuery({ from: null, to: null })).toBe('')
    expect(rangeQuery({ from: '2026-01', to: '2026-02' })).toBe('?from=2026-01&to=2026-02')
    expect(orderedRange({ from: '2026-02', to: '2026-01' })).toEqual({ from: '2026-01', to: '2026-02' })
  })
})
