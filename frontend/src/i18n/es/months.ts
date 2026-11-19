// Spanish UI text: months. Keys start with "months.".
import type { Catalog } from '../index'

export const months = {
  'months.longDay': '{day} de {month}',
  'months.previous': 'Mes anterior',
  'months.next': 'Mes siguiente',
  'months.backTo': 'Volver a {month}',
  'months.headerScope': 'Movimientos del 1 al {last} de {month} en {scope} · montos en RD$',
  'months.pick': 'Elegir mes',
  'months.previousYear': 'Año anterior',
  'months.nextYear': 'Año siguiente',
  'months.currentCell': '{month} (mes en curso)',
} as const satisfies Catalog
