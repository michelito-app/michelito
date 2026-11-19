// Textos y tonos del Resumen, calculados a partir de la respuesta de /api/summary.
import type { AccountTotal, CategoryLine, Change, Coverage, MonthTotal, Rate } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { THIRD_PARTY } from './categories'
import { formatDop, formatSignedDop, formatUsd } from './money'
import { longDay, monthName, monthPhrase, shortDay } from './months'

/** Igual que SAME_FLOOR y SAME_SHARE del servidor: "igual" si |dif| < max(RD$ 500, 5 %). */
const SAME_FLOOR_CENTS = 50_000
const SAME_SHARE = 0.05

export type Tone = 'up' | 'down' | 'same' | 'none'

export interface Diff {
  tone: Tone
  text: string
}

/** Diferencia de una categoría contra lo habitual: "+RD$ 7,129", "igual", "nuevo" si antes no
 * había gasto en ella (repetir el monto no dice nada), "—" si el mes no se compara. */
export function categoryDiff(line: CategoryLine): Diff {
  if (line.diff_cents === null) return { tone: 'none', text: '—' }
  if (line.same) return { tone: 'same', text: 'igual' }
  const isNew = line.habitual_cents === 0 && line.diff_cents > 0
  const text = isNew ? 'nuevo' : formatSignedDop(line.diff_cents)
  if (line.diff_cents > 0 && line.one_offs_cents > 0) return { tone: 'up', text: `${text} · único` }
  return { tone: line.diff_cents > 0 ? 'up' : 'down', text }
}

/** Ancho de la barra (0..100) contra la categoría mayor; las devoluciones no la desbordan. */
export function barWidth(amountCents: number, maxCents: number): number {
  if (maxCents <= 0) return 0
  return Math.min(100, Math.max(0, (amountCents / maxCents) * 100))
}

/** Frase de un indicador contra lo habitual del mes. */
export function versusHabitual(amountCents: number, habitualCents: number): Diff {
  const diff = amountCents - habitualCents
  const floor = Math.max(SAME_FLOOR_CENTS, Math.abs(habitualCents) * SAME_SHARE)
  if (Math.abs(diff) < floor) {
    return { tone: 'same', text: `Casi igual a lo habitual (${formatDop(habitualCents)})` }
  }
  const word = diff > 0 ? 'más' : 'menos'
  return { tone: diff > 0 ? 'up' : 'down', text: `${formatDop(Math.abs(diff))} ${word} que lo habitual` }
}

/** "Delivery +RD$ 4,400". */
export function changeTitle(change: Change): string {
  return `${change.category} ${formatSignedDop(change.diff_cents)}`
}

function purchasesText(count: number): string {
  return count === 1 ? '1 compra' : `${count} compras`
}

/** Una frase que explica el cambio: gasto único, número de compras o monto. */
export function changeDetail(change: Change): string {
  if (change.diff_cents > 0 && change.one_offs_cents > 0) {
    return `Incluye ${formatDop(change.one_offs_cents)} marcado como gasto único`
  }
  if (change.purchases === 0) return 'Sin compras este mes'
  const habitual = change.habitual_purchases
  if (habitual !== null && habitual !== change.purchases) {
    return `${purchasesText(change.purchases)}; lo habitual son ${habitual}`
  }
  return `Las mismas compras, por ${change.diff_cents > 0 ? 'más' : 'menos'} dinero`
}

/** "completo", "hasta 13 oct" o "sin datos". */
export function coverageText(coverage: Coverage): string {
  if (coverage.complete) return 'completo'
  return coverage.through ? `hasta ${shortDay(coverage.through)}` : 'sin datos'
}

/** "63.4000" → "63.40"; conserva hasta 4 decimales si los tiene. */
export function rateText(value: string): string {
  return Number(value).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
    useGrouping: false,
  })
}

/** Aviso si la tasa usada es de otro mes: "tasa de agosto". */
export function rateNote(rate: Rate, month: string): string | null {
  return rate.month_used === month ? null : `tasa de ${monthName(rate.month_used)}`
}

const RATE_INPUT = /^\d+(\.\d{1,4})?$/

