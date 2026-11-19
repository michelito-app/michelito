// Textos y agrupación de la pantalla Recurrentes (API: GET /api/recurring).
import type {
  AlertKind,
  GroupTotal,
  MarkBody,
  MarkStatus,
  Recurring,
  RecurringGroupKey,
  RecurringItem,
  TxRecurringBody,
} from './api'
import { formatDop, formatUsd } from './money'
import { monthName, shortDay } from './months'

export type AlertTone = 'up' | 'neutral'
export type BadgeTone = AlertTone | 'positive' | 'muted'

export const MAX_INSTALLMENTS = 600

/** Los grupos que se pueden elegir a mano, en el orden de la pantalla (Cuotas no: lo pone
 * tener cuotas anotadas). */
export const GROUP_OPTIONS: { key: RecurringGroupKey; label: string }[] = [
  { key: 'vivienda', label: 'Vivienda' },
  { key: 'prestamos', label: 'Préstamos' },
  { key: 'servicios', label: 'Servicios' },
  { key: 'seguros', label: 'Seguros' },
  { key: 'suscripciones', label: 'Suscripciones' },
  { key: 'cargos', label: 'Cargos del banco' },
  { key: 'otros', label: 'Otros recurrentes' },
]
const LOANS_GROUP: RecurringGroupKey = 'prestamos'

const STATUS_BADGE: Record<RecurringItem['status'], string | null> = {
  activo: null,
  inactivo: 'Inactivo',
  cancelado: 'Cancelado',
  terminado: 'Terminado',
}
const UP_BADGES = new Set(['Subió', 'Te volvieron a cobrar'])
const MUTED_BADGES = new Set(['Inactivo', 'Cancelado', 'Terminado'])

function inCurrency(cents: number, currency: string): string {
  return currency === 'USD' ? formatUsd(cents) : formatDop(cents)
}

/** Insignias de la fila, de la más urgente a la más tranquila. `month` ("YYYY-MM") es el mes
 * con el que se deciden "Nuevo" y "Subió" (null para no marcar ninguno); `firstMonth` es el del
 * primer movimiento, donde nada es nuevo. Solo los activos las llevan. */
export function badgesOf(
  item: RecurringItem,
  month: string | null,
  firstMonth: string | null = null,
): string[] {
  const change = item.price_change
  const left = item.installments_left
  const status = STATUS_BADGE[item.status]
  const active = item.status === 'activo'
  const rose =
    active &&
    month !== null &&
    change !== null &&
    change.after_cents > change.before_cents &&
    change.day.slice(0, 7) === month
  const isNew =
    active && month !== null && month !== firstMonth && item.first_day.slice(0, 7) === month
  return [
    item.charged_after_cancel ? 'Te volvieron a cobrar' : null,
    rose ? 'Subió' : null,
    isNew ? 'Nuevo' : null,
    item.variable ? 'Variable' : null,
    left !== null && left > 0 ? installmentsText(left, item.group_key === LOANS_GROUP) : null,
    status,
  ].filter((badge): badge is string => badge !== null)
}

/** "3 cuotas restantes"; en un préstamo, "quedan 3". */
function installmentsText(left: number, loan = false): string {
  if (loan) return `quedan ${left}`
  return `${left} ${left === 1 ? 'cuota restante' : 'cuotas restantes'}`
}

/** Tono de una insignia de `badgesOf`. */
export function badgeTone(badge: string): BadgeTone {
  if (UP_BADGES.has(badge)) return 'up'
  if (MUTED_BADGES.has(badge)) return 'muted'
  if (/cuotas? restantes?$/.test(badge) || /^quedan \d+$/.test(badge)) return 'positive'
  return 'neutral'
}

/** Tono de un aviso del mes: subidas y cobros tras cancelar llaman la atención. */
export function alertTone(kind: AlertKind): AlertTone {
  return kind === 'nuevo' ? 'neutral' : 'up'
}

export function cadenceText(item: RecurringItem): string {
  return item.cadence
}

/** "2025-12-05" → "desde dic 25". */
export function sinceText(item: RecurringItem): string {
  const month = item.first_day.slice(0, 7)
  return `desde ${monthName(month).slice(0, 3)} ${month.slice(2, 4)}`
}

