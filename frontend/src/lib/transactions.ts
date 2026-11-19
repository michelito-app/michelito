// Filtros, agrupación y ediciones de la pantalla Transacciones (lógica pura).
import type { EditBody, Kind, Transactions, Tx } from './api'
import { ACCOUNTS_PARAM, selectionFromParams } from './accountFilter'
import { canonicalCategory } from './categories'
import { formatDop, formatSignedDop, formatUsd } from './money'
import { monthName } from './months'

/** Cómo se agrupa la lista: por día (lo de siempre), por categoría o por comercio. */
export type GroupBy = 'day' | 'category' | 'merchant'

/** Orden de las filas dentro de cada grupo: el de la API (fecha) o mayor monto primero. */
export type SortBy = 'date' | 'amount'

/** Filtros tal como viven en la URL: `mes`, `cuentas` (claves separadas por coma; también se
 * lee la `cuenta` de antes), `categoria`, `q`, `tx` (la huella),
 * `tipo` (gastos, ingresos o transferencias), `agrupar` y `orden`. Los dos últimos no
 * recortan la lista, solo la presentan distinto. */
export interface TxFilters {
  month: string | null
  accounts: readonly string[] | null // null: todas
  category: string | null
  q: string
  tx: string | null
  kind: Kind | null
  group: GroupBy
  sort: SortBy
  shared: SharedFilter | null // `compartidos=pendientes`: gastos compartidos con pendiente
}

/** Filtro de gastos compartidos: solo los que tienen algo pendiente ("te deben"). */
export type SharedFilter = 'pending'
export const SHARED_PENDING_PARAM = 'pendientes'

/** Opciones de "Agrupar por"; el día no va en la URL. */
export const GROUP_OPTIONS: readonly { param: string | null; group: GroupBy; label: string }[] = [
  { param: null, group: 'day', label: 'Día' },
  { param: 'categoria', group: 'category', label: 'Categoría' },
  { param: 'comercio', group: 'merchant', label: 'Comercio' },
]

/** Opciones de "Ordenar"; la fecha no va en la URL. */
export const SORT_OPTIONS: readonly { param: string | null; sort: SortBy; label: string }[] = [
  { param: null, sort: 'date', label: 'Fecha' },
  { param: 'monto', sort: 'amount', label: 'Monto (mayor primero)' },
]

/** Opciones del filtro "Tipo": valor en la URL, tipo de la API y etiqueta. */
export const KIND_OPTIONS: readonly { param: string; kind: Kind; label: string }[] = [
  { param: 'gastos', kind: 'gasto', label: 'Gastos' },
  { param: 'ingresos', kind: 'ingreso', label: 'Ingresos' },
  { param: 'transferencias', kind: 'transferencia', label: 'Transferencias' },
]

/** Filtros que recortan la lista (los que van a la API además del mes). */
export type ListFilters = Pick<TxFilters, 'accounts' | 'category' | 'q' | 'kind' | 'shared'>

export type Scope = NonNullable<EditBody['scope']>

/** Lo que el usuario tiene elegido en el panel de detalle. */
export interface Draft {
  category: string
  oneOff: boolean
  scope: Scope
  note: string
}

export interface DayGroup {
  day: string
  label: string
  items: Tx[]
}

const PARAM = {
  month: 'mes',
  accounts: ACCOUNTS_PARAM,
  category: 'categoria',
  q: 'q',
  tx: 'tx',
  kind: 'tipo',
  group: 'agrupar',
  sort: 'orden',
  shared: 'compartidos',
} as const

function groupOf(param: string | null): GroupBy {
  return GROUP_OPTIONS.find((o) => o.param !== null && o.param === param)?.group ?? 'day'
}

function sortOf(param: string | null): SortBy {
  return SORT_OPTIONS.find((o) => o.param !== null && o.param === param)?.sort ?? 'date'
}

function kindOf(param: string | null): Kind | null {
  return KIND_OPTIONS.find((o) => o.param === param)?.kind ?? null
}

function kindParam(kind: Kind | null): string | null {
  return KIND_OPTIONS.find((o) => o.kind === kind)?.param ?? null
}

function value(params: URLSearchParams, key: string): string | null {
  const text = params.get(key)?.trim() ?? ''
  return text === '' ? null : text
}

function optional(text: string | null, map: (text: string) => string): string | null {
  return text === null ? null : map(text)
}