/** Valida la tasa escrita a mano (acepta coma decimal); null si no sirve. */
export function parseRate(input: string): string | null {
  const value = input.trim().replace(',', '.')
  if (!RATE_INPUT.test(value) || Number(value) <= 0) return null
  return value
}

/** Nota bajo una cuenta en "Por cuenta": moneda y, si hubo dólares, la tasa. */
export function accountNote(account: AccountTotal, rate: Rate | null): string {
  if (account.usd_cents === 0) return 'RD$'
  const usd = formatUsd(account.usd_cents)
  return rate ? `${usd} a ${rateText(rate.value)}` : `${usd} sin tasa: no están en el total`
}

const RANKS = ['el más alto', 'el segundo más alto', 'el tercero más alto']

/** Mes de la barra en `index` (el índice que entrega Recharts al hacer clic), o null. */
export function trendMonthAt(trend: MonthTotal[], index: number | string | undefined): string | null {
  if (index === undefined) return null
  const i = Number(index)
  if (!Number.isInteger(i) || i < 0 || i >= trend.length) return null
  return trend[i].month
}

/** Resumen en texto del gráfico de 12 meses (gastos), para lectores de pantalla. */
export function trendSummary(trend: MonthTotal[], month: string): string {
  if (trend.length === 0) return 'Sin meses para mostrar'
  const first = trend[0].month
  const last = trend[trend.length - 1].month
  const chosen = trend.find((t) => t.month === month)
  if (trend.length === 1) {
    return `Gasto mensual de ${monthPhrase(first)}: ${formatDop(trend[0].total_cents)}`
  }
  const range = `Gasto mensual de ${monthPhrase(first)} a ${monthPhrase(last)}`
  if (!chosen) return range
  const higher = trend.filter((t) => t.total_cents > chosen.total_cents).length
  const lower = trend.filter((t) => t.total_cents < chosen.total_cents).length
  const rank =
    higher > 0 && lower === 0
      ? 'el más bajo'
      : (RANKS[higher] ?? `el ${higher + 1}.º más alto de ${trend.length}`)
  return `${range}; ${monthName(month)}: ${formatDop(chosen.total_cents)}, ${rank}`
}

/** Dónde están los gastos únicos: "En Salud", "En Salud y Viajes", "En 3 categorías". */
export function oneOffsText(lines: CategoryLine[]): string | null {
  const names = lines.filter((l) => l.one_offs_cents > 0).map((l) => l.category)
  if (names.length === 0) return null
  if (names.length > 2) return `En ${names.length} categorías`
  return `En ${names.join(' y ')}`
}

