// Reportes: comparar meses (lógica pura). La regla de las celdas vive en el servidor
// (src/finanzas/web/reports.py): aquí solo se eligen clases, textos y enlaces.
import type { CompareCell, MonthOption } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { THIRD_PARTY } from './categories'
import { formatDop } from './money'

export const FROM_PARAM = 'desde'
export const TO_PARAM = 'hasta'

/** Clave de una fila de ingresos por categoría (`reports.INCOME_PREFIX`): `ingreso:Cripto`. */
export const INCOME_PREFIX = 'ingreso:'

/** Filas de arriba: no son categorías. */
export const TOTAL_KEYS = ['ingresos', 'gastos', 'terceros', 'neto'] as const

/** Fondo de una subida (terracota más intensa cuanto más se aparta). El texto sigue oscuro. */
const UP_LEVELS = ['', 'bg-[#F7E9E2]', 'bg-[#EFD3C5]', 'bg-[#E4B8A3]'] as const
const DOWN = 'shadow-[inset_0_0_0_2px_var(--color-down)]'

/** Clases de una celda: subida en terracota (intensidad 1 a 3), bajada con borde verde. Los
 * ingresos y "Te quedó" no se colorean (subir ahí es bueno, no un gasto). */
export function cellClass(rowKey: string, cell: CompareCell): string {
  if (rowKey === 'ingresos' || rowKey === 'terceros' || rowKey === 'neto') return ''
  if (rowKey.startsWith(INCOME_PREFIX)) return ''
  if (cell.flag === 'up') return UP_LEVELS[Math.min(3, Math.max(1, cell.level))]
  if (cell.flag === 'down') return DOWN
  return ''
}

/** Texto de ayuda de una celda: lo habitual y el desvío. */
export function cellTitle(cell: CompareCell): string {
  if (cell.habitual_cents === null) return 'Este mes no se compara'
  const base = `Lo habitual: ${formatDop(cell.habitual_cents)}`
  if (cell.flag === 'up') return `${base} · más alto que lo habitual`
  if (cell.flag === 'down') return `${base} · más bajo que lo habitual`
  return base
}

/** Adónde lleva una celda en Transacciones (mes, categoría y cuentas); null para "Te quedó". */
export function cellHref(
  rowKey: string,
  month: string,
  selection: Selection,
  thirdPartyName: string = THIRD_PARTY,
): string | null {
  switch (rowKey) {
    case 'neto':
      return null
    case 'ingresos':
      return transactionsHref({ mes: month, tipo: 'ingresos' }, selection)
    case 'gastos':
      return transactionsHref({ mes: month, tipo: 'gastos' }, selection)
    case 'terceros':
      return transactionsHref({ mes: month, categoria: thirdPartyName }, selection)
    default:
      if (rowKey.startsWith(INCOME_PREFIX)) {
        const categoria = rowKey.slice(INCOME_PREFIX.length)
        return transactionsHref({ mes: month, tipo: 'ingresos', categoria }, selection)
      }
      return transactionsHref({ mes: month, categoria: rowKey }, selection)
  }
}

export interface Range {
  from: string | null
  to: string | null
}

/** El rango de la URL (`desde`, `hasta`), solo si son meses con datos. */
export function parseRange(params: URLSearchParams, months: readonly MonthOption[]): Range {
  const known = new Set(months.map((m) => m.month))
  const pick = (key: string) => {
    const value = params.get(key)
    return value && known.has(value) ? value : null
  }
  return { from: pick(FROM_PARAM), to: pick(TO_PARAM) }
}

/** Parámetros de la API para el rango (`from`, `to`); vacío: los 12 meses más recientes. */
export function rangeQuery(range: Range): string {
  const query = new URLSearchParams()
  if (range.from) query.set('from', range.from)
  if (range.to) query.set('to', range.to)
  const text = query.toString()
  return text ? `?${text}` : ''
}

/** Un rango que el servidor acepta: si "desde" queda después de "hasta", se intercambian. */
export function orderedRange(range: Range): Range {
  if (range.from && range.to && range.from > range.to) return { from: range.to, to: range.from }
  return range
}
