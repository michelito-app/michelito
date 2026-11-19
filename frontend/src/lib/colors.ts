// Colores del flujo de dinero, iguales en gráficos, leyendas, indicadores y Reportes:
// ingresos en verde (el mismo de "+RD$" y de "Te quedó" positivo), gastos en terracota apagado
// (no un rojo de alarma) y transferencias a terceros en gris. Los meses no elegidos o en curso
// van en la versión clara. Los tokens de index.css (--color-income, --color-expense…) repiten
// estos valores; las pruebas comprueban el contraste.
import type { MonthTotal } from './api'

export interface SeriesColor {
  /** Barra del mes elegido, leyenda y acentos. */
  strong: string
  /** Meses no elegidos o en curso. */
  light: string
}

export const FLOW_COLORS = {
  income: { strong: '#1F6F5C', light: '#CFE0DA' },
  expense: { strong: '#BF7050', light: '#EED6CB' },
  transfer: { strong: '#80868F', light: '#DCDFE3' },
} as const satisfies Record<string, SeriesColor>

/** Texto de "más gasto" (`text-up`) y de "menos gasto" o ingreso (`text-down`). */
export const TONE_COLORS = { up: '#9C4F35', down: '#1F6F5C' } as const

/** Fondos de la app sobre los que van los colores. */
export const SURFACES = { card: '#FFFFFF', background: '#F7F7F5' } as const

function channel(value: number): number {
  const c = value / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

/** Luminancia relativa (WCAG 2) de un color "#RRGGBB". */
export function luminance(hex: string): number {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex)
  if (!match) throw new Error(`color inválido: ${hex}`)
  const [r, g, b] = match.slice(1).map((part) => channel(parseInt(part, 16)))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** Contraste WCAG entre dos colores (1 a 21). */
export function contrastRatio(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

export interface BarStyle {
  fill: string
  stroke: string | undefined
  strokeWidth: number
}

/** Relleno y borde de una barra mensual: el mes elegido va en el color fuerte; los demás y los
 * meses en curso, en el claro. Un mes en curso elegido lleva además el borde fuerte, para que se
 * siga viendo cuál es. */
export function barStyle(series: SeriesColor, point: Pick<MonthTotal, 'month' | 'partial'>, month: string): BarStyle {
  const selected = point.month === month
  const outlined = selected && point.partial
  return {
    fill: selected && !point.partial ? series.strong : series.light,
    stroke: outlined ? series.strong : undefined,
    strokeWidth: outlined ? 1.5 : 0,
  }
}
