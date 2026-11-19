// Presupuesto y reservas (lógica pura de la vista). Las reglas viven en el servidor
// (src/finanzas/analysis/budget.py y reserves.py); aquí, los tipos y cómo se dice cada cosa.
import { formatDop } from './money'
import { monthName, monthPhrase } from './months'

export interface BudgetWarning {
  habitual_cents: number
  basis_cents: number
  up: boolean
}

/** Una categoría del mes (GET /api/budget). */
export interface BudgetLine {
  category_id: number
  category: string
  cap_cents: number | null // null: «Sin presupuesto»
  manual: boolean
  spent_cents: number // contra el tope (sin gastos únicos ni lo cubierto por reservas)
  one_offs_cents: number
  covered_cents: number
  without_rate: number
  over_cents: number // lo que pasa del tope, exacto
  passed: boolean // pasó por más de max(5 %, RD$ 500): cuenta como pasada
  refunds_cents: number // devuelto de más en el mes (lo gastado queda en 0)
  habitual_cents: number | null
  warning: BudgetWarning | null
  active: boolean
}

export interface Budget {
  active: boolean
  month: string
  lines: BudgetLine[]
  cap_cents: number
  spent_cents: number
  over_count: number
  over_cents: number
  reference_months: string[]
  filtered: boolean // con filtro de cuentas: topes de todas, lo gastado de las elegidas
  missing: string[] // cuentas sin el estado completo del mes
}

export interface ReserveMember {
  fingerprint: string
  day: string
  month: string
  merchant: string
  amount_cents: number
  currency: string
  amount_dop_cents: number | null
}

export interface Reserve {
  id: number
  name: string
  amount_cents: number
  category_id: number
  category: string
  due_month: string
  every_months: number | null // null: una sola vez
  multiple: boolean
  next_due: string | null
  monthly_cents: number
  year_spent_cents: number
  year_estimated_cents: number
  year_without_rate: number
  paid: boolean // el próximo vencimiento ya tiene su gasto vinculado
  members: ReserveMember[]
}

export interface ReserveSuggestion {
  key: string
  name: string
  amount_cents: number
  category_id: number
  category: string
  due_month: string
  every_months: number
  multiple: boolean
  reason: string
}

export interface Reserves {
  items: Reserve[]
  suggestions: ReserveSuggestion[]
  monthly_cents: number
}

export interface ReserveBody {
  name: string
  amount_cents: number
  category_id: number
  due_month: string
  every_months: number | null
  multiple: boolean
  source?: string | null
}

export interface ReserveRef {
  id: number
  name: string
  category: string
  next_due: string | null
  suggested: boolean
}

/** La sección «Reserva» del detalle (GET /api/transactions/{huella}/reserve). */
export interface TxReserve {
  reserve: ReserveRef | null
  options: ReserveRef[]
  can_link: boolean
  reason: string
}

export interface MembersResult {
  applied: string[]
  skipped: { fingerprint: string; reason: string; message: string }[]
  entry_id: number | null
}

export interface BudgetOverview {
  active: boolean
  over_count: number | null // null con filtro de cuentas: no se cuentan las pasadas
  over_cents: number
  missing: string[]
  monthly_cents: number
  reserves: number
  upcoming: { id: number; name: string; due_month: string; amount_cents: number }[]
}

export const BUDGET_PATH = '/presupuesto'

/** Cada cuánto: los tres planes que ofrece el formulario (el servidor admite 1 a 12 meses). */
export type Schedule = 'anual' | 'semestral' | 'una'
export const SCHEDULES: { value: Schedule; label: string }[] = [
  { value: 'anual', label: 'Cada año' },
  { value: 'semestral', label: 'Cada 6 meses' },
  { value: 'una', label: 'Una vez' },
]

export function scheduleMonths(schedule: Schedule): number | null {
  return schedule === 'anual' ? 12 : schedule === 'semestral' ? 6 : null
}

export function scheduleOf(every: number | null): Schedule {
  return every === null ? 'una' : every === 6 ? 'semestral' : 'anual'
}

