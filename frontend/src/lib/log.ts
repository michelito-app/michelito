// Bitácora (lógica pura de la vista y del historial de una transacción). Las reglas viven en el
// servidor (src/finanzas/analysis/changelog.py y changelog_rules.py).
import { transactionsHref } from './accountFilter'

export type Author = 'usuario' | 'claude'

/** Un lado de la entrada: la línea legible y las filas tal como estaban. */
export interface LogSide {
  text: string
  rows: Record<string, Record<string, unknown>[]>
}

/** Una entrada (GET /api/log, /api/transactions/{huella}/history). */
export interface LogEntry {
  id: number
  at: string // ISO con zona (UTC)
  author: Author
  kind: string
  target_type: string
  target: string
  subject: string
  merchant: string | null
  before: LogSide
  after: LogSide
  affected: number
  fingerprints: string[]
  reason: string | null
  undoes: number | null
  undone: boolean
  can_undo: boolean
  undo_message: string
  blocked_by: number | null
  fingerprint: string | null // la transacción para el enlace
  month: string | null // su mes (null: ya no aparece)
  session_start?: string | null
  session_end?: string | null
  session_count?: number | null
}

export interface LogPage {
  items: LogEntry[]
  total: number
  offset: number
  kinds: string[]
}

export interface RuleHint {
  merchant: string
  category_id: number
  category: string
  count: number
}

export interface TxHistory {
  items: LogEntry[]
  rule_hint: RuleHint | null
}

export interface LogFilters {
  kind: string | null
  author: Author | null
  q: string
}

export const NO_FILTERS: LogFilters = { kind: null, author: null, q: '' }
export const PAGE_SIZE = 50
export const REASON_MAX = 500

/** Nombre de cada tipo (en el orden del filtro). */
export const KIND_LABELS: Record<string, string> = {
  categoria: 'Categoría',
  categoria_lote: 'Categoría en lote',
  regla: 'Regla por comercio',
  nota: 'Nota',
  gasto_unico: 'Gasto único',
  compartido: 'Compartido',
  cambio: 'Cambio de divisas',
  inversion: 'Inversión',
  caja_fuerte: 'Caja fuerte',
  caja_movimiento: 'Movimiento de la caja',
  recurrente: 'Recurrente',
  recurrente_union: 'Unión de recurrentes',
  revisado: 'Para revisar',
  palabras_clave: 'Palabras clave',
  categoria_tipo: 'Tipo de categoría',
  categoria_borrada: 'Categoría borrada',
  presupuesto: 'Presupuesto',
  presupuesto_aviso: 'Aviso de lo habitual',
  reserva: 'Reserva',
  reserva_gasto: 'Gasto de una reserva',
  reserva_descarte: 'Sugerencia de reserva',
}

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

/** «RETIRO AHORRO LBRT · Efectivo → Caja fuerte»; un «Deshacer» lo dice delante. */
type LineParts = Pick<LogEntry, 'subject' | 'before' | 'after' | 'undoes'>

export function entryLine(entry: LineParts): string {
  const line = `${entry.subject} · ${entry.before.text} → ${entry.after.text}`
  return entry.undoes === null ? line : `Deshecho: ${line}`
}

/** «1 transacción», «14 transacciones». */
export function affectedText(count: number): string {
  return count === 1 ? '1 transacción' : `${count} transacciones`
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

const TIME = new Intl.DateTimeFormat('es-DO', { hour: '2-digit', minute: '2-digit', hour12: false })
const DAY = new Intl.DateTimeFormat('es-DO', { day: 'numeric', month: 'short' })
const DAY_YEAR = new Intl.DateTimeFormat('es-DO', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

/** «Hoy», «Ayer», «12 feb» o «12 feb 2025» (en la hora local). */
export function dayText(when: Date, now: Date = new Date()): string {
  if (sameDay(when, now)) return 'Hoy'
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (sameDay(when, yesterday)) return 'Ayer'
  const format = when.getFullYear() === now.getFullYear() ? DAY : DAY_YEAR
  return format.format(when).replace(/\./g, '').replace(/ de /g, ' ')
}

export function timeText(when: Date): string {
  return TIME.format(when)
}

/** «Hoy, 18:40–19:05 · 14 cambios»; con un solo cambio, «Hoy, 18:40 · 1 cambio». Con filtros
 * (`shown` menor que `count`), «Hoy, 18:40–19:05 · 2 de 14 cambios». */
export function sessionLabel(
  start: string,
  end: string,
  count: number,
  now: Date = new Date(),
  shown: number = count,
): string {
  const from = new Date(start)
  const to = new Date(end)
  const [first, last] = [timeText(from), timeText(to)]
  const span = first === last ? first : `${first}–${last}`
  const total = count === 1 ? '1 cambio' : `${count} cambios`
  const changes = shown < count ? `${shown} de ${total}` : total
  return `${dayText(from, now)}, ${span} · ${changes}`
}

export interface SessionGroup {
  key: string
  label: string
  entries: LogEntry[]
}

/** Agrupa las entradas (ya en orden, la más reciente primero) por su sesión de edición. */
export function groupBySession(
  entries: readonly LogEntry[],
  now: Date = new Date(),
): SessionGroup[] {
  const groups: { key: string; first: LogEntry; entries: LogEntry[] }[] = []
  for (const entry of entries) {
    const key = `${entry.session_start ?? entry.at}|${entry.session_end ?? entry.at}`
    const last = groups.at(-1)
    if (last && last.key === key) last.entries.push(entry)
    else groups.push({ key, first: entry, entries: [entry] })
  }
  // El total es el de la sesión entera; si se ven menos (filtros, «Ver más»), lo dice.
  return groups.map(({ key, first, entries: shown }) => ({
    key,
    label: sessionLabel(
      first.session_start ?? first.at,
      first.session_end ?? first.at,
      first.session_count ?? shown.length,
      now,
      shown.length,
    ),
    entries: shown,
  }))
}

/** La ruta de la página pedida, con los filtros. */
export function logPath(filters: LogFilters, offset = 0, limit = PAGE_SIZE): string {
  const query = new URLSearchParams()
  if (filters.kind) query.set('kind', filters.kind)
  if (filters.author) query.set('author', filters.author)
  if (filters.q.trim()) query.set('q', filters.q.trim())
  if (offset) query.set('offset', String(offset))
  query.set('limit', String(limit))
  return `/api/log?${query.toString()}`
}

/** Enlace a la transacción de la entrada (en Transacciones, con su mes) o, para una regla por
 * comercio, a Transacciones buscando el comercio. Null si ya no aparece. */
export function entryHref(entry: LogEntry): string | null {
  if (entry.target_type === 'comercio' && entry.month) {
    return transactionsHref({ mes: entry.month, q: entry.target }, null)
  }
  if (!entry.fingerprint || !entry.month) return null
  return transactionsHref({ mes: entry.month, tx: entry.fingerprint }, null)
}

/** Por qué no hay «Deshacer» (vacío si lo hay). */
export function undoNote(entry: LogEntry): string {
  if (entry.can_undo) return ''
  return entry.undo_message
}

/** «Las otras 2 veces lo pusiste en Delivery». */
export function hintText(hint: RuleHint): string {
  return `Las otras ${hint.count} veces lo pusiste en ${hint.category}.`
}
