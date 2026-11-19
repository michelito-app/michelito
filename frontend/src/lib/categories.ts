// Colores de las categorías (los mismos que la tabla del Resumen, por puesto de gasto del mes)
// y su agrupación por tipo para los selectores.
import type { Category, Kind } from './api'

/** Paleta de categorías, en orden de gasto. No usa los colores del flujo (verde de ingresos,
 * terracota de gastos, gris de terceros; ver lib/colors) ni el azul de antes: una categoría no
 * debe leerse como ingreso o como alerta. */
export const CATEGORY_PALETTE = [
  '#3FA7C9',
  '#8E5FB8',
  '#D9A93A',
  '#B8467E',
  '#A3994F',
  '#4A5568',
  '#D88FC4',
  '#6B4FA0',
  '#E0B98A',
  '#7A3E8F',
] as const

/** Débitos bancarios a otras personas: no son gasto, pero restan de lo que te quedó. Nombre
 * de nacimiento de `categories.THIRD_PARTY` del servidor (el usuario puede renombrarla: el
 * nombre de hoy sale de `builtinName`; el servidor también entiende este). */
export const THIRD_PARTY = 'Transferencias a terceros'

/** Identidad estable (`builtin_key`) de las categorías del sistema que el board nombra. */
export const BUILTIN = { thirdParty: 'THIRD_PARTY' } as const

/** Las que solo pone su vínculo (marcar una inversión o la caja fuerte): no se eligen a mano ni
 * llevan palabras clave. «Rendimientos» sí se elige: un ingreso cualquiera puede serlo. */
export const LINK_ONLY_KEYS: readonly string[] = ['INVESTMENT', 'INVESTMENT_CAPITAL', 'CASH_BOX']

/** ¿Solo la pone su vínculo? */
export function isLinkOnly(category: Pick<Category, 'builtin_key'>): boolean {
  return category.builtin_key !== null && LINK_ONLY_KEYS.includes(category.builtin_key)
}

/** Las que se pueden elegir a mano (sin las que solo pone su vínculo). */
export function choosable<T extends Pick<Category, 'builtin_key'>>(categories: readonly T[]): T[] {
  return categories.filter((c) => !isLinkOnly(c))
}

/** Nombre de hoy de una categoría del sistema, por su identidad estable. */
export function builtinName(
  categories: readonly Pick<Category, 'name' | 'builtin_key'>[],
  key: string,
  fallback: string,
): string {
  return categories.find((c) => c.builtin_key === key)?.name ?? fallback
}

/** Colores elegidos por el usuario, por nombre de categoría (las demás van por puesto). */
export function customColors(
  categories: readonly Pick<Category, 'name' | 'color'>[],
): Readonly<Record<string, string>> {
  return Object.fromEntries(
    categories.filter((c) => c.color !== null).map((c) => [c.name, c.color as string]),
  )
}

/** Nombres viejos de categorías renombradas (igual que `categories._LEGACY_NAMES`). */
const LEGACY_NAMES: Readonly<Record<string, string>> = { 'Efectivo y transferencias': 'Efectivo' }

/** Nombre actual de una categoría que puede venir con un nombre anterior (un enlace viejo). */
export function canonicalCategory(name: string): string {
  return LEGACY_NAMES[name] ?? name
}

/** Gris para categorías sin puesto (sin compras en el mes o resumen aún cargando). */
export const NO_COLOR = '#C9CDD2'

/** Color del puesto `index` (0 = la categoría con más gasto). */
export function categoryColor(index: number): string {
  return CATEGORY_PALETTE[index % CATEGORY_PALETTE.length]
}

/** Color de `category`: el que eligió el usuario o, si no, el de su puesto en `ranking`
 * (categorías del Resumen, de mayor a menor). */
export function colorFor(
  ranking: readonly string[],
  category: string,
  custom: Readonly<Record<string, string>> = {},
): string {
  if (custom[category]) return custom[category]
  const index = ranking.indexOf(category)
  return index < 0 ? NO_COLOR : categoryColor(index)
}

export interface CategoryGroup {
  label: string
  names: string[]
}

/** Grupos de los selectores, en este orden. */
export const GROUPS: readonly { kind: Kind; label: string }[] = [
  { kind: 'gasto', label: 'Gastos' },
  { kind: 'ingreso', label: 'Ingresos' },
  { kind: 'transferencia', label: 'Transferencias' },
]

type Listed = Pick<Category, 'name' | 'kind'> & { hidden?: boolean }

/** Categorías agrupadas por tipo (para `<optgroup>`), sin las ocultas ni grupos vacíos.
 * `keep`: una oculta que igual va (la que tiene la fila o el filtro). */
export function categoryGroups(
  categories: readonly Listed[],
  keep: string | null = null,
): CategoryGroup[] {
  const shown = categories.filter((c) => !c.hidden || c.name === keep)
  return GROUPS.map(({ kind, label }) => ({
    label,
    names: shown.filter((c) => c.kind === kind).map((c) => c.name),
  })).filter((group) => group.names.length > 0)
}

/** Valor de la opción "+ Nueva categoría…" del selector del detalle. Con espacios en los bordes:
 * el servidor los quita de los nombres, así que ninguna categoría puede llamarse así. */
export const NEW_CATEGORY = ' + nueva categoría '

/** `data-action` de esa opción: se reconoce por esto, no por el valor. */
export const NEW_CATEGORY_ACTION = 'nueva-categoria'

/** ¿La opción elegida es "+ Nueva categoría…"? */
export function isNewCategoryOption(
  option: { dataset: Record<string, string | undefined> } | undefined,
): boolean {
  return option?.dataset.action === NEW_CATEGORY_ACTION
}

/** Colores para elegir al crear o editar una categoría (los de la paleta del diseño). */
export const COLOR_CHOICES: readonly string[] = CATEGORY_PALETTE

/** "12 este año" / "1 este año" / "Sin transacciones este año". */
export function countText(count: number): string {
  if (count === 0) return 'Sin transacciones este año'
  return `${count} ${count === 1 ? 'transacción' : 'transacciones'} este año`
}

/** "Esto moverá 3 transacciones (RD$ 1,250)"; más la nota de los US$ sin tasa. */
export function previewText(count: number, dop: string, usd: string | null): string {
  if (count === 0) return 'Esto no mueve ninguna transacción'
  const noun = count === 1 ? 'transacción' : 'transacciones'
  const money = usd ? `${dop} y ${usd} sin tasa` : dop
  return `Esto moverá ${count} ${noun} (${money})`
}

/** Nota de choques: transacciones que también tienen palabras de otra categoría. */
export function conflictText(conflicts: number): string | null {
  if (conflicts === 0) return null
  const noun = conflicts === 1 ? 'transacción coincide' : 'transacciones coinciden'
  return `${conflicts} ${noun} también con palabras de otra categoría: gana la palabra más larga`
}

/** Palabras clave escritas separadas por coma o salto de línea, sin vacías. */
export function parseKeywords(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((word) => word.trim())
    .filter((word) => word !== '')
}
