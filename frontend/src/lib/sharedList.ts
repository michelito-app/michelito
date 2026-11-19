// Textos y filtros de Compartidos (todos los grupos compartidos). Puros.
import type {
  SharedList,
  SharedListExpense,
  SharedListGroup,
  SharedListRefund,
  SharedStatus,
} from './api'
import { expenseCount, formatMoney, moneyList } from './links'
import { formatDop } from './money'
import { shortDay } from './months'
import { unconvertedNote } from './pending'
import { amountQuery, centsText, fold } from './picker'

export const SHARED_PATH = '/compartidos'
export const EMPTY_TEXT = 'Aún no tienes gastos compartidos'
export const EMPTY_CHOSEN_TEXT = 'Ningún grupo en las cuentas elegidas'
export const STATUS_PARAM = 'estado'
export const QUERY_PARAM = 'q'
export const GROUP_PARAM = 'grupo'

export type Chip = 'todos' | 'pendiente' | 'saldados' | 'perdidos'

export const CHIPS: readonly { chip: Chip; label: string; status: SharedStatus | null }[] = [
  { chip: 'todos', label: 'Todos', status: null },
  { chip: 'pendiente', label: 'Con pendiente', status: 'pending' },
  { chip: 'saldados', label: 'Saldados', status: 'settled' },
  { chip: 'perdidos', label: 'Perdidos', status: 'written_off' },
]

const NONE_TEXT: Record<Chip, string> = {
  todos: 'Ningún grupo',
  pendiente: 'Ningún grupo con pendiente',
  saldados: 'Ningún grupo saldado',
  perdidos: 'Ningún grupo perdido',
}

/** El chip de la URL (`?estado=`); uno desconocido o ausente es «Todos». */
export function parseChip(value: string | null): Chip {
  return CHIPS.find((c) => c.chip === value)?.chip ?? 'todos'
}

/** El grupo desplegado de la URL (`?grupo=<id>`); null si no hay o no es un id. */
export function parseGroup(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null
  return Number(value)
}

/** Lo que dice la lista cuando el chip o la búsqueda la dejan vacía. */
export function noneText(chip: Chip, query: string): string {
  const q = query.trim()
  return q === '' ? NONE_TEXT[chip] : `${NONE_TEXT[chip]} coincide con «${q}»`
}

function amounts(group: SharedListGroup): number[] {
  return [
    ...group.expenses.map((e) => e.amount_cents),
    ...group.refunds.map((r) => r.amount_cents),
    ...[...group.paid, ...group.pending, ...group.reimbursed].map((p) => p.cents),
  ]
}

/** ¿El grupo coincide con la búsqueda? Un monto (como en los selectores: "1000", "1,000",
 * "US$ 29.75") coincide si alguno de sus montos (gastos, reembolsos, pagado, devuelto o
 * pendiente) empieza por esos dígitos; si no, el texto se busca en el nombre, «Con quién» y el
 * comercio de cada gasto (sin distinguir mayúsculas ni acentos). */
export function groupMatches(group: SharedListGroup, query: string): boolean {
  const amount = amountQuery(query)
  if (amount !== null) return amounts(group).some((c) => centsText(c).startsWith(amount))
  const needle = fold(query.trim())
  if (needle === '') return true
  const texts = [group.title, group.name, group.with_whom, ...group.expenses.map((e) => e.merchant)]
  return texts.some((text) => fold(text).includes(needle))
}

/** Los grupos del chip que coinciden con la búsqueda, en el orden del servidor. */
export function filterGroups(
  groups: readonly SharedListGroup[],
  chip: Chip,
  query: string,
): SharedListGroup[] {
  const status = CHIPS.find((c) => c.chip === chip)?.status ?? null
  return groups.filter((g) => (status === null || g.status === status) && groupMatches(g, query))
}

/** Lo que se ve sin ningún grupo: con todas las cuentas, que aún no hay compartidos; con
 * cuentas elegidas, que ninguno es de ellas. */
export function emptyText(filtered: boolean): string {
  return filtered ? EMPTY_CHOSEN_TEXT : EMPTY_TEXT
}

/** Lo que se lista: los grupos filtrados y, si el grupo `pinned` (el desplegado al volver de su
 * pantalla) ya no coincide con el chip o la búsqueda, también él, en su lugar del orden del
 * servidor (su fila dice su estado actual), para no perder el contexto. */
export function withPinned(
  all: readonly SharedListGroup[],
  shown: readonly SharedListGroup[],
  pinned: number | null,
): SharedListGroup[] {
  if (pinned === null || shown.some((g) => g.id === pinned)) return [...shown]
  if (!all.some((g) => g.id === pinned)) return [...shown]
  const ids = new Set([...shown.map((g) => g.id), pinned])
  return all.filter((g) => ids.has(g.id))
}

/** Cuántos grupos hay de cada chip (para mostrarlo junto a su nombre). */
export function chipCounts(groups: readonly SharedListGroup[]): Record<Chip, number> {
  const count = (status: SharedStatus) => groups.filter((g) => g.status === status).length
  return {
    todos: groups.length,
    pendiente: count('pending'),
    saldados: count('settled'),
    perdidos: count('written_off'),
  }
}

export interface StatusText {
  main: string // "Te deben US$ 29.75", "Saldado" o "Dado por perdido"
  approx: string | null // "≈ RD$ 1,845" si hay US$ pendientes con tasa; sin tasa, la nota
}

