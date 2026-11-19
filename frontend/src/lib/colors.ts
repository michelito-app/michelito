// Money-flow colors, the same in charts, legends, KPIs and Reports: income in green (the same as
// "+RD$" and a positive "Left over"), expenses in muted terracotta (not an alarm red) and transfers
// to third parties in gray. Months not selected or in progress use the light version. The
// index.css tokens (--color-income, --color-expense…) repeat these values; the tests check the
// contrast.
import type { MonthTotal } from './api'

export interface SeriesColor {
  /** Bar of the selected month, legend and accents. */
  strong: string
  /** Months not selected or in progress. */
  light: string
}

export const FLOW_COLORS = {
  income: { strong: '#1F6F5C', light: '#CFE0DA' },
  expense: { strong: '#BF7050', light: '#EED6CB' },
  transfer: { strong: '#80868F', light: '#DCDFE3' },
} as const satisfies Record<string, SeriesColor>

/** Text for "more spending" (`text-up`) and for "less spending" or income (`text-down`). */
export const TONE_COLORS = { up: '#9C4F35', down: '#1F6F5C' } as const

/** App backgrounds the colors sit on. */
export const SURFACES = { card: '#FFFFFF', background: '#F7F7F5' } as const

function channel(value: number): number {
  const c = value / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

/** Relative luminance (WCAG 2) of a "#RRGGBB" color. */
export function luminance(hex: string): number {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex)
  if (!match) throw new Error(`invalid color: ${hex}`)
  const [r, g, b] = match.slice(1).map((part) => channel(parseInt(part, 16)))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** WCAG contrast between two colors (1 to 21). */
export function contrastRatio(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

export interface BarStyle {
  fill: string
  stroke: string | undefined
  strokeWidth: number
}

/** Fill and border of a monthly bar: the selected month in the strong color; the others and the
 * months in progress in the light one. A selected month in progress also gets the strong border,
 * so it is still clear which one it is. */
export function barStyle(series: SeriesColor, point: Pick<MonthTotal, 'month' | 'partial'>, month: string): BarStyle {
  const selected = point.month === month
  const outlined = selected && point.partial
  return {
    fill: selected && !point.partial ? series.strong : series.light,
    stroke: outlined ? series.strong : undefined,
    strokeWidth: outlined ? 1.5 : 0,
  }
}