/** Lee los filtros de la URL; lo vacío cuenta como ausente. Una categoría renombrada se lee
 * con su nombre actual. */
export function parseFilters(params: URLSearchParams): TxFilters {
  return {
    month: value(params, PARAM.month),
    accounts: selectionFromParams(params),
    category: optional(value(params, PARAM.category), canonicalCategory),
    q: value(params, PARAM.q) ?? '',
    tx: value(params, PARAM.tx),
    kind: kindOf(value(params, PARAM.kind)),
    group: groupOf(value(params, PARAM.group)),
    sort: sortOf(value(params, PARAM.sort)),
    shared: value(params, PARAM.shared) === SHARED_PENDING_PARAM ? 'pending' : null,
  }
}

function paramText(filters: TxFilters, key: keyof TxFilters): string | null {
  switch (key) {
    case 'kind':
      return kindParam(filters.kind)
    case 'group':
      return GROUP_OPTIONS.find((o) => o.group === filters.group)?.param ?? null
    case 'sort':
      return SORT_OPTIONS.find((o) => o.sort === filters.sort)?.param ?? null
    case 'accounts':
      return filters.accounts === null ? null : filters.accounts.join(',')
    case 'shared':
      return filters.shared === 'pending' ? SHARED_PENDING_PARAM : null
    default:
      return filters[key]
  }
}

/** Los filtros como parámetros de URL, sin los vacíos ni los valores por defecto. */
export function toParams(filters: TxFilters): URLSearchParams {
  const params = new URLSearchParams()
  for (const key of Object.keys(PARAM) as (keyof TxFilters)[]) {
    const text = paramText(filters, key)?.trim()
    if (text) params.set(PARAM[key], text)
  }
  return params
}

/** ¿Hay algo que recorte la lista además del mes? */
export function hasNarrowing(filters: TxFilters): boolean {
  return (
    filters.accounts !== null ||
    filters.category !== null ||
    filters.kind !== null ||
    filters.shared !== null ||
    filters.q.trim() !== ''
  )
}

/** Quita cuentas, categoría, tipo, compartidos y búsqueda; conserva el mes, la fila elegida, la
 * agrupación y el orden. */
export function clearFilters(filters: TxFilters): TxFilters {
  return { ...filters, accounts: null, category: null, q: '', kind: null, shared: null }
}

/** Ruta de /api/transactions con los filtros puestos. */
export function apiPath(month: string, filters: ListFilters): string {
  const params = new URLSearchParams({ month })
  if (filters.accounts) params.set('accounts', filters.accounts.join(','))
  if (filters.category) params.set('category', filters.category)
  if (filters.q.trim()) params.set('q', filters.q.trim())
  if (filters.kind) params.set('kind', filters.kind)
  if (filters.shared) params.set('shared', filters.shared)
  return `/api/transactions?${params}`
}

const WEEKDAYS = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']

/** "2026-09-26" → "Sábado 26 de septiembre". */
export function dayLabel(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()]
  return `${weekday} ${day} de ${monthName(iso.slice(0, 7))}`
}

/** Agrupa filas seguidas del mismo día; la API ya las manda de la más nueva a la más vieja. */
export function groupByDay(items: Tx[]): DayGroup[] {
  return items.reduce<DayGroup[]>((groups, item) => {
    const last = groups[groups.length - 1]
    if (last && last.day === item.day) {
      return [...groups.slice(0, -1), { ...last, items: [...last.items, item] }]
    }
    return [...groups, { day: item.day, label: dayLabel(item.day), items: [item] }]
  }, [])
}

/** Valor para ordenar por monto: el absoluto en RD$; sin tasa no se compara y va al final. */
function amountKey(tx: Tx): number {
  return tx.amount_dop_cents === null ? -1 : Math.abs(tx.amount_dop_cents)
}

/** Filas en el orden pedido. Por fecha es el de la API (de la más nueva a la más vieja); por
 * monto, mayor primero, y a igual monto se conserva el de la API. No toca la lista recibida. */
export function sortItems(items: Tx[], sort: SortBy): Tx[] {
  if (sort === 'date') return items
  return [...items].sort((a, b) => amountKey(b) - amountKey(a))
}

