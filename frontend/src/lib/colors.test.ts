/// <reference types="node" />
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { barStyle, contrastRatio, FLOW_COLORS, luminance, SURFACES, TONE_COLORS } from './colors'

// Se lee el archivo tal cual (en Vitest, `?raw` de un .css llega vacío).
const CSS = readFileSync(new URL('../index.css', import.meta.url), 'utf8')

function token(name: string): string | undefined {
  return new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`).exec(CSS)?.[1]?.toUpperCase()
}

describe('contrastRatio', () => {
  it('va de 1 (iguales) a 21 (negro sobre blanco)', () => {
    expect(contrastRatio('#FFFFFF', '#FFFFFF')).toBeCloseTo(1)
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21)
    expect(contrastRatio('#FFFFFF', '#000000')).toBeCloseTo(21)
  })
  it('rechaza colores mal escritos', () => {
    expect(() => luminance('verde')).toThrow()
  })
})

describe('colores del flujo', () => {
  it('ingresos en el verde de la app; gastos en terracota; terceros en gris', () => {
    expect(FLOW_COLORS.income.strong).toBe(TONE_COLORS.down)
    // Terracota: más rojo que verde, más verde que azul (no un rojo puro de alarma).
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(FLOW_COLORS.expense.strong.slice(i, i + 2), 16))
    expect(r).toBeGreaterThan(g)
    expect(g).toBeGreaterThan(b)
    expect(r - g).toBeLessThan(0x60)
  })

  it('las barras del mes elegido se distinguen del fondo (≥ 3:1)', () => {
    for (const { strong } of Object.values(FLOW_COLORS)) {
      expect(contrastRatio(strong, SURFACES.card)).toBeGreaterThanOrEqual(3)
      expect(contrastRatio(strong, SURFACES.background)).toBeGreaterThanOrEqual(3)
    }
  })

  it('ingresos y gastos difieren también en luminosidad (daltonismo rojo-verde)', () => {
    expect(contrastRatio(FLOW_COLORS.income.strong, FLOW_COLORS.expense.strong)).toBeGreaterThanOrEqual(1.4)
  })

  it('la versión clara es más clara que la fuerte', () => {
    for (const { strong, light } of Object.values(FLOW_COLORS)) {
      expect(luminance(light)).toBeGreaterThan(luminance(strong))
    }
  })

  it('los textos de tono se leen sobre tarjeta y fondo (≥ 4.5:1)', () => {
    for (const color of Object.values(TONE_COLORS)) {
      expect(contrastRatio(color, SURFACES.card)).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(color, SURFACES.background)).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('los tokens de index.css repiten estos valores', () => {
    expect(token('income')).toBe(FLOW_COLORS.income.strong)
    expect(token('income-light')).toBe(FLOW_COLORS.income.light)
    expect(token('expense')).toBe(FLOW_COLORS.expense.strong)
    expect(token('expense-light')).toBe(FLOW_COLORS.expense.light)
    expect(token('transfer')).toBe(FLOW_COLORS.transfer.strong)
    expect(token('transfer-light')).toBe(FLOW_COLORS.transfer.light)
    expect(token('up')).toBe(TONE_COLORS.up)
    expect(token('down')).toBe(TONE_COLORS.down)
  })

  it('los avisos destructivos van en la terracota, no en el naranja de antes', () => {
    const destructive = /--destructive:\s*(#[0-9a-fA-F]{6})/.exec(CSS)?.[1]?.toUpperCase()
    expect(destructive).toBe(TONE_COLORS.up)
    expect(CSS.toLowerCase()).not.toContain('#b4540a')
  })
})

describe('barStyle', () => {
  const income = FLOW_COLORS.income
  it('el mes elegido va fuerte; los demás, claros', () => {
    expect(barStyle(income, { month: '2026-09', partial: false }, '2026-09').fill).toBe(income.strong)
    expect(barStyle(income, { month: '2026-08', partial: false }, '2026-09').fill).toBe(income.light)
  })
  it('un mes en curso va claro aunque esté elegido, con borde fuerte', () => {
    expect(barStyle(income, { month: '2026-10', partial: true }, '2026-10')).toEqual({
      fill: income.light,
      stroke: income.strong,
      strokeWidth: 1.5,
    })
    expect(barStyle(income, { month: '2026-10', partial: true }, '2026-09').stroke).toBeUndefined()
  })
})
