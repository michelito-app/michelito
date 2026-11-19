// Meses atípicos y "Qué pasó" (lógica pura). La regla vive en el servidor
// (src/finanzas/analysis/anomalies.py); aquí solo se arman los textos y enlaces.
import type { Contribution, Direction, MonthTotal } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { formatDop, formatSignedDop } from './money'
import { monthPhrase } from './months'

export interface Flag {
  side: 'gasto' | 'ingreso'
  direction: Direction
}

/** Marcas del mes: primero el gasto, luego los ingresos. */
export function monthFlags(point: MonthTotal): Flag[] {
  const flags: Flag[] = []
  if (point.spent_flag) flags.push({ side: 'gasto', direction: point.spent_flag })
  if (point.income_flag) flags.push({ side: 'ingreso', direction: point.income_flag })
  return flags
}

function flagWords(flag: Flag): string {
  if (flag.side === 'gasto') return flag.direction === 'up' ? 'gasto alto' : 'gasto bajo'
  return flag.direction === 'up' ? 'ingresos altos' : 'ingresos bajos'
}

/** "gasto alto y ingresos bajos"; null si el mes no es atípico. */
export function flagText(point: MonthTotal): string | null {
  const words = monthFlags(point).map(flagWords)
  return words.length ? words.join(' y ') : null
}

/** "Meses atípicos: julio 2026 (gasto alto)"; null si no hay ninguno. */
export function atypicalNote(trend: MonthTotal[]): string | null {
  const parts = trend.flatMap((t) => {
    const text = flagText(t)
    return text ? [`${monthPhrase(t.month)} (${text})`] : []
  })
  return parts.length ? `Meses atípicos: ${parts.join(', ')}` : null
}

/** Frase del mes atípico para el encabezado de "Qué pasó":
 * "Gastos de RD$ 40,000; lo habitual es RD$ 10,000". */
export function flagSentence(point: MonthTotal, flag: Flag): string {
  const spent = flag.side === 'gasto'
  const amount = spent ? point.total_cents : point.income_cents
  const habitual = spent ? point.spent_habitual_cents : point.income_habitual_cents
  const what = spent ? 'Gastos' : 'Ingresos'
  const tail = habitual === null ? '' : `; lo habitual es ${formatDop(habitual)}`
  const word = flag.direction === 'up' ? 'más altos' : 'más bajos'
  return `${what} ${word} que lo habitual: ${formatDop(amount)}${tail}`
}

/** "+RD$ 30,000 frente a lo habitual". */
export function contributionDiff(item: Contribution): string {
  return `${formatSignedDop(item.diff_cents)} frente a lo habitual`
}

/** Una línea de detalle: cuánto fue en el mes y cuánto suele ser; "no apareció" si falta. */
export function contributionDetail(item: Contribution): string {
  const category = item.category ? `${item.category} · ` : ''
  if (item.count === 0) {
    return `${category}No apareció este mes (suele ser ${formatDop(item.habitual_cents)})`
  }
  const times = item.count === 1 ? '' : ` en ${item.count} movimientos`
  return `${category}${formatDop(item.amount_cents)}${times} · suele ser ${formatDop(item.habitual_cents)}`
}

/** El movimiento mayor en Transacciones; si no apareció, la búsqueda del comercio en el mes. */
export function contributionHref(item: Contribution, month: string, selection: Selection): string {
  if (item.fingerprint) return transactionsHref({ mes: month, tx: item.fingerprint }, selection)
  return transactionsHref({ mes: month, q: item.merchant }, selection)
}

/** Umbrales de mes atípico: los mismos ANOMALY_SHARE y ANOMALY_FLOOR del servidor
 * (analysis/anomalies.py), que decide las marcas; tests/test_anomalies.py comprueba que coinciden. */
export const ATYPICAL_SHARE = 0.3
export const ATYPICAL_FLOOR_CENTS = 1_000_000

/** Leyenda del gráfico de 12 meses, bajo las barras. */
export const ATYPICAL_LEGEND =
  `meses atípicos: se apartan más de ${Math.round(ATYPICAL_SHARE * 100)}% ` +
  `(y ${formatDop(ATYPICAL_FLOOR_CENTS)}) de lo habitual`

export interface FlagMark extends Flag {
  /** "▲" si subió, "▼" si bajó. */
  glyph: '▲' | '▼'
  /** "gasto alto", "ingresos bajos"… */
  words: string
  /** El gasto alto o los ingresos bajos son la parte mala del mes (van en terracota). */
  worse: boolean
}

/** Marcas que van sobre las barras de un mes atípico (primero el gasto). */
export function flagMarks(point: MonthTotal): FlagMark[] {
  return monthFlags(point).map((flag) => ({
    ...flag,
    glyph: flag.direction === 'up' ? '▲' : '▼',
    words: flagWords(flag),
    worse: (flag.side === 'gasto') === (flag.direction === 'up'),
  }))
}

/** "+45%" o "−30%" de `amount` frente a `habitual`; null si no hay con qué comparar. */
export function deviationPercent(amount: number, habitual: number | null): string | null {
  if (habitual === null || habitual <= 0) return null
  const pct = Math.round(((amount - habitual) / habitual) * 100)
  if (pct === 0) return '0%'
  return `${pct > 0 ? '+' : '−'}${Math.abs(pct)}%`
}

/** Línea del tooltip de un mes atípico: "Gasto RD$ 40,000 · +45% vs lo habitual". */
export function flagDeviation(point: MonthTotal, flag: Flag): string {
  const spent = flag.side === 'gasto'
  const amount = spent ? point.total_cents : point.income_cents
  const habitual = spent ? point.spent_habitual_cents : point.income_habitual_cents
  const what = `${spent ? 'Gasto' : 'Ingresos'} ${formatDop(amount)}`
  const pct = deviationPercent(amount, habitual)
  return pct === null ? what : `${what} · ${pct} vs lo habitual`
}

/** ¿Algún mes del gráfico es atípico? */
export function hasAtypical(trend: MonthTotal[]): boolean {
  return trend.some((t) => monthFlags(t).length > 0)
}

/** ¿Hay algo que contar en "Qué pasó"? (un mes atípico con comercios de ese lado). */
export function hasWhatHappened(point: MonthTotal | undefined, items: Contribution[]): boolean {
  if (!point) return false
  return monthFlags(point).some((flag) => items.some((item) => item.side === flag.side))
}
