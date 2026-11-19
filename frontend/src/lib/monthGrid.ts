// Cuadrícula de meses (3 columnas × 4 filas) para saltar a cualquier mes con datos.
import type { MonthOption } from './api'
import { monthName } from './months'

/** Columnas de la cuadrícula: ↑/↓ saltan esta cantidad de meses. */
export const GRID_COLUMNS = 3

export interface MonthCell {
  /** "YYYY-MM". */
  month: string
  /** "Ene". */
  short: string
  /** "Enero 2026". */
  label: string
  /** Hay datos de ese mes. */
  enabled: boolean
  /** Es el mes de hoy. */
  current: boolean
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Años con al menos un mes con datos, del más viejo al más nuevo. */
export function gridYears(options: readonly MonthOption[]): number[] {
  const years = new Set(options.map((o) => Number(o.month.slice(0, 4))))
  return [...years].sort((a, b) => a - b)
}

/** El año con datos anterior (`-1`) o siguiente (`1`); null en los extremos. */
export function adjacentYear(years: readonly number[], year: number, step: -1 | 1): number | null {
  const candidates = years.filter((y) => (step < 0 ? y < year : y > year))
  if (candidates.length === 0) return null
  return step < 0 ? Math.max(...candidates) : Math.min(...candidates)
}

/** Los 12 meses de `year`; `today` es el mes en curso ("YYYY-MM"). */
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

/** Índice al que va el foco desde `from` con un paso `delta` (±1 o ±columnas), saltando los
 * meses sin datos; si no hay ninguno en esa dirección, se queda en `from`. */
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
