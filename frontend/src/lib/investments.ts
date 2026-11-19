// Textos, filtros y cuerpos de Inversiones (lógica pura). Las cuentas las hace el servidor
// (src/finanzas/analysis/investments.py).
import type {
  CreditRole,
  Investment,
  InvestmentEntry,
  InvestmentList,
  InvestmentStatus,
  RoleBody,
} from './api'
import { formatMoney, parseCents, ROLE_LABELS } from './links'
import { formatDop } from './money'
import { unconvertedNote } from './pending'
import { amountQuery, centsText, fold } from './picker'
import { dateRange } from './sharedList'

export const INVESTMENTS_PATH = '/inversiones'
export const EMPTY_TEXT = 'Aún no tienes inversiones'
export const EMPTY_CHOSEN_TEXT = 'Ninguna inversión en las cuentas elegidas'
export const STATUS_PARAM = 'estado'
export const QUERY_PARAM = 'q'
export const OPEN_PARAM = 'inversion'

export type Chip = 'activas' | 'cerradas' | 'todas'

/** Activas · Cerradas (también las dadas por perdidas: ya no se espera nada) · Todas. */
export const CHIPS: readonly { chip: Chip; label: string; statuses: InvestmentStatus[] | null }[] =
  [
    { chip: 'activas', label: 'Activas', statuses: ['active'] },
    { chip: 'cerradas', label: 'Cerradas', statuses: ['closed', 'written_off'] },
    { chip: 'todas', label: 'Todas', statuses: null },
  ]

const NONE_TEXT: Record<Chip, string> = {
  activas: 'Ninguna inversión activa',
  cerradas: 'Ninguna inversión cerrada',
  todas: 'Ninguna inversión',
}

export const STATUS_LABELS: Record<InvestmentStatus, string> = {
  active: 'Activa',
  closed: 'Cerrada',
  written_off: 'Dada por perdida',
}

/** El chip de la URL (`?estado=`); uno desconocido o ausente es «Activas». */
export function parseChip(value: string | null): Chip {
  return CHIPS.find((c) => c.chip === value)?.chip ?? 'activas'
}

/** La inversión desplegada de la URL (`?inversion=<id>`); null si no hay o no es un id. */
export function parseOpen(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null
  return Number(value)
}

export function noneText(chip: Chip, query: string): string {
  const q = query.trim()
  return q === '' ? NONE_TEXT[chip] : `${NONE_TEXT[chip]} coincide con «${q}»`
}

export function emptyText(filtered: boolean): string {
  return filtered ? EMPTY_CHOSEN_TEXT : EMPTY_TEXT
}

/** ¿Coincide con la búsqueda? Un monto ("300000", "300,000") coincide si alguno de sus
 * movimientos o cifras empieza por esos dígitos; si no, el texto se busca en el nombre, «Con
 * quién» y el comercio de cada movimiento (sin mayúsculas ni acentos). */
export function investmentMatches(investment: Investment, query: string): boolean {
  const amount = amountQuery(query)
  if (amount !== null) {
    const amounts = [
      ...investment.entries.map((e) => e.amount_cents),
      investment.contributed_cents,
      investment.pending_cents,
      investment.returns_cents,
    ]
    return amounts.some((c) => centsText(c).startsWith(amount))
  }
  const needle = fold(query.trim())
  if (needle === '') return true
  const texts = [
    investment.title,
    investment.name,
    investment.with_whom,
    ...investment.entries.map((e) => e.merchant),
  ]
  return texts.some((text) => fold(text).includes(needle))
}

/** Las del chip que coinciden con la búsqueda, en el orden del servidor. */
export function filterInvestments(
  all: readonly Investment[],
  chip: Chip,
  query: string,
): Investment[] {
  const statuses = CHIPS.find((c) => c.chip === chip)?.statuses ?? null
  return all.filter(
    (i) => (statuses === null || statuses.includes(i.status)) && investmentMatches(i, query),
  )
}

/** Lo que se lista y, si la desplegada al volver ya no coincide, también ella (en su lugar). */
export function withPinned(
  all: readonly Investment[],
  shown: readonly Investment[],
  pinned: number | null,
): Investment[] {
  if (pinned === null || shown.some((i) => i.id === pinned)) return [...shown]
  if (!all.some((i) => i.id === pinned)) return [...shown]
  const ids = new Set([...shown.map((i) => i.id), pinned])
  return all.filter((i) => ids.has(i.id))
}

export function chipCounts(all: readonly Investment[]): Record<Chip, number> {
  const count = (chip: Chip) => filterInvestments(all, chip, '').length
  return { activas: count('activas'), cerradas: count('cerradas'), todas: all.length }
}

/** "12.5 %" con un decimal (como los montos, con punto); "—" sin tiempo invertido. */
export function rateText(rate: number | null): string {
  if (rate === null) return '—'
  return `${(rate * 100).toFixed(1)} %`
}

/** "Pedro · desde 2 dic 2025 · último cobro 29 dic 2025": con quién (si no es el título), las
 * fechas y el último cobro. */
