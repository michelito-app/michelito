// Month grid (3 columns × 4 rows) to jump to any month with data.
import type { MonthOption } from './api'
import { monthName } from './months'

/** Grid columns: ↑/↓ jump this many months. */
export const GRID_COLUMNS = 3

export interface MonthCell {
  /** "YYYY-MM". */
  month: string
  /** First three letters of the capitalized month name. */
  short: string
  /** Month name and year (the API label when the month has data). */
  label: string
  /** There is data for that month. */
  enabled: boolean
  /** It is today's month. */
  current: boolean
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Years with at least one month with data, oldest to newest. */
export function gridYears(options: readonly MonthOption[]): number[] {
  const years = new Set(options.map((o) => Number(o.month.slice(0, 4))))
  return [...years].sort((a, b) => a - b)
}

/** The previous (`-1`) or next (`1`) year with data; null at the ends. */
export function adjacentYear(years: readonly number[], year: number, step: -1 | 1): number | null {
  const candidates = years.filter((y) => (step < 0 ? y < year : y > year))
  if (candidates.length === 0) return null
  return step < 0 ? Math.max(...candidates) : Math.min(...candidates)
}

/** The 12 months of `year`; `today` is the current month ("YYYY-MM"). */
export function monthCells(
  options: readonly MonthOption[],
  year: number,
  today: string,
): MonthCell[] {
  return Array.from({ length: 12 }, (_, index) => {
    const month = `${year}-${String(index + 1).padStart(2, '0')}`
    const option = options.find((o) => o.month === month)
    const name = capitalize(monthName(month))
    return {
      month,
      short: name.slice(0, 3),
      label: option?.label ?? `${name} ${year}`,
      enabled: option !== undefined,
      current: month === today,
    }
  })
}

/** Index focus moves to from `from` with a step `delta` (±1 or ±columns), skipping months
 * without data; if there is none in that direction, it stays on `from`. */
export function moveFocus(
  cells: readonly { enabled: boolean }[],
  from: number,
  delta: number,
): number {
  for (let at = from + delta; at >= 0 && at < cells.length; at += delta) {
    if (cells[at].enabled) return at
  }
  return from
}