/** Grupos por día; con orden por monto, ordena dentro de cada día. */
export function dayGroups(items: Tx[], sort: SortBy): DayGroup[] {
  const groups = groupByDay(items)
  return sort === 'date' ? groups : groups.map((g) => ({ ...g, items: sortItems(g.items, sort) }))
}

/** Totales de unas filas con las mismas reglas que /api/transactions para el encabezado. */
export function totalsOf(items: Tx[]): Transactions {
  const spent = items.filter((t) => t.kind === 'gasto')
  const sum = (rows: Tx[]) => rows.reduce((total, t) => total + (t.amount_dop_cents ?? 0), 0)
  return {
    items,
    count: items.length,
    total_cents: sum(spent),
    income_cents: -sum(items.filter((t) => t.kind === 'ingreso')),
    unconverted_usd_cents: spent
      .filter((t) => t.amount_dop_cents === null)
      .reduce((total, t) => total + t.amount_cents, 0),
  }
}

/** Grupo de la vista por categoría o por comercio, con sus totales. */
export interface FieldGroup {
  key: string
  items: Tx[]
  totals: Transactions
}

/** Lo que se ordena para poner primero los grupos de más gasto (a igual gasto en RD$, el que
 * tiene más US$ sin tasa): luego los de más ingresos y, entre los que no tienen ninguno
 * (transferencias), los de más dinero movido. */
function groupRank(totals: Transactions): number[] {
  const moved = totals.items.reduce((total, t) => total + Math.abs(t.amount_dop_cents ?? 0), 0)
  return [totals.total_cents, totals.unconverted_usd_cents, totals.income_cents, moved]
}

function compareRanks(a: number[], b: number[]): number {
  const index = a.findIndex((value, i) => value !== b[i])
  return index === -1 ? 0 : b[index] - a[index]
}

/** Agrupa por categoría o comercio, de mayor a menor total; las filas siguen el orden pedido. */
export function fieldGroups(items: Tx[], field: 'category' | 'merchant', sort: SortBy): FieldGroup[] {
  // Acumulador local: no sale de la función, así que se llena en el lugar.
  const byKey = new Map<string, Tx[]>()
  for (const t of items) {
    const rows = byKey.get(t[field])
    if (rows) rows.push(t)
    else byKey.set(t[field], [t])
  }
  return [...byKey.entries()]
    .map(([key, rows]) => ({ key, items: sortItems(rows, sort), totals: totalsOf(rows) }))
    .sort((a, b) => compareRanks(groupRank(a.totals), groupRank(b.totals)))
}

/** "3 transacciones · RD$ 2,150 · ingresos RD$ 500": lo mismo que el encabezado, por grupo. */
export function groupLine(group: FieldGroup): string {
  const parts = totalsParts(group.totals)
  return [parts.count, parts.total, parts.income, parts.unconverted].filter(Boolean).join(' · ')
}

/** Cuerpo del PATCH con solo lo que cambió; `null` si no hay nada que guardar.
 * Con alcance de comercio se manda la categoría aunque no cambie: crea la regla. */
export function editBody(tx: Tx, draft: Draft): EditBody | null {
  const categoryChanged = draft.category !== tx.category
  const sendCategory = categoryChanged || draft.scope === 'merchant'
  const oneOffChanged = draft.oneOff !== tx.one_off
  const noteChanged = draft.note.trim() !== tx.note
  if (!sendCategory && !oneOffChanged && !noteChanged) return null
  return {
    ...(sendCategory && { category: draft.category }),
    ...(oneOffChanged && { one_off: draft.oneOff }),
    ...(noteChanged && { note: draft.note.trim() }),
    scope: draft.scope,
  }
}

/** Largo máximo de una nota (como el servidor). */
export const NOTE_MAX = 500

/** "6 compras en 2026": compras del comercio en el año de la transacción. */
export function historyText(tx: Tx): string {
  const count = tx.merchant_year_count
  return `${count} ${count === 1 ? 'compra' : 'compras'} en ${tx.day.slice(0, 4)}`
}

/** Detalle de la opción "Todo el comercio": un crédito no cuenta compras. */
export function merchantScopeNote(tx: Tx): string {
  return tx.amount_cents < 0 ? 'también a futuro' : `${historyText(tx)}, también a futuro`
}

/** Insignia de gasto único: marcado por el usuario, o sugerido y aún sin decidir. */
export function oneOffBadge(tx: Tx): 'Único' | '¿Único?' | null {
  if (tx.one_off) return 'Único'
  return tx.suggested_one_off ? '¿Único?' : null
}