export function investmentMeta(investment: Investment): string {
  const who = investment.with_whom === investment.title ? '' : investment.with_whom
  const range = dateRange(investment.first_day, investment.last_activity)
  const credit = investment.last_credit
  const last = credit ? `último cobro ${dateRange(credit, credit)}` : 'sin cobros'
  return [who, range, last].filter((part) => part !== '').join(' · ')
}

export interface Stat {
  key: 'contributed' | 'returned' | 'pending' | 'returns' | 'rate'
  label: string
  value: string
}

/** Las cifras de una inversión, en su moneda. */
export function investmentStats(investment: Investment): Stat[] {
  const money = (cents: number) => formatMoney(cents, investment.currency)
  return [
    { key: 'contributed', label: 'Aportado', value: money(investment.contributed_cents) },
    { key: 'returned', label: 'Capital devuelto', value: money(investment.capital_returned_cents) },
    { key: 'pending', label: 'Por volver', value: money(investment.pending_cents) },
    { key: 'returns', label: 'Rendimientos', value: money(investment.returns_cents) },
    { key: 'rate', label: '% anual aprox.', value: rateText(investment.annual_rate) },
  ]
}

/** "Rendimiento", "Devolución de capital" o "Mixto: RD$ 50,000 de capital + RD$ 10,000". */
export function entryRole(entry: InvestmentEntry): string {
  const extra =
    entry.excess_cents > 0
      ? ` (${formatMoney(entry.excess_cents, entry.currency)} de más: rendimiento)`
      : ''
  if (entry.role !== 'mixed') return `${ROLE_LABELS[entry.role]}${extra}`
  const capital = formatMoney(entry.capital_cents, entry.currency)
  const back = formatMoney(entry.return_cents, entry.currency)
  return `Mixto: ${capital} de capital + ${back} de rendimiento${extra}`
}

/** Aviso si devolvieron más capital que lo aportado: lo de más cuenta como rendimiento. */
export function excessWarning(investment: Investment): string | null {
  if (investment.excess_cents <= 0) return null
  const extra = formatMoney(investment.excess_cents, investment.currency)
  return `Devolvieron ${extra} más de lo aportado; cuenta como rendimiento`
}

/** Aviso si algún movimiento en otra moneda no suma por falta de tasa. */
export function unconvertedWarning(investment: Investment): string | null {
  const n = investment.unconverted_count
  if (n === 0) return null
  const which = n === 1 ? 'Un movimiento no suma' : `${n} movimientos no suman`
  return `${which}: está en otra moneda y falta la tasa de su mes.`
}

export interface Figure {
  key: 'pending' | 'year' | 'active'
  label: string
  value: string
  extra: string | null
}

function activeText(n: number): string {
  return n === 1 ? '1 activa' : `${n} activas`
}

/** Las tres cifras de arriba (≈ RD$); los US$ sin tasa van aparte, sin inventar. */
export function investmentFigures(list: InvestmentList): Figure[] {
  return [
    {
      key: 'pending',
      label: 'Capital por volver',
      value: `≈ ${formatDop(list.pending_dop_cents)}`,
      extra: unconvertedNote(list.unconverted.pending_usd_cents),
    },
    {
      key: 'year',
      label: 'Rendimientos cobrados este año',
      value: `≈ ${formatDop(list.returns_year_dop_cents)}`,
      extra: unconvertedNote(list.unconverted.returns_usd_cents),
    },
    { key: 'active', label: 'Activas', value: activeText(list.active_count), extra: null },
  ]
}

/** La URL de Inversiones con el chip, la búsqueda y la desplegada (sin los vacíos ni los
 * valores por defecto), conservando los demás parámetros (las cuentas). */
export function investmentParams(
  current: URLSearchParams,
  next: { chip?: Chip; query?: string; open?: number | null },
): URLSearchParams {
  const copy = new URLSearchParams(current)
  const put = (key: string, value: string | null) => {
    if (value === null || value === '') copy.delete(key)
    else copy.set(key, value)
  }
  if (next.chip !== undefined) put(STATUS_PARAM, next.chip === 'activas' ? null : next.chip)
  if (next.query !== undefined) put(QUERY_PARAM, next.query)
  if (next.open !== undefined) put(OPEN_PARAM, next.open === null ? null : String(next.open))
  return copy
}

/** Cuerpo del tipo de un crédito, o el error que se muestra. Un mixto pide la parte de capital:
 * mayor que 0 y menor que el crédito (el resto es rendimiento). */
export function roleBody(
  role: CreditRole,
  capital: string,
  amountCents: number,
): { body: RoleBody } | { error: string } {
  if (role !== 'mixed') return { body: { role } }
  const cents = parseCents(capital)
  if (cents === null) return { error: 'Pon la parte de capital: un monto mayor que 0' }
  if (cents >= amountCents) {
    return { error: 'La parte de capital tiene que ser menor que el crédito' }
  }
  return { body: { role, capital_cents: cents } }
}

/** «de eso, RD$ X fueron a inversiones»; null sin aportes en el mes. */
export function investedNote(investedCents: number): string | null {
  if (investedCents <= 0) return null
  return `de eso, ${formatDop(investedCents)} fueron a inversiones`
}
