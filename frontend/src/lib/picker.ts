// Selectores de vínculos (patas de un cambio, reembolsos): el servidor ordena y marca cuáles
// van a la vista (`primary`); aquí se buscan y se parten en lo visible y lo de «Ver más».
import type { Candidate } from './api'

/** Cuántas opciones primarias se ven antes de «Ver más». */
export const VISIBLE = 5

export interface Shown {
  visible: Candidate[]
  more: Candidate[]
}

/** Sin búsqueda: las primeras VISIBLE primarias a la vista; el resto (las demás primarias y las
 * no primarias), tras «Ver más», en el orden del servidor. */
export function partition(items: readonly Candidate[], limit = VISIBLE): Shown {
  const visible = items.filter((c) => c.primary).slice(0, limit)
  const shown = new Set(visible.map((c) => c.fingerprint))
  return { visible, more: items.filter((c) => !shown.has(c.fingerprint)) }
}

const AMOUNT_QUERY = /^\d[\d,]*(\.\d{0,2})?$/

/** Dígitos de un monto para comparar: "1,000.50" → "1000.50"; null si no parece un monto. */
export function amountQuery(query: string): string | null {
  const clean = query.trim().replace(/^(RD|US)?\$\s*/i, '')
  if (!AMOUNT_QUERY.test(clean)) return null
  return clean.replaceAll(',', '')
}

/** Los montos que muestra la opción (el suyo y, si lo trae, el convertido), como "1000.50". */
function amountTexts(item: Candidate): string[] {
  const cents = [item.amount_cents]
  if (item.converted_cents != null) cents.push(item.converted_cents)
  return cents.map(centsText)
}

/** Un monto como lo compara el buscador: "1000.50" (sin signo). */
export function centsText(cents: number): string {
  return (Math.abs(cents) / 100).toFixed(2)
}

/** ¿La opción coincide con la búsqueda? Un monto ("1000", "1,000", "1000.50") coincide si
 * alguno de sus montos empieza por esos dígitos; si no, el texto se busca en el comercio, la
 * descripción y la cuenta (sin distinguir mayúsculas ni acentos). */
export function matches(item: Candidate, query: string): boolean {
  const amount = amountQuery(query)
  if (amount !== null) return amountTexts(item).some((text) => text.startsWith(amount))
  const needle = fold(query.trim())
  if (needle === '') return true
  return [item.merchant, item.description ?? '', item.account_label].some((text) =>
    fold(text).includes(needle),
  )
}

/** Lo que se ve: sin búsqueda, la partición; con búsqueda, todas las que coinciden (de toda la
 * lista, no solo de las visibles). */
export function shownCandidates(items: readonly Candidate[], query: string): Shown {
  if (query.trim() === '') return partition(items)
  return { visible: items.filter((c) => matches(c, query)), more: [] }
}

/** Sin acentos y en minúsculas, para buscar. */
export function fold(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
}