/** "2026-02-05" → "último cobro 5 feb". */
export function lastChargeText(item: RecurringItem): string {
  return `último cobro ${shortDay(item.last_day)}`
}

export interface CostLines {
  main: string
  detail: string
}

/** Costo mensual en RD$ y, debajo, el cobro original cuando dice algo más. */
export function costLines(item: RecurringItem): CostLines {
  const yearly = item.cadence === 'anual'
  if (item.monthly_cents === null) {
    const monthly = yearly ? Math.round(item.typical_cents / 12) : item.typical_cents
    return {
      main: inCurrency(monthly, item.currency),
      detail: 'al mes · sin tasa',
    }
  }
  const main = formatDop(item.monthly_cents)
  if (yearly)
    return {
      main,
      detail: `${inCurrency(item.typical_cents, item.currency)} al año`,
    }
  if (item.currency === 'USD') {
    return { main, detail: `${formatUsd(item.typical_cents)} al mes` }
  }
  return { main, detail: item.variable ? 'promedio al mes' : 'al mes' }
}

/** Préstamos: "abonos extra este año: RD$ 50,000" (null si no hubo). */
export function extrasText(
  item: Pick<RecurringItem, 'extras_year_cents' | 'currency'>,
): string | null {
  if (item.extras_year_cents <= 0) return null
  return `abonos extra este año: ${inCurrency(item.extras_year_cents, item.currency)}`
}

/** Los comercios de la serie cuando no es uno solo con su mismo nombre: "LUZ PAGO, LUZ WB". */
export function membersText(item: Pick<RecurringItem, 'members' | 'name'>): string | null {
  if (item.members.length === 1 && item.members[0] === item.name) return null
  return item.members.join(', ')
}

export interface JoinTarget {
  key: string
  name: string
}

/** Con qué se puede unir un recurrente: los demás de la pantalla (sin repetir la clave de otra
 * moneda) y los proveedores de la lista que no estén ya, por nombre. */
export function joinTargets(overview: Recurring, item: RecurringItem): JoinTarget[] {
  const found = new Map<string, string>()
  for (const other of [...overview.items, ...overview.dismissed]) {
    if (other.merchant !== item.merchant) found.set(other.merchant, other.name)
  }
  for (const provider of overview.providers) {
    if (provider.key !== item.merchant && !found.has(provider.key))
      found.set(provider.key, provider.name)
  }
  return [...found]
    .map(([key, name]) => ({ key, name }))
    .sort((a, b) => a.name.localeCompare(b.name, 'es'))
}

/** Cuerpo de «Es recurrente…»: el grupo y las cuotas solo si se eligieron. */
export function txRecurringBody(
  cadence: TxRecurringBody['cadence'],
  group: RecurringGroupKey | '',
  installments: number | null,
): TxRecurringBody {
  return {
    cadence,
    ...(group === '' ? {} : { group }),
    ...(installments === null ? {} : { installments_left: installments }),
  }
}

/** "RD$ 3,264 al mes · RD$ 39,165 al año". */
export function totalLine(monthlyCents: number, yearlyCents: number): string {
  return `${formatDop(monthlyCents)} al mes · ${formatDop(yearlyCents)} al año`
}

export interface Section {
  group: string
  /** null cuando el grupo no tiene ningún cargo activo. */
  total: GroupTotal | null
  items: RecurringItem[]
}

/** Grupos en el orden en que llegan de la API; dentro de cada uno, los activos primero
 * (inactivos, cancelados y terminados al final, en su orden). */
export function sections(overview: Recurring): Section[] {
  const groups = [...new Set(overview.items.map((i) => i.group))]
  return groups.map((group) => {
    const members = overview.items.filter((i) => i.group === group)
    return {
      group,
      total: overview.groups.find((g) => g.group === group) ?? null,
      items: [
        ...members.filter((i) => i.status === 'activo'),
        ...members.filter((i) => i.status !== 'activo'),
      ],
    }
  })
}

/** Cambia la marca sin tocar las cuotas (no se manda `installments_left`). */
export function statusBody(item: RecurringItem, status: MarkStatus | null): MarkBody {
  return { merchant: item.merchant, currency: item.currency, status }
}

