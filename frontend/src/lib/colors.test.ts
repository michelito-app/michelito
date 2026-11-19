/// <reference types="node" />
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { barStyle, contrastRatio, FLOW_COLORS, luminance, SURFACES, TONE_COLORS } from './colors'

// The file is read as is (in Vitest, `?raw` of a .css arrives empty).
const CSS = readFileSync(new URL('../index.css', import.meta.url), 'utf8')

function token(name: string): string | undefined {
  return new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`).exec(CSS)?.[1]?.toUpperCase()
}

describe('contrastRatio', () => {
  it('goes from 1 (equal) to 21 (black on white)', () => {
    expect(contrastRatio('#FFFFFF', '#FFFFFF')).toBeCloseTo(1)
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21)
    expect(contrastRatio('#FFFFFF', '#000000')).toBeCloseTo(21)
  })
  it('rejects badly written colors', () => {
    expect(() => luminance('green')).toThrow()
  })
})

describe('flow colors', () => {
  it('income in the app green; expenses in terracotta; third parties in gray', () => {
    expect(FLOW_COLORS.income.strong).toBe(TONE_COLORS.down)
    // Terracotta: more red than green, more green than blue (not a pure alarm red).
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(FLOW_COLORS.expense.strong.slice(i, i + 2), 16))
    expect(r).toBeGreaterThan(g)
    expect(g).toBeGreaterThan(b)
    expect(r - g).toBeLessThan(0x60)
  })

  it('the selected month bars stand out from the background (≥ 3:1)', () => {
    for (const { strong } of Object.values(FLOW_COLORS)) {
      expect(contrastRatio(strong, SURFACES.card)).toBeGreaterThanOrEqual(3)
      expect(contrastRatio(strong, SURFACES.background)).toBeGreaterThanOrEqual(3)
    }
  })

  it('income and expenses also differ in luminance (red-green color blindness)', () => {
    expect(contrastRatio(FLOW_COLORS.income.strong, FLOW_COLORS.expense.strong)).toBeGreaterThanOrEqual(1.4)
  })

  it('the light version is lighter than the strong one', () => {
    for (const { strong, light } of Object.values(FLOW_COLORS)) {
      expect(luminance(light)).toBeGreaterThan(luminance(strong))
    }
  })

  it('tone texts are readable on card and background (≥ 4.5:1)', () => {
    for (const color of Object.values(TONE_COLORS)) {
      expect(contrastRatio(color, SURFACES.card)).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(color, SURFACES.background)).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('the index.css tokens repeat these values', () => {
    expect(token('income')).toBe(FLOW_COLORS.income.strong)
    expect(token('income-light')).toBe(FLOW_COLORS.income.light)
    expect(token('expense')).toBe(FLOW_COLORS.expense.strong)
    expect(token('expense-light')).toBe(FLOW_COLORS.expense.light)
    expect(token('transfer')).toBe(FLOW_COLORS.transfer.strong)
    expect(token('transfer-light')).toBe(FLOW_COLORS.transfer.light)
    expect(token('up')).toBe(TONE_COLORS.up)
    expect(token('down')).toBe(TONE_COLORS.down)
  })

  it('destructive notices use the terracotta, not the former orange', () => {
    const destructive = /--destructive:\s*(#[0-9a-fA-F]{6})/.exec(CSS)?.[1]?.toUpperCase()
    expect(destructive).toBe(TONE_COLORS.up)
    expect(CSS.toLowerCase()).not.toContain('#b4540a')
  })
})

describe('barStyle', () => {
  const income = FLOW_COLORS.income
  it('the selected month is strong; the others light', () => {
    expect(barStyle(income, { month: '2026-09', partial: false }, '2026-09').fill).toBe(income.strong)
    expect(barStyle(income, { month: '2026-08', partial: false }, '2026-09').fill).toBe(income.light)
  })
  it('a month in progress is light even when selected, with a strong border', () => {
    expect(barStyle(income, { month: '2026-10', partial: true }, '2026-10')).toEqual({
      fill: income.light,
      stroke: income.strong,
      strokeWidth: 1.5,
    })
    expect(barStyle(income, { month: '2026-10', partial: true }, '2026-09').stroke).toBeUndefined()
  })
})