/** «Cada año en enero», «Cada 6 meses (marzo y septiembre)», «Una vez, en diciembre 2026». */
export function scheduleText(reserve: Pick<Reserve, 'every_months' | 'due_month'>): string {
  const { every_months: every, due_month: due } = reserve
  if (every === null) return `Una vez, en ${monthPhrase(due)}`
  if (every === 12) return `Cada año en ${monthName(due)}`
  if (every === 6) {
    const second = shiftMonth(due, 6)
    const [a, b] = [due, second].sort((x, y) => Number(x.slice(5)) - Number(y.slice(5)))
    return `Cada 6 meses (${monthName(a)} y ${monthName(b)})`
  }
  return `Cada ${every} meses desde ${monthPhrase(due)}`
}

/** "2026-11" + 3 → "2027-02". */
export function shiftMonth(month: string, count: number): string {
  const index = Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7)) - 1 + count
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, '0')}`
}

/** «Vence en marzo 2026» o «Ya venció» (una de una vez ya pasada). */
export function dueText(reserve: Pick<Reserve, 'next_due'>): string {
  return reserve.next_due === null ? 'Ya venció' : `Vence en ${monthPhrase(reserve.next_due)}`
}

/** Pesos escritos («3,500», «3500.50», «RD$ 3,500») a centavos; null si no es un monto válido. */
export function parsePesos(text: string): number | null {
  const clean = text.replace(/RD\$|\s/g, '').replace(/,/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  return Math.round(Number(clean) * 100)
}

/** El tope como se escribe en el campo («16500»); vacío sin tope. */
export function capInput(cents: number | null): string {
  return cents === null ? '' : String(Math.round(cents / 100))
}

/** Lo que muestra la barra: «RD$ 12,000 de RD$ 10,000» o «RD$ 4,000 · sin presupuesto». */
export function spentText(line: Pick<BudgetLine, 'spent_cents' | 'cap_cents'>): string {
  if (line.cap_cents === null) return `${formatDop(line.spent_cents)} · sin presupuesto`
  return `${formatDop(line.spent_cents)} de ${formatDop(line.cap_cents)}`
}

/** Ancho de la barra en % (0 a 100) y si pasó del tope. */
export function barShare(line: Pick<BudgetLine, 'spent_cents' | 'cap_cents'>): {
  share: number
  over: boolean
} {
  if (line.cap_cents === null) return { share: 0, over: false }
  if (line.cap_cents <= 0) {
    const spent = line.spent_cents > 0
    return { share: spent ? 100 : 0, over: spent }
  }
  const ratio = line.spent_cents / line.cap_cents
  return { share: Math.max(0, Math.min(100, Math.round(ratio * 100))), over: ratio > 1 }
}

/** Lo que va aparte de la barra: gastos únicos, lo cubierto y lo que está en US$ sin tasa. */
export function asideNotes(
  line: Pick<BudgetLine, 'one_offs_cents' | 'covered_cents' | 'without_rate'> &
    Partial<Pick<BudgetLine, 'refunds_cents'>>,
): string[] {
  const notes = []
  if (line.refunds_cents) notes.push(`devoluciones: ${formatDop(line.refunds_cents)}`)
  if (line.one_offs_cents) notes.push(`+ ${formatDop(line.one_offs_cents)} en gastos únicos`)
  if (line.covered_cents) notes.push(`${formatDop(line.covered_cents)} cubiertos por reservas`)
  if (line.without_rate) {
    const count = line.without_rate
    notes.push(count === 1 ? '1 gasto en US$ sin tasa' : `${count} gastos en US$ sin tasa`)
  }
  return notes
}

/** «Lo habitual de Delivery subió a RD$ 25,000; ¿actualizar el tope?». */
export function warningText(line: Pick<BudgetLine, 'category' | 'warning' | 'cap_cents'>): string {
  const found = line.warning
  if (!found) return ''
  const verb = found.up ? 'subió' : 'bajó'
  if (found.habitual_cents === 0) {
    return `Lo habitual de ${line.category} bajó a RD$ 0; ¿quitar el tope?`
  }
  const ask = line.cap_cents === null ? '¿poner ese tope?' : '¿actualizar el tope?'
  return `Lo habitual de ${line.category} ${verb} a ${formatDop(found.habitual_cents)}; ${ask}`
}

/** «Presupuesto: 2 categorías pasadas (+RD$ 4,800)» o «Presupuesto: todo dentro del tope»; con
 * un filtro de cuentas no se cuentan (los topes son de todas) y con datos parciales no se afirma
 * que todo está dentro. */
export function overviewText(
  overview: Pick<BudgetOverview, 'over_count' | 'over_cents'> &
    Partial<Pick<BudgetOverview, 'missing'>>,
): string {
  if (overview.over_count === null) {
    return 'Presupuesto: con filtro de cuentas no se cuentan las pasadas'
  }
  if (overview.over_count === 0) {
    return overview.missing?.length
      ? 'Presupuesto: nada pasado por ahora (datos parciales)'
      : 'Presupuesto: todo dentro del tope'
  }
  const count = overview.over_count
  const what = count === 1 ? '1 categoría pasada' : `${count} categorías pasadas`
  return `Presupuesto: ${what} (+${formatDop(overview.over_cents)})`
}

/** «después de apartar para tus reservas (RD$ 2,600/mes): RD$ 14,400»; null sin reservas o sin
 * «Te quedó». El número principal no cambia. */
export function afterReservesNote(netCents: number | null, monthlyCents: number): string | null {
  if (netCents === null || monthlyCents <= 0) return null
  return `después de apartar para tus reservas (${formatDop(monthlyCents)}/mes): ${formatDop(
    netCents - monthlyCents,
  )}`
}

/** «Este año: RD$ 3,400 de RD$ 3,500». */
export function yearText(
  reserve: Pick<Reserve, 'year_spent_cents' | 'year_estimated_cents'>,
): string {
  const spent = formatDop(reserve.year_spent_cents)
  return `Este año: ${spent} de ${formatDop(reserve.year_estimated_cents)}`
}

/** El cuerpo para crear una reserva desde una sugerencia. */
export function bodyFromSuggestion(item: ReserveSuggestion): ReserveBody {
  return {
    name: item.name,
    amount_cents: item.amount_cents,
    category_id: item.category_id,
    due_month: item.due_month,
    every_months: item.every_months,
    multiple: item.multiple,
    source: item.key,
  }
}

/** «¿Crear reserva “Diciembre: Entretenimiento” por ≈ RD$ 18,000 (vence en diciembre)?». */
export function suggestionText(item: ReserveSuggestion): string {
  return `¿Crear reserva “${item.name}” por ≈ ${formatDop(item.amount_cents)} (vence en ${monthName(
    item.due_month,
  )})?`
}

/** «3 vinculadas a «Navidad»» y, si se omitió alguna, cuántas y por qué. */
export function membersResultText(result: MembersResult, name: string): string {
  const done = result.applied.length
  const head =
    done === 0
      ? 'No se vinculó ninguna'
      : done === 1
        ? `1 vinculada a «${name}»`
        : `${done} vinculadas a «${name}»`
  if (result.skipped.length === 0) return `${head}.`
  const reasons = [...new Set(result.skipped.map((s) => s.message))].join('; ')
  const left = result.skipped.length
  const count = left === 1 ? '1 no se vinculó' : `${left} no se vincularon`
  return `${head}. ${count}: ${reasons}.`
}

/** «Datos parciales: falta el estado de VISA ···4242»; null si no falta ninguno. */
export function missingText(missing: readonly string[]): string | null {
  if (missing.length === 0) return null
  return `Datos parciales: falta el estado de ${missing.join(', ')}.`
}

/** La línea junto a los topes con un filtro de cuentas. */
export const FILTERED_NOTE = 'Topes de todas las cuentas; lo gastado, solo de las elegidas.'