/** Anota (o borra, con null) las cuotas restantes y conserva la marca actual. */
export function installmentsBody(item: RecurringItem, left: number | null): MarkBody {
  return { ...statusBody(item, item.mark), installments_left: left }
}

/** Elige el grupo a mano ('' vuelve al de la categoría) y conserva la marca actual. */
export function groupBody(item: RecurringItem, group: RecurringGroupKey | ''): MarkBody {
  return { ...statusBody(item, item.mark), group: group === '' ? null : group }
}

/** Los comercios que se pueden «Separar»: todos menos el que da nombre a la serie (el destino
 * de una unión no se separa de sí mismo). */
export function separableMembers(item: Pick<RecurringItem, 'members' | 'merchant'>): string[] {
  if (item.members.length < 2) return []
  return item.members.filter((member) => member !== item.merchant)
}

/** Entero de 0 a 600, o null si el texto no lo es. */
export function parseInstallments(text: string): number | null {
  const trimmed = text.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const value = Number(trimmed)
  return value <= MAX_INSTALLMENTS ? value : null
}

export interface UpcomingCharge {
  item: RecurringItem
  /** Fecha esperada del próximo cobro ("YYYY-MM-DD"). */
  day: string
}

/** Tope de pasos al estimar (100 años de cobros mensuales). */
const MAX_STEPS = 1200

type ChargeDates = Pick<RecurringItem, 'first_day' | 'last_day' | 'cadence'>

function monthEnd(year: number, index: number): number {
  return new Date(Date.UTC(year, index + 1, 0)).getUTCDate()
}

/** Día del mes en que suele cobrar: el del último cobro, salvo que ese caiga en el fin de un mes
 * corto y la serie empezara un día más tarde (un cobro del 31 que en febrero fue el 28). */
export function typicalDay(item: Pick<RecurringItem, 'first_day' | 'last_day'>): number {
  const [year, month, last] = item.last_day.split('-').map(Number)
  const first = Number(item.first_day.slice(8, 10))
  return last === monthEnd(year, month - 1) && first > last ? first : last
}

/** El próximo cobro estimado desde `today` ("YYYY-MM-DD"): el último más un mes (o un año) en su
 * día típico, sin pasarse del fin de mes, y tantas veces como haga falta para no quedar antes de
 * hoy. */
export function nextChargeDay(item: ChargeDates, today: string): string {
  const [year, month] = item.last_day.split('-').map(Number)
  const day = typicalDay(item)
  const step = item.cadence === 'anual' ? 12 : 1
  // Meses desde enero del año 0, para avanzar sin pelear con los cambios de año.
  let at = year * 12 + month - 1
  let candidate = item.last_day
  for (let steps = 0; steps < MAX_STEPS; steps += 1) {
    at += step
    const [y, index] = [Math.floor(at / 12), at % 12]
    candidate = new Date(Date.UTC(y, index, Math.min(day, monthEnd(y, index))))
      .toISOString()
      .slice(0, 10)
    if (candidate >= today) break
  }
  return candidate
}

/** Los `count` cobros activos más próximos desde `today`, del más cercano al más lejano. */
export function upcomingCharges(
  items: readonly RecurringItem[],
  today: string,
  count = 3,
): UpcomingCharge[] {
  return items
    .filter((item) => item.status === 'activo')
    .map((item) => ({ item, day: nextChargeDay(item, today) }))
    .sort((a, b) => a.day.localeCompare(b.day) || a.item.merchant.localeCompare(b.item.merchant))
    .slice(0, count)
}

/** Monto típico de un cobro en su moneda: "US$ 11.99", "RD$ 2,500". */
export function chargeText(item: Pick<RecurringItem, 'typical_cents' | 'currency'>): string {
  return inCurrency(item.typical_cents, item.currency)
}

/** Nota de la tarjeta del Resumen cuando no hay avisos que mostrar; null si los hay. */
export function cardNote(overview: Recurring): string | null {
  if (overview.items.length === 0) return 'Sin cargos recurrentes detectados'
  return overview.alerts.length === 0 ? 'Sin cambios este mes' : null
}