/** Acción de sugerencia en el detalle: descartar ("No es único") lo sugerido o deshacer un
 * descarte ("Volver a sugerir"). Nada si ya está marcado como gasto único. */
export function oneOffAction(tx: Tx): 'dismiss' | 'restore' | null {
  if (tx.one_off) return null
  if (tx.one_off_dismissed) return 'restore'
  return tx.suggested_one_off ? 'dismiss' : null
}

export interface TotalsParts {
  count: string
  total: string | null // null si la lista no tiene gastos (p. ej. solo ingresos)
  income: string | null
  unconverted: string | null
}

/** Piezas del encabezado: "9 transacciones · RD$ 30,745 · ingresos RD$ 97,000 · US$ 11.99 sin
 * tasa". El total es solo de gastos. */
export function totalsParts(data: Transactions): TotalsParts {
  return {
    count: `${data.count} ${data.count === 1 ? 'transacción' : 'transacciones'}`,
    total:
      data.items.length === 0 || data.items.some((t) => t.kind === 'gasto')
        ? formatDop(data.total_cents)
        : null,
    income: data.income_cents > 0 ? `ingresos ${formatDop(data.income_cents)}` : null,
    unconverted:
      data.unconverted_usd_cents > 0 ? `${formatUsd(data.unconverted_usd_cents)} sin tasa` : null,
  }
}

export interface AmountLines {
  main: string
  original: string | null
  credit: boolean // devolución de un gasto
}

/** Tono del monto: ingreso (verde), devolución (crédito) o neutro (gastos y transferencias). */
export type AmountTone = 'income' | 'credit' | 'plain'

export function amountTone(tx: Tx): AmountTone {
  if (tx.kind === 'ingreso') return 'income'
  return tx.kind === 'gasto' && tx.amount_cents < 0 ? 'credit' : 'plain'
}

/** El dinero que entra se muestra en positivo: los créditos llegan con signo negativo. */
function signedUsd(cents: number): string {
  const text = formatUsd(-cents)
  return cents <= 0 ? `+${text}` : text
}

/** Monto de una fila: en RD$ (o US$ si no hay tasa) y, debajo, el original en US$. Un
 * ingreso lleva "+"; una devolución, "−" y el tono de crédito. */
export function amountLines(tx: Tx): AmountLines {
  const credit = amountTone(tx) === 'credit'
  const income = tx.kind === 'ingreso'
  const usd = income ? signedUsd : formatUsd
  if (tx.amount_dop_cents === null) {
    return { main: usd(tx.amount_cents), original: 'sin tasa', credit }
  }
  const original =
    tx.gross_cents !== null && tx.gross_cents !== tx.amount_cents
      ? `de ${tx.currency === 'DOP' ? formatDop(tx.gross_cents) : formatUsd(tx.gross_cents)}`
      : tx.currency === 'DOP'
        ? null
        : usd(tx.amount_cents)
  const main = income ? formatSignedDop(-tx.amount_dop_cents) : formatDop(tx.amount_dop_cents)
  return { main, original, credit }
}

/** Clase de color del monto según su tono. */
export const AMOUNT_TONE_CLASS: Record<AmountTone, string | null> = {
  income: 'text-primary',
  credit: 'text-down',
  plain: null,
}

/** De dónde sale el monto, para el detalle. */
export function originText(tx: Tx): string {
  if (tx.currency === 'DOP') return 'Cargado en pesos'
  if (tx.amount_dop_cents === null) return 'Sin tasa del mes: no cuenta en el total en RD$'
  return `${formatUsd(tx.amount_cents)} convertidos a la tasa del mes`
}

/** Insignia de las filas que no son gasto. */
export function kindBadge(tx: Tx): 'Ingreso' | 'Transferencia' | null {
  if (tx.kind === 'ingreso') return 'Ingreso'
  if (tx.kind === 'transferencia') return 'Transferencia'
  return null
}

/** ¿La fila queda fuera de la ventana (aunque sea en parte)? Arriba se descuenta el encabezado
 * fijo del día o grupo (`top`). */
export function outOfView(
  rect: { top: number; bottom: number },
  viewportHeight: number,
  top = 48,
): boolean {
  return rect.top < top || rect.bottom > viewportHeight
}