/** El estado del grupo: lo que te deben (por moneda y, con US$, ≈ RD$ como Pendientes), o si
 * está saldado o dado por perdido. */
export function statusText(group: SharedListGroup): StatusText {
  if (group.status === 'settled') return { main: 'Saldado', approx: null }
  if (group.status === 'written_off') return { main: 'Dado por perdido', approx: null }
  const main = `Te deben ${moneyList(group.pending)}`
  // US$ sin ninguna tasa: se dice en vez de inventar el equivalente (como Pendientes).
  const unconverted = unconvertedNote(group.unconverted_usd_cents)
  if (unconverted !== null) return { main, approx: unconverted }
  const usd = group.pending.some((p) => p.currency === 'USD')
  const dop = group.pending_dop_cents
  return { main, approx: usd && dop !== null ? `≈ ${formatDop(dop)}` : null }
}

/** "Te devolvieron RD$ 300 de más" si sobró tras saldar todo; si no, null. */
export function excessText(group: SharedListGroup): string | null {
  return group.excess.length ? `Te devolvieron ${moneyList(group.excess)} de más` : null
}

function dayWithYear(iso: string): string {
  return `${shortDay(iso)} ${iso.slice(0, 4)}`
}

/** Fechas de los gastos: "20 dic 2025", "3 feb – 7 feb 2026" o, entre años,
 * "18 dic 2025 – 9 ene 2026". */
export function dateRange(first: string, last: string): string {
  if (first === last) return dayWithYear(first)
  if (first.slice(0, 4) === last.slice(0, 4)) return `${shortDay(first)} – ${dayWithYear(last)}`
  return `${dayWithYear(first)} – ${dayWithYear(last)}`
}

/** "Luis · 2 gastos · 3 feb – 7 feb 2026": con quién (si no es ya el título), cuántos gastos
 * y sus fechas. */
export function groupMeta(group: SharedListGroup): string {
  const who = group.with_whom === group.title ? '' : group.with_whom
  const range = dateRange(group.first_day, group.last_day)
  const parts = [who, expenseCount(group.expenses.length), range]
  return parts.filter((part) => part !== '').join(' · ')
}

/** "Pagaste RD$ 4,350 · te devolvieron RD$ 2,175" (o "· nada devuelto"). */
export function moneyLine(group: SharedListGroup): string {
  const back = group.reimbursed.length
    ? `te devolvieron ${moneyList(group.reimbursed)}`
    : 'nada devuelto'
  return `Pagaste ${moneyList(group.paid)} · ${back}`
}

/** El estado de un gasto del grupo: "Saldado", "Pendiente RD$ 2,000" o "Dado por perdido". */
export function expenseState(expense: SharedListExpense): string {
  if (expense.written_off_cents > 0) return 'Dado por perdido'
  if (expense.pending_cents === 0) return 'Saldado'
  return `Pendiente ${formatMoney(expense.pending_cents, expense.currency)}`
}

/** De dónde vino un reembolso: "TOKE DE ANA · Corriente ···2" o
 * "A mano · Marta · efectivo". */
export function refundLabel(refund: SharedListRefund): string {
  if (!refund.manual) {
    return [refund.description, refund.account_label].filter((p) => p !== '').join(' · ')
  }
  const where = refund.account_label === '' ? 'efectivo' : refund.account_label
  return ['A mano', refund.description, where].filter((p) => p !== '').join(' · ')
}

export interface Figure {
  key: 'owed' | 'year' | 'open'
  label: string
  value: string
  extra: string | null
}

function groupsText(n: number): string {
  return n === 1 ? '1 grupo abierto' : `${n} grupos abiertos`
}

/** Las tres cifras de arriba: te deben (como Pendientes), lo devuelto este año y cuántos
 * grupos siguen abiertos. Los US$ sin tasa van aparte, sin inventar. */
export function sharedFigures(list: SharedList): Figure[] {
  return [
    {
      key: 'owed',
      label: 'Te deben',
      value: `≈ ${formatDop(list.owed_dop_cents)}`,
      extra: unconvertedNote(list.unconverted.owed_usd_cents),
    },
    {
      key: 'year',
      label: 'Te devolvieron este año',
      value: `≈ ${formatDop(list.reimbursed_year_dop_cents)}`,
      extra: unconvertedNote(list.unconverted.reimbursed_usd_cents),
    },
    { key: 'open', label: 'Abiertos', value: groupsText(list.open_count), extra: null },
  ]
}

/** La URL de Compartidos con el chip, la búsqueda y el grupo desplegado (sin los vacíos ni
 * los valores por defecto), conservando los demás parámetros (las cuentas). */
export function sharedParams(
  current: URLSearchParams,
  next: { chip?: Chip; query?: string; group?: number | null },
): URLSearchParams {
  const copy = new URLSearchParams(current)
  const put = (key: string, value: string | null) => {
    if (value === null || value === '') copy.delete(key)
    else copy.set(key, value)
  }
  if (next.chip !== undefined) put(STATUS_PARAM, next.chip === 'todos' ? null : next.chip)
  if (next.query !== undefined) put(QUERY_PARAM, next.query)
  if (next.group !== undefined) put(GROUP_PARAM, next.group === null ? null : String(next.group))
  return copy
}