function joinPhrases(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} y ${items[items.length - 1]}`
}

/** Aviso de mes incompleto con hasta dónde llega cada cuenta que no lo cubre. */
export function partialNote(label: string, coverage: Coverage[]): string {
  const missing = coverage
    .filter((c) => !c.complete)
    .map((c) =>
      c.through ? `${c.label} tiene datos hasta el ${longDay(c.through)}` : `${c.label} no tiene datos`,
    )
  const detail = missing.length ? `: ${joinPhrases(missing)}` : ''
  return `${label} está incompleto${detail}. Se compara cuando todas las cuentas cierran el mes.`
}

/** "84 %" de lo que entró quedó; "—" si el mes no tiene ingresos que valgan. */
export function savingsText(rate: number | null): string {
  if (rate === null) return '—'
  const percent = Math.round(rate * 100)
  return percent < 0 ? `−${Math.abs(percent)} %` : `${percent} %`
}

/** "Hasta el 15 ene" cuando una cuenta bancaria corta antes del fin del mes; si no, nada. */
export function incomeThroughNote(incomeThrough: string | null): string | null {
  return incomeThrough === null ? null : `Hasta el ${shortDay(incomeThrough)}`
}

/** Debajo del % ahorrado: qué mide o por qué no se calcula. */
export function savingsNote(rate: number | null, incomeThrough: string | null): string {
  if (incomeThrough !== null) return `Ingresos hasta el ${shortDay(incomeThrough)}: no se calcula`
  if (rate === null) return 'Sin ingresos: no se calcula'
  return 'De lo que entró, lo que quedó'
}

/** Lo que quedó: bueno si no es negativo; en rojo (tono de subida) si se gastó de más. */
export function netTone(netCents: number): 'good' | 'up' {
  return netCents < 0 ? 'up' : 'good'
}

/** Frase bajo "Te quedó". */
export function netDetail(netCents: number, thirdPartyCents = 0): string {
  const sent = thirdPartyCents !== 0
  if (netCents >= 0) return sent ? 'Ingresos menos gastos y transferencias a terceros' : 'Ingresos menos gastos'
  return `${sent ? 'Salió' : 'Gastaste'} ${formatDop(-netCents)} más de lo que entró`
}

/** Transacciones del mes en la categoría de transferencias a terceros (con las cuentas
 * elegidas). `name`: su nombre de hoy (`builtinName`), si el usuario la renombró. */
export function thirdPartyHref(
  month: string,
  selection: Selection = null,
  name: string = THIRD_PARTY,
): string {
  return transactionsHref({ mes: month, categoria: name }, selection)
}

/** «Ver en qué se gastó»: los gastos del mes en Transacciones, agrupados por categoría (con
 * las cuentas elegidas). */
export function spendingHref(month: string, selection: Selection = null): string {
  return transactionsHref({ mes: month, tipo: 'gastos', agrupar: 'categoria' }, selection)
}

/** Nota de "Te quedó" y "% ahorrado" cuando las cuentas elegidas no tienen ingresos. */
export const NO_FLOW_NOTE = 'Elige una cuenta con ingresos para ver el flujo'

/** Cifra de "Te quedó": "—" sin flujo (las cuentas elegidas no tienen ingresos). */
export function netText(netCents: number | null): string {
  return netCents === null ? '—' : formatDop(netCents)
}

/** Lo que salió de las cuentas elegidas hacia otras cuentas tuyas (no se resta de nada):
 * "Pagos a tus tarjetas RD$ 8,000 · Movido a tus otras cuentas RD$ 400"; null si nada. */
export function ownMovesNote(toCardsCents: number, toOwnCents: number): string | null {
  const parts = [
    toCardsCents > 0 ? `Pagos a tus tarjetas ${formatDop(toCardsCents)}` : null,
    toOwnCents > 0 ? `Movido a tus otras cuentas ${formatDop(toOwnCents)}` : null,
  ].filter((p): p is string => p !== null)
  return parts.length ? parts.join(' · ') : null
}

/** Nota de la tarjeta de transferencias a terceros. */
export function thirdPartyNote(thirdPartyCents: number): string {
  return thirdPartyCents === 0 ? 'Ninguna este mes' : 'No es gasto; sí resta de lo que te quedó'
}

/** Cuántas filas muestra cada tarjeta del Resumen antes de "Ver las N". */
export const CATEGORY_LIMIT = 8
export const REVIEW_LIMIT = 4
export const ACCOUNT_LIMIT = 4

export interface Split<T> {
  shown: T[]
  rest: T[]
}

/** Las primeras `limit` filas y el resto; con "todo" abierto, todo va en `shown`. */
export function splitTop<T>(items: readonly T[], limit: number, all = false): Split<T> {
  if (all || items.length <= limit) return { shown: [...items], rest: [] }
  return { shown: items.slice(0, limit), rest: items.slice(limit) }
}

/** Las cuentas con más movimiento primero (gasto del mes en RD$). */
export function byMovement(accounts: readonly AccountTotal[]): AccountTotal[] {
  return [...accounts].sort((a, b) => b.total_cents - a.total_cents)
}

/** Ingresos del mes elegido en el gráfico, para lectores de pantalla. */
export function trendIncomeNote(trend: MonthTotal[], month: string): string | null {
  const chosen = trend.find((t) => t.month === month)
  if (!chosen) return null
  if (chosen.income_cents <= 0) return `Sin ingresos en ${monthName(month)}`
  return `Ingresos de ${monthName(month)}: ${formatDop(chosen.income_cents)}`
}
